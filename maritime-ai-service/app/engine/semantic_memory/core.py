"""
Semantic Memory Engine Core - Facade Pattern
CHI THI KY THUAT SO 25 - Project Restructure

Main facade class that maintains backward compatibility.
Delegates to specialized modules:
- ContextRetriever: Context and insights retrieval
- FactExtractor: Fact extraction and storage
- InsightProvider: Insight extraction, validation, and lifecycle management

Requirements: 2.2, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3
"""
import logging
from typing import List, Optional

from app.core.config import settings
from app.engine.embedding_runtime import (
    EmbeddingBackendProtocol,
    get_semantic_embedding_backend,
)
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.services.output_processor import extract_thinking_from_response
from app.models.semantic_memory import (
    ConversationSummary,
    Insight,
    InsightCategory,
    MemoryType,
    SemanticContext,
    SemanticMemoryCreate,
    SemanticMemorySearchResult,
    UserFact,
    UserFactExtraction,
)
from app.repositories.semantic_memory_repository import SemanticMemoryRepository

# Import specialized modules
from .context import ContextRetriever
from .extraction import FactExtractor
from .insight_provider import InsightProvider
from .session_runtime import (
    check_and_summarize_impl,
    count_session_tokens_impl,
    count_tokens_impl,
    delete_all_user_memories_impl,
    delete_memory_by_keyword_impl,
    generate_summary_impl,
    get_session_messages_impl,
    store_explicit_insight_impl,
    summarize_session_impl,
)
from .write_audit import (
    append_semantic_memory_write_audit_event,
    build_semantic_memory_write_audit,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)

logger = logging.getLogger(__name__)


