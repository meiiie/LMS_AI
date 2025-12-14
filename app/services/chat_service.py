"""
Chat Service - Integration layer for all components.

REFACTORED: This file is now a thin facade that delegates to:
- ChatOrchestrator: Pipeline orchestration
- SessionManager: Session and state management
- InputProcessor: Validation and context building
- OutputProcessor: Response formatting
- BackgroundTaskRunner: Async task management

**Pattern:** Facade Pattern (Gang of Four)
**Spec:** CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure

This service wires together:
- Unified Agent (CHỈ THỊ SỐ 13) - LLM-driven orchestration (ReAct pattern)
- OR Multi-Agent System (Phase 8, SOTA 2025)
- Semantic Memory Engine v0.5 (pgvector + Gemini embeddings)
- Knowledge Graph (Neo4j GraphRAG)
- Guardrails / Guardian Agent
- Learning Profile
- Chat History

**Feature: maritime-ai-tutor**
**Validates: Requirements 1.1, 2.1, 2.2, 2.3**
"""

import logging
from typing import Callable, Optional

from app.core.config import settings
from app.models.schemas import ChatRequest, InternalChatResponse

# Orchestrator and processors
from .chat_orchestrator import (
    ChatOrchestrator,
    get_chat_orchestrator,
    init_chat_orchestrator,
    AgentType  # Re-export for backward compatibility
)
from .session_manager import (
    SessionManager,
    SessionState,
    SessionContext,
    get_session_manager
)
from .input_processor import (
    InputProcessor,
    ChatContext,
    ValidationResult,
    get_input_processor,
    init_input_processor
)
from .output_processor import (
    OutputProcessor,
    ProcessingResult,
    get_output_processor,
    init_output_processor
)
from .background_tasks import (
    BackgroundTaskRunner,
    get_background_runner,
    init_background_runner
)

# Engine imports for initialization
from app.engine.guardrails import Guardrails
from app.engine.agentic_rag.rag_agent import RAGAgent, get_knowledge_repository
from app.repositories.user_graph_repository import get_user_graph_repository
from app.services.learning_graph_service import get_learning_graph_service
from app.services.chat_response_builder import get_chat_response_builder
from app.repositories.learning_profile_repository import get_learning_profile_repository
from app.repositories.chat_history_repository import get_chat_history_repository

# Optional imports with fallbacks
try:
    from app.engine.semantic_memory import SemanticMemoryEngine, get_semantic_memory_engine
    SEMANTIC_MEMORY_AVAILABLE = True
except ImportError:
    SEMANTIC_MEMORY_AVAILABLE = False

try:
    from app.engine.unified_agent import UnifiedAgent, get_unified_agent
    UNIFIED_AGENT_AVAILABLE = True
except ImportError:
    UNIFIED_AGENT_AVAILABLE = False

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

try:
    from app.engine.guardian_agent import get_guardian_agent
    GUARDIAN_AGENT_AVAILABLE = True
except ImportError:
    GUARDIAN_AGENT_AVAILABLE = False
    def get_guardian_agent(fallback_guardrails=None):
        return None

try:
    from app.engine.conversation_analyzer import get_conversation_analyzer
    CONVERSATION_ANALYZER_AVAILABLE = True
except ImportError:
    CONVERSATION_ANALYZER_AVAILABLE = False
    def get_conversation_analyzer():
        return None

try:
    from app.engine.multi_agent.graph import get_multi_agent_graph
    MULTI_AGENT_AVAILABLE = True
except ImportError:
    MULTI_AGENT_AVAILABLE = False

try:
    from app.engine.memory_compression import get_compression_engine
    MEMORY_COMPRESSION_AVAILABLE = True
except ImportError:
    MEMORY_COMPRESSION_AVAILABLE = False
    def get_compression_engine():
        return None

logger = logging.getLogger(__name__)


