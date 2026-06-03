"""
Tests for Sprint 51: LearningProfileRepository coverage.

Tests both InMemory and PostgreSQL implementations:
- InMemoryLearningProfileRepository: get, create, update, delete, get_or_create,
  add_assessment, update_level, update_learning_style, count, clear
- LearningProfileRepository: init, is_available, get, create,
  get_or_create, update_weak_areas, update_strong_areas, increment_stats,
  _convert_user_id, singleton
"""

import pytest
from uuid import uuid4, UUID
from unittest.mock import MagicMock, patch

from app.models.learning_profile import (
    Assessment,
    LearnerLevel,
    LearningStyle,
    LearningProfile,
)
from app.repositories.learning_profile_repository import (
    InMemoryLearningProfileRepository,
    LearningProfileRepository,
)


# ============================================================================
# InMemoryLearningProfileRepository
# ============================================================================


class TestInMemoryGet:
    """Test in-memory get."""

    @pytest.mark.asyncio
    async def test_not_found(self):
        repo = InMemoryLearningProfileRepository()
        result = await repo.get(uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_found(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        profile = LearningProfile(user_id=uid)
        await repo.create(profile)
        result = await repo.get(uid)
        assert result is not None
        assert result.user_id == uid


class TestInMemoryCreate:
    """Test in-memory create."""

    @pytest.mark.asyncio
    async def test_success(self):
        repo = InMemoryLearningProfileRepository()
        profile = LearningProfile(user_id=uuid4())
        result = await repo.create(profile)
        assert result.user_id == profile.user_id
        assert repo.count() == 1

    @pytest.mark.asyncio
    async def test_duplicate_raises(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        profile = LearningProfile(user_id=uid)
        await repo.create(profile)
        with pytest.raises(ValueError, match="already exists"):
            await repo.create(profile)


class TestInMemoryUpdate:
    """Test in-memory update."""

    @pytest.mark.asyncio
    async def test_success(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        profile = LearningProfile(user_id=uid)
        await repo.create(profile)
        profile.current_level = LearnerLevel.OFFICER
        result = await repo.update(profile)
        assert result.current_level == LearnerLevel.OFFICER

    @pytest.mark.asyncio
    async def test_upserts(self):
        """Update can work even if profile doesn't exist (upsert)."""
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        profile = LearningProfile(user_id=uid, current_level=LearnerLevel.CAPTAIN)
        result = await repo.update(profile)
        assert result.current_level == LearnerLevel.CAPTAIN


class TestInMemoryDelete:
    """Test in-memory delete."""

    @pytest.mark.asyncio
    async def test_existing(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        await repo.create(LearningProfile(user_id=uid))
        assert await repo.delete(uid) is True
        assert repo.count() == 0

    @pytest.mark.asyncio
    async def test_not_found(self):
        repo = InMemoryLearningProfileRepository()
        assert await repo.delete(uuid4()) is False


class TestInMemoryGetOrCreate:
    """Test in-memory get_or_create."""

    @pytest.mark.asyncio
    async def test_creates_new(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        result = await repo.get_or_create(uid)
        assert result.user_id == uid
        assert result.current_level == LearnerLevel.CADET
        assert repo.count() == 1

    @pytest.mark.asyncio
    async def test_returns_existing(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        profile = LearningProfile(user_id=uid, current_level=LearnerLevel.OFFICER)
        await repo.create(profile)
        result = await repo.get_or_create(uid)
        assert result.current_level == LearnerLevel.OFFICER
        assert repo.count() == 1  # No duplicate


class TestInMemoryAddAssessment:
    """Test in-memory add_assessment."""

    @pytest.mark.asyncio
    async def test_adds_assessment(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        assessment = Assessment(topic="Rule 15", score=85.0, questions_asked=10, correct_answers=8)
        result = await repo.add_assessment(uid, assessment)
        assert len(result.assessment_history) == 1
        assert "Rule 15" in result.completed_topics

    @pytest.mark.asyncio
    async def test_creates_profile_if_not_exists(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        assessment = Assessment(topic="SOLAS", score=30.0, questions_asked=5, correct_answers=1)
        result = await repo.add_assessment(uid, assessment)
        assert repo.count() == 1
        assert "SOLAS" in result.weak_topics


class TestInMemoryUpdateLevel:
    """Test in-memory update_level."""

    @pytest.mark.asyncio
    async def test_updates_level(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        result = await repo.update_level(uid, LearnerLevel.CAPTAIN)
        assert result.current_level == LearnerLevel.CAPTAIN


class TestInMemoryUpdateLearningStyle:
    """Test in-memory update_learning_style."""

    @pytest.mark.asyncio
    async def test_updates_style(self):
        repo = InMemoryLearningProfileRepository()
        uid = uuid4()
        result = await repo.update_learning_style(uid, LearningStyle.PRACTICAL)
        assert result.learning_style == LearningStyle.PRACTICAL


class TestInMemoryCountClear:
    """Test in-memory count and clear."""

    @pytest.mark.asyncio
    async def test_count(self):
        repo = InMemoryLearningProfileRepository()
        assert repo.count() == 0
        await repo.create(LearningProfile(user_id=uuid4()))
        assert repo.count() == 1

    @pytest.mark.asyncio
    async def test_clear(self):
        repo = InMemoryLearningProfileRepository()
        await repo.create(LearningProfile(user_id=uuid4()))
        repo.clear()
        assert repo.count() == 0


# ============================================================================
# LearningProfileRepository
# ============================================================================


def _make_pg_repo(available=True):
    """Create LearningProfileRepository with mocked DB.

    Lazy import inside _init_connection(): patch at source module
    app.core.database.get_shared_engine / get_shared_session_factory
    """
    with patch("app.core.database.get_shared_engine") as mock_eng, \
         patch("app.core.database.get_shared_session_factory") as mock_sf:

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_sf.return_value = lambda: mock_session

        if not available:
            mock_session.execute.side_effect = Exception("Connection refused")

        repo = LearningProfileRepository()

    if available:
        repo._available = True
        # Re-setup session factory for test methods
        mock_session_inner = MagicMock()
        mock_session_inner.__enter__ = lambda s: mock_session_inner
        mock_session_inner.__exit__ = MagicMock(return_value=False)
        repo._session_factory = lambda: mock_session_inner
        return repo, mock_session_inner
    return repo, None


class TestPgInit:
    """Test PG repository initialization."""

    def test_available(self):
        repo, _ = _make_pg_repo(available=True)
        assert repo.is_available() is True

    def test_unavailable(self):
        repo, _ = _make_pg_repo(available=False)
        assert repo.is_available() is False


class TestPgConvertUserId:
    """Test user ID conversion."""

    def test_valid_uuid(self):
        repo, _ = _make_pg_repo()
        uid = str(uuid4())
        result = repo._convert_user_id(uid)
        assert isinstance(result, UUID)

    def test_invalid_uuid(self):
        repo, _ = _make_pg_repo()
        result = repo._convert_user_id("test-user")
        assert result == "test-user"


class TestPgGet:
    """Test PG get."""

    @pytest.mark.asyncio
    async def test_found(self):
        repo, session = _make_pg_repo()
        mock_row = (
            str(uuid4()),
            {"level": "beginner"},
            ["Rule 15"],
            ["Rule 7"],
            5,
            20,
            None,
            "default",
        )
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        session.execute.return_value = mock_result

        result = await repo.get("user1")
        assert result is not None
        assert result["total_sessions"] == 5

    @pytest.mark.asyncio
    async def test_not_found(self):
        repo, session = _make_pg_repo()
        mock_result = MagicMock()
        mock_result.fetchone.return_value = None
        session.execute.return_value = mock_result

        result = await repo.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_unavailable(self):
        repo, _ = _make_pg_repo(available=False)
        result = await repo.get("user1")
        assert result is None

    @pytest.mark.asyncio
    async def test_error(self):
        repo, session = _make_pg_repo()
        session.execute.side_effect = Exception("DB error")
        result = await repo.get("user1")
        assert result is None


class TestPgCreate:
    """Test PG create."""

    @pytest.mark.asyncio
    async def test_success(self):
        repo, session = _make_pg_repo()
        # Mock the get call after create
        mock_row = ("user1", {"level": "beginner"}, [], [], 0, 0, None, "default")
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        session.execute.return_value = mock_result

        result = await repo.create("user1")
        assert result is not None

    @pytest.mark.asyncio
    async def test_unavailable(self):
        repo, _ = _make_pg_repo(available=False)
        result = await repo.create("user1")
        assert result is None

    @pytest.mark.asyncio
    async def test_error(self):
        repo, session = _make_pg_repo()
        session.execute.side_effect = Exception("DB error")
        result = await repo.create("user1")
        assert result is None


class TestPgUpdateWeakAreas:
    """Test PG update_weak_areas."""

    @pytest.mark.asyncio
    async def test_success(self):
        repo, session = _make_pg_repo()
        result = await repo.update_weak_areas("user1", ["Rule 15", "SOLAS"])
        assert result is True

    @pytest.mark.asyncio
    async def test_unavailable(self):
        repo, _ = _make_pg_repo(available=False)
        result = await repo.update_weak_areas("user1", ["Rule 15"])
        assert result is False

    @pytest.mark.asyncio
    async def test_error(self):
        repo, session = _make_pg_repo()
        session.execute.side_effect = Exception("DB error")
        result = await repo.update_weak_areas("user1", ["Rule 15"])
        assert result is False


class TestPgUpdateStrongAreas:
    """Test PG update_strong_areas."""

    @pytest.mark.asyncio
    async def test_success(self):
        repo, session = _make_pg_repo()
        result = await repo.update_strong_areas("user1", ["Rule 7"])
        assert result is True

    @pytest.mark.asyncio
    async def test_unavailable(self):
        repo, _ = _make_pg_repo(available=False)
        result = await repo.update_strong_areas("user1", [])
        assert result is False


class TestPgIncrementStats:
    """Test PG increment_stats."""

    @pytest.mark.asyncio
    async def test_success(self):
        repo, session = _make_pg_repo()
        # Mock get_or_create (returns profile dict or creates)
        mock_row = ("user1", {}, [], [], 0, 0, None, "default")
        mock_result = MagicMock()
        mock_result.fetchone.return_value = mock_row
        session.execute.return_value = mock_result

        result = await repo.increment_stats("user1", messages=3)
        assert result is True

    @pytest.mark.asyncio
    async def test_unavailable(self):
        repo, _ = _make_pg_repo(available=False)
        result = await repo.increment_stats("user1")
        assert result is False


class TestPgSingleton:
    """Test singleton factory."""

    def test_get_learning_profile_repository(self):
        import app.repositories.learning_profile_repository as mod
        mod._pg_profile_repo = None

        with patch("app.core.database.get_shared_engine"), \
             patch("app.core.database.get_shared_session_factory") as mock_sf:
            mock_session = MagicMock()
            mock_session.__enter__ = lambda s: mock_session
            mock_session.__exit__ = MagicMock(return_value=False)
            mock_sf.return_value = lambda: mock_session

            r1 = mod.get_learning_profile_repository()
            r2 = mod.get_learning_profile_repository()
            assert r1 is r2

        mod._pg_profile_repo = None  # Cleanup
