"""
Unit tests for web search tools.

Tests tool_web_search with mocked search backends.
No real web requests are made.

Sprint 198: Serper is now primary, DuckDuckGo is fallback.
Tests must mock Serper path to avoid real API calls.
"""
import sys
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def mock_ddgs():
    """Mock duckduckgo_search/ddgs module for all tests."""
    mock_module = MagicMock()
    with patch.dict(sys.modules, {"ddgs": mock_module, "duckduckgo_search": mock_module}):
        yield mock_module


@pytest.fixture(autouse=True)
def disable_serper():
    """Force DuckDuckGo path by disabling Serper (Sprint 198).

    Without this, tool_web_search calls real Serper API if SERPER_API_KEY is set.
    """
    with patch(
        "app.engine.tools.serper_web_search.is_serper_available",
        return_value=False,
    ):
        yield


@pytest.fixture(autouse=True)
def disable_layered_live_backends():
    """Keep unit tests offline even when SearXNG/Brave/deep-fetch are enabled."""
    with patch(
        "app.engine.tools.web_search_tools._searxng_search_sync",
        return_value=[],
    ), patch(
        "app.engine.tools.web_search_tools._brave_search_sync",
        return_value=[],
    ), patch(
        "app.engine.tools.web_search_tools._augment_top_result_with_deep_fetch",
        side_effect=lambda results, _query: results,
    ), patch(
        "app.engine.tools.web_search_tools._merge_news_into_search",
        side_effect=lambda results, _query: results,
    ):
        yield


class TestWebSearchTool:
    """Test tool_web_search function."""

    def test_successful_search(self, mock_ddgs):
        """Test that search results are formatted correctly."""
        mock_results = [
            {"title": "COLREGs Rule 15", "body": "Crossing situation", "href": "https://example.com/1"},
            {"title": "Maritime Law", "body": "Overview", "href": "https://example.com/2"},
        ]
        mock_ddgs.DDGS.return_value.text.return_value = mock_results

        from app.engine.tools.web_search_tools import tool_web_search
        result = tool_web_search.invoke({"query": "COLREGs Rule 15"})

        assert "COLREGs Rule 15" in result
        assert "Crossing situation" in result

    def test_empty_results(self, mock_ddgs):
        """Test handling when no results found."""
        mock_ddgs.DDGS.return_value.text.return_value = []

        from app.engine.tools.web_search_tools import tool_web_search
        result = tool_web_search.invoke({"query": "nonexistent query"})

        assert "Không tìm thấy" in result

    def test_search_exception(self, mock_ddgs):
        """Test handling of search API errors."""
        mock_ddgs.DDGS.return_value.text.side_effect = Exception("Connection timeout")

        from app.engine.tools.web_search_tools import tool_web_search
        result = tool_web_search.invoke({"query": "test"})

        assert "Lỗi" in result

    def test_official_source_uses_site_restricted_branch(self):
        """Official source requests should not wait for generic news merging."""
        from app.engine.tools import web_search_tools as ws

        official_results = [
            {
                "title": "Introducing GPT-5.5 | OpenAI",
                "body": "OpenAI is releasing GPT-5.5, its latest model.",
                "href": "https://openai.com/index/introducing-gpt-5-5/",
            }
        ]

        with patch.object(ws, "_search_sync_with_timeout", return_value=official_results) as search_mock, patch.object(
            ws, "_searxng_search_sync", side_effect=AssertionError("generic search should be skipped")
        ), patch.object(
            ws, "_merge_news_into_search", side_effect=AssertionError("news merge should be skipped")
        ):
            result = ws.tool_web_search.invoke(
                {"query": "OpenAI official blog latest model announcement 2026"}
            )

        assert "Introducing GPT-5.5" in result
        assert "https://openai.com/index/introducing-gpt-5-5/" in result
        assert search_mock.call_args.args[0].startswith("site:openai.com/index")

    def test_official_latest_model_ranks_newer_gpt_release_first(self):
        """Latest official OpenAI model queries should prefer newer GPT releases."""
        from app.engine.tools import web_search_tools as ws

        official_results = [
            {
                "title": "Introducing GPT-5.2 - OpenAI",
                "body": "GPT-5.2 Thinking is the best model yet for professional use.",
                "href": "https://openai.com/index/introducing-gpt-5-2/",
            },
            {
                "title": "Introducing GPT-5.5 - OpenAI",
                "body": "We're releasing GPT-5.5, our smartest model yet.",
                "href": "https://openai.com/index/introducing-gpt-5-5/",
            },
            {
                "title": "GPT-5.5 Instant: smarter, clearer, and more personalized - OpenAI",
                "body": "Updates ChatGPT's default model.",
                "href": "https://openai.com/index/gpt-5-5-instant/",
            },
        ]

        with patch.object(ws, "_search_sync_with_timeout", return_value=official_results):
            ranked = ws._official_site_search_sync(
                "OpenAI official blog latest model announcement 2026",
                max_results=5,
            )

        assert ranked[0]["title"] == "Introducing GPT-5.5 - OpenAI"

    def test_searxng_default_candidates_include_local_docker_host(self):
        from app.engine.tools import web_search_tools as ws

        assert ws._searxng_base_url_candidates(None) == [
            "http://searxng:8080",
            "http://host.docker.internal:8080",
            "http://127.0.0.1:8080",
        ]

    def test_searxng_explicit_url_does_not_add_local_fallbacks(self):
        from app.engine.tools import web_search_tools as ws

        assert ws._searxng_base_url_candidates("http://search.internal:8888/") == [
            "http://search.internal:8888",
        ]

    def test_weather_search_keeps_organic_results_without_news_merge(self):
        from app.engine.tools import web_search_tools as ws

        weather_results = [
            {
                "title": "Thời tiết Hải Phòng hôm nay - AccuWeather",
                "body": "Hải Phòng hiện nhiều mây, nhiệt độ 30°C.",
                "href": "https://www.accuweather.com/vi/vn/haiphong/353511/weather-forecast/353511",
            }
        ]

        with patch.object(ws, "_searxng_search_sync", return_value=weather_results), patch.object(
            ws, "_merge_news_into_search", side_effect=AssertionError("weather search should not merge news")
        ):
            result = ws.tool_web_search.invoke({"query": "thời tiết Hải Phòng hôm nay"})

        assert "AccuWeather" in result
        assert "30°C" in result


class TestWebSearchRegistration:
    """Test tool registration."""

    @patch("app.engine.tools.web_search_tools.get_tool_registry")
    def test_init_registers_all_tools(self, mock_registry_fn):
        """init_web_search_tools should register all 4 search tools."""
        from app.engine.tools.web_search_tools import init_web_search_tools

        mock_registry = MagicMock()
        mock_registry_fn.return_value = mock_registry

        init_web_search_tools()

        # Sprint 102: Now registers 4 tools
        assert mock_registry.register.call_count == 4
        registered_names = [
            call[0][0].name for call in mock_registry.register.call_args_list
        ]
        assert "tool_web_search" in registered_names
        assert "tool_search_news" in registered_names
        assert "tool_search_legal" in registered_names
        assert "tool_search_maritime" in registered_names
