"""
Unit tests for Multi-Agent Graph routing logic.

Tests:
- route_decision() for all 4 routes
- _build_domain_config() fallback behavior
- _get_domain_greetings() fallback behavior

Sprint 233: should_skip_grader removed — grader node eliminated from pipeline.
"""

import asyncio
import pytest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, MagicMock

from app.engine.multi_agent.code_studio_fast_paths import CodeStudioFastPathResult
from app.engine.multi_agent.graph import (
    route_decision,
    _ainvoke_with_fallback,
    _build_domain_config,
    _build_visual_tool_runtime_metadata,
    _build_ambiguous_simulation_clarifier,
    _derive_code_stream_session_id,
    _should_enable_real_code_streaming,
    _build_code_studio_progress_messages,
    _build_code_studio_retry_status,
    _build_code_studio_wait_heartbeat_text,
    _build_direct_wait_heartbeat_text,
    _capture_public_thinking_event,
    _thinking_start_label,
    _format_code_studio_progress_message,
    _get_domain_greetings,
    _direct_required_tool_names,
    _public_reasoning_delta_chunks,
    _resolve_direct_answer_timeout_profile,
    _resolve_public_thinking_content,
    _summarize_tool_result_for_stream,
    _stream_answer_with_fallback,
    _stream_openai_compatible_answer_with_route,
    _bind_direct_tools,
    _collect_direct_tools,
    _collect_code_studio_tools,
    _execute_code_studio_tool_rounds,
    _ground_simulation_query_from_visual_context,
    _infer_pendulum_fast_path_title,
    _looks_like_ambiguous_simulation_request,
    _should_use_pendulum_code_studio_fast_path,
    direct_response_node,
    code_studio_node,
    supervisor_node,
)


# =============================================================================
# Tests: route_decision
# =============================================================================

class TestRouteDecision:
    def test_routes_to_rag_agent(self):
        state = {"next_agent": "rag_agent"}
        assert route_decision(state) == "rag_agent"

    def test_routes_to_tutor_agent(self):
        state = {"next_agent": "tutor_agent"}
        assert route_decision(state) == "tutor_agent"

    def test_routes_to_memory_agent(self):
        state = {"next_agent": "memory_agent"}
        assert route_decision(state) == "memory_agent"

    def test_routes_to_direct(self):
        state = {"next_agent": "direct"}
        assert route_decision(state) == "direct"

    def test_routes_to_code_studio_agent(self):
        state = {"next_agent": "code_studio_agent"}
        assert route_decision(state) == "code_studio_agent"

    def test_unknown_agent_defaults_to_direct(self):
        state = {"next_agent": "unknown_agent"}
        assert route_decision(state) == "direct"

    def test_missing_next_agent_defaults_to_rag(self):
        state = {}
        assert route_decision(state) == "rag_agent"

    def test_empty_next_agent_defaults_to_direct(self):
        state = {"next_agent": ""}
        assert route_decision(state) == "direct"


# =============================================================================
# Sprint 233: TestShouldSkipGrader removed — grader node eliminated from pipeline.
# CRAG confidence is the sole confidence source. See test_sprint44_*.py for
# CRAG grading tests that remain valid.
# =============================================================================


# =============================================================================
# Tests: visual runtime metadata
# =============================================================================

class TestVisualRuntimeMetadata:
    def test_chart_runtime_metadata_prefers_inline_html_svg(self):
        metadata = _build_visual_tool_runtime_metadata({}, "Ve bieu do so sanh toc do cac loai tau container")

        assert metadata is not None
        assert metadata["presentation_intent"] == "chart_runtime"
        assert metadata["visual_intent_mode"] == "inline_html"
        assert metadata["preferred_render_surface"] == "svg"
        assert metadata["planning_profile"] == "chart_svg"
        assert metadata["preferred_visual_tool"] == "tool_generate_visual"


# =============================================================================
# Tests: _build_domain_config
# =============================================================================

class TestBuildDomainConfig:
    def test_fallback_returns_dict(self):
        """When domain registry returns None, returns generic fallback."""
        with patch("app.domains.registry.get_domain_registry") as mock_reg:
            mock_reg.return_value.get.return_value = None
            config = _build_domain_config("nonexistent")
        assert isinstance(config, dict)
        assert "domain_name" in config
        assert "domain_id" in config
        assert "routing_keywords" in config

    def test_fallback_has_rag_description(self):
        with patch("app.domains.registry.get_domain_registry") as mock_reg:
            mock_reg.return_value.get.return_value = None
            config = _build_domain_config("nonexistent")
        assert "rag_description" in config
        assert len(config["rag_description"]) > 0

    def test_fallback_has_tutor_description(self):
        with patch("app.domains.registry.get_domain_registry") as mock_reg:
            mock_reg.return_value.get.return_value = None
            config = _build_domain_config("nonexistent")
        assert "tutor_description" in config
        assert len(config["tutor_description"]) > 0


# =============================================================================
# Tests: _get_domain_greetings
# =============================================================================

class TestGetDomainGreetings:
    def test_fallback_returns_dict(self):
        with patch("app.domains.registry.get_domain_registry") as mock_reg:
            mock_reg.return_value.get.return_value = None
            greetings = _get_domain_greetings("nonexistent")
        assert isinstance(greetings, dict)

    def test_fallback_has_vietnamese_greetings(self):
        with patch("app.domains.registry.get_domain_registry") as mock_reg:
            mock_reg.return_value.get.return_value = None
            greetings = _get_domain_greetings("nonexistent")
        assert "xin chào" in greetings
        assert "hi" in greetings

    def test_fallback_has_english_greetings(self):
        with patch("app.domains.registry.get_domain_registry") as mock_reg:
            mock_reg.return_value.get.return_value = None
            greetings = _get_domain_greetings("nonexistent")
        assert "hello" in greetings
        assert "thanks" in greetings


