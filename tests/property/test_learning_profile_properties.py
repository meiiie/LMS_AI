"""
Property-based tests for Learning Profile.

**Feature: maritime-ai-tutor**
**Validates: Requirements 6.1, 6.2, 6.5, 6.6**
"""

import pytest
from datetime import datetime, timezone
from uuid import uuid4

from hypothesis import given, settings, strategies as st, assume

from app.models.learning_profile import (
    Assessment,
    LearnerLevel,
    LearningProfile,
    LearningStyle,
    create_default_profile,
)


# Custom strategies
@st.composite
def assessment_strategy(draw):
    """Generate valid Assessment objects."""
    questions = draw(st.integers(min_value=1, max_value=50))
    correct = draw(st.integers(min_value=0, max_value=questions))
    score = (correct / questions) * 100 if questions > 0 else 0.0
    
    return Assessment(
        topic=draw(st.text(min_size=1, max_size=50).filter(lambda x: x.strip())),
        score=score,
        questions_asked=questions,
        correct_answers=correct,
    )


@st.composite
def learning_profile_strategy(draw):
    """Generate valid LearningProfile objects."""
    return LearningProfile(
        user_id=draw(st.uuids()),
        current_level=draw(st.sampled_from(LearnerLevel)),
        learning_style=draw(st.none() | st.sampled_from(LearningStyle)),
        weak_topics=draw(st.lists(
            st.text(min_size=1, max_size=30).filter(lambda x: x.strip()),
            max_size=5,
            unique=True
        )),
        completed_topics=draw(st.lists(
            st.text(min_size=1, max_size=30).filter(lambda x: x.strip()),
            max_size=5,
            unique=True
        )),
        assessment_history=draw(st.lists(assessment_strategy(), max_size=3)),
    )


class TestLearningProfileSerializationRoundTrip:
    """
    **Feature: maritime-ai-tutor, Property 3: Learning Profile Serialization Round-Trip**
    
    For any LearningProfile object, serializing to JSON and deserializing back
    SHALL produce an equivalent LearningProfile.
    """
    
    @given(profile=learning_profile_strategy())
    @settings(max_examples=100)
    def test_learning_profile_json_round_trip(self, profile: LearningProfile):
        """
        **Feature: maritime-ai-tutor, Property 3: Learning Profile Serialization Round-Trip**
        **Validates: Requirements 6.5, 6.6**
        """
        # Serialize to JSON
        json_str = profile.model_dump_json()
        
        # Deserialize back
        restored = LearningProfile.model_validate_json(json_str)
        
        # Verify key fields
        assert restored.user_id == profile.user_id
        assert restored.current_level == profile.current_level
        assert restored.learning_style == profile.learning_style
        assert restored.weak_topics == profile.weak_topics
        assert restored.completed_topics == profile.completed_topics
        assert len(restored.assessment_history) == len(profile.assessment_history)

    
    @given(profile=learning_profile_strategy())
    @settings(max_examples=100)
    def test_learning_profile_dict_round_trip(self, profile: LearningProfile):
        """
        **Feature: maritime-ai-tutor, Property 3: Learning Profile Serialization Round-Trip**
        **Validates: Requirements 6.5, 6.6**
        """
        # Serialize to dict
        data = profile.model_dump()
        
        # Deserialize back
        restored = LearningProfile.model_validate(data)
        
        # Verify equivalence
        assert restored.user_id == profile.user_id
        assert restored.current_level == profile.current_level
        assert restored.learning_style == profile.learning_style


class TestDefaultLearningProfileValues:
    """
    **Feature: maritime-ai-tutor, Property 15: Default Learning Profile Values**
    
    For any newly created LearningProfile, the default values SHALL be:
    current_level=CADET, learning_style=null, weak_topics=[].
    """
    
    @given(user_id=st.uuids())
    @settings(max_examples=100)
    def test_default_profile_has_correct_values(self, user_id):
        """
        **Feature: maritime-ai-tutor, Property 15: Default Learning Profile Values**
        **Validates: Requirements 6.1**
        """
        profile = create_default_profile(user_id)
        
        # Verify default values
        assert profile.user_id == user_id
        assert profile.current_level == LearnerLevel.CADET
        assert profile.learning_style is None
        assert profile.weak_topics == []
        assert profile.completed_topics == []
        assert profile.assessment_history == []
    
    @given(user_id=st.uuids())
    @settings(max_examples=50)
    def test_default_profile_is_serializable(self, user_id):
        """Default profile should be serializable."""
        profile = create_default_profile(user_id)
        
        # Should not raise
        json_str = profile.model_dump_json()
        restored = LearningProfile.model_validate_json(json_str)
        
        assert restored.user_id == user_id


