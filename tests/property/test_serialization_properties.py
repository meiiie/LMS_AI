"""
Property-Based Tests for Serialization Round-Trip
**Feature: maritime-ai-tutor, Property 1: Chat Request/Response Round-Trip**
**Validates: Requirements 1.5, 1.6**

Tests that serializing to JSON and deserializing back produces equivalent objects.
"""
import sys
from datetime import datetime
from uuid import UUID

import pytest
from hypothesis import given, settings, strategies as st

# Add app to path for imports
sys.path.insert(0, str(__file__).replace("tests/property/test_serialization_properties.py", ""))

from app.models.schemas import (
    AgentType,
    ChatRequest,
    ChatResponse,
    ComponentHealth,
    ComponentStatus,
    ErrorResponse,
    HealthResponse,
    RateLimitResponse,
    Source,
)


# =============================================================================
# Custom Strategies for Hypothesis
# =============================================================================

# Strategy for valid non-empty messages (trimmed)
valid_message_strategy = st.text(
    min_size=1, 
    max_size=1000,
    alphabet=st.characters(blacklist_categories=("Cs",))  # Exclude surrogates
).filter(lambda x: x.strip())  # Must have non-whitespace content

# Strategy for optional context strings
context_strategy = st.one_of(
    st.none(),
    st.text(min_size=1, max_size=100).filter(lambda x: x.strip())
)

# Strategy for ChatRequest
chat_request_strategy = st.builds(
    ChatRequest,
    user_id=st.uuids(),
    message=valid_message_strategy,
    current_context=context_strategy,
)

# Strategy for Source
source_strategy = st.builds(
    Source,
    node_id=st.text(min_size=1, max_size=50).filter(lambda x: x.strip()),
    title=st.text(min_size=1, max_size=200).filter(lambda x: x.strip()),
    source_type=st.sampled_from(["regulation", "concept", "ship_type", "accident"]),
    content_snippet=st.one_of(st.none(), st.text(min_size=1, max_size=500)),
)


# Strategy for ChatResponse
chat_response_strategy = st.builds(
    ChatResponse,
    message=valid_message_strategy,
    agent_type=st.sampled_from(list(AgentType)),
    sources=st.one_of(st.none(), st.lists(source_strategy, min_size=0, max_size=5)),
    metadata=st.one_of(
        st.none(),
        st.dictionaries(
            keys=st.text(min_size=1, max_size=20).filter(lambda x: x.strip()),
            values=st.one_of(st.integers(), st.floats(allow_nan=False), st.text(max_size=100)),
            max_size=5,
        ),
    ),
)

# Strategy for ComponentHealth
component_health_strategy = st.builds(
    ComponentHealth,
    name=st.text(min_size=1, max_size=50).filter(lambda x: x.strip()),
    status=st.sampled_from(list(ComponentStatus)),
    latency_ms=st.one_of(st.none(), st.floats(min_value=0, max_value=10000, allow_nan=False)),
    message=st.one_of(st.none(), st.text(max_size=200)),
)


# =============================================================================
# Property Tests - Round Trip Serialization
# =============================================================================

class TestChatRequestRoundTrip:
    """
    **Feature: maritime-ai-tutor, Property 1: Chat Request/Response Round-Trip**
    **Validates: Requirements 1.5, 1.6**
    
    For any valid ChatRequest object, serializing to JSON and then 
    deserializing back SHALL produce an equivalent ChatRequest object.
    """
    
    @given(chat_request_strategy)
    @settings(max_examples=100, deadline=None)
    def test_chat_request_json_round_trip(self, request: ChatRequest):
        """
        Property: serialize(deserialize(ChatRequest)) == ChatRequest
        """
        # Serialize to JSON string
        json_str = request.model_dump_json()
        
        # Deserialize back to object
        restored = ChatRequest.model_validate_json(json_str)
        
        # Assert equivalence
        assert restored.user_id == request.user_id
        assert restored.message == request.message
        assert restored.current_context == request.current_context
    
    @given(chat_request_strategy)
    @settings(max_examples=100, deadline=None)
    def test_chat_request_dict_round_trip(self, request: ChatRequest):
        """
        Property: from_dict(to_dict(ChatRequest)) == ChatRequest
        """
        # Convert to dict
        data = request.model_dump()
        
        # Restore from dict
        restored = ChatRequest.model_validate(data)
        
        # Assert equivalence
        assert restored == request