class TestDirectAnswerTimeoutProfile:
    def test_zhipu_identity_turn_uses_structured_timeout_profile(self):
        assert _resolve_direct_answer_timeout_profile(
            provider_name="zhipu",
            is_identity_turn=True,
            is_short_house_chatter=False,
            use_house_voice_direct=False,
            tools_bound=False,
        ) == "structured"

    def test_google_identity_turn_keeps_default_timeout_profile(self):
        assert _resolve_direct_answer_timeout_profile(
            provider_name="google",
            is_identity_turn=True,
            is_short_house_chatter=False,
            use_house_voice_direct=False,
            tools_bound=False,
        ) is None

    def test_tool_bound_turn_keeps_existing_timeout_path(self):
        assert _resolve_direct_answer_timeout_profile(
            provider_name="zhipu",
            is_identity_turn=True,
            is_short_house_chatter=True,
            use_house_voice_direct=True,
            tools_bound=True,
        ) is None

    @pytest.mark.asyncio
    async def test_direct_response_node_uses_house_voice_for_obvious_social_turn(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        state = {
            "query": "Xin chào hảo hán",
            "context": {},
            "domain_config": {},
            "provider": "zhipu",
            "routing_metadata": {"method": "always_on_social_fast_path", "intent": "social"},
        }

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ) as mock_get_llm, patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([], False),
        ) as mock_collect_tools, patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ) as mock_build_messages, patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=AsyncMock(return_value=(SimpleNamespace(content="Chào hảo hán~", tool_calls=[]), [], [])),
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("Chào hảo hán~", "", []),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="Mình bắt nhịp câu chào này để mở nhịp trò chuyện tự nhiên."),
        ):
            result = await direct_response_node(state)

        assert "hảo hán" in result["final_response"]
        assert mock_get_llm.call_args.kwargs["provider_override"] == "zhipu"
        mock_collect_tools.assert_not_called()
        assert mock_build_messages.call_args.kwargs["role_name"] == "direct_chatter_agent"
        assert mock_build_messages.call_args.kwargs["history_limit"] == 0
        assert mock_build_messages.call_args.kwargs["tools_context_override"] == ""
        fake_tracer.end_step.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_response_node_uses_house_voice_for_laughter_social_turn(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        state = {
            "query": "hẹ hẹ",
            "context": {},
            "domain_config": {},
            "provider": "zhipu",
            "routing_metadata": {"method": "always_on_social_fast_path", "intent": "social"},
        }

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ) as mock_get_llm, patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([], False),
        ) as mock_collect_tools, patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ) as mock_build_messages, patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=AsyncMock(return_value=(SimpleNamespace(content="Hẹ hẹ~ mình ở đây nè.", tool_calls=[]), [], [])),
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("Hẹ hẹ~ mình ở đây nè.", "", []),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="Mình bắt nhịp tiếng cười nhẹ này để đáp lại có hồn hơn."),
        ):
            result = await direct_response_node(state)

        assert "Hẹ hẹ" in result["final_response"]
        assert mock_get_llm.call_args.kwargs["provider_override"] == "zhipu"
        mock_collect_tools.assert_not_called()
        assert mock_build_messages.call_args.kwargs["role_name"] == "direct_chatter_agent"
        assert mock_build_messages.call_args.kwargs["history_limit"] == 0
        assert mock_build_messages.call_args.kwargs["tools_context_override"] == ""
        fake_tracer.end_step.assert_called_once()


    @pytest.mark.asyncio
    async def test_direct_response_node_uses_house_voice_for_reaction_turn(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        state = {
            "query": "wow",
            "context": {},
            "domain_config": {},
            "provider": "zhipu",
            "routing_metadata": {"method": "always_on_chatter_fast_path", "intent": "social"},
        }

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ) as mock_get_llm, patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([], False),
        ) as mock_collect_tools, patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ) as mock_build_messages, patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=AsyncMock(return_value=(SimpleNamespace(content="Woa~", tool_calls=[]), [], [])),
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("Woa~", "", []),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="Mình giữ nhịp tự nhiên cho câu trò chuyện ngắn này."),
        ):
            result = await direct_response_node(state)

        assert result["final_response"] == "Woa~"
        assert mock_get_llm.call_args.kwargs["provider_override"] == "zhipu"
        mock_collect_tools.assert_not_called()
        assert mock_build_messages.call_args.kwargs["role_name"] == "direct_chatter_agent"
        assert mock_build_messages.call_args.kwargs["history_limit"] == 0
        assert mock_build_messages.call_args.kwargs["tools_context_override"] == ""
        fake_tracer.end_step.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_response_node_uses_house_voice_for_vague_banter_turn(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        state = {
            "query": "gì đó",
            "context": {},
            "domain_config": {},
            "provider": "zhipu",
            "routing_metadata": {"method": "always_on_chatter_fast_path", "intent": "off_topic"},
        }

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ) as mock_get_llm, patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([], False),
        ) as mock_collect_tools, patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ) as mock_build_messages, patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=AsyncMock(return_value=(SimpleNamespace(content="Bạn thả lửng một ý nhỏ nè~", tool_calls=[]), [], [])),
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("Bạn thả lửng một ý nhỏ nè~", "", []),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="Mình giữ nhịp mở để bạn nối tiếp dễ hơn."),
        ):
            result = await direct_response_node(state)

        assert "ý nhỏ" in result["final_response"]
        assert mock_get_llm.call_args.kwargs["provider_override"] == "zhipu"
        mock_collect_tools.assert_not_called()
        assert mock_build_messages.call_args.kwargs["role_name"] == "direct_chatter_agent"
        assert mock_build_messages.call_args.kwargs["history_limit"] == 0
        assert mock_build_messages.call_args.kwargs["tools_context_override"] == ""
        fake_tracer.end_step.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_response_node_keeps_identity_turn_on_full_prompt_without_tools(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        state = {
            "query": "ban la ai",
            "context": {},
            "domain_config": {},
            "provider": "zhipu",
            "routing_metadata": {"method": "structured", "intent": "selfhood"},
            "_routing_hint": {"kind": "identity_probe", "intent": "selfhood", "shape": "identity"},
        }

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ) as mock_get_llm, patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([], False),
        ) as mock_collect_tools, patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ) as mock_build_messages, patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=AsyncMock(return_value=(SimpleNamespace(content="MÃ¬nh lÃ  Wiii.", tool_calls=[]), [], [])),
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("MÃ¬nh lÃ  Wiii.", "", []),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="MÃ¬nh Ä‘ang cháº¡m láº¡i pháº§n tá»± thÃ¢n cá»§a Wiii trÆ°á»›c khi tráº£ lá»i."),
        ):
            result = await direct_response_node(state)

        assert "Wiii" in result["final_response"]
        assert mock_get_llm.call_args.kwargs["provider_override"] == "zhipu"
        assert mock_get_llm.call_args.args[0] == "direct_identity"
        mock_collect_tools.assert_not_called()
        assert mock_build_messages.call_args.kwargs["role_name"] == "direct_chatter_agent"
        assert mock_build_messages.call_args.kwargs["history_limit"] >= 6
        assert mock_build_messages.call_args.kwargs["tools_context_override"] is None
        fake_tracer.end_step.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_response_node_keeps_house_provider_for_llm_but_preserves_auto_failover(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        state = {
            "query": "ban la ai",
            "context": {},
            "domain_config": {},
            "provider": "auto",
            "_house_routing_provider": "google",
            "routing_metadata": {"method": "structured", "intent": "selfhood"},
            "_routing_hint": {"kind": "identity_probe", "intent": "selfhood", "shape": "identity"},
        }

        execute_direct_tool_rounds = AsyncMock(
            return_value=(SimpleNamespace(content="Mình là Wiii.", tool_calls=[]), [], [])
        )

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ) as mock_get_llm, patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([], False),
        ) as mock_collect_tools, patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=execute_direct_tool_rounds,
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("Mình là Wiii.", "", []),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="Mình chỉ cần đáp thật và đứng đúng là Wiii thôi."),
        ):
            result = await direct_response_node(state)

        assert result["final_response"] == "Mình là Wiii."
        assert mock_get_llm.call_args.kwargs["provider_override"] == "google"
        assert execute_direct_tool_rounds.await_args.kwargs["provider"] is None
        mock_collect_tools.assert_not_called()
        fake_tracer.end_step.assert_called_once()

    def test_public_reasoning_delta_chunks_keep_interval_body(self):
        beat = SimpleNamespace(
            summary=(
                "Câu này cần một nhịp đáp chậm và thật hơn là một lời giải thích vội.\n\n"
                "Mình muốn mở lời vừa đủ dịu để nếu bạn muốn kể tiếp thì vẫn còn chỗ cho nhịp đó đi ra."
            ),
            delta_chunks=[
                "Câu này cần một nhịp đáp chậm và thật hơn là một lời giải thích vội.",
                "Mình muốn mở lời vừa đủ dịu để nếu bạn muốn kể tiếp thì vẫn còn chỗ cho nhịp đó đi ra.",
            ],
        )

        assert _public_reasoning_delta_chunks(beat) == [
            "Câu này cần một nhịp đáp chậm và thật hơn là một lời giải thích vội.",
            "Mình muốn mở lời vừa đủ dịu để nếu bạn muốn kể tiếp thì vẫn còn chỗ cho nhịp đó đi ra.",
        ]

    def test_capture_public_thinking_event_only_uses_thinking_deltas(self):
        state = {"_public_thinking_fragments": []}

        _capture_public_thinking_event(
            state,
            {"type": "thinking_start", "summary": "Mình muốn mở lời vừa đủ dịu."},
        )
        _capture_public_thinking_event(
            state,
            {"type": "thinking_delta", "content": "Mình muốn mở lời vừa đủ dịu."},
        )
        _capture_public_thinking_event(
            state,
            {"type": "thinking_delta", "content": "Mình muốn mở lời vừa đủ dịu."},
        )
        _capture_public_thinking_event(
            state,
            {"type": "status", "content": "iteration=0"},
        )

        assert state["_public_thinking_fragments"] == ["Mình muốn mở lời vừa đủ dịu."]

    def test_capture_public_thinking_event_redacts_secret_text(self):
        state = {"_public_thinking_fragments": []}

        _capture_public_thinking_event(
            state,
            {
                "type": "thinking_start",
                "content": "Bearer raw-start-token-12345678",
                "node": "direct",
                "details": {"access_token": "raw-access-token"},
            },
        )
        _capture_public_thinking_event(
            state,
            {
                "type": "thinking_delta",
                "content": "Mình kiểm tra Bearer raw-delta-token-12345678",
                "node": "direct",
            },
        )

        serialized = str(state)
        assert "<redacted-secret>" in serialized
        assert "raw-start-token-12345678" not in serialized
        assert "raw-access-token" not in serialized
        assert "raw-delta-token-12345678" not in serialized

    def test_resolve_public_thinking_content_prefers_interval_fragments_over_summary(self):
        state = {
            "_public_thinking_fragments": [
                "Câu này cần một nhịp đáp chậm và thật hơn là một lời giải thích vội.",
                "Mình muốn mở lời vừa đủ dịu để nếu bạn muốn kể tiếp thì vẫn còn chỗ cho nhịp đó đi ra.",
            ],
            "thinking_content": "Nhịp này không cần kéo dài quá tay.",
        }

        assert _resolve_public_thinking_content(state, fallback="fallback") == (
            "Câu này cần một nhịp đáp chậm và thật hơn là một lời giải thích vội.\n\n"
            "Mình muốn mở lời vừa đủ dịu để nếu bạn muốn kể tiếp thì vẫn còn chỗ cho nhịp đó đi ra."
        )

    @pytest.mark.asyncio
    async def test_direct_response_node_prefers_interval_fragments_for_final_thinking_content(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        state = {
            "query": "buon qua",
            "context": {},
            "domain_config": {},
            "provider": "auto",
            "routing_metadata": {"method": "structured", "intent": "emotional"},
            "_routing_hint": {"kind": "emotional_support", "intent": "emotional"},
            "_public_thinking_fragments": [],
        }

        async def _fake_execute(*args, **kwargs):
            working_state = kwargs["state"]
            working_state["_public_thinking_fragments"] = [
                "Câu này cần một nhịp đáp chậm và thật hơn là một lời giải thích vội.",
                "Mình muốn mở lời vừa đủ dịu để nếu bạn muốn kể tiếp thì vẫn còn chỗ cho nhịp đó đi ra.",
            ]
            return SimpleNamespace(content="Mình ở đây với bạn.", tool_calls=[]), [], []

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ), patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([], False),
        ), patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=AsyncMock(side_effect=_fake_execute),
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("Mình ở đây với bạn.", "", []),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="Nhịp này không cần kéo dài quá tay."),
        ):
            result = await direct_response_node(state)

        assert result["thinking_content"] == (
            "Câu này cần một nhịp đáp chậm và thật hơn là một lời giải thích vội.\n\n"
            "Mình muốn mở lời vừa đủ dịu để nếu bạn muốn kể tiếp thì vẫn còn chỗ cho nhịp đó đi ra."
        )
        assert result["final_response"] == "Mình ở đây với bạn."
        fake_tracer.end_step.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_response_node_backfills_emotional_thinking_without_native_or_fragments(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        state = {
            "query": "minh buon qua",
            "context": {},
            "domain_config": {},
            "provider": "auto",
            "routing_metadata": {"method": "structured", "intent": "emotional"},
            "_routing_hint": {"kind": "emotional_support", "intent": "emotional"},
            "_public_thinking_fragments": [],
        }

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ), patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([], False),
        ), patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=AsyncMock(return_value=(SimpleNamespace(content="Mình ở đây.", tool_calls=[]), [], [])),
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("Mình ở đây.", "", []),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="Câu này cần một nhịp đáp chậm và thật hơn là một lời giải thích vội."),
        ):
            result = await direct_response_node(state)

        assert result.get("thinking_content", "") == "Câu này cần một nhịp đáp chậm và thật hơn là một lời giải thích vội."
        assert "khoảng chùng xuống" not in result.get("thinking_content", "").lower()

    @pytest.mark.asyncio
    async def test_direct_response_node_surfaces_model_visible_thought_for_emotional_turns(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        state = {
            "query": "minh thay te qua",
            "context": {},
            "domain_config": {},
            "provider": "auto",
            "routing_metadata": {"method": "structured", "intent": "social"},
            "_routing_hint": {"kind": "emotional_support", "intent": "social"},
            "_public_thinking_fragments": [],
        }

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ), patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([], False),
        ), patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=AsyncMock(return_value=(SimpleNamespace(content="ignored", tool_calls=[]), [], [])),
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=(
                "Oi, nghe ban noi ma minh thay lo qua.",
                "Nguoi ban cua minh dang thay khong on, minh muon hoi tham nhe thoi.",
                [],
            ),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="template narrator should not win"),
        ):
            result = await direct_response_node(state)

        assert result["final_response"] == "Oi, nghe ban noi ma minh thay lo qua."
        assert result["thinking_content"] == "Nguoi ban cua minh dang thay khong on, minh muon hoi tham nhe thoi."
        assert result["thinking"] == "Nguoi ban cua minh dang thay khong on, minh muon hoi tham nhe thoi."

