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
    INSIGHT = "insight"      # Behavioral insight (v0.5)


class InsightCategory(str, Enum):
    """Categories for behavioral insights (v0.5 - CHỈ THỊ 23 CẢI TIẾN)."""
    LEARNING_STYLE = "learning_style"      # Phong cách học tập
    KNOWLEDGE_GAP = "knowledge_gap"        # Lỗ hổng kiến thức  
    GOAL_EVOLUTION = "goal_evolution"      # Sự thay đổi mục tiêu
    HABIT = "habit"                        # Thói quen học tập
    PREFERENCE = "preference"              # Sở thích cá nhân


class FactType(str, Enum):
    """
    Types of user facts that can be extracted.
    
    v0.4 Update (CHỈ THỊ 23):
    - Limited to 6 essential types for cleaner memory management
    - Deprecated types mapped to new types for backward compatibility
    """
    # Primary types (v0.4 - 6 essential types)
    NAME = "name"                    # User's name
    ROLE = "role"                    # Sinh viên/Giáo viên/Thuyền trưởng
    LEVEL = "level"                  # Năm 3, Đại phó, Sĩ quan...
    GOAL = "goal"                    # Learning goals
    PREFERENCE = "preference"        # Learning preferences/style
    WEAKNESS = "weakness"            # Areas needing improvement
    
    # Deprecated types (kept for backward compatibility, mapped to new types)
    BACKGROUND = "background"        # -> mapped to ROLE
    WEAK_AREA = "weak_area"          # -> mapped to WEAKNESS
    STRONG_AREA = "strong_area"      # -> ignored (not essential)
    INTEREST = "interest"            # -> mapped to PREFERENCE
    LEARNING_STYLE = "learning_style"  # -> mapped to PREFERENCE


# Allowed fact types for v0.4 (6 essential types only)
ALLOWED_FACT_TYPES = {"name", "role", "level", "goal", "preference", "weakness"}

# Mapping deprecated types to new types
FACT_TYPE_MAPPING = {
    "background": "role",
    "weak_area": "weakness",
    "interest": "preference",
    "learning_style": "preference",
}

# Types to ignore (not stored)
IGNORED_FACT_TYPES = {"strong_area"}


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


class Insight(BaseModel):
    """
    Represents a behavioral insight (v0.5 - CHỈ THỊ 23 CẢI TIẾN).
    
    Unlike atomic facts, insights capture behavioral patterns, learning styles,
    knowledge gaps, and goal evolution over time.
    
    Attributes:
        id: Unique identifier
        user_id: User who owns this insight
        content: Complete sentence describing the insight
        category: Type of insight (learning_style, knowledge_gap, etc.)
        sub_topic: Specific topic (e.g., "Rule 15", "COLREGs")
        confidence: Confidence score (0.0 - 1.0)
        source_messages: Messages that led to this insight
        created_at: Creation timestamp
        updated_at: Last update timestamp
        last_accessed: Last access timestamp (for FIFO eviction)
        evolution_notes: Track changes over time
    """
    id: Optional[UUID] = None
    user_id: str
    content: str
    category: InsightCategory
    sub_topic: Optional[str] = None
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    source_messages: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_accessed: Optional[datetime] = None
    evolution_notes: List[str] = Field(default_factory=list)
    
    def to_content(self) -> str:
        """Convert insight to storable content string."""
        return self.content
    
    def to_metadata(self) -> Dict[str, Any]:
        """Convert insight to metadata dict."""
        return {
            "insight_category": self.category.value,
            "sub_topic": self.sub_topic,
            "confidence": self.confidence,
            "source_messages": self.source_messages,
            "evolution_notes": self.evolution_notes
        }
    
    class Config:
        from_attributes = True


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
        
        Cross-session Memory Persistence (v0.2.1):
        - User facts appear at TOP of context (highest priority)
        - Facts are grouped by type for better readability
        - Includes relevant memories from all sessions
        
        Returns:
            Formatted context string
            
        Requirements: 2.2, 4.3
        **Feature: cross-session-memory, Property 5: Context Includes User Facts**
        """
        parts = []
        
        # Add user facts section (FIRST - highest priority for personalization)
        if self.user_facts:
            # Group facts by type for better formatting
            facts_by_type = self._group_facts_by_type()
            
            facts_lines = []
            # Priority order for fact types
            type_order = ["name", "background", "goal", "weak_area", "strong_area", 
                         "interest", "preference", "learning_style"]
            
            for fact_type in type_order:
                if fact_type in facts_by_type:
                    fact = facts_by_type[fact_type]
                    # Format based on type
                    type_labels = {
                        "name": "Tên",
                        "background": "Nghề nghiệp",
                        "goal": "Mục tiêu học tập",
                        "weak_area": "Điểm yếu",
                        "strong_area": "Điểm mạnh",
                        "interest": "Quan tâm",
                        "preference": "Sở thích",
                        "learning_style": "Phong cách học"
                    }
                    label = type_labels.get(fact_type, fact_type.replace("_", " ").title())
                    # Extract value from content (format: "fact_type: value")
                    value = fact.content.split(": ", 1)[-1] if ": " in fact.content else fact.content
                    facts_lines.append(f"- {label}: {value}")
            
            # Add any remaining facts not in priority order
            for fact_type, fact in facts_by_type.items():
                if fact_type not in type_order:
                    value = fact.content.split(": ", 1)[-1] if ": " in fact.content else fact.content
                    facts_lines.append(f"- {fact_type}: {value}")
            
            if facts_lines:
                parts.append(f"=== Hồ sơ người dùng ===\n" + "\n".join(facts_lines))
        
        # Add relevant memories section
        if self.relevant_memories:
            memories_text = "\n".join([
                f"- {m.content}"
                for m in self.relevant_memories[:5]  # Limit to top 5
            ])
            parts.append(f"=== Ngữ cảnh liên quan ===\n{memories_text}")
        
        # Add recent messages section
        if self.recent_messages:
            recent_text = "\n".join(self.recent_messages[-5:])  # Last 5 messages
            parts.append(f"=== Hội thoại gần đây ===\n{recent_text}")
        
        return "\n\n".join(parts) if parts else ""
    
    def _group_facts_by_type(self) -> Dict[str, "SemanticMemorySearchResult"]:
        """
        Group user facts by fact_type from metadata.
        
        Returns:
            Dict mapping fact_type to the most recent fact of that type
        """
        facts_by_type = {}
        for fact in self.user_facts:
            fact_type = fact.metadata.get("fact_type", "unknown")
            # Keep first occurrence (already sorted by recency from repository)
            if fact_type not in facts_by_type:
                facts_by_type[fact_type] = fact
        return facts_by_type
    
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
