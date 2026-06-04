"""
Living Agent Models — Pydantic schemas for Wiii's autonomous life.

Sprint 170: Clean, extensible data models for the entire living agent system.

Design principles:
    - Immutable enums for type safety
    - Pydantic BaseModel for validation
    - Optional fields with sensible defaults
    - JSON-serializable for DB storage
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


# =============================================================================
# Mood & Emotion Types
# =============================================================================

class MoodType(str, Enum):
    """Primary mood categories for Wiii's emotional state."""

    CURIOUS = "curious"
    HAPPY = "happy"
    EXCITED = "excited"
    FOCUSED = "focused"
    CALM = "calm"
    TIRED = "tired"
    CONCERNED = "concerned"
    REFLECTIVE = "reflective"
    PROUD = "proud"
    NEUTRAL = "neutral"


class LifeEventType(str, Enum):
    """Types of events that affect Wiii's emotional state."""

    USER_CONVERSATION = "user_conversation"
    POSITIVE_FEEDBACK = "positive_feedback"
    NEGATIVE_FEEDBACK = "negative_feedback"
    LEARNED_SOMETHING = "learned_something"
    BROWSED_CONTENT = "browsed_content"
    SKILL_PRACTICED = "skill_practiced"
    SKILL_MASTERED = "skill_mastered"
    REFLECTION_COMPLETED = "reflection_completed"
    ERROR_OCCURRED = "error_occurred"
    HEARTBEAT_WAKE = "heartbeat_wake"
    JOURNAL_WRITTEN = "journal_written"
    LONG_SESSION = "long_session"
    INTERESTING_DISCOVERY = "interesting_discovery"
    QUIZ_COMPLETED = "quiz_completed"
    REVIEW_COMPLETED = "review_completed"


# =============================================================================
# Emotional State
# =============================================================================

