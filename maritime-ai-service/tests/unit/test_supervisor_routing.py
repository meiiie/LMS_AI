"""
Unit tests for Supervisor Agent routing logic.

Tests:
- _rule_based_route() for all keyword groups
- Web search keyword routing
- Domain keyword routing from config
- Fallback behavior
"""

import sys
import types
import pytest
from unittest.mock import patch, MagicMock

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

from app.core.exceptions import ProviderUnavailableError
from app.engine.multi_agent.agent_config import AgentConfigRegistry
from app.engine.multi_agent.supervisor import SupervisorAgent, AgentType

if not _had_cs:
    sys.modules.pop(_cs_key, None)
    if not _had_svc:
        sys.modules.pop(_svc_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def supervisor():
    """Create SupervisorAgent with mocked LLM (tests rule-based only)."""
    with patch.object(AgentConfigRegistry, "get_llm", return_value=None):
        agent = SupervisorAgent()
        agent._llm = None  # Force rule-based routing
        return agent


def _make_domain_config(keywords=None):
    """Create a domain_config dict with routing keywords."""
    if keywords is None:
        return {}
    return {"routing_keywords": keywords}


# =============================================================================
# Tests: Domain keyword routing
# =============================================================================

class TestDomainKeywordRouting:
    def test_routes_domain_keyword_to_rag(self, supervisor):
        config = _make_domain_config(["colregs", "solas", "marpol"])
        result = supervisor._rule_based_route("What is COLREGs Rule 5?", config)
        assert result == AgentType.RAG.value

    def test_routes_comma_separated_keywords(self, supervisor):
        config = _make_domain_config(["colregs,solas,marpol"])
        result = supervisor._rule_based_route("Tell me about SOLAS", config)
        assert result == AgentType.RAG.value

    def test_case_insensitive_domain_match(self, supervisor):
        config = _make_domain_config(["COLREGS", "SOLAS"])
        result = supervisor._rule_based_route("what about colregs?", config)
        assert result == AgentType.RAG.value

    def test_no_match_without_keywords(self, supervisor):
        config = _make_domain_config(["colregs", "solas"])
        result = supervisor._rule_based_route("hi", config)
        assert result == AgentType.DIRECT.value


# =============================================================================
# Tests: Domain keyword fallback from plugin
# =============================================================================

class TestDomainKeywordFallback:
    def test_loads_from_domain_plugin_when_no_config(self, supervisor):
        """When domain_config has no keywords, loads from registry."""
        mock_plugin = MagicMock()
        mock_plugin.get_config.return_value.routing_keywords = ["colregs", "solas"]

        with patch("app.domains.registry.get_domain_registry") as mock_reg:
            mock_reg.return_value.get.return_value = mock_plugin
            result = supervisor._rule_based_route("COLREGs Rule 5?", {})
        assert result == AgentType.RAG.value

    def test_empty_fallback_when_no_plugin(self, supervisor):
        """When no domain plugin and no config, domain keywords are empty."""
        with patch("app.domains.registry.get_domain_registry") as mock_reg:
            mock_reg.return_value.get.return_value = None
            # Sprint 80: No domain signal → DIRECT (off-topic protection)
            result = supervisor._rule_based_route("something completely unrelated to anything", {})
        assert result == AgentType.DIRECT.value


# Sprint 103: TestWebSearchRouting deleted — WEB_KEYWORDS removed.
# Sprint 103: TestLearningRouting deleted — LEARNING_KEYWORDS removed.
# All nuanced routing (web search, learning) handled by LLM structured routing.


# =============================================================================
# Tests: Personal/memory keyword routing
# =============================================================================

class TestMemoryRouting:
    def test_routes_remember_to_memory(self, supervisor):
        result = supervisor._rule_based_route("do you remember what I asked?", {})
        assert result == AgentType.MEMORY.value

    def test_routes_my_name_to_memory(self, supervisor):
        result = supervisor._rule_based_route("my name is Hung", {})
        assert result == AgentType.MEMORY.value

    def test_routes_last_time_to_memory(self, supervisor):
        result = supervisor._rule_based_route("last time we discussed Rule 5", {})
        assert result == AgentType.MEMORY.value

    def test_routes_vietnamese_remember_to_memory(self, supervisor):
        result = supervisor._rule_based_route("bạn có nhớ câu hỏi lần trước không?", {})
        assert result == AgentType.MEMORY.value

    def test_routes_wiii_recall_complaint_to_memory(self, supervisor):
        result = supervisor._rule_based_route("Wii không nhớ mình hả ?", {})
        assert result == AgentType.MEMORY.value

    @pytest.mark.asyncio
    async def test_provider_unavailable_routing_falls_back_to_memory(self):
        with patch.object(AgentConfigRegistry, "get_llm", return_value=MagicMock()):
            agent = SupervisorAgent()

        state = {
            "query": "Wii không nhớ mình hả ?",
            "context": {},
            "domain_config": {},
        }
        error = ProviderUnavailableError(provider="google", reason_code="busy")
        with patch.object(agent, "_route_structured", side_effect=error):
            result = await agent.route(state)

        assert result == AgentType.MEMORY.value
        assert state["routing_metadata"]["method"] == "rule_based"
        assert state["routing_metadata"]["final_agent"] == AgentType.MEMORY.value


# =============================================================================
# Tests: Default routing behavior
# =============================================================================

class TestDefaultRouting:
    def test_query_with_domain_keyword_routes_to_rag(self, supervisor):
        """Query with domain keyword still routes to RAG."""
        config = _make_domain_config(["vessel, ship"])
        result = supervisor._rule_based_route("What is the safe speed requirement for vessel?", config)
        assert result == AgentType.RAG.value

    def test_short_query_defaults_to_direct(self, supervisor):
        result = supervisor._rule_based_route("hi", {})
        assert result == AgentType.DIRECT.value

    def test_short_greeting_is_direct(self, supervisor):
        result = supervisor._rule_based_route("hello", {})
        assert result == AgentType.DIRECT.value

    def test_long_query_no_domain_defaults_to_direct(self, supervisor):
        """Sprint 80: Long queries without domain keywords → DIRECT (off-topic protection)."""
        result = supervisor._rule_based_route("a" * 50, {})
        assert result == AgentType.DIRECT.value

        result = supervisor._rule_based_route("What is the weather today in Hanoi?", {})
        assert result == AgentType.DIRECT.value


# =============================================================================
# Tests: Priority ordering (Sprint 103)
# Rule-based guardrails only: social > personal > domain > default
# All nuanced routing (learning vs lookup, web search) handled by LLM.
# =============================================================================

class TestRoutingPriority:
    """Sprint 103: Simplified priority — social > personal > domain > default."""

    def test_domain_keyword_routes_to_rag(self, supervisor):
        """Domain keyword present → RAG (Sprint 103: only guardrail check)."""
        config = _make_domain_config(["explain"])
        result = supervisor._rule_based_route("explain this concept", config)
        assert result == AgentType.RAG.value

    def test_domain_keyword_with_learning_signal(self, supervisor):
        """Sprint 103: 'quiz về bộ luật hàng hải' → RAG (domain match, no learning keywords)."""
        config = _make_domain_config(["hàng hải"])
        result = supervisor._rule_based_route("quiz về bộ luật hàng hải", config)
        assert result == AgentType.RAG.value

    def test_lookup_domain_still_goes_to_rag(self, supervisor):
        """Domain query → RAG."""
        config = _make_domain_config(["colregs"])
        result = supervisor._rule_based_route("tra cứu Điều 15 COLREGs", config)
        assert result == AgentType.RAG.value

    def test_social_beats_domain(self, supervisor):
        """Social intent has highest priority."""
        config = _make_domain_config(["chào"])
        result = supervisor._rule_based_route("xin chào", config)
        assert result == AgentType.DIRECT.value

    def test_personal_beats_domain(self, supervisor):
        """Personal intent beats domain."""
        config = _make_domain_config(["colregs"])
        result = supervisor._rule_based_route("tên tôi là Minh COLREGs", config)
        assert result == AgentType.MEMORY.value


# =============================================================================
# Tests: AgentType enum
# =============================================================================

class TestAgentType:
    def test_rag_value(self):
        assert AgentType.RAG.value == "rag_agent"

    def test_tutor_value(self):
        assert AgentType.TUTOR.value == "tutor_agent"

    def test_memory_value(self):
        assert AgentType.MEMORY.value == "memory_agent"

    def test_direct_value(self):
        assert AgentType.DIRECT.value == "direct"


# =============================================================================
# Sprint 80: Off-topic detection and Vietnamese polysemy
# =============================================================================

class TestOffTopicDetection:
    """Sprint 80: Queries not related to domain should route to DIRECT."""

    def test_hungry_on_ship_is_off_topic(self, supervisor):
        """The bug that started it: 'trên tàu đói quá' should NOT go to RAG."""
        config = _make_domain_config(["tàu thủy, tàu biển", "colregs", "hàng hải"])
        result = supervisor._rule_based_route("trên tàu đói quá thì làm gì", config)
        assert result == AgentType.DIRECT.value

    def test_cooking_on_ship_is_off_topic(self, supervisor):
        config = _make_domain_config(["tàu thủy, tàu biển", "colregs", "hàng hải"])
        result = supervisor._rule_based_route("nấu cơm trên tàu", config)
        assert result == AgentType.DIRECT.value

    def test_weather_is_off_topic(self, supervisor):
        config = _make_domain_config(["colregs", "solas", "hàng hải"])
        result = supervisor._rule_based_route("hôm nay thời tiết thế nào?", config)
        assert result == AgentType.DIRECT.value

    def test_programming_routes_to_code_studio(self, supervisor):
        config = _make_domain_config(["colregs", "solas", "hàng hải"])
        result = supervisor._rule_based_route("Python là ngôn ngữ lập trình gì?", config)
        # Post-code_studio_agent: programming queries route to code_studio
        assert result in (AgentType.DIRECT.value, "code_studio_agent")

    def test_general_life_advice_is_off_topic(self, supervisor):
        config = _make_domain_config(["colregs", "solas", "hàng hải"])
        result = supervisor._rule_based_route("làm thế nào để ngủ ngon hơn?", config)
        assert result == AgentType.DIRECT.value

    def test_train_tau_does_not_match_maritime(self, supervisor):
        """'tàu' alone shouldn't match maritime — removed from domain.yaml."""
        config = _make_domain_config(["tàu thủy, tàu biển", "hàng hải"])
        result = supervisor._rule_based_route("tàu hỏa đi Đà Nẵng mấy giờ?", config)
        assert result == AgentType.DIRECT.value

    def test_tau_thuy_still_matches_maritime(self, supervisor):
        """Compound 'tàu thủy' correctly matches maritime domain."""
        config = _make_domain_config(["tàu thủy, tàu biển", "hàng hải"])
        result = supervisor._rule_based_route("tàu thủy phải mang bao nhiêu áo phao?", config)
        assert result == AgentType.RAG.value

    def test_tau_bien_still_matches_maritime(self, supervisor):
        config = _make_domain_config(["tàu thủy, tàu biển", "hàng hải"])
        result = supervisor._rule_based_route("quy định an toàn tàu biển", config)
        assert result == AgentType.RAG.value

    def test_hang_hai_still_matches(self, supervisor):
        config = _make_domain_config(["hàng hải", "colregs"])
        result = supervisor._rule_based_route("quy tắc hàng hải phòng ngừa va chạm", config)
        assert result == AgentType.RAG.value

    def test_colregs_still_matches(self, supervisor):
        config = _make_domain_config(["colregs", "solas"])
        result = supervisor._rule_based_route("Điều 15 COLREGs nói gì?", config)
        assert result == AgentType.RAG.value

    def test_thuyen_truong_still_matches(self, supervisor):
        config = _make_domain_config(["thuyền, thuyền trưởng", "hàng hải"])
        result = supervisor._rule_based_route("nhiệm vụ của thuyền trưởng", config)
        assert result == AgentType.RAG.value

    def test_entertainment_is_off_topic(self, supervisor):
        config = _make_domain_config(["colregs", "solas", "hàng hải"])
        result = supervisor._rule_based_route("phim hay nhất 2025 là gì?", config)
        assert result == AgentType.DIRECT.value

    def test_math_is_off_topic(self, supervisor):
        config = _make_domain_config(["colregs", "solas", "hàng hải"])
        result = supervisor._rule_based_route("giải phương trình x^2 + 2x + 1 = 0", config)
        assert result == AgentType.DIRECT.value
