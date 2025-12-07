"""
Property-based tests for Agent Orchestrator.

**Feature: maritime-ai-tutor**
**Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.5, 8.2**
"""

import pytest
from uuid import uuid4

from hypothesis import given, settings, strategies as st, assume

from app.engine.graph import (
    AgentOrchestrator,
    AgentRouter,
    AgentType,
    Intent,
    IntentClassifier,
    IntentType,
    KNOWLEDGE_KEYWORDS,
    TEACHING_KEYWORDS,
)
from app.engine.agents.chat_agent import ChatAgent


class TestAgentRoutingCorrectness:
    """
    **Feature: maritime-ai-tutor, Property 4: Agent Routing Correctness**
    
    For any user message with classified intent, the Agent_Orchestrator SHALL
    route to the correct agent: Chat_Agent for GENERAL, RAG_Agent for KNOWLEDGE,
    Tutor_Agent for TEACHING.
    """
    
    @given(keyword=st.sampled_from(list(KNOWLEDGE_KEYWORDS)))
    @settings(max_examples=50)
    def test_knowledge_intent_routes_to_rag(self, keyword):
        """
        **Feature: maritime-ai-tutor, Property 4: Agent Routing Correctness**
        **Validates: Requirements 2.2**
        """
        classifier = IntentClassifier()
        router = AgentRouter()
        
        # Message with knowledge keyword
        message = f"Tell me about {keyword} regulations"
        intent = classifier.classify(message)
        
        # Should classify as KNOWLEDGE
        assert intent.type == IntentType.KNOWLEDGE
        
        # Should route to RAG agent
        agent = router.route(intent)
        assert agent == AgentType.RAG
    
    def test_teaching_intent_routes_to_tutor(self):
        """
        **Feature: maritime-ai-tutor, Property 4: Agent Routing Correctness**
        **Validates: Requirements 2.3**
        """
        classifier = IntentClassifier()
        router = AgentRouter()
        
        # Message with clear teaching intent (using phrase)
        message = "teach me about navigation"
        intent = classifier.classify(message)
        
        # Should classify as TEACHING
        assert intent.type == IntentType.TEACHING
        
        # Should route to TUTOR agent
        agent = router.route(intent)
        assert agent == AgentType.TUTOR
    
    def test_explain_intent_routes_to_tutor(self):
        """Teaching phrases should route to tutor."""
        classifier = IntentClassifier()
        router = AgentRouter()
        
        message = "help me learn about fire safety"
        intent = classifier.classify(message)
        
        assert intent.type == IntentType.TEACHING
        agent = router.route(intent)
        assert agent == AgentType.TUTOR
    
    def test_general_message_routes_to_chat(self):
        """
        **Feature: maritime-ai-tutor, Property 4: Agent Routing Correctness**
        **Validates: Requirements 2.1**
        """
        classifier = IntentClassifier()
        router = AgentRouter()
        
        # General message without specific keywords
        message = "Hello, how are you today?"
        intent = classifier.classify(message)
        
        # Should classify as GENERAL
        assert intent.type == IntentType.GENERAL
        
        # Should route to CHAT agent
        agent = router.route(intent)
        assert agent == AgentType.CHAT



class TestLowConfidenceClarification:
    """
    **Feature: maritime-ai-tutor, Property 5: Low Confidence Clarification**
    
    For any intent classification result with confidence below 0.7,
    the Agent_Orchestrator SHALL return a clarification request.
    """
    
    def test_low_confidence_requires_clarification(self):
        """
        **Feature: maritime-ai-tutor, Property 5: Low Confidence Clarification**
        **Validates: Requirements 2.4**
        """
        # Create intent with low confidence
        intent = Intent(
            type=IntentType.KNOWLEDGE,
            confidence=0.5,
            entities=[]
        )
        
        # Should require clarification
        assert intent.requires_clarification()
    
    def test_high_confidence_does_not_require_clarification(self):
        """High confidence should not require clarification."""
        intent = Intent(
            type=IntentType.KNOWLEDGE,
            confidence=0.8,
            entities=[]
        )
        
        assert not intent.requires_clarification()
    
    @given(confidence=st.floats(min_value=0.0, max_value=0.69))
    @settings(max_examples=50)
    def test_any_low_confidence_requires_clarification(self, confidence):
        """
        **Feature: maritime-ai-tutor, Property 5: Low Confidence Clarification**
        **Validates: Requirements 2.4**
        """
        intent = Intent(
            type=IntentType.GENERAL,
            confidence=confidence,
            entities=[]
        )
        
        router = AgentRouter()
        agent = router.route(intent)
        
        # Should return None (clarification needed)
        assert agent is None
    
    @given(confidence=st.floats(min_value=0.7, max_value=1.0))
    @settings(max_examples=50)
    def test_any_high_confidence_routes_to_agent(self, confidence):
        """High confidence should route to an agent."""
        intent = Intent(
            type=IntentType.GENERAL,
            confidence=confidence,
            entities=[]
        )
        
        router = AgentRouter()
        agent = router.route(intent)
        
        # Should route to an agent
        assert agent is not None
        assert agent == AgentType.CHAT