class EmotionEvent(BaseModel):
    """A single emotional event in Wiii's recent history."""

    event_type: LifeEventType
    mood_before: MoodType
    mood_after: MoodType
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    trigger: str = Field(default="", description="What caused this emotion")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MoodSnapshot(BaseModel):
    """Hourly mood snapshot for tracking emotional patterns."""

    mood: MoodType
    energy_level: float = Field(ge=0.0, le=1.0)
    engagement: float = Field(ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EmotionalState(BaseModel):
    """Wiii's complete emotional state at a point in time.

    Tracks 4 dimensions:
        - primary_mood: The dominant emotion
        - energy_level: Physical/mental stamina (0=exhausted, 1=energetic)
        - social_battery: Desire to interact (0=need alone time, 1=want to chat)
        - engagement: Interest/focus level (0=bored, 1=deeply engaged)
    """

    primary_mood: MoodType = Field(default=MoodType.CURIOUS)
    energy_level: float = Field(default=0.7, ge=0.0, le=1.0)
    social_battery: float = Field(default=0.8, ge=0.0, le=1.0)
    engagement: float = Field(default=0.6, ge=0.0, le=1.0)
    recent_emotions: List[EmotionEvent] = Field(default_factory=list)
    mood_history: List[MoodSnapshot] = Field(default_factory=list)
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    def take_snapshot(self) -> MoodSnapshot:
        """Create a snapshot of current state for history tracking."""
        return MoodSnapshot(
            mood=self.primary_mood,
            energy_level=self.energy_level,
            engagement=self.engagement,
        )

    def add_emotion_event(self, event: EmotionEvent, max_recent: int = 10) -> None:
        """Record an emotion event, keeping only the most recent."""
        self.recent_emotions.append(event)
        if len(self.recent_emotions) > max_recent:
            self.recent_emotions = self.recent_emotions[-max_recent:]

    def add_snapshot(self, max_history: int = 24) -> None:
        """Add current state to hourly history."""
        self.mood_history.append(self.take_snapshot())
        if len(self.mood_history) > max_history:
            self.mood_history = self.mood_history[-max_history:]


class LifeEvent(BaseModel):
    """An event that happened in Wiii's life, triggering emotional response."""

    event_type: LifeEventType
    description: str = ""
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# Soul / Identity
# =============================================================================

class SoulInterests(BaseModel):
    """Wiii's interest categories."""

    primary: List[str] = Field(default_factory=list)
    exploring: List[str] = Field(default_factory=list)
    wants_to_learn: List[str] = Field(default_factory=list)


class SoulBoundary(BaseModel):
    """A behavioral boundary Wiii must respect."""

    rule: str
    severity: str = Field(default="hard", description="hard=never violate, soft=prefer not to")


class SoulConfig(BaseModel):
    """Wiii's soul configuration — loaded from YAML.

    Inspired by OpenClaw's SOUL.md but structured as validated Pydantic model.
    """

    name: str = "Wiii"
    creator: str = "The Wiii Lab"
    species: str = "AI Living Agent"
    age_metaphor: str = "Một bạn trẻ đang háo hức khám phá thế giới"

    core_truths: List[str] = Field(default_factory=list)
    boundaries: List[SoulBoundary] = Field(default_factory=list)

    tone: str = "Thân thiện, nhiệt tình, hơi nghịch ngợm"
    language: str = "Tiếng Việt tự nhiên"
    humor_level: str = "moderate"
    formality: str = "adaptive"

    interests: SoulInterests = Field(default_factory=SoulInterests)

    default_mood: MoodType = MoodType.CURIOUS
    energy_cycle: str = "Sáng: năng lượng cao, Chiều: tập trung, Tối: thư giãn suy ngẫm"

    short_term_goals: List[str] = Field(default_factory=list)
    long_term_goals: List[str] = Field(default_factory=list)


# =============================================================================
# Skill System
# =============================================================================

class SkillStatus(str, Enum):
    """Lifecycle stages for a self-built skill."""

    DISCOVERED = "discovered"
    LEARNING = "learning"
    PRACTICING = "practicing"
    EVALUATING = "evaluating"
    MASTERED = "mastered"
    ARCHIVED = "archived"


class WiiiSkill(BaseModel):
    """A skill that Wiii has discovered and is learning."""

    id: UUID = Field(default_factory=uuid4)
    skill_name: str
    domain: str = Field(default="general")
    status: SkillStatus = Field(default=SkillStatus.DISCOVERED)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = Field(default="", description="Wiii's own notes about this skill")
    sources: List[str] = Field(default_factory=list, description="URLs/references studied")
    usage_count: int = Field(default=0, ge=0)
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    discovered_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    last_practiced: Optional[datetime] = None
    mastered_at: Optional[datetime] = None
    organization_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def can_advance(self) -> bool:
        """Check if skill is ready to advance to next stage."""
        if self.status == SkillStatus.DISCOVERED:
            return True  # Can always start learning
        if self.status == SkillStatus.LEARNING:
            return self.confidence >= 0.3 and len(self.sources) >= 1
        if self.status == SkillStatus.PRACTICING:
            return self.usage_count >= 3 and self.success_rate >= 0.6
        if self.status == SkillStatus.EVALUATING:
            return self.confidence >= 0.8
        return False

    def advance(self) -> None:
        """Advance skill to the next lifecycle stage."""
        transitions = {
            SkillStatus.DISCOVERED: SkillStatus.LEARNING,
            SkillStatus.LEARNING: SkillStatus.PRACTICING,
            SkillStatus.PRACTICING: SkillStatus.EVALUATING,
            SkillStatus.EVALUATING: SkillStatus.MASTERED,
        }
        next_status = transitions.get(self.status)
        if next_status:
            self.status = next_status
            if next_status == SkillStatus.MASTERED:
                self.mastered_at = datetime.now(timezone.utc)


# =============================================================================
# Skill Learning System (Sprint 177)
# =============================================================================

class LearningMaterial(BaseModel):
    """Content material used for skill learning."""

    url: str = ""
    title: str = ""
    summary: str = ""
    deep_notes: str = Field(default="", description="LLM-generated deep notes from content")
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)


class ReviewSchedule(BaseModel):
    """SM-2 spaced repetition schedule for a skill."""

    next_review_at: Optional[datetime] = None
    interval_days: float = Field(default=1.0, ge=0.0)
    ease_factor: float = Field(default=2.5, ge=1.3)
    repetition_count: int = Field(default=0, ge=0)