# =============================================================================
# Tests: request-scoped failover delegation
# =============================================================================


class TestGraphFailoverDelegation:
    @pytest.mark.asyncio
    async def test_fallback_rebind_preserves_provider_specific_tool_choice(self):
        tools = [
            SimpleNamespace(name="tool_web_search"),
            SimpleNamespace(name="tool_get_current_datetime"),
        ]

        class FakeFallbackLLM:
            def __init__(self):
                self._wiii_provider_name = "openai"
                self.bind_calls: list[str | None] = []

            def bind_tools(self, _tools, tool_choice=None):
                self.bind_calls.append(tool_choice)
                return {"tool_choice": tool_choice}

        fallback_llm = FakeFallbackLLM()

        async def _fake_failover(_llm, _messages, **kwargs):
            prepared = kwargs["on_fallback"](fallback_llm)
            return prepared

        with patch(
            "app.engine.llm_pool.ainvoke_with_failover",
            side_effect=_fake_failover,
        ):
            result = await _ainvoke_with_fallback(
                MagicMock(),
                ["hello"],
                tools=tools,
                tool_choice="any",
                provider="google",
            )

        assert fallback_llm.bind_calls == ["required"]
        assert result == {"tool_choice": "required"}

    @pytest.mark.asyncio
    async def test_timeout_profile_is_forwarded_to_failover_helper(self):
        captured: dict[str, object] = {}

        async def _fake_failover(_llm, _messages, **kwargs):
            captured.update(kwargs)
            return {"ok": True}

        with patch(
            "app.engine.llm_pool.ainvoke_with_failover",
            side_effect=_fake_failover,
        ):
            result = await _ainvoke_with_fallback(
                MagicMock(),
                ["hello"],
                timeout_profile="background",
            )

        assert captured["timeout_profile"] == "background"
        assert result == {"ok": True}


# =============================================================================
# Tests: supervisor_node adaptive thinking for visual/code quality
# =============================================================================

