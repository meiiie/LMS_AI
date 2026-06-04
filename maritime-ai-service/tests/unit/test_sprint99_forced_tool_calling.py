"""
Sprint 99: Forced Tool Calling — 3-Tier Intent-Based System

Tests:
- Tier 1: tool_choice="any" when web/datetime intent detected
- Tier 2: _needs_web_search() / _needs_datetime() intent detection
- Tier 3: Training cutoff + prompt conflict fix
"""
import sys
import types
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from tests.unit._direct_node_test_utils import patched_direct_node_runtime

# Break circular import (same pattern as test_sprint97)
_cs_key = "app.services.chat_service"
if _cs_key not in sys.modules:
    _mock_cs = types.ModuleType(_cs_key)
    _mock_cs.ChatService = type("ChatService", (), {})
    _mock_cs.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_cs


# ============================================================================
# Tier 2: Intent Detection Functions
# ============================================================================

class TestNormalizeForIntent:
    """Test _normalize_for_intent diacritics stripping."""

    def test_strips_vietnamese_diacritics(self):
        from app.engine.multi_agent.graph import _normalize_for_intent
        result = _normalize_for_intent("tìm kiếm trên web")
        assert "tim" in result
        assert "kiem" in result
        assert "tren" in result

    def test_lowercase(self):
        from app.engine.multi_agent.graph import _normalize_for_intent
        assert _normalize_for_intent("TIN TỨC") == "tin tuc"

    def test_strips_d_bar(self):
        from app.engine.multi_agent.graph import _normalize_for_intent
        assert "d" in _normalize_for_intent("đổi")

    def test_already_no_diacritics(self):
        from app.engine.multi_agent.graph import _normalize_for_intent
        assert _normalize_for_intent("tim tren web") == "tim tren web"

    def test_empty_string(self):
        from app.engine.multi_agent.graph import _normalize_for_intent
        assert _normalize_for_intent("") == ""

    def test_english_passthrough(self):
        from app.engine.multi_agent.graph import _normalize_for_intent
        assert _normalize_for_intent("Search Google") == "search google"

    def test_fallback_when_textnormalizer_unavailable(self):
        """Still works when TextNormalizer import fails."""
        from app.engine.multi_agent.graph import _normalize_for_intent
        with patch.dict("sys.modules", {"app.engine.content_filter": None}):
            result = _normalize_for_intent("tin tức")
            assert "tin" in result
            assert "tuc" in result


