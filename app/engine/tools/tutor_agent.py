"""
Tutor Agent for teaching and assessment.

This module implements the Tutor Agent that handles structured
teaching sessions with introduction, explanation, and assessment phases.

**Feature: maritime-ai-tutor**
**Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.models.learning_profile import Assessment, LearningProfile

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class TeachingPhase(str, Enum):
    """Phases of a teaching session."""
    INTRODUCTION = "INTRODUCTION"
    EXPLANATION = "EXPLANATION"
    ASSESSMENT = "ASSESSMENT"
    COMPLETED = "COMPLETED"


class AnswerEvaluation(str, Enum):
    """Result of evaluating a user's answer."""
    CORRECT = "CORRECT"
    INCORRECT = "INCORRECT"
    PARTIAL = "PARTIAL"


class TeachingState(BaseModel):
    """
    State maintained during a teaching session.
    
    **Validates: Requirements 5.5**
    """
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    topic: str = Field(..., min_length=1)
    current_phase: TeachingPhase = Field(default=TeachingPhase.INTRODUCTION)
    questions_asked: int = Field(default=0)
    correct_answers: int = Field(default=0)
    hints_given: int = Field(default=0)
    current_question: Optional[str] = Field(default=None)
    current_correct_answer: Optional[str] = Field(default=None)
    awaiting_answer: bool = Field(default=False)
    started_at: datetime = Field(default_factory=_utc_now)
    
    @property
    def score(self) -> float:
        """Calculate current score percentage."""
        if self.questions_asked == 0:
            return 0.0
        return (self.correct_answers / self.questions_asked) * 100
    
    def has_mastery(self) -> bool:
        """Check if user has achieved mastery (>= 80%)."""
        return self.score >= 80.0 and self.questions_asked >= 3
    
    def is_struggling(self) -> bool:
        """Check if user is struggling (< 50%)."""
        return self.score < 50.0 and self.questions_asked >= 3


@dataclass
class TutorResponse:
    """Response from Tutor Agent."""
    content: str
    phase: TeachingPhase
    state: TeachingState
    hint_provided: bool = False
    assessment_complete: bool = False
    mastery_achieved: bool = False


