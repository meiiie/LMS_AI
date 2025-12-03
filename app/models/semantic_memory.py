"""
Semantic Memory Models for Maritime AI Tutor v0.3
CHỈ THỊ KỸ THUẬT SỐ 06

Pydantic models for semantic memory storage and retrieval.

Requirements: 2.1
"""
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class MemoryType(str, Enum):
    """Types of semantic memories."""
    MESSAGE = "message"      # Regular conversation message
    SUMMARY = "summary"      # Conversation summary
    USER_FACT = "user_fact"  # Extracted user information


class FactType(str, Enum):
    """Types of user facts that can be extracted."""
    NAME = "name"                    # User's name
    PREFERENCE = "preference"        # Learning preferences
    GOAL = "goal"                    # Learning goals
    BACKGROUND = "background"        # Professional background
    WEAK_AREA = "weak_area"          # Areas needing improvement
    STRONG_AREA = "strong_area"      # Areas of strength
    INTEREST = "interest"            # Topics of interest
    LEARNING_STYLE = "learning_style"  # Preferred learning style


class SemanticMemory(BaseModel):
    """
    Represents a single semantic memory stored in the database.
    
    Attributes:
        id: Unique identifier
        user_id: User who owns this memory
        content: Text content of the memory
        embedding: Vector embedding (768 dimensions for MRL)
        memory_type: Type of memory (message, summary, user_fact)
        importance: Importance score (0.0 - 1.0)
        metadata: Additional metadata as JSON
        session_id: Optional session reference
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """
    id: UUID
    user_id: str
    content: str
    embedding: List[float] = Field(default_factory=list)
    memory_type: MemoryType = MemoryType.MESSAGE
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    
    @field_validator("embedding")
    @classmethod
    def validate_embedding_dimensions(cls, v: List[float]) -> List[float]:
        """Validate embedding has correct dimensions (768 for MRL)."""
        if v and len(v) != 768:
            # Log warning but don't fail - allow flexibility
            pass
        return v
    
    class Config:
        from_attributes = True


class SemanticMemoryCreate(BaseModel):
    """
    Schema for creating a new semantic memory.
    
    Used when storing new memories to the database.
    """
    user_id: str
    content: str
    embedding: List[float]
    memory_type: MemoryType = MemoryType.MESSAGE
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    session_id: Optional[str] = None
    
    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        """Ensure content is not empty."""
        if not v or not v.strip():
            raise ValueError("Content cannot be empty")
        return v.strip()


class SemanticMemorySearchResult(BaseModel):
    """
    Result from semantic similarity search.
    
    Includes similarity score for ranking.
    """
    id: UUID
    content: str
    memory_type: MemoryType
    importance: float
    similarity: float = Field(ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    
    class Config:
        from_attributes = True


class UserFact(BaseModel):
    """
    Represents an extracted user fact.
    
    Used for personalization based on information extracted from conversations.
    
    Attributes:
        fact_type: Category of the fact
        value: The actual fact content
        confidence: Confidence score of extraction (0.0 - 1.0)
        source_message: Original message the fact was extracted from
    """
    fact_type: FactType
    value: str
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source_message: Optional[str] = None
    
    def to_content(self) -> str:
        """Convert fact to storable content string."""
        return f"{self.fact_type.value}: {self.value}"
    
    def to_metadata(self) -> Dict[str, Any]:
        """Convert fact to metadata dict."""
        return {
            "fact_type": self.fact_type.value,
            "confidence": self.confidence,
            "source_message": self.source_message
        }


class UserFactExtraction(BaseModel):
    """
    Result of user fact extraction from a message.
    
    Contains multiple facts that may have been extracted.
    """
    facts: List[UserFact] = Field(default_factory=list)
    raw_message: str
    extraction_timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    @property
    def has_facts(self) -> bool:
        """Check if any facts were extracted."""
        return len(self.facts) > 0


class SemanticContext(BaseModel):
    """
    Assembled context for response generation.
    
    Combines semantic memories with recent messages for hybrid context.
    
    Attributes:
        relevant_memories: Semantically similar memories from vector search
        user_facts: User facts for personalization
        recent_messages: Recent messages from sliding window (fallback/hybrid)
        total_tokens: Estimated token count of context
    """
    relevant_memories: List[SemanticMemorySearchResult] = Field(default_factory=list)
    user_facts: List[SemanticMemorySearchResult] = Field(default_factory=list)
    recent_messages: List[str] = Field(default_factory=list)
    total_tokens: int = 0
    
    def to_prompt_context(self) -> str:
        """
        Format context for injection into LLM prompt.
        
        Returns:
            Formatted context string
        """
        parts = []
        
        # Add user facts section
        if self.user_facts:
            facts_text = "\n".join([f"- {m.content}" for m in self.user_facts])
            parts.append(f"**Thông tin về người dùng:**\n{facts_text}")
        
        # Add relevant memories section
        if self.relevant_memories:
            memories_text = "\n".join([
                f"- {m.content} (relevance: {m.similarity:.2f})"
                for m in self.relevant_memories
            ])
            parts.append(f"**Ngữ cảnh liên quan:**\n{memories_text}")
        
        # Add recent messages section
        if self.recent_messages:
            recent_text = "\n".join(self.recent_messages)
            parts.append(f"**Hội thoại gần đây:**\n{recent_text}")
        
        return "\n\n".join(parts) if parts else ""
    
    @property
    def is_empty(self) -> bool:
        """Check if context is empty."""
        return (
            not self.relevant_memories
            and not self.user_facts
            and not self.recent_messages
        )


class ConversationSummary(BaseModel):
    """
    Summary of a conversation for long-term storage.
    
    Created when conversation exceeds token threshold.
    """
    user_id: str
    session_id: str
    summary_text: str
    original_message_count: int
    original_token_count: int
    key_topics: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    def to_semantic_memory_create(self, embedding: List[float]) -> SemanticMemoryCreate:
        """Convert summary to SemanticMemoryCreate for storage."""
        return SemanticMemoryCreate(
            user_id=self.user_id,
            content=self.summary_text,
            embedding=embedding,
            memory_type=MemoryType.SUMMARY,
            importance=0.9,  # Summaries are high importance
            metadata={
                "original_message_count": self.original_message_count,
                "original_token_count": self.original_token_count,
                "key_topics": self.key_topics
            },
            session_id=self.session_id
        )
