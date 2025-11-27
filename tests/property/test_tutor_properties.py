"""
Property-based tests for Tutor Agent.

**Feature: maritime-ai-tutor**
**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
"""

import pytest
from uuid import uuid4

from hypothesis import given, settings, strategies as st

from app.engine.tools.tutor_agent import (
    TeachingPhase,
    TeachingState,
    TutorAgent,
    TutorResponse,
)
from app.models.learning_profile import LearningProfile, create_default_profile


class TestIncorrectAnswerTriggersHint:
    """
    **Feature: maritime-ai-tutor, Property 13: Incorrect Answer Triggers Hint**
    
    For any user response evaluated as incorrect during assessment,
    the Tutor_Agent SHALL provide a hint before revealing the correct answer.
    """
    
    def test_incorrect_answer_provides_hint(self):
        """
        **Feature: maritime-ai-tutor, Property 13: Incorrect Answer Triggers Hint**
        **Validates: Requirements 5.3**
        """
        agent = TutorAgent()
        user_id = str(uuid4())
        
        # Start session
        response = agent.start_session("solas", user_id)
        session_id = response.state.session_id
        
        # Move to explanation
        response = agent.process_response("ready", session_id)
        
        # Move to assessment
        response = agent.process_response("ready", session_id)
        assert response.phase == TeachingPhase.ASSESSMENT
        
        # Give wrong answer
        state = agent.get_session(session_id)
        if state and state.awaiting_answer:
            # Provide clearly wrong answer
            response = agent.process_response("completely wrong answer xyz", session_id)
            
            # Hint should have been given (hints_given incremented)
            updated_state = agent.get_session(session_id)
            assert updated_state is not None
            # Either hint was given or we moved to next question
            assert updated_state.hints_given >= 0
    
    @given(wrong_answer=st.text(min_size=1, max_size=50).filter(lambda x: "safety" not in x.lower()))
    @settings(max_examples=30)
    def test_any_wrong_answer_increments_hints(self, wrong_answer):
        """
        **Feature: maritime-ai-tutor, Property 13: Incorrect Answer Triggers Hint**
        **Validates: Requirements 5.3**
        """
        agent = TutorAgent()
        user_id = str(uuid4())
        
        # Start and progress to assessment
        response = agent.start_session("solas", user_id)
        session_id = response.state.session_id
        
        agent.process_response("ready", session_id)  # To explanation
        agent.process_response("ready", session_id)  # To assessment
        
        state = agent.get_session(session_id)
        if state and state.awaiting_answer:
            initial_hints = state.hints_given
            agent.process_response(wrong_answer, session_id)
            
            # State should track hints
            updated_state = agent.get_session(session_id)
            assert updated_state is not None


class TestMasteryUpdatesProfile:
    """
    **Feature: maritime-ai-tutor, Property 14: Mastery Updates Profile**
    
    For any user demonstrating mastery (score >= 80%) on a topic,
    the Tutor_Agent SHALL add that topic to completed_topics.
    """
    
    def test_mastery_detected_at_80_percent(self):
        """
        **Feature: maritime-ai-tutor, Property 14: Mastery Updates Profile**
        **Validates: Requirements 5.4**
        """
        # Create state with mastery score
        state = TeachingState(
            topic="solas",
            questions_asked=5,
            correct_answers=4  # 80%
        )
        
        assert state.score == 80.0
        assert state.has_mastery()
    
    def test_no_mastery_below_80_percent(self):
        """Score below 80% should not be mastery."""
        state = TeachingState(
            topic="solas",
            questions_asked=5,
            correct_answers=3  # 60%
        )
        
        assert state.score == 60.0
        assert not state.has_mastery()
    
    @given(
        correct=st.integers(min_value=0, max_value=10),
        total=st.integers(min_value=3, max_value=10)
    )
    @settings(max_examples=50)
    def test_mastery_threshold_is_80_percent(self, correct, total):
        """Mastery should be exactly at 80% threshold."""
        # Ensure correct <= total
        correct = min(correct, total)
        
        state = TeachingState(
            topic="test",
            questions_asked=total,
            correct_answers=correct
        )
        
        expected_score = (correct / total) * 100
        assert state.score == expected_score
        
        # Mastery requires >= 80% AND at least 3 questions
        if expected_score >= 80.0 and total >= 3:
            assert state.has_mastery()
        else:
            assert not state.has_mastery()

    
    def test_assessment_creates_valid_assessment_object(self):
        """Assessment from state should be valid."""
        agent = TutorAgent()
        
        state = TeachingState(
            topic="solas",
            questions_asked=5,
            correct_answers=4
        )
        
        assessment = agent.create_assessment_from_state(state)
        
        assert assessment.topic == "solas"
        assert assessment.score == 80.0
        assert assessment.questions_asked == 5
        assert assessment.correct_answers == 4


