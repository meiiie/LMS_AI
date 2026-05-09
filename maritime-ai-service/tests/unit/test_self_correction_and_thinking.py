"""Tests for self-correction loop and thinking preservation (Phase 2+ extras)."""

import pytest

from app.engine.multi_agent.runner import WiiiRunner


class TestSelfCorrection:
    """Verify orchestrator-level self-correction retry logic."""

    @pytest.fixture
    def runner(self):
        return WiiiRunner()

    # -- _should_retry_response tests --

    def test_no_retry_on_turn_0(self, runner):
        """Should not retry before any agent has executed."""
        state = {"_runner_error": "something broke"}
        assert runner._should_retry_response(state, turn=0) is False

    def test_no_retry_when_response_is_good(self, runner):
        state = {
            "final_response": "Đây là câu trả lời đầy đủ và chi tiết cho câu hỏi của bạn.",
            "grader_score": 8.0,
        }
        assert runner._should_retry_response(state, turn=1) is False

    def test_retry_on_empty_response(self, runner):
        state = {"final_response": ""}
        assert runner._should_retry_response(state, turn=1) is True

    def test_retry_on_short_response(self, runner):
        state = {"final_response": "  short  "}
        assert runner._should_retry_response(state, turn=1) is True

    def test_no_retry_on_intentional_direct_reply_only_ack(self, runner):
        state = {
            "final_response": "Đã ghi nhận.",
            "_direct_reply_only_ack": True,
        }
        assert runner._should_retry_response(state, turn=1) is False

    def test_retry_on_runner_error(self, runner):
        state = {
            "final_response": "Some response",
            "_runner_error": "RAG agent crashed",
        }
        assert runner._should_retry_response(state, turn=1) is True

    def test_retry_on_low_grader_score(self, runner):
        state = {
            "final_response": "Response text that is long enough",
            "grader_score": 2.5,
        }
        assert runner._should_retry_response(state, turn=1) is True

    def test_no_retry_on_decent_grader_score(self, runner):
        """Good grader score should prevent retry even with short response."""
        state = {
            "final_response": "OK",
            "grader_score": 5.0,
        }
        assert runner._should_retry_response(state, turn=1) is False

    def test_max_one_retry(self, runner):
        """After 1 retry, should not retry again."""
        state = {
            "final_response": "",
            "_self_correction_retry": 1,
        }
        assert runner._should_retry_response(state, turn=1) is False

    def test_first_retry_allowed(self, runner):
        """First retry (retry count 0) is allowed."""
        state = {
            "final_response": "",
            "_self_correction_retry": 0,
        }
        assert runner._should_retry_response(state, turn=1) is True

    # -- Integration: _resolve_next_step produces self-correction handoff --

    @pytest.mark.asyncio
    async def test_resolve_produces_self_correction_handoff(self, runner):
        """When response is bad, _resolve_next_step should route to supervisor."""
        from app.engine.multi_agent.next_step import NextStepHandoff

        state = {
            "current_agent": "rag_agent",
            "final_response": "",
            "_orchestrator_turn": 1,
            "_agentic_continue": None,
            "_handoff_target": None,
            "_handoff_count": 0,
            "_self_correction_retry": 0,
        }
        step = await runner._resolve_next_step(state, turn=1)
        assert isinstance(step, NextStepHandoff)
        assert step.target_agent == "supervisor"
        assert step.reason == "self_correction_retry"

    @pytest.mark.asyncio
    async def test_resolve_no_self_correction_after_retry(self, runner):
        """After a retry has happened, should finalize instead."""
        from app.engine.multi_agent.next_step import NextStepFinalOutput

        state = {
            "current_agent": "rag_agent",
            "final_response": "",
            "_orchestrator_turn": 2,
            "_agentic_continue": None,
            "_handoff_target": None,
            "_handoff_count": 0,
            "_self_correction_retry": 1,
        }
        step = await runner._resolve_next_step(state, turn=2)
        assert isinstance(step, NextStepFinalOutput)

    @pytest.mark.asyncio
    async def test_self_correction_increments_counter(self, runner):
        """Self-correction should increment _self_correction_retry."""
        state = {
            "current_agent": "rag_agent",
            "final_response": "",
            "_orchestrator_turn": 1,
            "_agentic_continue": None,
            "_handoff_target": None,
            "_handoff_count": 0,
            "_self_correction_retry": 0,
        }
        await runner._resolve_next_step(state, turn=1)
        assert state["_self_correction_retry"] == 1


class TestThinkingPreservation:
    """Verify thinking is preserved across NextStep turns."""

    @pytest.fixture
    def runner(self):
        return WiiiRunner()

    def test_preserve_thinking_content(self, runner):
        """thinking_content should be saved to history."""
        state = {
            "current_agent": "rag_agent",
            "_orchestrator_turn": 1,
            "thinking_content": "User asks about COLREGs Rule 15...",
            "_thinking_history": [],
        }
        runner._preserve_thinking(state)

        history = state["_thinking_history"]
        assert len(history) == 1
        assert history[0]["turn"] == 1
        assert history[0]["agent"] == "rag_agent"
        assert history[0]["thinking_content"] == "User asks about COLREGs Rule 15..."

    def test_preserve_fragments(self, runner):
        """Public thinking fragments should be saved."""
        state = {
            "current_agent": "tutor_agent",
            "_orchestrator_turn": 2,
            "_public_thinking_fragments": ["fragment 1", "fragment 2"],
            "_thinking_history": [],
        }
        runner._preserve_thinking(state)

        history = state["_thinking_history"]
        assert len(history) == 1
        assert history[0]["fragments"] == ["fragment 1", "fragment 2"]

    def test_preserve_native_thinking(self, runner):
        """Native Gemini thinking should be preserved."""
        state = {
            "current_agent": "direct",
            "_orchestrator_turn": 0,
            "thinking": "Deep reasoning about the query...",
            "_thinking_history": [],
        }
        runner._preserve_thinking(state)

        history = state["_thinking_history"]
        assert len(history) == 1
        assert history[0]["thinking"] == "Deep reasoning about the query..."

    def test_no_preserve_when_empty(self, runner):
        """Should not add entry when no thinking data exists."""
        state = {
            "current_agent": "rag_agent",
            "_orchestrator_turn": 1,
            "_thinking_history": [],
        }
        runner._preserve_thinking(state)
        assert len(state["_thinking_history"]) == 0

    def test_accumulates_across_turns(self, runner):
        """History should accumulate across multiple calls."""
        state = {
            "current_agent": "rag_agent",
            "_orchestrator_turn": 0,
            "thinking_content": "First thinking",
            "_thinking_history": [],
        }
        runner._preserve_thinking(state)

        state["thinking_content"] = "Second thinking"
        state["_orchestrator_turn"] = 1
        runner._preserve_thinking(state)

        history = state["_thinking_history"]
        assert len(history) == 2
        assert history[0]["thinking_content"] == "First thinking"
        assert history[1]["thinking_content"] == "Second thinking"

    def test_initializes_empty_history(self, runner):
        """Should create _thinking_history list if missing."""
        state = {
            "current_agent": "rag_agent",
            "thinking_content": "Some thinking",
        }
        runner._preserve_thinking(state)
        assert "_thinking_history" in state
        assert len(state["_thinking_history"]) == 1