class TestSupervisorNodeThinkingEffort:
    @pytest.mark.asyncio
    async def test_escalates_recipe_backed_premium_simulation_to_high_when_not_explicit(self):
        state = {
            "query": "Hãy mô phỏng vật lý con lắc có thể kéo thả chuột",
            "context": {},
        }
        result_state = {
            "query": state["query"],
            "context": {},
            "routing_metadata": {"intent": "code_execution"},
            "next_agent": "code_studio_agent",
        }
        fake_supervisor = SimpleNamespace(process=AsyncMock(return_value=result_state))
        fake_registry = SimpleNamespace(tracer=SimpleNamespace(span=lambda *args, **kwargs: nullcontext()))
        fake_tracer = MagicMock()

        with patch("app.engine.multi_agent.graph.get_supervisor_agent", return_value=fake_supervisor), \
             patch("app.engine.multi_agent.graph.get_agent_registry", return_value=fake_registry), \
             patch("app.engine.multi_agent.graph.get_reasoning_tracer", return_value=fake_tracer):
            result = await supervisor_node(state)

        assert result["thinking_effort"] == "max"

    @pytest.mark.asyncio
    async def test_preserves_explicit_thinking_effort(self):
        state = {
            "query": "Hãy mô phỏng vật lý con lắc có thể kéo thả chuột",
            "context": {},
            "thinking_effort": "low",
        }
        result_state = {
            "query": state["query"],
            "context": {},
            "routing_metadata": {"intent": "code_execution"},
            "next_agent": "code_studio_agent",
        }
        fake_supervisor = SimpleNamespace(process=AsyncMock(return_value=result_state))
        fake_registry = SimpleNamespace(tracer=SimpleNamespace(span=lambda *args, **kwargs: nullcontext()))
        fake_tracer = MagicMock()

        with patch("app.engine.multi_agent.graph.get_supervisor_agent", return_value=fake_supervisor), \
             patch("app.engine.multi_agent.graph.get_agent_registry", return_value=fake_registry), \
             patch("app.engine.multi_agent.graph.get_reasoning_tracer", return_value=fake_tracer):
            result = await supervisor_node(state)

        assert result["thinking_effort"] == "low"


# =============================================================================
# Tests: _collect_code_studio_tools
# =============================================================================

class TestCollectCodeStudioTools:
    @patch("app.engine.multi_agent.graph.settings")
    @patch("app.engine.multi_agent.graph.filter_tools_for_visual_intent")
    @patch("app.engine.multi_agent.graph.filter_tools_for_role")
    @patch("app.engine.tools.output_generation_tools.get_output_generation_tools")
    @patch("app.engine.tools.visual_tools.get_visual_tools")
    @patch("app.engine.tools.chart_tools.get_chart_tools")
    def test_restricts_clear_app_requests_to_preferred_tool(
        self,
        mock_chart_tools,
        mock_visual_tools,
        mock_output_tools,
        mock_filter_role,
        mock_filter_visual,
        mock_settings,
    ):
        mock_settings.enable_code_execution = False
        mock_settings.enable_browser_agent = False
        mock_settings.enable_privileged_sandbox = False
        mock_settings.sandbox_provider = ""
        mock_settings.sandbox_allow_browser_workloads = False
        mock_settings.enable_structured_visuals = True

        tool_create_visual_code = SimpleNamespace(name="tool_create_visual_code")
        tool_generate_visual = SimpleNamespace(name="tool_generate_visual")
        tool_generate_html_file = SimpleNamespace(name="tool_generate_html_file")

        mock_chart_tools.return_value = [tool_generate_visual]
        mock_visual_tools.return_value = [tool_create_visual_code]
        mock_output_tools.return_value = [tool_generate_html_file]
        mock_filter_role.side_effect = lambda tools, user_role: tools
        mock_filter_visual.side_effect = lambda tools, *_args, **_kwargs: tools

        tools, force_tools = _collect_code_studio_tools(
            "Build a mini pendulum physics app in chat with drag interaction",
            "student",
        )

        assert force_tools is True
        assert [tool.name for tool in tools] == ["tool_create_visual_code"]


class TestCollectDirectTools:
    @patch("app.engine.multi_agent.graph.settings")
    @patch("app.engine.multi_agent.graph.filter_tools_for_visual_intent")
    @patch("app.engine.multi_agent.graph.filter_tools_for_role")
    @patch("app.engine.tools.visual_tools.get_visual_tools")
    @patch("app.engine.tools.chart_tools.get_chart_tools")
    @patch("app.engine.tools.rag_tools.tool_knowledge_search")
    def test_restricts_clear_chart_visual_requests_to_preferred_tool(
        self,
        mock_knowledge_search,
        mock_chart_tools,
        mock_visual_tools,
        mock_filter_role,
        mock_filter_visual,
        mock_settings,
    ):
        mock_settings.enable_character_tools = False
        mock_settings.enable_code_execution = False
        mock_settings.enable_structured_visuals = True

        tool_generate_visual = SimpleNamespace(name="tool_generate_visual")
        tool_generate_chart = SimpleNamespace(name="tool_generate_interactive_chart")

        mock_knowledge_search.name = "tool_knowledge_search"
        mock_chart_tools.return_value = [tool_generate_chart]
        mock_visual_tools.return_value = [tool_generate_visual]
        mock_filter_role.side_effect = lambda tools, user_role: tools
        mock_filter_visual.side_effect = lambda tools, *_args, **_kwargs: tools

        tools, force_tools = _collect_direct_tools(
            "Ve bieu do so sanh toc do cac loai tau container.",
            "student",
        )

        assert force_tools is True
        assert [tool.name for tool in tools] == ["tool_generate_visual"]

    @patch("app.engine.multi_agent.graph.settings")
    @patch("app.engine.multi_agent.graph.filter_tools_for_visual_intent")
    @patch("app.engine.multi_agent.graph.filter_tools_for_role")
    @patch("app.engine.tools.visual_tools.get_visual_tools")
    @patch("app.engine.tools.chart_tools.get_chart_tools")
    @patch("app.engine.tools.lms_tools.get_all_lms_tools")
    @patch("app.engine.tools.rag_tools.tool_knowledge_search")
    def test_plain_quiz_study_turn_without_creation_verbs_does_not_force_code_visual_tools(
        self,
        mock_knowledge_search,
        mock_get_lms_tools,
        mock_chart_tools,
        mock_visual_tools,
        mock_filter_role,
        mock_filter_visual,
        mock_settings,
    ):
        mock_settings.enable_character_tools = False
        mock_settings.enable_code_execution = False
        mock_settings.enable_structured_visuals = True
        mock_settings.enable_lms_integration = True

        mock_knowledge_search.name = "tool_knowledge_search"
        mock_chart_tools.return_value = [SimpleNamespace(name="tool_generate_interactive_chart")]
        mock_visual_tools.return_value = [
            SimpleNamespace(name="tool_generate_visual"),
            SimpleNamespace(name="tool_create_visual_code"),
        ]
        mock_get_lms_tools.return_value = [SimpleNamespace(name="tool_lms_get_progress")]
        mock_filter_role.side_effect = lambda tools, user_role: tools
        mock_filter_visual.side_effect = lambda tools, *_args, **_kwargs: tools

        tools, force_tools = _collect_direct_tools(
            "Cho minh bo quiz tieng Trung de on tap duoc khong?",
            "student",
        )

        tool_names = [tool.name for tool in tools]
        assert force_tools is False
        assert "tool_create_visual_code" not in tool_names
        assert "tool_generate_visual" not in tool_names