class TutorAgent:
    """
    Tutor Agent for structured teaching sessions.
    
    Implements teaching flow with:
    - Introduction phase
    - Explanation phase
    - Assessment phase with hints
    
    **Validates: Requirements 5.1, 5.2, 5.3, 5.4, 5.5**
    """
    
    # Sample questions for maritime topics (in production, from knowledge base)
    SAMPLE_QUESTIONS: Dict[str, List[Dict[str, str]]] = {
        "solas": [
            {"q": "What does SOLAS stand for?", "a": "Safety of Life at Sea"},
            {"q": "When was SOLAS first adopted?", "a": "1914"},
            {"q": "What is the main purpose of SOLAS?", "a": "maritime safety"},
        ],
        "colregs": [
            {"q": "What does COLREGs stand for?", "a": "Collision Regulations"},
            {"q": "How many rules are in COLREGs?", "a": "41"},
            {"q": "What color is the port side light?", "a": "red"},
        ],
        "fire_safety": [
            {"q": "What SOLAS chapter covers fire safety?", "a": "Chapter II-2"},
            {"q": "What is the minimum number of fire extinguishers required?", "a": "depends on ship size"},
            {"q": "What type of fire is Class B?", "a": "flammable liquids"},
        ],
    }
    
    def __init__(self):
        """Initialize Tutor Agent."""
        self._sessions: Dict[str, TeachingState] = {}
    
    def start_session(self, topic: str, user_id: str) -> TutorResponse:
        """
        Start a new teaching session.
        
        Args:
            topic: Topic to teach
            user_id: User's ID
            
        Returns:
            TutorResponse with introduction
            
        **Validates: Requirements 5.1**
        """
        session_id = f"{user_id}_{topic}"
        
        state = TeachingState(
            session_id=session_id,
            topic=topic,
            current_phase=TeachingPhase.INTRODUCTION
        )
        self._sessions[session_id] = state
        
        content = self._generate_introduction(topic)
        
        return TutorResponse(
            content=content,
            phase=TeachingPhase.INTRODUCTION,
            state=state
        )
    
    def process_response(
        self, 
        user_response: str, 
        session_id: str
    ) -> TutorResponse:
        """
        Process user response during teaching session.
        
        Args:
            user_response: User's response/answer
            session_id: Current session ID
            
        Returns:
            TutorResponse with next step
            
        **Validates: Requirements 5.2, 5.3**
        """
        state = self._sessions.get(session_id)
        if not state:
            return self._create_error_response("Session not found")
        
        if state.current_phase == TeachingPhase.INTRODUCTION:
            return self._move_to_explanation(state)
        
        elif state.current_phase == TeachingPhase.EXPLANATION:
            return self._move_to_assessment(state)
        
        elif state.current_phase == TeachingPhase.ASSESSMENT:
            return self._evaluate_answer(state, user_response)
        
        else:
            return self._create_completion_response(state)
    
    def _generate_introduction(self, topic: str) -> str:
        """Generate introduction for a topic."""
        return (
            f"Welcome to the lesson on **{topic.upper()}**!\n\n"
            f"In this session, we'll cover the key concepts and regulations "
            f"related to {topic}. After the explanation, I'll ask you some "
            f"questions to test your understanding.\n\n"
            f"Ready to begin? Just say 'continue' or 'ready'."
        )

    
    def _move_to_explanation(self, state: TeachingState) -> TutorResponse:
        """Move to explanation phase."""
        state.current_phase = TeachingPhase.EXPLANATION
        
        content = self._generate_explanation(state.topic)
        
        return TutorResponse(
            content=content,
            phase=TeachingPhase.EXPLANATION,
            state=state
        )
    
    def _generate_explanation(self, topic: str) -> str:
        """Generate explanation content for a topic."""
        explanations = {
            "solas": (
                "**SOLAS (Safety of Life at Sea)**\n\n"
                "SOLAS is the most important international treaty concerning "
                "maritime safety. First adopted in 1914 after the Titanic disaster, "
                "it has been updated multiple times.\n\n"
                "Key chapters include:\n"
                "- Chapter II-1: Construction\n"
                "- Chapter II-2: Fire protection\n"
                "- Chapter III: Life-saving appliances\n"
                "- Chapter V: Safety of navigation\n\n"
                "Say 'ready' when you want to start the assessment."
            ),
            "colregs": (
                "**COLREGs (Collision Regulations)**\n\n"
                "The International Regulations for Preventing Collisions at Sea "
                "contain 41 rules divided into parts:\n\n"
                "- Part A: General (Rules 1-3)\n"
                "- Part B: Steering and Sailing (Rules 4-19)\n"
                "- Part C: Lights and Shapes (Rules 20-31)\n"
                "- Part D: Sound and Light Signals (Rules 32-37)\n\n"
                "Say 'ready' when you want to start the assessment."
            ),
        }
        return explanations.get(topic.lower(), f"Explanation for {topic}...")
    
    def _move_to_assessment(self, state: TeachingState) -> TutorResponse:
        """Move to assessment phase and ask first question."""
        state.current_phase = TeachingPhase.ASSESSMENT
        return self._ask_next_question(state)
    
    def _ask_next_question(self, state: TeachingState) -> TutorResponse:
        """Ask the next question in assessment."""
        topic_key = state.topic.lower().replace(" ", "_")
        questions = self.SAMPLE_QUESTIONS.get(topic_key, self.SAMPLE_QUESTIONS.get("solas", []))
        
        if state.questions_asked >= len(questions) or state.questions_asked >= 5:
            return self._complete_assessment(state)
        
        q_data = questions[state.questions_asked]
        state.current_question = q_data["q"]
        state.current_correct_answer = q_data["a"]
        state.awaiting_answer = True
        
        content = (
            f"**Question {state.questions_asked + 1}:**\n\n"
            f"{state.current_question}"
        )
        
        return TutorResponse(
            content=content,
            phase=TeachingPhase.ASSESSMENT,
            state=state
        )
    
    def _evaluate_answer(
        self, 
        state: TeachingState, 
        user_answer: str
    ) -> TutorResponse:
        """
        Evaluate user's answer.
        
        **Validates: Requirements 5.2, 5.3**
        """
        if not state.awaiting_answer:
            return self._ask_next_question(state)
        
        correct_answer = state.current_correct_answer or ""
        is_correct = self._check_answer(user_answer, correct_answer)
        
        state.questions_asked += 1
        state.awaiting_answer = False
        hint_provided = False
        
        if is_correct:
            state.correct_answers += 1
            content = (
                f"✅ **Correct!** Well done!\n\n"
                f"Current score: {state.correct_answers}/{state.questions_asked} "
                f"({state.score:.0f}%)"
            )
        else:
            # Provide hint before revealing answer (Property 13)
            hint_provided = True
            state.hints_given += 1
            content = (
                f"❌ **Not quite right.**\n\n"
                f"**Hint:** The answer relates to '{correct_answer[:3]}...'\n\n"
                f"The correct answer is: **{correct_answer}**\n\n"
                f"Current score: {state.correct_answers}/{state.questions_asked} "
                f"({state.score:.0f}%)"
            )
        
        # Check if more questions or complete
        if state.questions_asked >= 3:
            if state.has_mastery():
                return self._complete_with_mastery(state)
        
        # Continue with next question
        content += "\n\nLet's continue..."
        
        response = TutorResponse(
            content=content,
            phase=TeachingPhase.ASSESSMENT,
            state=state,
            hint_provided=hint_provided
        )
        
        # Automatically ask next question
        return self._ask_next_question(state)
    
    def _check_answer(self, user_answer: str, correct_answer: str) -> bool:
        """Check if user's answer is correct."""
        user_lower = user_answer.lower().strip()
        correct_lower = correct_answer.lower().strip()
        
        # Exact match or contains
        return correct_lower in user_lower or user_lower in correct_lower
    
    def _complete_assessment(self, state: TeachingState) -> TutorResponse:
        """Complete the assessment phase."""
        state.current_phase = TeachingPhase.COMPLETED
        state.awaiting_answer = False
        
        content = (
            f"🎓 **Assessment Complete!**\n\n"
            f"Topic: {state.topic}\n"
            f"Score: {state.correct_answers}/{state.questions_asked} ({state.score:.0f}%)\n"
            f"Hints used: {state.hints_given}\n\n"
        )
        
        if state.has_mastery():
            content += "🌟 **Congratulations!** You've demonstrated mastery of this topic!"
        elif state.is_struggling():
            content += "📚 Consider reviewing this topic again. Practice makes perfect!"
        else:
            content += "👍 Good effort! Keep studying to improve your score."
        
        return TutorResponse(
            content=content,
            phase=TeachingPhase.COMPLETED,
            state=state,
            assessment_complete=True,
            mastery_achieved=state.has_mastery()
        )
    
    def _complete_with_mastery(self, state: TeachingState) -> TutorResponse:
        """
        Complete with mastery achievement.
        
        **Validates: Requirements 5.4**
        """
        response = self._complete_assessment(state)
        response.mastery_achieved = True
        return response
    
    def _create_error_response(self, message: str) -> TutorResponse:
        """Create error response."""
        return TutorResponse(
            content=f"Error: {message}",
            phase=TeachingPhase.INTRODUCTION,
            state=TeachingState(topic="unknown")
        )
    
    def _create_completion_response(self, state: TeachingState) -> TutorResponse:
        """Create completion response."""
        return TutorResponse(
            content="Session already completed. Start a new session to continue learning.",
            phase=TeachingPhase.COMPLETED,
            state=state,
            assessment_complete=True
        )
    
    def get_session(self, session_id: str) -> Optional[TeachingState]:
        """Get a teaching session by ID."""
        return self._sessions.get(session_id)
    
    def create_assessment_from_state(self, state: TeachingState) -> Assessment:
        """
        Create Assessment object from teaching state.
        
        **Validates: Requirements 5.4**
        """
        return Assessment(
            topic=state.topic,
            score=state.score,
            questions_asked=state.questions_asked,
            correct_answers=state.correct_answers
        )
