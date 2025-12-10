"""
Semantic Memory Engine Core - Facade Pattern
CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure

Main facade class that maintains backward compatibility.
Delegates to specialized modules:
- ContextRetriever: Context and insights retrieval
- FactExtractor: Fact extraction and storage

Requirements: 2.2, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3
"""
import json
import logging
from typing import List, Optional
from datetime import datetime, timedelta

from app.core.config import settings
from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
from app.models.semantic_memory import (
    ALLOWED_FACT_TYPES,
    FACT_TYPE_MAPPING,
    IGNORED_FACT_TYPES,
    ConversationSummary,
    FactType,
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

logger = logging.getLogger(__name__)


class SemanticMemoryEngine:
    """
    Main Semantic Memory Engine - Facade Pattern.
    
    Orchestrates:
    - ContextRetriever for context/insights retrieval
    - FactExtractor for fact extraction/storage
    - GeminiOptimizedEmbeddings for vector generation
    - SemanticMemoryRepository for storage/retrieval
    
    Maintains backward compatibility with existing code.
    
    Requirements: 2.2, 2.4
    """
    
    # Configuration
    DEFAULT_SEARCH_LIMIT = 5
    DEFAULT_SIMILARITY_THRESHOLD = 0.7
    DEFAULT_USER_FACTS_LIMIT = 10
    MAX_USER_FACTS = 50  # Memory cap (CHỈ THỊ 23)
    
    # Insight Engine v0.5 Configuration (CHỈ THỊ 23 CẢI TIẾN)
    MAX_INSIGHTS = 50  # Hard limit for insights
    CONSOLIDATION_THRESHOLD = 40  # Trigger consolidation at this count
    PRESERVE_DAYS = 7  # Preserve memories accessed within 7 days
    
    # Priority categories for retrieval
    PRIORITY_CATEGORIES = [InsightCategory.KNOWLEDGE_GAP, InsightCategory.LEARNING_STYLE]
    
    def __init__(
        self,
        embeddings: Optional[GeminiOptimizedEmbeddings] = None,
        repository: Optional[SemanticMemoryRepository] = None,
        llm=None  # Optional LLM for fact extraction
    ):
        """
        Initialize SemanticMemoryEngine.
        
        Args:
            embeddings: GeminiOptimizedEmbeddings instance
            repository: SemanticMemoryRepository instance
            llm: Optional LLM for fact extraction (ChatGoogleGenerativeAI)
        """
        self._embeddings = embeddings or GeminiOptimizedEmbeddings()
        self._repository = repository or SemanticMemoryRepository()
        self._llm = llm
        self._initialized = False
        
        # Initialize specialized modules
        self._context_retriever = ContextRetriever(self._embeddings, self._repository)
        self._fact_extractor = FactExtractor(self._embeddings, self._repository, llm)
        
        # Insight Engine v0.5 components (lazy initialization)
        self._insight_extractor = None
        self._insight_validator = None
        self._memory_consolidator = None
        
        logger.info("SemanticMemoryEngine initialized (v0.5 - Refactored)")
    
    def is_available(self) -> bool:
        """
        Check if Semantic Memory Engine is available.
        
        Returns:
            True if repository is available and embeddings are configured
        """
        try:
            return (
                self._repository is not None 
                and self._repository.is_available()
                and self._embeddings is not None
            )
        except Exception as e:
            logger.warning(f"SemanticMemoryEngine availability check failed: {e}")
            return False
    
    def _ensure_llm(self):
        """Lazy initialization of LLM for fact extraction."""
        if self._llm is None:
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                self._llm = ChatGoogleGenerativeAI(
                    model="gemini-2.0-flash-exp",
                    google_api_key=settings.google_api_key,
                    temperature=0.1  # Low temperature for consistent extraction
                )
                # Update fact extractor with LLM
                self._fact_extractor._llm = self._llm
                logger.info("LLM initialized for fact extraction")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM: {e}")
    
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
    
    # ==================== FACT EXTRACTION (Delegated) ====================
    
    async def _extract_and_store_facts(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None
    ) -> List[UserFact]:
        """
        Extract user facts from a message using LLM.
        
        Delegates to FactExtractor.extract_and_store_facts()
        """
        return await self._fact_extractor.extract_and_store_facts(
            user_id=user_id,
            message=message,
            session_id=session_id
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
    
    async def store_user_fact(
        self,
        user_id: str,
        fact_content: str,
        fact_type: str = "name",
        confidence: float = 0.9,
        session_id: Optional[str] = None
    ) -> bool:
        """
        Store a user fact directly (without LLM extraction).
        
        DEPRECATED: Use store_user_fact_upsert() instead for v0.4.
        """
        return await self.store_user_fact_upsert(
            user_id=user_id,
            fact_content=fact_content,
            fact_type=fact_type,
            confidence=confidence,
            session_id=session_id
        )
    
    async def store_user_fact_upsert(
        self,
        user_id: str,
        fact_content: str,
        fact_type: str = "name",
        confidence: float = 0.9,
        session_id: Optional[str] = None
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
            session_id=session_id
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
        try:
            # Store user message
            message_embedding = self._embeddings.embed_documents([message])[0]
            message_memory = SemanticMemoryCreate(
                user_id=user_id,
                content=f"User: {message}",
                embedding=message_embedding,
                memory_type=MemoryType.MESSAGE,
                importance=0.5,
                session_id=session_id
            )
            self._repository.save_memory(message_memory)
            
            # Store AI response
            response_embedding = self._embeddings.embed_documents([response])[0]
            response_memory = SemanticMemoryCreate(
                user_id=user_id,
                content=f"AI: {response}",
                embedding=response_embedding,
                memory_type=MemoryType.MESSAGE,
                importance=0.5,
                session_id=session_id
            )
            self._repository.save_memory(response_memory)
            
            # Extract and store user facts if enabled
            if extract_facts:
                await self._extract_and_store_facts(user_id, message, session_id)
            
            logger.debug(f"Stored interaction for user {user_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store interaction: {e}")
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
        try:
            import tiktoken
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except ImportError:
            return len(text) // 4
        except Exception as e:
            logger.warning(f"Token counting failed: {e}")
            return len(text) // 4
    
    def count_session_tokens(
        self,
        user_id: str,
        session_id: str
    ) -> int:
        """
        Count total tokens for a session's messages.
        
        Requirements: 3.1
        """
        try:
            messages = self._repository.search_similar(
                user_id=user_id,
                query_embedding=[0.0] * 768,
                limit=1000,
                threshold=0.0,
                memory_types=[MemoryType.MESSAGE]
            )
            
            total_tokens = 0
            for msg in messages:
                if msg.metadata.get("session_id") == session_id:
                    total_tokens += self.count_tokens(msg.content)
            
            return total_tokens
            
        except Exception as e:
            logger.error(f"Failed to count session tokens: {e}")
            return 0
    
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
        
        try:
            current_tokens = self.count_session_tokens(user_id, session_id)
            
            if current_tokens < threshold:
                logger.debug(
                    f"Session {session_id} has {current_tokens} tokens, "
                    f"below threshold {threshold}"
                )
                return None
            
            logger.info(
                f"Session {session_id} has {current_tokens} tokens, "
                f"triggering summarization"
            )
            
            summary = await self._summarize_session(
                user_id=user_id,
                session_id=session_id,
                token_count=current_tokens
            )
            
            return summary
            
        except Exception as e:
            logger.error(f"Summarization check failed: {e}")
            return None
    
    async def _summarize_session(
        self,
        user_id: str,
        session_id: str,
        token_count: int
    ) -> Optional[ConversationSummary]:
        """Summarize a session's conversation."""
        self._ensure_llm()
        
        if not self._llm:
            logger.warning("LLM not available for summarization")
            return None
        
        try:
            messages = self._get_session_messages(user_id, session_id)
            
            if not messages:
                return None
            
            conversation_text = "\n".join([m.content for m in messages])
            summary_text, key_topics = await self._generate_summary(conversation_text)
            
            summary = ConversationSummary(
                user_id=user_id,
                session_id=session_id,
                summary_text=summary_text,
                original_message_count=len(messages),
                original_token_count=token_count,
                key_topics=key_topics
            )
            
            summary_embedding = self._embeddings.embed_documents([summary_text])[0]
            summary_memory = summary.to_semantic_memory_create(summary_embedding)
            self._repository.save_memory(summary_memory)
            
            self._repository.delete_by_session(user_id, session_id)
            
            logger.info(
                f"Summarized session {session_id}: "
                f"{len(messages)} messages -> 1 summary"
            )
            
            return summary
            
        except Exception as e:
            logger.error(f"Session summarization failed: {e}")
            return None
    
    def _get_session_messages(
        self,
        user_id: str,
        session_id: str
    ) -> List[SemanticMemorySearchResult]:
        """Get all messages for a session."""
        try:
            all_memories = self._repository.search_similar(
                user_id=user_id,
                query_embedding=[0.0] * 768,
                limit=1000,
                threshold=0.0,
                memory_types=[MemoryType.MESSAGE]
            )
            
            session_messages = [
                m for m in all_memories
                if m.metadata.get("session_id") == session_id
            ]
            
            session_messages.sort(key=lambda x: x.created_at)
            
            return session_messages
            
        except Exception as e:
            logger.error(f"Failed to get session messages: {e}")
            return []
    
    async def _generate_summary(
        self,
        conversation_text: str
    ) -> tuple[str, List[str]]:
        """Generate summary using LLM."""
        prompt = f"""Summarize the following conversation between a user and an AI tutor about maritime topics.

Conversation:
{conversation_text}

Provide:
1. A concise summary (2-3 paragraphs) capturing the main points discussed
2. A list of key topics covered

Format your response as JSON:
{{
    "summary": "Your summary here...",
    "key_topics": ["topic1", "topic2", "topic3"]
}}

Return ONLY valid JSON:"""
        
        try:
            response = await self._llm.ainvoke(prompt)
            content = response.content.strip()
            
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()
            
            data = json.loads(content)
            
            summary_text = data.get("summary", "")
            key_topics = data.get("key_topics", [])
            
            return summary_text, key_topics
            
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return conversation_text[:500] + "...", []
    
    # ==================== INSIGHT ENGINE v0.5 ====================
    
    async def update_last_accessed(self, insight_id: int) -> bool:
        """Update last_accessed timestamp for an insight."""
        try:
            return self._repository.update_last_accessed(insight_id)
        except Exception as e:
            logger.error(f"Failed to update last_accessed: {e}")
            return False
    
    async def extract_and_store_insights(
        self,
        user_id: str,
        message: str,
        conversation_history: List[str] = None,
        session_id: Optional[str] = None
    ) -> List[Insight]:
        """
        Extract behavioral insights from message and store them.
        
        v0.5 (CHỈ THỊ 23 CẢI TIẾN):
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
        try:
            # Lazy init insight components
            if self._insight_extractor is None:
                try:
                    from app.engine.insight_extractor import InsightExtractor
                    self._insight_extractor = InsightExtractor()
                except ImportError:
                    logger.warning("InsightExtractor not available, skipping insight extraction")
                    return []
            
            if self._insight_validator is None:
                try:
                    from app.engine.insight_validator import InsightValidator
                    self._insight_validator = InsightValidator()
                except ImportError:
                    logger.warning("InsightValidator not available")
                    self._insight_validator = None
            
            if self._memory_consolidator is None:
                try:
                    from app.engine.memory_consolidator import MemoryConsolidator
                    self._memory_consolidator = MemoryConsolidator()
                except ImportError:
                    logger.warning("MemoryConsolidator not available")
                    self._memory_consolidator = None
            
            # Step 1: Extract insights
            insights = await self._insight_extractor.extract_insights(
                user_id=user_id,
                message=message,
                conversation_history=conversation_history
            )
            
            if not insights:
                return []
            
            # Step 2: Get existing insights for validation
            existing_insights = await self._get_user_insights(user_id)
            
            # Step 3: Validate and process each insight
            stored_insights = []
            for insight in insights:
                if self._insight_validator:
                    result = self._insight_validator.validate(insight, existing_insights)
                    
                    if not result.is_valid:
                        logger.debug(f"Insight rejected: {result.reason}")
                        continue
                    
                    if result.action == "merge":
                        await self._merge_insight(insight, result.target_insight)
                        stored_insights.append(insight)
                        
                    elif result.action == "update":
                        await self._update_insight_with_evolution(insight, result.target_insight)
                        stored_insights.append(insight)
                        
                    elif result.action == "store":
                        await self._store_insight(insight, session_id)
                        stored_insights.append(insight)
                        existing_insights.append(insight)
                else:
                    # No validator, just store
                    await self._store_insight(insight, session_id)
                    stored_insights.append(insight)
            
            # Step 4: Check consolidation threshold
            if self._memory_consolidator:
                await self._check_and_consolidate(user_id)
            
            logger.info(f"Stored {len(stored_insights)} insights for user {user_id}")
            return stored_insights
            
        except Exception as e:
            logger.error(f"Failed to extract and store insights: {e}")
            return []
    
    async def _get_user_insights(self, user_id: str) -> List[Insight]:
        """Get all insights for a user."""
        try:
            memories = self._repository.get_user_facts(
                user_id=user_id,
                limit=self.MAX_INSIGHTS,
                deduplicate=False
            )
            
            insights = []
            for mem in memories:
                if mem.metadata.get("insight_category"):
                    try:
                        insight = Insight(
                            id=mem.id,
                            user_id=user_id,
                            content=mem.content,
                            category=InsightCategory(mem.metadata.get("insight_category")),
                            sub_topic=mem.metadata.get("sub_topic"),
                            confidence=mem.metadata.get("confidence", 0.8),
                            source_messages=mem.metadata.get("source_messages", []),
                            created_at=mem.created_at,
                            evolution_notes=mem.metadata.get("evolution_notes", [])
                        )
                        insights.append(insight)
                    except (ValueError, KeyError) as e:
                        logger.debug(f"Skipping invalid insight: {e}")
            
            return insights
            
        except Exception as e:
            logger.error(f"Failed to get user insights: {e}")
            return []
    
    async def _store_insight(self, insight: Insight, session_id: Optional[str] = None) -> bool:
        """Store a new insight."""
        try:
            embedding = self._embeddings.embed_documents([insight.content])[0]
            
            memory = SemanticMemoryCreate(
                user_id=insight.user_id,
                content=insight.content,
                embedding=embedding,
                memory_type=MemoryType.INSIGHT,
                importance=insight.confidence,
                metadata=insight.to_metadata(),
                session_id=session_id
            )
            
            self._repository.save_memory(memory)
            return True
            
        except Exception as e:
            logger.error(f"Failed to store insight: {e}")
            return False
    
    async def _merge_insight(self, new_insight: Insight, existing_insight: Insight) -> bool:
        """Merge new insight with existing one."""
        try:
            new_confidence = (existing_insight.confidence + new_insight.confidence) / 2
            
            evolution_notes = existing_insight.evolution_notes.copy() if existing_insight.evolution_notes else []
            evolution_notes.append(f"Merged with similar insight: {new_insight.content[:50]}...")
            
            return self._repository.update_fact(
                fact_id=existing_insight.id,
                content=existing_insight.content,
                embedding=None,
                metadata={
                    **existing_insight.to_metadata(),
                    "confidence": new_confidence,
                    "evolution_notes": evolution_notes
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to merge insight: {e}")
            return False
    
    async def _update_insight_with_evolution(self, new_insight: Insight, existing_insight: Insight) -> bool:
        """Update existing insight with evolution note (for contradictions)."""
        try:
            embedding = self._embeddings.embed_documents([new_insight.content])[0]
            
            evolution_notes = existing_insight.evolution_notes.copy() if existing_insight.evolution_notes else []
            evolution_notes.append(f"Updated from: {existing_insight.content[:50]}...")
            
            return self._repository.update_fact(
                fact_id=existing_insight.id,
                content=new_insight.content,
                embedding=embedding,
                metadata={
                    **new_insight.to_metadata(),
                    "evolution_notes": evolution_notes
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to update insight with evolution: {e}")
            return False
    
    async def enforce_hard_limit(self, user_id: str) -> bool:
        """
        Enforce hard limit of 50 insights.
        
        **Validates: Requirements 3.1**
        """
        try:
            current_count = self._repository.count_user_memories(
                user_id=user_id,
                memory_type=MemoryType.INSIGHT
            )
            
            if current_count <= self.MAX_INSIGHTS:
                return True
            
            consolidated = await self._check_and_consolidate(user_id)
            
            if not consolidated:
                await self._fifo_eviction(user_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to enforce hard limit: {e}")
            return False
    
    async def _check_and_consolidate(self, user_id: str) -> bool:
        """Check and trigger consolidation if needed."""
        # Placeholder for consolidation logic
        return False
    
    async def _fifo_eviction(self, user_id: str) -> int:
        """Evict oldest insights using FIFO."""
        try:
            current_count = self._repository.count_user_memories(
                user_id=user_id,
                memory_type=MemoryType.INSIGHT
            )
            
            if current_count <= self.MAX_INSIGHTS:
                return 0
            
            excess = current_count - self.MAX_INSIGHTS
            deleted = self._repository.delete_oldest_facts(user_id, excess)
            
            logger.info(f"FIFO eviction for user {user_id}: deleted {deleted} insights")
            return deleted
            
        except Exception as e:
            logger.error(f"FIFO eviction failed: {e}")
            return 0


# Factory function
def get_semantic_memory_engine() -> SemanticMemoryEngine:
    """Get a configured SemanticMemoryEngine instance."""
    return SemanticMemoryEngine()