class TestDirectKnowledgeSearchGating:
    @patch("app.engine.multi_agent.graph.settings")
    @patch("app.engine.multi_agent.graph.filter_tools_for_visual_intent")
    @patch("app.engine.multi_agent.graph.filter_tools_for_role")
    @patch("app.engine.tools.visual_tools.get_visual_tools")
    @patch("app.engine.tools.chart_tools.get_chart_tools")
    @patch("app.engine.tools.rag_tools.tool_knowledge_search")
    def test_social_turn_does_not_bind_knowledge_search(
        self,
        mock_knowledge_search,
        mock_chart_tools,
        mock_visual_tools,
        mock_filter_role,
        mock_filter_visual,
        mock_settings,
    ):
        mock_settings.enable_character_tools = False
        mock_settings.enable_code_execution = False
        mock_settings.enable_structured_visuals = True
        mock_settings.enable_lms_integration = False

        mock_knowledge_search.name = "tool_knowledge_search"
        mock_chart_tools.return_value = [SimpleNamespace(name="tool_generate_interactive_chart")]
        mock_visual_tools.return_value = [SimpleNamespace(name="tool_generate_visual")]
        mock_filter_role.side_effect = lambda tools, user_role: tools
        mock_filter_visual.side_effect = lambda tools, *_args, **_kwargs: tools

        tools, force_tools = _collect_direct_tools(
            "có thể uống rượu thưởng trăng không ?",
            "student",
        )

        tool_names = [tool.name for tool in tools]
        assert force_tools is False
        assert "tool_knowledge_search" not in tool_names
        assert "tool_knowledge_search" not in _direct_required_tool_names(
            "có thể uống rượu thưởng trăng không ?",
            "student",
        )

    @patch("app.engine.multi_agent.graph.settings")
    @patch("app.engine.multi_agent.graph.filter_tools_for_visual_intent")
    @patch("app.engine.multi_agent.graph.filter_tools_for_role")
    @patch("app.engine.tools.visual_tools.get_visual_tools")
    @patch("app.engine.tools.chart_tools.get_chart_tools")
    @patch("app.engine.tools.rag_tools.tool_knowledge_search")
    def test_visual_turn_does_not_bind_knowledge_search(
        self,
        mock_knowledge_search,
        mock_chart_tools,
        mock_visual_tools,
        mock_filter_role,
        mock_filter_visual,
        mock_settings,
    ):
        mock_settings.enable_character_tools = False
        mock_settings.enable_code_execution = False
        mock_settings.enable_structured_visuals = True
        mock_settings.enable_lms_integration = False

        mock_knowledge_search.name = "tool_knowledge_search"
        mock_chart_tools.return_value = [SimpleNamespace(name="tool_generate_interactive_chart")]
        mock_visual_tools.return_value = [SimpleNamespace(name="tool_generate_visual")]
        mock_filter_role.side_effect = lambda tools, user_role: tools
        mock_filter_visual.side_effect = lambda tools, *_args, **_kwargs: tools

        tools, force_tools = _collect_direct_tools(
            "Visual cho mình xem thống kê dữ liệu hiện tại giá dầu mấy ngày gần đây",
            "student",
        )

        tool_names = [tool.name for tool in tools]
        assert force_tools is True
        assert "tool_knowledge_search" not in tool_names
        assert "tool_knowledge_search" not in _direct_required_tool_names(
            "Visual cho mình xem thống kê dữ liệu hiện tại giá dầu mấy ngày gần đây",
            "student",
        )

    @patch("app.engine.multi_agent.graph.settings")
    @patch("app.engine.multi_agent.graph.filter_tools_for_visual_intent")
    @patch("app.engine.multi_agent.graph.filter_tools_for_role")
    @patch("app.engine.tools.visual_tools.get_visual_tools")
    @patch("app.engine.tools.chart_tools.get_chart_tools")
    @patch("app.engine.tools.rag_tools.tool_knowledge_search")
    def test_explicit_retrieval_turn_keeps_knowledge_search(
        self,
        mock_knowledge_search,
        mock_chart_tools,
        mock_visual_tools,
        mock_filter_role,
        mock_filter_visual,
        mock_settings,
    ):
        mock_settings.enable_character_tools = False
        mock_settings.enable_code_execution = False
        mock_settings.enable_structured_visuals = True
        mock_settings.enable_lms_integration = False

        mock_knowledge_search.name = "tool_knowledge_search"
        mock_chart_tools.return_value = [SimpleNamespace(name="tool_generate_interactive_chart")]
        mock_visual_tools.return_value = [SimpleNamespace(name="tool_generate_visual")]
        mock_filter_role.side_effect = lambda tools, user_role: tools
        mock_filter_visual.side_effect = lambda tools, *_args, **_kwargs: tools

        tools, force_tools = _collect_direct_tools(
            "Tra cứu tài liệu nội bộ về quy định an toàn hàng hải",
            "student",
        )

        tool_names = [tool.name for tool in tools]
        assert "tool_knowledge_search" in tool_names
        assert "tool_knowledge_search" in _direct_required_tool_names(
            "Tra cứu tài liệu nội bộ về quy định an toàn hàng hải",
            "student",
        )


class TestPendulumCodeStudioFastPath:
    def test_uses_fast_path_for_clear_pendulum_build_request(self):
        state = {"context": {"code_studio_context": {}}}

        assert _should_use_pendulum_code_studio_fast_path(
            "Build a mini pendulum physics app in chat with drag interaction. Use Code Studio inline.",
            state,
        ) is True

    def test_uses_fast_path_for_pendulum_follow_up_patch_from_active_session(self):
        state = {
            "context": {
                "code_studio_context": {
                    "active_session": {
                        "session_id": "vs-1",
                        "title": "Mini Pendulum Physics App",
                    }
                }
            }
        }

        assert _should_use_pendulum_code_studio_fast_path(
            "Keep the current app and add gravity and damping sliders.",
            state,
        ) is True

    def test_skips_fast_path_when_user_is_explicitly_requesting_code_view(self):
        state = {
            "context": {
                "code_studio_context": {
                    "requested_view": "code",
                    "active_session": {
                        "session_id": "vs-1",
                        "title": "Mini Pendulum Physics App",
                    },
                }
            }
        }

        assert _should_use_pendulum_code_studio_fast_path(
            "Show me the code you are generating.",
            state,
        ) is False

    def test_prefers_active_session_title_for_fast_path_title(self):
        state = {
            "context": {
                "code_studio_context": {
                    "active_session": {
                        "session_id": "vs-1",
                        "title": "Mo phong con lac",
                    }
                }
            }
        }

        assert _infer_pendulum_fast_path_title("Add damping slider", state) == "Mo phong con lac"


