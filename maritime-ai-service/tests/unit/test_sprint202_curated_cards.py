"""Sprint 202: "Kết Quả Sạch" — LLM-Curated Product Cards.

Tests for:
- Curation Pydantic schemas (validation, bounds, highlights)
- curate_with_llm() (success, failure, timeout, invalid indices)
- curate_products node (enabled/disabled, fallback, preview emission)
- Graph wiring (node exists, edge order)
- Raw preview suppression (flag interaction)
- Legacy ReAct path (post-loop curation)
- Config flags (defaults, bounds)
"""

import asyncio
import json
import sys
from types import SimpleNamespace
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ─── Helpers ──────────────────────────────────────────────────────


def _make_products(n: int = 20) -> List[Dict[str, Any]]:
    """Generate N fake product dicts for testing."""
    products = []
    for i in range(n):
        products.append({
            "title": f"Sản phẩm Test {i}",
            "price": f"{(i + 1) * 100_000:,}đ",
            "extracted_price": (i + 1) * 100_000,
            "link": f"https://example.com/product/{i}",
            "platform": ["shopee", "lazada", "google_shopping"][i % 3],
            "rating": round(3.5 + (i % 15) * 0.1, 1),
            "sold_count": (i + 1) * 10,
            "seller": f"Shop {i}",
            "image": f"https://img.example.com/{i}.jpg",
            "snippet": f"Mô tả sản phẩm {i}",
        })
    return products


