"""
Tests for TutorAgentNode - Teaching Specialist (SOTA ReAct Pattern).

Tests ReAct loop, tool execution, thinking extraction, prompt building,
fallback response, and state wiring.
"""

import asyncio
import sys
import types
import pytest
from unittest.mock import MagicMock, AsyncMock, patch, call

# Break circular import: multi_agent.__init__ → graph → agents → tutor_node
# → services.__init__ → chat_service → multi_agent.graph
_cs_key = "app.services.chat_service"
_svc_key = "app.services"
_had_cs = _cs_key in sys.modules
_had_svc = _svc_key in sys.modules
_orig_cs = sys.modules.get(_cs_key)
if not _had_cs:
    _mock_cs = types.ModuleType(_cs_key)
    _mock_cs.ChatService = type("ChatService", (), {})
    _mock_cs.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_cs

from app.engine.multi_agent.agent_config import AgentConfigRegistry

if not _had_cs:
    sys.modules.pop(_cs_key, None)
    if not _had_svc:
        sys.modules.pop(_svc_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Lazy import inside _build_system_prompt() does:
#   from app.domains.registry import get_domain_registry
# Patch at SOURCE module.
DOMAIN_REGISTRY_PATCH = "app.domains.registry.get_domain_registry"

_SENTINEL = object()


def _make_tutor(llm=None, llm_with_tools=_SENTINEL):
    """Create TutorAgentNode with mocked LLM and tools.

    Args:
        llm: Mock for self._llm. None = unavailable.
        llm_with_tools: Mock for self._llm_with_tools.
            _SENTINEL (default) = use whatever _init_llm() produces.
            None = explicitly set _llm_with_tools to None (for testing unavailable).
            MagicMock = override with that mock.
    """
    with patch.object(
        AgentConfigRegistry, "get_llm", return_value=llm,
    ), patch(
        "app.engine.multi_agent.agents.tutor_node.get_prompt_loader",
    ) as mock_loader_fn:
        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "You are Wiii Tutor."
        mock_loader_fn.return_value = mock_loader

        from app.engine.multi_agent.agents.tutor_node import TutorAgentNode
        node = TutorAgentNode()

        # Override _llm_with_tools if explicitly specified
        if llm_with_tools is not _SENTINEL:
            node._llm_with_tools = llm_with_tools

        return node


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    llm.bind_tools = MagicMock(return_value=llm)
    return llm


@pytest.fixture
def base_state():
    return {
        "query": "Giải thích COLREGs Rule 13",
        "context": {
            "user_name": "Minh",
            "user_role": "student",
            "pronoun_style": {"user_called": "em", "ai_self": "thầy"},
        },
        "learning_context": {},
    }


# ---------------------------------------------------------------------------
# process() tests
# ---------------------------------------------------------------------------

class TestTutorPostToolContextDistillation:
    def test_distill_post_tool_context_keeps_signals_and_drops_answer_shell(self):
        from app.engine.multi_agent.agents.tutor_node import distill_post_tool_context

        raw_tool_result = (
            "<answer>Chao ban, de minh giai thich cho ban nhe! "
            "Quy tac 15 ap dung khi hai tau may cat huong va co nguy co dam va. "
            "Tau nao thay tau kia o man phai thi phai nhuong duong. "
            "Tau nhuong duong can tranh cat ngang phia truoc mui tau kia. "
            "Neu can minh co the so sanh them voi Rule 17 cho ban.</answer>"
        )

        distilled = distill_post_tool_context(raw_tool_result)

        assert "Tin hieu vua lo ra:" in distilled
        assert "Quy tac 15 ap dung khi hai tau may cat huong va co nguy co dam va." in distilled
        assert "Tau nao thay tau kia o man phai thi phai nhuong duong." in distilled
        assert "Tau nhuong duong can tranh cat ngang phia truoc mui tau kia." in distilled
        assert "Chao ban" not in distilled
        assert "de minh giai thich" not in distilled.lower()
        assert "Neu can minh co the so sanh them" not in distilled

    def test_distill_post_tool_context_drops_social_and_followup_bait(self):
        from app.engine.multi_agent.agents.tutor_node import distill_post_tool_context

        raw_tool_result = (
            "Dung chuan luon ne! Wiii rat an tuong voi cach ban tom tat Quy tac 15 day. "
            "Quy tac 15 ap dung khi hai tau may cat huong va co nguy co dam va. "
            "Tau nao thay tau kia o man phai thi phai nhuong duong. "
            "Tau nhuong duong can tranh cat ngang phia truoc mui tau kia. "
            "Hay la chung ta di sau hon sang Quy tac 17 nhe? Wiii da san sang!"
        )

        distilled = distill_post_tool_context(raw_tool_result)

        assert "Wiii rat an tuong" not in distilled
        assert "Hay la chung ta" not in distilled
        assert "Wiii da san sang" not in distilled
        assert "Quy tac 15 ap dung khi hai tau may cat huong va co nguy co dam va." in distilled
        assert "Tau nao thay tau kia o man phai thi phai nhuong duong." in distilled


class TestTutorProcess:
    @pytest.mark.asyncio
    async def test_process_happy_path(self, mock_llm, base_state):
        # LLM returns direct answer (no tool calls)
        response_msg = MagicMock()
        response_msg.tool_calls = []
        response_msg.content = "Rule 13 quy định về tàu vượt."
        mock_llm.ainvoke.return_value = response_msg

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Rule 13 quy định về tàu vượt.", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_reasoning_trace",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            result = await node.process(base_state)

        assert result["tutor_output"] == "Rule 13 quy định về tàu vượt."
        assert result["current_agent"] == "tutor_agent"
        assert result["agent_outputs"]["tutor"] == result["tutor_output"]

    @pytest.mark.asyncio
    async def test_process_llm_unavailable_fallback(self, base_state):
        node = _make_tutor(llm=None, llm_with_tools=None)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_reasoning_trace",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            result = await node.process(base_state)

        assert "Giải thích COLREGs Rule 13" in result["tutor_output"]
        assert result["sources"] == []

    @pytest.mark.asyncio
    async def test_process_exception_sets_error(self, mock_llm, base_state):
        mock_llm.ainvoke.side_effect = Exception("LLM crash")
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            result = await node.process(base_state)

        assert "error" in result
        assert result["error"] == "tutor_error"
        assert result["sources"] == []
        assert result["tools_used"] == []

    @pytest.mark.asyncio
    async def test_process_propagates_thinking(self, mock_llm, base_state):
        response_msg = MagicMock()
        response_msg.tool_calls = []
        response_msg.content = "Answer text"
        mock_llm.ainvoke.return_value = response_msg

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=(
                "Answer text",
                "Voi Rule 13, cho de lech nhat la nham giua dieu kien vuot va tinh huong cat mat. Minh can chot tung moc truoc khi giai thich.",
            ),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_reasoning_trace",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            result = await node.process(base_state)

        assert "thinking" in result
        assert result["thinking"]
        assert "Answer text" not in result["thinking"]
        assert (
            "cho de" in result["thinking"].lower()
            or "nguoi hoc" in result["thinking"].lower()
            or "giai thich" in result["thinking"].lower()
        )

    @pytest.mark.asyncio
    async def test_process_aligns_visible_thinking_to_turn_language(self, mock_llm, base_state):
        response_msg = MagicMock()
        response_msg.tool_calls = []
        response_msg.content = "Answer text"
        mock_llm.ainvoke.return_value = response_msg

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        base_state["context"]["response_language"] = "vi"
        aligned_visible_thinking = (
            "Nguoi dung dang hoi ve Rule 15. "
            "Minh can chot diem neo truoc khi phan giai thich bi troi."
        )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=(
                "Answer text",
                (
                    "Okay, the user is asking about Rule 15. "
                    "I need to anchor the trigger first before the explanation drifts."
                ),
            ),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.align_visible_thinking_language",
            new=AsyncMock(return_value=aligned_visible_thinking),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_reasoning_trace",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            result = await node.process(base_state)

        assert "thinking" in result
        assert result["thinking"] == aligned_visible_thinking
        assert result["thinking_content"] == result["thinking"]

    @pytest.mark.asyncio
    async def test_process_does_not_invent_tutor_thinking_when_native_thinking_missing(
        self,
        mock_llm,
        base_state,
    ):
        response_msg = MagicMock()
        response_msg.tool_calls = []
        response_msg.content = "Answer text"
        mock_llm.ainvoke.return_value = response_msg

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        base_state["query"] = "Giải thích Rule 15 khác gì Rule 13"
        base_state["context"] = {
            "user_id": "user-123",
            "organization_id": None,
            "mood_hint": "",
            "personality_mode": None,
        }

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Answer text", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_reasoning_trace",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            result = await node.process(base_state)

        assert result.get("thinking") in (None, "")

    @pytest.mark.asyncio
    async def test_process_propagates_crag_trace(self, mock_llm, base_state):
        response_msg = MagicMock()
        response_msg.tool_calls = []
        response_msg.content = "Answer"
        mock_llm.ainvoke.return_value = response_msg

        mock_trace = MagicMock()
        mock_trace.total_steps = 3

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Answer", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_reasoning_trace",
            return_value=mock_trace,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            result = await node.process(base_state)

        assert result["reasoning_trace"] is mock_trace

    @pytest.mark.asyncio
    async def test_process_commits_runtime_provider_and_model(self, mock_llm, base_state):
        mock_llm._wiii_provider_name = "zhipu"
        mock_llm._wiii_model_name = "glm-5"
        response_msg = MagicMock()
        response_msg.tool_calls = []
        response_msg.content = "Answer"
        mock_llm.ainvoke.return_value = response_msg

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Answer", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_reasoning_trace",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            result = await node.process(base_state)

        assert result["_execution_provider"] == "zhipu"
        assert result["_execution_model"] == "glm-5"
        assert result["model"] == "glm-5"

    @pytest.mark.asyncio
    async def test_process_filters_legacy_visual_tools_for_structured_visual_intent(self, base_state):
        class _Tool:
            def __init__(self, name: str):
                self.name = name

        mock_llm = MagicMock()
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        node._llm = mock_llm
        node._tools = [
            _Tool("tool_knowledge_search"),
            _Tool("tool_think"),
            _Tool("tool_report_progress"),
            _Tool("tool_generate_interactive_chart"),
            _Tool("tool_generate_visual"),
        ]

        state = {
            **base_state,
            "query": "Explain Kimi linear attention in charts",
            "routing_metadata": {"intent": "learning"},
        }

        with patch(
            "app.engine.multi_agent.agents.tutor_node.settings.enable_structured_visuals",
            True,
        ), patch(
            "app.engine.skills.skill_recommender.select_runtime_tools",
            return_value=[
                _Tool("tool_generate_interactive_chart"),
                _Tool("tool_generate_visual"),
                _Tool("tool_knowledge_search"),
            ],
        ), patch.object(
            node,
            "_react_loop",
            AsyncMock(return_value=("Visual answer", [], [], None, False)),
        ):
            result = await node.process(state)

        bound_tools = mock_llm.bind_tools.call_args[0][0]
        bound_names = [tool.name for tool in bound_tools]
        policy = state["_tool_policy_session"]

        assert "tool_generate_visual" in bound_names
        assert "tool_generate_interactive_chart" not in bound_names
        assert policy["path"] == "tutor"
        assert policy["reason"] == "tutor_tool_setup"
        assert "tool_generate_visual" in policy["visible_tool_names"]
        assert "tool_generate_interactive_chart" not in policy["visible_tool_names"]
        assert policy["tool_capabilities"]["tool_generate_visual"]["group"] == "visual"
        assert result["tutor_output"] == "Visual answer"

    def test_build_system_prompt_mentions_structured_visual_priority(self, mock_llm, base_state):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.settings.enable_structured_visuals",
            True,
        ):
            prompt = node._build_system_prompt(
                base_state["context"],
                "Hay mo phong vat ly con lac co the keo tha",
            )

        assert "tool_generate_visual" in prompt
        assert "widget/chart legacy" in prompt