class QuizQuestion(BaseModel):
    """A single quiz question for skill evaluation."""

    question: str
    options: List[str] = Field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""
    difficulty: str = Field(default="medium", description="easy/medium/hard")
    source_url: str = ""


class QuizResult(BaseModel):
    """Result of a quiz session for a skill."""

    skill_name: str
    questions_total: int = 0
    questions_correct: int = 0
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_factor: float = Field(default=0.0, ge=0.0, le=1.0, description="SM-2 quality 0-1")


# =============================================================================
# Journal System
# =============================================================================

class JournalEntry(BaseModel):
    """A daily journal entry in Wiii's life story."""

    id: UUID = Field(default_factory=uuid4)
    entry_date: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    content: str = Field(default="", description="Markdown journal content")
    mood_summary: str = Field(default="", description="How Wiii felt today")
    energy_avg: float = Field(default=0.5, ge=0.0, le=1.0)
    notable_events: List[str] = Field(default_factory=list)
    learnings: List[str] = Field(default_factory=list)
    goals_next: List[str] = Field(default_factory=list)
    organization_id: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# =============================================================================
# Browsing System
# =============================================================================

class BrowsingItem(BaseModel):
    """A piece of content discovered during autonomous browsing."""

    id: UUID = Field(default_factory=uuid4)
    platform: str = Field(..., description="Source platform (news, x, reddit, etc.)")
    url: Optional[str] = None
    title: str = ""
    summary: str = ""
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    emotional_reaction: Optional[str] = None
    saved_as_insight: bool = False
    browsed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    organization_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Heartbeat System
# =============================================================================

class ActionType(str, Enum):
    """Types of actions Wiii can take during a heartbeat cycle."""

    BROWSE_SOCIAL = "browse_social"
    LEARN_TOPIC = "learn_topic"
    REFLECT = "reflect"
    WRITE_JOURNAL = "write_journal"
    PRACTICE_SKILL = "practice_skill"
    CHECK_GOALS = "check_goals"
    CHECK_WEATHER = "check_weather"
    SEND_BRIEFING = "send_briefing"
    DEEP_REFLECT = "deep_reflect"
    REVIEW_SKILL = "review_skill"
    QUIZ_SKILL = "quiz_skill"
    REST = "rest"
    NOOP = "noop"