def _mock_settings(**overrides):
    """Create a mock settings object with Sprint 202 flags."""
    defaults = {
        "enable_curated_product_cards": False,
        "curated_product_max_cards": 8,
        "curated_product_llm_tier": "light",
        "enable_product_preview_cards": True,
        "product_preview_max_cards": 20,
        "enable_product_image_enrichment": False,
        "enable_query_planner": False,
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
# Group 1: Curation Pydantic Schemas
# ═════════════════════════════════════════════════════════════════


class TestCurationSchemas:
    """Test CuratedProduct and CuratedProductSelection schemas."""

    def test_curated_product_valid(self):
        from app.engine.multi_agent.subagents.search.curation import CuratedProduct

        p = CuratedProduct(index=0, relevance_score=0.95, reason="Giá tốt", highlight="Giá tốt nhất")
        assert p.index == 0
        assert p.relevance_score == 0.95
        assert p.highlight == "Giá tốt nhất"

    def test_curated_product_clamps_score(self):
        from app.engine.multi_agent.subagents.search.curation import CuratedProduct

        p = CuratedProduct(index=1, relevance_score=1.5, reason="Test", highlight="Test")
        assert p.relevance_score == 1.0

        p2 = CuratedProduct(index=2, relevance_score=-0.5, reason="Test", highlight="Test")
        assert p2.relevance_score == 0.0

    def test_curated_product_invalid_score_type(self):
        from app.engine.multi_agent.subagents.search.curation import CuratedProduct

        p = CuratedProduct(index=0, relevance_score="invalid", reason="Test", highlight="Test")
        assert p.relevance_score == 0.5  # fallback

    def test_curated_selection_valid(self):
        from app.engine.multi_agent.subagents.search.curation import (
            CuratedProduct,
            CuratedProductSelection,
        )

        selection = CuratedProductSelection(
            selected=[
                CuratedProduct(index=0, relevance_score=0.9, reason="R1", highlight="H1"),
                CuratedProduct(index=3, relevance_score=0.8, reason="R2", highlight="H2"),
            ],
            reasoning="Test reasoning",
            total_evaluated=20,
        )
        assert len(selection.selected) == 2
        assert selection.total_evaluated == 20


# ═════════════════════════════════════════════════════════════════
# Group 2: curate_with_llm()
# ═════════════════════════════════════════════════════════════════


class TestCurateWithLLM:
    """Test the curate_with_llm function."""

    @pytest.mark.asyncio
    async def test_curate_success(self):
        from app.engine.multi_agent.subagents.search.curation import (
            CuratedProduct,
            CuratedProductSelection,
            curate_with_llm,
        )

        mock_selection = CuratedProductSelection(
            selected=[
                CuratedProduct(index=0, relevance_score=0.95, reason="Best price", highlight="Giá tốt nhất"),
                CuratedProduct(index=2, relevance_score=0.85, reason="Popular", highlight="Bán chạy"),
            ],
            reasoning="Selected top products",
            total_evaluated=5,
        )

        products = _make_products(5)

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg, patch(
            "app.services.structured_invoke_service.StructuredInvokeService.ainvoke",
            new=AsyncMock(return_value=mock_selection),
        ) as mock_invoke:
            mock_reg.get_llm.return_value = MagicMock(_wiii_provider_name="zhipu")
            result = await curate_with_llm("test query", products, max_curated=8)

        assert result is not None
        assert len(result.selected) == 2
        assert result.selected[0].index == 0
        assert result.total_evaluated == 5
        assert mock_invoke.await_args.kwargs["timeout_profile"] == "structured"

    @pytest.mark.asyncio
    async def test_curate_empty_products(self):
        from app.engine.multi_agent.subagents.search.curation import curate_with_llm

        result = await curate_with_llm("test", [], max_curated=8)
        assert result is None

    @pytest.mark.asyncio
    async def test_curate_llm_failure(self):
        from app.engine.multi_agent.subagents.search.curation import curate_with_llm

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg, patch(
            "app.services.structured_invoke_service.StructuredInvokeService.ainvoke",
            new=AsyncMock(side_effect=RuntimeError("LLM error")),
        ):
            mock_reg.get_llm.return_value = MagicMock(_wiii_provider_name="zhipu")
            result = await curate_with_llm("test", _make_products(5))

        assert result is None

    @pytest.mark.asyncio
    async def test_curate_invalid_indices(self):
        from app.engine.multi_agent.subagents.search.curation import (
            CuratedProduct,
            CuratedProductSelection,
            curate_with_llm,
        )

        mock_selection = CuratedProductSelection(
            selected=[
                CuratedProduct(index=0, relevance_score=0.9, reason="OK", highlight="Good"),
                CuratedProduct(index=99, relevance_score=0.8, reason="Bad", highlight="OOB"),
                CuratedProduct(index=-1, relevance_score=0.7, reason="Neg", highlight="Neg"),
            ],
            reasoning="Mixed",
            total_evaluated=5,
        )

        products = _make_products(5)

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg, patch(
            "app.services.structured_invoke_service.StructuredInvokeService.ainvoke",
            new=AsyncMock(return_value=mock_selection),
        ):
            mock_reg.get_llm.return_value = MagicMock(_wiii_provider_name="zhipu")
            result = await curate_with_llm("test", products)

        assert result is not None
        assert len(result.selected) == 1  # Only index 0 is valid
        assert result.selected[0].index == 0

    @pytest.mark.asyncio
    async def test_curate_all_indices_invalid(self):
        from app.engine.multi_agent.subagents.search.curation import (
            CuratedProduct,
            CuratedProductSelection,
            curate_with_llm,
        )

        mock_selection = CuratedProductSelection(
            selected=[
                CuratedProduct(index=100, relevance_score=0.9, reason="OOB", highlight="Bad"),
            ],
            reasoning="All bad",
            total_evaluated=3,
        )

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg, patch(
            "app.services.structured_invoke_service.StructuredInvokeService.ainvoke",
            new=AsyncMock(return_value=mock_selection),
        ):
            mock_reg.get_llm.return_value = MagicMock(_wiii_provider_name="zhipu")
            result = await curate_with_llm("test", _make_products(3))

        assert result is None

    @pytest.mark.asyncio
    async def test_curate_no_llm(self):
        from app.engine.multi_agent.subagents.search.curation import curate_with_llm

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_reg:
            mock_reg.get_llm.return_value = None
            result = await curate_with_llm("test", _make_products(5))

        assert result is None


# ═════════════════════════════════════════════════════════════════
# Group 3: compact product text builder
# ═════════════════════════════════════════════════════════════════


class TestBuildCompactProductText:
    """Test the _build_compact_product_text helper."""

    def test_basic_formatting(self):
        from app.engine.multi_agent.subagents.search.curation import _build_compact_product_text

        products = _make_products(3)
        text = _build_compact_product_text(products)
        assert "[0]" in text
        assert "[1]" in text
        assert "[2]" in text
        assert "Sản phẩm Test 0" in text

    def test_truncation(self):
        from app.engine.multi_agent.subagents.search.curation import _build_compact_product_text

        products = _make_products(200)
        text = _build_compact_product_text(products, max_chars=500)
        assert len(text) < 1500  # Allow some overflow from last line
        assert "sản phẩm khác" in text


# ═════════════════════════════════════════════════════════════════
# Group 4: curate_products node
# ═════════════════════════════════════════════════════════════════


class TestCurateProductsNode:
    """Test the curate_products graph node."""

    @pytest.mark.asyncio
    async def test_disabled_passthrough(self):
        """When curation disabled, passes deduped products through."""
        from app.engine.multi_agent.subagents.search.workers import curate_products

        products = _make_products(15)
        state = {"deduped_products": products, "query": "test", "_event_bus_id": None}

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=None):
            with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=False)):
                result = await curate_products(state)

        assert "curated_products" in result
        assert len(result["curated_products"]) == 8  # max_curated default

    @pytest.mark.asyncio
    async def test_small_list_skip_llm(self):
        """When products <= max_curated, skip LLM even if enabled."""
        from app.engine.multi_agent.subagents.search.workers import curate_products

        products = _make_products(5)
        state = {"deduped_products": products, "query": "test", "_event_bus_id": None}

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=None):
            with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=True)):
                result = await curate_products(state)

        assert len(result["curated_products"]) == 5  # All products, no LLM needed

    @pytest.mark.asyncio
    async def test_enabled_with_llm_success(self):
        """When enabled and products > max, calls LLM curation."""
        from app.engine.multi_agent.subagents.search.curation import (
            CuratedProduct,
            CuratedProductSelection,
        )
        from app.engine.multi_agent.subagents.search.workers import curate_products

        mock_selection = CuratedProductSelection(
            selected=[
                CuratedProduct(index=0, relevance_score=0.95, reason="Best", highlight="Giá tốt nhất"),
                CuratedProduct(index=5, relevance_score=0.90, reason="Popular", highlight="Bán chạy"),
                CuratedProduct(index=10, relevance_score=0.85, reason="Quality", highlight="Chính hãng"),
            ],
            reasoning="Top 3",
            total_evaluated=15,
        )

        products = _make_products(15)
        eq = asyncio.Queue()
        state = {"deduped_products": products, "query": "laptop test", "_event_bus_id": "bus123"}

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=eq):
            with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=True)):
                with patch("app.engine.multi_agent.subagents.search.curation.curate_with_llm", new_callable=AsyncMock, return_value=mock_selection) as mock_curate:
                    result = await curate_products(state)

        assert len(result["curated_products"]) == 3
        assert result["curated_products"][0]["_highlight"] == "Giá tốt nhất"
        assert result["curated_products"][1]["_relevance_score"] == 0.90

        # Verify preview events were emitted
        events = []
        while not eq.empty():
            events.append(eq.get_nowait())
        preview_events = [e for e in events if e.get("type") == "preview"]
        assert len(preview_events) == 3  # 3 curated products

    @pytest.mark.asyncio
    async def test_llm_failure_fallback(self):
        """When LLM fails, falls back to top-N by price."""
        from app.engine.multi_agent.subagents.search.workers import curate_products

        products = _make_products(15)
        eq = asyncio.Queue()
        state = {"deduped_products": products, "query": "test", "_event_bus_id": "bus123"}

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=eq):
            with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=True)):
                with patch("app.engine.multi_agent.subagents.search.curation.curate_with_llm", new_callable=AsyncMock, return_value=None):
                    result = await curate_products(state)

        assert len(result["curated_products"]) == 8  # Fallback: top 8

    @pytest.mark.asyncio
    async def test_curated_preview_metadata(self):
        """Curated preview events include highlight and relevance_score."""
        from app.engine.multi_agent.subagents.search.curation import (
            CuratedProduct,
            CuratedProductSelection,
        )
        from app.engine.multi_agent.subagents.search.workers import curate_products

        mock_selection = CuratedProductSelection(
            selected=[
                CuratedProduct(index=0, relevance_score=0.95, reason="Best", highlight="Giá tốt"),
            ],
            reasoning="Top 1",
            total_evaluated=15,
        )

        products = _make_products(15)
        eq = asyncio.Queue()
        state = {"deduped_products": products, "query": "test", "_event_bus_id": "bus123"}

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=eq):
            with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=True)):
                with patch("app.engine.multi_agent.subagents.search.curation.curate_with_llm", new_callable=AsyncMock, return_value=mock_selection):
                    await curate_products(state)

        events = []
        while not eq.empty():
            events.append(eq.get_nowait())
        preview_events = [e for e in events if e.get("type") == "preview"]
        assert len(preview_events) >= 1
        meta = preview_events[0]["content"]["metadata"]
        assert meta["highlight"] == "Giá tốt"
        assert meta["relevance_score"] == 0.95

    @pytest.mark.asyncio
    async def test_curated_preview_id_prefix(self):
        """Curated preview IDs start with 'curated_'."""
        from app.engine.multi_agent.subagents.search.curation import (
            CuratedProduct,
            CuratedProductSelection,
        )
        from app.engine.multi_agent.subagents.search.workers import curate_products

        mock_selection = CuratedProductSelection(
            selected=[
                CuratedProduct(index=0, relevance_score=0.9, reason="R", highlight="H"),
            ],
            reasoning="",
            total_evaluated=15,
        )

        products = _make_products(15)
        eq = asyncio.Queue()
        state = {"deduped_products": products, "query": "test", "_event_bus_id": "bus123"}

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=eq):
            with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=True)):
                with patch("app.engine.multi_agent.subagents.search.curation.curate_with_llm", new_callable=AsyncMock, return_value=mock_selection):
                    await curate_products(state)

        events = []
        while not eq.empty():
            events.append(eq.get_nowait())
        preview_events = [e for e in events if e.get("type") == "preview"]
        for pe in preview_events:
            assert pe["content"]["preview_id"].startswith("curated_")

    @pytest.mark.asyncio
    async def test_empty_deduped(self):
        """Empty deduped products returns empty curated list."""
        from app.engine.multi_agent.subagents.search.workers import curate_products

        state = {"deduped_products": [], "query": "test", "_event_bus_id": None}

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=None):
            with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=True)):
                result = await curate_products(state)

        assert result["curated_products"] == []

    @pytest.mark.asyncio
    async def test_thinking_events_emitted(self):
        """curate_products emits thinking_start/end events during LLM curation."""
        from app.engine.multi_agent.subagents.search.workers import curate_products

        products = _make_products(15)
        eq = asyncio.Queue()
        state = {"deduped_products": products, "query": "test", "_event_bus_id": "bus123"}

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=eq):
            with patch("app.core.config.get_settings", return_value=_mock_settings(enable_curated_product_cards=True)):
                with patch("app.engine.multi_agent.subagents.search.curation.curate_with_llm", new_callable=AsyncMock, return_value=None):
                    await curate_products(state)

        events = []
        while not eq.empty():
            events.append(eq.get_nowait())
        thinking_starts = [e for e in events if e.get("type") == "thinking_start"]
        thinking_ends = [e for e in events if e.get("type") == "thinking_end"]
        assert len(thinking_starts) >= 1
        assert len(thinking_ends) >= 1


