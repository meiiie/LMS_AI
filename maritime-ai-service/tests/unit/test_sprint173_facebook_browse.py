"""
Sprint 173: "Tự Khám Phá" — Autonomous Facebook Browsing Tests.

Tests verify:
1. Facebook topic queries exist and target site:facebook.com
2. _search_facebook() — Serper integration (success, no key, error, empty)
3. BrowsingItem mapping — platform="facebook", URL/title/summary correct
4. Topic routing — facebook topic calls _search_facebook(), not _invoke_tool()
5. Heartbeat integration — "facebook" in topic choices
6. Safety — Facebook URLs validated, content sanitized
7. Integration — browse_feed(topic="facebook") end-to-end

22 tests across 8 groups.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ============================================================================
# Helpers
# ============================================================================

def _make_settings(**overrides):
    """Create a mock settings object with Living Agent defaults."""
    s = MagicMock()
    s.living_agent_enable_social_browse = True
    s.living_agent_require_human_approval = False
    s.living_agent_enable_skill_building = True
    s.living_agent_enable_journal = True
    s.living_agent_heartbeat_interval = 1800
    s.living_agent_max_actions_per_heartbeat = 3
    s.living_agent_max_daily_cycles = 48
    s.living_agent_active_hours_start = 8
    s.living_agent_active_hours_end = 23
    s.serper_api_key = "test-serper-key"
    s.enable_living_agent = True
    # Flags added in later sprints (default off in tests)
    s.living_agent_enable_weather = False
    s.living_agent_enable_briefing = False
    s.living_agent_enable_skill_learning = False
    s.living_agent_enable_proactive_messaging = False
    for k, v in overrides.items():
        setattr(s, k, v)
    return s


def _make_serper_response(results=None):
    """Create a mock Serper API response."""
    if results is None:
        results = [
            {
                "title": "Hàng Hải Việt Nam - Maritime Group",
                "link": "https://www.facebook.com/hanghaiVN",
                "snippet": "Cộng đồng hàng hải Việt Nam chia sẻ tin tức",
            },
            {
                "title": "AI Technology Vietnam",
                "link": "https://www.facebook.com/AITechVN",
                "snippet": "Tin tức công nghệ AI tại Việt Nam",
            },
            {
                "title": "Maritime Shipping News",
                "link": "https://www.facebook.com/shippingnews",
                "snippet": "Latest maritime shipping updates 2026",
            },
        ]
    return {"organic": results}


def _mock_httpx_client(response_data, raise_for_status_error=None):
    """Create a mock httpx.AsyncClient context manager."""
    mock_resp = MagicMock()
    mock_resp.json.return_value = response_data
    if raise_for_status_error:
        mock_resp.raise_for_status.side_effect = raise_for_status_error
    else:
        mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post.return_value = mock_resp
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# Patch target for settings (lazy import inside functions)
_SETTINGS_PATCH = "app.core.config.settings"


# ============================================================================
# Group 1: Topic Queries (3 tests)
# ============================================================================

class TestFacebookTopicQueries:
    """Verify facebook topic exists and queries target site:facebook.com."""

    def test_facebook_key_exists_in_topic_queries(self):
        """_TOPIC_QUERIES contains 'facebook' key."""
        from app.engine.living_agent.social_browser import _TOPIC_QUERIES
        assert "facebook" in _TOPIC_QUERIES

    def test_facebook_queries_contain_site_restriction(self):
        """All facebook queries contain 'site:facebook.com'."""
        from app.engine.living_agent.social_browser import _TOPIC_QUERIES
        for query in _TOPIC_QUERIES["facebook"]:
            assert "site:facebook.com" in query, f"Missing site restriction: {query}"

    def test_facebook_queries_non_empty(self):
        """Facebook topic has at least 3 query variants."""
        from app.engine.living_agent.social_browser import _TOPIC_QUERIES
        assert len(_TOPIC_QUERIES["facebook"]) >= 3


# ============================================================================
# Group 2: _search_facebook() (5 tests)
# ============================================================================

class TestSearchFacebook:
    """Verify _search_facebook() Serper integration."""

    @pytest.mark.asyncio
    async def test_search_facebook_success(self):
        """Successful Serper response returns BrowsingItems."""
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()
        mock_client = _mock_httpx_client(_make_serper_response())

        with patch(_SETTINGS_PATCH, _make_settings()):
            with patch("httpx.AsyncClient", return_value=mock_client):
                items = await browser._search_facebook(
                    "site:facebook.com maritime", 5
                )

        assert len(items) == 3
        assert items[0].platform == "facebook"
        assert items[0].title == "Hàng Hải Việt Nam - Maritime Group"
        assert items[0].url == "https://www.facebook.com/hanghaiVN"

    @pytest.mark.asyncio
    async def test_search_facebook_no_api_key(self):
        """Returns empty list when serper_api_key is not set."""
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()

        with patch(_SETTINGS_PATCH, _make_settings(serper_api_key="")):
            items = await browser._search_facebook("site:facebook.com test", 5)

        assert items == []

    @pytest.mark.asyncio
    async def test_search_facebook_api_error(self):
        """Raises exception on Serper API error (caller catches it)."""
        import httpx
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()
        error = httpx.HTTPStatusError(
            "500 Server Error", request=MagicMock(), response=MagicMock()
        )
        mock_client = _mock_httpx_client({}, raise_for_status_error=error)

        with patch(_SETTINGS_PATCH, _make_settings()):
            with patch("httpx.AsyncClient", return_value=mock_client):
                with pytest.raises(httpx.HTTPStatusError):
                    await browser._search_facebook("site:facebook.com test", 5)

    @pytest.mark.asyncio
    async def test_search_facebook_empty_results(self):
        """Returns empty list when Serper returns no organic results."""
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()
        mock_client = _mock_httpx_client({"organic": []})

        with patch(_SETTINGS_PATCH, _make_settings()):
            with patch("httpx.AsyncClient", return_value=mock_client):
                items = await browser._search_facebook("site:facebook.com test", 5)

        assert items == []

    @pytest.mark.asyncio
    async def test_search_facebook_adds_site_prefix(self):
        """Adds site:facebook.com if not already in query."""
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()
        mock_client = _mock_httpx_client({"organic": []})

        with patch(_SETTINGS_PATCH, _make_settings()):
            with patch("httpx.AsyncClient", return_value=mock_client):
                await browser._search_facebook("maritime news", 5)

        # Verify the query sent to Serper includes site:facebook.com
        call_args = mock_client.post.call_args
        sent_json = call_args.kwargs.get("json") or call_args[1].get("json")
        assert "site:facebook.com" in sent_json["q"]


# ============================================================================
# Group 3: BrowsingItem Mapping (2 tests)
# ============================================================================

class TestBrowsingItemMapping:
    """Verify Facebook results map correctly to BrowsingItem."""

    @pytest.mark.asyncio
    async def test_platform_is_facebook(self):
        """All items from _search_facebook have platform='facebook'."""
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()
        mock_client = _mock_httpx_client(_make_serper_response())

        with patch(_SETTINGS_PATCH, _make_settings()):
            with patch("httpx.AsyncClient", return_value=mock_client):
                items = await browser._search_facebook("site:facebook.com test", 5)

        for item in items:
            assert item.platform == "facebook"

    @pytest.mark.asyncio
    async def test_url_title_summary_mapped(self):
        """URL, title, and summary are correctly extracted from Serper results."""
        from app.engine.living_agent.social_browser import SocialBrowser

        single_result = [{"title": "Test Page", "link": "https://www.facebook.com/testpage", "snippet": "Test snippet"}]
        mock_client = _mock_httpx_client({"organic": single_result})

        browser = SocialBrowser()
        with patch(_SETTINGS_PATCH, _make_settings()):
            with patch("httpx.AsyncClient", return_value=mock_client):
                items = await browser._search_facebook("site:facebook.com test", 5)

        assert len(items) == 1
        assert items[0].url == "https://www.facebook.com/testpage"
        assert items[0].title == "Test Page"
        assert items[0].summary == "Test snippet"


# ============================================================================
# Group 4: Topic Routing (3 tests)
# ============================================================================

class TestTopicRouting:
    """Verify facebook topic routes to _search_facebook, not _invoke_tool."""

    @pytest.mark.asyncio
    async def test_facebook_topic_calls_search_facebook(self):
        """When topic='facebook', _search_web calls _search_facebook."""
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        browser._current_topic = "facebook"

        fb_items = [BrowsingItem(platform="facebook", title="Test", url="https://facebook.com/test")]

        with patch.object(browser, "_search_facebook", new_callable=AsyncMock, return_value=fb_items) as mock_fb:
            with patch.object(browser, "_invoke_tool", new_callable=AsyncMock) as mock_tool:
                with patch("app.engine.living_agent.safety.validate_url", return_value=True):
                    with patch("app.engine.living_agent.safety.sanitize_content", side_effect=lambda x: x):
                        items = await browser._search_web("site:facebook.com test", 5)

        mock_fb.assert_called_once_with("site:facebook.com test", 5)
        mock_tool.assert_not_called()
        assert len(items) == 1
        assert items[0].platform == "facebook"

    @pytest.mark.asyncio
    async def test_non_facebook_topic_uses_invoke_tool(self):
        """When topic='news', _search_web uses _invoke_tool, not _search_facebook."""
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()
        browser._current_topic = "news"

        with patch.object(browser, "_search_facebook", new_callable=AsyncMock) as mock_fb:
            with patch.object(browser, "_invoke_tool", new_callable=AsyncMock, return_value="**Title**\nBody\nURL: https://example.com\n\n---\n\n"):
                with patch("app.engine.living_agent.safety.validate_url", return_value=True):
                    with patch("app.engine.living_agent.safety.sanitize_content", side_effect=lambda x: x):
                        await browser._search_web("AI news", 5)

        mock_fb.assert_not_called()

    @pytest.mark.asyncio
    async def test_facebook_fallback_to_tool_on_empty(self):
        """When _search_facebook returns empty, falls through to _invoke_tool."""
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()
        browser._current_topic = "facebook"

        with patch.object(browser, "_search_facebook", new_callable=AsyncMock, return_value=[]) as mock_fb:
            with patch.object(browser, "_invoke_tool", new_callable=AsyncMock, return_value="") as mock_tool:
                with patch.object(browser, "_fallback_search", new_callable=AsyncMock, return_value=[]):
                    with patch("app.engine.living_agent.safety.validate_url", return_value=True):
                        with patch("app.engine.living_agent.safety.sanitize_content", side_effect=lambda x: x):
                            items = await browser._search_web("site:facebook.com test", 5)

        mock_fb.assert_called_once()
        mock_tool.assert_called_once()
        assert items == []


# ============================================================================
# Group 5: Heartbeat Integration (3 tests)
# ============================================================================

class TestHeartbeatFacebookIntegration:
    """Verify heartbeat includes 'facebook' in browse targets."""

    @pytest.mark.asyncio
    async def test_browse_target_is_auto(self):
        """_plan_actions BROWSE_SOCIAL uses target='auto' (Phase 3A smart topic)."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import ActionType

        scheduler = HeartbeatScheduler()
        settings = _make_settings(
            living_agent_enable_social_browse=True,
            living_agent_enable_skill_building=False,
            living_agent_enable_journal=False,
            living_agent_max_actions_per_heartbeat=5,
        )

        with patch(_SETTINGS_PATCH, settings):
            actions = await scheduler._plan_actions("curious", 0.8)
            browse_actions = [a for a in actions if a.action_type == ActionType.BROWSE_SOCIAL]
            assert len(browse_actions) >= 1
            # Phase 3A: target is "auto" (smart topic selection at execution time)
            assert browse_actions[0].target == "auto"


    @pytest.mark.asyncio
    async def test_plan_actions_browse_when_energy_high(self):
        """With energy > 0.5 and social_browse enabled, BROWSE_SOCIAL is planned."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import ActionType

        scheduler = HeartbeatScheduler()
        settings = _make_settings(
            living_agent_enable_social_browse=True,
            living_agent_enable_skill_building=False,
            living_agent_enable_journal=False,
            living_agent_max_actions_per_heartbeat=5,
        )

        with patch(_SETTINGS_PATCH, settings):
            actions = await scheduler._plan_actions("curious", 0.8)

        action_types = [a.action_type for a in actions]
        assert ActionType.BROWSE_SOCIAL in action_types


# ============================================================================
# Group 6: Safety (2 tests)
# ============================================================================

class TestFacebookSafety:
    """Verify safety filters apply to Facebook results."""

    @pytest.mark.asyncio
    async def test_unsafe_facebook_url_filtered(self):
        """Facebook items with unsafe URLs are filtered out in _search_web."""
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        browser._current_topic = "facebook"

        fb_items = [
            BrowsingItem(platform="facebook", title="Good", url="https://www.facebook.com/page1"),
            BrowsingItem(platform="facebook", title="Bad", url="http://127.0.0.1/evil"),
        ]

        with patch.object(browser, "_search_facebook", new_callable=AsyncMock, return_value=fb_items):
            with patch("app.engine.living_agent.safety.validate_url", side_effect=lambda u: "facebook.com" in u):
                with patch("app.engine.living_agent.safety.sanitize_content", side_effect=lambda x: x):
                    items = await browser._search_web("site:facebook.com test", 5)

        assert len(items) == 1
        assert items[0].title == "Good"

    @pytest.mark.asyncio
    async def test_facebook_content_sanitized(self):
        """Facebook item summaries pass through sanitize_content."""
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        browser._current_topic = "facebook"

        fb_items = [
            BrowsingItem(
                platform="facebook",
                title="Test",
                url="https://www.facebook.com/test",
                summary="<script>alert('xss')</script>Clean text",
            ),
        ]

        with patch.object(browser, "_search_facebook", new_callable=AsyncMock, return_value=fb_items):
            with patch("app.engine.living_agent.safety.validate_url", return_value=True):
                with patch("app.engine.living_agent.safety.sanitize_content", return_value="Clean text"):
                    items = await browser._search_web("site:facebook.com test", 5)

        assert len(items) == 1
        assert items[0].summary == "Clean text"


# ============================================================================
# Group 7: Integration — browse_feed (2 tests)
# ============================================================================

class TestBrowseFeedFacebook:
    """End-to-end browse_feed with topic='facebook'."""

    @pytest.mark.asyncio
    async def test_browse_feed_facebook_returns_items(self):
        """browse_feed(topic='facebook') returns Facebook items."""
        from app.engine.living_agent.social_browser import SocialBrowser
        from app.engine.living_agent.models import BrowsingItem

        browser = SocialBrowser()
        fb_items = [
            BrowsingItem(platform="facebook", title="FB Post", url="https://facebook.com/post1", relevance_score=0.8),
            BrowsingItem(platform="facebook", title="FB Post 2", url="https://facebook.com/post2", relevance_score=0.5),
        ]

        with patch(_SETTINGS_PATCH, _make_settings()):
            with patch.object(browser, "_search_web", new_callable=AsyncMock, return_value=fb_items):
                with patch.object(browser, "_save_browsing_log"):
                    results = await browser.browse_feed(topic="facebook", max_items=5)

        assert len(results) == 2
        assert results[0].platform == "facebook"
        assert results[0].relevance_score >= results[1].relevance_score

    @pytest.mark.asyncio
    async def test_browse_feed_facebook_sets_current_topic(self):
        """browse_feed sets _current_topic to 'facebook' for routing."""
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()

        with patch(_SETTINGS_PATCH, _make_settings()):
            with patch.object(browser, "_search_web", new_callable=AsyncMock, return_value=[]):
                await browser.browse_feed(topic="facebook")

        assert browser._current_topic == "facebook"


# ============================================================================
# Group 8: Config Flags (2 tests)
# ============================================================================

class TestConfigFlags:
    """Verify .env flag changes are reflected in behavior."""

    @pytest.mark.asyncio
    async def test_social_browse_disabled_returns_empty(self):
        """browse_feed returns [] when living_agent_enable_social_browse=False."""
        from app.engine.living_agent.social_browser import SocialBrowser

        browser = SocialBrowser()

        with patch(_SETTINGS_PATCH, _make_settings(living_agent_enable_social_browse=False)):
            results = await browser.browse_feed(topic="facebook")

        assert results == []

    @pytest.mark.asyncio
    async def test_no_browse_when_social_browse_disabled(self):
        """_plan_actions doesn't include BROWSE_SOCIAL when disabled."""
        from app.engine.living_agent.heartbeat import HeartbeatScheduler
        from app.engine.living_agent.models import ActionType

        scheduler = HeartbeatScheduler()
        settings = _make_settings(
            living_agent_enable_social_browse=False,
            living_agent_enable_skill_building=False,
            living_agent_enable_journal=False,
            living_agent_max_actions_per_heartbeat=5,
        )

        with patch(_SETTINGS_PATCH, settings):
            actions = await scheduler._plan_actions("curious", 0.8)

        action_types = [a.action_type for a in actions]
        assert ActionType.BROWSE_SOCIAL not in action_types