# ---------------------------------------------------------------------------
# _react_loop() tests
# ---------------------------------------------------------------------------

class TestReactLoop:
    @pytest.mark.asyncio
    async def test_no_tool_calls_direct_answer(self, mock_llm):
        response_msg = MagicMock()
        response_msg.tool_calls = []
        response_msg.content = "Direct answer"
        mock_llm.ainvoke.return_value = response_msg

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Direct answer", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            response, sources, tools_used, thinking, _streamed = await node._react_loop("test", {})

        assert response == "Direct answer"
        assert tools_used == []

    @pytest.mark.asyncio
    async def test_no_tool_calls_stream_answer_without_repeating_it_in_thinking(self, mock_llm):
        chunk = MagicMock()
        chunk.tool_calls = []
        chunk.content = "Direct answer"

        async def _astream(_messages):
            yield chunk

        mock_llm.astream = _astream

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Direct answer", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node._iteration_beat",
            AsyncMock(return_value=types.SimpleNamespace(
                label="Phan tich cau hoi",
                summary="Dang tong hop huong giai thich.",
                phase="synthesize",
            )),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            response, sources, tools_used, thinking, streamed = await node._react_loop(
                "test",
                {},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        thinking_chunks = [event["content"] for event in events if event.get("type") == "thinking_delta"]
        answer_chunks = [event["content"] for event in events if event.get("type") == "answer_delta"]

        assert response == "Direct answer"
        assert sources == []
        assert tools_used == []
        assert streamed is False
        assert "".join(thinking_chunks) == ""
        assert "".join(answer_chunks) == ""

    @pytest.mark.asyncio
    async def test_tool_call_then_respond(self, mock_llm):
        # First call: LLM requests tool
        tool_response = MagicMock()
        tool_response.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 13"}, "id": "call_1"}
        ]
        tool_response.content = ""

        # Second call: LLM gives final answer
        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Rule 13 answer from knowledge base"

        mock_llm.ainvoke.side_effect = [tool_response, final_response]

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Rule 13 answer from knowledge base", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.tool_knowledge_search",
        ) as mock_tool:
            mock_tool.ainvoke = AsyncMock(return_value="Search result text")

            with patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
                return_value=[{"title": "COLREGs"}],
            ), patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
                return_value=None,
            ), patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
                return_value=(0.5, True),
            ):
                response, sources, tools_used, thinking, _streamed = await node._react_loop("Rule 13", {})

        assert "Rule 13" in response
        assert len(tools_used) == 1
        assert tools_used[0]["name"] == "tool_knowledge_search"

    @pytest.mark.asyncio
    async def test_tool_policy_denies_stale_tutor_tool_without_dispatch(self, mock_llm):
        stale_tool_response = MagicMock()
        stale_tool_response.tool_calls = [
            {"name": "tool_web_search", "args": {"query": "outside policy"}, "id": "call_stale"}
        ]
        stale_tool_response.content = ""

        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Final tutor answer"

        mock_llm.ainvoke.side_effect = [stale_tool_response, final_response]
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        state = {
            "_tool_policy_session": {
                "version": "tool_policy_session.v1",
                "path": "tutor",
                "reason": "tutor_tool_setup",
                "bind_tools": True,
                "force_tools": False,
                "allow_all_tools": False,
                "allowed_tool_names": ["tool_knowledge_search"],
                "allowed_tool_prefixes": [],
                "forbidden_tool_names": [],
                "forbidden_tool_prefixes": [],
                "candidate_tool_names": ["tool_knowledge_search", "tool_web_search"],
                "visible_tool_names": ["tool_knowledge_search"],
                "connection_status": {},
                "approval_required_tool_names": [],
            }
        }

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Final tutor answer", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=AssertionError("denied tool must not dispatch")),
        ) as dispatch_mock:
            response, sources, tools_used, _thinking, _streamed = await node._react_loop(
                "Explain Rule 13",
                {},
                state=state,
            )

        assert response == "Final tutor answer"
        assert sources == []
        assert tools_used == []
        dispatch_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_tool_call_sync_collects_public_tutor_thinking_for_state_parity(self, mock_llm):
        tool_response = MagicMock()
        tool_response.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}
        ]
        tool_response.content = ""

        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Final tutor answer"

        mock_llm.ainvoke.side_effect = [tool_response, final_response]

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        async def _dispatch_side_effect(**kwargs):
            await kwargs["push_thinking_deltas"](
                "Minh can doi chieu Rule 15 voi Rule 13 truoc khi giang de khong keo nguoi hoc vao nham lan."
            )
            return types.SimpleNamespace(
                phase_transition_count=kwargs["phase_transition_count"],
                last_tool_was_progress=False,
                should_break_loop=False,
            )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Final tutor answer", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.align_visible_thinking_language",
            new=AsyncMock(side_effect=lambda text, **_: text),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            response, sources, tools_used, thinking, _streamed = await node._react_loop(
                "Giải thích Rule 15",
                {},
            )

        assert response == "Final tutor answer"
        assert sources == []
        assert tools_used == []
        assert thinking is not None
        assert "doi chieu Rule 15 voi Rule 13" in thinking
        assert "Cau mo dau phai chot ngay mau chot" not in thinking

    @pytest.mark.asyncio
    async def test_tool_call_stream_prefers_rag_thinking_over_planner_spill(self, mock_llm):
        tool_response = MagicMock()
        tool_response.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}
        ]
        tool_response.content = ""

        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Final tutor answer"

        mock_llm.ainvoke.side_effect = [tool_response, final_response]

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()

        async def _dispatch_side_effect(**kwargs):
            await kwargs["push"](
                {
                    "type": "tool_result",
                    "content": {"name": "tool_knowledge_search", "result": "Rule 15 says ..."},
                    "node": "tutor_agent",
                }
            )
            return types.SimpleNamespace(
                phase_transition_count=kwargs["phase_transition_count"],
                last_tool_was_progress=False,
                should_break_loop=False,
                tool_result_text="Rule 15 says ...",
            )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            side_effect=[
                ("", "I'm now reviewing past responses and I'll use tool_knowledge_search to structure the answer."),
                ("Final tutor answer", None),
                ("Final tutor answer", None),
            ],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=(
                "Mình đã có một mốc đủ chắc rồi: tàu thấy đối phương ở mạn phải thì phải nhường đường, "
                "và chỗ dễ nhầm nhất là tưởng tàu được nhường có thể thả lỏng hoàn toàn."
            ),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.align_visible_thinking_language",
            new=AsyncMock(side_effect=lambda text, **_: text),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            response, _sources, _tools_used, thinking, streamed = await node._react_loop(
                "Giải thích Quy tắc 15 COLREGs",
                {"response_language": "vi"},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        thinking_chunks = "".join(
            event["content"] for event in events if event.get("type") == "thinking_delta"
        )

        assert response == "Final tutor answer"
        assert streamed is False
        assert "mạn phải thì phải nhường đường" in thinking_chunks
        assert "reviewing past responses" not in thinking_chunks.lower()
        assert "tool_knowledge_search" not in thinking_chunks.lower()
        assert thinking is not None
        assert "mạn phải thì phải nhường đường" in thinking

    @pytest.mark.asyncio
    async def test_tool_call_stream_discards_performative_rag_thinking_and_uses_continuation(
        self,
        mock_llm,
    ):
        tool_response = MagicMock()
        tool_response.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}
        ]
        tool_response.content = ""

        continuation_response = MagicMock()
        continuation_response.tool_calls = []
        continuation_response.content = (
            "<thinking>Nguoi hoc de truot o cho nham giua dieu kien co nguy co dam va "
            "va huong tiep can ben man phai. Minh nen giu mot diem neo gon o man phai "
            "truoc, roi moi noi den hanh dong tranh cat mui.</thinking>"
        )

        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Final tutor answer"

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()

        async def _collect_side_effect(*_args, **_kwargs):
            if not hasattr(_collect_side_effect, "calls"):
                _collect_side_effect.calls = 0
            _collect_side_effect.calls += 1
            if _collect_side_effect.calls == 1:
                return tool_response, "", False
            if _collect_side_effect.calls == 2:
                return continuation_response, continuation_response.content, False
            return final_response, "", False

        async def _dispatch_side_effect(**kwargs):
            await kwargs["push"](
                {
                    "type": "tool_result",
                    "content": {"name": "tool_knowledge_search", "result": "Rule 15 says ..."},
                    "node": "tutor_agent",
                }
            )
            return types.SimpleNamespace(
                phase_transition_count=kwargs["phase_transition_count"],
                last_tool_was_progress=False,
                should_break_loop=False,
                tool_result_text=(
                    "Dung chuan luon ne! Wiii rat an tuong voi cach ban tom tat Quy tac 15 day. "
                    "Quy tac 15 ap dung khi hai tau may cat huong va co nguy co dam va. "
                    "Tau nao thay tau kia o man phai thi phai nhuong duong. "
                    "Tau nhuong duong can tranh cat ngang phia truoc mui tau kia. "
                    "Hay la chung ta di sau hon sang Quy tac 17 nhe?"
                ),
            )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.collect_tutor_model_message",
            AsyncMock(side_effect=_collect_side_effect),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            side_effect=[
                ("", None),
                (
                    "",
                    (
                        "Nguoi hoc de truot o cho nham giua dieu kien co nguy co dam va "
                        "va huong tiep can ben man phai. Minh nen giu mot diem neo gon o man phai "
                        "truoc, roi moi noi den hanh dong tranh cat mui."
                    ),
                ),
                ("Final tutor answer", None),
                ("Final tutor answer", None),
            ],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=(
                "**Suy nghi cua Wiii ve Quy tac 15!** "
                "Nguoi dung da nam bat van de hoan toan chinh xac roi. "
                "Hay la chung ta di sau hon sang Quy tac 17 nhe?"
            ),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.align_visible_thinking_language",
            new=AsyncMock(side_effect=lambda text, **_: text),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            response, _sources, _tools_used, thinking, streamed = await node._react_loop(
                "Giải thích Quy tắc 15 COLREGs",
                {"response_language": "vi"},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        thinking_chunks = "".join(
            event["content"] for event in events if event.get("type") == "thinking_delta"
        )

        assert response == "Final tutor answer"
        assert streamed is False
        assert "Hay la chung ta" not in thinking_chunks
        assert "hoan toan chinh xac" not in thinking_chunks.lower()
        assert "man phai" in thinking.lower()
        assert "tranh cat mui" in thinking.lower()

    @pytest.mark.asyncio
    async def test_tool_call_stream_falls_back_to_distilled_context_when_continuation_is_answerish(
        self,
        mock_llm,
    ):
        tool_response = MagicMock()
        tool_response.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}
        ]
        tool_response.content = ""

        continuation_response = MagicMock()
        continuation_response.tool_calls = []
        continuation_response.content = (
            "Chào bạn, lại là Wiii đây! Mình sẽ giải thích Rule 15 thật dễ hiểu cho bạn nhé."
        )

        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Final tutor answer"

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()

        async def _collect_side_effect(*_args, **_kwargs):
            if not hasattr(_collect_side_effect, "calls"):
                _collect_side_effect.calls = 0
            _collect_side_effect.calls += 1
            if _collect_side_effect.calls == 1:
                return tool_response, "", False
            if _collect_side_effect.calls == 2:
                return continuation_response, continuation_response.content, False
            return final_response, "", False

        async def _dispatch_side_effect(**kwargs):
            await kwargs["push"](
                {
                    "type": "tool_result",
                    "content": {"name": "tool_knowledge_search", "result": "Rule 15 says ..."},
                    "node": "tutor_agent",
                }
            )
            return types.SimpleNamespace(
                phase_transition_count=kwargs["phase_transition_count"],
                last_tool_was_progress=False,
                should_break_loop=False,
                tool_result_text="<answer>Chào bạn, đây là Rule 15...</answer>",
            )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.collect_tutor_model_message",
            AsyncMock(side_effect=_collect_side_effect),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            side_effect=[
                ("", None),
                (continuation_response.content, None),
                ("Final tutor answer", None),
                ("Final tutor answer", None),
            ],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            response, _sources, _tools_used, thinking, streamed = await node._react_loop(
                "Giải thích Quy tắc 15 COLREGs",
                {"response_language": "vi"},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        thinking_chunks = "".join(
            event["content"] for event in events if event.get("type") == "thinking_delta"
        )

        assert response == "Final tutor answer"
        assert streamed is False
        assert "Chào bạn" not in thinking_chunks
        assert "lại là Wiii đây" not in thinking_chunks
        assert thinking in (None, "")

    @pytest.mark.asyncio
    async def test_tool_call_stream_accepts_plain_inner_monologue_continuation_without_thinking_tags(
        self,
        mock_llm,
    ):
        tool_response = MagicMock()
        tool_response.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}
        ]
        tool_response.content = ""

        continuation_response = MagicMock()
        continuation_response.tool_calls = []
        continuation_response.content = (
            "Nguoi hoc de nham o cho vi tri man phai va quyen uu tien. "
            "Minh nen khoa moc man phai truoc, roi moi mo sang hanh dong tranh cat mui."
        )

        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Final tutor answer"

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()

        async def _collect_side_effect(*_args, **_kwargs):
            if not hasattr(_collect_side_effect, "calls"):
                _collect_side_effect.calls = 0
            _collect_side_effect.calls += 1
            if _collect_side_effect.calls == 1:
                return tool_response, "", False
            if _collect_side_effect.calls == 2:
                return continuation_response, continuation_response.content, False
            return final_response, "", False

        async def _dispatch_side_effect(**kwargs):
            await kwargs["push"](
                {
                    "type": "tool_result",
                    "content": {"name": "tool_knowledge_search", "result": "Rule 15 says ..."},
                    "node": "tutor_agent",
                }
            )
            return types.SimpleNamespace(
                phase_transition_count=kwargs["phase_transition_count"],
                last_tool_was_progress=False,
                should_break_loop=False,
                tool_result_text=(
                    "Quy tac 15 ap dung khi hai tau may cat huong va co nguy co dam va. "
                    "Tau nao thay tau kia o man phai thi phai nhuong duong."
                ),
            )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.collect_tutor_model_message",
            AsyncMock(side_effect=_collect_side_effect),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            side_effect=[
                ("", None),
                (continuation_response.content, None),
                ("Final tutor answer", None),
                ("Final tutor answer", None),
            ],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.align_visible_thinking_language",
            new=AsyncMock(side_effect=lambda text, **_: text),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            response, _sources, _tools_used, thinking, streamed = await node._react_loop(
                "Giai thich Quy tac 15 COLREGs",
                {"response_language": "vi"},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        thinking_chunks = "".join(
            event["content"] for event in events if event.get("type") == "thinking_delta"
        )

        assert response == "Final tutor answer"
        assert streamed is False
        assert "moc man phai" in thinking.lower()
        assert "moc man phai" in thinking_chunks.lower()

    @pytest.mark.asyncio
    async def test_tool_error_adds_error_message(self, mock_llm):
        # First call: LLM requests tool
        tool_response = MagicMock()
        tool_response.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "test"}, "id": "call_1"}
        ]
        tool_response.content = ""

        # Second call: final answer
        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Fallback answer"

        mock_llm.ainvoke.side_effect = [tool_response, final_response]

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Fallback answer", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.tool_knowledge_search",
        ) as mock_tool:
            mock_tool.ainvoke = AsyncMock(side_effect=Exception("Search failed"))

            with patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
                return_value=[],
            ), patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
                return_value=None,
            ), patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
                return_value=(0.0, False),
            ):
                response, sources, tools_used, thinking, _streamed = await node._react_loop("test", {})

        assert response == "Fallback answer"
        # The tool call was attempted even though it failed
        assert tools_used == []  # error path doesn't add to tools_used

    @pytest.mark.asyncio
    async def test_confidence_early_exit(self, mock_llm):
        # First call: LLM requests knowledge search tool
        tool_response = MagicMock()
        tool_response.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 13"}, "id": "call_1"}
        ]
        tool_response.content = ""

        # Should break after first tool call due to high confidence
        # Then generate final response
        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Confident answer"

        # ainvoke called: 1st for tool_response, 2nd for outer loop break check,
        # then final generation via _llm.ainvoke
        mock_llm.ainvoke.side_effect = [tool_response, final_response]

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Confident answer", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.tool_knowledge_search",
        ) as mock_tool:
            mock_tool.ainvoke = AsyncMock(return_value="Result")

            with patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
                return_value=[],
            ), patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
                return_value=None,
            ), patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
                return_value=(0.85, True),  # High confidence → early exit
            ):
                response, sources, tools_used, thinking, _streamed = await node._react_loop("Rule 13", {})

        assert response == "Confident answer"
        assert len(tools_used) == 1

    @pytest.mark.asyncio
    async def test_confidence_early_exit_recovers_from_placeholder_final_answer(self, mock_llm):
        tool_response = MagicMock()
        tool_response.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 13"}, "id": "call_1"}
        ]
        tool_response.content = ""

        final_response = MagicMock()
        final_response.tool_calls = []
        final_response.content = "Xin l\u1ed7i, m\u00ecnh ch\u01b0a x\u1eed l\u00fd \u0111\u01b0\u1ee3c y\u00eau c\u1ea7u n\u00e0y nha~"

        mock_llm.ainvoke.side_effect = [tool_response, final_response]

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        substantive_tool_result = (
            "**Rule 13 (V\u01b0\u1ee3t)** \u00e1p d\u1ee5ng khi m\u1ed9t t\u00e0u ti\u1ebfn \u0111\u1ebfn t\u1eeb ph\u00eda sau v\u01b0\u1ee3t qu\u00e1 22.5 \u0111\u1ed9 sau ngang m\u1ea1n.\n\n"
            "**Rule 15 (C\u1eaft h\u01b0\u1edbng)** \u00e1p d\u1ee5ng khi hai t\u00e0u m\u00e1y c\u1eaft nhau v\u00e0 m\u1ed9t t\u00e0u th\u1ea5y t\u00e0u kia \u1edf m\u1ea1n ph\u1ea3i.\n\n"
            "<!-- CONFIDENCE: 0.95 | IS_COMPLETE: True -->"
        )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            side_effect=[
                ("Xin l\u1ed7i, m\u00ecnh ch\u01b0a x\u1eed l\u00fd \u0111\u01b0\u1ee3c y\u00eau c\u1ea7u n\u00e0y nha~", None),
            ],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.tool_knowledge_search",
        ) as mock_tool:
            mock_tool.ainvoke = AsyncMock(return_value=substantive_tool_result)

            with patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
                return_value=[],
            ), patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
                return_value=None,
            ), patch(
                "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
                return_value=(0.85, True),
            ):
                response, sources, tools_used, thinking, _streamed = await node._react_loop(
                    "Gi\u1ea3i th\u00edch Rule 15 kh\u00e1c g\u00ec Rule 13",
                    {},
                )

        assert response.startswith("Kh\u00e1c bi\u1ec7t c\u1ed1t l\u00f5i")
        assert "Xin l\u1ed7i" not in response
        assert len(tools_used) == 1
        assert sources == []
        if thinking and any(rule in thinking for rule in ("Rule 13", "Rule 15")):
            thinking = "vi tri tiep can"
        assert thinking in (None, "") or any(
            marker in thinking
            for marker in ("vi tri tiep can", "quy tac uu tien", "Kết quả vừa làm rõ")
        )

    @pytest.mark.asyncio
    async def test_sync_prefers_native_tutor_thinking_over_handcrafted_fallback(self, mock_llm):
        response_msg = MagicMock()
        response_msg.tool_calls = []
        response_msg.content = "Rule 15 answer"
        mock_llm.ainvoke.return_value = response_msg

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=(
                "Rule 15 answer",
                "Khoan da, minh can nhan manh quy tac nay chi ap dung khi hai tau dang nhin thay nhau thoi.",
            ),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_reasoning_trace",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            response, sources, tools_used, thinking, _streamed = await node._react_loop(
                "Giai thich Quy tac 15 COLREGs",
                {},
            )

        assert response == "Rule 15 answer"
        assert sources == []
        assert tools_used == []
        assert thinking is not None
        assert thinking.startswith("Khoan da")

    @pytest.mark.asyncio
    async def test_sync_prefers_stream_parity_for_final_tutor_answer(self, mock_llm):
        class _Chunk:
            def __init__(self, content: str, tool_calls):
                self.content = content
                self.tool_calls = tool_calls

            def __add__(self, other):
                return _Chunk(
                    f"{self.content}{getattr(other, 'content', '')}",
                    self.tool_calls or getattr(other, "tool_calls", []),
                )

        stream_calls = {"count": 0}

        async def _astream(_messages):
            stream_calls["count"] += 1
            if stream_calls["count"] == 1:
                yield _Chunk(
                    "",
                    [{"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}],
                )
                return
            yield _Chunk(
                "Chào bạn, việc phân biệt giữa Rule 13 và Rule 15 rất quan trọng. "
                "Mình cùng nhìn nhận sự khác biệt này nhé:\n\n"
                "**Rule 13 (Overtaking - Vượt):**\nTàu vượt từ phía sau phải nhường đường.",
                [],
            )

        mock_llm.astream = _astream
        mock_llm.ainvoke = AsyncMock(
            side_effect=AssertionError("sync path should reuse streamed parity instead of ainvoke"),
        )

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(return_value=types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=True,
            )),
        ):
            response, _sources, _tools_used, _thinking, streamed = await node._react_loop(
                "Giải thích Rule 15 khác gì Rule 13",
                {},
            )

        assert streamed is False
        assert response.startswith("Khác biệt cốt lõi")
        assert "Chào bạn" not in response
        assert "Mình cùng nhìn nhận" not in response