class TestNeedsWebSearch:
    """Test _needs_web_search() intent detection."""

    def test_tin_tuc_with_diacritics(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("tin tức hôm nay") is True

    def test_tin_tuc_without_diacritics(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("tin tuc hom nay") is True

    def test_tra_cuu_tren_web(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("tra cứu trên web về thời tiết") is True

    def test_search_english(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("search latest news") is True

    def test_cap_nhat(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("cập nhật tình hình Ukraine") is True

    def test_su_kien(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("các sự kiện nổi bật") is True

    def test_weather_keyword_uses_weather_policy_not_generic_web(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("thoi tiet Ha Noi hom nay") is False

    def test_gia_vang(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("giá vàng hôm nay") is True

    def test_hom_nay(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("hôm nay có gì hot?") is True

    def test_moi_nhat(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("thông tin mới nhất") is True

    def test_google(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("google xem COLREGs Rule 15") is True

    def test_normal_greeting_no_match(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("xin chào") is False

    def test_domain_question_no_match(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("quy tắc COLREGs là gì?") is False

    def test_personal_chat_no_match(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("tôi buồn quá") is False

    def test_empty_query_no_match(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("") is False

    def test_mixed_case(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("TÌM TRÊN WEB tin tức") is True

    def test_ban_tin(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("bản tin sáng nay") is True

    def test_ty_gia(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("tỷ giá USD hôm nay") is True

    def test_look_up(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("look up the weather") is True


class TestNeedsDatetime:
    """Test _needs_datetime() intent detection."""

    def test_ngay_may(self):
        from app.engine.multi_agent.graph import _needs_datetime
        assert _needs_datetime("hôm nay ngày mấy?") is True

    def test_may_gio(self):
        from app.engine.multi_agent.graph import _needs_datetime
        assert _needs_datetime("bây giờ mấy giờ?") is True

    def test_bay_gio_la(self):
        from app.engine.multi_agent.graph import _needs_datetime
        assert _needs_datetime("bây giờ là mấy giờ rồi?") is True

    def test_current_time_english(self):
        from app.engine.multi_agent.graph import _needs_datetime
        assert _needs_datetime("what time is it?") is True

    def test_what_date(self):
        from app.engine.multi_agent.graph import _needs_datetime
        assert _needs_datetime("what date is today?") is True

    def test_no_diacritics(self):
        from app.engine.multi_agent.graph import _needs_datetime
        assert _needs_datetime("hom nay ngay may?") is True

    def test_normal_chat_no_match(self):
        from app.engine.multi_agent.graph import _needs_datetime
        assert _needs_datetime("xin chào bạn") is False

    def test_empty_no_match(self):
        from app.engine.multi_agent.graph import _needs_datetime
        assert _needs_datetime("") is False


# ============================================================================
# Tier 1: tool_choice="any" Forced Calling
# ============================================================================

class TestForcedToolChoice:
    """Test that tool_choice='any' is passed when intent detected."""

    @pytest.mark.asyncio
    async def test_web_search_forces_tool_choice_any(self):
        """When query needs web search, bind_tools gets tool_choice='any'."""
        from app.engine.multi_agent.state import AgentState

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Đây là tin tức hôm nay..."
        mock_response.tool_calls = []
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        state: AgentState = {
            "query": "tin tức hôm nay có gì?",
            "context": {"is_follow_up": False},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        with patched_direct_node_runtime(
                "Day la tin tuc hom nay...",
                mock_llm=mock_llm,
                patch_bind=False,
                collect_tools=None,
             ), \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._get_or_create_tracer") as mock_tracer_fn, \
             patch("app.engine.multi_agent.graph._get_domain_greetings", return_value={}):

            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = False
            mock_settings.enable_code_execution = False

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {
                "identity": {
                    "voice": {"emoji_usage": "emoji"},
                    "personality": {"summary": "nice"},
                    "response_style": {"avoid": []},
                }
            }
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            mock_tracer = MagicMock()
            mock_tracer_fn.return_value = mock_tracer

            from app.engine.multi_agent.graph import direct_response_node
            await direct_response_node(state)

            # Verify bind_tools was called with tool_choice="any" for one call
            # Sprint 99 fix: bind_tools called twice — llm_auto (no tool_choice)
            # and llm_with_tools (tool_choice="any")
            assert mock_llm.bind_tools.call_count == 2
            calls = mock_llm.bind_tools.call_args_list
            has_forced = any(
                c.kwargs.get("tool_choice") == "any" for c in calls
            )
            assert has_forced, "One bind_tools call should have tool_choice='any'"

    @pytest.mark.asyncio
    async def test_normal_chat_no_forced_tool_choice(self):
        """When query is normal chat, bind_tools uses default (no tool_choice)."""
        from app.engine.multi_agent.state import AgentState

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Xin chào!"
        mock_response.tool_calls = []
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        state: AgentState = {
            "query": "xin chào bạn",
            "context": {"is_follow_up": False},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        with patched_direct_node_runtime(
                "Xin chao!",
                mock_llm=mock_llm,
                patch_bind=False,
                collect_tools=None,
             ), \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._get_or_create_tracer") as mock_tracer_fn, \
             patch("app.engine.multi_agent.graph._get_domain_greetings", return_value={}):

            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = False
            mock_settings.enable_code_execution = False

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {
                "identity": {
                    "voice": {"emoji_usage": "emoji"},
                    "personality": {"summary": "nice"},
                    "response_style": {"avoid": []},
                }
            }
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            mock_tracer = MagicMock()
            mock_tracer_fn.return_value = mock_tracer

            from app.engine.multi_agent.graph import direct_response_node
            await direct_response_node(state)

            # Path governor contract: plain greetings stay off the tool-schema path.
            mock_llm.bind_tools.assert_not_called()

    @pytest.mark.asyncio
    async def test_plain_meta_complaint_does_not_bind_tools(self):
        """No-tool direct prose must not expose broad tools to the model."""
        from app.engine.multi_agent.state import AgentState

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Mình sẽ kiểm tra luồng trực tiếp."
        mock_response.tool_calls = []
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        state: AgentState = {
            "query": "flow noi chuyen thuong van bi keo sang search/tool",
            "context": {"is_follow_up": False},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        with patched_direct_node_runtime(
                "Mình sẽ kiểm tra luồng trực tiếp.",
                mock_llm=mock_llm,
                patch_bind=False,
                collect_tools=None,
             ), \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._get_or_create_tracer") as mock_tracer_fn, \
             patch("app.engine.multi_agent.graph._get_domain_greetings", return_value={}):

            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = False
            mock_settings.enable_code_execution = False

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {
                "identity": {
                    "voice": {"emoji_usage": "emoji"},
                    "personality": {"summary": "nice"},
                    "response_style": {"avoid": []},
                }
            }
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            mock_tracer = MagicMock()
            mock_tracer_fn.return_value = mock_tracer

            from app.engine.multi_agent.graph import direct_response_node
            await direct_response_node(state)

            mock_llm.bind_tools.assert_not_called()
            assert state["_turn_path_decision"]["reason"] == "default_direct_prose_no_tool"

    @pytest.mark.asyncio
    async def test_datetime_query_forces_tool_choice(self):
        """When query asks for time/date, bind_tools gets tool_choice='any'."""
        from app.engine.multi_agent.state import AgentState

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Bây giờ là 10:00"
        mock_response.tool_calls = []
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        state: AgentState = {
            "query": "bây giờ mấy giờ rồi?",
            "context": {"is_follow_up": False},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        with patched_direct_node_runtime(
                "Bay gio la 10:00",
                mock_llm=mock_llm,
                patch_bind=False,
                collect_tools=None,
             ), \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._get_or_create_tracer") as mock_tracer_fn, \
             patch("app.engine.multi_agent.graph._get_domain_greetings", return_value={}):

            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = False
            mock_settings.enable_code_execution = False

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {
                "identity": {
                    "voice": {"emoji_usage": "emoji"},
                    "personality": {"summary": "nice"},
                    "response_style": {"avoid": []},
                }
            }
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            mock_tracer = MagicMock()
            mock_tracer_fn.return_value = mock_tracer

            from app.engine.multi_agent.graph import direct_response_node
            await direct_response_node(state)

            # bind_tools called twice (llm_auto + llm_with_tools forced)
            assert mock_llm.bind_tools.call_count == 2
            calls = mock_llm.bind_tools.call_args_list
            has_forced = any(
                c.kwargs.get("tool_choice") in {"any", "tool_current_datetime"}
                for c in calls
            )
            assert has_forced, "One bind_tools call should force the datetime tool"

    @pytest.mark.asyncio
    async def test_follow_up_call_uses_auto_not_forced(self):
        """After tool dispatch, follow-up LLM call uses auto (not forced)."""
        from app.engine.multi_agent.state import AgentState

        # First response: tool call (forced), second: text (auto)
        mock_tool_response = MagicMock()
        mock_tool_response.content = ""
        mock_tool_response.tool_calls = [{"name": "tool_web_search", "args": {"query": "news"}, "id": "tc1"}]

        mock_text_response = MagicMock()
        mock_text_response.content = "Kết quả tìm kiếm: có nhiều tin tức..."
        mock_text_response.tool_calls = []

        mock_llm = MagicMock()
        # bind_tools returns different objects for tracking
        mock_llm_auto = MagicMock()
        mock_llm_auto.ainvoke = AsyncMock(return_value=mock_text_response)
        mock_llm_forced = MagicMock()
        mock_llm_forced.ainvoke = AsyncMock(return_value=mock_tool_response)

        def _bind_tools_side_effect(tools, **kwargs):
            if kwargs.get("tool_choice") == "any":
                return mock_llm_forced
            return mock_llm_auto

        mock_llm.bind_tools.side_effect = _bind_tools_side_effect

        # Create a mock tool that matches tool_web_search
        mock_tool = MagicMock()
        mock_tool.name = "tool_web_search"
        mock_tool.invoke.return_value = "Search results here"

        async def _fake_ainvoke_with_fallback(llm, messages, **_kwargs):
            return await llm.ainvoke(messages)

        state: AgentState = {
            "query": "tin tức hôm nay",
            "context": {"is_follow_up": False},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
                   return_value=mock_llm), \
             patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
                   return_value=None), \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._get_or_create_tracer") as mock_tracer_fn, \
             patch("app.engine.multi_agent.graph._get_domain_greetings", return_value={}), \
             patch("app.engine.multi_agent.graph._ainvoke_with_fallback",
                   side_effect=_fake_ainvoke_with_fallback), \
             patch("app.engine.tools.web_search_tools.tool_web_search", mock_tool), \
             patch("app.services.output_processor.extract_thinking_from_response",
                   return_value=("Kết quả tìm kiếm: có nhiều tin tức...", None)):

            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = False
            mock_settings.enable_code_execution = False
            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {
                "identity": {
                    "voice": {"emoji_usage": "emoji"},
                    "personality": {"summary": "nice"},
                    "response_style": {"avoid": []},
                }
            }
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            mock_tracer = MagicMock()
            mock_tracer_fn.return_value = mock_tracer

            from app.engine.multi_agent.graph import direct_response_node
            result = await direct_response_node(state)

            # After tool dispatch, llm_auto (not forced) should be used
            # The second ainvoke call should be on llm_auto
            assert mock_llm_auto.ainvoke.call_count >= 1, \
                "Follow-up call after tool dispatch should use llm_auto"
            # Final response should contain the text from the auto call
            assert "tin tức" in result.get("final_response", "").lower() or \
                   len(result.get("final_response", "")) > 0


# ============================================================================
# Tier 3: Prompt Content Verification
# ============================================================================

class TestPromptContent:
    """Test system prompt includes training cutoff and tool rules.

    Sprint 100: Tests use real PromptLoader (no mock) to verify actual prompt content.
    """

    @pytest.mark.asyncio
    async def test_prompt_includes_training_cutoff(self):
        """System prompt must mention knowledge cutoff."""
        from app.engine.multi_agent.state import AgentState

        captured_messages = []

        async def capture_ainvoke(messages):
            captured_messages.extend(messages)
            return MagicMock(content="test", tool_calls=[])

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = capture_ainvoke

        state: AgentState = {
            "query": "xin chào",
            "context": {"is_follow_up": False},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        state["query"] = "giai thich nguyen tac su dung tool cua Wiii trong he thong"

        async def capture_ainvoke_with_fallback(_llm, messages, **_kwargs):
            return await capture_ainvoke(messages)

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_acr, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._get_or_create_tracer") as mock_tracer_fn, \
             patch("app.engine.multi_agent.graph._get_domain_greetings", return_value={}), \
             patch("app.engine.multi_agent.graph._ainvoke_with_fallback",
                   side_effect=capture_ainvoke_with_fallback):

            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = False
            mock_settings.enable_code_execution = False
            mock_acr.get_llm.return_value = mock_llm
            mock_acr.get_native_llm.return_value = None

            mock_tracer = MagicMock()
            mock_tracer_fn.return_value = mock_tracer

            from app.engine.multi_agent.graph import direct_response_node
            await direct_response_node(state)

            system_content = captured_messages[0]["content"] if isinstance(captured_messages[0], dict) else captured_messages[0].content

            # Tier 3: Must include training cutoff
            assert "2024" in system_content
            assert "GIỚI HẠN KIẾN THỨC" in system_content

            # Must NOT have contradictory "trả lời MỌI câu hỏi"
            assert "trả lời MỌI câu hỏi" not in system_content

            # Must include tool rules
            assert "tool_web_search" in system_content
            assert "tool_current_datetime" in system_content

    @pytest.mark.asyncio
    async def test_prompt_has_multi_domain_not_all_questions(self):
        """System prompt must say 'đa lĩnh vực', not 'MỌI câu hỏi'."""
        from app.engine.multi_agent.state import AgentState

        captured_messages = []

        async def capture_ainvoke(messages):
            captured_messages.extend(messages)
            return MagicMock(content="test", tool_calls=[])

        mock_llm = MagicMock()
        mock_llm.bind_tools.return_value = mock_llm
        mock_llm.ainvoke = capture_ainvoke

        state: AgentState = {
            "query": "hello",
            "context": {"is_follow_up": False},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        state["query"] = "phan tich kha nang ho tro da linh vuc cua Wiii"

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_acr, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._get_or_create_tracer") as mock_tracer_fn, \
             patch("app.engine.multi_agent.graph._get_domain_greetings", return_value={}):

            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = False
            mock_settings.enable_code_execution = False
            mock_acr.get_llm.return_value = mock_llm
            mock_acr.get_native_llm.return_value = None

            mock_tracer = MagicMock()
            mock_tracer_fn.return_value = mock_tracer

            from app.engine.multi_agent.graph import direct_response_node
            await direct_response_node(state)

            system_content = captured_messages[0]["content"] if isinstance(captured_messages[0], dict) else captured_messages[0].content
            assert "đa lĩnh vực" in system_content


# Sprint 103: TestSupervisorWebKeywords deleted — WEB_KEYWORDS removed from supervisor.py.
# Web search routing is now handled by LLM structured routing (_route_structured).


# ============================================================================
# Edge Cases
# ============================================================================

class TestEdgeCases:
    """Edge cases for intent detection."""

    def test_web_search_with_domain_keywords(self):
        """Query with both web + domain keywords still triggers web search."""
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("tra cứu tin tức hàng hải") is True

    def test_datetime_and_web_overlap(self):
        """'hôm nay' triggers both web and datetime."""
        from app.engine.multi_agent.graph import _needs_web_search, _needs_datetime
        query = "hôm nay ngày mấy, có tin gì mới?"
        assert _needs_web_search(query) is True
        assert _needs_datetime(query) is True

    def test_very_long_query(self):
        from app.engine.multi_agent.graph import _needs_web_search
        long_q = "a " * 1000 + "tin tức"
        assert _needs_web_search(long_q) is True

    def test_unicode_edge(self):
        from app.engine.multi_agent.graph import _normalize_for_intent
        result = _normalize_for_intent("ắ")
        # Should strip the combining accent
        assert len(result) >= 1

    def test_mixed_diacritics_and_plain(self):
        from app.engine.multi_agent.graph import _needs_web_search
        assert _needs_web_search("tim tin tức mới nhất") is True
