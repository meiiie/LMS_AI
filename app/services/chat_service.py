"""
Chat Service - Integration layer for all components.

This service wires together:
- Unified Agent (CHỈ THỊ SỐ 13) - LLM-driven orchestration (ReAct pattern)
- OR Legacy: Agent Orchestrator (LangGraph) with IntentClassifier
- Semantic Memory Engine v0.3 (pgvector + Gemini embeddings)
- Knowledge Graph (Neo4j GraphRAG)
- Guardrails
- Learning Profile
- Chat History

**Feature: maritime-ai-tutor**
**Validates: Requirements 1.1, 2.1, 2.2, 2.3**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 06 - Semantic Memory v0.3**
**Spec: CHỈ THỊ KỸ THUẬT SỐ 13 - Unified Agent (Tool-Use Architecture)**
"""

import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional
from uuid import UUID, uuid4

from app.core.config import settings
from app.engine.agents.chat_agent import ChatAgent
from app.engine.graph import AgentOrchestrator, AgentType, IntentType
from app.engine.guardrails import Guardrails, ValidationStatus
from app.engine.tools.rag_tool import RAGAgent, get_knowledge_repository
from app.engine.tools.tutor_agent import TutorAgent
from app.models.learning_profile import LearningProfile
from app.models.schemas import ChatRequest, InternalChatResponse, Source, UserRole
from app.repositories.learning_profile_repository import (
    InMemoryLearningProfileRepository,
    get_learning_profile_repository
)
from app.repositories.chat_history_repository import (
    ChatHistoryRepository, 
    get_chat_history_repository
)

# Semantic Memory v0.3 (CHỈ THỊ KỸ THUẬT SỐ 06)
try:
    from app.engine.semantic_memory import SemanticMemoryEngine, get_semantic_memory_engine
    SEMANTIC_MEMORY_AVAILABLE = True
except ImportError:
    SEMANTIC_MEMORY_AVAILABLE = False

# Unified Agent (CHỈ THỊ KỸ THUẬT SỐ 13)
try:
    from app.engine.unified_agent import (
        UnifiedAgent, 
        get_unified_agent,
        get_last_retrieved_sources,
        clear_retrieved_sources
    )
    UNIFIED_AGENT_AVAILABLE = True
except ImportError:
    UNIFIED_AGENT_AVAILABLE = False
    # Fallback functions
    def get_last_retrieved_sources():
        return []
    def clear_retrieved_sources():
        pass

# CHỈ THỊ KỸ THUẬT SỐ 16 & 17: Humanization - PromptLoader & MemorySummarizer
try:
    from app.prompts import get_prompt_loader
    PROMPT_LOADER_AVAILABLE = True
except ImportError:
    PROMPT_LOADER_AVAILABLE = False
    def get_prompt_loader():
        return None

try:
    from app.engine.memory_summarizer import get_memory_summarizer
    MEMORY_SUMMARIZER_AVAILABLE = True