class TestSimulationClarifier:
    def test_detects_bare_simulation_followup(self):
        state = {
            "context": {
                "visual_context": {
                    "last_visual_title": "Kimi linear attention",
                }
            }
        }

        assert _looks_like_ambiguous_simulation_request(
            "Wiii tao mo phong cho minh duoc chu ?",
            state,
        ) is True

    def test_clarifier_mentions_last_visual_title(self):
        state = {
            "context": {
                "visual_context": {
                    "last_visual_title": "Kimi linear attention",
                }
            }
        }

        response = _build_ambiguous_simulation_clarifier(state)
        assert "Kimi linear attention" in response
        assert "canvas" in response

    def test_grounded_query_uses_active_visual_title(self):
        state = {
            "context": {
                "visual_context": {
                    "last_visual_title": "Kimi linear attention",
                }
            }
        }

        grounded = _ground_simulation_query_from_visual_context(
            "Wiii tao mo phong cho minh duoc chu ?",
            state,
        )

        assert "Kimi linear attention" in grounded
        assert "canvas" in grounded
        assert "follow-up" in grounded

    @pytest.mark.asyncio
    async def test_code_studio_node_grounds_ambiguous_simulation_followup_from_visual_context(self):
        state = {
            "query": "Wiii tao mo phong cho minh duoc chu ?",
            "context": {
                "visual_context": {
                    "last_visual_title": "Kimi linear attention",
                }
            },
            "domain_id": "maritime",
            "domain_config": {},
        }
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        captured = {}

        async def fake_execute(*_args, **kwargs):
            captured["query"] = kwargs.get("query")
            return SimpleNamespace(content=""), [], []

        with patch("app.engine.multi_agent.graph._get_or_create_tracer", return_value=fake_tracer), \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._build_code_studio_reasoning_summary", new=AsyncMock(return_value="grounded")) as _mock_summary, \
             patch("app.engine.multi_agent.graph._execute_code_studio_tool_rounds", new=AsyncMock(side_effect=fake_execute)), \
             patch("app.engine.multi_agent.graph._bind_direct_tools", return_value=(fake_llm, fake_llm, "any")), \
             patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=fake_llm) as mock_get_llm:
            mock_settings.default_domain = "maritime"
            mock_settings.enable_natural_conversation = False

            result = await code_studio_node(state)

        mock_get_llm.assert_called_once()
        assert "Kimi linear attention" in captured["query"]
        assert result["final_response"] == ""
        assert result["current_agent"] == "code_studio_agent"

    @pytest.mark.asyncio
    async def test_code_studio_node_still_clarifies_when_no_visual_context_exists(self):
        state = {
            "query": "Wiii tao mo phong cho minh duoc chu ?",
            "context": {},
            "domain_id": "maritime",
            "domain_config": {},
        }
        fake_tracer = MagicMock()

        with patch("app.engine.multi_agent.graph._get_or_create_tracer", return_value=fake_tracer), \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._build_code_studio_reasoning_summary", new=AsyncMock(return_value="clarify")) as _mock_summary, \
             patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm") as mock_get_llm:
            mock_settings.default_domain = "maritime"
            mock_settings.enable_natural_conversation = False

            result = await code_studio_node(state)

        mock_get_llm.assert_not_called()
        assert "chưa nói rõ hiện tượng nào" in result["final_response"]
        assert result["current_agent"] == "code_studio_agent"


    @pytest.mark.asyncio
    async def test_code_studio_node_runs_recipe_fast_path_before_provider_selection(self):
        from app.core.exceptions import ProviderUnavailableError

        state = {
            "query": "mo phong COLREG rule 15",
            "context": {},
            "domain_id": "maritime",
            "domain_config": {},
        }
        fake_tracer = MagicMock()
        fast_path_result = CodeStudioFastPathResult(
            response="opened deterministic visual preview",
            thinking_content="deterministic code studio recipe",
            tool_call_events=[],
            tools_used=[{"name": "tool_create_visual_code"}],
            fast_path="fast_colreg15",
        )

        with patch("app.engine.multi_agent.graph._get_or_create_tracer", return_value=fake_tracer), \
             patch("app.engine.multi_agent.graph.settings") as mock_settings, \
             patch("app.engine.multi_agent.graph._looks_like_ambiguous_simulation_request", return_value=False), \
             patch(
                 "app.engine.multi_agent.graph._collect_code_studio_tools",
                 return_value=([SimpleNamespace(name="tool_create_visual_code")], True),
             ), \
             patch(
                 "app.engine.multi_agent.graph._execute_code_studio_fast_path",
                 new=AsyncMock(return_value=fast_path_result),
             ) as mock_fast_path, \
             patch(
                 "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
                 side_effect=ProviderUnavailableError(
                     provider="test",
                     reason_code="not_configured",
                     message="provider unavailable",
                 ),
             ) as mock_get_llm:
            mock_settings.default_domain = "maritime"
            mock_settings.enable_natural_conversation = False

            result = await code_studio_node(state)

        mock_fast_path.assert_awaited_once()
        mock_get_llm.assert_not_called()
        assert result["final_response"] == "opened deterministic visual preview"
        assert result["tools_used"] == [{"name": "tool_create_visual_code"}]
        assert result["current_agent"] == "code_studio_agent"