class SemanticMemoryEngine:
    """
    Main Semantic Memory Engine - Facade Pattern.

    Orchestrates:
    - ContextRetriever for context/insights retrieval
    - FactExtractor for fact extraction/storage
    - InsightProvider for insight extraction, validation, and lifecycle
    - provider-agnostic embedding backend for vector generation
    - SemanticMemoryRepository for storage/retrieval

    Maintains backward compatibility with existing code.

    Requirements: 2.2, 2.4
    """

    # Configuration
    DEFAULT_SEARCH_LIMIT = 5
    DEFAULT_SIMILARITY_THRESHOLD = 0.7
    DEFAULT_USER_FACTS_LIMIT = 20  # Sprint 88: 15 fact types need >= 15 slots
    MAX_USER_FACTS = 50  # Memory cap (CHI THI 23)

    # Insight Engine v0.5 Configuration (CHI THI 23 CAI TIEN)
    MAX_INSIGHTS = 50  # Hard limit for insights
    CONSOLIDATION_THRESHOLD = 40  # Trigger consolidation at this count
    PRESERVE_DAYS = 7  # Preserve memories accessed within 7 days

    # Priority categories for retrieval
    PRIORITY_CATEGORIES = [InsightCategory.KNOWLEDGE_GAP, InsightCategory.LEARNING_STYLE]

    def __init__(
        self,
        embeddings: Optional[EmbeddingBackendProtocol] = None,
        repository: Optional[SemanticMemoryRepository] = None,
        llm=None  # Optional LLM for fact extraction
    ):
        """
        Initialize SemanticMemoryEngine.

        Args:
            embeddings: Semantic embedding backend instance
            repository: SemanticMemoryRepository instance
            llm: Optional LLM for fact extraction (ChatGoogleGenerativeAI)
        """
        self._embeddings = embeddings or get_semantic_embedding_backend()
        self._repository = repository or SemanticMemoryRepository()
        self._llm = llm
        self._initialized = False

        # Initialize specialized modules
        self._context_retriever = ContextRetriever(self._embeddings, self._repository)
        self._fact_extractor = FactExtractor(self._embeddings, self._repository, llm)
        self._insight_provider = InsightProvider(self._embeddings, self._repository)

        logger.info("SemanticMemoryEngine initialized (v0.5 - Refactored)")

    def is_available(self) -> bool:
        """
        Check if Semantic Memory Engine is available.

        Returns:
            True if repository is available. Embeddings can degrade independently
            because read/write paths now have lexical and NULL-vector fallbacks.
        """
        try:
            return self._repository is not None and self._repository.is_available()
        except Exception as e:
            logger.warning("SemanticMemoryEngine availability check failed: %s", e)
            return False

    def _ensure_llm(self):
        """Lazy initialization of LLM for summarization."""
        if self._llm is None:
            try:
                from app.engine.llm_pool import get_llm_light
                self._llm = get_llm_light()
                self._fact_extractor._llm = self._llm
                logger.info("LLM initialized for summarization (LIGHT tier - shared pool)")
            except Exception as e:
                logger.warning("Failed to initialize LLM: %s", e)

    # ==================== CONTEXT RETRIEVAL (Delegated) ====================

    async def retrieve_context(
        self,
        user_id: str,
        query: str,
        search_limit: int = DEFAULT_SEARCH_LIMIT,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
        include_user_facts: bool = True,
        deduplicate_facts: bool = True
    ) -> SemanticContext:
        """
        Retrieve relevant context for a query.

        Delegates to ContextRetriever.retrieve_context()

        Args:
            user_id: User ID
            query: Query text to find similar memories
            search_limit: Maximum similar memories to return
            similarity_threshold: Minimum similarity score
            include_user_facts: Whether to include user facts
            deduplicate_facts: If True, deduplicate facts by fact_type

        Returns:
            SemanticContext with relevant memories and user facts

        Requirements: 1.1, 2.2, 2.4, 4.3
        """
        return await self._context_retriever.retrieve_context(
            user_id=user_id,
            query=query,
            search_limit=search_limit,
            similarity_threshold=similarity_threshold,
            include_user_facts=include_user_facts,
            deduplicate_facts=deduplicate_facts
        )

    async def retrieve_insights_prioritized(
        self,
        user_id: str,
        query: str,
        limit: int = 10
    ) -> List[Insight]:
        """
        Retrieve insights with category prioritization.

        Delegates to ContextRetriever.retrieve_insights_prioritized()

        **Validates: Requirements 4.3, 4.4**
        """
        return await self._context_retriever.retrieve_insights_prioritized(
            user_id=user_id,
            query=query,
            limit=limit,
            update_last_accessed_callback=self.update_last_accessed
        )

    async def get_user_facts(self, user_id: str) -> dict:
        """
        Get user facts as a dictionary for easy access.

        This method converts the List[SemanticMemorySearchResult] from
        repository.get_user_facts() into a dict format with keys:
        - name, role, goal, preference, weakness, background, etc.

        Used by:
        - MemoryAgentNode._get_user_facts() for personalization
        - tool_get_user_info() for tool-based retrieval

        Args:
            user_id: User ID to get facts for

        Returns:
            Dict with fact_type as keys and fact content as values.
            Each value is the fact text. An additional key "{fact_type}__updated_at"
            holds the datetime when the fact was last updated (for staleness display).
            Example: {"name": "User", "name__updated_at": datetime(...)}

        **SOTA Pattern:** MemGPT/Mem0 style archival memory access
        **Validates: Requirements 2.2, 4.3**
        """
        read_scope = resolve_memory_read_scope()
        if not read_scope.write_allowed:
            logger.warning(
                "User fact retrieval blocked for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                read_scope.state,
            )
            return {}

        try:
            # Get facts from repository (returns List[SemanticMemorySearchResult])
            facts_list = self._repository.get_user_facts(
                user_id=user_id,
                limit=20,
                deduplicate=True  # Keep only latest of each type
            )

            if not facts_list:
                logger.debug(
                    "No user facts found for user_hash=%s",
                    hash_memory_identifier(user_id),
                )
                return {}

            # Convert to dict format
            result = {}
            for fact in facts_list:
                # Get fact_type from metadata
                fact_type = fact.metadata.get("fact_type", "unknown")

                # Extract value from content
                # Format can be "fact_type: value" or just "value"
                content = fact.content
                if ": " in content:
                    # Split and get value part
                    value = content.split(": ", 1)[-1]
                else:
                    value = content

                # Only set if not already present (keep first/latest)
                if fact_type not in result:
                    result[fact_type] = value
                    # Sprint 121 RC-4: Include updated_at for staleness display
                    ts = fact.updated_at or fact.created_at
                    result[f"{fact_type}__updated_at"] = ts

            logger.debug(
                "Retrieved %d user facts for user_hash=%s: %s",
                len(result),
                hash_memory_identifier(user_id),
                list(result.keys()),
            )
            return result

        except Exception as e:
            logger.error(
                "Failed to get user facts for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                e,
            )
            return {}

    def search_relevant_facts(
        self,
        user_id: str,
        query_embedding: List[float],
        limit: int = DEFAULT_SEARCH_LIMIT,
        min_similarity: float = 0.3,
    ) -> List[SemanticMemorySearchResult]:
        """
        Search user facts by query embedding.

        This keeps the facade aligned with the repository API used by the
        prompt-context builder, so semantic fact retrieval does not silently
        fall back to broad fact injection.
        """
        read_scope = resolve_memory_read_scope()
        if not read_scope.write_allowed:
            logger.warning(
                "Relevant fact search blocked for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                read_scope.state,
            )
            return []

        try:
            return self._repository.search_relevant_facts(
                user_id=user_id,
                query_embedding=query_embedding,
                limit=limit,
                min_similarity=min_similarity,
            )
        except Exception as exc:
            logger.warning(
                "Failed to search relevant facts for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                exc,
            )
            return []

    # ==================== FACT EXTRACTION (Delegated) ====================

    async def _extract_and_store_facts(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        emit_write_audit: bool = True,
    ) -> List[UserFact]:
        """
        Extract user facts from a message using LLM.

        Sprint 73 fix: Fetches existing facts and passes them to the
        enhanced extractor so it avoids re-extraction and detects changes.
        This ensures ALL messages (including tutor/RAG-routed) get proper
        15-type extraction with existing facts context.
        """
        # Fetch existing facts for context-aware extraction
        existing_facts = None
        try:
            existing_facts = await self.get_user_facts(user_id)
        except Exception as e:
            logger.warning("Failed to fetch existing facts for extraction context: %s", e)

        return await self._fact_extractor.extract_and_store_facts(
            user_id=user_id,
            message=message,
            session_id=session_id,
            existing_facts=existing_facts,
            emit_write_audit=emit_write_audit,
        )

    async def extract_user_facts(
        self,
        user_id: str,
        message: str
    ) -> UserFactExtraction:
        """
        Use LLM to extract user facts from a message.

        Delegates to FactExtractor.extract_user_facts()
        """
        return await self._fact_extractor.extract_user_facts(user_id, message)

    async def store_user_fact_upsert(
        self,
        user_id: str,
        fact_content: str,
        fact_type: str = "name",
        confidence: float = 0.9,
        session_id: Optional[str] = None,
        source_message: Optional[str] = None,
    ) -> bool:
        """
        Store or update a user fact using upsert logic.

        Delegates to FactExtractor.store_user_fact_upsert()
        """
        return await self._fact_extractor.store_user_fact_upsert(
            user_id=user_id,
            fact_content=fact_content,
            fact_type=fact_type,
            confidence=confidence,
            session_id=session_id,
            source_message=source_message,
        )

    # ==================== INTERACTION STORAGE ====================

    async def store_interaction(
        self,
        user_id: str,
        message: str,
        response: str,
        session_id: Optional[str] = None,
        extract_facts: bool = True
    ) -> bool:
        """
        Store an interaction (message + response) as semantic memories.

        Args:
            user_id: User ID
            message: User's message
            response: AI's response
            session_id: Optional session ID
            extract_facts: Whether to extract user facts

        Returns:
            True if storage successful

        Requirements: 2.1
        """
        message_saved = False
        response_saved = False
        stored_fact_count = 0
        audit_scope = resolve_memory_write_scope()
        if not audit_scope.write_allowed:
            audit_payload = build_semantic_memory_write_audit(
                user_id=user_id,
                session_id=session_id,
                message=message,
                response=response,
                scope=audit_scope,
                message_saved=False,
                response_saved=False,
                extract_facts=extract_facts,
                stored_fact_count=0,
                status="blocked",
                warnings=["semantic_memory_write_blocked_missing_org_context"],
            )
            await append_semantic_memory_write_audit_event(
                session_id=session_id,
                org_id=audit_scope.org_id,
                payload=audit_payload,
            )
            logger.warning(
                "Semantic memory interaction write blocked for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                audit_scope.state,
            )
            return False

        try:
            async def _safe_embed(text: str, label: str) -> list[float]:
                try:
                    embeddings = await self._embeddings.aembed_documents([text])
                    if embeddings and embeddings[0]:
                        return embeddings[0]
                except Exception as exc:
                    logger.warning(
                        "Interaction embedding unavailable for %s of user_hash=%s: %s",
                        label,
                        hash_memory_identifier(user_id),
                        exc,
                    )
                return []

            # Store user message (Sprint 27: async embedding)
            message_embedding = await _safe_embed(message, "user_message")
            message_memory = SemanticMemoryCreate(
                user_id=user_id,
                content=f"User: {message}",
                embedding=message_embedding,
                memory_type=MemoryType.MESSAGE,
                importance=0.5,
                session_id=session_id
            )
            message_saved = self._repository.save_memory(message_memory) is not None

            # Store AI response (Sprint 27: async embedding)
            response_embedding = await _safe_embed(response, "assistant_response")
            response_memory = SemanticMemoryCreate(
                user_id=user_id,
                content=f"AI: {response}",
                embedding=response_embedding,
                memory_type=MemoryType.MESSAGE,
                importance=0.5,
                session_id=session_id
            )
            response_saved = self._repository.save_memory(response_memory) is not None

            # Extract and store user facts if enabled
            if extract_facts:
                stored_facts = await self._extract_and_store_facts(
                    user_id, message, session_id, emit_write_audit=False
                )
                stored_fact_count = len(stored_facts or [])

            logger.debug(
                "Stored interaction for user_hash=%s",
                hash_memory_identifier(user_id),
            )
            audit_payload = build_semantic_memory_write_audit(
                user_id=user_id,
                session_id=session_id,
                message=message,
                response=response,
                scope=audit_scope,
                message_saved=message_saved,
                response_saved=response_saved,
                extract_facts=extract_facts,
                stored_fact_count=stored_fact_count,
                status=(
                    "saved"
                    if message_saved and response_saved
                    else "degraded"
                ),
            )
            await append_semantic_memory_write_audit_event(
                session_id=session_id,
                org_id=audit_scope.org_id,
                payload=audit_payload,
            )
            return message_saved and response_saved

        except Exception as e:
            logger.error("Failed to store interaction: %s", e)
            audit_payload = build_semantic_memory_write_audit(
                user_id=user_id,
                session_id=session_id,
                message=message,
                response=response,
                scope=audit_scope,
                message_saved=message_saved,
                response_saved=response_saved,
                extract_facts=extract_facts,
                stored_fact_count=stored_fact_count,
                status="failed",
                warnings=["semantic_memory_write_failed"],
            )
            await append_semantic_memory_write_audit_event(
                session_id=session_id,
                org_id=audit_scope.org_id,
                payload=audit_payload,
            )
            return False

    # ==================== TOKEN COUNTING ====================

    def count_tokens(self, text: str) -> int:
        """
        Count tokens in text using tiktoken.

        Args:
            text: Text to count tokens for

        Returns:
            Estimated token count

        Requirements: 3.1
        """
        return count_tokens_impl(text, logger)

    def count_session_tokens(
        self,
        user_id: str,
        session_id: str
    ) -> int:
        """
        Count total tokens for a session's messages.

        Sprint 27 FIX: Uses get_memories_by_type() with session_id filter
        instead of search_similar() with zero-vector (NaN bug in pgvector).

        Requirements: 3.1
        """
        return count_session_tokens_impl(
            self._repository,
            user_id,
            session_id,
            self.count_tokens,
            logger,
        )

    # ==================== SUMMARIZATION ====================

    async def check_and_summarize(
        self,
        user_id: str,
        session_id: str,
        token_threshold: Optional[int] = None
    ) -> Optional[ConversationSummary]:
        """
        Check if session exceeds token threshold and summarize if needed.

        Requirements: 3.1, 3.2, 3.3, 3.4
        """
        threshold = token_threshold or settings.summarization_token_threshold
        return await check_and_summarize_impl(self, user_id, session_id, threshold, logger)

    async def _summarize_session(
        self,
        user_id: str,
        session_id: str,
        token_count: int
    ) -> Optional[ConversationSummary]:
        """Summarize a session's conversation."""
        return await summarize_session_impl(
            self,
            user_id,
            session_id,
            token_count,
            extract_thinking_from_response,
            logger,
        )

    def _get_session_messages(
        self,
        user_id: str,
        session_id: str
    ) -> List[SemanticMemorySearchResult]:
        """
        Get all messages for a session.

        Sprint 27 FIX: Uses get_memories_by_type() with session_id filter
        instead of search_similar() with zero-vector (NaN bug in pgvector).
        Also filters directly in SQL instead of in-memory Python loop.
        """
        return get_session_messages_impl(self._repository, user_id, session_id, logger)

    async def _generate_summary(
        self,
        conversation_text: str
    ) -> tuple[str, List[str]]:
        """Generate summary using LLM."""
        return await generate_summary_impl(
            self._llm,
            conversation_text,
            extract_thinking_from_response,
            logger,
        )

    # ==================== MEMORY MANAGEMENT (Sprint 26) ====================

    async def delete_memory_by_keyword(
        self,
        user_id: str,
        keyword: str
    ) -> int:
        """
        Delete memories matching a keyword for a user.

        Searches content field for keyword match and deletes matching entries.
        Used by tool_forget for user-initiated memory deletion.

        Args:
            user_id: User ID
            keyword: Keyword to search and delete

        Returns:
            Number of memories deleted

        Sprint 26: Fix for CRITICAL-2 (tool_forget silent failure)
        """
        return await delete_memory_by_keyword_impl(self._repository, user_id, keyword, logger)

    async def delete_all_user_memories(self, user_id: str) -> int:
        """
        Delete ALL memories for a user (factory reset).

        Removes all memory types: USER_FACT, INSIGHT, MESSAGE, SUMMARY.
        Used by tool_clear_all_memories for user-initiated full reset.

        Args:
            user_id: User ID

        Returns:
            Number of memories deleted

        Sprint 26: Fix for CRITICAL-1 (tool_clear_all_memories only cleared cache)
        """
        return await delete_all_user_memories_impl(self._repository, user_id, logger)

    async def store_explicit_insight(
        self,
        user_id: str,
        insight_text: str,
        category: str = "preference",
        session_id: Optional[str] = None
    ) -> bool:
        """
        Store an explicit user-requested memory as an INSIGHT.

        Used by tool_remember when user says "remember this".

        Args:
            user_id: User ID
            insight_text: The text to remember
            category: Insight category (default: preference)
            session_id: Optional session ID

        Returns:
            True if stored successfully

        Sprint 26: Fix for CRITICAL-3 (tool_remember called non-existent method)
        """
        return await store_explicit_insight_impl(
            self,
            user_id,
            insight_text,
            category,
            session_id,
            logger,
        )

    # ==================== INSIGHT ENGINE v0.5 (Delegated) ====================

    async def update_last_accessed(self, insight_id: int) -> bool:
        """
        Update last_accessed timestamp for an insight.

        Delegates to InsightProvider.update_last_accessed()
        """
        return await self._insight_provider.update_last_accessed(insight_id)

    async def extract_and_store_insights(
        self,
        user_id: str,
        message: str,
        conversation_history: List[str] = None,
        session_id: Optional[str] = None
    ) -> List[Insight]:
        """
        Extract behavioral insights from message and store them.

        Delegates to InsightProvider.extract_and_store_insights()

        v0.5 (CHI THI 23 CAI TIEN):
        1. Extract insights using InsightExtractor
        2. Validate each insight
        3. Handle duplicates (merge) and contradictions (update)
        4. Check consolidation threshold
        5. Store valid insights

        Args:
            user_id: User ID
            message: User message to extract insights from
            conversation_history: Previous messages for context
            session_id: Optional session ID

        Returns:
            List of stored insights

        **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 5.1, 5.2, 5.3, 5.4**
        """
        return await self._insight_provider.extract_and_store_insights(
            user_id=user_id,
            message=message,
            conversation_history=conversation_history,
            session_id=session_id
        )

    async def enforce_hard_limit(self, user_id: str) -> bool:
        """
        Enforce hard limit of 50 insights.

        Delegates to InsightProvider.enforce_hard_limit()

        **Validates: Requirements 3.1**
        """
        return await self._insight_provider.enforce_hard_limit(user_id)


# Factory function
def get_semantic_memory_engine() -> SemanticMemoryEngine:
    """Get a configured SemanticMemoryEngine instance."""
    return SemanticMemoryEngine()
