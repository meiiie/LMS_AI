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
    ChatResponseData,
    ChatResponseMetadata,
    ComponentHealth,
    ComponentStatus,
    ErrorResponse,
    HealthResponse,
    RateLimitResponse,
    Source,
    SourceInfo,
    UserRole,
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

# Strategy for user_id (string, not UUID)
user_id_strategy = st.text(min_size=1, max_size=50).filter(lambda x: x.strip())

# Strategy for optional context
context_strategy = st.one_of(
    st.none(),
    st.dictionaries(
        keys=st.text(min_size=1, max_size=20).filter(lambda x: x.strip()),
        values=st.text(max_size=100),
        max_size=3,
    )
)

# Strategy for ChatRequest (updated for new schema)
chat_request_strategy = st.builds(
    ChatRequest,
    user_id=user_id_strategy,
    message=valid_message_strategy,
    role=st.sampled_from(list(UserRole)),
    session_id=st.one_of(st.none(), st.text(min_size=1, max_size=50).filter(lambda x: x.strip())),
    context=context_strategy,
)

# Strategy for SourceInfo (new schema)
source_info_strategy = st.builds(
    SourceInfo,
    title=st.text(min_size=1, max_size=200).filter(lambda x: x.strip()),
    content=st.text(min_size=1, max_size=500).filter(lambda x: x.strip()),
)

# Strategy for ChatResponseData
chat_response_data_strategy = st.builds(
    ChatResponseData,
    answer=valid_message_strategy,
    sources=st.lists(source_info_strategy, min_size=0, max_size=3),
    suggested_questions=st.lists(
        st.text(min_size=1, max_size=100).filter(lambda x: x.strip()),
        min_size=0,
        max_size=3,
    ),
)

# Strategy for ChatResponseMetadata
chat_response_metadata_strategy = st.builds(
    ChatResponseMetadata,
    processing_time=st.floats(min_value=0.01, max_value=100.0, allow_nan=False),
    model=st.just("maritime-rag-v1"),
    agent_type=st.sampled_from(list(AgentType)),
)

# Strategy for ChatResponse (updated for new schema)
chat_response_strategy = st.builds(
    ChatResponse,
    status=st.just("success"),
    data=chat_response_data_strategy,
    metadata=chat_response_metadata_strategy,
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
        assert restored.role == request.role
        assert restored.session_id == request.session_id
        assert restored.context == request.context
    
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
        assert restored.status == response.status
        assert restored.data.answer == response.data.answer
        assert restored.metadata.agent_type == response.metadata.agent_type
        
        # Check sources
        assert len(restored.data.sources) == len(response.data.sources)
        for orig, rest in zip(response.data.sources, restored.data.sources):
            assert orig.title == rest.title
            assert orig.content == rest.content
    
    @given(chat_response_strategy)
    @settings(max_examples=100, deadline=None)
    def test_chat_response_dict_round_trip(self, response: ChatResponse):
        """
        Property: from_dict(to_dict(ChatResponse)) == ChatResponse
        """
        # Convert to dict
        data = response.model_dump()
        
        # Restore from dict
        restored = ChatResponse.model_validate(data)
        
        # Assert key fields match
        assert restored.status == response.status
        assert restored.data.answer == response.data.answer
        assert restored.metadata.agent_type == response.metadata.agent_type


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
                user_id="test_user",
                message="",
                role=UserRole.STUDENT,
            )
    
    def test_chat_request_rejects_whitespace_only_message(self):
        """Whitespace-only messages should be rejected"""
        with pytest.raises(ValueError):
            ChatRequest(
                user_id="test_user",
                message="   \n\t  ",
                role=UserRole.STUDENT,
            )
    
    def test_chat_request_trims_message(self):
        """Messages should be trimmed"""
        request = ChatRequest(
            user_id="test_user",
            message="  Hello World  ",
            role=UserRole.STUDENT,
        )
        assert request.message == "Hello World"
