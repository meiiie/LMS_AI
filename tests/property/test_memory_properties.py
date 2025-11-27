"""
Property-based tests for Memory Engine.

**Feature: maritime-ai-tutor**
**Validates: Requirements 3.1, 3.3, 3.4, 3.5, 3.6**
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4

from hypothesis import given, settings, strategies as st, assume

from app.models.memory import (
    Memory,
    MemoryType,
    MemoryContext,
    Message,
    create_namespace_for_user,
)


# Custom strategies for Memory objects
@st.composite
def memory_strategy(draw):
    """Generate valid Memory objects for testing."""
    return Memory(
        id=draw(st.uuids()),
        namespace=draw(st.text(min_size=1, max_size=100).filter(lambda x: x.strip())),
        memory_type=draw(st.sampled_from(MemoryType)),
        content=draw(st.text(min_size=1, max_size=1000).filter(lambda x: x.strip())),
        embedding=draw(st.none() | st.lists(st.floats(allow_nan=False, allow_infinity=False), min_size=10, max_size=10)),
        entities=draw(st.lists(st.text(min_size=1, max_size=50).filter(lambda x: x.strip()), max_size=10)),
        created_at=draw(st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2030, 1, 1))),
        updated_at=draw(st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2030, 1, 1))),
    )


@st.composite  
def message_strategy(draw):
    """Generate valid Message objects for testing."""
    return Message(
        role=draw(st.sampled_from(["user", "assistant", "system"])),
        content=draw(st.text(min_size=1, max_size=500).filter(lambda x: x.strip())),
        timestamp=draw(st.datetimes(min_value=datetime(2020, 1, 1), max_value=datetime(2030, 1, 1))),
    )


class TestMemorySerializationRoundTrip:
    """
    **Feature: maritime-ai-tutor, Property 2: Memory Serialization Round-Trip**
    
    For any Memory object with valid content and entities, serializing to JSON
    and then deserializing back SHALL produce an equivalent Memory object.
    """
    
    @given(memory=memory_strategy())
    @settings(max_examples=100)
    def test_memory_json_round_trip(self, memory: Memory):
        """
        **Feature: maritime-ai-tutor, Property 2: Memory Serialization Round-Trip**
        **Validates: Requirements 3.5, 3.6**
        """
        # Serialize to JSON
        json_str = memory.model_dump_json()
        
        # Deserialize back
        restored = Memory.model_validate_json(json_str)
        
        # Verify equivalence
        assert restored.id == memory.id
        assert restored.namespace == memory.namespace
        assert restored.memory_type == memory.memory_type
        assert restored.content == memory.content
        assert restored.entities == memory.entities

    
    @given(memory=memory_strategy())
    @settings(max_examples=100)
    def test_memory_dict_round_trip(self, memory: Memory):
        """
        **Feature: maritime-ai-tutor, Property 2: Memory Serialization Round-Trip**
        **Validates: Requirements 3.5, 3.6**
        """
        # Serialize to dict
        data = memory.model_dump()
        
        # Deserialize back
        restored = Memory.model_validate(data)
        
        # Verify equivalence
        assert restored.id == memory.id
        assert restored.namespace == memory.namespace
        assert restored.memory_type == memory.memory_type
        assert restored.content == memory.content


class TestNamespaceCreationPattern:
    """
    **Feature: maritime-ai-tutor, Property 6: Namespace Creation Pattern**
    
    For any new user_id, the namespace SHALL follow the exact pattern
    `user_{id}_maritime` where {id} is the user's UUID.
    """
    
    @given(user_id=st.uuids())
    @settings(max_examples=100)
    def test_namespace_follows_pattern(self, user_id):
        """
        **Feature: maritime-ai-tutor, Property 6: Namespace Creation Pattern**
        **Validates: Requirements 3.1**
        """
        namespace = create_namespace_for_user(str(user_id))
        
        # Verify pattern
        assert namespace.startswith("user_")
        assert namespace.endswith("_maritime")
        
        # Extract ID part and verify it matches (without hyphens)
        clean_id = str(user_id).replace("-", "")
        expected = f"user_{clean_id}_maritime"
        assert namespace == expected
    
    @given(user_id=st.uuids())
    @settings(max_examples=100)
    def test_namespace_is_deterministic(self, user_id):
        """
        Same user_id should always produce same namespace.
        **Validates: Requirements 3.1**
        """
        namespace1 = create_namespace_for_user(str(user_id))
        namespace2 = create_namespace_for_user(str(user_id))
        
        assert namespace1 == namespace2
    
    @given(user_id1=st.uuids(), user_id2=st.uuids())
    @settings(max_examples=100)
    def test_different_users_get_different_namespaces(self, user_id1, user_id2):
        """
        Different users should get different namespaces.
        **Validates: Requirements 3.1**
        """
        assume(user_id1 != user_id2)
        
        namespace1 = create_namespace_for_user(str(user_id1))
        namespace2 = create_namespace_for_user(str(user_id2))
        
        assert namespace1 != namespace2


class TestMemoryContextSerialization:
    """Test MemoryContext serialization."""
    
    @given(
        memories=st.lists(memory_strategy(), max_size=5),
        summary=st.none() | st.text(min_size=1, max_size=200).filter(lambda x: x.strip())
    )
    @settings(max_examples=50)
    def test_memory_context_round_trip(self, memories, summary):
        """MemoryContext should serialize and deserialize correctly."""
        context = MemoryContext(
            memories=memories,
            summary=summary,
            user_preferences={"theme": "dark"}
        )
        
        # Round trip
        json_str = context.model_dump_json()
        restored = MemoryContext.model_validate_json(json_str)
        
        assert len(restored.memories) == len(memories)
        assert restored.summary == summary


class TestMessageSerialization:
    """Test Message serialization for conversation summarization."""
    
    @given(message=message_strategy())
    @settings(max_examples=100)
    def test_message_round_trip(self, message: Message):
        """Message should serialize and deserialize correctly."""
        json_str = message.model_dump_json()
        restored = Message.model_validate_json(json_str)
        
        assert restored.role == message.role
        assert restored.content == message.content



class TestMemoryRetrievalRelevance:
    """
    **Feature: maritime-ai-tutor, Property 7: Memory Retrieval Contains Relevant Content**
    
    For any query to retrieve memories from a namespace, all returned Memory
    objects SHALL have content semantically related to the query.
    """
    
    @pytest.mark.asyncio
    @given(
        query_word=st.text(alphabet=st.characters(whitelist_categories=('L',)), min_size=3, max_size=20)
    )
    @settings(max_examples=50)
    async def test_retrieved_memories_contain_query_terms(self, query_word):
        """
        **Feature: maritime-ai-tutor, Property 7: Memory Retrieval Contains Relevant Content**
        **Validates: Requirements 3.3**
        """
        from app.engine.memory import MemoriEngine
        
        engine = MemoriEngine()
        namespace = await engine.create_namespace(str(uuid4()))
        
        # Store memories with and without the query word
        relevant_memory = Memory(
            namespace=namespace,
            content=f"This memory contains {query_word} which is relevant",
            memory_type=MemoryType.EPISODIC
        )
        irrelevant_memory = Memory(
            namespace=namespace,
            content="This memory has completely different content xyz123",
            memory_type=MemoryType.EPISODIC
        )
        
        await engine.store_memory(namespace, relevant_memory)
        await engine.store_memory(namespace, irrelevant_memory)
        
        # Retrieve with query
        results = await engine.retrieve_memories(namespace, query_word, limit=5)
        
        # If results returned, they should contain the query term
        if results:
            for memory in results:
                # At least one word from query should be in content
                assert query_word.lower() in memory.content.lower()
    
    @pytest.mark.asyncio
    async def test_empty_namespace_returns_empty_list(self):
        """Empty namespace should return empty list."""
        from app.engine.memory import MemoriEngine
        
        engine = MemoriEngine()
        results = await engine.retrieve_memories("nonexistent_namespace", "any query")
        
        assert results == []
    
    @pytest.mark.asyncio
    async def test_retrieval_respects_limit(self):
        """Retrieval should respect the limit parameter."""
        from app.engine.memory import MemoriEngine
        
        engine = MemoriEngine()
        namespace = await engine.create_namespace(str(uuid4()))
        
        # Store multiple memories with same keyword
        for i in range(10):
            memory = Memory(
                namespace=namespace,
                content=f"Memory {i} about SOLAS regulations",
                memory_type=MemoryType.EPISODIC
            )
            await engine.store_memory(namespace, memory)
        
        # Retrieve with limit
        results = await engine.retrieve_memories(namespace, "SOLAS", limit=3)
        
        assert len(results) <= 3


class TestSummarizationTrigger:
    """
    **Feature: maritime-ai-tutor, Property 8: Summarization Trigger**
    
    For any conversation with more than 10 turns, the Memori_Engine SHALL
    apply recursive summarization, resulting in a summary shorter than original.
    """
    
    @pytest.mark.asyncio
    @given(num_messages=st.integers(min_value=11, max_value=20))
    @settings(max_examples=20)
    async def test_summarization_triggered_above_threshold(self, num_messages):
        """
        **Feature: maritime-ai-tutor, Property 8: Summarization Trigger**
        **Validates: Requirements 3.4**
        """
        from app.engine.memory import MemoriEngine
        
        engine = MemoriEngine()
        namespace = await engine.create_namespace(str(uuid4()))
        
        # Create messages exceeding threshold
        messages = [
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i} about maritime navigation and safety procedures"
            )
            for i in range(num_messages)
        ]
        
        # Summarize
        summary = await engine.summarize_conversation(namespace, messages)
        
        # Summary should be non-empty when above threshold
        assert summary != ""
        
        # Summary should be shorter than concatenated messages
        total_content = " ".join(m.content for m in messages)
        assert len(summary) < len(total_content)
    
    @pytest.mark.asyncio
    @given(num_messages=st.integers(min_value=1, max_value=10))
    @settings(max_examples=20)
    async def test_no_summarization_below_threshold(self, num_messages):
        """
        **Feature: maritime-ai-tutor, Property 8: Summarization Trigger**
        **Validates: Requirements 3.4**
        """
        from app.engine.memory import MemoriEngine
        
        engine = MemoriEngine()
        namespace = await engine.create_namespace(str(uuid4()))
        
        # Create messages below threshold
        messages = [
            Message(
                role="user" if i % 2 == 0 else "assistant",
                content=f"Short message {i}"
            )
            for i in range(num_messages)
        ]
        
        # Summarize
        summary = await engine.summarize_conversation(namespace, messages)
        
        # No summary when below threshold
        assert summary == ""
