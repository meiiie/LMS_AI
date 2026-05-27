"""
Sprint 97: Awaken Wiii's Soul — Living Character Activation Tests

Tests:
1. Config activation (defaults True, can override)
2. tool_character_log_experience is @tool and in get_character_tools()
3. Direct node: living state injection, character tools binding + dispatch
4. Tutor node: character tool instruction in prompt
5. Module exports: BlockLabel, ExperienceType
"""

import sys
import types
import asyncio
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from tests.unit._direct_node_test_utils import patched_direct_node_runtime

# Break circular import
_cs_key = "app.services.chat_service"
if _cs_key not in sys.modules:
    _mock_cs = types.ModuleType(_cs_key)
    _mock_cs.ChatService = type("ChatService", (), {})
    _mock_cs.get_chat_service = lambda: None
    sys.modules[_cs_key] = _mock_cs


# =============================================================================
# Phase 1: Config Activation
# =============================================================================

class TestConfigActivation:
    """Sprint 97: Feature flags default to True."""

    def test_character_tools_default_true(self):
        from app.core.config import Settings
        s = Settings(google_api_key="test", api_key="test", _env_file=None)
        assert s.enable_character_tools is True

    def test_character_reflection_default_true(self):
        from app.core.config import Settings
        s = Settings(google_api_key="test", api_key="test", _env_file=None)
        assert s.enable_character_reflection is True

    def test_can_override_to_false(self):
        from app.core.config import Settings
        s = Settings(
            google_api_key="test", api_key="test",
            enable_character_tools=False,
            enable_character_reflection=False,
            _env_file=None,
        )
        assert s.enable_character_tools is False
        assert s.enable_character_reflection is False


# =============================================================================
# Phase 2: Log Experience Tool
# =============================================================================

class TestLogExperienceTool:
    """Sprint 97: tool_character_log_experience is now @tool."""

    def test_is_structured_tool(self):
        from app.engine.character.character_tools import tool_character_log_experience
        assert hasattr(tool_character_log_experience, 'invoke')
        assert hasattr(tool_character_log_experience, 'name')
        assert tool_character_log_experience.name == "tool_character_log_experience"

    def test_in_get_character_tools(self):
        from app.engine.character.character_tools import get_character_tools
        tools = get_character_tools()
        names = [t.name for t in tools]
        assert "tool_character_log_experience" in names
        assert len(tools) == 3

    def test_description_is_ascii(self):
        from app.engine.character.character_tools import tool_character_log_experience
        desc = tool_character_log_experience.description
        assert "trai nghiem" in desc
        assert "milestone" in desc

    def test_rejects_invalid_type(self):
        from app.engine.character.character_tools import tool_character_log_experience
        result = tool_character_log_experience.invoke({
            "content": "test",
            "experience_type": "invalid_xyz",
        })
        assert "không hợp lệ" in result


# =============================================================================
# Phase 3: Direct Node — Living State
# =============================================================================

