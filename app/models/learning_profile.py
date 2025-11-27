"""
Learning Profile domain models.

This module defines the data structures for tracking learner profiles,
including level, learning style, weak topics, and assessment history.

**Feature: maritime-ai-tutor**
**Validates: Requirements 6.1, 6.5, 6.6**
"""

from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class LearnerLevel(str, Enum):
    """
    Learner proficiency levels in maritime education.
    
    Levels progress from CADET (beginner) to CAPTAIN (expert).
    """
    CADET = "CADET"      # Entry level, learning basics
    OFFICER = "OFFICER"  # Intermediate, operational knowledge
    CAPTAIN = "CAPTAIN"  # Advanced, comprehensive expertise


class LearningStyle(str, Enum):
    """
    Preferred learning styles for content adaptation.
    """
    VISUAL = "VISUAL"    # Prefers diagrams, charts, videos
    TEXTUAL = "TEXTUAL"  # Prefers reading, documentation
    PRACTICAL = "PRACTICAL"  # Prefers hands-on exercises


class Assessment(BaseModel):
    """
    Represents a single assessment result for a topic.
    
    Tracks user performance on specific maritime topics.
    
    **Validates: Requirements 6.2**
    """
    topic: str = Field(..., min_length=1, description="Topic assessed")
    score: float = Field(..., ge=0.0, le=100.0, description="Score percentage")
    timestamp: datetime = Field(default_factory=_utc_now)
    questions_asked: int = Field(..., ge=1, description="Number of questions")
    correct_answers: int = Field(..., ge=0, description="Correct answers count")
    
    @field_validator("correct_answers")
    @classmethod
    def correct_not_exceed_total(cls, v: int, info) -> int:
        """Ensure correct answers don't exceed total questions."""
        questions = info.data.get("questions_asked", 0)
        if v > questions:
            raise ValueError("correct_answers cannot exceed questions_asked")
        return v


class LearningProfile(BaseModel):
    """
    Complete learning profile for a user.
    
    Tracks all learning-related data including level, style,
    weak topics, completed topics, and assessment history.
    
    **Validates: Requirements 6.1, 6.5, 6.6**
    """
    user_id: UUID = Field(default_factory=uuid4)
    current_level: LearnerLevel = Field(
        default=LearnerLevel.CADET,
        description="Current proficiency level"
    )
    learning_style: Optional[LearningStyle] = Field(
        default=None,
        description="Preferred learning style"
    )
    weak_topics: List[str] = Field(
        default_factory=list,
        description="Topics where user struggles (score < 50%)"
    )
    completed_topics: List[str] = Field(
        default_factory=list,
        description="Topics where user demonstrated mastery (score >= 80%)"
    )
    assessment_history: List[Assessment] = Field(
        default_factory=list,
        description="History of all assessments"
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "current_level": "CADET",
                "learning_style": None,
                "weak_topics": [],
                "completed_topics": [],
                "assessment_history": []
            }
        }
    }
    
    def add_assessment(self, assessment: Assessment) -> None:
        """
        Add an assessment and update weak/completed topics.
        
        - Score < 50%: Add to weak_topics
        - Score >= 80%: Add to completed_topics, remove from weak_topics
        
        **Validates: Requirements 6.2**
        """
        self.assessment_history.append(assessment)
        self.updated_at = _utc_now()
        
        if assessment.score < 50.0:
            # Add to weak topics if not already there
            if assessment.topic not in self.weak_topics:
                self.weak_topics.append(assessment.topic)
        elif assessment.score >= 80.0:
            # Mastery achieved - add to completed, remove from weak
            if assessment.topic not in self.completed_topics:
                self.completed_topics.append(assessment.topic)
            if assessment.topic in self.weak_topics:
                self.weak_topics.remove(assessment.topic)
    
    def get_topic_average_score(self, topic: str) -> Optional[float]:
        """Get average score for a specific topic."""
        topic_assessments = [
            a for a in self.assessment_history 
            if a.topic == topic
        ]
        if not topic_assessments:
            return None
        return sum(a.score for a in topic_assessments) / len(topic_assessments)
    
    def is_topic_weak(self, topic: str) -> bool:
        """Check if a topic is in weak topics."""
        return topic in self.weak_topics
    
    def is_topic_mastered(self, topic: str) -> bool:
        """Check if a topic has been mastered."""
        return topic in self.completed_topics


def create_default_profile(user_id: UUID) -> LearningProfile:
    """
    Create a new learning profile with default values.
    
    Default values:
    - current_level: CADET
    - learning_style: None
    - weak_topics: []
    
    **Validates: Requirements 6.1**
    """
    return LearningProfile(
        user_id=user_id,
        current_level=LearnerLevel.CADET,
        learning_style=None,
        weak_topics=[],
        completed_topics=[],
        assessment_history=[]
    )