class ChatService:
    """
    Main service that integrates all components.
    
    REFACTORED: Now acts as a thin facade, delegating to specialized services.
    
    **Pattern:** Facade Pattern
    **Validates: Requirements 1.1, 2.1, 2.2, 2.3**
    """
    
    def __init__(self):
        """Initialize all components and wire up dependencies."""
        logger.info("Initializing ChatService (Facade Pattern)...")
        
        # ================================================================
        # CORE REPOSITORIES
        # ================================================================
        self._knowledge_graph = get_knowledge_repository()
        self._user_graph = get_user_graph_repository()
        self._learning_graph = get_learning_graph_service()
        self._pg_profile_repo = get_learning_profile_repository()
        self._chat_history = get_chat_history_repository()
        self._guardrails = Guardrails()
        
        # Ensure chat history tables
        if self._chat_history.is_available():
            self._chat_history.ensure_tables()
            logger.info("Chat History initialized")
        
        # ================================================================
        # ENGINE COMPONENTS
        # ================================================================
        
        # Semantic Memory v0.5
        self._semantic_memory = None
        if SEMANTIC_MEMORY_AVAILABLE and settings.semantic_memory_enabled:
            try:
                self._semantic_memory = get_semantic_memory_engine()
                if self._semantic_memory.is_available():
                    logger.info("✅ Semantic Memory v0.5 initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Semantic Memory: {e}")
        
        # RAG Agent
        self._rag_agent = RAGAgent(knowledge_graph=self._knowledge_graph)
        
        # Unified Agent (CHỈ THỊ SỐ 13)
        self._unified_agent = None
        if UNIFIED_AGENT_AVAILABLE and getattr(settings, 'use_unified_agent', True):
            try:
                self._unified_agent = UnifiedAgent(
                    rag_agent=self._rag_agent,
                    semantic_memory=self._semantic_memory,
                    chat_history=self._chat_history
                )
                if self._unified_agent.is_available():
                    logger.info("✅ Unified Agent (ReAct) initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Unified Agent: {e}")
        
        # Multi-Agent System (Phase 8)
        self._multi_agent_graph = None
        if MULTI_AGENT_AVAILABLE and getattr(settings, 'use_multi_agent', False):
            try:
                self._multi_agent_graph = get_multi_agent_graph()
                logger.info("✅ Multi-Agent System initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Multi-Agent: {e}")
        
        # Guardian Agent (CHỈ THỊ SỐ 21)
        self._guardian_agent = None
        if GUARDIAN_AGENT_AVAILABLE:
            try:
                self._guardian_agent = get_guardian_agent(fallback_guardrails=self._guardrails)
                if self._guardian_agent and self._guardian_agent.is_available():
                    logger.info("✅ Guardian Agent initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Guardian Agent: {e}")
        
        # Conversation Analyzer (CHỈ THỊ SỐ 21)
        self._conversation_analyzer = None
        if CONVERSATION_ANALYZER_AVAILABLE:
            try:
                self._conversation_analyzer = get_conversation_analyzer()
                logger.info("✅ Conversation Analyzer initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Conversation Analyzer: {e}")
        
        # Memory Summarizer (CHỈ THỊ SỐ 17)
        self._memory_summarizer = None
        if MEMORY_SUMMARIZER_AVAILABLE:
            try:
                self._memory_summarizer = get_memory_summarizer()
                if self._memory_summarizer and self._memory_summarizer.is_available():
                    logger.info("✅ Memory Summarizer initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Memory Summarizer: {e}")
        
        # Prompt Loader (CHỈ THỊ SỐ 16)
        self._prompt_loader = None
        if PROMPT_LOADER_AVAILABLE:
            try:
                self._prompt_loader = get_prompt_loader()
                logger.info("✅ Prompt Loader initialized")
            except Exception as e:
                logger.warning(f"Failed to initialize Prompt Loader: {e}")
        
        # Response Builder
        self._response_builder = get_chat_response_builder()
        
        # ================================================================
        # INITIALIZE PROCESSORS WITH DEPENDENCIES
        # ================================================================
        
        # Initialize InputProcessor
        init_input_processor(
            guardian_agent=self._guardian_agent,
            guardrails=self._guardrails,
            semantic_memory=self._semantic_memory,
            chat_history=self._chat_history,
            learning_graph=self._learning_graph,
            memory_summarizer=self._memory_summarizer,
            conversation_analyzer=self._conversation_analyzer
        )
        
        # Initialize OutputProcessor
        init_output_processor(
            guardrails=self._guardrails,
            response_builder=self._response_builder
        )
        
        # Initialize BackgroundTaskRunner
        init_background_runner(
            chat_history=self._chat_history,
            semantic_memory=self._semantic_memory,
            memory_summarizer=self._memory_summarizer,
            profile_repo=self._pg_profile_repo
        )
        
        # Initialize ChatOrchestrator
        init_chat_orchestrator(
            unified_agent=self._unified_agent,
            multi_agent_graph=self._multi_agent_graph,
            rag_agent=self._rag_agent,
            semantic_memory=self._semantic_memory,
            chat_history=self._chat_history,
            prompt_loader=self._prompt_loader,
            guardrails=self._guardrails
        )
        
        # Initialize Tool Registry with dependencies
        # CRITICAL: Without this, tool_maritime_search cannot access RAG Agent!
        from app.engine.tools import init_all_tools
        init_all_tools(
            rag_agent=self._rag_agent,
            semantic_memory=self._semantic_memory
        )
        logger.info("✅ Tool Registry initialized (RAG, Memory tools)")
        
        # Get the orchestrator
        self._orchestrator = get_chat_orchestrator()
        
        # Log availability status
        logger.info(f"Knowledge graph available: {self._knowledge_graph.is_available()}")
        logger.info(f"Chat history available: {self._chat_history.is_available()}")
        logger.info(f"Semantic memory available: {self._semantic_memory is not None}")
        logger.info(f"Unified Agent available: {self._unified_agent is not None}")
        logger.info(f"Multi-Agent available: {self._multi_agent_graph is not None}")
        
        logger.info("ChatService initialized (Facade Pattern) ✅")
    
    async def process_message(
        self,
        request: ChatRequest,
        background_save: Optional[Callable] = None
    ) -> InternalChatResponse:
        """
        Process a chat message through the full pipeline.
        
        Delegates to ChatOrchestrator for actual processing.
        
        Args:
            request: ChatRequest from API
            background_save: FastAPI BackgroundTasks.add_task
            
        Returns:
            InternalChatResponse ready for API serialization
        """
        return await self._orchestrator.process(request, background_save)


# =============================================================================
# SINGLETON
# =============================================================================

_chat_service: Optional[ChatService] = None


def get_chat_service() -> ChatService:
    """Get or create ChatService singleton."""
    global _chat_service
    if _chat_service is None:
        _chat_service = ChatService()
    return _chat_service


# =============================================================================
# BACKWARD COMPATIBILITY EXPORTS
# =============================================================================

# Re-export for backward compatibility with existing code
__all__ = [
    'ChatService',
    'get_chat_service',
    'AgentType',
    'ProcessingResult',
    'SessionState',
    'SessionContext',
]