class TestWeakTopicTracking:
    """
    **Feature: maritime-ai-tutor, Property 16: Weak Topic Tracking**
    
    For any topic where user score is below 50%, the Maritime_AI_Service
    SHALL add that topic to weak_topics in LearningProfile.
    """
    
    @given(
        user_id=st.uuids(),
        topic=st.text(min_size=1, max_size=30).filter(lambda x: x.strip()),
        score=st.floats(min_value=0.0, max_value=49.9)
    )
    @settings(max_examples=100)
    def test_low_score_adds_to_weak_topics(self, user_id, topic, score):
        """
        **Feature: maritime-ai-tutor, Property 16: Weak Topic Tracking**
        **Validates: Requirements 6.2**
        """
        profile = create_default_profile(user_id)
        
        # Create assessment with low score
        assessment = Assessment(
            topic=topic,
            score=score,
            questions_asked=10,
            correct_answers=int(score / 10)  # Approximate
        )
        
        # Add assessment
        profile.add_assessment(assessment)
        
        # Topic should be in weak_topics
        assert topic in profile.weak_topics
    
    @given(
        user_id=st.uuids(),
        topic=st.text(min_size=1, max_size=30).filter(lambda x: x.strip()),
        score=st.floats(min_value=80.0, max_value=100.0)
    )
    @settings(max_examples=100)
    def test_high_score_adds_to_completed_topics(self, user_id, topic, score):
        """
        **Feature: maritime-ai-tutor, Property 14: Mastery Updates Profile**
        **Validates: Requirements 5.4**
        """
        profile = create_default_profile(user_id)
        
        # Create assessment with high score (mastery)
        assessment = Assessment(
            topic=topic,
            score=score,
            questions_asked=10,
            correct_answers=int(score / 10)
        )
        
        # Add assessment
        profile.add_assessment(assessment)
        
        # Topic should be in completed_topics
        assert topic in profile.completed_topics
    
    @given(
        user_id=st.uuids(),
        topic=st.text(min_size=1, max_size=30).filter(lambda x: x.strip())
    )
    @settings(max_examples=50)
    def test_mastery_removes_from_weak_topics(self, user_id, topic):
        """
        When mastery is achieved, topic should be removed from weak_topics.
        **Validates: Requirements 6.2**
        """
        profile = create_default_profile(user_id)
        
        # First, add a low score assessment
        low_assessment = Assessment(
            topic=topic,
            score=30.0,
            questions_asked=10,
            correct_answers=3
        )
        profile.add_assessment(low_assessment)
        assert topic in profile.weak_topics
        
        # Then, add a high score assessment (mastery)
        high_assessment = Assessment(
            topic=topic,
            score=90.0,
            questions_asked=10,
            correct_answers=9
        )
        profile.add_assessment(high_assessment)
        
        # Topic should be removed from weak_topics
        assert topic not in profile.weak_topics
        assert topic in profile.completed_topics


class TestAssessmentValidation:
    """Test Assessment model validation."""
    
    @given(
        questions=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=50)
    def test_correct_answers_cannot_exceed_questions(self, questions):
        """Correct answers should not exceed total questions."""
        with pytest.raises(ValueError):
            Assessment(
                topic="Test Topic",
                score=100.0,
                questions_asked=questions,
                correct_answers=questions + 1  # Invalid
            )
    
    @given(assessment=assessment_strategy())
    @settings(max_examples=100)
    def test_assessment_round_trip(self, assessment: Assessment):
        """Assessment should serialize and deserialize correctly."""
        json_str = assessment.model_dump_json()
        restored = Assessment.model_validate_json(json_str)
        
        assert restored.topic == assessment.topic
        assert restored.score == assessment.score
        assert restored.questions_asked == assessment.questions_asked
        assert restored.correct_answers == assessment.correct_answers