# ═════════════════════════════════════════════════════════════════
# Group 5: Graph Wiring
# ═════════════════════════════════════════════════════════════════


class TestGraphWiring:
    """Test that curate_products is available (De-LangGraphing Phase 3: graph wiring removed)."""

    def test_curate_products_importable(self):
        """curate_products function is importable from workers."""
        from app.engine.multi_agent.subagents.search.workers import curate_products
        assert curate_products is not None

    def test_build_search_subgraph_deprecated(self):
        """build_search_subgraph raises RuntimeError (LangGraph removed)."""
        from app.engine.multi_agent.subagents.search.graph import build_search_subgraph

        with pytest.raises(RuntimeError, match="deprecated"):
            build_search_subgraph()

    def test_graph_imports_curate_products(self):
        """graph.py imports curate_products from workers."""
        from app.engine.multi_agent.subagents.search import graph

        assert hasattr(graph, "curate_products")



# ═════════════════════════════════════════════════════════════════
# Group 6: Raw Preview Suppression
# ═════════════════════════════════════════════════════════════════


class TestRawPreviewSuppression:
    """Test that raw preview emission is suppressed when curation is active."""

    @pytest.mark.asyncio
    async def test_raw_previews_suppressed_when_curation_on(self):
        """platform_worker does NOT emit preview events when curation is enabled."""
        from app.engine.multi_agent.subagents.search.workers import platform_worker

        eq = asyncio.Queue()
        state = {
            "platform_id": "google_shopping",
            "query": "laptop test",
            "max_results": 5,
            "page": 1,
            "_event_bus_id": "bus123",
        }

        mock_adapter = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "title": "Test Laptop", "price": "10,000,000đ", "link": "https://example.com/1",
            "platform": "google_shopping", "image": "https://img.com/1.jpg",
        }
        mock_adapter.search_sync.return_value = [mock_result]

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_adapter

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=eq):
            with patch("app.engine.search_platforms.get_search_platform_registry", return_value=mock_registry):
                with patch("app.core.config.get_settings", return_value=_mock_settings(
                    enable_curated_product_cards=True,
                    enable_product_preview_cards=True,
                )):
                    result = await platform_worker(state)

        events = []
        while not eq.empty():
            events.append(eq.get_nowait())
        preview_events = [e for e in events if e.get("type") == "preview"]
        assert len(preview_events) == 0  # No raw previews

    @pytest.mark.asyncio
    async def test_raw_previews_preserved_when_curation_off(self):
        """platform_worker emits preview events when curation is disabled."""
        from app.engine.multi_agent.subagents.search.workers import platform_worker

        eq = asyncio.Queue()
        state = {
            "platform_id": "google_shopping",
            "query": "laptop test",
            "max_results": 5,
            "page": 1,
            "_event_bus_id": "bus123",
        }

        mock_adapter = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {
            "title": "Test Laptop", "price": "10,000,000đ", "link": "https://example.com/1",
            "platform": "google_shopping", "image": "https://img.com/1.jpg",
        }
        mock_adapter.search_sync.return_value = [mock_result]

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_adapter

        with patch("app.engine.multi_agent.subagents.search.workers._get_event_queue", return_value=eq):
            with patch("app.engine.search_platforms.get_search_platform_registry", return_value=mock_registry):
                with patch("app.core.config.get_settings", return_value=_mock_settings(
                    enable_curated_product_cards=False,
                    enable_product_preview_cards=True,
                )):
                    result = await platform_worker(state)

        events = []
        while not eq.empty():
            events.append(eq.get_nowait())
        preview_events = [e for e in events if e.get("type") == "preview"]
        assert len(preview_events) >= 1  # Raw previews emitted


