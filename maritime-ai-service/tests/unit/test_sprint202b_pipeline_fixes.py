"""Sprint 202b: "Dòng Chảy Đúng" — Product Search Pipeline Hardening.

Tests for:
- Follow-up detection in query_planner (langchain_messages extraction)
- Curation quality (no price sort, char limit, platform diversity)
- Synthesize context injection (conversation history, sort_label)
- State schema (_all_search_products_json)
- Regression (Sprint 202 curated cards compatibility)
"""

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _structured_invoke_uses_test_llm_mock(monkeypatch):
    """Keep query-planner pipeline tests on the mocked structured-output seam."""

    async def _ainvoke(*, llm, schema, payload, **kwargs):
        structured_llm = llm.with_structured_output(schema)
        return await structured_llm.ainvoke(payload)

    monkeypatch.setattr(
        "app.services.structured_invoke_service.StructuredInvokeService.ainvoke",
        _ainvoke,
    )


# ─── Helpers ──────────────────────────────────────────────────────


def _make_products(n: int = 20) -> List[Dict[str, Any]]:
    """Generate N fake product dicts for testing."""
    products = []
    platforms = ["shopee", "lazada", "google_shopping", "websosanh", "all_web"]
    for i in range(n):
        products.append({
            "title": f"Sản phẩm Test {i}",
            "price": f"{(i + 1) * 100_000:,}đ",
            "extracted_price": (i + 1) * 100_000,
            "link": f"https://example.com/product/{i}",
            "platform": platforms[i % len(platforms)],
            "rating": round(3.5 + (i % 15) * 0.1, 1),
            "sold_count": (i + 1) * 10,
            "seller": f"Shop {i}",
            "image": f"https://img.example.com/{i}.jpg",
            "snippet": f"Mô tả sản phẩm {i}",
        })
    return products


