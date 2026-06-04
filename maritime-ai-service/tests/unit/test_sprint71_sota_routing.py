"""
Tests for Sprint 71: SOTA Supervisor Routing.

Tests:
1. TestEnhancedRoutingDecision — schema with reasoning, intent, confidence
2. TestIntentAwareRuleRouting — dual-signal logic (learning+domain=TUTOR)
3. TestConfidenceGate — confidence-gated structured routing
4. TestCoTRoutingPrompt — prompt includes few-shot, domain descriptions
5. TestRoutingMetadata — metadata stored in state for observability
"""

import sys
import types
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pydantic import ValidationError

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

from app.engine.multi_agent import supervisor as supervisor_module
from app.engine.multi_agent.agent_config import AgentConfigRegistry
from app.engine.multi_agent.supervisor import (
    SupervisorAgent, AgentType,
    ROUTING_PROMPT_TEMPLATE, CONFIDENCE_THRESHOLD,
    SOCIAL_KEYWORDS, PERSONAL_KEYWORDS,
)
from app.engine.structured_schemas import RoutingDecision

if not _had_cs:
    sys.modules.pop(_cs_key, None)
    if not _had_svc:
        sys.modules.pop(_svc_key, None)
elif _orig_cs is not None:
    sys.modules[_cs_key] = _orig_cs


# =============================================================================
# Fixtures
# =============================================================================

def _bypass_failover():
    """Bypass provider failover so structured-routing tests use mock LLMs."""
    async def _direct(llm, messages, **kwargs):
        del messages, kwargs
        ainvoke = getattr(llm, "ainvoke", None)
        if isinstance(ainvoke, AsyncMock):
            return await ainvoke([])
        raise Exception("Mock LLM fallback: no async ainvoke")

    return patch(
        "app.services.structured_invoke_service.ainvoke_with_failover",
        side_effect=_direct,
    )


@pytest.fixture
def supervisor():
    """Create SupervisorAgent with no LLM (tests rule-based routing)."""
    with patch.object(AgentConfigRegistry, "get_llm", return_value=None):
        agent = SupervisorAgent()
        agent._llm = None
        return agent


def _make_domain_config(keywords=None, domain_name="Hàng hải",
                         rag_desc="Tra cứu quy định", tutor_desc="Giải thích"):
    """Create a domain_config dict."""
    config = {
        "domain_name": domain_name,
        "rag_description": rag_desc,
        "tutor_description": tutor_desc,
    }
    if keywords is not None:
        config["routing_keywords"] = keywords
    return config


def _make_state(query="", domain_config=None, context=None):
    """Create a minimal AgentState dict."""
    return {
        "query": query,
        "context": context or {},
        "domain_config": domain_config or {},
    }


# =============================================================================
# 1. TestEnhancedRoutingDecision — Schema Tests
# =============================================================================

class TestEnhancedRoutingDecision:
    """Test enhanced RoutingDecision schema (Sprint 71)."""

    def test_valid_full_schema(self):
        """All fields populated correctly."""
        d = RoutingDecision(
            reasoning="Người dùng hỏi về quy tắc COLREGs → tra cứu",
            intent="lookup",
            agent="RAG_AGENT",
            confidence=0.95,
        )
        assert d.reasoning == "Người dùng hỏi về quy tắc COLREGs → tra cứu"
        assert d.intent == "lookup"
        assert d.agent == "RAG_AGENT"
        assert d.confidence == 0.95

    def test_confidence_bounds_min(self):
        """Confidence cannot be below 0."""
        with pytest.raises(ValidationError):
            RoutingDecision(agent="RAG_AGENT", confidence=-0.1)

    def test_confidence_bounds_max(self):
        """Confidence cannot be above 1."""
        with pytest.raises(ValidationError):
            RoutingDecision(agent="RAG_AGENT", confidence=1.5)

    def test_confidence_zero_valid(self):
        """Confidence=0 is valid."""
        d = RoutingDecision(agent="DIRECT", confidence=0.0)
        assert d.confidence == 0.0

    def test_confidence_one_valid(self):
        """Confidence=1 is valid."""
        d = RoutingDecision(agent="DIRECT", confidence=1.0)
        assert d.confidence == 1.0

    def test_intent_enum_values(self):
        """All intent values accepted."""
        for intent in ["lookup", "learning", "personal", "social", "off_topic", "web_search"]:
            d = RoutingDecision(agent="RAG_AGENT", intent=intent)
            assert d.intent == intent

    def test_invalid_intent_rejected(self):
        """Invalid intent is rejected."""
        with pytest.raises(ValidationError):
            RoutingDecision(agent="RAG_AGENT", intent="invalid")

    def test_backward_compat_agent_only(self):
        """Agent-only construction works (defaults for new fields)."""
        d = RoutingDecision(agent="TUTOR_AGENT")
        assert d.agent == "TUTOR_AGENT"
        assert d.reasoning == ""
        assert d.intent == "lookup"  # default
        assert d.confidence == 0.8  # default

    def test_agent_still_required(self):
        """Agent field is still required."""
        with pytest.raises(ValidationError):
            RoutingDecision()

    def test_invalid_agent_rejected(self):
        """Invalid agent values are rejected."""
        with pytest.raises(ValidationError):
            RoutingDecision(agent="INVALID_AGENT")