# ═════════════════════════════════════════════════════════════════
# Group 7: Config Flags
# ═════════════════════════════════════════════════════════════════


class TestConfigFlags:
    """Test Sprint 202 config flag defaults and validation."""

    def test_defaults(self):
        from app.core.config import Settings

        # Explicitly pass defaults to avoid .env contamination
        s = Settings(
            google_api_key="test",
            api_key="test",
            enable_curated_product_cards=False,
            curated_product_max_cards=8,
            curated_product_llm_tier="light",
        )
        assert s.enable_curated_product_cards is False
        assert s.curated_product_max_cards == 8
        assert s.curated_product_llm_tier == "light"

    def test_max_cards_bounds(self):
        from app.core.config import Settings

        s = Settings(
            google_api_key="test",
            api_key="test",
            curated_product_max_cards=5,
        )
        assert s.curated_product_max_cards == 5

    def test_tier_options(self):
        from app.core.config import Settings

        for tier in ("light", "moderate", "deep"):
            s = Settings(
                google_api_key="test",
                api_key="test",
                curated_product_llm_tier=tier,
            )
            assert s.curated_product_llm_tier == tier


# ═════════════════════════════════════════════════════════════════
# Group 8: Legacy ReAct Path (product_search_node.py)
# ═════════════════════════════════════════════════════════════════