class TestGracefulDegradationMemory:
    """
    **Feature: maritime-ai-tutor, Property 19: Graceful Degradation - Memory Unavailable**
    
    For any chat request when Memori_Engine is unavailable, the Maritime_AI_Service
    SHALL continue processing and return a valid response.
    """
    
    @pytest.mark.asyncio
    @given(message=st.text(min_size=1, max_size=100).filter(lambda x: x.strip()))
    @settings(max_examples=30, deadline=None)  # LLM calls can be slow
    async def test_chat_works_without_memory(self, message):
        """
        **Feature: maritime-ai-tutor, Property 19: Graceful Degradation - Memory Unavailable**
        **Validates: Requirements 8.2**
        
        Note: Legacy memory removed. ChatAgent now works without memory_engine parameter.
        Personalization is handled by Semantic Memory v0.3 at ChatService level.
        """
        # Create chat agent (no legacy memory parameter)
        agent = ChatAgent()
        
        # Should still process message
        response = await agent.process(
            message=message,
            user_id=str(uuid4())
        )
        
        # Should return valid response
        assert response.content is not None
        assert len(response.content) > 0
    
    @pytest.mark.asyncio
    async def test_chat_without_legacy_memory_works(self):
        """Chat without legacy memory should work (uses Semantic Memory v0.3)."""
        agent = ChatAgent()  # No legacy memory
        
        user_id = str(uuid4())
        
        # First message
        response1 = await agent.process(
            message="Tell me about SOLAS",
            user_id=user_id
        )
        
        # Should work without legacy memory (personalization via Semantic Memory v0.3)
        assert response1.content is not None
        assert len(response1.content) > 0


class TestConversationStateManagement:
    """Test conversation state persistence across turns."""
    
    @given(
        session_id=st.uuids().map(str),
        user_id=st.uuids().map(str)
    )
    @settings(max_examples=30)
    def test_state_persists_across_turns(self, session_id, user_id):
        """
        State should persist across multiple turns.
        **Validates: Requirements 2.5**
        """
        orchestrator = AgentOrchestrator()
        
        # First turn
        response1 = orchestrator.process_message(
            "Hello",
            session_id,
            user_id
        )
        
        # Second turn
        response2 = orchestrator.process_message(
            "Tell me about SOLAS",
            session_id,
            user_id
        )
        
        # State should track turn count
        state = orchestrator.get_or_create_state(session_id, user_id)
        assert state["turn_count"] == 2
        assert len(state["messages"]) == 2
    
    def test_different_sessions_have_separate_state(self):
        """Different sessions should have separate state."""
        orchestrator = AgentOrchestrator()
        user_id = str(uuid4())
        
        session1 = str(uuid4())
        session2 = str(uuid4())
        
        # Process in session 1
        orchestrator.process_message("Hello", session1, user_id)
        orchestrator.process_message("Hi again", session1, user_id)
        
        # Process in session 2
        orchestrator.process_message("New session", session2, user_id)
        
        # States should be separate
        state1 = orchestrator.get_or_create_state(session1, user_id)
        state2 = orchestrator.get_or_create_state(session2, user_id)
        
        assert state1["turn_count"] == 2
        assert state2["turn_count"] == 1


class TestIntentSerialization:
    """Test Intent serialization."""
    
    @given(
        intent_type=st.sampled_from(IntentType),
        confidence=st.floats(min_value=0.0, max_value=1.0)
    )
    @settings(max_examples=50)
    def test_intent_round_trip(self, intent_type, confidence):
        """Intent should serialize and deserialize correctly."""
        intent = Intent(
            type=intent_type,
            confidence=confidence,
            entities=[]
        )
        
        json_str = intent.model_dump_json()
        restored = Intent.model_validate_json(json_str)
        
        assert restored.type == intent.type
        assert restored.confidence == intent.confidence
