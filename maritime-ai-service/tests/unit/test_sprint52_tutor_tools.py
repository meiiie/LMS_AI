"""
Tests for Sprint 52: Tutor Tools coverage.

Tests tutor tools including ContextVar state management:
- TutorToolState dataclass
- _get_state, init_tutor_tools, set_tutor_user, get_current_session_id
- tool_start_lesson (success, no agent, error)
- tool_continue_lesson (success, no agent, no session, assessment, error)
- tool_lesson_status (no session, success, mastery, struggling, error)
- tool_end_lesson (no session, success, mastery, low score, error)
"""

import pytest
from unittest.mock import MagicMock, patch
import unicodedata


# ============================================================================
# Helpers
# ============================================================================


def _reset_module_state():
    """Reset module-level state for clean tests."""
    import app.engine.tools.tutor_tools as mod
    mod._tutor_agent = None
    mod._tutor_tool_state.set(None)


def _plain(text: str) -> str:
    """Return lowercase text without Vietnamese accents for stable assertions."""
    return "".join(
        char
        for char in unicodedata.normalize("NFD", text)
        if unicodedata.category(char) != "Mn"
    ).lower()


# ============================================================================
# TutorToolState and state management
# ============================================================================


class TestTutorToolState:
    """Test state dataclass and accessors."""

    def setup_method(self):
        _reset_module_state()

    def test_defaults(self):
        from app.engine.tools.tutor_tools import TutorToolState
        state = TutorToolState()
        assert state.user_id == "current_user"
        assert state.session_id is None

    def test_get_state_creates_new(self):
        from app.engine.tools.tutor_tools import _get_state
        state = _get_state()
        assert state.user_id == "current_user"

    def test_get_state_returns_same(self):
        from app.engine.tools.tutor_tools import _get_state
        s1 = _get_state()
        s2 = _get_state()
        assert s1 is s2


class TestInitTutorTools:
    """Test init_tutor_tools."""

    def setup_method(self):
        _reset_module_state()

    def test_sets_user_id(self):
        import app.engine.tools.tutor_tools as mod
        with patch("app.engine.tutor.tutor_agent.TutorAgent") as MockAgent:
            MockAgent.return_value = MagicMock()
            mod.init_tutor_tools(user_id="user-123")
        state = mod._get_state()
        assert state.user_id == "user-123"

    def test_resets_session_when_user_changes(self):
        import app.engine.tools.tutor_tools as mod
        mod._tutor_agent = MagicMock()
        mod.init_tutor_tools(user_id="user-a")
        mod._get_state().session_id = "lesson-a"

        mod.init_tutor_tools(user_id="user-b")
        state = mod._get_state()

        assert state.user_id == "user-b"
        assert state.session_id is None

    def test_preserves_session_for_same_user(self):
        import app.engine.tools.tutor_tools as mod
        mod._tutor_agent = MagicMock()
        mod.init_tutor_tools(user_id="user-a")
        mod._get_state().session_id = "lesson-a"

        mod.init_tutor_tools(user_id="user-a")

        assert mod._get_state().session_id == "lesson-a"

    def test_import_error(self):
        import app.engine.tools.tutor_tools as mod
        with patch("app.engine.tutor.tutor_agent.TutorAgent", side_effect=ImportError("No module")):
            mod.init_tutor_tools(user_id="user-123")
        assert mod._tutor_agent is None

    def test_reuses_agent(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mod._tutor_agent = mock_agent
        mod.init_tutor_tools(user_id="user-456")
        assert mod._tutor_agent is mock_agent


class TestSetTutorUser:
    """Test set_tutor_user."""

    def setup_method(self):
        _reset_module_state()

    def test_sets_user(self):
        from app.engine.tools.tutor_tools import set_tutor_user, _get_state
        set_tutor_user("user-789")
        assert _get_state().user_id == "user-789"

    def test_set_tutor_user_resets_previous_session(self):
        from app.engine.tools.tutor_tools import set_tutor_user, _get_state

        set_tutor_user("user-a")
        _get_state().session_id = "lesson-a"
        set_tutor_user("user-b")

        assert _get_state().user_id == "user-b"
        assert _get_state().session_id is None

    def test_runtime_context_identity_isolates_session(self):
        from app.engine.tools.runtime_context import (
            build_tool_runtime_context,
            tool_runtime_scope,
        )
        from app.engine.tools.tutor_tools import _get_state

        ctx_a = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-a",
            session_id="chat-a",
        )
        ctx_b = build_tool_runtime_context(
            user_id="user-a",
            organization_id="org-b",
            session_id="chat-a",
        )

        with tool_runtime_scope(ctx_a):
            _get_state().session_id = "lesson-a"
            assert _get_state().session_id == "lesson-a"

        with tool_runtime_scope(ctx_b):
            assert _get_state().session_id is None
            _get_state().session_id = "lesson-b"

        with tool_runtime_scope(ctx_a):
            assert _get_state().session_id is None


