"""
Memory domain models for Memori Engine.

This module defines the core data structures for the long-term memory system,
including Memory objects, MemoryType enum, and the IMemoryEngine interface.

**Feature: maritime-ai-tutor**
**Validates: Requirements 3.1, 3.5, 3.6**
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional, Protocol
from uuid import UUID, uuid4


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)

from pydantic import BaseModel, Field


class MemoryType(str, Enum):
    """Types of memory stored in the system."""
    EPISODIC = "episodic"  # Specific events/conversations
    SEMANTIC = "semantic"  # General knowledge/facts about user


class Memory(BaseModel):
    """
    Represents a single memory unit stored in the Memori Engine.
    
    Attributes:
        id: Unique identifier for the memory
        namespace: User-specific namespace (pattern: user_{id}_maritime)
        memory_type: Type of memory (EPISODIC or SEMANTIC)
        content: The actual memory content
        embedding: Vector embedding for similarity search
        entities: Extracted entities from the content
        created_at: Timestamp when memory was created
        updated_at: Timestamp when memory was last updated
    """
    id: UUID = Field(default_factory=uuid4)
    namespace: str = Field(..., min_length=1)
    memory_type: MemoryType = Field(default=MemoryType.EPISODIC)
    content: str = Field(..., min_length=1)
    embedding: Optional[List[float]] = Field(default=None)
    entities: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "namespace": "user_123_maritime",
                "memory_type": "episodic",
                "content": "User asked about SOLAS Chapter II-2 fire safety",
                "entities": ["SOLAS", "fire safety", "Chapter II-2"],
                "created_at": "2024-01-15T10:30:00Z"
            }
        }
    }


class MemoryContext(BaseModel):
    """
    Context retrieved from memory for conversation.
    
    Attributes:
        memories: List of relevant memories
        summary: Summarized context from past conversations
        user_preferences: Extracted user preferences
    """
    memories: List[Memory] = Field(default_factory=list)
    summary: Optional[str] = Field(default=None)
    user_preferences: dict = Field(default_factory=dict)


class Message(BaseModel):
    """
    Represents a single message in a conversation.
    
    Used for conversation summarization.
    """
    role: str = Field(..., pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1)
    timestamp: datetime = Field(default_factory=_utc_now)


class IMemoryEngine(Protocol):
    """
    Interface for Memory Engine implementations.
    
    This protocol defines the contract that any memory engine must implement,
    following the Dependency Inversion Principle.
    """
    
    async def create_namespace(self, user_id: str) -> str:
        """
        Create a unique namespace for a user.
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            The created namespace string (pattern: user_{id}_maritime)
        """
        ...
    
    async def store_memory(self, namespace: str, memory: Memory) -> None:
        """
        Store a memory in the specified namespace.
        
        Args:
            namespace: The user's namespace
            memory: The memory object to store
        """
        ...
    
    async def retrieve_memories(
        self, 
        namespace: str, 
        query: str, 
        limit: int = 5
    ) -> List[Memory]:
        """
        Retrieve relevant memories based on a query.
        
        Args:
            namespace: The user's namespace
            query: The search query
            limit: Maximum number of memories to return
            
        Returns:
            List of relevant Memory objects
        """
        ...
    
    async def summarize_conversation(
        self, 
        namespace: str, 
        messages: List[Message]
    ) -> str:
        """
        Summarize a conversation when it exceeds threshold.
        
        Args:
            namespace: The user's namespace
            messages: List of messages to summarize
            
        Returns:
            Summarized conversation string
        """
        ...
    
    async def delete_namespace(self, namespace: str) -> bool:
        """
        Delete all memories in a namespace.
        
        Args:
            namespace: The namespace to delete
            
        Returns:
            True if successful, False otherwise
        """
        ...


def create_namespace_for_user(user_id: str) -> str:
    """
    Create a namespace string following the pattern user_{id}_maritime.
    
    Args:
        user_id: The user's unique identifier (UUID string)
        
    Returns:
        Formatted namespace string
        
    **Validates: Requirements 3.1**
    """
    # Remove hyphens from UUID for cleaner namespace
    clean_id = str(user_id).replace("-", "")
    return f"user_{clean_id}_maritime"
