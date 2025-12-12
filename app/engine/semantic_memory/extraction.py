"""
Fact Extraction Module for Semantic Memory
CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure

Handles fact extraction from conversations and storage.
Extracted from semantic_memory.py for better modularity.

Requirements: 4.1, 4.2, 4.3
"""
import json
import logging
from typing import List, Optional

from app.core.config import settings
from app.models.semantic_memory import (
    ALLOWED_FACT_TYPES,
    FACT_TYPE_MAPPING,
    IGNORED_FACT_TYPES,
    FactType,
    MemoryType,
    SemanticMemoryCreate,
    UserFact,
    UserFactExtraction,
)
from app.repositories.semantic_memory_repository import SemanticMemoryRepository
from app.engine.gemini_embedding import GeminiOptimizedEmbeddings

logger = logging.getLogger(__name__)


class FactExtractor:
    """
    Handles fact extraction and storage operations.
    
    Responsibilities:
    - Extract user facts from messages using LLM
    - Store facts with upsert logic
    - Enforce memory caps
    
    Requirements: 4.1, 4.2, 4.3
    """
    
    # Configuration
    MAX_USER_FACTS = 50  # Memory cap (CHỈ THỊ 23)
    
    def __init__(
        self,
        embeddings: GeminiOptimizedEmbeddings,
        repository: SemanticMemoryRepository,
        llm=None
    ):
        """
        Initialize FactExtractor.
        
        Args:
            embeddings: GeminiOptimizedEmbeddings instance
            repository: SemanticMemoryRepository instance
            llm: Optional LLM for fact extraction
        """
        self._embeddings = embeddings
        self._repository = repository
        self._llm = llm
        logger.debug("FactExtractor initialized")
    
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
    
    async def extract_and_store_facts(
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
            
            # Step 3: SOTA - Check for semantic duplicate first
            # Find existing fact with high embedding similarity (>= 0.90)
            semantic_duplicate = self._repository.find_similar_fact_by_embedding(
                user_id=user_id,
                embedding=fact_embedding,
                similarity_threshold=0.90,  # SOTA threshold
                memory_type=MemoryType.USER_FACT
            )
            
            metadata = {
                "fact_type": validated_type,
                "confidence": confidence,
                "source": "explicit_save"
            }
            
            if semantic_duplicate:
                # SOTA: Update semantically similar fact
                logger.info(f"Found semantic duplicate for {validated_type}, updating...")
                success = self._repository.update_fact(
                    fact_id=semantic_duplicate.id,
                    content=fact_content,
                    embedding=fact_embedding,
                    metadata=metadata
                )
                if success:
                    logger.info(f"Updated similar fact for {user_id}: {validated_type}={fact_content[:50]}...")
                return success
            
            # Step 4: Fallback - Check if fact of same type exists
            existing_fact = self._repository.find_fact_by_type(user_id, validated_type)
            
            if existing_fact:
                # Step 4a: Update existing fact (UPSERT - Update)
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
                # Step 4b: Insert new fact (UPSERT - Insert)
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
                
                # Step 5: Enforce memory cap after insert
                await self._enforce_memory_cap(user_id)
                
                return True
            
        except Exception as e:
            logger.error(f"Failed to store/update user fact: {e}")
            return False
    
    def _validate_fact_type(self, fact_type: str) -> Optional[str]:
        """
        Validate and normalize fact_type.
        
        Args:
            fact_type: Raw fact type string
            
        Returns:
            Normalized fact type or None if invalid/ignored
        """
        # Normalize to lowercase
        normalized = fact_type.lower().strip()
        
        # Check if in ignored types
        if normalized in IGNORED_FACT_TYPES:
            return None
        
        # Check if in allowed types
        if normalized in ALLOWED_FACT_TYPES:
            return normalized
        
        # Check mapping
        if normalized in FACT_TYPE_MAPPING:
            return FACT_TYPE_MAPPING[normalized]
        
        # Default to None (invalid)
        logger.debug(f"Unknown fact type: {fact_type}")
        return None
    
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
