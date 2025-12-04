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
from app.models.semantic_memory import (
    ConversationSummary,
    FactType,
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
        
        logger.info("SemanticMemoryEngine initialized")
    
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
            
            # Store each fact as a semantic memory
            for fact in extraction.facts:
                fact_content = fact.to_content()
                fact_embedding = self._embeddings.embed_documents([fact_content])[0]
                
                fact_memory = SemanticMemoryCreate(
                    user_id=user_id,
                    content=fact_content,
                    embedding=fact_embedding,
                    memory_type=MemoryType.USER_FACT,
                    importance=fact.confidence,
                    metadata=fact.to_metadata(),
                    session_id=session_id
                )
                self._repository.save_memory(fact_memory)
            
            logger.info(f"Extracted {len(extraction.facts)} facts for user {user_id}")
            return extraction.facts
            
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
    
    def is_available(self) -> bool:
        """Check if semantic memory is available."""
        return self._repository.is_available()


# Factory function
def get_semantic_memory_engine() -> SemanticMemoryEngine:
    """Get a configured SemanticMemoryEngine instance."""
    return SemanticMemoryEngine()