except ImportError:
    MEMORY_SUMMARIZER_AVAILABLE = False
    def get_memory_summarizer():
        return None

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing a chat request."""
    message: str
    agent_type: AgentType
    sources: Optional[List[Source]] = None
    blocked: bool = False
    metadata: dict = None


class ChatService:
    """
    Main service that integrates all components.
    
    **Validates: Requirements 1.1, 2.1, 2.2, 2.3**
    """
    
    def __init__(self):
        """Initialize all components."""
        # Core components (Semantic Memory v0.3 is primary - no legacy fallback)
        self._knowledge_graph = get_knowledge_repository()  # Use Neo4j if available
        self._profile_repo = InMemoryLearningProfileRepository()  # Legacy
        self._supabase_profile_repo = get_learning_profile_repository()  # CHỈ THỊ SỐ 04
        self._guardrails = Guardrails()
        
        # Memory Lite - Chat History (Week 2)
        self._chat_history = get_chat_history_repository()
        if self._chat_history.is_available():
            self._chat_history.ensure_tables()
            logger.info("Memory Lite (Chat History) initialized")
        
        # Semantic Memory v0.3 (CHỈ THỊ KỸ THUẬT SỐ 06)
        self._semantic_memory: Optional[SemanticMemoryEngine] = None
        if SEMANTIC_MEMORY_AVAILABLE and settings.semantic_memory_enabled:
            try:
                self._semantic_memory = get_semantic_memory_engine()
                if self._semantic_memory.is_available():
                    logger.info("Semantic Memory v0.3 initialized (pgvector + Gemini embeddings)")
                else:
                    logger.warning("Semantic Memory v0.3 not available, falling back to sliding window")
                    self._semantic_memory = None
            except Exception as e:
                logger.warning(f"Failed to initialize Semantic Memory: {e}")
                self._semantic_memory = None
        
        # Agents (Legacy - kept for backward compatibility)
        self._orchestrator = AgentOrchestrator()
        self._chat_agent = ChatAgent()  # No legacy memory, uses Semantic Memory v0.3
        self._rag_agent = RAGAgent(knowledge_graph=self._knowledge_graph)
        self._tutor_agent = TutorAgent()
        
        # Unified Agent (CHỈ THỊ KỸ THUẬT SỐ 13)
        # This replaces IntentClassifier with LLM-driven orchestration
        self._unified_agent: Optional[UnifiedAgent] = None
        self._use_unified_agent = getattr(settings, 'use_unified_agent', True)  # Default: ON
        
        if UNIFIED_AGENT_AVAILABLE and self._use_unified_agent:
            try:
                self._unified_agent = UnifiedAgent(
                    rag_agent=self._rag_agent,
                    semantic_memory=self._semantic_memory,
                    chat_history=self._chat_history
                )
                if self._unified_agent.is_available():
                    logger.info("✅ Unified Agent (CHỈ THỊ SỐ 13) initialized - LLM-driven orchestration ENABLED")
                else:
                    logger.warning("Unified Agent not available, falling back to legacy IntentClassifier")
                    self._unified_agent = None
            except Exception as e:
                logger.warning(f"Failed to initialize Unified Agent: {e}")
                self._unified_agent = None
        
        # CHỈ THỊ KỸ THUẬT SỐ 16 & 17: Humanization Components
        self._prompt_loader = None
        self._memory_summarizer = None
        
        if PROMPT_LOADER_AVAILABLE:
            try:
                self._prompt_loader = get_prompt_loader()
                logger.info("✅ PromptLoader (CHỈ THỊ SỐ 16) initialized - YAML Persona Config ENABLED")
            except Exception as e:
                logger.warning(f"Failed to initialize PromptLoader: {e}")
        
        if MEMORY_SUMMARIZER_AVAILABLE:
            try:
                self._memory_summarizer = get_memory_summarizer()
                if self._memory_summarizer.is_available():
                    logger.info("✅ MemorySummarizer (CHỈ THỊ SỐ 16) initialized - Tiered Memory ENABLED")
                else:
                    logger.warning("MemorySummarizer not available (no LLM)")
                    self._memory_summarizer = None
            except Exception as e:
                logger.warning(f"Failed to initialize MemorySummarizer: {e}")
        
        logger.info(f"Knowledge graph available: {self._knowledge_graph.is_available()}")
        logger.info(f"Chat history available: {self._chat_history.is_available()}")
        logger.info(f"Learning profile (Supabase) available: {self._supabase_profile_repo.is_available()}")
        logger.info(f"PromptLoader available: {self._prompt_loader is not None}")
        logger.info(f"MemorySummarizer available: {self._memory_summarizer is not None}")
        logger.info(f"Semantic memory v0.3 available: {self._semantic_memory is not None}")
        logger.info(f"Unified Agent (ReAct) available: {self._unified_agent is not None}")
        
        # Session tracking (in-memory fallback)
        self._sessions: dict[str, UUID] = {}  # user_id -> session_id
        
        logger.info("ChatService initialized with all components")
    
    async def process_message(
        self,
        request: ChatRequest,
        background_save: Optional[Callable] = None
    ) -> InternalChatResponse:
        """
        Process a chat message through the full pipeline.
        
        Pipeline:
        1. Input validation (Guardrails)
        2. Get/create session and retrieve history (Memory Lite)
        3. Save user message to history
        4. Intent classification (Orchestrator)
        5. Role-Based Prompting (student=Tutor, teacher/admin=Assistant)
        6. Agent routing and processing (with history context)
        7. Save AI response to history
        8. Output validation (Guardrails)
        9. Response generation
        
        **Validates: Requirements 1.1, 2.1, 2.2, 2.3, 7.1, 7.2**
        **Feature: Week 2 - Memory Lite**
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 03 - Role-Based Prompting**
        """
        user_id = str(request.user_id)
        message = request.message
        user_role = request.role  # student | teacher | admin
        
        # Step 1: Input validation
        input_result = await self._guardrails.validate_input(message)
        if not input_result.is_valid:
            logger.warning(f"Input blocked for user {user_id}: {input_result.issues}")
            return self._create_blocked_response(input_result.issues)
        
        # Log role for debugging
        logger.info(f"Processing request for user {user_id} with role: {user_role.value}")
        
        # Step 2: Get or create session (Memory Lite)
        session_id = self._get_or_create_session(user_id)
        
        # Step 3: Fetch learning profile (CHỈ THỊ SỐ 04)
        learning_profile = None
        if self._supabase_profile_repo.is_available():
            learning_profile = await self._supabase_profile_repo.get_or_create(user_id)
            if learning_profile:
                logger.debug(f"Loaded learning profile for user {user_id}: {learning_profile.get('attributes', {})}")
        
        # Step 4: Retrieve conversation history (Hybrid: Semantic + Sliding Window)
        conversation_history = ""
        semantic_context = ""
        user_name = None
        
        # Try Semantic Memory v0.3 first (CHỈ THỊ KỸ THUẬT SỐ 06)
        if self._semantic_memory is not None:
            try:
                context = await self._semantic_memory.retrieve_context(
                    user_id=user_id,
                    query=message,
                    search_limit=5,
                    similarity_threshold=0.7,
                    include_user_facts=True
                )
                semantic_context = context.to_prompt_context()
                logger.debug(f"Semantic context retrieved: {len(context.relevant_memories)} memories, {len(context.user_facts)} facts")
            except Exception as e:
                logger.warning(f"Semantic memory retrieval failed: {e}")
        
        # Fallback/Hybrid: Also get sliding window history
        if self._chat_history.is_available():
            # Get recent messages
            recent_messages = self._chat_history.get_recent_messages(session_id)
            conversation_history = self._chat_history.format_history_for_prompt(recent_messages)
            
            # Get user name if stored
            user_name = self._chat_history.get_user_name(session_id)
            
            # Save user message (use background task if provided)
            if background_save:
                background_save(self._save_message_async, session_id, "user", message)
            else:
                self._chat_history.save_message(session_id, "user", message)
            
            # Try to extract user name from message
            extracted_name = self._extract_user_name(message)
            if extracted_name and not user_name:
                self._chat_history.update_user_name(session_id, extracted_name)
                user_name = extracted_name
        
        # CHỈ THỊ KỸ THUẬT SỐ 12: Debug Logging để truy vết Memory
        logger.info(f"--- PREPARING PROMPT FOR USER {user_id} ---")
        logger.info(f"Detected Name: {user_name or 'UNKNOWN'}")
        logger.info(f"Retrieved History Length: {len(conversation_history)} chars")
        logger.info(f"Semantic Context Length: {len(semantic_context)} chars")
        logger.info("-------------------------------------------")
        
        # Combine semantic context with conversation history
        if semantic_context:
            conversation_history = f"{semantic_context}\n\n{conversation_history}".strip()
        
        # ================================================================
        # CHỈ THỊ KỸ THUẬT SỐ 13: UNIFIED AGENT (LLM-driven Orchestration)
        # Thay vì dùng IntentClassifier cứng nhắc, để Gemini tự quyết định
        # ================================================================
        if self._unified_agent is not None:
            logger.info("[UNIFIED AGENT] Processing with LLM-driven orchestration (ReAct)")
            
            # CHỈ THỊ KỸ THUẬT SỐ 16: Clear sources trước mỗi request
            clear_retrieved_sources()
            
            # Build conversation history as list for UnifiedAgent
            history_list = []
            if self._chat_history.is_available():
                recent_messages = self._chat_history.get_recent_messages(session_id)
                for msg in recent_messages:
                    history_list.append({
                        "role": msg.role,
                        "content": msg.content
                    })
            
            # CHỈ THỊ SỐ 16: Get user facts from semantic memory for personalization
            user_facts = []
            if self._semantic_memory is not None:
                try:
                    context = await self._semantic_memory.retrieve_context(
                        user_id=user_id,
                        query=message,
                        include_user_facts=True
                    )
                    user_facts = context.user_facts if context.user_facts else []
                except Exception as e:
                    logger.warning(f"Failed to get user facts: {e}")
            
            # CHỈ THỊ SỐ 17: Get conversation summary from MemorySummarizer
            conversation_summary = None
            if self._memory_summarizer is not None:
                try:
                    conversation_summary = await self._memory_summarizer.get_summary_async(str(session_id))
                except Exception as e:
                    logger.warning(f"Failed to get conversation summary: {e}")
            
            # Process with UnifiedAgent (CHỈ THỊ SỐ 16: Pass user_name for {{user_name}} replacement)
            unified_result = await self._unified_agent.process(
                message=message,
                user_id=user_id,
                session_id=str(session_id),
                conversation_history=history_list,
                user_role=user_role.value,
                user_name=user_name,  # CHỈ THỊ SỐ 16: Thay thế {{user_name}} trong YAML
                user_facts=user_facts,  # CHỈ THỊ SỐ 16: Facts từ Semantic Memory
                conversation_summary=conversation_summary  # CHỈ THỊ SỐ 17: Summary từ MemorySummarizer
            )
            
            # CHỈ THỊ KỸ THUẬT SỐ 16: Lấy sources từ tool_maritime_search
            retrieved_sources = get_last_retrieved_sources()
            sources_list = None
            if retrieved_sources:
                sources_list = [
                    Source(
                        node_id=s.get("node_id", ""),
                        title=s.get("title", ""),
                        source_type="knowledge_graph",
                        content_snippet=s.get("content", "")[:200]  # Truncate for API
                    )
                    for s in retrieved_sources
                ]
                logger.info(f"[UNIFIED AGENT] Retrieved {len(sources_list)} sources for API response")
            
            # Convert to ProcessingResult
            result = ProcessingResult(
                message=unified_result.get("content", ""),
                agent_type=AgentType.RAG if sources_list else AgentType.CHAT,
                sources=sources_list,
                metadata={
                    "unified_agent": True,
                    "tools_used": unified_result.get("tools_used", []),
                    "iterations": unified_result.get("iterations", 1)
                }
            )
            
            logger.info(f"[UNIFIED AGENT] Tools used: {unified_result.get('tools_used', [])}")
        
        else:
            # ================================================================
            # LEGACY: Rule-based IntentClassifier (fallback)
            # ================================================================
            logger.info("[LEGACY] Processing with IntentClassifier (rule-based)")
            
            # Step 5: Process through orchestrator
            orchestrator_response = self._orchestrator.process_message(
                message=message,
                session_id=str(session_id),
                user_id=user_id
            )
            
            # Step 6: Handle clarification request
            if orchestrator_response.requires_clarification:
                return self._create_clarification_response(orchestrator_response.content)
            
            # Step 7: Route to appropriate agent (with history context + role-based prompting + learning profile)
            result = await self._route_to_agent(
                agent_type=orchestrator_response.agent_type,
                message=message,
                user_id=user_id,
                session_id=str(session_id),
                conversation_history=conversation_history,
                user_name=user_name,
                user_role=user_role,  # Pass role for role-based prompting
                learning_profile=learning_profile  # CHỈ THỊ SỐ 04
            )
        
        # Step 8: Save AI response to history (use background task if provided)
        if self._chat_history.is_available():
            if background_save:
                # Use BackgroundTasks to save without blocking response
                background_save(self._save_message_async, session_id, "assistant", result.message)
            else:
                self._chat_history.save_message(session_id, "assistant", result.message)
        
        # Step 8.5: Store interaction in Semantic Memory v0.3 (background)
        if self._semantic_memory is not None and background_save:
            background_save(
                self._store_semantic_interaction_async,
                user_id, message, result.message, str(session_id)
            )
        
        # Step 8.6: CHỈ THỊ SỐ 17 - Summarize memory if needed (background)
        if self._memory_summarizer is not None and background_save:
            background_save(
                self._summarize_memory_async,
                str(session_id), message, result.message
            )
        
        # Step 9: Update learning profile stats (background)
        if self._supabase_profile_repo.is_available() and background_save:
            background_save(self._update_profile_stats_async, user_id)
        
        # Step 10: Output validation
        output_result = await self._guardrails.validate_output(result.message)
        if output_result.status == ValidationStatus.FLAGGED:
            result.message += "\n\n_Note: Please verify safety-critical information with official sources._"
        
        # Step 11: Create response (InternalChatResponse for API layer to convert)
        # Build metadata based on whether UnifiedAgent or Legacy was used
        response_metadata = {
            "session_id": str(session_id),
            "user_name": user_name,
            "user_role": user_role.value,
            "history_available": self._chat_history.is_available(),
            **(result.metadata or {})
        }
        
        # Add intent info only if using legacy orchestrator
        if self._unified_agent is None:
            response_metadata["intent"] = orchestrator_response.intent.type.value
            response_metadata["confidence"] = orchestrator_response.intent.confidence
        
        return InternalChatResponse(
            response_id=uuid4(),
            message=result.message,
            agent_type=result.agent_type,
            sources=result.sources,
            metadata=response_metadata
        )

    
    async def _route_to_agent(
        self,
        agent_type: AgentType,
        message: str,
        user_id: str,
        session_id: str,
        conversation_history: str = "",
        user_name: Optional[str] = None,
        user_role: UserRole = UserRole.STUDENT,
        learning_profile: Optional[dict] = None
    ) -> ProcessingResult:
        """
        Route message to appropriate agent with conversation context.
        
        Role-Based Prompting (CHỈ THỊ KỸ THUẬT SỐ 03):
        - student: AI đóng vai Gia sư (Tutor) - giọng văn khuyến khích, giải thích cặn kẽ
        - teacher/admin: AI đóng vai Trợ lý (Assistant) - chuyên nghiệp, ngắn gọn
        """
        
        if agent_type == AgentType.RAG:
            return await self._process_with_rag(message, user_id, conversation_history, user_role)
        
        elif agent_type == AgentType.TUTOR:
            return await self._process_with_tutor(message, user_id, session_id)
        
        else:  # CHAT
            return await self._process_with_chat(message, user_id, conversation_history, user_name, user_role)
    
    async def _process_with_chat(
        self, 
        message: str, 
        user_id: str,
        conversation_history: str = "",
        user_name: Optional[str] = None,
        user_role: UserRole = UserRole.STUDENT
    ) -> ProcessingResult:
        """
        Process with Chat Agent with conversation context.
        
        Role-Based Prompting:
        - student: Gia sư - khuyến khích, giải thích cặn kẽ
        - teacher/admin: Trợ lý - chuyên nghiệp, ngắn gọn
        """
        # Build conversation history for chat agent
        history_list = []
        if conversation_history:
            for line in conversation_history.split("\n"):
                if line.startswith("User: "):
                    history_list.append({"role": "user", "content": line[6:]})
                elif line.startswith("AI: "):
                    history_list.append({"role": "assistant", "content": line[4:]})
        
        response = await self._chat_agent.process(
            message=message,
            user_id=user_id,
            conversation_history=history_list if history_list else None,
            user_role=user_role.value  # Pass role for role-based prompting
        )
        
        # Personalize response with user name
        content = response.content
        if user_name and not any(name in content.lower() for name in [user_name.lower()]):
            # Add personalization if not already present
            if "chào" in message.lower() or "hello" in message.lower():
                content = f"Chào {user_name}! " + content
        
        return ProcessingResult(
            message=content,
            agent_type=AgentType.CHAT,
            metadata={"memory_used": response.memory_used, "user_name": user_name, "user_role": user_role.value}
        )
    
    async def _process_with_rag(
        self, 
        message: str, 
        user_id: str,
        conversation_history: str = "",
        user_role: UserRole = UserRole.STUDENT
    ) -> ProcessingResult:
        """
        Process with RAG Agent with conversation context.
        
        Role-Based Prompting:
        - student: Gia sư - khuyến khích, giải thích cặn kẽ thuật ngữ
        - teacher/admin: Trợ lý - chuyên nghiệp, ngắn gọn, trích dẫn luật chính xác
        """
        logger.info(f"RAG query: {message} (role: {user_role.value})")
        logger.info(f"Knowledge graph available: {self._knowledge_graph.is_available()}")
        
        # Pass conversation history and role to RAG for context
        response = await self._rag_agent.query(
            message, 
            conversation_history=conversation_history,
            user_role=user_role.value  # Pass role for role-based prompting
        )
        logger.info(f"RAG response: {response.content[:100]}...")
        
        sources = None
        if response.citations:
            sources = [
                Source(
                    node_id=c.node_id,
                    title=c.title,
                    source_type="knowledge_graph",
                    content_snippet=c.source
                )
                for c in response.citations
            ]
        
        return ProcessingResult(
            message=response.content,
            agent_type=AgentType.RAG,
            sources=sources,
            metadata={
                "is_fallback": response.is_fallback,
                "citation_count": len(response.citations)
            }
        )
    
    async def _process_with_tutor(
        self, 
        message: str, 
        user_id: str,
        session_id: str
    ) -> ProcessingResult:
        """Process with Tutor Agent."""
        # Check for existing teaching session
        tutor_session_id = f"{user_id}_teaching"
        existing_session = self._tutor_agent.get_session(tutor_session_id)
        
        if existing_session:
            # Continue existing session
            response = self._tutor_agent.process_response(message, tutor_session_id)
        else:
            # Extract topic from message and start new session
            topic = self._extract_topic(message)
            response = self._tutor_agent.start_session(topic, user_id)
        
        # Update learning profile if assessment complete
        if response.assessment_complete:
            await self._update_learning_profile(user_id, response)
        
        return ProcessingResult(
            message=response.content,
            agent_type=AgentType.TUTOR,
            metadata={
                "phase": response.phase.value,
                "mastery_achieved": response.mastery_achieved
            }
        )
    
    def _extract_topic(self, message: str) -> str:
        """Extract topic from teaching request."""
        message_lower = message.lower()
        
        # Common maritime topics
        topics = {
            "solas": "solas",
            "colregs": "colregs",
            "fire": "fire_safety",
            "navigation": "navigation",
            "safety": "safety",
        }
        
        for keyword, topic in topics.items():
            if keyword in message_lower:
                return topic
        
        return "maritime_basics"
    
    async def _update_learning_profile(self, user_id: str, response) -> None:
        """Update learning profile after assessment."""
        try:
            profile = await self._profile_repo.get_or_create(UUID(user_id))
            assessment = self._tutor_agent.create_assessment_from_state(response.state)
            profile.add_assessment(assessment)
            await self._profile_repo.update(profile)
            logger.info(f"Updated learning profile for user {user_id}")
        except Exception as e:
            logger.warning(f"Failed to update learning profile: {e}")
    
    def _get_or_create_session(self, user_id: str) -> UUID:
        """Get or create a session for user (Memory Lite)."""
        # Try to get from chat history (persistent)
        if self._chat_history.is_available():
            chat_session = self._chat_history.get_or_create_session(user_id)
            if chat_session:
                self._sessions[user_id] = chat_session.session_id
                return chat_session.session_id
        
        # Fallback to in-memory session
        if user_id not in self._sessions:
            self._sessions[user_id] = uuid4()
        return self._sessions[user_id]
    
    def _extract_user_name(self, message: str) -> Optional[str]:
        """
        Extract user name from message.
        
        Patterns:
        - "tên là X", "tên tôi là X", "mình tên là X"
        - "I'm X", "my name is X", "call me X"
        """
        patterns = [
            r"tên (?:là|tôi là|mình là)\s+(\w+)",
            r"mình tên là\s+(\w+)",
            r"(?:i'm|i am|my name is|call me)\s+(\w+)",
            r"tên\s+(\w+)",
        ]
        
        message_lower = message.lower()
        for pattern in patterns:
            match = re.search(pattern, message_lower, re.IGNORECASE)
            if match:
                name = match.group(1).capitalize()
                # Filter out common words that aren't names
                if name.lower() not in ["là", "tôi", "mình", "the", "a", "an"]:
                    return name
        return None
    
    def _create_blocked_response(self, issues: List[str]) -> InternalChatResponse:
        """Create response for blocked content."""
        return InternalChatResponse(
            response_id=uuid4(),
            message=self._guardrails.get_refusal_message(),
            agent_type=AgentType.CHAT,
            metadata={"blocked": True, "issues": issues}
        )
    
    def _create_clarification_response(self, content: str) -> InternalChatResponse:
        """Create response requesting clarification."""
        return InternalChatResponse(
            response_id=uuid4(),
            message=content,
            agent_type=AgentType.CHAT,
            metadata={"requires_clarification": True}
        )
    
    def _save_message_async(self, session_id: UUID, role: str, content: str) -> None:
        """
        Save message to chat history (for BackgroundTasks).
        
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 04**
        """
        try:
            self._chat_history.save_message(session_id, role, content)
            logger.debug(f"Background saved {role} message to session {session_id}")
        except Exception as e:
            logger.error(f"Failed to save message in background: {e}")
    
    async def _update_profile_stats_async(self, user_id: str) -> None:
        """
        Update learning profile stats (for BackgroundTasks).
        
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 04**
        """
        try:
            await self._supabase_profile_repo.increment_stats(user_id, messages=2)  # user + assistant
            logger.debug(f"Background updated profile stats for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to update profile stats in background: {e}")
    
    async def _store_semantic_interaction_async(
        self,
        user_id: str,
        message: str,
        response: str,
        session_id: str
    ) -> None:
        """
        Store interaction in Semantic Memory v0.3 (for BackgroundTasks).
        
        **Spec: CHỈ THỊ KỸ THUẬT SỐ 06**
        """
        if self._semantic_memory is None:
            return
        
        try:
            # Store interaction with fact extraction
            await self._semantic_memory.store_interaction(
                user_id=user_id,
                message=message,
                response=response,
                session_id=session_id,
                extract_facts=True
            )
            
            # Check and summarize if needed
            await self._semantic_memory.check_and_summarize(
                user_id=user_id,
                session_id=session_id
            )
            
            logger.debug(f"Background stored semantic interaction for user {user_id}")
        except Exception as e:
            logger.error(f"Failed to store semantic interaction: {e}")
    
    async def _summarize_memory_async(
        self,
        session_id: str,
        message: str,
        response: str
    ) -> None:
        """
        Summarize conversation memory if needed (for BackgroundTasks).
        
        CHỈ THỊ KỸ THUẬT SỐ 17: Memory Summarizer Integration
        
        This runs in background after response is sent to user.
        """
        if self._memory_summarizer is None:
            return
        
        try:
            # Add messages to tiered memory
            await self._memory_summarizer.add_message_async(session_id, "user", message)
            await self._memory_summarizer.add_message_async(session_id, "assistant", response)
            
            logger.debug(f"Background added messages to MemorySummarizer for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to summarize memory: {e}")


# Singleton instance
_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get or create ChatService singleton."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service