class TestCodeStudioProgressHeartbeat:
    def test_code_stream_session_id_is_stable_for_same_request_id(self):
        runtime = SimpleNamespace(request_id="req-code-studio-123")

        session_a = _derive_code_stream_session_id(runtime_context_base=runtime)
        session_b = _derive_code_stream_session_id(runtime_context_base=runtime)

        assert session_a == session_b
        assert session_a.startswith("vs-stream-")

    def test_real_code_streaming_is_allowed_for_zhipu_glm5(self):
        with patch("app.core.config.get_settings", return_value=SimpleNamespace(enable_real_code_streaming=True)):
            assert _should_enable_real_code_streaming(
                "zhipu",
                llm=SimpleNamespace(_wiii_model_name="glm-5"),
            ) is True

    def test_real_code_streaming_is_allowed_for_openai_compatible_gate(self):
        with patch("app.core.config.get_settings", return_value=SimpleNamespace(enable_real_code_streaming=True)):
            assert _should_enable_real_code_streaming("openai") is True

    @pytest.mark.asyncio
    async def test_native_answer_streaming_surfaces_provider_reasoning_for_direct_lane(self):
        class _FakeDelta:
            def __init__(self, *, reasoning=None, content=None):
                self.reasoning_content = reasoning
                self.content = content

        class _FakeChoice:
            def __init__(self, delta):
                self.delta = delta

        class _FakeChunk:
            def __init__(self, delta):
                self.choices = [_FakeChoice(delta)]

        class _FakeStream:
            def __init__(self, chunks):
                self._chunks = chunks

            def __aiter__(self):
                self._iter = iter(self._chunks)
                return self

            async def __anext__(self):
                try:
                    return next(self._iter)
                except StopIteration as exc:
                    raise StopAsyncIteration from exc

        class _FakeCompletions:
            def __init__(self, chunks):
                self._chunks = chunks

            async def create(self, **_kwargs):
                return _FakeStream(self._chunks)

        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=_FakeCompletions(
                    [
                        _FakeChunk(_FakeDelta(reasoning="raw hidden scratchpad")),
                        _FakeChunk(_FakeDelta(content="Xin ")),
                        _FakeChunk(_FakeDelta(content="chao")),
                    ]
                )
            )
        )
        route = SimpleNamespace(
            provider="zhipu",
            llm=SimpleNamespace(_wiii_tier_key="moderate"),
        )
        events = []
        thinking_stop = asyncio.Event()

        async def push_event(event):
            events.append(event)

        with patch(
            "app.engine.multi_agent.graph._create_openai_compatible_stream_client",
            return_value=fake_client,
        ), patch(
            "app.engine.multi_agent.graph._resolve_openai_stream_model_name",
            return_value="glm-4.5-air",
        ):
            response, streamed = await _stream_openai_compatible_answer_with_route(
                route,
                [],
                push_event,
                node="direct",
                thinking_stop_signal=thinking_stop,
            )

        assert streamed is True
        assert thinking_stop.is_set() is True
        assert response.content == "Xin chao"
        assert [event["type"] for event in events] == [
            "thinking_start",
            "thinking_delta",
            "thinking_end",
            "answer_delta",
            "answer_delta",
        ]
        assert any(event.get("content") == "raw hidden scratchpad" for event in events)

    @pytest.mark.asyncio
    async def test_stream_answer_with_fallback_strips_google_thinking_tags_from_direct_answer(self):
        class FakeChunk:
            def __init__(self, content: str):
                self.content = content

            def __add__(self, other):
                return FakeChunk(self.content + getattr(other, "content", ""))

        class FakeLLM:
            _wiii_tier_key = "deep"

            async def astream(self, _messages):
                yield FakeChunk("<thinking>Câu này chạm vào mình.")
                yield FakeChunk("</thinking>Chào bạn! ")
                yield FakeChunk("Mình là Wiii.")

        fake_llm = FakeLLM()
        events = []
        thinking_stop = asyncio.Event()

        async def push_event(event):
            events.append(event)

        with patch(
            "app.engine.multi_agent.graph._stream_openai_compatible_answer_with_route",
            new=AsyncMock(return_value=(None, False)),
        ), patch(
            "app.engine.llm_pool.LLMPool.resolve_runtime_route",
            return_value=SimpleNamespace(llm=fake_llm),
        ):
            response, streamed = await _stream_answer_with_fallback(
                fake_llm,
                [],
                push_event,
                provider="google",
                node="direct",
                thinking_stop_signal=thinking_stop,
            )

        assert streamed is True
        assert response.content == "Chào bạn! Mình là Wiii."
        assert thinking_stop.is_set() is True
        answer_events = [event["content"] for event in events if event["type"] == "answer_delta"]
        assert answer_events == ["Chào bạn! ", "Mình là Wiii."]
        assert not any("<thinking>" in chunk for chunk in answer_events)

    @pytest.mark.asyncio
    async def test_stream_answer_with_fallback_forwards_deep_tier_to_failover_helper(self):
        class FakeLLM:
            _wiii_tier_key = "deep"

            async def astream(self, _messages):
                if False:
                    yield None
                raise RuntimeError("force fallback")

        captured = {}

        async def fake_push_event(_event):
            return None

        async def fake_ainvoke_with_fallback(_llm, _messages, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(content="fallback ok")

        with patch(
            "app.engine.multi_agent.graph._stream_openai_compatible_answer_with_route",
            new=AsyncMock(return_value=(None, False)),
        ), patch(
            "app.engine.multi_agent.direct_execution._ainvoke_with_fallback",
            new=fake_ainvoke_with_fallback,
        ), patch(
            "app.engine.llm_pool.LLMPool.resolve_runtime_route",
            return_value=SimpleNamespace(llm=FakeLLM()),
        ):
            response, streamed = await _stream_answer_with_fallback(
                FakeLLM(),
                [],
                fake_push_event,
                provider="google",
                node="direct",
            )

        assert streamed is False
        assert response.content == "fallback ok"
        assert captured["tier"] == "deep"

    def test_simulation_progress_messages_are_living_and_specific(self):
        state = {
            "context": {
                "visual_context": {
                    "last_visual_title": "Kimi linear attention",
                }
            }
        }

        messages = _build_code_studio_progress_messages(
            "Wiii tao mo phong cho minh duoc chu ?",
            state,
        )

        assert any("state model" in message for message in messages)
        assert any("canvas loop" in message for message in messages)
        assert any("Kimi linear attention" in message for message in messages)

    def test_progress_message_includes_elapsed_seconds(self):
        formatted = _format_code_studio_progress_message("Minh dang dung canvas loop...", 42.1)
        assert "(đã 42s)" in formatted

    def test_retry_status_is_honest_about_long_running_simulation(self):
        retry = _build_code_studio_retry_status(
            "Wiii tao mo phong cho minh duoc chu ?",
            {"context": {"visual_context": {"last_visual_title": "Kimi linear attention"}}},
            elapsed_seconds=240,
        )
        assert "preview thật" in retry
        assert "(đã 240s)" in retry

    @pytest.mark.asyncio
    async def test_stream_answer_suppresses_raw_code_dump_for_code_studio_lane(self):
        events: list[dict] = []

        class FakeChunk:
            def __init__(self, content: str):
                self.content = content

            def __add__(self, other):
                return FakeChunk(self.content + getattr(other, "content", ""))

        class FakeLLM:
            _wiii_tier_key = "moderate"

            async def astream(self, _messages):
                yield FakeChunk("Mình sẽ tạo một ứng dụng mô phỏng cho bạn ngay đây.\n\n")
                yield FakeChunk("```html\n<div class='demo'>Hello</div>\n```")

        async def push_event(event):
            events.append(event)

        with patch(
            "app.engine.multi_agent.graph._stream_openai_compatible_answer_with_route",
            new=AsyncMock(return_value=(None, False)),
        ), patch(
            "app.engine.llm_pool.LLMPool.resolve_runtime_route",
            return_value=SimpleNamespace(llm=FakeLLM()),
        ):
            response, streamed = await _stream_answer_with_fallback(
                FakeLLM(),
                [],
                push_event,
                provider="zhipu",
                node="code_studio_agent",
            )

        assert streamed is True
        assert getattr(response, "content", "").endswith("```")
        answer_events = [event for event in events if event["type"] == "answer_delta"]
        assert len(answer_events) == 1
        assert "ứng dụng mô phỏng" in answer_events[0]["content"]
        assert "```html" not in answer_events[0]["content"]
        assert "<div" not in answer_events[0]["content"]

    @pytest.mark.asyncio
    async def test_preserves_timeout_fallback_response_without_overwrite(self):
        from app.engine.messages import Message

        class SlowLLM:
            async def ainvoke(self, _messages):
                await asyncio.sleep(0.01)
                return Message(role="assistant", content="stale primary response")

        class FallbackLLM:
            def bind_tools(self, _tools):
                return self

            async def ainvoke(self, _messages):
                return Message(role="assistant", content="fallback recovery response")

        async def push_event(_event):
            return None

        async def fake_render_reasoning(**_kwargs):
            return SimpleNamespace(
                label="Dang tong hop",
                summary="Dang tong hop",
                phase="synthesize",
                action_text="",
                delta_chunks=[],
            )

        time_values = iter([0.0, 241.0, 241.0, 241.0, 241.0])

        with patch("app.engine.multi_agent.graph.time.time", side_effect=lambda: next(time_values, 241.0)), \
             patch("app.engine.multi_agent.graph._render_reasoning", new=fake_render_reasoning), \
             patch("app.engine.llm_pool.get_llm_moderate", return_value=FallbackLLM()):
            llm_response, _messages, _events = await _execute_code_studio_tool_rounds(
                SlowLLM(),
                SlowLLM(),
                [],
                [SimpleNamespace(name="tool_create_visual_code")],
                push_event,
                query="",
                state={},
            )

        assert "fallback recovery response" in llm_response.content

    @pytest.mark.asyncio
    async def test_returns_missing_tool_response_when_initial_code_studio_call_times_out(self):
        async def push_event(_event):
            return None

        async def fake_render_reasoning(**kwargs):
            return SimpleNamespace(
                label="Dang tong hop",
                summary="Dang tong hop",
                phase=kwargs.get("phase", "synthesize"),
                action_text="",
                delta_chunks=[],
            )

        async def fake_invoke(*_args, **_kwargs):
            raise TimeoutError("Primary LLM timed out after 25.0s, no fallback available")

        with patch("app.engine.multi_agent.graph._ainvoke_with_fallback", new=AsyncMock(side_effect=fake_invoke)), \
             patch("app.engine.multi_agent.graph._render_reasoning", new=fake_render_reasoning):
            llm_response, _messages, _events = await _execute_code_studio_tool_rounds(
                MagicMock(),
                MagicMock(),
                [],
                [SimpleNamespace(name="tool_create_visual_code")],
                push_event,
                query="Tạo mô phỏng hảo hán uống rượu ngắm trăng xem",
                state={},
            )

        assert "mở đúng lane mô phỏng" in llm_response.content.lower()


class TestBindDirectTools:
    def test_forces_exact_tool_name_when_single_tool_is_bound(self):
        class FakeLLM:
            def __init__(self):
                self.calls = []

            def bind_tools(self, tools, tool_choice=None):
                self.calls.append({
                    "tools": tools,
                    "tool_choice": tool_choice,
                })
                return {"tool_choice": tool_choice, "count": len(tools)}

        llm = FakeLLM()
        tool = SimpleNamespace(name="tool_create_visual_code")

        llm_with_tools, llm_auto, forced_choice = _bind_direct_tools(llm, [tool], True)

        assert llm.calls[0]["tool_choice"] is None
        assert llm.calls[1]["tool_choice"] == "tool_create_visual_code"
        assert llm_auto["tool_choice"] is None
        assert llm_with_tools["tool_choice"] == "tool_create_visual_code"
        assert forced_choice == "tool_create_visual_code"

    def test_keeps_any_when_multiple_tools_are_bound(self):
        class FakeLLM:
            def __init__(self):
                self.calls = []

            def bind_tools(self, tools, tool_choice=None):
                self.calls.append(tool_choice)
                return {"tool_choice": tool_choice, "count": len(tools)}

        llm = FakeLLM()
        tools = [
            SimpleNamespace(name="tool_generate_visual"),
            SimpleNamespace(name="tool_create_visual_code"),
        ]

        llm_with_tools, _llm_auto, forced_choice = _bind_direct_tools(llm, tools, True)

        assert llm.calls == [None, "any"]
        assert llm_with_tools["tool_choice"] == "any"
        assert forced_choice == "any"

    def test_preserves_runtime_metadata_across_bound_wrappers(self):
        class FakeBound(dict):
            pass

        class FakeLLM:
            def __init__(self):
                self._wiii_provider_name = "google"
                self._wiii_model_name = "gemini-3.1-pro-preview"
                self._wiii_tier_key = "deep"

            def bind_tools(self, tools, tool_choice=None):
                return FakeBound(tool_choice=tool_choice, count=len(tools))

        llm = FakeLLM()
        tool = SimpleNamespace(name="tool_generate_visual")

        llm_with_tools, llm_auto, forced_choice = _bind_direct_tools(llm, [tool], True)

        assert getattr(llm_auto, "_wiii_provider_name", None) == "google"
        assert getattr(llm_auto, "_wiii_model_name", None) == "gemini-3.1-pro-preview"
        assert getattr(llm_auto, "_wiii_tier_key", None) == "deep"
        assert getattr(llm_with_tools, "_wiii_tier_key", None) == "deep"
        assert forced_choice == "tool_generate_visual"


class TestVisibleProgressCopy:
    def test_direct_wait_heartbeat_does_not_echo_raw_query_or_tool_name(self):
        query = "Visual cho mình xem thống kê dữ liệu hiện tại giá dầu mấy ngày gần đây"
        text = _build_direct_wait_heartbeat_text(
            query=query,
            phase="ground",
            cue="visual",
            beat_index=1,
            elapsed_sec=4.0,
            tool_names=["tool_web_search"],
        )

        lowered = text.lower()
        assert "visual cho mình xem" not in lowered
        assert "tool_web_search" not in lowered
        assert "http" not in lowered

    def test_code_studio_wait_heartbeat_stays_generic_and_non_query_echo(self):
        query = "mô phỏng cảnh Thúy Kiều ở lầu Ngưng Bích cho mình được chứ ?"
        text = _build_code_studio_wait_heartbeat_text(
            query=query,
            beat_index=1,
            elapsed_sec=8.0,
            state={},
        )

        lowered = text.lower()
        assert "thúy kiều" not in lowered
        assert "lầu ngưng bích" not in lowered
        assert "tool_" not in lowered

    def test_tool_result_summary_hides_search_snippets(self):
        result = _summarize_tool_result_for_stream(
            "tool_web_search",
            "giá dầu hôm nay https://example.com Brent 98.74 WTI 95.92",
        )

        assert result == "Tìm được 1 nguồn: example.com"


class TestProviderFlowIntegrity:
    @pytest.mark.asyncio
    async def test_direct_visual_auto_applies_visual_thinking_floor(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        fake_llm._wiii_provider_name = "zhipu"
        fake_llm._wiii_model_name = "glm-4.5-air"
        state = {
            "query": "Visual cho mình xem thống kê dữ liệu hiện tại giá dầu mấy ngày gần đây",
            "context": {},
            "domain_config": {},
            "provider": "auto",
            "routing_metadata": {"method": "structured", "intent": "web_search"},
        }

        mock_execute = AsyncMock(
            return_value=(SimpleNamespace(content="Đã dựng chart", tool_calls=[]), [], [])
        )

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            return_value=fake_llm,
        ) as mock_get_native_llm, patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ) as mock_get_llm, patch(
            "app.engine.multi_agent.graph._collect_direct_tools",
            return_value=([SimpleNamespace(name="tool_generate_visual")], False),
        ), patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, None),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.graph._execute_direct_tool_rounds",
            new=mock_execute,
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("Đã dựng chart", "", []),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_reasoning_summary",
            new=AsyncMock(return_value="Mình đang giữ phần nhìn và phần nghĩa đi cùng nhau."),
        ):
            result = await direct_response_node(state)

        assert result["final_response"] == "Đã dựng chart"
        assert mock_get_native_llm.call_args.kwargs["effort_override"] == "high"
        mock_get_llm.assert_not_called()
        assert mock_execute.call_args.kwargs["provider"] is None
        assert result["provider"] == "auto"
        assert result["model"] == "glm-4.5-air"

    @pytest.mark.asyncio
    async def test_code_studio_respects_explicit_provider_override(self):
        fake_tracer = MagicMock()
        fake_llm = MagicMock()
        fake_llm._wiii_provider_name = "zhipu"
        fake_llm._wiii_model_name = "glm-5"
        state = {
            "query": "Tạo mô phỏng hảo hán uống rượu ngắm trăng",
            "context": {},
            "domain_config": {},
            "provider": "zhipu",
            "routing_metadata": {"method": "structured", "intent": "code_execution"},
        }

        mock_execute = AsyncMock(
            return_value=(SimpleNamespace(content="Đã mở Code Studio", tool_calls=[]), [], [])
        )

        with patch(
            "app.engine.multi_agent.graph._get_or_create_tracer",
            return_value=fake_tracer,
        ), patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            return_value=fake_llm,
        ) as mock_get_llm, patch(
            "app.engine.multi_agent.graph._looks_like_ambiguous_simulation_request",
            return_value=False,
        ), patch(
            "app.engine.multi_agent.graph._collect_code_studio_tools",
            return_value=([SimpleNamespace(name="tool_create_visual_code")], True),
        ), patch(
            "app.engine.multi_agent.graph._bind_direct_tools",
            return_value=(fake_llm, fake_llm, "tool_create_visual_code"),
        ), patch(
            "app.engine.multi_agent.graph._build_direct_system_messages",
            return_value=[],
        ), patch(
            "app.engine.multi_agent.graph._execute_code_studio_fast_path",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.engine.multi_agent.graph._execute_code_studio_tool_rounds",
            new=mock_execute,
        ), patch(
            "app.engine.multi_agent.graph._extract_direct_response",
            return_value=("Đã mở Code Studio", "", []),
        ):
            result = await code_studio_node(state)

        assert result["final_response"] == "Đã mở Code Studio"
        assert mock_get_llm.call_args.kwargs["provider_override"] == "zhipu"
        assert mock_execute.call_args.kwargs["provider"] == "zhipu"


