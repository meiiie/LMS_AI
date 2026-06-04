"""
Tests for SessionSummarizer — Cross-session context via conversation summaries.

Verifies:
- summarize_thread with provided messages
- summarize_thread with no messages (returns None)
- summarize_thread when LLM is unavailable
- summarize_thread when LLM raises an exception
- get_recent_summaries with results
- get_recent_summaries empty (no threads)
- get_recent_summaries when repository raises an exception
- _format_messages truncation and labeling
- _format_messages with empty list
- _save_summary delegation to repository
- singleton get_session_summarizer
"""

import pytest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, MagicMock

from app.services.session_summarizer import (
    SessionSummarizer,
    get_session_summarizer,
    SUMMARIZE_PROMPT,
)


# =============================================================================
# Fixtures
# =============================================================================

SAMPLE_MESSAGES = [
    {"role": "human", "content": "COLREG Rule 5 la gi?"},
    {"role": "ai", "content": "Rule 5 yeu cau moi tau phai duy tri canh gioi thuong xuyen."},
    {"role": "human", "content": "Cam on, con Rule 6?"},
    {"role": "ai", "content": "Rule 6 quy dinh ve toc do an toan."},
]


def _make_llm_response(content: str) -> MagicMock:
    """Create a mock LLM response with .content attribute."""
    response = MagicMock()
    response.content = content
    return response


# =============================================================================
# TestSummarizeThread
# =============================================================================