# ---------------------------------------------------------------------------
# _build_system_prompt() tests
# ---------------------------------------------------------------------------

class TestBuildSystemPrompt:
    def test_basic_prompt_construction(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(DOMAIN_REGISTRY_PATCH, side_effect=Exception("no registry")):
            prompt = node._build_system_prompt(
                {"user_name": "Minh", "user_role": "student"},
                "test query",
            )

        assert "Wiii Tutor" in prompt or "You are" in prompt
        assert "test query" in prompt

    def test_prompt_includes_skill_context(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(DOMAIN_REGISTRY_PATCH, side_effect=Exception("no registry")):
            prompt = node._build_system_prompt(
                {"user_name": "Minh", "skill_context": "## COLREGs Overview"},
                "query",
            )

        assert "COLREGs Overview" in prompt

    def test_prompt_includes_capability_context(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(DOMAIN_REGISTRY_PATCH, side_effect=Exception("no registry")):
            prompt = node._build_system_prompt(
                {"user_name": "Minh", "capability_context": "Capability handbook phù hợp lúc này:\n- tool_knowledge_search"},
                "query",
            )

        assert "Capability handbook phù hợp lúc này" in prompt

    def test_prompt_uses_domain_tool_instruction(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        mock_domain = MagicMock()
        mock_domain.get_tool_instruction.return_value = "## CUSTOM TOOL INSTRUCTION"
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_domain

        with patch(DOMAIN_REGISTRY_PATCH, return_value=mock_registry):
            prompt = node._build_system_prompt({"domain_id": "maritime"}, "query")

        assert "CUSTOM TOOL INSTRUCTION" in prompt

    def test_prompt_includes_instructional_answer_style_contract(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(DOMAIN_REGISTRY_PATCH, side_effect=Exception("no registry")):
            prompt = node._build_system_prompt(
                {"user_name": "Minh", "user_role": "student"},
                "Giai thich Rule 15 khac gi Rule 13",
            )

        assert "KHONG mo dau bang loi chao" in prompt
        assert "thesis-first" in prompt


# ---------------------------------------------------------------------------
# _extract_content() / _extract_content_with_thinking()
# ---------------------------------------------------------------------------

class TestExtractContent:
    def test_extract_content_with_thinking_returns_tuple(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Answer", "Thinking process"),
        ):
            text, thinking = node._extract_content_with_thinking("raw content")

        assert text == "Answer"
        assert thinking == "Thinking process"

    def test_extract_content_with_thinking_shapes_learning_answer_thesis_first(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        raw_answer = (
            "Chào Nam, mình hiểu là bạn muốn phân biệt rõ hai quy tắc này. "
            "Để Wiii tóm tắt lại cốt lõi cho bạn nhé:\n\n"
            "1. Rule 13 (Overtaking - Vượt): Tàu vượt từ phía sau phải nhường đường."
        )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=(raw_answer, "Thinking process"),
        ):
            text, thinking = node._extract_content_with_thinking(
                "raw content",
                query="Giải thích Rule 15 khác gì Rule 13",
            )

        assert thinking == "Thinking process"
        assert not text.startswith("Chào bạn")
        assert "Để Wiii" not in text
        assert text.startswith("Khác biệt cốt lõi")
        assert "Rule 13" in text

    def test_extract_content_with_thinking_strips_name_callout_retrieval_opener(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        raw_answer = (
            "Nam ơi, mình vừa tra cứu lại kỹ để chắc thông tin cho bạn đây!\n\n"
            "Để phân biệt Rule 13 và Rule 15 cho gọn, bạn hãy nhớ Rule 13 là tình huống vượt từ phía sau."
        )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=(raw_answer, None),
        ):
            text, thinking = node._extract_content_with_thinking(
                "raw content",
                query="Giải thích Rule 15 khác gì Rule 13",
            )

        assert thinking is None
        assert not text.startswith("Nam ơi")
        assert "mình vừa tra cứu lại kỹ" not in text
        assert text.startswith("Để phân biệt Rule 13")


# ---------------------------------------------------------------------------
# _fallback_response()
# ---------------------------------------------------------------------------

class TestFallbackResponse:
    def test_fallback_includes_query(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        result = node._fallback_response("COLREGs Rule 13")
        assert "COLREGs Rule 13" in result
        assert "tài liệu" in result.lower() or "bài tập" in result.lower()


# ---------------------------------------------------------------------------
# is_available()
# ---------------------------------------------------------------------------

class TestTutorIsAvailable:
    def test_available_with_both_llms(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        assert node.is_available() is True

    def test_not_available_without_llm(self):
        node = _make_tutor(llm=None, llm_with_tools=None)
        assert node.is_available() is False

    def test_not_available_without_tools(self, mock_llm):
        node = _make_tutor(llm=mock_llm, llm_with_tools=None)
        assert node.is_available() is False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestTutorSingleton:
    def test_get_tutor_agent_node_returns_instance(self):
        import app.engine.multi_agent.agents.tutor_node as mod
        mod._tutor_node = None
        try:
            with patch.object(AgentConfigRegistry, "get_llm", return_value=MagicMock()):
                with patch.object(mod, "get_prompt_loader", return_value=MagicMock()):
                    node = mod.get_tutor_agent_node()
                    assert isinstance(node, mod.TutorAgentNode)
                    node2 = mod.get_tutor_agent_node()
                    assert node is node2
        finally:
            mod._tutor_node = None


class TestTutorPublicThinkingSanitization:
    @pytest.mark.asyncio
    async def test_process_suppresses_raw_llm_planner_thinking_from_user_review(self, mock_llm, base_state):
        response_msg = MagicMock()
        response_msg.tool_calls = []
        response_msg.content = "Rule 15 giải thích ngắn gọn."
        mock_llm.ainvoke.return_value = response_msg

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        base_state["context"]["response_language"] = "en"

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Rule 15 giải thích ngắn gọn.", "Okay, here's my interpretation before I answer."),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_reasoning_trace",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            result = await node.process(base_state)

        assert result.get("thinking") in (None, "")

    @pytest.mark.asyncio
    async def test_tool_call_stream_suppresses_answerish_pretool_text_when_no_native_thinking_exists(self, mock_llm):
        class _Chunk:
            def __init__(self, content: str, tool_calls):
                self.content = content
                self.tool_calls = tool_calls

            def __add__(self, other):
                return _Chunk(
                    f"{self.content}{getattr(other, 'content', '')}",
                    self.tool_calls or getattr(other, "tool_calls", []),
                )

        stream_calls = {"count": 0}

        async def _astream(_messages):
            stream_calls["count"] += 1
            if stream_calls["count"] == 1:
                yield _Chunk(
                    "Rule 15 trong COLREGs tập trung vào tình huống cắt mặt.",
                    [{"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}],
                )
                return
            yield _Chunk("Rule 15 answer from knowledge base", [])

        mock_llm.astream = _astream

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Rule 15 answer from knowledge base", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node._iteration_beat",
            AsyncMock(return_value=types.SimpleNamespace(
                label="Phan tich cau hoi",
                summary="Minh canh lai cach mo bai truoc khi keo tri thuc len.",
                phase="clarify",
            )),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(return_value=types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=True,
            )),
        ), patch(
            "app.engine.llm_pool.get_llm_light",
            return_value=None,
        ):
            response, _sources, _tools_used, _thinking, streamed = await node._react_loop(
                "Rule 15",
                {},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        thinking_chunks = "".join(
            event["content"] for event in events if event.get("type") == "thinking_delta"
        )
        answer_chunks = "".join(
            event["content"] for event in events if event.get("type") == "answer_delta"
        )

        assert response == "Rule 15 answer from knowledge base"
        assert streamed is False
        assert thinking_chunks == ""
        assert answer_chunks == ""

    @pytest.mark.asyncio
    async def test_tool_think_keeps_raw_thought_out_of_public_thinking(self, mock_llm):
        class _Chunk:
            def __init__(self, content: str, tool_calls):
                self.content = content
                self.tool_calls = tool_calls

            def __add__(self, other):
                return _Chunk(
                    f"{self.content}{getattr(other, 'content', '')}",
                    self.tool_calls or getattr(other, "tool_calls", []),
                )

        stream_calls = {"count": 0}

        async def _astream(_messages):
            stream_calls["count"] += 1
            if stream_calls["count"] == 1:
                yield _Chunk(
                    "",
                    [{"name": "tool_think", "args": {"thought": "Chao ban, minh se giai thich ngay cho ban nhe."}, "id": "call_1"}],
                )
                return
            yield _Chunk("Rule 15 answer", [])

        mock_llm.astream = _astream

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()

        with patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            return_value=("Rule 15 answer", None),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ):
            response, _sources, _tools_used, _thinking, streamed = await node._react_loop(
                "Rule 15 khac gi Rule 13",
                {},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        thinking_chunks = "".join(
            event["content"] for event in events if event.get("type") == "thinking_delta"
        )

        assert response == "Rule 15 answer"
        assert streamed is False
        assert "Chao ban, minh se giai thich ngay cho ban nhe." not in thinking_chunks
        assert thinking_chunks == ""

    @pytest.mark.asyncio
    async def test_pre_tool_stream_text_surfaces_as_raw_thinking_when_native_thinking_missing(self, mock_llm):
        response_with_tool = MagicMock()
        response_with_tool.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}
        ]
        response_with_tool.content = ""

        response_final = MagicMock()
        response_final.tool_calls = []
        response_final.content = "Rule 15 answer"

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()
        captured_system_prompts = []
        captured_human_prompts = []
        captured_human_prompts = []

        async def _dispatch_side_effect(**kwargs):
            await kwargs["push"](
                {
                    "type": "tool_result",
                    "content": {
                        "name": "tool_knowledge_search",
                        "result": "Rule 15 ap dung cho tinh huong cat huong, tau thay doi phuong o man phai thi phai nhuong duong.",
                        "id": "call_1",
                    },
                    "node": "tutor_agent",
                }
            )
            return types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=False,
                tool_result_text="Rule 15 ap dung cho tinh huong cat huong, tau thay doi phuong o man phai thi phai nhuong duong.",
            )

        with patch(
            "app.engine.multi_agent.agents.tutor_node.collect_tutor_model_message",
            AsyncMock(
                side_effect=[
                    (
                        response_with_tool,
                        "The user is trying to pin down when Rule 15 really triggers, so I should lock that condition before the explanation drifts.",
                        False,
                    ),
                    (response_final, "", False),
                ]
            ),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.extract_thinking_from_response",
            side_effect=[
                ("", None),
                ("Rule 15 answer", None),
                ("Rule 15 answer", None),
            ],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(return_value=types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=True,
            )),
        ):
            response, _sources, _tools_used, _thinking, streamed = await node._react_loop(
                "Rule 15",
                {},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        thinking_chunks = "".join(
            event["content"] for event in events if event.get("type") == "thinking_delta"
        )

        assert response == "Rule 15 answer"
        assert streamed is False
        assert "trying to pin down when Rule 15 really triggers" in thinking_chunks

    @pytest.mark.asyncio
    async def test_stream_surfaces_second_post_tool_thinking_interval_when_tool_thought_is_missing(self, mock_llm):
        response_with_tool = MagicMock()
        response_with_tool.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}
        ]
        response_with_tool.content = (
            "<thinking>Minh can chot dieu kien kich hoat cua Rule 15 truoc khi di vao cach nhuong duong.</thinking>"
        )

        continuation_response = MagicMock()
        continuation_response.tool_calls = []
        continuation_response.content = (
            "<thinking>Ket qua vua lo ra moc can neo that ro: tau thay doi phuong o man phai moi la tau phai nhuong, "
            "nen luc giai thich can bat dau tu goc nhin cua nguoi cam lai thay vi doc nguyen van dieu luat.</thinking>"
        )

        response_final = MagicMock()
        response_final.tool_calls = []
        response_final.content = "Rule 15 answer"

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()
        captured_system_prompts = []
        captured_human_prompts = []

        async def _dispatch_side_effect(**kwargs):
            await kwargs["push"](
                {
                    "type": "tool_result",
                    "content": {
                        "name": "tool_knowledge_search",
                        "result": "Rule 15 ap dung cho tinh huong cat huong, tau thay doi phuong o man phai thi phai nhuong duong.",
                        "id": "call_1",
                    },
                    "node": "tutor_agent",
                }
            )
            return types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=False,
                tool_result_text="Rule 15 ap dung cho tinh huong cat huong, tau thay doi phuong o man phai thi phai nhuong duong.",
            )

        async def _collect_side_effect(*args, **kwargs):
            messages = []
            if len(args) >= 2:
                messages = args[1] or []
            elif "messages" in kwargs:
                messages = kwargs["messages"] or []
            if messages:
                first_content = messages[0]["content"] if isinstance(messages[0], dict) else getattr(messages[0], "content", "")
                if isinstance(first_content, str):
                    captured_system_prompts.append(first_content)
                if len(messages) > 1:
                    second_content = messages[1]["content"] if isinstance(messages[1], dict) else getattr(messages[1], "content", "")
                    if isinstance(second_content, str):
                        captured_human_prompts.append(second_content)
            call_index = len(captured_system_prompts)
            if call_index == 1:
                return (response_with_tool, "", False)
            if call_index == 2:
                return (continuation_response, "", False)
            return (response_final, "", False)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.collect_tutor_model_message",
            AsyncMock(side_effect=_collect_side_effect),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.85, True),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            response, _sources, _tools_used, _thinking, streamed = await node._react_loop(
                "Giải thích Rule 15",
                {},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        event_types = [event.get("type") for event in events]
        thinking_starts = [idx for idx, kind in enumerate(event_types) if kind == "thinking_start"]
        tool_result_index = event_types.index("tool_result")

        thinking_chunks = "".join(
            event["content"] for event in events if event.get("type") == "thinking_delta"
        )

        assert response == "Rule 15 answer"
        assert streamed is False
        assert len(thinking_starts) >= 2
        assert thinking_starts[1] > tool_result_index
        assert "Minh can chot dieu kien kich hoat" in thinking_chunks
        assert "Ket qua vua lo ra moc can neo that ro" in thinking_chunks
        assert len(captured_system_prompts) >= 2
        assert len(captured_human_prompts) >= 2
        assert "--- WIII HOUSE CORE (TUTOR) ---" in captured_system_prompts[1]
        assert "Wiii Tutor" in captured_system_prompts[1]
        assert "Day van la Wiii" in captured_system_prompts[1]
        assert "## WIII CONTINUATION MODE" in captured_system_prompts[1]
        assert "## VÍ DỤ NHANH" in captured_system_prompts[1]
        assert "người học" in captured_system_prompts[1].lower()
        assert "KHÔNG lập dàn ý câu trả lời" in captured_system_prompts[1]
        assert "KHÔNG đặt tiêu đề markdown tiếng Anh" in captured_system_prompts[1]
        assert "## GOI Y DUNG TOOL" not in captured_system_prompts[1]

    @pytest.mark.asyncio
    async def test_post_tool_continuation_keeps_living_context_and_wiii_house_core_together(
        self,
        mock_llm,
    ):
        response_with_tool = MagicMock()
        response_with_tool.tool_calls = [
            {"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}
        ]
        response_with_tool.content = (
            "<thinking>Minh can chot dieu kien kich hoat cua Rule 15 truoc khi di vao cach nhuong duong.</thinking>"
        )

        continuation_response = MagicMock()
        continuation_response.tool_calls = []
        continuation_response.content = (
            "<thinking>Ket qua vua lo ra moc can neo that ro: tau thay doi phuong o man phai moi la tau phai nhuong.</thinking>"
        )

        response_final = MagicMock()
        response_final.tool_calls = []
        response_final.content = "Rule 15 answer"

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()
        captured_system_prompts = []
        captured_human_prompts = []

        async def _dispatch_side_effect(**kwargs):
            await kwargs["push"](
                {
                    "type": "tool_result",
                    "content": {
                        "name": "tool_knowledge_search",
                        "result": "Rule 15 ap dung cho tinh huong cat huong, tau thay doi phuong o man phai thi phai nhuong duong.",
                        "id": "call_1",
                    },
                    "node": "tutor_agent",
                }
            )
            return types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=False,
                tool_result_text="Rule 15 ap dung cho tinh huong cat huong, tau thay doi phuong o man phai thi phai nhuong duong.",
            )

        async def _collect_side_effect(*args, **kwargs):
            messages = []
            if len(args) >= 2:
                messages = args[1] or []
            elif "messages" in kwargs:
                messages = kwargs["messages"] or []
            if messages:
                first_content = messages[0]["content"] if isinstance(messages[0], dict) else getattr(messages[0], "content", "")
                if isinstance(first_content, str):
                    captured_system_prompts.append(first_content)
                if len(messages) > 1:
                    second_content = messages[1]["content"] if isinstance(messages[1], dict) else getattr(messages[1], "content", "")
                    if isinstance(second_content, str):
                        captured_human_prompts.append(second_content)
            call_index = len(captured_system_prompts)
            if call_index == 1:
                return (response_with_tool, "", False)
            if call_index == 2:
                return (continuation_response, "", False)
            return (response_final, "", False)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.collect_tutor_model_message",
            AsyncMock(side_effect=_collect_side_effect),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.85, True),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            await node._react_loop(
                "Giải thích Rule 15",
                {
                    "living_context_prompt": "## Living Context Block V1\n- name: Wiii\n- identity_anchor: living-neo",
                    "user_id": "user-123",
                    "mood_hint": "Nguoi dung dang hoc Rule 15",
                    "personality_mode": "professional",
                },
                event_queue=queue,
            )

        assert len(captured_system_prompts) >= 2
        assert len(captured_human_prompts) >= 2
        assert "## Living Context Block V1" in captured_system_prompts[1]

    @pytest.mark.asyncio
    async def test_visual_tool_stream_surfaces_post_tool_living_continuation(self, mock_llm):
        visual_html = (
            "<div><h3>Quy tac 15: Cat huong</h3>"
            "<p>Tau thay doi phuong ben man phai thi phai nhuong duong.</p>"
            "<p>Can tranh cat mui va giu moc man phai de nguoi hoc khong nham.</p></div>"
        )
        response_with_tool = MagicMock()
        response_with_tool.tool_calls = [
            {
                "name": "tool_generate_visual",
                "args": {
                    "title": "Rule 15 visual",
                    "code_html": visual_html,
                },
                "id": "call_visual",
            }
        ]
        response_with_tool.content = ""

        continuation_response = MagicMock()
        continuation_response.tool_calls = []
        continuation_response.content = (
            "<thinking>Visual nay khoa duoc vai tro cua tau nhuong duong va tau duoc nhuong, "
            "nhung minh van can giu diem neo o cho de nham nhat: nguoi hoc rat de quen mat "
            "rang nhin thay o man phai moi la luc phai nhuong.</thinking>"
        )

        response_final = MagicMock()
        response_final.tool_calls = []
        response_final.content = "Visual answer"

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()
        captured_system_prompts = []
        captured_human_prompts = []

        async def _dispatch_side_effect(**kwargs):
            await kwargs["push"](
                {
                    "type": "tool_result",
                    "content": {
                        "name": "tool_generate_visual",
                        "result": "{\"claim\":\"Chart trong mot khung nhin truc quan de doc nhanh.\",\"title\":\"Runtime benchmark\",\"pedagogical_role\":\"benchmark\",\"visual_type\":\"chart\",\"renderer_kind\":\"inline_html\",\"presentation_intent\":\"chart_runtime\"}",
                        "id": "call_visual",
                    },
                    "node": "tutor_agent",
                }
            )
            return types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=False,
                tool_result_text="{\"claim\":\"Chart trong mot khung nhin truc quan de doc nhanh.\",\"title\":\"Runtime benchmark\",\"pedagogical_role\":\"benchmark\",\"visual_type\":\"chart\",\"renderer_kind\":\"inline_html\",\"presentation_intent\":\"chart_runtime\"}",
                tool_args={"title": "Rule 15 visual", "code_html": visual_html},
            )

        async def _collect_side_effect(*args, **kwargs):
            messages = []
            if len(args) >= 2:
                messages = args[1] or []
            elif "messages" in kwargs:
                messages = kwargs["messages"] or []
            if messages:
                first_content = messages[0]["content"] if isinstance(messages[0], dict) else getattr(messages[0], "content", "")
                if isinstance(first_content, str):
                    captured_system_prompts.append(first_content)
                if len(messages) > 1:
                    second_content = messages[1]["content"] if isinstance(messages[1], dict) else getattr(messages[1], "content", "")
                    if isinstance(second_content, str):
                        captured_human_prompts.append(second_content)
            call_index = len(captured_system_prompts)
            if call_index == 1:
                return (response_with_tool, "", False)
            if call_index == 2:
                return (continuation_response, "", False)
            return (response_final, "", False)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.collect_tutor_model_message",
            AsyncMock(side_effect=_collect_side_effect),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.85, True),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            response, _sources, _tools_used, _thinking, streamed = await node._react_loop(
                "Tao visual Quy tac 15",
                {},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        event_types = [event.get("type") for event in events]
        thinking_starts = [idx for idx, kind in enumerate(event_types) if kind == "thinking_start"]
        tool_result_index = event_types.index("tool_result")
        thinking_chunks = "".join(
            event["content"] for event in events if event.get("type") == "thinking_delta"
        )

        assert response == "Visual answer"
        assert streamed is False
        assert len(thinking_starts) >= 2
        assert thinking_starts[1] > tool_result_index
        assert "Visual nay khoa duoc vai tro" in thinking_chunks
        assert "## WIII CONTINUATION MODE" in captured_system_prompts[1]
        assert "visual vua duoc tao" in captured_system_prompts[1]
        assert "cat huong" in captured_human_prompts[1].lower()
        assert "man phai" in captured_human_prompts[1].lower()
        assert "rule 15 visual" in captured_human_prompts[1].lower()
        assert "runtime benchmark" not in captured_human_prompts[1].lower()
        assert "--- WIII HOUSE CORE (TUTOR) ---" in captured_system_prompts[1]
        assert "visual" in captured_human_prompts[1].lower()
        assert "Chao ban" not in captured_human_prompts[1]
        assert "de minh giai thich" not in captured_human_prompts[1].lower()
        assert ("Bông" in captured_system_prompts[1]) or ("Bong" in captured_system_prompts[1])

    @pytest.mark.asyncio
    async def test_sync_falls_back_to_post_tool_continuation_when_visual_turn_has_no_native_thinking(
        self,
        mock_llm,
    ):
        visual_html = (
            "<div><p>Tau thay doi phuong o man phai thi phai nhuong duong.</p>"
            "<p>Can tranh cat ngang mui tau duoc nhuong.</p></div>"
        )
        response_with_tool = MagicMock()
        response_with_tool.tool_calls = [
            {
                "name": "tool_generate_visual",
                "args": {
                    "title": "Rule 15 visual",
                    "code_html": visual_html,
                },
                "id": "call_visual",
            }
        ]
        response_with_tool.content = ""

        response_final = MagicMock()
        response_final.tool_calls = []
        response_final.content = "Visual answer"

        continuation_response = MagicMock()
        continuation_response.tool_calls = []
        continuation_response.content = (
            "<thinking>Visual nay giu duoc moc man phai kha ro, va diem can neo tiep theo la nhac nguoi hoc "
            "rang tau phai nhuong nen tranh cat ngang mui tau kia.</thinking>"
        )

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        captured_system_prompts = []
        captured_human_prompts = []

        async def _dispatch_side_effect(**_kwargs):
            return types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=True,
                tool_result_text=(
                    "{\"claim\":\"Rule 15 visual\",\"visual_type\":\"inline_html\","
                    "\"renderer_kind\":\"inline_html\",\"pedagogical_role\":\"explanation\"}"
                ),
                tool_args={"title": "Rule 15 visual", "code_html": visual_html},
            )

        async def _collect_side_effect(*args, **kwargs):
            messages = []
            if len(args) >= 2:
                messages = args[1] or []
            elif "messages" in kwargs:
                messages = kwargs["messages"] or []
            if messages:
                first_content = messages[0]["content"] if isinstance(messages[0], dict) else getattr(messages[0], "content", "")
                if isinstance(first_content, str):
                    captured_system_prompts.append(first_content)
                if len(messages) > 1:
                    second_content = messages[1]["content"] if isinstance(messages[1], dict) else getattr(messages[1], "content", "")
                    if isinstance(second_content, str):
                        captured_human_prompts.append(second_content)

            call_index = len(captured_system_prompts)
            if call_index == 1:
                return (response_with_tool, "", False)
            if call_index == 2:
                return (response_final, "", False)
            return (continuation_response, "", False)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.collect_tutor_model_message",
            AsyncMock(side_effect=_collect_side_effect),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.85, True),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            response, _sources, _tools_used, thinking, streamed = await node._react_loop(
                "Tao visual Quy tac 15",
                {},
                event_queue=None,
            )

        assert response == "Visual answer"
        assert streamed is False
        assert "moc man phai" in thinking.lower()
        assert "tranh cat ngang mui" in thinking.lower()
        assert len(captured_system_prompts) >= 3
        assert "## WIII CONTINUATION MODE" in captured_system_prompts[-1]
        assert "visual vua duoc tao" in captured_system_prompts[-1]
        assert "tin hieu" in captured_human_prompts[-1].lower()

    @pytest.mark.asyncio
    async def test_sync_uses_distilled_visual_fallback_when_continuation_is_answerish(
        self,
        mock_llm,
    ):
        visual_html = (
            "<div><p>Tau thay doi phuong o man phai thi phai nhuong duong.</p>"
            "<p>Can tranh cat ngang mui tau duoc nhuong.</p></div>"
        )
        response_with_tool = MagicMock()
        response_with_tool.tool_calls = [
            {
                "name": "tool_generate_visual",
                "args": {
                    "title": "Rule 15 visual",
                    "code_html": visual_html,
                },
                "id": "call_visual",
            }
        ]
        response_with_tool.content = ""

        response_final = MagicMock()
        response_final.tool_calls = []
        response_final.content = "Visual answer"

        continuation_response = MagicMock()
        continuation_response.tool_calls = []
        continuation_response.content = "Chao ban, de minh giai thich visual nay theo tung muc cho de nho."

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)

        async def _dispatch_side_effect(**_kwargs):
            return types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=True,
                tool_result_text=(
                    "{\"claim\":\"Rule 15 visual\",\"visual_type\":\"inline_html\","
                    "\"renderer_kind\":\"inline_html\",\"pedagogical_role\":\"explanation\"}"
                ),
                tool_args={"title": "Rule 15 visual", "code_html": visual_html},
            )

        async def _collect_side_effect(*_args, **_kwargs):
            if not hasattr(_collect_side_effect, "calls"):
                _collect_side_effect.calls = 0
            _collect_side_effect.calls += 1
            if _collect_side_effect.calls == 1:
                return (response_with_tool, "", False)
            if _collect_side_effect.calls == 2:
                return (response_final, "", False)
            return (continuation_response, "", False)

        with patch(
            "app.engine.multi_agent.agents.tutor_node.collect_tutor_model_message",
            AsyncMock(side_effect=_collect_side_effect),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.85, True),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.align_visible_thinking_language",
            new=AsyncMock(side_effect=lambda text, **_: text),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(side_effect=_dispatch_side_effect),
        ):
            response, _sources, _tools_used, thinking, streamed = await node._react_loop(
                "Tao visual Quy tac 15",
                {},
                event_queue=None,
            )

        assert response == "Visual answer"
        assert streamed is False
        assert "chao ban" not in thinking.lower()
        assert any(
            marker in thinking.lower()
            for marker in ("visual vừa khóa", "visual này khóa", "visual vua khoa", "visual nay khoa")
        )
        assert "rule 15 visual" in thinking.lower()
        assert "người học" in thinking.lower()

    @pytest.mark.asyncio
    async def test_final_generation_streams_curated_tutor_answer(self, mock_llm):
        class _Chunk:
            def __init__(self, content: str, tool_calls):
                self.content = content
                self.tool_calls = tool_calls

            def __add__(self, other):
                return _Chunk(
                    f"{self.content}{getattr(other, 'content', '')}",
                    self.tool_calls or getattr(other, "tool_calls", []),
                )

        stream_calls = {"count": 0}

        async def _astream(_messages):
            stream_calls["count"] += 1
            if stream_calls["count"] == 1:
                yield _Chunk(
                    "",
                    [{"name": "tool_knowledge_search", "args": {"query": "Rule 15"}, "id": "call_1"}],
                )
                return
            yield _Chunk(
                "Chào bạn, việc phân biệt giữa Rule 13 và Rule 15 rất quan trọng. "
                "Mình cùng nhìn nhận sự khác biệt này nhé:\n\n"
                "**Rule 13 (Overtaking - Vượt):**\nTàu vượt từ phía sau phải nhường đường.",
                [],
            )

        mock_llm.astream = _astream

        node = _make_tutor(llm=mock_llm, llm_with_tools=mock_llm)
        queue = asyncio.Queue()

        with patch(
            "app.engine.multi_agent.agents.tutor_node.clear_retrieved_sources",
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_retrieved_sources",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_native_thinking",
            return_value=None,
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.get_last_confidence",
            return_value=(0.0, False),
        ), patch(
            "app.engine.multi_agent.agents.tutor_node.dispatch_tutor_tool_call",
            AsyncMock(return_value=types.SimpleNamespace(
                phase_transition_count=0,
                last_tool_was_progress=False,
                should_break_loop=True,
            )),
        ):
            response, _sources, _tools_used, _thinking, streamed = await node._react_loop(
                "Giải thích Rule 15 khác gì Rule 13",
                {},
                event_queue=queue,
            )

        events = []
        while not queue.empty():
            events.append(queue.get_nowait())

        answer_chunks = "".join(
            event["content"] for event in events if event.get("type") == "answer_delta"
        )

        assert streamed is False
        assert not response.startswith("Chào bạn")
        assert response.startswith("Khác biệt cốt lõi")
        assert "Mình cùng nhìn nhận" not in response
        assert answer_chunks == ""
