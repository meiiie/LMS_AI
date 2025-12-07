"""
Semantic Memory Engine for Maritime AI Tutor v0.3
CHỈ THỊ KỸ THUẬT SỐ 06

Main engine for semantic memory operations including:
- Context retrieval with vector similarity search
- Interaction storage with embeddings
- User facts extraction
- Conversation summarization

Requirements: 2.2, 2.4, 3.1, 3.2, 3.3, 3.4, 4.1, 4.2, 4.3
"""
import json
import logging
from typing import List, Optional

from app.core.config import settings
from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
from datetime import datetime, timedelta

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

logger = logging.getLogger(__name__)


class SemanticMemoryEngine:
    """
    Main engine for semantic memory operations.
    
    Orchestrates:
    - GeminiOptimizedEmbeddings for vector generation
    - SemanticMemoryRepository for storage/retrieval
    - LLM for fact extraction and summarization
    
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
        llm = None  # Optional LLM for fact extraction
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
        
        # Insight Engine v0.5 components (lazy initialization)
        self._insight_extractor = None
        self._insight_validator = None
        self._memory_consolidator = None
        
        logger.info("SemanticMemoryEngine initialized (v0.5 - Insight Engine)")
    
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
                logger.info("LLM initialized for fact extraction")
            except Exception as e:
                logger.warning(f"Failed to initialize LLM: {e}")
    
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
        
        Cross-session Memory Persistence (v0.2.1):
        - Retrieves user facts from ALL sessions (deduplicated by fact_type)
        - Searches relevant memories across ALL sessions
        - Combines into SemanticContext for LLM prompt
        
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
        **Feature: cross-session-memory, Property 5: Context Includes User Facts**
        """
        try:
            # Generate query embedding
            query_embedding = self._embeddings.embed_query(query)
            
            # Search for similar memories across ALL sessions (excluding user_facts)
            relevant_memories = self._repository.search_similar(
                user_id=user_id,
                query_embedding=query_embedding,
                limit=search_limit,
                threshold=similarity_threshold,
                memory_types=[MemoryType.MESSAGE, MemoryType.SUMMARY],
                include_all_sessions=True  # Cross-session search
            )
            
            # Get user facts from ALL sessions (deduplicated)
            user_facts = []
            if include_user_facts:
                user_facts = self._repository.get_user_facts(
                    user_id=user_id,
                    limit=self.DEFAULT_USER_FACTS_LIMIT,
                    deduplicate=deduplicate_facts  # Deduplicate by fact_type
                )
            
            context = SemanticContext(
                relevant_memories=relevant_memories,
                user_facts=user_facts,
                recent_messages=[],  # Will be filled by ChatService if needed
                total_tokens=self._estimate_tokens(relevant_memories, user_facts)
            )
            
            logger.debug(
                f"Retrieved context for user {user_id}: "
                f"{len(relevant_memories)} memories, {len(user_facts)} facts"
            )
            
            return context
            
        except Exception as e:
            logger.error(f"Failed to retrieve context: {e}")
            return SemanticContext()
    
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
    
    async def _extract_and_store_facts(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None
    ) -> List[UserFact]:
        """
        Extract user facts from a message using LLM.
        
        v0.4 Update (CHỈ THỊ 23):
        - Uses store_user_fact_upsert() for upsert logic
        - Validates fact_type before storing
        - Enforces memory cap
        
        Args:
            user_id: User ID
            message: Message to extract facts from
            session_id: Optional session ID
            
        Returns:
            List of extracted UserFact objects
            
        Requirements: 4.1, 4.2, 4.3
        """
        self._ensure_llm()
        
        if not self._llm:
            return []
        
        try:
            extraction = await self.extract_user_facts(user_id, message)
            
            if not extraction.has_facts:
                return []
            
            # Store each fact using upsert logic (v0.4)
            stored_facts = []
            for fact in extraction.facts:
                fact_content = fact.to_content()
                
                # Use upsert method which handles validation, dedup, and capping
                success = await self.store_user_fact_upsert(
                    user_id=user_id,
                    fact_content=fact_content,
                    fact_type=fact.fact_type.value,
                    confidence=fact.confidence,
                    session_id=session_id
                )
                
                if success:
                    stored_facts.append(fact)
            
            logger.info(f"Extracted and stored {len(stored_facts)} facts for user {user_id}")
            return stored_facts
            
        except RuntimeError as e:
            # Handle "Event loop is closed" gracefully
            if "Event loop is closed" in str(e):
                logger.warning(f"Fact extraction skipped (event loop closed): {e}")
            else:
                logger.error(f"Fact extraction runtime error: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to extract facts: {e}")
            return []
    
    async def extract_user_facts(
        self,
        user_id: str,
        message: str
    ) -> UserFactExtraction:
        """
        Use LLM to extract user facts from a message.
        
        Args:
            user_id: User ID
            message: Message to analyze
            
        Returns:
            UserFactExtraction with extracted facts
            
        Requirements: 4.1, 4.2
        """
        self._ensure_llm()
        
        if not self._llm:
            return UserFactExtraction(facts=[], raw_message=message)
        
        try:
            prompt = self._build_fact_extraction_prompt(message)
            response = await self._llm.ainvoke(prompt)
            
            # Parse JSON response
            facts = self._parse_fact_extraction_response(response.content, message)
            
            return UserFactExtraction(
                facts=facts,
                raw_message=message
            )
            
        except Exception as e:
            logger.error(f"Fact extraction failed: {e}")
            return UserFactExtraction(facts=[], raw_message=message)
    
    def _build_fact_extraction_prompt(self, message: str) -> str:
        """Build prompt for fact extraction."""
        return f"""Analyze the following message and extract any personal facts about the user.
Return a JSON array of facts. Each fact should have:
- fact_type: one of [name, preference, goal, background, weak_area, strong_area, interest, learning_style]
- value: the actual fact
- confidence: confidence score from 0.0 to 1.0

If no facts are found, return an empty array: []

Message: "{message}"

Examples of facts to extract:
- User's name ("Tôi là Minh" -> name: "Minh")
- Learning goals ("Tôi muốn học về COLREGs" -> goal: "học về COLREGs")
- Professional background ("Tôi là thuyền trưởng" -> background: "thuyền trưởng")
- Weak areas ("Tôi chưa hiểu về quy tắc 15" -> weak_area: "quy tắc 15 COLREGs")
- Interests ("Tôi quan tâm đến an toàn hàng hải" -> interest: "an toàn hàng hải")

Return ONLY valid JSON, no explanation:"""
    
    def _parse_fact_extraction_response(
        self,
        response: str,
        original_message: str
    ) -> List[UserFact]:
        """Parse LLM response into UserFact objects."""
        try:
            # Clean response - extract JSON
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
            
            # Parse JSON
            facts_data = json.loads(response)
            
            if not isinstance(facts_data, list):
                return []
            
            facts = []
            for item in facts_data:
                try:
                    fact_type = FactType(item.get("fact_type", "").lower())
                    value = item.get("value", "")
                    confidence = float(item.get("confidence", 0.8))
                    
                    if value:
                        facts.append(UserFact(
                            fact_type=fact_type,
                            value=value,
                            confidence=min(max(confidence, 0.0), 1.0),
                            source_message=original_message
                        ))
                except (ValueError, KeyError) as e:
                    logger.debug(f"Skipping invalid fact: {e}")
                    continue
            
            return facts
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse fact extraction response: {e}")
            return []
    
    def _estimate_tokens(
        self,
        memories: List[SemanticMemorySearchResult],
        facts: List[SemanticMemorySearchResult]
    ) -> int:
        """Estimate token count for context."""
        total_chars = sum(len(m.content) for m in memories)
        total_chars += sum(len(f.content) for f in facts)
        # Rough estimate: 1 token ≈ 4 characters for Vietnamese/English mix
        return total_chars // 4
    
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
            # Use cl100k_base encoding (GPT-4/Gemini compatible)
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))
        except ImportError:
            # Fallback: estimate 1 token ≈ 4 characters
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
        
        Args:
            user_id: User ID
            session_id: Session ID
            
        Returns:
            Total token count for session
            
        Requirements: 3.1
        """
        try:
            # Get all messages for session
            messages = self._repository.search_similar(
                user_id=user_id,
                query_embedding=[0.0] * 768,  # Dummy embedding
                limit=1000,
                threshold=0.0,  # Get all
                memory_types=[MemoryType.MESSAGE]
            )
            
            # Filter by session and count tokens
            total_tokens = 0
            for msg in messages:
                if msg.metadata.get("session_id") == session_id:
                    total_tokens += self.count_tokens(msg.content)
            
            return total_tokens
            
        except Exception as e:
            logger.error(f"Failed to count session tokens: {e}")
            return 0
    
    async def check_and_summarize(
        self,
        user_id: str,
        session_id: str,
        token_threshold: Optional[int] = None
    ) -> Optional[ConversationSummary]:
        """
        Check if session exceeds token threshold and summarize if needed.
        
        Args:
            user_id: User ID
            session_id: Session ID
            token_threshold: Token threshold (defaults to settings)
            
        Returns:
            ConversationSummary if summarization was performed, None otherwise
            
        Requirements: 3.1, 3.2, 3.3, 3.4
        """
        threshold = token_threshold or settings.summarization_token_threshold
        
        try:
            # Count current session tokens
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
            
            # Perform summarization
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
        """
        Summarize a session's conversation.
        
        Args:
            user_id: User ID
            session_id: Session ID
            token_count: Current token count
            
        Returns:
            ConversationSummary object
            
        Requirements: 3.2, 3.3, 3.4
        """
        self._ensure_llm()
        
        if not self._llm:
            logger.warning("LLM not available for summarization")
            return None
        
        try:
            # Get all messages for session
            messages = self._get_session_messages(user_id, session_id)
            
            if not messages:
                return None
            
            # Build conversation text
            conversation_text = "\n".join([m.content for m in messages])
            
            # Generate summary using LLM
            summary_text, key_topics = await self._generate_summary(conversation_text)
            
            # Create summary object
            summary = ConversationSummary(
                user_id=user_id,
                session_id=session_id,
                summary_text=summary_text,
                original_message_count=len(messages),
                original_token_count=token_count,
                key_topics=key_topics
            )
            
            # Store summary as semantic memory
            summary_embedding = self._embeddings.embed_documents([summary_text])[0]
            summary_memory = summary.to_semantic_memory_create(summary_embedding)
            self._repository.save_memory(summary_memory)
            
            # Archive original messages (delete from semantic_memories)
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
            # Use a broad search to get all messages
            all_memories = self._repository.search_similar(
                user_id=user_id,
                query_embedding=[0.0] * 768,
                limit=1000,
                threshold=0.0,
                memory_types=[MemoryType.MESSAGE]
            )
            
            # Filter by session_id from metadata
            session_messages = [
                m for m in all_memories
                if m.metadata.get("session_id") == session_id
            ]
            
            # Sort by created_at
            session_messages.sort(key=lambda x: x.created_at)
            
            return session_messages
            
        except Exception as e:
            logger.error(f"Failed to get session messages: {e}")
            return []
    
    async def _generate_summary(
        self,
        conversation_text: str
    ) -> tuple[str, List[str]]:
        """
        Generate summary using LLM.
        
        Args:
            conversation_text: Full conversation text
            
        Returns:
            Tuple of (summary_text, key_topics)
            
        Requirements: 3.2
        """
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
            
            # Clean JSON
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
            # Fallback: truncate conversation
            return conversation_text[:500] + "...", []
    
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
        This method is kept for backward compatibility.
        
        Args:
            user_id: User ID
            fact_content: The fact content (e.g., "User's name is Minh")
            fact_type: Type of fact (name, preference, goal, etc.)
            confidence: Confidence score (0.0 - 1.0)
            session_id: Optional session ID
            
        Returns:
            True if storage successful
        """
        # Delegate to upsert method for v0.4
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
        
        v0.4 (CHỈ THỊ 23):
        1. Validate fact_type is in ALLOWED_FACT_TYPES
        2. Check if fact of same type exists
        3. If exists: Update content, embedding, updated_at
        4. If not: Insert new fact
        5. Enforce memory cap (delete oldest if > 50)
        
        Args:
            user_id: User ID
            fact_content: The fact content (e.g., "User's name is Minh")
            fact_type: Type of fact (name, role, level, goal, preference, weakness)
            confidence: Confidence score (0.0 - 1.0)
            session_id: Optional session ID
            
        Returns:
            True if storage successful
            
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        try:
            # Step 1: Validate and normalize fact_type
            validated_type = self._validate_fact_type(fact_type)
            if validated_type is None:
                logger.debug(f"Fact type '{fact_type}' is invalid/ignored, skipping storage")
                return False
            
            # Step 2: Generate embedding for the fact
            fact_embedding = self._embeddings.embed_documents([fact_content])[0]
            
            # Step 3: Check if fact of same type exists
            existing_fact = self._repository.find_fact_by_type(user_id, validated_type)
            
            metadata = {
                "fact_type": validated_type,
                "confidence": confidence,
                "source": "explicit_save"
            }
            
            if existing_fact:
                # Step 3a: Update existing fact (UPSERT - Update)
                success = self._repository.update_fact(
                    fact_id=existing_fact.id,
                    content=fact_content,
                    embedding=fact_embedding,
                    metadata=metadata
                )
                if success:
                    logger.info(f"Updated user fact for {user_id}: {validated_type}={fact_content[:50]}...")
                return success
            else:
                # Step 3b: Insert new fact (UPSERT - Insert)
                fact_memory = SemanticMemoryCreate(
                    user_id=user_id,
                    content=fact_content,
                    embedding=fact_embedding,
                    memory_type=MemoryType.USER_FACT,
                    importance=confidence,
                    metadata=metadata,
                    session_id=session_id
                )
                
                self._repository.save_memory(fact_memory)
                logger.info(f"Stored new user fact for {user_id}: {validated_type}={fact_content[:50]}...")
                
                # Step 4: Enforce memory cap after insert
                await self._enforce_memory_cap(user_id)
                
                return True
            
        except Exception as e:
            logger.error(f"Failed to store/update user fact: {e}")
            return False
    
    async def _enforce_memory_cap(self, user_id: str) -> int:
        """
        Enforce memory cap by deleting oldest facts.
        
        v0.4 (CHỈ THỊ 23):
        - Count USER_FACT entries for user
        - If count > MAX_USER_FACTS (50): delete oldest (FIFO)
        - Log deletions for audit
        
        Args:
            user_id: User ID
            
        Returns:
            Number of facts deleted
            
        **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
        """
        try:
            # Count current facts
            current_count = self._repository.count_user_memories(
                user_id=user_id,
                memory_type=MemoryType.USER_FACT
            )
            
            if current_count <= self.MAX_USER_FACTS:
                return 0
            
            # Calculate how many to delete
            excess = current_count - self.MAX_USER_FACTS
            
            # Delete oldest facts (FIFO)
            deleted = self._repository.delete_oldest_facts(user_id, excess)
            
            if deleted > 0:
                logger.info(
                    f"Memory cap enforced for user {user_id}: "
                    f"deleted {deleted} oldest facts (was {current_count}, now {current_count - deleted})"
                )
            
            return deleted
            
        except Exception as e:
            logger.error(f"Failed to enforce memory cap: {e}")
            return 0
    
    def is_available(self) -> bool:
        """Check if semantic memory is available."""
        return self._repository.is_available()
    
    def _validate_fact_type(self, fact_type: str) -> Optional[str]:
        """
        Validate and normalize fact_type.
        
        v0.4 (CHỈ THỊ 23):
        - Case-insensitive comparison
        - Maps deprecated types to new types
        - Returns None for ignored/invalid types
        
        Args:
            fact_type: Raw fact type string
            
        Returns:
            Normalized fact type or None if invalid/ignored
            
        **Validates: Requirements 4.1, 4.2, 4.3**
        """
        if not fact_type:
            return None
        
        # Normalize to lowercase
        normalized = fact_type.lower().strip()
        
        # Check if it's an ignored type
        if normalized in IGNORED_FACT_TYPES:
            logger.debug(f"Ignoring fact type: {normalized}")
            return None
        
        # Check if it needs mapping to a new type
        if normalized in FACT_TYPE_MAPPING:
            mapped = FACT_TYPE_MAPPING[normalized]
            logger.debug(f"Mapping deprecated fact type: {normalized} -> {mapped}")
            return mapped
        
        # Check if it's an allowed type
        if normalized in ALLOWED_FACT_TYPES:
            return normalized
        
        # Unknown type - ignore
        logger.warning(f"Unknown fact type ignored: {normalized}")
        return None


    # ==================== INSIGHT ENGINE v0.5 METHODS ====================
    
    def _ensure_insight_components(self):
        """Lazy initialization of Insight Engine components."""
        if self._insight_extractor is None:
            from app.engine.insight_extractor import InsightExtractor
            self._insight_extractor = InsightExtractor()
        
        if self._insight_validator is None:
            from app.engine.insight_validator import InsightValidator
            self._insight_validator = InsightValidator()
        
        if self._memory_consolidator is None:
            from app.engine.memory_consolidator import MemoryConsolidator
            self._memory_consolidator = MemoryConsolidator()
    
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
        2. Validate each insight using InsightValidator
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
        self._ensure_insight_components()
        
        try:
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
                result = self._insight_validator.validate(insight, existing_insights)
                
                if not result.is_valid:
                    logger.debug(f"Insight rejected: {result.reason}")
                    continue
                
                if result.action == "merge":
                    # Merge with existing insight
                    await self._merge_insight(insight, result.target_insight)
                    stored_insights.append(insight)
                    
                elif result.action == "update":
                    # Update existing insight with evolution note
                    await self._update_insight_with_evolution(insight, result.target_insight)
                    stored_insights.append(insight)
                    
                elif result.action == "store":
                    # Store as new insight
                    await self._store_insight(insight, session_id)
                    stored_insights.append(insight)
                    existing_insights.append(insight)  # Add to existing for next validation
            
            # Step 4: Check consolidation threshold
            await self._check_and_consolidate(user_id)
            
            logger.info(f"Stored {len(stored_insights)} insights for user {user_id}")
            return stored_insights
            
        except Exception as e:
            logger.error(f"Failed to extract and store insights: {e}")
            return []
    
    async def _get_user_insights(self, user_id: str) -> List[Insight]:
        """Get all insights for a user."""
        try:
            # Get all INSIGHT type memories
            memories = self._repository.get_user_facts(
                user_id=user_id,
                limit=self.MAX_INSIGHTS,
                deduplicate=False
            )
            
            # Convert to Insight objects
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
            # Generate embedding
            embedding = self._embeddings.embed_documents([insight.content])[0]
            
            # Create memory
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
            # Update existing insight's confidence (average)
            new_confidence = (existing_insight.confidence + new_insight.confidence) / 2
            
            # Add evolution note
            evolution_notes = existing_insight.evolution_notes.copy()
            evolution_notes.append(f"Merged with similar insight: {new_insight.content[:50]}...")
            
            # Update in database
            return self._repository.update_fact(
                fact_id=existing_insight.id,
                content=existing_insight.content,  # Keep existing content
                embedding=None,  # Don't update embedding
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
            # Generate new embedding for updated content
            embedding = self._embeddings.embed_documents([new_insight.content])[0]
            
            # Add evolution note
            evolution_notes = existing_insight.evolution_notes.copy()
            evolution_notes.append(f"Updated from: {existing_insight.content[:50]}...")
            
            # Update in database with new content
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
    
    async def _check_and_consolidate(self, user_id: str) -> bool:
        """
        Check if consolidation is needed and run it.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5**
        """
        self._ensure_insight_components()
        
        try:
            # Count current insights
            current_count = self._repository.count_user_memories(
                user_id=user_id,
                memory_type=MemoryType.INSIGHT
            )
            
            if not await self._memory_consolidator.should_consolidate(current_count):
                return False
            
            logger.info(f"Triggering consolidation for user {user_id} ({current_count} insights)")
            
            # Get all insights
            insights = await self._get_user_insights(user_id)
            
            # Run consolidation
            result = await self._memory_consolidator.consolidate(insights)
            
            if result.success:
                # Delete old insights and store consolidated ones
                self._repository.delete_user_insights(user_id)
                
                for insight in result.consolidated_insights:
                    await self._store_insight(insight)
                
                logger.info(
                    f"Consolidation complete for user {user_id}: "
                    f"{result.original_count} -> {result.final_count} insights"
                )
                return True
            else:
                # Fallback to FIFO eviction
                logger.warning(f"Consolidation failed, using FIFO fallback: {result.error}")
                await self._fifo_eviction(user_id)
                return False
                
        except Exception as e:
            logger.error(f"Consolidation check failed: {e}")
            return False
    
    async def _fifo_eviction(self, user_id: str) -> int:
        """
        FIFO eviction fallback when consolidation fails.
        
        **Validates: Requirements 3.2, 3.4**
        """
        try:
            # Get all insights sorted by last_accessed
            insights = await self._get_user_insights(user_id)
            
            if len(insights) <= self.MAX_INSIGHTS:
                return 0
            
            # Calculate how many to delete
            excess = len(insights) - self.CONSOLIDATION_THRESHOLD  # Target 40 after eviction
            
            # Sort by last_accessed (oldest first)
            sorted_insights = sorted(
                insights,
                key=lambda x: x.last_accessed or x.created_at or datetime.min
            )
            
            # Preserve recent memories (accessed within PRESERVE_DAYS)
            cutoff_date = datetime.now() - timedelta(days=self.PRESERVE_DAYS)
            
            deleted = 0
            for insight in sorted_insights:
                if deleted >= excess:
                    break
                
                # Check if this insight should be preserved
                last_access = insight.last_accessed or insight.created_at
                if last_access and last_access > cutoff_date:
                    continue  # Preserve recent insights
                
                # Delete this insight
                if insight.id:
                    self._repository.delete_memory(insight.id)
                    deleted += 1
            
            logger.info(f"FIFO eviction for user {user_id}: deleted {deleted} insights")
            return deleted
            
        except Exception as e:
            logger.error(f"FIFO eviction failed: {e}")
            return 0
    
    async def update_last_accessed(self, memory_id) -> bool:
        """
        Update last_accessed timestamp for a memory.
        
        **Validates: Requirements 3.3**
        """
        try:
            return self._repository.update_last_accessed(memory_id)
        except Exception as e:
            logger.error(f"Failed to update last_accessed: {e}")
            return False
    
    async def retrieve_insights_prioritized(
        self,
        user_id: str,
        query: str,
        limit: int = 10
    ) -> List[Insight]:
        """
        Retrieve insights with category prioritization.
        
        Prioritizes knowledge_gap and learning_style categories.
        
        **Validates: Requirements 4.3, 4.4**
        """
        try:
            # Get all insights
            all_insights = await self._get_user_insights(user_id)
            
            if not all_insights:
                return []
            
            # Separate by priority
            priority_insights = []
            other_insights = []
            
            for insight in all_insights:
                if insight.category in self.PRIORITY_CATEGORIES:
                    priority_insights.append(insight)
                else:
                    other_insights.append(insight)
            
            # Sort each group by last_accessed (most recent first)
            priority_insights.sort(
                key=lambda x: x.last_accessed or x.created_at or datetime.min,
                reverse=True
            )
            other_insights.sort(
                key=lambda x: x.last_accessed or x.created_at or datetime.min,
                reverse=True
            )
            
            # Combine with priority first
            result = priority_insights + other_insights
            
            # Update last_accessed for retrieved insights
            for insight in result[:limit]:
                if insight.id:
                    await self.update_last_accessed(insight.id)
            
            return result[:limit]
            
        except Exception as e:
            logger.error(f"Failed to retrieve prioritized insights: {e}")
            return []
    
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
            
            # Trigger consolidation first
            consolidated = await self._check_and_consolidate(user_id)
            
            if not consolidated:
                # Force FIFO eviction
                await self._fifo_eviction(user_id)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to enforce hard limit: {e}")
            return False


# Factory function
def get_semantic_memory_engine() -> SemanticMemoryEngine:
    """Get a configured SemanticMemoryEngine instance."""
    return SemanticMemoryEngine()
