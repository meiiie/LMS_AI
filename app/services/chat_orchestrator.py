"""
Chat Orchestrator - Pipeline Orchestration for Chat Processing

Extracted from chat_service.py as part of Clean Architecture refactoring.
Orchestrates the complete chat processing pipeline.

**Pattern:** Orchestrator / Pipeline
**Spec:** CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID, uuid4

from app.core.config import settings
from app.models.schemas import ChatRequest, InternalChatResponse, Source, UserRole

from .session_manager import SessionContext, SessionManager, get_session_manager
from .input_processor import InputProcessor, ChatContext, get_input_processor
from .output_processor import OutputProcessor, ProcessingResult, get_output_processor
from .background_tasks import BackgroundTaskRunner, get_background_runner

logger = logging.getLogger(__name__)


# =============================================================================
# AGENT TYPE ENUM (for backward compatibility)
# =============================================================================

class AgentType(str, Enum):
    """Types of agents in the system."""
    CHAT = "chat"
    RAG = "rag"
    TUTOR = "tutor"


# =============================================================================
# CHAT ORCHESTRATOR
# =============================================================================

class ChatOrchestrator:
    """
    Orchestrates the chat processing pipeline.
    
    Pipeline stages:
    1. Input validation (Guardian/Guardrails)
    2. Context retrieval (Memory, History, Insights)
    3. Agent processing (UnifiedAgent/MultiAgent)
    4. Output validation & formatting
    5. Background tasks (Memory, Profile)
    
    **Pattern:** Orchestrator with Single Responsibility stages
    """
    
    def __init__(
        self,
        session_manager: Optional[SessionManager] = None,
        input_processor: Optional[InputProcessor] = None,
        output_processor: Optional[OutputProcessor] = None,
        background_runner: Optional[BackgroundTaskRunner] = None,
        unified_agent=None,
        multi_agent_graph=None,
        rag_agent=None,
        semantic_memory=None,
        chat_history=None,
        prompt_loader=None,
        guardrails=None
    ):
        """
        Initialize orchestrator with all dependencies.
        
        Dependencies are lazily initialized if not provided.
        """
        # Core processors
        self._session_manager = session_manager or get_session_manager()
        self._input_processor = input_processor or get_input_processor()
        self._output_processor = output_processor or get_output_processor()
        self._background_runner = background_runner or get_background_runner()
        
        # Agents
        self._unified_agent = unified_agent
        self._multi_agent_graph = multi_agent_graph
        self._rag_agent = rag_agent
        
        # Dependencies for context building
        self._semantic_memory = semantic_memory
        self._chat_history = chat_history
        self._prompt_loader = prompt_loader
        self._guardrails = guardrails
        
        # Configuration flags
        self._use_unified_agent = getattr(settings, 'use_unified_agent', True)
        self._use_multi_agent = getattr(settings, 'use_multi_agent', False)
        
        logger.info("ChatOrchestrator initialized")
    
    async def process(
        self,
        request: ChatRequest,
        background_save: Optional[Callable] = None
    ) -> InternalChatResponse:
        """
        Process a chat request through the full pipeline.
        
        Pipeline:
        1. Get/create session
        2. Validate input
        3. Build context
        4. Process with agent
        5. Format output
        6. Schedule background tasks
        
        Args:
            request: ChatRequest from API
            background_save: FastAPI BackgroundTasks.add_task
            
        Returns:
            InternalChatResponse ready for API serialization
        """
        user_id = str(request.user_id)
        message = request.message
        user_role = request.role
        
        # Handle thread_id "new" as None
        thread_id = request.thread_id
        if thread_id and thread_id.lower() == "new":
            thread_id = None
        
        # ================================================================
        # STAGE 1: SESSION MANAGEMENT
        # ================================================================
        session = self._session_manager.get_or_create_session(user_id, thread_id)
        session_id = session.session_id
        
        logger.info(f"Processing request for user {user_id} with role: {user_role.value}")
        
        # ================================================================
        # STAGE 2: INPUT VALIDATION
        # ================================================================
        validation = await self._input_processor.validate(
            request=request,
            session_id=session_id,
            create_blocked_response=self._output_processor.create_blocked_response
        )
        
        if validation.blocked:
            return validation.blocked_response
        
        # Save user message to history
        if self._chat_history and self._chat_history.is_available() and background_save:
            background_save(
                self._chat_history.save_message,
                session_id, "user", message
            )
        
        # ================================================================
        # STAGE 3: CONTEXT BUILDING
        # ================================================================
        context = await self._input_processor.build_context(
            request=request,
            session_id=session_id,
            user_name=session.user_name
        )
        
        # Update session with extracted user name
        if not session.user_name:
            extracted_name = self._input_processor.extract_user_name(message)
            if extracted_name:
                self._session_manager.update_user_name(session_id, extracted_name)
                context.user_name = extracted_name
        
        # Pronoun detection and validation
        from app.prompts.prompt_loader import detect_pronoun_style
        detected_pronoun = detect_pronoun_style(message)
        if detected_pronoun:
            session.state.update_pronoun_style(detected_pronoun)
        
        # Custom pronoun validation with Guardian
        custom_pronoun = await self._input_processor.validate_pronoun_request(
            message=message,
            current_style=session.state.pronoun_style
        )
        if custom_pronoun:
            session.state.update_pronoun_style(custom_pronoun)
        
        # ================================================================
        # STAGE 4: AGENT PROCESSING
        # ================================================================
        
        # Option A: Multi-Agent System (SOTA 2025)
        if self._use_multi_agent and self._multi_agent_graph is not None:
            result = await self._process_with_multi_agent(context, session)
        
        # Option B: UnifiedAgent (ReAct Pattern) - Default
        elif self._unified_agent is not None:
            result = await self._process_with_unified_agent(context, session)
        
        # Option C: Error - No agent available
        else:
            logger.error("[ERROR] UnifiedAgent not available - cannot process message")
            raise RuntimeError(
                "UnifiedAgent is required but not available. "
                "Please check GOOGLE_API_KEY configuration."
            )
        
        # ================================================================
        # STAGE 5: OUTPUT FORMATTING
        # ================================================================
        response = await self._output_processor.validate_and_format(
            result=result,
            session_id=session_id,
            user_name=context.user_name,
            user_role=user_role
        )
        
        # ================================================================
        # STAGE 6: POST-PROCESSING & BACKGROUND TASKS
        # ================================================================
        
        # Update session state
        used_name = context.user_name and context.user_name.lower() in result.message.lower() if context.user_name else False
        opening = result.message[:50].strip() if result.message else None
        self._session_manager.update_state(
            session_id=session_id,
            phrase=opening,
            used_name=used_name
        )
        
        # Save AI response
        if self._chat_history and self._chat_history.is_available() and background_save:
            background_save(
                self._chat_history.save_message,
                session_id, "assistant", result.message
            )
        
        # Schedule background tasks
        if background_save and self._background_runner:
            self._background_runner.schedule_all(
                background_save=background_save,
                user_id=user_id,
                session_id=session_id,
                message=message,
                response=result.message
            )
        
        return response
    
    async def _process_with_unified_agent(
        self,
        context: ChatContext,
        session: SessionContext
    ) -> ProcessingResult:
        """
        Process with UnifiedAgent (ReAct Pattern).
        
        CHỈ THỊ KỸ THUẬT SỐ 13: LLM-driven orchestration
        """
        logger.info("[UNIFIED AGENT] Processing with LLM-driven orchestration (ReAct)")
        
        # Clear previous sources
        from app.engine.unified_agent import clear_retrieved_sources, get_last_retrieved_sources
        clear_retrieved_sources()
        
        # Process with UnifiedAgent
        unified_result = await self._unified_agent.process(
            message=context.message,
            user_id=context.user_id,
            session_id=str(context.session_id),
            conversation_history=context.history_list,
            user_role=context.user_role.value,
            user_name=context.user_name,
            user_facts=context.user_facts,
            conversation_summary=context.conversation_summary,
            recent_phrases=session.state.recent_phrases,
            is_follow_up=not session.state.is_first_message,
            name_usage_count=session.state.name_usage_count,
            total_responses=session.state.total_responses,
            pronoun_style=session.state.pronoun_style,
            conversation_context=context.conversation_analysis
        )
        
        # Get sources from tool_maritime_search
        retrieved_sources = get_last_retrieved_sources()
        sources_list = None
        if retrieved_sources:
            sources_list = self._output_processor.format_sources(retrieved_sources)
            logger.info(f"[UNIFIED AGENT] Retrieved {len(sources_list)} sources")
        
        return ProcessingResult(
            message=unified_result.get("content", ""),
            agent_type=AgentType.RAG if sources_list else AgentType.CHAT,
            sources=sources_list,
            metadata={
                "unified_agent": True,
                "tools_used": unified_result.get("tools_used", []),
                "iterations": unified_result.get("iterations", 1)
            }
        )
    
    async def _process_with_multi_agent(
        self,
        context: ChatContext,
        session: SessionContext
    ) -> ProcessingResult:
        """
        Process with Multi-Agent System (LangGraph).
        
        Phase 8: SOTA 2025 - Supervisor Agent
        """
        logger.info("[MULTI-AGENT] Processing with Multi-Agent System (SOTA 2025)")
        
        from app.engine.multi_agent.graph import process_with_multi_agent
        
        # Build context for multi-agent
        multi_agent_context = {
            "user_name": context.user_name,
            "user_role": context.user_role.value,
            "lms_course": context.lms_course_name,
            "lms_module": context.lms_module_id,
            "conversation_history": context.conversation_history,
            "semantic_context": context.semantic_context
        }
        
        result = await process_with_multi_agent(
            query=context.message,
            user_id=context.user_id,
            session_id=str(context.session_id),
            context=multi_agent_context
        )
        
        response_text = result.get("response", "")
        sources = result.get("sources", [])
        
        # Convert sources to Source objects
        source_objects = []
        for s in sources:
            source_objects.append(Source(
                node_id=s.get("node_id", ""),
                title=s.get("title", ""),
                source_type="knowledge_graph",
                content_snippet=s.get("content", "")[:200],
                image_url=s.get("image_url")
            ))
        
        # Extract tools_used from Multi-Agent result (SOTA: API transparency)
        tools_used = result.get("agent_outputs", {}).get("tutor_tools_used", [])
        if not tools_used:
            # Fallback: check top-level tools_used
            tools_used = result.get("tools_used", [])
        
        return ProcessingResult(
            message=response_text,
            agent_type=AgentType.RAG,
            sources=source_objects if source_objects else None,
            metadata={
                "multi_agent": True,
                "grader_score": result.get("grader_score", 0),
                "tools_used": tools_used  # SOTA: Track tool usage
            }
        )


# =============================================================================
# SINGLETON
# =============================================================================

_chat_orchestrator: Optional[ChatOrchestrator] = None


def get_chat_orchestrator() -> ChatOrchestrator:
    """Get or create ChatOrchestrator singleton."""
    global _chat_orchestrator
    if _chat_orchestrator is None:
        _chat_orchestrator = ChatOrchestrator()
    return _chat_orchestrator


def init_chat_orchestrator(
    session_manager=None,
    input_processor=None,
    output_processor=None,
    background_runner=None,
    unified_agent=None,
    multi_agent_graph=None,
    rag_agent=None,
    semantic_memory=None,
    chat_history=None,
    prompt_loader=None,
    guardrails=None
) -> ChatOrchestrator:
    """Initialize ChatOrchestrator with all dependencies."""
    global _chat_orchestrator
    _chat_orchestrator = ChatOrchestrator(
        session_manager=session_manager,
        input_processor=input_processor,
        output_processor=output_processor,
        background_runner=background_runner,
        unified_agent=unified_agent,
        multi_agent_graph=multi_agent_graph,
        rag_agent=rag_agent,
        semantic_memory=semantic_memory,
        chat_history=chat_history,
        prompt_loader=prompt_loader,
        guardrails=guardrails
    )
    return _chat_orchestrator
