"""Unit tests for P3: Per-agent model tier configuration + tier tracking."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.engine.multi_agent.state import AgentState


# =========================================================================
# AgentConfigRegistry default tier mapping
# =========================================================================


class TestDefaultTierMapping:
    """Verify each agent has the expected default tier."""

    def setup_method(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        AgentConfigRegistry.initialize("{}", "{}")

    def test_rag_agent_is_moderate(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        config = AgentConfigRegistry.get_config("rag_agent")
        assert config.tier == "moderate"

    def test_tutor_agent_is_moderate(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        config = AgentConfigRegistry.get_config("tutor_agent")
        assert config.tier == "moderate"

    def test_supervisor_is_light(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        config = AgentConfigRegistry.get_config("supervisor")
        assert config.tier == "light"

    def test_guardian_is_light(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        config = AgentConfigRegistry.get_config("guardian")
        assert config.tier == "light"

    def test_memory_is_light(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        config = AgentConfigRegistry.get_config("memory")
        assert config.tier == "light"

    def test_direct_is_light(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        config = AgentConfigRegistry.get_config("direct")
        assert config.tier == "light"

    def test_code_studio_is_deep(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        config = AgentConfigRegistry.get_config("code_studio_agent")
        assert config.tier == "deep"
        assert config.model == "gemini-3.1-pro-preview"

    def test_grader_is_moderate(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        config = AgentConfigRegistry.get_config("grader")
        assert config.tier == "moderate"

    def test_synthesizer_is_moderate(self):
        from app.engine.multi_agent.agent_config import AgentConfigRegistry

        config = AgentConfigRegistry.get_config("synthesizer")
        assert config.tier == "moderate"


# =========================================================================
# Tier injection in WiiiRunner
# =========================================================================


class TestTierInjection:
    """Test that WiiiRunner injects tier info into state before agent execution."""

    def setup_method(self):
        import app.engine.multi_agent.runner as runner_mod
        runner_mod._RUNNER = None

    @pytest.mark.asyncio
    async def test_rag_agent_gets_moderate_tier(self):
        from app.engine.multi_agent.runner import WiiiRunner

        runner = WiiiRunner()

        async def mock_rag(state):
            return state

        runner.register_node("rag_agent", mock_rag)
        state = await runner._run_step("rag_agent", {"query": "test"})

        assert state.get("_execution_tier") == "moderate"

    @pytest.mark.asyncio
    async def test_supervisor_gets_light_tier(self):
        from app.engine.multi_agent.runner import WiiiRunner

        runner = WiiiRunner()

        async def mock_supervisor(state):
            return state

        runner.register_node("supervisor", mock_supervisor)
        state = await runner._run_step("supervisor", {"query": "test"})

        assert state.get("_execution_tier") == "light"

    @pytest.mark.asyncio
    async def test_guardian_no_tier_injection(self):
        """Infrastructure nodes should NOT inject tier (not agent-specific)."""
        from app.engine.multi_agent.runner import WiiiRunner, _NODE_GUARDIAN

        runner = WiiiRunner()

        async def mock_guardian(state):
            return state

        runner.register_node(_NODE_GUARDIAN, mock_guardian)
        state = await runner._run_step(_NODE_GUARDIAN, {"query": "test"})

        assert "_execution_tier" not in state

    @pytest.mark.asyncio
    async def test_synthesizer_no_tier_injection(self):
        """Synthesizer is infrastructure, not agent-specific."""
        from app.engine.multi_agent.runner import WiiiRunner, _NODE_SYNTHESIZER

        runner = WiiiRunner()

        async def mock_synth(state):
            return state

        runner.register_node(_NODE_SYNTHESIZER, mock_synth)
        state = await runner._run_step(_NODE_SYNTHESIZER, {"query": "test"})

        assert "_execution_tier" not in state


# =========================================================================
# Grader uses registry
# =========================================================================


class TestGraderUsesRegistry:
    """Verify GraderAgentNode uses AgentConfigRegistry instead of direct LLMPool."""

    @patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm")
    def test_grader_init_uses_registry(self, mock_get_llm):
        mock_llm = MagicMock()
        mock_get_llm.return_value = mock_llm

        from app.engine.multi_agent.agents.grader_agent import GraderAgentNode

        agent = GraderAgentNode()

        mock_get_llm.assert_called_once_with("grader")
        assert agent._llm is mock_llm


# =========================================================================
# _execution_tier in state
# =========================================================================


class TestExecutionTierState:
    """_execution_tier field exists in AgentState and RuntimeMeta."""

    def test_execution_tier_in_state(self):
        state: AgentState = {"_execution_tier": "moderate"}
        assert state["_execution_tier"] == "moderate"

    def test_execution_tier_in_runtime_meta_accessor(self):
        from app.engine.multi_agent.state import get_runtime_meta

        state = {"_execution_tier": "deep", "_trace_id": "t1"}
        meta = get_runtime_meta(state)
        assert meta["_execution_tier"] == "deep"