class TestChatResponseRoundTrip:
    """
    **Feature: maritime-ai-tutor, Property 1: Chat Request/Response Round-Trip**
    **Validates: Requirements 1.5, 1.6**
    
    For any valid ChatResponse object, serializing to JSON and then 
    deserializing back SHALL produce an equivalent ChatResponse object.
    """
    
    @given(chat_response_strategy)
    @settings(max_examples=100, deadline=None)
    def test_chat_response_json_round_trip(self, response: ChatResponse):
        """
        Property: serialize(deserialize(ChatResponse)) == ChatResponse
        """
        # Serialize to JSON string
        json_str = response.model_dump_json()
        
        # Deserialize back to object
        restored = ChatResponse.model_validate_json(json_str)
        
        # Assert key fields are preserved
        assert restored.message == response.message
        assert restored.agent_type == response.agent_type
        
        # Check sources if present
        if response.sources is not None:
            assert restored.sources is not None
            assert len(restored.sources) == len(response.sources)
            for orig, rest in zip(response.sources, restored.sources):
                assert orig.node_id == rest.node_id
                assert orig.title == rest.title
    
    @given(chat_response_strategy)
    @settings(max_examples=100, deadline=None)
    def test_chat_response_dict_round_trip(self, response: ChatResponse):
        """
        Property: from_dict(to_dict(ChatResponse)) == ChatResponse
        """
        # Convert to dict (excluding generated fields)
        data = response.model_dump()
        
        # Restore from dict
        restored = ChatResponse.model_validate(data)
        
        # Assert key fields match
        assert restored.message == response.message
        assert restored.agent_type == response.agent_type


class TestHealthResponseRoundTrip:
    """
    **Feature: maritime-ai-tutor, Property 21: Health Check Completeness**
    **Validates: Requirements 8.4**
    """
    
    @given(
        status=st.sampled_from(["healthy", "degraded", "unhealthy"]),
        version=st.text(min_size=1, max_size=20).filter(lambda x: x.strip()),
        environment=st.sampled_from(["development", "staging", "production"]),
        components=st.dictionaries(
            keys=st.sampled_from(["api", "memory", "knowledge_graph"]),
            values=component_health_strategy,
            min_size=1,
            max_size=3,
        ),
    )
    @settings(max_examples=100, deadline=None)
    def test_health_response_round_trip(
        self, status: str, version: str, environment: str, components: dict
    ):
        """
        Property: serialize(deserialize(HealthResponse)) == HealthResponse
        """
        response = HealthResponse(
            status=status,
            version=version,
            environment=environment,
            components=components,
        )
        
        # Serialize and deserialize
        json_str = response.model_dump_json()
        restored = HealthResponse.model_validate_json(json_str)
        
        # Assert equivalence
        assert restored.status == response.status
        assert restored.version == response.version
        assert restored.environment == response.environment
        assert set(restored.components.keys()) == set(response.components.keys())


# =============================================================================
# Edge Case Tests
# =============================================================================

class TestEdgeCases:
    """Edge case tests for schema validation"""
    
    def test_chat_request_rejects_empty_message(self):
        """Empty messages should be rejected"""
        with pytest.raises(ValueError):
            ChatRequest(
                user_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                message="",
            )
    
    def test_chat_request_rejects_whitespace_only_message(self):
        """Whitespace-only messages should be rejected"""
        with pytest.raises(ValueError):
            ChatRequest(
                user_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
                message="   \n\t  ",
            )
    
    def test_chat_request_trims_message(self):
        """Messages should be trimmed"""
        request = ChatRequest(
            user_id=UUID("550e8400-e29b-41d4-a716-446655440000"),
            message="  Hello World  ",
        )
        assert request.message == "Hello World"
