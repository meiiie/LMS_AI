"""
Tests for SupervisorAgent - Query Router & Response Synthesizer.

Tests LLM routing, rule-based fallback, response synthesis,
skill activation, and state wiring.
"""

import asyncio
import sys
import types
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from app.engine.messages import Message
from app.core.exceptions import ProviderUnavailableError

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

def _make_supervisor(llm=None):
    """Create SupervisorAgent with optional mocked LLM."""
    with patch.object(
        AgentConfigRegistry, "get_llm", return_value=llm,
    ):
        from app.engine.multi_agent.supervisor import SupervisorAgent
        return SupervisorAgent()


def _mock_structured_route(
    agent_name: str,
    *,
    intent: str = "lookup",
    confidence: float = 0.95,
    reasoning: str = "structured route",
):
    """Patch StructuredInvokeService so supervisor tests follow the real contract."""
    from app.engine.structured_schemas import RoutingDecision

    return patch(
        "app.services.structured_invoke_service.StructuredInvokeService.ainvoke",
        new=AsyncMock(
            return_value=RoutingDecision(
                agent=agent_name,
                intent=intent,
                confidence=confidence,
                reasoning=reasoning,
            )
        ),
    )


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    return llm


@pytest.fixture(autouse=True)
def reset_supervisor_feature_flags(monkeypatch):
    """Keep supervisor tests isolated from global Settings mutations in full suite runs."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "enable_conservative_fast_routing", True, raising=False)


@pytest.fixture
def base_state():
    return {
        "query": "COLREGs Rule 13",
        "context": {},
        "domain_id": "maritime",
        "domain_config": {},
    }


# Lazy imports inside route()/synthesize() do:
#   from app.services.output_processor import extract_thinking_from_response
#   from app.domains.registry import get_domain_registry
# Patch at SOURCE module because they're resolved at call time.
EXTRACT_THINKING_PATCH = "app.services.output_processor.extract_thinking_from_response"
DOMAIN_REGISTRY_PATCH = "app.domains.registry.get_domain_registry"


# ---------------------------------------------------------------------------
# route() — LLM routing
# ---------------------------------------------------------------------------

class TestSupervisorRoute:
    """Sprint 103: route() always uses structured output (_route_structured)."""

    @pytest.mark.asyncio
    async def test_route_obvious_social_turn_sets_house_hint_and_uses_fast_path(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "Xin chào hảo hán",
            "context": {},
            "domain_config": {},
        }

        with patch.object(
            sup,
            "_route_structured",
            new=AsyncMock(return_value="direct"),
        ) as mock_route:
            result = await sup.route(state)

        assert result == "direct"
        assert state["_routing_hint"] == {
            "kind": "fast_chatter",
            "intent": "social",
            "shape": "social",
        }
        assert state["routing_metadata"]["method"] == "conservative_fast_path"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_ascii_greeting_instruction_uses_fast_path(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "Chao Wiii, tra loi ngan",
            "context": {},
            "domain_config": {},
        }

        with patch.object(sup, "_route_structured", new=AsyncMock(return_value="direct")) as mock_route:
            result = await sup.route(state)

        assert result == "direct"
        assert state["_routing_hint"] == {
            "kind": "fast_chatter",
            "intent": "social",
            "shape": "social",
        }
        assert state["routing_metadata"]["method"] == "conservative_fast_path"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_short_social_status_uses_fast_path_without_feature_flag(
        self,
        mock_llm,
        monkeypatch,
    ):
        from app.core.config import settings

        monkeypatch.setattr(
            settings,
            "enable_conservative_fast_routing",
            False,
            raising=False,
        )
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "trưa nay ăn cơm rồi",
            "context": {},
            "domain_config": {},
        }

        with patch.object(sup, "_route_structured", new=AsyncMock(return_value="direct")) as mock_route:
            result = await sup.route(state)

        assert result == "direct"
        assert state["_routing_hint"] == {
            "kind": "fast_chatter",
            "intent": "social",
            "shape": "social_status",
        }
        assert state["routing_metadata"]["method"] == "always_on_social_status_fast_path"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "query",
        [
            "noi de",
            "thế ngủ đi",
            "sao lại z",
            "sao lơ lửng ?",
        ],
    )
    async def test_route_short_social_followup_uses_fast_path(
        self,
        mock_llm,
        query,
    ):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": query,
            "context": {},
            "domain_config": {},
        }

        with patch.object(sup, "_route_structured", new=AsyncMock(return_value="direct")) as mock_route:
            result = await sup.route(state)

        assert result == "direct"
        assert state["_routing_hint"] == {
            "kind": "fast_chatter",
            "intent": "social",
            "shape": "social_followup",
        }
        assert state["routing_metadata"]["method"] == "conservative_fast_path"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_greeting_learning_request_does_not_use_fast_path(self, mock_llm, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_conservative_fast_routing", False, raising=False)
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "hello explain COLREG Rule 15",
            "context": {},
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="tutor_agent")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "tutor_agent"
        mock_route.assert_awaited_once()
        assert mock_route.await_args.args[6] is state
        assert state.get("_routing_hint", {}).get("kind") != "fast_chatter"

    @pytest.mark.asyncio
    async def test_route_laughter_social_turn_sets_house_hint_and_uses_fast_path(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "hẹ hẹ",
            "context": {},
            "domain_config": {},
        }

        with patch.object(sup, "_route_structured", new=AsyncMock(return_value="direct")) as mock_route:
            result = await sup.route(state)

        assert result == "direct"
        assert state["_routing_hint"] == {
            "kind": "fast_chatter",
            "intent": "social",
            "shape": "social",
        }
        assert state["routing_metadata"]["method"] == "conservative_fast_path"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_reaction_turn_sets_house_hint_and_uses_fast_path(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "wow",
            "context": {},
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="direct")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "direct"
        assert state["_routing_hint"] == {
            "kind": "fast_chatter",
            "intent": "social",
            "shape": "reaction",
        }
        assert state["routing_metadata"]["method"] == "conservative_fast_path"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_identity_probe_sets_house_hint_and_keeps_llm_first(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "ban la ai",
            "context": {},
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="direct")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "direct"
        assert state["_routing_hint"] == {
            "kind": "identity_probe",
            "intent": "selfhood",
            "shape": "identity",
        }
        mock_route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_selfhood_followup_sets_house_hint_when_recent_context_is_origin(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "còn Bông thì sao?",
            "context": {
                "conversation_summary": (
                    "Người dùng vừa hỏi Wiii được sinh ra như thế nào, và Wiii đã kể về The Wiii Lab,"
                    " đêm mưa tháng Giêng, cùng Bông."
                ),
            },
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="direct")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "direct"
        assert state["_routing_hint"] == {
            "kind": "selfhood_followup",
            "intent": "selfhood",
            "shape": "lore_followup",
        }
        mock_route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_vague_banter_turn_sets_house_hint_and_uses_fast_path(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "gì đó",
            "context": {},
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="direct")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "direct"
        assert state["_routing_hint"] == {
            "kind": "fast_chatter",
            "intent": "off_topic",
            "shape": "vague_banter",
        }
        assert state["routing_metadata"]["method"] == "conservative_fast_path"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_host_ui_navigation_uses_fast_path(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "Wiii oi, nut Kham pha khoa hoc o dau?",
            "context": {},
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="memory_agent")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "direct"
        assert state["routing_metadata"]["method"] == "conservative_fast_path"
        assert state["routing_metadata"]["intent"] == "host_ui_navigation"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_weather_turn_uses_turn_path_preflight(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "nay thoi tiet nong nhi",
            "context": {},
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="rag_agent")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "direct"
        assert state["routing_metadata"]["method"] == "turn_path_governor_preflight"
        assert state["routing_metadata"]["intent"] == "weather_lookup"
        assert state["routing_metadata"]["turn_path"] == "weather_lookup"
        assert state["_turn_path_decision"]["path"] == "weather_lookup"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_wiii_connect_status_uses_turn_path_preflight(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "Wiii co ket noi duoc facebook khong?",
            "context": {},
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="rag_agent")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "direct"
        assert state["routing_metadata"]["method"] == "turn_path_governor_preflight"
        assert state["routing_metadata"]["intent"] == "external_connection_status"
        assert state["routing_metadata"]["turn_path"] == "external_connection_status"
        assert state["_turn_path_decision"]["path"] == "external_connection_status"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_wiii_connect_action_uses_turn_path_preflight(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "Wiii dang mot bai bat ky len facebook di",
            "context": {},
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="rag_agent")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "direct"
        assert state["routing_metadata"]["method"] == "turn_path_governor_preflight"
        assert state["routing_metadata"]["intent"] == "external_app_action"
        assert state["routing_metadata"]["turn_path"] == "external_app_action"
        assert state["_turn_path_decision"]["path"] == "external_app_action"
        mock_route.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_route_learning_course_question_does_not_use_host_ui_fast_path(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "giai thich khoa hoc hang hai co ban cho toi",
            "context": {},
            "domain_config": {},
        }

        mock_route = AsyncMock(return_value="tutor_agent")
        with patch.object(sup, "_route_structured", new=mock_route):
            result = await sup.route(state)

        assert result == "tutor_agent"
        mock_route.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_route_to_rag(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)

        with _mock_structured_route("RAG_AGENT", intent="lookup"):
            result = await sup.route(base_state)
        assert result == "rag_agent"

    @pytest.mark.asyncio
    async def test_route_to_tutor(self, mock_llm, base_state, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_conservative_fast_routing", False, raising=False)
        sup = _make_supervisor(mock_llm)

        with _mock_structured_route("TUTOR_AGENT", intent="learning"):
            result = await sup.route(base_state)
        assert result == "tutor_agent"

    @pytest.mark.asyncio
    async def test_route_to_memory(self, mock_llm, base_state, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_conservative_fast_routing", False, raising=False)
        sup = _make_supervisor(mock_llm)

        with _mock_structured_route("MEMORY_AGENT", intent="personal"):
            result = await sup.route(base_state)
        assert result == "memory_agent"

    @pytest.mark.asyncio
    async def test_route_to_direct(self, mock_llm, base_state, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_conservative_fast_routing", False, raising=False)
        sup = _make_supervisor(mock_llm)

        with _mock_structured_route("DIRECT", intent="off_topic"):
            result = await sup.route(base_state)
        assert result == "direct"

    @pytest.mark.asyncio
    async def test_route_provider_unavailable_uses_rule_based_fallback(
        self,
        mock_llm,
        base_state,
        monkeypatch,
    ):
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_conservative_fast_routing", False, raising=False)
        base_state["query"] = "hello there"
        sup = _make_supervisor(mock_llm)

        with patch.object(
            sup,
            "_route_structured",
            new=AsyncMock(
                side_effect=ProviderUnavailableError(
                    provider="google",
                    reason_code="busy",
                    message="Provider tam thoi ban hoac da cham gioi han.",
                )
            ),
        ):
            result = await sup.route(base_state)

        assert result == "direct"
        assert base_state["routing_metadata"]["method"] == "rule_based"
        assert base_state["routing_metadata"]["reason_code"] == "busy"

    @pytest.mark.asyncio
    async def test_structured_routing_keeps_house_provider_as_primary_but_does_not_pin_failover(
        self,
        mock_llm,
        base_state,
        monkeypatch,
    ):
        from app.engine.structured_schemas import RoutingDecision
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_conservative_fast_routing", False, raising=False)
        base_state["query"] = "hello there"
        sup = _make_supervisor(mock_llm)
        base_state["provider"] = "auto"
        base_state["_house_routing_provider"] = "google"

        invoke_mock = AsyncMock(
            return_value=RoutingDecision(
                agent="DIRECT",
                intent="social",
                confidence=0.95,
                reasoning="structured route",
            )
        )

        with patch(
            "app.services.structured_invoke_service.StructuredInvokeService.ainvoke",
            new=invoke_mock,
        ):
            result = await sup.route(base_state)

        assert result == "direct"
        assert invoke_mock.await_args.kwargs["provider"] is None

    def test_code_studio_keywords_route_to_code_studio(self):
        sup = _make_supervisor(None)
        result = sup._rule_based_route("ve bieu do bang python va luu PNG")
        assert result == "code_studio_agent"

    @pytest.mark.asyncio
    async def test_route_to_code_studio(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)
        base_state["query"] = "Ve bieu do bang python va tao file PNG"

        with _mock_structured_route("CODE_STUDIO_AGENT", intent="code_execution"):
            result = await sup.route(base_state)
        assert result == "code_studio_agent"

    @pytest.mark.asyncio
    async def test_short_simulation_turn_overrides_to_code_studio(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)
        base_state["query"] = "mô phỏng được chứ?"

        with _mock_structured_route("DIRECT", intent="off_topic", confidence=0.82):
            result = await sup.route(base_state)

        assert result == "code_studio_agent"
        assert base_state["routing_metadata"]["method"] == "structured+capability_override"

    @pytest.mark.asyncio
    async def test_code_studio_domain_simulation_overrides_rag(self, mock_llm, base_state):
        from app.engine.multi_agent import supervisor as supervisor_module

        sup = _make_supervisor(mock_llm)
        base_state["query"] = (
            "Tao mot mini app Code Studio mo phong COLREG Rule 15 "
            "co slider va canvas tuong tac."
        )

        with (
            patch.object(supervisor_module.settings, "enable_conservative_fast_routing", False),
            _mock_structured_route("RAG_AGENT", intent="lookup", confidence=0.91),
        ):
            result = await sup.route(base_state)

        assert result == "code_studio_agent"
        assert base_state["routing_metadata"]["method"] == "structured+capability_override"

    @pytest.mark.asyncio
    async def test_code_studio_domain_simulation_fast_routes_before_rag(self, mock_llm, base_state):
        from app.engine.multi_agent import supervisor as supervisor_module

        sup = _make_supervisor(mock_llm)
        base_state["query"] = (
            "Tao mot mini app Code Studio mo phong COLREG Rule 15 "
            "co slider va canvas tuong tac."
        )

        with patch.object(supervisor_module.settings, "enable_conservative_fast_routing", True):
            result = await sup.route(base_state)

        assert result == "code_studio_agent"
        assert base_state["routing_metadata"]["method"] == "conservative_fast_path"

    @pytest.mark.asyncio
    async def test_wiii_capability_inventory_does_not_override_to_code_studio(self, mock_llm, base_state):
        from app.engine.multi_agent import supervisor as supervisor_module

        sup = _make_supervisor(mock_llm)
        base_state["query"] = (
            "Wiii hien xu ly duoc anh dau vao, tao anh, Word, Excel, "
            "video toi muc nao? Tra loi trung thuc, 5 y ngan."
        )

        with (
            patch.object(supervisor_module.settings, "enable_conservative_fast_routing", False),
            _mock_structured_route("DIRECT", intent="off_topic", confidence=0.95),
        ):
            result = await sup.route(base_state)

        assert result == "direct"
        assert base_state["routing_metadata"]["method"] == "structured"
        assert base_state["routing_metadata"]["intent"] == "off_topic"

    @pytest.mark.asyncio
    async def test_route_llm_unavailable_falls_back(self, base_state):
        sup = _make_supervisor(None)
        # No LLM → rule-based
        base_state["query"] = "COLREGs Rule 13 là gì và áp dụng như thế nào?"
        result = await sup.route(base_state)
        assert result in ("rag_agent", "tutor_agent", "memory_agent", "direct")

    @pytest.mark.asyncio
    async def test_route_llm_error_falls_back(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)
        base_state["query"] = "COLREGs Rule 13 là gì?"
        with patch(
            "app.services.structured_invoke_service.StructuredInvokeService.ainvoke",
            new=AsyncMock(side_effect=Exception("API error")),
        ):
            result = await sup.route(base_state)
        # Should fall back to rule-based without crashing
        assert isinstance(result, str)


    @pytest.mark.asyncio
    async def test_visual_data_request_stays_on_direct_lane(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)
        base_state["query"] = "Visual cho minh xem thong ke du lieu hien tai gia dau may ngay gan day"

        with _mock_structured_route("CODE_STUDIO_AGENT", intent="code_execution", confidence=0.94):
            result = await sup.route(base_state)

        assert result == "direct"
        assert base_state["routing_metadata"]["method"] == "structured+visual_lane_override"

    @pytest.mark.asyncio
    async def test_domain_follow_up_visual_keeps_tutor_when_recent_context_has_domain_signal(
        self,
        mock_llm,
    ):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "tao visual cho minh xem duoc chu?",
            "context": {
                "conversation_summary": "Vua giai thich COLREGs Rule 15 va Rule 13 cho nguoi hoc.",
            },
            "domain_config": {
                "routing_keywords": ["colregs, rule, quy tac"],
            },
        }

        with _mock_structured_route("TUTOR_AGENT", intent="learning", confidence=0.95), patch(
            "app.engine.multi_agent.supervisor.resolve_visual_intent",
            return_value=types.SimpleNamespace(presentation_intent="", force_tool=False),
        ):
            result = await sup.route(state)

        assert result == "tutor_agent"
        assert state["routing_metadata"]["method"] == "structured"
        assert state["_routing_hint"]["kind"] == "visual_followup"
        assert state["_routing_hint"]["intent"] == "learning"

    @pytest.mark.asyncio
    async def test_domain_follow_up_visual_keeps_tutor_when_recent_messages_carry_domain_signal(
        self,
        mock_llm,
    ):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "tạo visual cho mình xem được chứ?",
            "context": {
                "langchain_messages": [
                    Message(role="user", content="Giải thích Quy tắc 15 COLREGs"),
                    Message(role="assistant",
                        content="Rule 15 trong COLREGs tập trung vào tình huống cắt hướng, tàu thấy bên mạn phải phải nhường đường."
                    ),
                ],
            },
            "domain_config": {
                "routing_keywords": ["colregs, rule, quy tac, cắt hướng, nhường đường"],
            },
        }

        with _mock_structured_route("TUTOR_AGENT", intent="learning", confidence=0.95), patch(
            "app.engine.multi_agent.supervisor.resolve_visual_intent",
            return_value=types.SimpleNamespace(presentation_intent="", force_tool=False),
        ):
            result = await sup.route(state)

        assert result == "tutor_agent"
        assert state["routing_metadata"]["method"] == "structured"
        assert state["_routing_hint"]["kind"] == "visual_followup"
        assert state["_routing_hint"]["intent"] == "learning"

    @pytest.mark.asyncio
    async def test_domain_follow_up_visual_overrides_direct_back_to_tutor(
        self,
        mock_llm,
    ):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "tạo visual cho mình xem được chứ?",
            "context": {
                "langchain_messages": [
                    Message(role="user", content="Giải thích Quy tắc 15 COLREGs"),
                    Message(role="assistant",
                        content="Rule 15 trong COLREGs tập trung vào tình huống cắt hướng, tàu thấy bên mạn phải phải nhường đường."
                    ),
                ],
            },
            "domain_config": {
                "routing_keywords": ["colregs, rule, quy tac, cắt hướng, nhường đường"],
            },
        }

        with _mock_structured_route("DIRECT", intent="learning", confidence=0.95), patch(
            "app.engine.multi_agent.supervisor.resolve_visual_intent",
            return_value=types.SimpleNamespace(presentation_intent="", force_tool=False),
        ):
            result = await sup.route(state)

        assert result == "tutor_agent"
        assert state["routing_metadata"]["method"] == "structured+visual_followup_override"
        assert state["_routing_hint"]["kind"] == "visual_followup"

    @pytest.mark.asyncio
    async def test_domain_follow_up_visual_uses_history_list_when_db_history_is_unavailable(
        self,
        mock_llm,
    ):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "tao visual cho minh xem duoc chu?",
            "context": {
                "history_list": [
                    {"role": "user", "content": "Giai thich Quy tac 15 COLREGs"},
                    {
                        "role": "assistant",
                        "content": "Rule 15 noi ve tinh huong cat huong, tau thay ben man phai phai nhuong duong.",
                    },
                ],
                "conversation_history": (
                    "user: Giai thich Quy tac 15 COLREGs\n"
                    "assistant: Rule 15 noi ve tinh huong cat huong, tau thay ben man phai phai nhuong duong."
                ),
            },
            "domain_config": {
                "routing_keywords": ["colregs, rule, quy tac, cat huong, nhuong duong"],
            },
        }

        with _mock_structured_route("DIRECT", intent="learning", confidence=0.95), patch(
            "app.engine.multi_agent.supervisor.resolve_visual_intent",
            return_value=types.SimpleNamespace(presentation_intent="", force_tool=False),
        ):
            result = await sup.route(state)

        assert result == "tutor_agent"
        assert state["routing_metadata"]["method"] == "structured+visual_followup_override"
        assert state["_routing_hint"]["kind"] == "visual_followup"


class TestSupervisorCompactRoutingPrompt:
    @pytest.mark.parametrize(
        ("query", "fast_chatter_hint", "expected"),
        [
            ("co the uong ruou thuong trang khong ?", None, False),
            ("Wiii co the uong ruou thuong trang khong ?", None, False),
            ("uong ruou thuong trang duoc khong", None, False),
            ("hehe", ("social", "social"), True),
            ("mo phong duoc chua?", ("unknown", "short_probe"), True),
        ],
    )
    def test_short_natural_questions_do_not_use_compact_prompt(
        self,
        query,
        fast_chatter_hint,
        expected,
    ):
        from app.engine.multi_agent.supervisor import _should_use_compact_routing_prompt

        assert _should_use_compact_routing_prompt(query, fast_chatter_hint) is expected


# ---------------------------------------------------------------------------
# _rule_based_route() tests
# ---------------------------------------------------------------------------

class TestRuleBasedRoute:
    def test_no_domain_config_keeps_obvious_web_and_small_talk_on_direct(self):
        """Without LLM, obvious chatter/web turns still stay on DIRECT."""
        sup = _make_supervisor(None)
        assert sup._rule_based_route("cho tôi ví dụ") == "direct"
        assert sup._rule_based_route("tìm trên mạng về tàu") == "direct"
        assert sup._rule_based_route("tin tức hàng hải mới nhất") == "direct"

    def test_clear_learning_turns_route_to_tutor_when_llm_unavailable(self):
        sup = _make_supervisor(None)
        assert sup._rule_based_route("giải thích COLREGs") == "tutor_agent"
        assert sup._rule_based_route("Phân tích về toán học con lắc đơn") == "tutor_agent"

    def test_personal_keywords_route_to_memory(self):
        sup = _make_supervisor(None)
        assert sup._rule_based_route("tên tôi là gì nhỉ") == "memory_agent"
        assert sup._rule_based_route("nhớ lần trước không") == "memory_agent"

    def test_long_query_without_domain_defaults_to_direct(self):
        sup = _make_supervisor(None)
        # Sprint 80: No domain signal → DIRECT (off-topic protection)
        result = sup._rule_based_route("quy định nào áp dụng cho tàu máy lớn hơn 50m")
        assert result == "direct"

    def test_short_query_defaults_to_direct(self):
        sup = _make_supervisor(None)
        result = sup._rule_based_route("hi")
        assert result == "direct"

    def test_custom_domain_keywords_route_to_rag(self):
        sup = _make_supervisor(None)
        domain_config = {"routing_keywords": ["luật giao thông, biển báo"]}
        result = sup._rule_based_route("luật giao thông đường bộ", domain_config)
        assert result == "rag_agent"

    def test_domain_keywords_from_registry_fallback(self):
        sup = _make_supervisor(None)
        mock_domain = MagicMock()
        mock_config = MagicMock()
        mock_config.routing_keywords = ["colregs", "solas"]
        mock_domain.get_config.return_value = mock_config

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_domain

        with patch(DOMAIN_REGISTRY_PATCH, return_value=mock_registry):
            result = sup._rule_based_route("colregs rule 13")

        assert result == "rag_agent"

    def test_domain_registry_error_doesnt_crash(self):
        sup = _make_supervisor(None)
        with patch(DOMAIN_REGISTRY_PATCH, side_effect=Exception("No registry")):
            # Sprint 80: Should still work without crashing; no domain signal → DIRECT
            result = sup._rule_based_route("quy định nào áp dụng cho tàu máy lớn")
        assert result == "direct"


class TestDomainValidation:
    def test_validate_domain_routing_keeps_tutor_for_short_visual_followup(self):
        sup = _make_supervisor(None)
        result = sup._validate_domain_routing(
            "tạo visual cho mình xem được chứ?",
            "tutor_agent",
            {"routing_keywords": ["colregs, rule, quy tac"]},
            context={},
        )
        assert result == "tutor_agent"


class TestHouseRoutingProviderSelection:
    def test_prefers_selectable_provider_over_merely_available_primary(self):
        sup = _make_supervisor(None)
        state = {"provider": "auto", "query": "ban la ai"}

        with patch(
            "app.services.llm_selectability_service.choose_best_runtime_provider",
            return_value=types.SimpleNamespace(provider="zhipu"),
        ):
            assert sup._resolve_house_routing_provider(state) == "zhipu"

    def test_house_routing_provider_is_preference_not_strict_pin(self):
        sup = _make_supervisor(None)
        runtime_llm = MagicMock()

        with patch.object(
            sup,
            "_resolve_house_routing_provider",
            return_value="google",
        ), patch.object(
            AgentConfigRegistry,
            "get_llm",
            return_value=runtime_llm,
        ) as mock_get_llm:
            result = sup._get_llm_for_state({"query": "ban la ai"})

        assert result is runtime_llm
        assert mock_get_llm.call_args.args[0] == "supervisor"
        assert mock_get_llm.call_args.kwargs["provider_override"] == "google"
        assert mock_get_llm.call_args.kwargs["strict_provider_pin"] is False


# ---------------------------------------------------------------------------
# synthesize() tests
# ---------------------------------------------------------------------------

class TestSupervisorSynthesize:
    @pytest.mark.asyncio
    async def test_single_output_passthrough(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {"agent_outputs": {"rag": "Rule 13 answer"}}
        result = await sup.synthesize(state)
        assert result == "Rule 13 answer"

    @pytest.mark.asyncio
    async def test_single_text_output_ignores_metadata_passthrough(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "agent_outputs": {
                "tutor": "Sự khác biệt cốt lõi nằm ở điều kiện áp dụng.",
                "tutor_tools_used": [{"name": "tool_knowledge_search"}],
            }
        }
        result = await sup.synthesize(state)
        assert result == "Sự khác biệt cốt lõi nằm ở điều kiện áp dụng."
        mock_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_outputs_returns_apology(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {"agent_outputs": {}}
        result = await sup.synthesize(state)
        assert "Xin lỗi" in result

    @pytest.mark.asyncio
    async def test_no_outputs_salvages_search_tool_events(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "OpenAI latest model announcement 2026",
            "agent_outputs": {},
            "tool_call_events": [
                {
                    "type": "call",
                    "id": "web-1",
                    "name": "tool_web_search",
                    "args": {"query": "OpenAI latest model announcement 2026"},
                },
                {
                    "type": "result",
                    "id": "web-1",
                    "name": "tool_web_search",
                    "result": (
                        "**Introducing GPT-5.5 - OpenAI**\n"
                        "Apr 23, 2026 · OpenAI is releasing GPT-5.5.\n"
                        "URL: https://openai.com/index/introducing-gpt-5-5/"
                    ),
                },
            ],
        }
        result = await sup.synthesize(state)
        assert "Introducing GPT-5.5" in result
        assert "https://openai.com/index/introducing-gpt-5-5/" in result
        assert "chưa xử lý" not in result

    @pytest.mark.asyncio
    async def test_multiple_outputs_with_llm(self, mock_llm):
        mock_llm.ainvoke.return_value = MagicMock(content="Synthesized answer")
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "test",
            "agent_outputs": {"rag": "RAG output", "memory": "Memory output"},
        }

        with patch.object(sup, "_get_llm_for_state", return_value=mock_llm):
            with patch(EXTRACT_THINKING_PATCH, return_value=("Synthesized answer", None)):
                result = await sup.synthesize(state)

        assert result == "Synthesized answer"

    @pytest.mark.asyncio
    async def test_multiple_outputs_no_llm_concatenates(self):
        sup = _make_supervisor(None)
        state = {
            "query": "test",
            "agent_outputs": {"rag": "RAG output", "memory": "Memory output"},
        }
        with patch.object(sup, "_get_llm_for_state", return_value=None):
            result = await sup.synthesize(state)
        assert "RAG output" in result
        assert "Memory output" in result

    @pytest.mark.asyncio
    async def test_synthesis_llm_error_returns_first_output(self, mock_llm):
        mock_llm.ainvoke.side_effect = Exception("API error")
        sup = _make_supervisor(mock_llm)
        state = {
            "query": "test",
            "agent_outputs": {"rag": "RAG output", "tutor": "Tutor output"},
        }
        with patch.object(sup, "_get_llm_for_state", return_value=mock_llm):
            result = await sup.synthesize(state)
        # Returns first output on error
        assert result in ("RAG output", "Tutor output")


# ---------------------------------------------------------------------------
# process() tests
# ---------------------------------------------------------------------------

class TestSupervisorProcess:
    """Sprint 103: process() uses structured routing (RoutingDecision)."""

    def _setup_structured_mock(self, mock_llm, agent_name):
        """Helper to patch structured route via StructuredInvokeService."""
        intent_map = {
            "RAG_AGENT": "lookup",
            "TUTOR_AGENT": "learning",
            "MEMORY_AGENT": "personal",
            "DIRECT": "off_topic",
            "PRODUCT_SEARCH_AGENT": "product_search",
            "CODE_STUDIO_AGENT": "code_execution",
        }
        return _mock_structured_route(
            agent_name,
            intent=intent_map.get(agent_name, "lookup"),
        )

    @pytest.mark.asyncio
    async def test_process_sets_next_agent(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)

        with self._setup_structured_mock(mock_llm, "RAG_AGENT"):
            with patch(DOMAIN_REGISTRY_PATCH, side_effect=Exception("skip")):
                result = await sup.process(base_state)

        assert result["next_agent"] == "rag_agent"
        assert result["current_agent"] == "supervisor"

    @pytest.mark.asyncio
    async def test_process_does_not_push_supervisor_thinking_events(self, mock_llm, base_state, monkeypatch):
        """Supervisor does NOT push thinking bus events — thinking comes from agent nodes."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_conservative_fast_routing", False, raising=False)
        sup = _make_supervisor(mock_llm)

        from app.engine.multi_agent import graph_streaming

        bus_id = "test-supervisor-no-thinking"
        queue: asyncio.Queue = asyncio.Queue()
        graph_streaming._EVENT_QUEUES[bus_id] = queue
        graph_streaming._EVENT_QUEUE_CREATED[bus_id] = 0.0
        state = dict(base_state)
        state["_event_bus_id"] = bus_id

        try:
            with self._setup_structured_mock(mock_llm, "DIRECT"):
                with patch(DOMAIN_REGISTRY_PATCH, side_effect=Exception("skip")):
                    result = await sup.process(state)

            events = []
            while not queue.empty():
                events.append(queue.get_nowait())

            event_types = [event.get("type") for event in events if isinstance(event, dict)]
            assert result["next_agent"] == "direct"
            assert "thinking_start" not in event_types
            assert "thinking_delta" not in event_types
        finally:
            graph_streaming._EVENT_QUEUES.pop(bus_id, None)
            graph_streaming._EVENT_QUEUE_CREATED.pop(bus_id, None)

    @pytest.mark.asyncio
    async def test_process_skill_activation(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)

        mock_domain = MagicMock()
        mock_skill = MagicMock()
        mock_skill.id = "colregs_overview"
        mock_domain.match_skills.return_value = [mock_skill]
        mock_domain.activate_skill.return_value = "## COLREGs Overview\nContent here..."

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_domain

        with self._setup_structured_mock(mock_llm, "TUTOR_AGENT"):
            with patch(DOMAIN_REGISTRY_PATCH, return_value=mock_registry):
                result = await sup.process(base_state)

        assert result["skill_context"] == "## COLREGs Overview\nContent here..."

    @pytest.mark.asyncio
    async def test_process_keeps_capability_context_separate(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)

        mock_domain = MagicMock()
        mock_skill = MagicMock()
        mock_skill.id = "colregs_overview"
        mock_domain.match_skills.return_value = [mock_skill]
        mock_domain.activate_skill.return_value = "## COLREGs Overview\nContent here..."

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_domain

        with self._setup_structured_mock(mock_llm, "TUTOR_AGENT"):
            with patch(DOMAIN_REGISTRY_PATCH, return_value=mock_registry):
                with patch(
                    "app.engine.skills.skill_handbook.get_skill_handbook",
                    return_value=MagicMock(
                        summarize_for_query=MagicMock(return_value="Capability handbook phù hợp lúc này:\n- tool_knowledge_search")
                    ),
                ):
                    result = await sup.process(base_state)

        assert result["skill_context"] == "## COLREGs Overview\nContent here..."
        assert result["capability_context"].startswith("Capability handbook phù hợp")

    @pytest.mark.asyncio
    async def test_process_skill_activation_error_doesnt_crash(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)

        with self._setup_structured_mock(mock_llm, "RAG_AGENT"):
            with patch(DOMAIN_REGISTRY_PATCH, side_effect=Exception("Registry error")):
                result = await sup.process(base_state)

        # Should still route successfully despite skill error
        assert result["next_agent"] == "rag_agent"

    @pytest.mark.asyncio
    async def test_process_no_domain_id_skips_skills(self, mock_llm):
        state = {"query": "hello there test", "context": {}, "domain_id": "", "domain_config": {}}
        sup = _make_supervisor(mock_llm)

        with self._setup_structured_mock(mock_llm, "DIRECT"):
            result = await sup.process(state)

        assert "skill_context" not in result

    @pytest.mark.asyncio
    async def test_process_uses_parallel_dispatch_for_complex_learning_query(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)
        base_state["query"] = (
            "Giải thích thật chi tiết quy tắc 13 COLREG, "
            "đưa ví dụ thực tế và đối chiếu với tài liệu gốc giúp tôi nhé."
        )

        with self._setup_structured_mock(mock_llm, "TUTOR_AGENT"):
            with patch("app.core.config.settings.enable_subagent_architecture", True):
                with patch.object(sup, "_is_complex_query", return_value=True):
                    with patch(
                        "app.engine.multi_agent.orchestration_planner.plan_parallel_targets",
                        return_value=["tutor", "rag"],
                    ):
                        result = await sup.process(base_state)

        assert result["next_agent"] == "parallel_dispatch"
        assert result["_parallel_targets"] == ["tutor", "rag"]

    @pytest.mark.asyncio
    async def test_process_uses_parallel_dispatch_for_complex_product_query(self, mock_llm, base_state):
        sup = _make_supervisor(mock_llm)
        base_state["query"] = (
            "Tìm iPhone 17 Pro Max rẻ nhất, so giá trên nhiều nguồn "
            "và phân tích giúp tôi nguồn nào đáng tin nhất."
        )

        with self._setup_structured_mock(mock_llm, "PRODUCT_SEARCH_AGENT"):
            with patch("app.core.config.settings.enable_product_search", True):
                with patch("app.core.config.settings.enable_subagent_architecture", True):
                    with patch.object(sup, "_is_complex_query", return_value=True):
                        with patch(
                            "app.engine.multi_agent.orchestration_planner.plan_parallel_targets",
                            return_value=["search", "rag"],
                        ):
                            result = await sup.process(base_state)

        assert result["next_agent"] == "parallel_dispatch"
        assert result["_parallel_targets"] == ["search", "rag"]


# ---------------------------------------------------------------------------
# is_available() tests
# ---------------------------------------------------------------------------

class TestSupervisorIsAvailable:
    def test_available_with_llm(self, mock_llm):
        sup = _make_supervisor(mock_llm)
        assert sup.is_available() is True

    def test_not_available_without_llm(self):
        sup = _make_supervisor(None)
        assert sup.is_available() is False


# TestSupervisorVisibleReasoningContract removed — LLM-first:
# Wiii tự quyết thinking content via ReasoningNarrator, no hardcoded templates to test.


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSupervisorSingleton:
    def test_get_supervisor_agent_returns_instance(self):
        import app.engine.multi_agent.supervisor as mod
        mod._supervisor = None
        try:
            with patch.object(AgentConfigRegistry, "get_llm", return_value=MagicMock()):
                sup = mod.get_supervisor_agent()
                assert isinstance(sup, mod.SupervisorAgent)
                sup2 = mod.get_supervisor_agent()
                assert sup is sup2
        finally:
            mod._supervisor = None