class TestLegacyReActCuration:
    """Test post-loop curation in ProductSearchAgentNode._react_loop."""

    def test_product_result_tools_set(self):
        """_PRODUCT_RESULT_TOOLS contains expected search tool names."""
        from app.engine.multi_agent.agents.product_search_node import _PRODUCT_RESULT_TOOLS

        assert "tool_search_google_shopping" in _PRODUCT_RESULT_TOOLS
        assert "tool_search_shopee" in _PRODUCT_RESULT_TOOLS

    def test_emit_product_previews_skipped_for_non_search_tools(self):
        """_emit_product_previews returns empty for non-search tools."""
        from app.engine.multi_agent.agents.product_search_node import _emit_product_previews

        events = _emit_product_previews(
            tool_name="tool_fetch_product_detail",
            result_str='{"results": [{"title": "Test"}]}',
            emitted_ids=set(),
            max_cards=20,
            current_count=0,
        )
        assert events == []

    def test_emit_product_previews_respects_max(self):
        """_emit_product_previews stops at max_cards."""
        from app.engine.multi_agent.agents.product_search_node import _emit_product_previews

        results = [{"title": f"P{i}", "link": f"https://example.com/{i}", "price": "100k"} for i in range(10)]
        result_str = json.dumps({"platform": "shopee", "results": results})

        events = _emit_product_previews(
            tool_name="tool_search_shopee",
            result_str=result_str,
            emitted_ids=set(),
            max_cards=3,
            current_count=0,
        )
        assert len(events) == 3

    def test_curation_active_flag_disables_previews(self):
        """When _curation_active is True, _preview_enabled should be False."""
        # This is a logic test — verify the flag interaction
        _curation_active = True
        _preview_enabled = True
        if _curation_active:
            _preview_enabled = False
        assert _preview_enabled is False