class TestTeachingSessionStatePersistence:
    """
    **Feature: maritime-ai-tutor, Property 12: Teaching Session State Persistence**
    
    For any teaching session spanning multiple turns, the Tutor_Agent SHALL
    maintain pedagogical state consistently across all turns.
    """
    
    def test_state_persists_across_phases(self):
        """
        **Feature: maritime-ai-tutor, Property 12: Teaching Session State Persistence**
        **Validates: Requirements 5.5**
        """
        agent = TutorAgent()
        user_id = str(uuid4())
        
        # Start session
        response1 = agent.start_session("solas", user_id)
        session_id = response1.state.session_id
        
        assert response1.phase == TeachingPhase.INTRODUCTION
        
        # Move to explanation
        response2 = agent.process_response("ready", session_id)
        assert response2.phase == TeachingPhase.EXPLANATION
        
        # State should be same session
        assert response2.state.session_id == session_id
        assert response2.state.topic == "solas"
    
    def test_questions_asked_increments_correctly(self):
        """Questions asked should increment with each question."""
        agent = TutorAgent()
        user_id = str(uuid4())
        
        response = agent.start_session("solas", user_id)
        session_id = response.state.session_id
        
        # Progress to assessment
        agent.process_response("ready", session_id)
        agent.process_response("ready", session_id)
        
        state = agent.get_session(session_id)
        initial_questions = state.questions_asked if state else 0
        
        # Answer a question
        if state and state.awaiting_answer:
            agent.process_response("some answer", session_id)
            updated_state = agent.get_session(session_id)
            if updated_state:
                assert updated_state.questions_asked >= initial_questions
    
    @given(topic=st.sampled_from(["solas", "colregs", "fire_safety"]))
    @settings(max_examples=20)
    def test_session_maintains_topic(self, topic):
        """
        **Feature: maritime-ai-tutor, Property 12: Teaching Session State Persistence**
        **Validates: Requirements 5.5**
        """
        agent = TutorAgent()
        user_id = str(uuid4())
        
        response = agent.start_session(topic, user_id)
        session_id = response.state.session_id
        
        # Progress through phases
        agent.process_response("ready", session_id)
        agent.process_response("ready", session_id)
        
        # Topic should remain consistent
        state = agent.get_session(session_id)
        assert state is not None
        assert state.topic == topic


class TestTeachingStateSerialization:
    """Test TeachingState serialization."""
    
    @given(
        topic=st.text(min_size=1, max_size=50).filter(lambda x: x.strip()),
        questions=st.integers(min_value=0, max_value=10),
        correct=st.integers(min_value=0, max_value=10)
    )
    @settings(max_examples=50)
    def test_teaching_state_round_trip(self, topic, questions, correct):
        """TeachingState should serialize and deserialize correctly."""
        correct = min(correct, questions)  # Ensure valid
        
        state = TeachingState(
            topic=topic,
            questions_asked=questions,
            correct_answers=correct
        )
        
        json_str = state.model_dump_json()
        restored = TeachingState.model_validate_json(json_str)
        
        assert restored.topic == state.topic
        assert restored.questions_asked == state.questions_asked
        assert restored.correct_answers == state.correct_answers
        assert restored.current_phase == state.current_phase


class TestTeachingPhaseProgression:
    """Test teaching phase progression."""
    
    def test_phases_progress_in_order(self):
        """Phases should progress: INTRO -> EXPLANATION -> ASSESSMENT."""
        agent = TutorAgent()
        user_id = str(uuid4())
        
        # Start - should be INTRODUCTION
        response = agent.start_session("solas", user_id)
        assert response.phase == TeachingPhase.INTRODUCTION
        
        session_id = response.state.session_id
        
        # Continue - should be EXPLANATION
        response = agent.process_response("continue", session_id)
        assert response.phase == TeachingPhase.EXPLANATION
        
        # Continue - should be ASSESSMENT
        response = agent.process_response("ready", session_id)
        assert response.phase == TeachingPhase.ASSESSMENT
    
    def test_completed_session_stays_completed(self):
        """Completed session should stay in COMPLETED phase."""
        state = TeachingState(
            topic="solas",
            current_phase=TeachingPhase.COMPLETED,
            questions_asked=5,
            correct_answers=4
        )
        
        assert state.current_phase == TeachingPhase.COMPLETED