class TestSummarizeThread:
    """Test summarize_thread() method."""

    @pytest.mark.asyncio
    async def test_summarize_with_provided_messages(self):
        """summarize_thread generates a summary when messages are provided."""
        summarizer = SessionSummarizer()

        summary_text = "Nguoi dung hoi ve COLREG Rule 5 va Rule 6. Tro ly giai thich noi dung cac quy tac."
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=_make_llm_response(summary_text))
        summarizer._llm = mock_llm

        with patch.object(summarizer, "_save_summary") as mock_save:
            result = await summarizer.summarize_thread(
                thread_id="user_abc__session_001",
                user_id="abc",
                messages=SAMPLE_MESSAGES,
            )

        assert result == summary_text
        mock_llm.ainvoke.assert_awaited_once()
        mock_save.assert_called_once_with(
            "user_abc__session_001",
            "abc",
            summary_text,
            organization_id=None,
        )

    @pytest.mark.asyncio
    async def test_summarize_passes_org_scope_to_summary_write(self):
        """Generated summaries persist through the active org boundary."""
        summarizer = SessionSummarizer()

        summary_text = "Nguoi dung hoi ve COLREG."
        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(return_value=_make_llm_response(summary_text))
        summarizer._llm = mock_llm

        with patch.object(summarizer, "_save_summary") as mock_save:
            result = await summarizer.summarize_thread(
                thread_id="user_abc__session_001",
                user_id="abc",
                messages=SAMPLE_MESSAGES,
                organization_id="org-active",
            )

        assert result == summary_text
        mock_save.assert_called_once_with(
            "user_abc__session_001",
            "abc",
            summary_text,
            organization_id="org-active",
        )

    @pytest.mark.asyncio
    async def test_summarize_no_messages_returns_none(self):
        """summarize_thread returns None when no messages are provided and none are loaded."""
        summarizer = SessionSummarizer()

        mock_llm = AsyncMock()
        summarizer._llm = mock_llm

        with patch.object(summarizer, "_load_thread_messages", new_callable=AsyncMock, return_value=[]):
            result = await summarizer.summarize_thread(
                thread_id="user_abc__session_002",
                user_id="abc",
                messages=None,
            )

        assert result is None
        mock_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_summarize_llm_unavailable_returns_none(self):
        """summarize_thread returns None when LLM cannot be loaded."""
        summarizer = SessionSummarizer()
        # _llm stays None, and _get_llm will fail

        with patch("app.engine.llm_pool.get_llm_light", side_effect=Exception("No LLM")):
            result = await summarizer.summarize_thread(
                thread_id="user_abc__session_003",
                user_id="abc",
                messages=SAMPLE_MESSAGES,
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_summarize_llm_exception_returns_none(self):
        """summarize_thread returns None when LLM.ainvoke raises an exception."""
        summarizer = SessionSummarizer()

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=Exception("LLM timeout"))
        summarizer._llm = mock_llm

        result = await summarizer.summarize_thread(
            thread_id="user_abc__session_004",
            user_id="abc",
            messages=SAMPLE_MESSAGES,
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_summarize_short_conversation_returns_none(self):
        """summarize_thread returns None when formatted text is too short (<20 chars)."""
        summarizer = SessionSummarizer()

        mock_llm = AsyncMock()
        summarizer._llm = mock_llm

        short_messages = [{"role": "human", "content": "Hi"}]
        result = await summarizer.summarize_thread(
            thread_id="user_abc__session_005",
            user_id="abc",
            messages=short_messages,
        )

        assert result is None
        mock_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_summarize_prompt_uses_truncated_text(self):
        """summarize_thread truncates conversation text to 3000 chars in prompt."""
        summarizer = SessionSummarizer()

        captured_prompt = None

        async def capture_invoke(prompt):
            nonlocal captured_prompt
            captured_prompt = prompt
            return _make_llm_response("Summary result.")

        mock_llm = AsyncMock()
        mock_llm.ainvoke = AsyncMock(side_effect=capture_invoke)
        summarizer._llm = mock_llm

        # Create messages with very long content
        long_messages = [
            {"role": "human", "content": "A" * 2000},
            {"role": "ai", "content": "B" * 2000},
        ]

        with patch.object(summarizer, "_save_summary"):
            await summarizer.summarize_thread(
                thread_id="user_abc__session_006",
                user_id="abc",
                messages=long_messages,
            )

        assert captured_prompt is not None
        # The conversation_text[:3000] is used in the prompt
        # So the entire prompt should be manageable, not contain full 4000+ chars of content
        assert len(captured_prompt) < 4000


# =============================================================================
# TestGetRecentSummaries
# =============================================================================

class TestGetRecentSummaries:
    """Test get_recent_summaries() method."""

    @pytest.mark.asyncio
    async def test_get_recent_summaries_with_results(self):
        """get_recent_summaries returns formatted summaries when threads exist."""
        summarizer = SessionSummarizer()

        mock_threads = [
            {"thread_id": "t1", "title": "COLREG Rules", "summary": "Discussed Rule 5 and Rule 6."},
            {"thread_id": "t2", "title": "SOLAS Chapter", "summary": "Reviewed fire safety."},
        ]

        mock_repo = MagicMock()
        mock_repo.get_threads_with_summaries.return_value = mock_threads

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            return_value=mock_repo,
        ):
            result = await summarizer.get_recent_summaries(user_id="abc", limit=15)

        assert "COLREG Rules" in result
        assert "Discussed Rule 5 and Rule 6." in result
        assert "SOLAS Chapter" in result
        assert "Reviewed fire safety." in result
        assert "LỊCH SỬ CÁC PHIÊN TRƯỚC" in result
        mock_repo.get_threads_with_summaries.assert_called_once_with(
            user_id="abc",
            limit=15,
            organization_id=None,
        )

    @pytest.mark.asyncio
    async def test_get_recent_summaries_passes_org_scope(self):
        """Layer 3 summaries are retrieved from the active org only."""
        summarizer = SessionSummarizer()

        mock_repo = MagicMock()
        mock_repo.get_threads_with_summaries.return_value = []

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            return_value=mock_repo,
        ):
            result = await summarizer.get_recent_summaries(
                user_id="abc",
                organization_id="org-active",
            )

        assert result == ""
        mock_repo.get_threads_with_summaries.assert_called_once_with(
            user_id="abc",
            limit=15,
            organization_id="org-active",
        )

    @pytest.mark.asyncio
    async def test_get_recent_summaries_empty(self):
        """get_recent_summaries returns empty string when no threads have summaries."""
        summarizer = SessionSummarizer()

        mock_repo = MagicMock()
        mock_repo.get_threads_with_summaries.return_value = []

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            return_value=mock_repo,
        ):
            result = await summarizer.get_recent_summaries(user_id="abc")

        assert result == ""

    @pytest.mark.asyncio
    async def test_get_recent_summaries_repo_exception(self):
        """get_recent_summaries returns empty string on repository failure."""
        summarizer = SessionSummarizer()

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            side_effect=Exception("DB connection failed"),
        ):
            result = await summarizer.get_recent_summaries(user_id="abc")

        assert result == ""


# =============================================================================
# TestFormatMessages
# =============================================================================