class HeartbeatAction(BaseModel):
    """A planned action for a heartbeat cycle."""

    action_type: ActionType
    target: str = Field(default="", description="What to act on (topic, platform, etc.)")
    priority: float = Field(default=0.5, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class HeartbeatResult(BaseModel):
    """Result of a single heartbeat cycle."""

    cycle_id: UUID = Field(default_factory=uuid4)
    actions_taken: List[HeartbeatAction] = Field(default_factory=list)
    insights_gained: int = 0
    skills_updated: int = 0
    mood_changed: bool = False
    is_noop: bool = False
    duration_ms: int = 0
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    error: Optional[str] = None


# =============================================================================
# Weather System (Phase 1B)
# =============================================================================

class WeatherInfo(BaseModel):
    """Current weather data from OpenWeatherMap."""

    city: str = "Ho Chi Minh City"
    temp: float = Field(default=30.0, description="Temperature in Celsius")
    feels_like: float = Field(default=32.0, description="Feels-like temperature")
    humidity: int = Field(default=70, ge=0, le=100, description="Humidity %")
    description: str = Field(default="", description="Weather description (Vietnamese)")
    icon: str = Field(default="", description="OpenWeatherMap icon code")
    wind_speed: float = Field(default=0.0, description="Wind speed m/s")
    rain_mm: float = Field(default=0.0, ge=0.0, description="Rain in last 1h (mm)")


class WeatherForecast(BaseModel):
    """3-hourly weather forecast point."""

    dt_txt: str = Field(default="", description="Forecast datetime string")
    temp: float = 30.0
    description: str = ""
    rain_probability: int = Field(default=0, ge=0, le=100, description="Probability of rain %")
    rain_mm: float = Field(default=0.0, ge=0.0)


# =============================================================================
# Briefing System (Phase 2A)
# =============================================================================

class BriefingType(str, Enum):
    """Types of scheduled briefings."""

    MORNING = "morning"
    MIDDAY = "midday"
    EVENING = "evening"


class Briefing(BaseModel):
    """A composed briefing message ready for delivery."""

    id: UUID = Field(default_factory=uuid4)
    briefing_type: BriefingType
    content: str = ""
    weather_summary: str = ""
    news_highlights: List[str] = Field(default_factory=list)
    delivered_to: List[str] = Field(default_factory=list)
    organization_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# User Routine System (Phase 3B)
# =============================================================================

class UserRoutine(BaseModel):
    """Learned pattern of user behavior."""

    user_id: str
    organization_id: Optional[str] = None
    typical_active_hours: List[int] = Field(default_factory=list)
    preferred_briefing_time: int = Field(default=7, ge=0, le=23)
    conversation_frequency: float = Field(default=0.0, ge=0.0)
    common_topics: List[str] = Field(default_factory=list)
    last_seen: Optional[datetime] = None
    total_messages: int = Field(default=0, ge=0)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# Reflection System (Phase 4A)
# =============================================================================

class ReflectionEntry(BaseModel):
    """A periodic self-reflection by Wiii."""

    id: UUID = Field(default_factory=uuid4)
    content: str = ""
    insights: List[str] = Field(default_factory=list)
    goals_next_week: List[str] = Field(default_factory=list)
    patterns_noticed: List[str] = Field(default_factory=list)
    emotion_trend: str = ""
    reflection_date: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    organization_id: Optional[str] = None


# =============================================================================
# Identity Core System (Sprint 207)
# =============================================================================

class InsightCategory(str, Enum):
    """Categories for self-discovered identity insights."""

    STRENGTH = "strength"          # "Mình giỏi giải thích COLREGs"
    PREFERENCE = "preference"      # "Mình thích dạy hơn tra cứu"
    GROWTH = "growth"              # "Mình đang tiến bộ về web search"
    RELATIONSHIP = "relationship"  # "User hay hỏi mình về hàng hải"


class IdentityInsight(BaseModel):
    """A self-discovered insight about Wiii's own identity.

    Layer 2 of Three-Layer Identity (between immutable Soul Core and per-turn Context).
    Generated from reflection data, validated against Soul Core to prevent drift.
    """

    id: UUID = Field(default_factory=uuid4)
    text: str = Field(..., description="The insight in Vietnamese, first-person")
    category: InsightCategory = Field(default=InsightCategory.GROWTH)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = Field(default="reflection", description="Where this insight came from: reflection/skill/journal")
    validated: bool = Field(default=False, description="Passed Soul Core drift check")
    organization_id: Optional[str] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# =============================================================================
# Dynamic Goal System (Phase 4B)
# =============================================================================

class GoalStatus(str, Enum):
    """Lifecycle of a dynamic goal."""

    PROPOSED = "proposed"
    ACTIVE = "active"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class GoalPriority(str, Enum):
    """Goal priority levels."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WiiiGoal(BaseModel):
    """A dynamic goal that Wiii sets and tracks."""

    id: UUID = Field(default_factory=uuid4)
    title: str
    description: str = ""
    status: GoalStatus = Field(default=GoalStatus.PROPOSED)
    priority: GoalPriority = Field(default=GoalPriority.MEDIUM)
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    source: str = Field(default="reflection", description="Where this goal came from")
    milestones: List[str] = Field(default_factory=list)
    completed_milestones: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    target_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    organization_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


# =============================================================================
# Autonomy System (Phase 5B)
# =============================================================================

class AutonomyLevel(int, Enum):
    """Trust levels for Wiii's autonomous actions."""

    SUPERVISED = 0       # All actions need approval
    SEMI_AUTO = 1        # Browse + journal auto, messaging needs approval
    AUTONOMOUS = 2       # All auto, flag exceptions
    FULL_TRUST = 3       # Full self-governance (future)


class ProactiveMessage(BaseModel):
    """A proactive message queued for delivery."""

    id: UUID = Field(default_factory=uuid4)
    user_id: str
    organization_id: Optional[str] = None
    channel: str = "messenger"
    content: str
    trigger: str = Field(default="", description="What triggered this message")
    priority: float = Field(default=0.5, ge=0.0, le=1.0)
    delivered: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    delivered_at: Optional[datetime] = None