# =============================================================================
# 2. TestIntentAwareRuleRouting — The Main Bug Fix
# =============================================================================

class TestIntentAwareRuleRouting:
    """Test minimal rule-based routing guardrails (Sprint 103).

    Sprint 103: _rule_based_route simplified to 4 checks:
    social→DIRECT, personal→MEMORY, domain→RAG, default→DIRECT.
    Learning vs lookup distinction is handled by LLM structured routing.
    """

    def test_quiz_about_colregs_routes_to_rag(self, supervisor):
        """Sprint 103: 'quiz về COLREGs' → RAG (domain match, learning handled by LLM)."""
        config = _make_domain_config(["colregs", "solas", "marpol"])
        result = supervisor._rule_based_route("quiz về COLREGs", config)
        assert result == AgentType.RAG.value

    def test_explain_colregs_routes_to_rag(self, supervisor):
        """Sprint 103: 'giải thích Điều 15 COLREGs' → RAG (domain match)."""
        config = _make_domain_config(["colregs", "solas"])
        result = supervisor._rule_based_route("giải thích Điều 15 COLREGs", config)
        assert result == AgentType.RAG.value

    def test_lookup_colregs_routes_to_rag(self, supervisor):
        """'Điều 15 COLREGs nói gì' → RAG (domain match)."""
        config = _make_domain_config(["colregs", "solas"])
        result = supervisor._rule_based_route("Điều 15 COLREGs nói gì?", config)
        assert result == AgentType.RAG.value

    def test_lookup_fine_routes_to_rag(self, supervisor):
        """'tra cứu mức phạt vượt đèn đỏ' → RAG (domain match)."""
        config = _make_domain_config(["đèn đỏ", "mức phạt"])
        result = supervisor._rule_based_route("tra cứu mức phạt vượt đèn đỏ", config)
        assert result == AgentType.RAG.value

    def test_hello_routes_to_direct(self, supervisor):
        """'xin chào' → DIRECT (social)."""
        result = supervisor._rule_based_route("xin chào", {})
        assert result == AgentType.DIRECT.value

    def test_name_intro_routes_to_memory(self, supervisor):
        """'tên tôi là Nam' → MEMORY (personal)."""
        result = supervisor._rule_based_route("tên tôi là Nam", {})
        assert result == AgentType.MEMORY.value

    def test_wiii_does_not_remember_me_routes_to_memory(self, supervisor):
        """A recall complaint like 'Wii không nhớ mình?' routes to MEMORY."""
        result = supervisor._rule_based_route("Wii không nhớ mình hả ?", {})
        assert result == AgentType.MEMORY.value

    def test_teach_about_solas_routes_to_rag(self, supervisor):
        """Sprint 103: 'dạy tôi về SOLAS' → RAG (domain match)."""
        config = _make_domain_config(["colregs", "solas"])
        result = supervisor._rule_based_route("dạy tôi về SOLAS", config)
        assert result == AgentType.RAG.value

    def test_content_of_marpol_routes_to_rag(self, supervisor):
        """'nội dung MARPOL' → RAG (domain match)."""
        config = _make_domain_config(["marpol", "colregs"])
        result = supervisor._rule_based_route("nội dung MARPOL", config)
        assert result == AgentType.RAG.value

    def test_english_hello_routes_to_direct(self, supervisor):
        """'hello' → DIRECT (social)."""
        result = supervisor._rule_based_route("hello", {})
        assert result == AgentType.DIRECT.value

    def test_hi_alone_routes_to_direct(self, supervisor):
        """'hi' alone (short query) → DIRECT."""
        result = supervisor._rule_based_route("hi", {})
        assert result == AgentType.DIRECT.value

    def test_short_no_keywords_routes_to_direct(self, supervisor):
        """Short query <20 chars, no keywords → DIRECT."""
        result = supervisor._rule_based_route("ok", {})
        assert result == AgentType.DIRECT.value

    def test_long_no_keywords_routes_to_direct(self, supervisor):
        """Sprint 80: Long query, no domain keywords → DIRECT (off-topic protection)."""
        result = supervisor._rule_based_route("something completely unrelated to anything here", {})
        assert result == AgentType.DIRECT.value

    def test_domain_only_keyword_routes_to_rag(self, supervisor):
        """Domain keyword alone → RAG."""
        config = _make_domain_config(["colregs"])
        result = supervisor._rule_based_route("COLREGs", config)
        assert result == AgentType.RAG.value

    def test_learning_only_routes_to_tutor(self, supervisor):
        """Learning keyword alone routes to tutor even without domain keywords."""
        result = supervisor._rule_based_route("giải thích cho tôi đi", {})
        assert result == AgentType.TUTOR.value

    def test_social_beats_domain(self, supervisor):
        """Social intent has highest priority over domain keywords."""
        config = _make_domain_config(["chào"])
        result = supervisor._rule_based_route("xin chào bạn", config)
        assert result == AgentType.DIRECT.value

    def test_personal_beats_domain(self, supervisor):
        """Personal intent beats domain keywords."""
        config = _make_domain_config(["colregs"])
        result = supervisor._rule_based_route("tên tôi là Minh, tôi thích COLREGs", config)
        assert result == AgentType.MEMORY.value

    def test_compare_with_domain_routes_to_rag(self, supervisor):
        """Sprint 103: 'so sánh COLREGs và SOLAS' → RAG (domain match)."""
        config = _make_domain_config(["colregs", "solas"])
        result = supervisor._rule_based_route("so sánh COLREGs và SOLAS", config)
        assert result == AgentType.RAG.value

    def test_why_with_domain_routes_to_rag(self, supervisor):
        """Sprint 103: 'tại sao COLREGs quan trọng' → RAG (domain match)."""
        config = _make_domain_config(["colregs"])
        result = supervisor._rule_based_route("tại sao COLREGs quan trọng", config)
        assert result == AgentType.RAG.value

    def test_review_with_domain_routes_to_rag(self, supervisor):
        """Sprint 103: 'ôn bài về SOLAS' → RAG (domain match)."""
        config = _make_domain_config(["solas"])
        result = supervisor._rule_based_route("ôn bài về SOLAS", config)
        assert result == AgentType.RAG.value

    def test_bye_routes_to_direct(self, supervisor):
        """'tạm biệt' → DIRECT."""
        result = supervisor._rule_based_route("tạm biệt", {})
        assert result == AgentType.DIRECT.value

    def test_thanks_routes_to_direct(self, supervisor):
        """'cảm ơn' → DIRECT."""
        result = supervisor._rule_based_route("cảm ơn bạn", {})
        assert result == AgentType.DIRECT.value

    def test_remember_routes_to_memory(self, supervisor):
        """'remember' → MEMORY."""
        result = supervisor._rule_based_route("remember my preference", {})
        assert result == AgentType.MEMORY.value

    def test_self_intro_routes_to_memory(self, supervisor):
        """'tôi tên là' → MEMORY."""
        result = supervisor._rule_based_route("tôi tên là Nam, sinh viên năm 3", {})
        assert result == AgentType.MEMORY.value

    def test_domain_keyword_routes_to_rag(self, supervisor):
        """Domain keyword in query → RAG."""
        config = _make_domain_config(["colregs"])
        result = supervisor._rule_based_route("liệt kê các quy tắc COLREGs", config)
        assert result == AgentType.RAG.value


