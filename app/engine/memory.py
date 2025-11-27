"""
Memori Engine implementation for long-term memory management.

This module provides the concrete implementation of IMemoryEngine
using the Memori (GibsonAI) service for persistent user memory.

**Feature: maritime-ai-tutor**
**Validates: Requirements 3.1, 3.2, 3.3, 3.4**
"""

import logging
from typing import List, Optional
from uuid import UUID

from app.models.memory import (
    IMemoryEngine,
    Memory,
    MemoryContext,
    MemoryType,
    Message,
    create_namespace_for_user,
)

logger = logging.getLogger(__name__)


class MemoriEngine:
    """
    Concrete implementation of IMemoryEngine using Memori service.
    
    This class wraps the Memori (GibsonAI) SDK to provide:
    - Namespace management per user
    - Memory storage with vector embeddings
    - Semantic memory retrieval
    - Conversation summarization
    
    **Validates: Requirements 3.1, 3.2, 3.3, 3.4**
    """
    
    # Threshold for triggering conversation summarization
    SUMMARIZATION_THRESHOLD = 10
    
    # Minimum cosine similarity for relevant memories
    RELEVANCE_THRESHOLD = 0.5
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None
    ):
        """
        Initialize the Memori Engine.
        
        Args:
            api_key: Memori API key (from environment if not provided)
            base_url: Memori service URL
        """
        self._api_key = api_key
        self._base_url = base_url
        self._namespaces: dict[str, bool] = {}  # Track created namespaces
        self._memories: dict[str, List[Memory]] = {}  # In-memory store for dev
        
    async def create_namespace(self, user_id: str) -> str:
        """
        Create a unique namespace for a user.
        
        Pattern: user_{id}_maritime
        
        Args:
            user_id: The user's unique identifier
            
        Returns:
            The created namespace string
            
        **Validates: Requirements 3.1**
        """
        namespace = create_namespace_for_user(user_id)
        
        if namespace not in self._namespaces:
            self._namespaces[namespace] = True
            self._memories[namespace] = []
            logger.info(f"Created namespace: {namespace}")
            
        return namespace

    
    async def store_memory(self, namespace: str, memory: Memory) -> None:
        """
        Store a memory in the specified namespace.
        
        Args:
            namespace: The user's namespace
            memory: The memory object to store
            
        **Validates: Requirements 3.5**
        """
        if namespace not in self._memories:
            self._memories[namespace] = []
            
        # Ensure memory has correct namespace
        memory.namespace = namespace
        self._memories[namespace].append(memory)
        
        logger.debug(f"Stored memory in {namespace}: {memory.id}")
    
    async def retrieve_memories(
        self, 
        namespace: str, 
        query: str, 
        limit: int = 5
    ) -> List[Memory]:
        """
        Retrieve relevant memories based on semantic similarity.
        
        Args:
            namespace: The user's namespace
            query: The search query
            limit: Maximum number of memories to return
            
        Returns:
            List of relevant Memory objects sorted by relevance
            
        **Validates: Requirements 3.3, 3.6**
        """
        if namespace not in self._memories:
            return []
        
        memories = self._memories[namespace]
        
        # Simple keyword matching for development
        # In production, this would use vector similarity search
        relevant = []
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        for memory in memories:
            content_lower = memory.content.lower()
            content_words = set(content_lower.split())
            
            # Calculate simple overlap score
            overlap = len(query_words & content_words)
            if overlap > 0 or any(word in content_lower for word in query_words):
                relevant.append((memory, overlap))
        
        # Sort by relevance and return top results
        relevant.sort(key=lambda x: x[1], reverse=True)
        return [m for m, _ in relevant[:limit]]
    
    async def summarize_conversation(
        self, 
        namespace: str, 
        messages: List[Message]
    ) -> str:
        """
        Summarize conversation when it exceeds threshold.
        
        Triggered when conversation has more than 10 turns.
        
        Args:
            namespace: The user's namespace
            messages: List of messages to summarize
            
        Returns:
            Summarized conversation string
            
        **Validates: Requirements 3.4**
        """
        if len(messages) <= self.SUMMARIZATION_THRESHOLD:
            # No summarization needed
            return ""
        
        # Simple summarization for development
        # In production, this would use LLM-based summarization
        user_messages = [m for m in messages if m.role == "user"]
        topics = set()
        
        for msg in user_messages:
            # Extract potential topics (simple word extraction)
            words = msg.content.split()
            for word in words:
                if len(word) > 4:  # Skip short words
                    topics.add(word.lower())
        
        summary = f"Conversation summary: User discussed topics including {', '.join(list(topics)[:10])}."
        
        # Store summary as semantic memory
        summary_memory = Memory(
            namespace=namespace,
            memory_type=MemoryType.SEMANTIC,
            content=summary,
            entities=list(topics)[:10]
        )
        await self.store_memory(namespace, summary_memory)
        
        logger.info(f"Summarized {len(messages)} messages for {namespace}")
        return summary
    
    async def delete_namespace(self, namespace: str) -> bool:
        """
        Delete all memories in a namespace.
        
        Args:
            namespace: The namespace to delete
            
        Returns:
            True if successful, False otherwise
        """
        if namespace in self._memories:
            del self._memories[namespace]
            del self._namespaces[namespace]
            logger.info(f"Deleted namespace: {namespace}")
            return True
        return False
    
    async def get_memory_context(
        self, 
        namespace: str, 
        query: str
    ) -> MemoryContext:
        """
        Get full memory context for a conversation.
        
        Args:
            namespace: The user's namespace
            query: Current query for relevance
            
        Returns:
            MemoryContext with relevant memories and summary
        """
        memories = await self.retrieve_memories(namespace, query)
        
        # Get semantic memories for summary
        semantic_memories = [
            m for m in self._memories.get(namespace, [])
            if m.memory_type == MemoryType.SEMANTIC
        ]
        
        summary = None
        if semantic_memories:
            # Use most recent summary
            summary = semantic_memories[-1].content
        
        return MemoryContext(
            memories=memories,
            summary=summary,
            user_preferences={}
        )
    
    def is_available(self) -> bool:
        """Check if the memory engine is available."""
        return True  # Always available in dev mode