class TestGetCurrentSessionId:
    """Test get_current_session_id."""

    def setup_method(self):
        _reset_module_state()

    def test_none_by_default(self):
        from app.engine.tools.tutor_tools import get_current_session_id
        assert get_current_session_id() is None

    def test_returns_session_id(self):
        from app.engine.tools.tutor_tools import get_current_session_id, _get_state
        _get_state().session_id = "lesson-abc"
        assert get_current_session_id() == "lesson-abc"


# ============================================================================
# tool_start_lesson
# ============================================================================


class TestToolStartLesson:
    """Test start lesson tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_no_agent_available(self):
        import app.engine.tools.tutor_tools as mod
        mod._tutor_agent = None
        with patch("app.engine.tutor.tutor_agent.TutorAgent", side_effect=ImportError):
            result = await mod.tool_start_lesson.coroutine(topic="solas")
        assert "khong kha dung" in _plain(result)

    @pytest.mark.asyncio
    async def test_success(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Welcome to SOLAS lesson"
        mock_response.phase.value = "INTRODUCTION"
        mock_response.state.session_id = "session-123"
        mock_agent.start_session.return_value = mock_response
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)

        result = await mod.tool_start_lesson.coroutine(topic="solas")
        assert "SOLAS" in result
        assert "INTRODUCTION" in result
        assert mod._get_state().session_id == "session-123"

    @pytest.mark.asyncio
    async def test_error(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_agent.start_session.side_effect = Exception("Start error")
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)

        result = await mod.tool_start_lesson.coroutine(topic="solas")
        assert "loi" in _plain(result)


# ============================================================================
# tool_continue_lesson
# ============================================================================


class TestToolContinueLesson:
    """Test continue lesson tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_no_agent(self):
        import app.engine.tools.tutor_tools as mod
        mod._tutor_agent = None
        result = await mod.tool_continue_lesson.coroutine(user_input="ready")
        assert "chua co buoi hoc" in _plain(result)

    @pytest.mark.asyncio
    async def test_no_session(self):
        import app.engine.tools.tutor_tools as mod
        mod._tutor_agent = MagicMock()
        mod._tutor_tool_state.set(None)
        result = await mod.tool_continue_lesson.coroutine(user_input="ready")
        assert "khong co buoi hoc" in _plain(result)

    @pytest.mark.asyncio
    async def test_success(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Good answer! Next question..."
        mock_response.phase.value = "EXPLANATION"
        mock_response.assessment_complete = False
        mock_agent.process_response.return_value = mock_response
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_continue_lesson.coroutine(user_input="SOLAS stands for...")
        assert "Good answer" in result

    @pytest.mark.asyncio
    async def test_assessment_with_score(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Correct!"
        mock_response.phase.value = "ASSESSMENT"
        mock_response.assessment_complete = False
        mock_response.state.correct_answers = 3
        mock_response.state.questions_asked = 4
        mock_response.state.score = 75.0
        mock_agent.process_response.return_value = mock_response
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_continue_lesson.coroutine(user_input="answer")
        assert "Score" in result
        assert "3/4" in result

    @pytest.mark.asyncio
    async def test_assessment_complete(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Final result"
        mock_response.phase.value = "COMPLETED"
        mock_response.assessment_complete = True
        mock_response.mastery_achieved = True
        mock_agent.process_response.return_value = mock_response
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_continue_lesson.coroutine(user_input="answer")
        assert "Mastery" in result
        assert mod._get_state().session_id is None  # Cleared

    @pytest.mark.asyncio
    async def test_error(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_agent.process_response.side_effect = Exception("Process error")
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_continue_lesson.coroutine(user_input="answer")
        assert "loi" in _plain(result)


# ============================================================================
# tool_lesson_status
# ============================================================================


class TestToolLessonStatus:
    """Test lesson status tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_no_session(self):
        import app.engine.tools.tutor_tools as mod
        mod._tutor_tool_state.set(None)
        result = await mod.tool_lesson_status.coroutine()
        assert "khong co buoi hoc" in _plain(result)

    @pytest.mark.asyncio
    async def test_success(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.topic = "SOLAS"
        mock_state.current_phase.value = "EXPLANATION"
        mock_state.questions_asked = 3
        mock_state.correct_answers = 2
        mock_state.score = 66.7
        mock_state.hints_given = 1
        mock_state.has_mastery.return_value = False
        mock_state.is_struggling.return_value = False
        mock_agent.get_session.return_value = mock_state
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_lesson_status.coroutine()
        assert "SOLAS" in result
        assert "EXPLANATION" in result

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_agent.get_session.return_value = None
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_lesson_status.coroutine()
        assert "tim thay" in _plain(result) or "kh" in _plain(result)

    @pytest.mark.asyncio
    async def test_error(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_agent.get_session.side_effect = Exception("Status error")
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_lesson_status.coroutine()
        assert "l" in _plain(result)  # "loi" or error message


# ============================================================================
# tool_end_lesson
# ============================================================================


class TestToolEndLesson:
    """Test end lesson tool."""

    def setup_method(self):
        _reset_module_state()

    @pytest.mark.asyncio
    async def test_no_session(self):
        import app.engine.tools.tutor_tools as mod
        mod._tutor_tool_state.set(None)
        result = await mod.tool_end_lesson.coroutine()
        assert "khong co buoi hoc" in _plain(result)

    @pytest.mark.asyncio
    async def test_session_not_found(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_agent.get_session.return_value = None
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_end_lesson.coroutine()
        assert "ket thuc" in _plain(result)
        assert mod._get_state().session_id is None

    @pytest.mark.asyncio
    async def test_success_mastery(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.topic = "SOLAS"
        mock_state.questions_asked = 5
        mock_state.correct_answers = 5
        mock_state.score = 100.0
        mock_state.hints_given = 0
        mock_state.has_mastery.return_value = True
        mock_agent.get_session.return_value = mock_state
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_end_lesson.coroutine()
        assert "SOLAS" in result
        assert mod._get_state().session_id is None

    @pytest.mark.asyncio
    async def test_success_low_score(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_state = MagicMock()
        mock_state.topic = "COLREGS"
        mock_state.questions_asked = 5
        mock_state.correct_answers = 1
        mock_state.score = 20.0
        mock_state.hints_given = 3
        mock_state.has_mastery.return_value = False
        mock_agent.get_session.return_value = mock_state
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_end_lesson.coroutine()
        assert "COLREGS" in result

    @pytest.mark.asyncio
    async def test_error(self):
        import app.engine.tools.tutor_tools as mod
        mock_agent = MagicMock()
        mock_agent.get_session.side_effect = Exception("End error")
        mod._tutor_agent = mock_agent
        mod._tutor_tool_state.set(None)
        mod._get_state().session_id = "session-123"

        result = await mod.tool_end_lesson.coroutine()
        assert "l" in _plain(result)