class TestDirectNodeLivingState:
    """Sprint 97: Living state injected into prompt via build_system_prompt.

    Sprint 100: Living state injection moved from direct_response_node into
    PromptLoader.build_system_prompt() — tested there. These tests verify
    direct_response_node calls build_system_prompt correctly.
    """

    @pytest.mark.asyncio
    async def test_living_state_in_prompt(self):
        """build_system_prompt is called — living state injected internally."""
        from app.engine.multi_agent.state import AgentState

        state: AgentState = {
            "query": "Xin chào!",
            "context": {},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Chào bạn!"
        mock_response.tool_calls = []
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        with patched_direct_node_runtime("Trời đẹp thật!", mock_llm=mock_llm, patch_bind=False), \
             patch("app.engine.character.character_state.get_character_state_manager") as mock_csm, \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings:
            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = True

            mock_mgr = MagicMock()
            mock_mgr.compile_living_state.return_value = "## TRANG THAI SONG\n- Bai hoc: test"
            mock_csm.return_value = mock_mgr

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {"identity": {
                "voice": {"emoji_usage": "emoji hint"},
                "personality": {"summary": "cute AI"},
                "response_style": {"avoid": []},
            }}
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            from app.engine.multi_agent.graph import direct_response_node
            result = await direct_response_node(state)

            # Sprint 100: Verify build_system_prompt called with direct_agent role
            mock_loader.build_system_prompt.assert_called_once()
            call_kwargs = mock_loader.build_system_prompt.call_args.kwargs
            assert call_kwargs.get("role") == "direct_agent"

    @pytest.mark.asyncio
    async def test_empty_living_state_no_noise(self):
        """Direct node works when living state is empty."""
        from app.engine.multi_agent.state import AgentState

        state: AgentState = {
            "query": "Hôm nay trời đẹp quá nhỉ?",
            "context": {},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Trời đẹp thật!"
        mock_response.tool_calls = []
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        with patched_direct_node_runtime(
            "Xin chào An!",
            mock_llm=mock_llm,
            patch_bind=False,
            collect_tools=None,
        ), \
             patch("app.engine.character.character_state.get_character_state_manager") as mock_csm, \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings:
            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = True

            mock_mgr = MagicMock()
            mock_mgr.compile_living_state.return_value = ""
            mock_csm.return_value = mock_mgr

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {"identity": {
                "voice": {"emoji_usage": ""},
                "personality": {"summary": ""},
                "response_style": {"avoid": []},
            }}
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            from app.engine.multi_agent.graph import direct_response_node
            result = await direct_response_node(state)

            # Node should still produce a response
            assert result.get("final_response")

    @pytest.mark.asyncio
    async def test_db_error_graceful(self):
        """DB error in compile_living_state() should not crash direct node."""
        from app.engine.multi_agent.state import AgentState

        state: AgentState = {
            "query": "Bạn nghĩ gì về điều này?",
            "context": {},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Tôi nghĩ điều này rất hay!"
        mock_response.tool_calls = []
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_acr, \
             patch("app.engine.character.character_state.get_character_state_manager") as mock_csm, \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings:
            mock_acr.get_llm.return_value = mock_llm
            mock_acr.get_native_llm.return_value = None
            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = True

            mock_csm.side_effect = RuntimeError("DB unavailable")

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {"identity": {
                "voice": {"emoji_usage": ""},
                "personality": {"summary": ""},
                "response_style": {"avoid": []},
            }}
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            from app.engine.multi_agent.graph import direct_response_node
            result = await direct_response_node(state)
            assert result["final_response"] == "Tôi nghĩ điều này rất hay!"


# =============================================================================
# Phase 4: Direct Node — Character Tools
# =============================================================================

class TestDirectNodeCharacterTools:
    """Sprint 97: Character tools bound and dispatched in direct node."""

    @pytest.mark.asyncio
    async def test_plain_direct_prose_does_not_bind_character_tools_when_enabled(self):
        """Plain direct prose should stay off tools even when character tools are enabled."""
        from app.engine.multi_agent.state import AgentState

        state: AgentState = {
            "query": "Kể cho tôi về lịch sử Việt Nam",
            "context": {},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Đây là câu trả lời!"
        mock_response.tool_calls = []
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_llm.bind_tools = MagicMock(return_value=mock_llm)

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_acr, \
             patch("app.engine.character.character_state.get_character_state_manager") as mock_csm, \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings:
            mock_acr.get_llm.return_value = mock_llm
            mock_acr.get_native_llm.return_value = None
            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = True
            mock_settings.enable_code_execution = False  # Sprint 98: explicit
            mock_settings.enable_lms_integration = False  # Sprint 175: LMS tools
            mock_settings.enable_chart_tools = False  # Sprint 179: chart tools

            mock_mgr = MagicMock()
            mock_mgr.compile_living_state.return_value = ""
            mock_csm.return_value = mock_mgr

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {"identity": {
                "voice": {"emoji_usage": ""},
                "personality": {"summary": ""},
                "response_style": {"avoid": []},
            }}
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            from app.engine.multi_agent.graph import direct_response_node
            await direct_response_node(state)

            mock_llm.bind_tools.assert_not_called()
            assert state["_turn_path_decision"]["reason"] == "default_direct_prose_no_tool"

    @pytest.mark.asyncio
    async def test_no_character_tools_when_disabled(self):
        """Plain direct prose stays no-tool when character tools are disabled."""
        from app.engine.multi_agent.state import AgentState

        state: AgentState = {
            "query": "Kể cho tôi về lịch sử Việt Nam",
            "context": {},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Đây là câu trả lời!"
        mock_response.tool_calls = []
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)
        mock_llm.bind_tools.return_value = mock_llm

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry") as mock_acr, \
             patch("app.engine.character.character_state.get_character_state_manager") as mock_csm, \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings:
            mock_acr.get_llm.return_value = mock_llm
            mock_acr.get_native_llm.return_value = None
            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = False
            mock_settings.enable_code_execution = False  # Sprint 98: explicit

            mock_mgr = MagicMock()
            mock_mgr.compile_living_state.return_value = ""
            mock_csm.return_value = mock_mgr

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {"identity": {
                "voice": {"emoji_usage": ""},
                "personality": {"summary": ""},
                "response_style": {"avoid": []},
            }}
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            from app.engine.multi_agent.graph import direct_response_node
            await direct_response_node(state)

            mock_llm.bind_tools.assert_not_called()
            assert state["_turn_path_decision"]["reason"] == "default_direct_prose_no_tool"

    @pytest.mark.asyncio
    async def test_tool_dispatch_works(self):
        """When LLM returns tool_calls, dispatch and re-invoke."""
        from app.engine.multi_agent.state import AgentState

        state: AgentState = {
            "query": "Tên tôi là An",
            "context": {},
            "current_agent": "",
            "final_response": "",
            "agent_outputs": {},
        }

        # First response: tool call; Second response: final answer
        tool_call_response = MagicMock()
        tool_call_response.content = ""
        tool_call_response.tool_calls = [
            {"name": "tool_character_note", "args": {"note": "User tên An", "block": "user_patterns"}, "id": "tc_1"}
        ]

        final_response = MagicMock()
        final_response.content = "Xin chào An!"
        final_response.tool_calls = []

        mock_llm = MagicMock()
        mock_llm_with_tools = MagicMock()
        # First call returns tool_call_response, second returns final text
        mock_llm_with_tools.ainvoke = AsyncMock(side_effect=[tool_call_response, final_response])
        mock_llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

        async def _fake_ainvoke_with_fallback(llm, messages, **_kwargs):
            return await llm.ainvoke(messages)

        with patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
                   return_value=mock_llm), \
             patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
                   return_value=None), \
             patch("app.engine.character.character_state.get_character_state_manager") as mock_csm, \
             patch("app.prompts.prompt_loader.get_prompt_loader") as mock_pl, \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._ainvoke_with_fallback",
                   side_effect=_fake_ainvoke_with_fallback):
            mock_settings.app_name = "Wiii"
            mock_settings.default_domain = "maritime"
            mock_settings.enable_character_tools = True
            mock_settings.enable_code_execution = False  # Sprint 98: explicit

            mock_mgr = MagicMock()
            mock_mgr.compile_living_state.return_value = ""
            mock_csm.return_value = mock_mgr

            mock_loader = MagicMock()
            mock_loader.get_identity.return_value = {"identity": {
                "voice": {"emoji_usage": ""},
                "personality": {"summary": ""},
                "response_style": {"avoid": []},
            }}
            # Sprint 100: direct_response_node now calls build_system_prompt
            mock_loader.build_system_prompt.return_value = "Bạn là Wiii, trợ lý đa lĩnh vực."
            mock_pl.return_value = mock_loader

            from app.engine.multi_agent.graph import direct_response_node
            result = await direct_response_node(state)

            mock_llm.bind_tools.assert_called()
            bound_tools = mock_llm.bind_tools.call_args_list[0].args[0]
            bound_names = {getattr(tool, "name", "") for tool in bound_tools}
            assert "tool_character_note" in bound_names
            assert result["final_response"] == "Xin chào An!"


# =============================================================================
# Phase 5: Tutor Character Instruction
# =============================================================================

class TestTutorCharacterInstruction:
    """Sprint 97: Character tool instruction in tutor system prompt."""

    @patch("app.engine.multi_agent.agents.tutor_runtime.AgentConfigRegistry")
    def test_present_when_enabled(self, mock_acr):
        mock_llm = MagicMock()
        mock_acr.get_llm.return_value = mock_llm
        with patch("app.engine.multi_agent.agents.tutor_node.settings") as mock_settings:
            mock_settings.enable_character_tools = True
            mock_settings.default_domain = "maritime"
            from app.engine.multi_agent.agents.tutor_node import TutorAgentNode
            import app.engine.multi_agent.agents.tutor_node as mod
            old = mod._tutor_node
            mod._tutor_node = None
            try:
                node = TutorAgentNode()
                prompt = node._build_system_prompt(
                    context={"user_role": "student"},
                    query="test"
                )
                assert "CONG CU GHI NHO" in prompt
                assert "tool_character_note" in prompt
                assert "tool_character_log_experience" in prompt
            finally:
                mod._tutor_node = old

    @patch("app.engine.multi_agent.agents.tutor_runtime.AgentConfigRegistry")
    def test_absent_when_disabled(self, mock_acr):
        mock_llm = MagicMock()
        mock_acr.get_llm.return_value = mock_llm
        with patch("app.engine.multi_agent.agents.tutor_node.settings") as mock_settings:
            mock_settings.enable_character_tools = False
            mock_settings.default_domain = "maritime"
            from app.engine.multi_agent.agents.tutor_node import TutorAgentNode
            import app.engine.multi_agent.agents.tutor_node as mod
            old = mod._tutor_node
            mod._tutor_node = None
            try:
                node = TutorAgentNode()
                prompt = node._build_system_prompt(
                    context={"user_role": "student"},
                    query="test"
                )
                assert "CONG CU GHI NHO" not in prompt
            finally:
                mod._tutor_node = old

    @patch("app.engine.multi_agent.agents.tutor_runtime.AgentConfigRegistry")
    def test_mentions_all_3_tools(self, mock_acr):
        mock_llm = MagicMock()
        mock_acr.get_llm.return_value = mock_llm
        with patch("app.engine.multi_agent.agents.tutor_node.settings") as mock_settings:
            mock_settings.enable_character_tools = True
            mock_settings.default_domain = "maritime"
            from app.engine.multi_agent.agents.tutor_node import TutorAgentNode
            import app.engine.multi_agent.agents.tutor_node as mod
            old = mod._tutor_node
            mod._tutor_node = None
            try:
                node = TutorAgentNode()
                prompt = node._build_system_prompt(
                    context={"user_role": "student"},
                    query="test"
                )
                assert "tool_character_note" in prompt
                assert "tool_character_log_experience" in prompt
                assert "learned_lessons" in prompt
                assert "milestone" in prompt
            finally:
                mod._tutor_node = old


# =============================================================================
# Phase 6: Module Exports
# =============================================================================

class TestModuleExports:
    """Sprint 97: BlockLabel and ExperienceType importable from character package."""

    def test_block_label_importable(self):
        from app.engine.character import BlockLabel
        assert hasattr(BlockLabel, 'LEARNED_LESSONS') or "learned_lessons" in [b.value for b in BlockLabel]

    def test_experience_type_importable(self):
        from app.engine.character import ExperienceType
        assert hasattr(ExperienceType, 'MILESTONE') or "milestone" in [t.value for t in ExperienceType]