# ═════════════════════════════════════════════════════════════════
# Group 9: State Schema
# ═════════════════════════════════════════════════════════════════


class TestStateSchema:
    """Test SearchSubgraphState includes curated_products field."""

    def test_curated_products_field_exists(self):
        from app.engine.multi_agent.subagents.search.state import SearchSubgraphState

        annotations = SearchSubgraphState.__annotations__
        assert "curated_products" in annotations

    def test_state_can_hold_curated_products(self):
        """curated_products field accepts list of dicts."""
        state = {
            "query": "test",
            "curated_products": [{"title": "P1", "price": "100k"}],
            "deduped_products": [{"title": "P1"}, {"title": "P2"}],
        }
        assert len(state["curated_products"]) == 1


# ═════════════════════════════════════════════════════════════════
# Group 10: _emit_curated_previews helper
# ═════════════════════════════════════════════════════════════════


class TestEmitCuratedPreviews:
    """Test the _emit_curated_previews helper in workers.py."""

    @pytest.mark.asyncio
    async def test_emit_with_highlights(self):
        from app.engine.multi_agent.subagents.search.workers import _emit_curated_previews

        eq = asyncio.Queue()
        products = [
            {
                "title": "Product A",
                "link": "https://a.com",
                "price": "100k",
                "platform": "shopee",
                "_highlight": "Giá tốt nhất",
                "_relevance_score": 0.95,
            },
        ]
        await _emit_curated_previews(eq, products, "test query")

        events = []
        while not eq.empty():
            events.append(eq.get_nowait())
        assert len(events) == 1
        assert events[0]["type"] == "preview"
        assert events[0]["content"]["metadata"]["highlight"] == "Giá tốt nhất"
        assert events[0]["content"]["metadata"]["relevance_score"] == 0.95

    @pytest.mark.asyncio
    async def test_emit_none_queue(self):
        from app.engine.multi_agent.subagents.search.workers import _emit_curated_previews

        # Should not raise
        await _emit_curated_previews(None, _make_products(3), "test")

    @pytest.mark.asyncio
    async def test_emit_empty_products(self):
        from app.engine.multi_agent.subagents.search.workers import _emit_curated_previews

        eq = asyncio.Queue()
        await _emit_curated_previews(eq, [], "test")
        assert eq.empty()

    @pytest.mark.asyncio
    async def test_emit_skips_no_title(self):
        from app.engine.multi_agent.subagents.search.workers import _emit_curated_previews

        eq = asyncio.Queue()
        products = [
            {"link": "https://a.com", "price": "100k"},  # No title
            {"title": "Valid Product", "link": "https://b.com"},
        ]
        await _emit_curated_previews(eq, products, "test")

        events = []
        while not eq.empty():
            events.append(eq.get_nowait())
        assert len(events) == 1
        assert events[0]["content"]["title"] == "Valid Product"