class TestVisibleProgressCopyQuality:
    def test_direct_wait_heartbeat_emotional_turn_sounds_present_not_generic(self):
        text = _build_direct_wait_heartbeat_text(
            query="Buồn quá",
            phase="attune",
            cue="social",
            beat_index=1,
            elapsed_sec=4.0,
        )

        lowered = text.lower()
        assert "khoảng chùng xuống" not in lowered
        assert "ở lại với bạn" not in lowered
        assert "nhịp đáp chậm" in lowered or "mở lời vừa đủ dịu" in lowered
        assert "mình đang chắt lấy điều cốt lõi" not in lowered
        assert "mình vẫn đang nghe thêm xem nhịp này" not in lowered

    def test_direct_wait_heartbeat_identity_turn_stays_effortless(self):
        text = _build_direct_wait_heartbeat_text(
            query="Bạn là ai?",
            phase="attune",
            cue="identity",
            beat_index=1,
            elapsed_sec=4.0,
        )

        lowered = text.lower()
        assert "giữ phần tự thân" not in lowered
        assert "bảo vệ identity" not in lowered
        assert "vòng vo" in lowered or "thành thật" in lowered or "màu mè" in lowered

    def test_code_studio_wait_heartbeat_simulation_turn_keeps_scene_mindset(self):
        text = _build_code_studio_wait_heartbeat_text(
            query="mô phỏng dạng 3d được khum",
            beat_index=1,
            elapsed_sec=8.0,
            state={},
        )

        lowered = text.lower()
        assert "mô phỏng" in lowered or "canvas" in lowered or "khung chuyển động" in lowered
        assert "demo chung chung" not in lowered


class TestThinkingStartSurfaceLabel:
    def test_generic_lifecycle_label_stays_hidden_from_visible_surface(self):
        assert _thinking_start_label("Bắt nhịp câu hỏi") == ""
        assert _thinking_start_label("Chốt cách đáp hợp nhịp") == ""

    def test_persona_label_can_still_surface_when_it_sounds_like_wiii(self):
        assert _thinking_start_label("Hmm Wiii suy nghĩ rồi nè~") == "Hmm Wiii suy nghĩ rồi nè~"