class TestFormatMessages:
    """Test _format_messages static method."""

    def test_format_basic_messages(self):
        """Messages are formatted with Vietnamese role labels."""
        result = SessionSummarizer._format_messages(SAMPLE_MESSAGES)

        assert "Người dùng: COLREG Rule 5 la gi?" in result
        assert "Trợ lý: Rule 5 yeu cau" in result

    def test_format_truncates_long_content(self):
        """Individual message content is truncated to 300 chars."""
        messages = [{"role": "human", "content": "X" * 500}]
        result = SessionSummarizer._format_messages(messages)

        # Each message content is truncated to 300 chars
        # "Người dùng: " prefix + 300 chars of X
        lines = result.strip().split("\n")
        assert len(lines) == 1
        content_part = lines[0].split(": ", 1)[1]
        assert len(content_part) == 300

    def test_format_limits_to_last_15(self):
        """Only the last 15 messages are included."""
        messages = [{"role": "human", "content": f"Message {i}"} for i in range(25)]
        result = SessionSummarizer._format_messages(messages)

        lines = [line for line in result.strip().split("\n") if line]
        assert len(lines) == 15
        # Should contain messages 10-24 (last 15)
        assert "Message 10" in result
        assert "Message 24" in result
        assert "Message 9" not in result

    def test_format_empty_messages(self):
        """Empty message list returns empty string."""
        result = SessionSummarizer._format_messages([])
        assert result == ""

    def test_format_skips_empty_content(self):
        """Messages with empty content are skipped."""
        messages = [
            {"role": "human", "content": "Hello"},
            {"role": "ai", "content": ""},
            {"role": "human", "content": "Question"},
        ]
        result = SessionSummarizer._format_messages(messages)

        lines = [line for line in result.strip().split("\n") if line]
        assert len(lines) == 2
        assert "Hello" in result
        assert "Question" in result


# =============================================================================
# TestSaveSummary
# =============================================================================

class TestSaveSummary:
    """Test _save_summary method."""

    def test_save_summary_calls_repository(self):
        """_save_summary delegates to thread repository update_extra_data."""
        summarizer = SessionSummarizer()

        mock_repo = MagicMock()

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            return_value=mock_repo,
        ):
            summarizer._save_summary(
                thread_id="user_abc__session_001",
                user_id="abc",
                summary="Test summary.",
            )

        mock_repo.update_extra_data.assert_called_once_with(
            thread_id="user_abc__session_001",
            user_id="abc",
            extra_data={"summary": "Test summary."},
            organization_id=None,
        )

    def test_save_summary_passes_org_scope(self):
        """_save_summary delegates with the resolved organization."""
        summarizer = SessionSummarizer()

        mock_repo = MagicMock()

        with patch(
            "app.repositories.thread_repository.get_thread_repository",
            return_value=mock_repo,
        ):
            summarizer._save_summary(
                thread_id="user_abc__session_001",
                user_id="abc",
                summary="Test summary.",
                organization_id="org-active",
            )

        mock_repo.update_extra_data.assert_called_once_with(
            thread_id="user_abc__session_001",
            user_id="abc",
            extra_data={"summary": "Test summary."},
            organization_id="org-active",
        )


class TestSessionSummaryContextInjection:
    """Test Layer 3 summary retrieval from the context builder path."""

    @pytest.mark.asyncio
    async def test_parallel_context_passes_request_org_to_recent_summaries(self):
        from app.services.input_processor_context_runtime import _populate_parallel_context

        summarizer = MagicMock()
        summarizer.get_recent_summaries = AsyncMock(return_value="Scoped summary")
        context = SimpleNamespace(semantic_context="", conversation_summary=None)
        semantic_parts: list[str] = []

        with patch(
            "app.services.session_summarizer.get_session_summarizer",
            return_value=summarizer,
        ):
            await _populate_parallel_context(
                context=context,
                request=SimpleNamespace(role=None, organization_id="org-active"),
                user_id="abc",
                message="Long enough message",
                session_id="session-1",
                learning_graph=None,
                memory_summarizer=None,
                semantic_parts=semantic_parts,
                logger_obj=MagicMock(),
            )

        summarizer.get_recent_summaries.assert_awaited_once_with(
            "abc",
            organization_id="org-active",
        )
        assert semantic_parts == ["Scoped summary"]


# =============================================================================
# TestSingleton
# =============================================================================

class TestSingleton:
    """Test get_session_summarizer singleton factory."""

    def test_get_session_summarizer_returns_instance(self):
        """get_session_summarizer returns a SessionSummarizer."""
        with patch("app.services.session_summarizer._summarizer", None):
            summarizer = get_session_summarizer()
            assert isinstance(summarizer, SessionSummarizer)

    def test_get_session_summarizer_is_singleton(self):
        """get_session_summarizer returns the same instance on repeated calls."""
        with patch("app.services.session_summarizer._summarizer", None):
            s1 = get_session_summarizer()
            s2 = get_session_summarizer()
            assert s1 is s2