def _mock_settings(**overrides):
    """Create a mock settings object with Sprint 202b flags."""
    defaults = {
        "enable_curated_product_cards": False,
        "curated_product_max_cards": 8,
        "curated_product_llm_tier": "light",
        "enable_product_preview_cards": True,
        "product_preview_max_cards": 20,
        "enable_product_image_enrichment": False,
        "enable_query_planner": True,
        "product_search_max_iterations": 5,
        "enable_visual_product_search": False,
        "visual_product_search_provider": "google",
        "visual_product_search_model": "",
        "enable_dealer_search": False,
        "enable_contact_extraction": False,
        "enable_international_search": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ═════════════════════════════════════════════════════════════════
# Group 1: Follow-Up Detection in Query Planner
# ═════════════════════════════════════════════════════════════════


class TestFollowUpDetection:
    """Test that query_planner extracts langchain_messages for follow-up context."""

    @pytest.mark.asyncio
    async def test_planner_extracts_langchain_messages_dict_format(self):
        """Planner should extract messages when passed as dicts."""
        from app.engine.tools.query_planner import plan_search_queries

        mock_llm = MagicMock()
        mock_structured = AsyncMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_structured.ainvoke.return_value = None  # Force None → returns None

        context = {
            "conversation_summary": "User searched for Sony headphones",
            "langchain_messages": [
                {"role": "human", "content": "Tìm tai nghe Sony WH-1000XM5 giá tốt"},
                {"role": "ai", "content": "Đã tìm thấy 15 kết quả từ 5 nền tảng..."},
                {"role": "human", "content": "top 10 đắt nhất"},
            ],
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                await plan_search_queries("top 10 đắt nhất", context)

        # Verify the prompt was called with recent conversation
        call_args = mock_structured.ainvoke.call_args
        prompt_text = call_args[0][0]
        assert "tai nghe Sony WH-1000XM5" in prompt_text
        assert "top 10 đắt nhất" in prompt_text

    @pytest.mark.asyncio
    async def test_planner_extracts_langchain_messages_object_format(self):
        """Planner should extract messages when passed as LangChain-like objects."""
        from app.engine.tools.query_planner import plan_search_queries

        mock_llm = MagicMock()
        mock_structured = AsyncMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_structured.ainvoke.return_value = None

        class FakeMessage:
            def __init__(self, type_, content):
                self.type = type_
                self.content = content

        context = {
            "langchain_messages": [
                FakeMessage("human", "Tìm laptop Dell XPS 15"),
                FakeMessage("ai", "Kết quả tìm kiếm Dell XPS 15..."),
                FakeMessage("human", "rẻ nhất ở đâu"),
            ],
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                await plan_search_queries("rẻ nhất ở đâu", context)

        prompt_text = mock_structured.ainvoke.call_args[0][0]
        assert "Dell XPS 15" in prompt_text

    @pytest.mark.asyncio
    async def test_planner_short_query_preserves_product_context(self):
        """Short follow-up queries should have prior product context in prompt."""
        from app.engine.tools.query_planner import plan_search_queries

        mock_llm = MagicMock()
        mock_structured = AsyncMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_structured.ainvoke.return_value = None

        context = {
            "langchain_messages": [
                {"role": "human", "content": "Tìm máy in Zebra ZXP7"},
                {"role": "ai", "content": "Tìm thấy 8 kết quả..."},
                {"role": "human", "content": "so sánh"},
            ],
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                await plan_search_queries("so sánh", context)

        prompt_text = mock_structured.ainvoke.call_args[0][0]
        assert "Zebra ZXP7" in prompt_text
        assert "FOLLOW-UP" in prompt_text

    @pytest.mark.asyncio
    async def test_planner_standalone_query_unchanged(self):
        """Standalone long queries should not be affected by follow-up logic."""
        from app.engine.tools.query_planner import plan_search_queries

        mock_llm = MagicMock()
        mock_structured = AsyncMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_structured.ainvoke.return_value = None

        context = {}  # No conversation history

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                await plan_search_queries("Tìm tai nghe Sony WH-1000XM5 giá tốt nhất 2026", context)

        prompt_text = mock_structured.ainvoke.call_args[0][0]
        assert "Không có lịch sử" in prompt_text

    @pytest.mark.asyncio
    async def test_planner_empty_messages_no_crash(self):
        """Empty langchain_messages should not cause errors."""
        from app.engine.tools.query_planner import plan_search_queries

        mock_llm = MagicMock()
        mock_structured = AsyncMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_structured.ainvoke.return_value = None

        context = {"langchain_messages": []}

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                result = await plan_search_queries("test query", context)

        assert result is None  # Returned None because mock returns None

    @pytest.mark.asyncio
    async def test_planner_truncates_long_ai_responses(self):
        """Long AI responses should be truncated to 200 chars."""
        from app.engine.tools.query_planner import plan_search_queries

        mock_llm = MagicMock()
        mock_structured = AsyncMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_structured.ainvoke.return_value = None

        long_ai_content = "A" * 1000
        context = {
            "langchain_messages": [
                {"role": "human", "content": "Tìm SP"},
                {"role": "ai", "content": long_ai_content},
            ],
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                await plan_search_queries("follow up", context)

        prompt_text = mock_structured.ainvoke.call_args[0][0]
        # AI content should be truncated (200 chars from inner truncation, then 300 from outer)
        ai_line = [l for l in prompt_text.split("\n") if l.startswith("ai: ")][0]
        assert len(ai_line) < 400  # "ai: " + truncated content

    @pytest.mark.asyncio
    async def test_planner_max_6_messages_only(self):
        """Planner should only use last 6 messages from conversation."""
        from app.engine.tools.query_planner import plan_search_queries

        mock_llm = MagicMock()
        mock_structured = AsyncMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_structured.ainvoke.return_value = None

        messages = [{"role": "human", "content": f"Message {i}"} for i in range(20)]
        context = {"langchain_messages": messages}

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                await plan_search_queries("query", context)

        prompt_text = mock_structured.ainvoke.call_args[0][0]
        # Should NOT contain early messages, only last 6
        assert "Message 0" not in prompt_text
        assert "Message 14" in prompt_text  # 20-6=14 is the first included

    @pytest.mark.asyncio
    async def test_planner_context_summary_300_chars(self):
        """Conversation summary should be truncated at 300 chars (was 200)."""
        from app.engine.tools.query_planner import plan_search_queries

        mock_llm = MagicMock()
        mock_structured = AsyncMock()
        mock_llm.with_structured_output.return_value = mock_structured
        mock_structured.ainvoke.return_value = None

        long_summary = "X" * 500
        context = {"conversation_summary": long_summary}

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                await plan_search_queries("query", context)

        prompt_text = mock_structured.ainvoke.call_args[0][0]
        # Should contain "Conversation: " + 300 chars max
        conv_line = [l for l in prompt_text.split("\n") if l.startswith("Conversation: ")][0]
        assert len(conv_line) < 320  # "Conversation: " + 300 X's


# ═════════════════════════════════════════════════════════════════
# Group 2: Curation Quality
# ═════════════════════════════════════════════════════════════════


class TestCurationQuality:
    """Test curation improvements: char limit, criteria order, platform display."""

    def test_char_limit_effectively_unlimited(self):
        """Max product text chars should be 100K (effectively unlimited)."""
        from app.engine.multi_agent.subagents.search.curation import _MAX_PRODUCT_TEXT_CHARS
        assert _MAX_PRODUCT_TEXT_CHARS == 100_000

    def test_prompt_diversity_criteria_at_position_2(self):
        """'Đa dạng nguồn' should be at position 2 in criteria."""
        from app.engine.multi_agent.subagents.search.curation import _CURATION_PROMPT
        lines = _CURATION_PROMPT.split("\n")
        criteria_lines = [l.strip() for l in lines if l.strip().startswith(("1.", "2.", "3.", "4.", "5.", "6."))]
        assert any("Đa dạng nguồn" in l for l in criteria_lines if l.startswith("2."))

    def test_platform_always_shown_in_compact_text(self):
        """Platform should always appear even when empty."""
        from app.engine.multi_agent.subagents.search.curation import _build_compact_product_text

        products = [{"title": "Test Product", "price": "100đ", "platform": ""}]
        text = _build_compact_product_text(products)
        assert "Sàn: web" in text  # Empty platform → "web"

    def test_platform_shown_when_present(self):
        """Platform should show actual name when provided."""
        from app.engine.multi_agent.subagents.search.curation import _build_compact_product_text

        products = [{"title": "Test Product", "price": "100đ", "platform": "shopee"}]
        text = _build_compact_product_text(products)
        assert "Sàn: shopee" in text

    def test_compact_text_fits_all_products(self):
        """With 100K chars, compact text should fit all products."""
        from app.engine.multi_agent.subagents.search.curation import _build_compact_product_text

        products = _make_products(70)
        text = _build_compact_product_text(products)
        # Count actual product lines (start with [N])
        product_lines = [l for l in text.split("\n") if l.startswith("[")]
        assert len(product_lines) == 70  # All products should fit



# ═════════════════════════════════════════════════════════════════
# Group 3: Synthesize Context Injection
# ═════════════════════════════════════════════════════════════════


class TestSynthesizeContext:
    """Test conversation history injection in synthesize_response."""

    @pytest.mark.asyncio
    async def test_conversation_history_injected(self):
        """synthesize_response should inject langchain_messages into LLM messages."""
        from app.engine.multi_agent.subagents.search.workers import synthesize_response

        products = _make_products(5)
        captured_messages = []

        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.content = "Test response"
        mock_llm.ainvoke = AsyncMock(return_value=mock_result)

        def capture_invoke(msgs):
            captured_messages.extend(msgs)
            return mock_result

        mock_llm.ainvoke = AsyncMock(side_effect=capture_invoke)

        state = {
            "curated_products": products,
            "deduped_products": products,
            "platforms_searched": ["shopee"],
            "platform_errors": [],
            "query": "top 10 đắt nhất",
            "context": {
                "langchain_messages": [
                    {"role": "human", "content": "Tìm tai nghe Sony WH-1000XM5"},
                    {"role": "ai", "content": "Đã tìm thấy kết quả..."},
                ],
            },
        }

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg:
            mock_reg.get_llm.return_value = mock_llm
            result = await synthesize_response(state)

        # Should have system_dict + 2 history dicts + user_dict (synthesis prompt)
        assert len(captured_messages) == 4
        # Phase 1 migration: history items are also native dicts inside workers_runtime
        msg = captured_messages[1]
        history_content = msg["content"] if isinstance(msg, dict) else getattr(msg, "content", "")
        assert "Sony WH-1000XM5" in history_content

    @pytest.mark.asyncio
    async def test_no_history_no_crash(self):
        """synthesize_response should work fine without langchain_messages."""
        from app.engine.multi_agent.subagents.search.workers import synthesize_response

        products = _make_products(3)
        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.content = "Response text"
        mock_llm.ainvoke = AsyncMock(return_value=mock_result)

        state = {
            "curated_products": products,
            "deduped_products": products,
            "platforms_searched": ["shopee"],
            "platform_errors": [],
            "query": "Tìm laptop Dell",
            "context": {},  # No langchain_messages
        }

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg:
            mock_reg.get_llm.return_value = mock_llm
            result = await synthesize_response(state)

        assert result["final_response"] == "Response text"

    @pytest.mark.asyncio
    async def test_long_messages_truncated_in_synthesize(self):
        """Long messages in history should be truncated to 500 chars."""
        from app.engine.multi_agent.subagents.search.workers import synthesize_response

        captured_messages = []
        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.content = "Done"

        def capture_invoke(msgs):
            captured_messages.extend(msgs)
            return mock_result

        mock_llm.ainvoke = AsyncMock(side_effect=capture_invoke)

        state = {
            "curated_products": _make_products(2),
            "deduped_products": _make_products(2),
            "platforms_searched": ["shopee"],
            "platform_errors": [],
            "query": "follow up",
            "context": {
                "langchain_messages": [
                    {"role": "human", "content": "X" * 2000},
                ],
            },
        }

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg:
            mock_reg.get_llm.return_value = mock_llm
            await synthesize_response(state)

        # History message (index 1) should be truncated
        history_msg = captured_messages[1]
        history_content = history_msg["content"] if isinstance(history_msg, dict) else getattr(history_msg, "content", "")
        assert len(history_content) <= 500

    @pytest.mark.asyncio
    async def test_curated_sort_label_text(self):
        """When curated_products exist, sort_label should say 'LLM lọc chọn'."""
        from app.engine.multi_agent.subagents.search.workers import synthesize_response

        captured_messages = []
        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.content = "Done"

        def capture_invoke(msgs):
            captured_messages.extend(msgs)
            return mock_result

        mock_llm.ainvoke = AsyncMock(side_effect=capture_invoke)

        state = {
            "curated_products": _make_products(3),
            "deduped_products": _make_products(20),
            "platforms_searched": ["shopee"],
            "platform_errors": [],
            "query": "test",
            "context": {},
        }

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg:
            mock_reg.get_llm.return_value = mock_llm
            await synthesize_response(state)

        # The last HumanMessage contains the synthesis prompt
        _last = captured_messages[-1]
        synthesis_prompt = _last["content"] if isinstance(_last, dict) else getattr(_last, "content", "")
        assert "đã được LLM lọc chọn" in synthesis_prompt
        assert "sắp xếp giá rẻ nhất" not in synthesis_prompt

    @pytest.mark.asyncio
    async def test_non_curated_sort_label_text(self):
        """When no curated_products, sort_label should say 'sắp xếp giá rẻ nhất'."""
        from app.engine.multi_agent.subagents.search.workers import synthesize_response

        captured_messages = []
        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.content = "Done"

        def capture_invoke(msgs):
            captured_messages.extend(msgs)
            return mock_result

        mock_llm.ainvoke = AsyncMock(side_effect=capture_invoke)

        state = {
            "deduped_products": _make_products(10),
            "platforms_searched": ["shopee"],
            "platform_errors": [],
            "query": "test",
            "context": {},
            # No curated_products key
        }

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg:
            mock_reg.get_llm.return_value = mock_llm
            await synthesize_response(state)

        _last = captured_messages[-1]
        synthesis_prompt = _last["content"] if isinstance(_last, dict) else getattr(_last, "content", "")
        assert "sắp xếp giá rẻ nhất" in synthesis_prompt

    @pytest.mark.asyncio
    async def test_all_products_json_preserved(self):
        """synthesize_response should return _all_search_products_json."""
        from app.engine.multi_agent.subagents.search.workers import synthesize_response

        products = _make_products(15)
        mock_llm = MagicMock()
        mock_result = MagicMock()
        mock_result.content = "Response"
        mock_llm.ainvoke = AsyncMock(return_value=mock_result)

        state = {
            "curated_products": products[:5],
            "deduped_products": products,
            "platforms_searched": ["shopee"],
            "platform_errors": [],
            "query": "test",
            "context": {},
        }

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg:
            mock_reg.get_llm.return_value = mock_llm
            result = await synthesize_response(state)

        assert "_all_search_products_json" in result
        parsed = json.loads(result["_all_search_products_json"])
        assert len(parsed) == 15  # All deduped products preserved


# ═════════════════════════════════════════════════════════════════
# Group 4: State Schema
# ═════════════════════════════════════════════════════════════════


class TestStateSchema:
    """Test SearchSubgraphState schema additions."""

    def test_all_search_products_json_field_exists(self):
        """_all_search_products_json should be a field in SearchSubgraphState."""
        from app.engine.multi_agent.subagents.search.state import SearchSubgraphState
        annotations = SearchSubgraphState.__annotations__
        assert "_all_search_products_json" in annotations

    def test_state_accepts_string_data(self):
        """State should accept string data for _all_search_products_json."""
        from app.engine.multi_agent.subagents.search.state import SearchSubgraphState
        # TypedDict should accept the field without error
        state: SearchSubgraphState = {
            "query": "test",
            "_all_search_products_json": json.dumps([{"title": "Test"}]),
        }
        assert "_all_search_products_json" in state


# ═════════════════════════════════════════════════════════════════
# Group 5: Planner Prompt
# ═════════════════════════════════════════════════════════════════


class TestPlannerPrompt:
    """Test planner prompt template changes."""

    def test_recent_conversation_placeholder_in_prompt(self):
        """_PLANNER_PROMPT should contain {recent_conversation} placeholder."""
        from app.engine.tools.query_planner import _PLANNER_PROMPT
        assert "{recent_conversation}" in _PLANNER_PROMPT

    def test_follow_up_section_present(self):
        """_PLANNER_PROMPT should contain FOLLOW-UP guidance section."""
        from app.engine.tools.query_planner import _PLANNER_PROMPT
        assert "FOLLOW-UP" in _PLANNER_PROMPT

    def test_format_args_match(self):
        """Prompt should format correctly with all 3 args."""
        from app.engine.tools.query_planner import _PLANNER_PROMPT
        # Should not raise KeyError
        result = _PLANNER_PROMPT.format(
            query="test query",
            context="test context",
            recent_conversation="test conversation",
        )
        assert "test query" in result
        assert "test context" in result
        assert "test conversation" in result


# ═════════════════════════════════════════════════════════════════
# Group 6: Query Rewrite in plan_search
# ═════════════════════════════════════════════════════════════════


class TestQueryRewrite:
    """Test that plan_search rewrites short follow-up queries with product context."""

    @pytest.mark.asyncio
    async def test_followup_query_rewritten_with_product_name(self):
        """Short follow-up query should be rewritten with planner's product_name_vi."""
        from app.engine.multi_agent.subagents.search.workers import plan_search
        from app.engine.tools.query_planner import QueryPlan, SubQuery, SearchIntent, SearchStrategy

        plan = QueryPlan(
            product_name_en="Sony WH-1000XM5 headphones",
            product_name_vi="tai nghe Sony WH-1000XM5",
            brand="Sony",
            model_number="WH-1000XM5",
            intent=SearchIntent.B2C_CONSUMER,
            search_strategy=SearchStrategy.ECOMMERCE_FIRST,
            sub_queries=[SubQuery(platform="google_shopping", query="tai nghe Sony WH-1000XM5 đắt nhất")],
            synonyms=["Sony WH-1000XM5"],
            reasoning="Follow-up query",
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=plan)
        mock_llm.with_structured_output.return_value = mock_structured

        state = {
            "query": "top 10 đắt nhất",
            "context": {
                "langchain_messages": [
                    {"role": "human", "content": "Tìm tai nghe Sony WH-1000XM5 giá tốt"},
                    {"role": "ai", "content": "Đã tìm thấy kết quả..."},
                ],
            },
            "_event_bus_id": None,
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                with patch(
                    "app.engine.search_platforms.get_search_platform_registry",
                    return_value=MagicMock(get_all_enabled=MagicMock(return_value=[])),
                ):
                    result = await plan_search(state)

        # Query should be rewritten to include product name
        assert "tai nghe Sony WH-1000XM5" in result["query"]
        assert "đắt nhất" in result["query"]
        assert result["query_variants"][0] == result["query"]

    @pytest.mark.asyncio
    async def test_standalone_query_not_rewritten(self):
        """Long standalone queries should NOT be rewritten even with planner."""
        from app.engine.multi_agent.subagents.search.workers import plan_search
        from app.engine.tools.query_planner import QueryPlan, SubQuery, SearchIntent, SearchStrategy

        original_query = "Tìm tai nghe Sony WH-1000XM5 giá tốt nhất 2026"
        plan = QueryPlan(
            product_name_en="Sony WH-1000XM5",
            product_name_vi="tai nghe Sony WH-1000XM5",
            brand="Sony",
            model_number="WH-1000XM5",
            intent=SearchIntent.B2C_CONSUMER,
            search_strategy=SearchStrategy.ECOMMERCE_FIRST,
            sub_queries=[SubQuery(platform="google_shopping", query=original_query)],
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=plan)
        mock_llm.with_structured_output.return_value = mock_structured

        state = {
            "query": original_query,
            "context": {},
            "_event_bus_id": None,
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                with patch(
                    "app.engine.search_platforms.get_search_platform_registry",
                    return_value=MagicMock(get_all_enabled=MagicMock(return_value=[])),
                ):
                    result = await plan_search(state)

        # Query already contains the product name — should NOT be rewritten
        assert result["query"] == original_query

    @pytest.mark.asyncio
    async def test_no_rewrite_when_planner_disabled(self):
        """When planner is disabled, query should remain unchanged."""
        from app.engine.multi_agent.subagents.search.workers import plan_search

        state = {
            "query": "top 10 đắt nhất",
            "context": {},
            "_event_bus_id": None,
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings(enable_query_planner=False)):
            with patch(
                "app.engine.search_platforms.get_search_platform_registry",
                return_value=MagicMock(get_all_enabled=MagicMock(return_value=[])),
            ):
                result = await plan_search(state)

        assert result["query"] == "top 10 đắt nhất"

    @pytest.mark.asyncio
    async def test_no_rewrite_when_product_already_in_query(self):
        """When product name is already in query, should NOT duplicate."""
        from app.engine.multi_agent.subagents.search.workers import plan_search
        from app.engine.tools.query_planner import QueryPlan, SubQuery, SearchIntent, SearchStrategy

        plan = QueryPlan(
            product_name_en="Sony WH-1000XM5",
            product_name_vi="tai nghe Sony WH-1000XM5",
            brand="Sony",
            intent=SearchIntent.B2C_CONSUMER,
            search_strategy=SearchStrategy.ECOMMERCE_FIRST,
            sub_queries=[SubQuery(platform="google_shopping", query="test")],
        )

        mock_llm = MagicMock()
        mock_structured = MagicMock()
        mock_structured.ainvoke = AsyncMock(return_value=plan)
        mock_llm.with_structured_output.return_value = mock_structured

        state = {
            "query": "tai nghe Sony WH-1000XM5 rẻ nhất",  # Already contains product
            "context": {},
            "_event_bus_id": None,
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings()):
            with patch("app.engine.llm_pool.get_llm_light", return_value=mock_llm):
                with patch(
                    "app.engine.search_platforms.get_search_platform_registry",
                    return_value=MagicMock(get_all_enabled=MagicMock(return_value=[])),
                ):
                    result = await plan_search(state)

        # Should NOT prepend — product name already in query
        assert result["query"] == "tai nghe Sony WH-1000XM5 rẻ nhất"


# ═════════════════════════════════════════════════════════════════
# Group 7: Regression
# ═════════════════════════════════════════════════════════════════


class TestRegression:
    """Ensure Sprint 202 curated cards and preview suppression still work."""

    @pytest.mark.asyncio
    async def test_curate_products_node_still_works(self):
        """curate_products node should still function with Sprint 202b changes."""
        from app.engine.multi_agent.subagents.search.workers import curate_products

        products = _make_products(5)
        state = {
            "deduped_products": products,
            "query": "test",
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=False)):
            result = await curate_products(state)

        assert "curated_products" in result
        assert len(result["curated_products"]) == 5  # All products (below max)

    @pytest.mark.asyncio
    async def test_preview_suppression_unchanged(self):
        """Raw previews should still be suppressed when curation is active."""
        from app.engine.multi_agent.subagents.search.workers import platform_worker

        state = {
            "platform_id": "google_shopping",
            "query": "test",
            "max_results": 5,
            "page": 1,
            "_event_bus_id": None,
        }

        mock_adapter = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"title": "Test", "link": "https://example.com", "price": "100đ"}
        mock_adapter.search_sync.return_value = [mock_result]

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_adapter

        with patch("app.engine.search_platforms.get_search_platform_registry", return_value=mock_registry):
            with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=True)):
                result = await platform_worker(state)

        assert len(result["all_products"]) == 1

    @pytest.mark.asyncio
    async def test_aggregate_dedup_still_works(self):
        """Deduplication in aggregate_results should still work."""
        from app.engine.multi_agent.subagents.search.workers import aggregate_results

        products = [
            {"title": "A", "link": "https://a.com", "extracted_price": 500},
            {"title": "B", "link": "https://a.com", "extracted_price": 300},  # Duplicate link
            {"title": "C", "link": "https://c.com", "extracted_price": 100},
        ]

        state = {
            "all_products": products,
            "platforms_searched": ["shopee"],
            "query": "test",
            "_event_bus_id": None,
        }

        result = await aggregate_results(state)
        assert len(result["deduped_products"]) == 2  # Deduplicated

    @pytest.mark.asyncio
    async def test_aggregate_order_preserves_platform_interleaving(self):
        """After removing price sort, products should stay in platform-interleaved order."""
        from app.engine.multi_agent.subagents.search.workers import aggregate_results

        products = [
            {"title": "Shopee-1", "link": "https://s1.com", "platform": "shopee", "extracted_price": 500},
            {"title": "Lazada-1", "link": "https://l1.com", "platform": "lazada", "extracted_price": 100},
            {"title": "Shopee-2", "link": "https://s2.com", "platform": "shopee", "extracted_price": 200},
            {"title": "Google-1", "link": "https://g1.com", "platform": "google_shopping", "extracted_price": 800},
        ]

        state = {
            "all_products": products,
            "platforms_searched": ["shopee", "lazada", "google_shopping"],
            "query": "test",
            "_event_bus_id": None,
        }

        result = await aggregate_results(state)
        deduped = result["deduped_products"]
        # Order should be preserved (not sorted by price)
        assert deduped[0]["title"] == "Shopee-1"
        assert deduped[1]["title"] == "Lazada-1"
        assert deduped[2]["title"] == "Shopee-2"
        assert deduped[3]["title"] == "Google-1"

    @pytest.mark.asyncio
    async def test_fallback_still_works_on_llm_failure(self):
        """curate_products should fallback to top-N when LLM fails."""
        from app.engine.multi_agent.subagents.search.workers import curate_products

        products = _make_products(20)
        state = {
            "deduped_products": products,
            "query": "test",
            "_event_bus_id": None,
        }

        with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=True)):
            with patch(
                "app.engine.multi_agent.subagents.search.curation.curate_with_llm",
                new_callable=AsyncMock,
                return_value=None,  # LLM failure
            ):
                result = await curate_products(state)

        assert len(result["curated_products"]) == 8  # Fallback top-8

    @pytest.mark.asyncio
    async def test_excel_in_aggregate_gets_all_products(self):
        """Excel generation in aggregate should still receive all deduped products."""
        from app.engine.multi_agent.subagents.search.workers import aggregate_results

        products = _make_products(10)
        state = {
            "all_products": products,
            "platforms_searched": ["shopee", "lazada"],
            "query": "test",
            "_event_bus_id": None,
        }

        excel_json = None

        def capture_excel(args):
            nonlocal excel_json
            excel_json = args.get("products_json", "")
            return "report.xlsx"

        mock_tool = MagicMock()
        mock_tool.invoke = capture_excel

        with patch("app.engine.tools.excel_report_tool.tool_generate_product_report", mock_tool):
            result = await aggregate_results(state)

        # Excel should get all 10 products (not just curated subset)
        assert excel_json is not None
        parsed = json.loads(excel_json)
        assert len(parsed) == 10