# =============================================================================
# 3. TestConfidenceGate — Confidence-Gated Structured Routing
# =============================================================================

class TestConfidenceGate:
    """Test confidence-gated structured routing (Sprint 71)."""

    @pytest.fixture(autouse=True)
    def _bypass_pool(self):
        with _bypass_failover():
            yield

    @pytest.fixture
    def supervisor_with_llm(self):
        """Create SupervisorAgent with a mock LLM."""
        with patch.object(AgentConfigRegistry, "get_llm", return_value=MagicMock()):
            agent = SupervisorAgent()
            return agent

    @pytest.mark.asyncio
    async def test_high_confidence_uses_llm_decision(self, supervisor_with_llm):
        """High confidence (>=0.7) → use LLM decision as-is."""
        mock_result = RoutingDecision(
            reasoning="Tra cứu quy định",
            intent="lookup",
            agent="RAG_AGENT",
            confidence=0.95,
        )
        mock_structured = AsyncMock(return_value=mock_result)
        supervisor_with_llm._llm.with_structured_output.return_value.ainvoke = mock_structured

        state = _make_state("Điều 15 COLREGs nói gì?",
                            _make_domain_config(["colregs"]))

        result = await supervisor_with_llm._route_structured(
            "Điều 15 COLREGs nói gì?", {}, "Hàng hải",
            "Tra cứu", "Giải thích", {"routing_keywords": ["colregs"]}, state
        )
        assert result == AgentType.RAG.value
        assert state["routing_metadata"]["method"] == "structured"
        assert state["routing_metadata"]["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_low_confidence_rule_agrees_keeps_llm(self, supervisor_with_llm):
        """Low confidence but rule agrees → keep LLM decision."""
        mock_result = RoutingDecision(
            reasoning="Có vẻ chào hỏi",
            intent="social",
            agent="DIRECT",
            confidence=0.5,
        )
        mock_structured = AsyncMock(return_value=mock_result)
        supervisor_with_llm._llm.with_structured_output.return_value.ainvoke = mock_structured

        state = _make_state("COLREGs rule 15?", _make_domain_config(["colregs"]))

        result = await supervisor_with_llm._route_structured(
            "hello", {}, "AI", "Tra cứu", "Giải thích", {}, state
        )
        # Rule-based also says DIRECT for "hello", so no override
        assert result == AgentType.DIRECT.value
        assert state["routing_metadata"]["method"] == "structured"

    @pytest.mark.asyncio
    async def test_low_confidence_rule_disagrees_overrides(self, supervisor_with_llm):
        """Low confidence + rule disagrees → override with rule-based result."""
        mock_result = RoutingDecision(
            reasoning="Không chắc",
            intent="lookup",
            agent="RAG_AGENT",
            confidence=0.4,
        )
        mock_structured = AsyncMock(return_value=mock_result)
        supervisor_with_llm._llm.with_structured_output.return_value.ainvoke = mock_structured

        state = _make_state("xin chào bạn")

        result = await supervisor_with_llm._route_structured(
            "xin chào bạn", {}, "AI", "Tra cứu", "Giải thích", {}, state
        )
        # LLM says RAG with low confidence, but "xin chào" → rule says DIRECT
        assert result == AgentType.DIRECT.value
        assert state["routing_metadata"]["method"] == "structured+rule_override"

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_rules(self, supervisor_with_llm):
        """LLM failure → fallback to rule-based routing."""
        supervisor_with_llm._llm.with_structured_output.side_effect = Exception("LLM down")

        state = _make_state("quiz về COLREGs",
                            _make_domain_config(["colregs"]))

        # Sprint 103: No feature flag check — always structured, falls back to rule-based
        with patch.object(
            supervisor_module.settings,
            "enable_conservative_fast_routing",
            False,
        ):
            result = await supervisor_with_llm.route(state)

        # Sprint 103: rule-based has no learning keywords → domain match → RAG
        assert result == AgentType.RAG.value
        assert state["routing_metadata"]["method"] == "rule_based"

    @pytest.mark.asyncio
    async def test_confidence_threshold_boundary(self, supervisor_with_llm):
        """Confidence exactly at threshold (0.7) is NOT overridden."""
        mock_result = RoutingDecision(
            reasoning="Vừa đủ tự tin",
            intent="lookup",
            agent="RAG_AGENT",
            confidence=CONFIDENCE_THRESHOLD,  # exactly 0.7
        )
        mock_structured = AsyncMock(return_value=mock_result)
        supervisor_with_llm._llm.with_structured_output.return_value.ainvoke = mock_structured

        state = _make_state("hello COLREGs", _make_domain_config(["colregs"]))

        result = await supervisor_with_llm._route_structured(
            "hello COLREGs", {}, "AI", "Tra cứu", "Giải thích", {"routing_keywords": ["colregs"]}, state
        )
        # confidence >= 0.7, no override
        assert result == AgentType.RAG.value
        assert state["routing_metadata"]["method"] == "structured"


# =============================================================================
# 4. TestCoTRoutingPrompt — Prompt Structure Tests
# =============================================================================

class TestCoTRoutingPrompt:
    """Test the CoT routing prompt template (Sprint 71)."""

    def test_prompt_includes_few_shot_examples(self):
        """Prompt contains Vietnamese few-shot examples."""
        assert "Quiz về SOLAS" in ROUTING_PROMPT_TEMPLATE
        assert "Giải thích Điều 15 COLREGs" in ROUTING_PROMPT_TEMPLATE
        assert "Xin chào" in ROUTING_PROMPT_TEMPLATE
        assert "Tên tôi là Nam" in ROUTING_PROMPT_TEMPLATE

    def test_prompt_includes_intent_types(self):
        """Prompt describes all 6 intent types (Sprint 103: +web_search)."""
        assert "lookup" in ROUTING_PROMPT_TEMPLATE
        assert "learning" in ROUTING_PROMPT_TEMPLATE
        assert "personal" in ROUTING_PROMPT_TEMPLATE
        assert "social" in ROUTING_PROMPT_TEMPLATE
        assert "off_topic" in ROUTING_PROMPT_TEMPLATE
        assert "web_search" in ROUTING_PROMPT_TEMPLATE

    def test_prompt_includes_domain_placeholders(self):
        """Prompt has domain-specific placeholders."""
        assert "{domain_name}" in ROUTING_PROMPT_TEMPLATE
        assert "{rag_description}" in ROUTING_PROMPT_TEMPLATE
        assert "{tutor_description}" in ROUTING_PROMPT_TEMPLATE

    def test_prompt_includes_critical_rule(self):
        """Prompt explicitly states learning+domain → TUTOR (NOT RAG)."""
        assert "TUTOR_AGENT (NOT RAG_AGENT)" in ROUTING_PROMPT_TEMPLATE

    def test_prompt_format_succeeds(self):
        """Prompt template formats without error."""
        formatted = ROUTING_PROMPT_TEMPLATE.format(
            scope_hint="",
            domain_name="Hàng hải",
            rag_description="Tra cứu quy định hàng hải",
            tutor_description="Dạy và giải thích kiến thức",
            query="quiz về COLREGs",
            context="{}",
            user_role="student",
        )
        assert "quiz về COLREGs" in formatted
        assert "Hàng hải" in formatted

    def test_prompt_context_truncation(self):
        """Context is truncated to 500 chars in formatting."""
        long_context = {"data": "x" * 1000}
        full_context_str = str(long_context)
        truncated = full_context_str[:500]
        formatted = ROUTING_PROMPT_TEMPLATE.format(
            scope_hint="",
            domain_name="AI",
            rag_description="Tra cứu",
            tutor_description="Giải thích",
            query="test",
            context=truncated,
            user_role="student",
        )
        # The truncated context (500 chars) is in the prompt, not the full context (1000+ chars)
        assert truncated in formatted
        assert full_context_str not in formatted


# =============================================================================
# 5. TestRoutingMetadata — Observability
# =============================================================================

class TestRoutingMetadata:
    """Test routing metadata stored in state (Sprint 71)."""

    @pytest.fixture(autouse=True)
    def _bypass_pool(self):
        with _bypass_failover():
            yield

    @pytest.mark.asyncio
    async def test_fast_route_sets_metadata(self):
        """Conservative fast routing sets metadata for obvious chatter."""
        with (
            patch.object(supervisor_module.settings, "enable_conservative_fast_routing", True),
            patch.object(AgentConfigRegistry, "get_llm", return_value=None),
        ):
            agent = SupervisorAgent()
            agent._llm = None

            state = _make_state("xin chào")
            await agent.route(state)

            assert "routing_metadata" in state
            meta = state["routing_metadata"]
            assert meta["method"] == "conservative_fast_path"
            assert meta["confidence"] == 1.0
            assert meta["final_agent"] == AgentType.DIRECT.value

    @pytest.mark.asyncio
    async def test_structured_route_sets_metadata(self):
        """Structured routing sets metadata with intent and reasoning."""
        with patch.object(AgentConfigRegistry, "get_llm", return_value=MagicMock()):
            agent = SupervisorAgent()

        mock_result = RoutingDecision(
            reasoning="Tra cứu quy định COLREGs",
            intent="lookup",
            agent="RAG_AGENT",
            confidence=0.92,
        )
        mock_structured = AsyncMock(return_value=mock_result)
        agent._llm.with_structured_output.return_value.ainvoke = mock_structured

        state = _make_state("Điều 15 COLREGs?")

        await agent._route_structured(
            "Điều 15 COLREGs?", {}, "Hàng hải",
            "Tra cứu", "Giải thích", {}, state
        )

        meta = state["routing_metadata"]
        assert meta["intent"] == "lookup"
        assert meta["confidence"] == 0.92
        assert meta["reasoning"] == "Tra cứu quy định COLREGs"
        assert meta["method"] == "structured"

    # Sprint 103: test_legacy_route_sets_metadata deleted — _route_legacy() removed.

    @pytest.mark.asyncio
    async def test_error_fallback_sets_metadata(self):
        """LLM error fallback sets metadata with error info."""
        with (
            patch.object(supervisor_module.settings, "enable_conservative_fast_routing", False),
            patch.object(AgentConfigRegistry, "get_llm", return_value=MagicMock()),
        ):
            agent = SupervisorAgent()

            state = _make_state("COLREGs rule 15?", _make_domain_config(["colregs"]))

            # Sprint 103: No feature flag check — always structured
            agent._llm.with_structured_output.side_effect = ValueError("broken")
            await agent.route(state)

        meta = state["routing_metadata"]
        assert meta["method"] == "rule_based"
        assert "LLM routing unavailable" in meta["reasoning"]

    @pytest.mark.asyncio
    async def test_process_sets_routing_metadata(self):
        """process() populates routing_metadata in returned state."""
        with (
            patch.object(supervisor_module.settings, "enable_conservative_fast_routing", True),
            patch.object(AgentConfigRegistry, "get_llm", return_value=None),
        ):
            agent = SupervisorAgent()
            agent._llm = None

            state = _make_state("xin chào")
            result_state = await agent.process(state)

            assert "routing_metadata" in result_state
            assert result_state["next_agent"] == AgentType.DIRECT.value
            assert result_state["routing_metadata"]["method"] == "conservative_fast_path"


# =============================================================================
# 6. TestKeywordLists — Keyword Coverage
# =============================================================================

class TestKeywordLists:
    """Test guardrail keyword lists (Sprint 103: only SOCIAL + PERSONAL kept)."""

    def test_social_keywords_non_empty(self):
        assert len(SOCIAL_KEYWORDS) > 0

    def test_personal_keywords_non_empty(self):
        assert len(PERSONAL_KEYWORDS) > 0

    # Sprint 103: LEARNING_KEYWORDS, LOOKUP_KEYWORDS deleted — LLM handles these.

    def test_social_includes_greetings(self):
        assert "xin chào" in SOCIAL_KEYWORDS
        assert "hello" in SOCIAL_KEYWORDS
        # "hi" excluded — too short, matches substrings like "anything"
        assert "hi" not in SOCIAL_KEYWORDS

    def test_personal_no_bare_toi(self):
        """'tôi' alone is too broad — should not be in personal keywords."""
        assert "tôi" not in PERSONAL_KEYWORDS

    def test_confidence_threshold_is_0_7(self):
        """Confidence threshold is 0.7."""
        assert CONFIDENCE_THRESHOLD == 0.7

    def test_web_search_intent_valid(self):
        """Sprint 103: web_search is a valid RoutingDecision intent."""
        d = RoutingDecision(agent="DIRECT", intent="web_search")
        assert d.intent == "web_search"


# =============================================================================
# 7. TestGetDomainKeywords — Helper Method
# =============================================================================

class TestGetDomainKeywords:
    """Test _get_domain_keywords helper."""

    def test_extracts_from_config(self, supervisor):
        config = {"routing_keywords": ["colregs", "solas"]}
        result = supervisor._get_domain_keywords(config)
        assert "colregs" in result
        assert "solas" in result

    def test_splits_comma_separated(self, supervisor):
        config = {"routing_keywords": ["colregs,solas,marpol"]}
        result = supervisor._get_domain_keywords(config)
        assert "colregs" in result
        assert "solas" in result
        assert "marpol" in result

    def test_lowercases_keywords(self, supervisor):
        config = {"routing_keywords": ["COLREGs", "SOLAS"]}
        result = supervisor._get_domain_keywords(config)
        assert "colregs" in result
        assert "solas" in result

    def test_empty_config_returns_empty_or_fallback(self, supervisor):
        """Empty config attempts fallback, returns empty on failure."""
        with patch("app.domains.registry.get_domain_registry", side_effect=Exception("no registry")):
            result = supervisor._get_domain_keywords({})
        assert result == []

    def test_none_config_returns_empty_or_fallback(self, supervisor):
        """None config attempts fallback."""
        with patch("app.domains.registry.get_domain_registry", side_effect=Exception("no registry")):
            result = supervisor._get_domain_keywords(None)
        assert result == []


# =============================================================================
# 8. TestRoutingStateIntegration — State Field
# =============================================================================

class TestRoutingStateIntegration:
    """Test that routing_metadata is a valid AgentState field."""

    def test_state_accepts_routing_metadata(self):
        """AgentState TypedDict accepts routing_metadata."""
        from app.engine.multi_agent.state import AgentState
        state: AgentState = {
            "query": "test",
            "routing_metadata": {
                "intent": "lookup",
                "confidence": 0.9,
                "reasoning": "test",
                "method": "structured",
            },
        }
        assert state["routing_metadata"]["intent"] == "lookup"

    def test_state_routing_metadata_optional(self):
        """routing_metadata is optional (total=False)."""
        from app.engine.multi_agent.state import AgentState
        state: AgentState = {"query": "test"}
        assert state.get("routing_metadata") is None


class TestRoutingMetadataAPIExposure:
    """Sprint 103: routing_metadata exposed in API response."""

    def test_chat_response_metadata_has_routing_metadata_field(self):
        """ChatResponseMetadata schema includes routing_metadata."""
        from app.models.schemas import ChatResponseMetadata

        meta = ChatResponseMetadata(
            agent_type="rag",
            processing_time=1.5,
            routing_metadata={
                "intent": "lookup",
                "confidence": 0.95,
                "reasoning": "Domain query",
                "method": "structured",
            },
        )
        assert meta.routing_metadata is not None
        assert meta.routing_metadata["intent"] == "lookup"
        assert meta.routing_metadata["confidence"] == 0.95

    def test_chat_response_metadata_routing_metadata_default_none(self):
        """routing_metadata defaults to None."""
        from app.models.schemas import ChatResponseMetadata

        meta = ChatResponseMetadata(agent_type="direct", processing_time=0.5)
        assert meta.routing_metadata is None

    def test_chat_response_metadata_routing_metadata_serializes(self):
        """routing_metadata appears in JSON serialization."""
        from app.models.schemas import ChatResponseMetadata

        meta = ChatResponseMetadata(
            agent_type="rag",
            processing_time=2.0,
            routing_metadata={"intent": "web_search", "confidence": 0.9},
        )
        data = meta.model_dump()
        assert "routing_metadata" in data
        assert data["routing_metadata"]["intent"] == "web_search"
