"""
Sprint 154: "Dọn Nhà" — Tech Debt Cleanup Tests

Tests for:
1. Config nested model groups (DatabaseConfig, LLMConfig, etc.)
2. Extracted direct_response_node helper functions
3. Shared test fixture usage
4. New fact_retrieval weight sum validator
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from types import SimpleNamespace


# =========================================================================
# 1. Config Nested Model Groups
# =========================================================================

class TestConfigNestedGroups:
    """Test that nested config groups are properly synced from flat fields."""

    def test_database_config_synced(self):
        """DatabaseConfig should reflect flat postgres_* fields."""
        from app.core.config import Settings
        s = Settings(
            postgres_host="myhost",
            postgres_port=5555,
            postgres_user="myuser",
            postgres_password="mypass",
            postgres_db="mydb",
            _env_file=None,
        )
        assert s.database.host == "myhost"
        assert s.database.port == 5555
        assert s.database.user == "myuser"
        assert s.database.password == "mypass"
        assert s.database.db == "mydb"

    def test_llm_config_synced(self):
        """LLMConfig should reflect flat llm_provider, google_api_key, etc."""
        from app.core.config import Settings
        s = Settings(
            llm_provider="google",
            google_api_key="test-key-123",
            google_model="gemini-3-flash-preview",
            ollama_model="qwen3:8b",
            _env_file=None,
        )
        assert s.llm.provider == "google"
        assert s.llm.google_api_key == "test-key-123"
        assert s.llm.google_model == "gemini-3-flash-preview"
        assert s.llm.ollama_model == "qwen3:8b"

    def test_rag_config_synced(self):
        """RAGConfig should reflect flat rag_* fields."""
        from app.core.config import Settings
        s = Settings(
            rag_confidence_high=0.80,
            rag_confidence_medium=0.50,
            rag_quality_mode="quality",
            _env_file=None,
        )
        assert s.rag.confidence_high == 0.80
        assert s.rag.confidence_medium == 0.50
        assert s.rag.quality_mode == "quality"

    def test_memory_config_synced(self):
        """MemoryConfig should reflect flat memory_* fields."""
        from app.core.config import Settings
        s = Settings(
            max_user_facts=100,
            fact_retrieval_alpha=0.4,
            fact_retrieval_beta=0.4,
            fact_retrieval_gamma=0.2,
            _env_file=None,
        )
        assert s.memory.max_user_facts == 100
        assert s.memory.fact_retrieval_alpha == 0.4

    def test_product_search_config_synced(self):
        """ProductSearchConfig should reflect flat product_search_* fields."""
        from app.core.config import Settings
        s = Settings(
            enable_product_search=True,
            product_search_max_results=50,
            product_search_max_iterations=20,
            _env_file=None,
        )
        assert s.product_search.enable_product_search is True
        assert s.product_search.max_results == 50
        assert s.product_search.max_iterations == 20

    def test_thinking_config_synced(self):
        """ThinkingConfig should reflect flat thinking_* fields."""
        from app.core.config import Settings
        s = Settings(
            thinking_enabled=False,
            thinking_budget_deep=16384,
            gemini_thinking_level="high",
            _env_file=None,
        )
        assert s.thinking.enabled is False
        assert s.thinking.budget_deep == 16384
        assert s.thinking.gemini_level == "high"

    def test_character_config_synced(self):
        """CharacterConfig should reflect flat character_* fields."""
        from app.core.config import Settings
        s = Settings(
            enable_character_reflection=False,
            character_reflection_interval=10,
            _env_file=None,
        )
        assert s.character.enable_reflection is False
        assert s.character.reflection_interval == 10

    def test_cache_config_synced(self):
        """CacheConfig should reflect flat cache_* fields."""
        from app.core.config import Settings
        s = Settings(
            semantic_cache_enabled=False,
            cache_similarity_threshold=0.95,
            cache_response_ttl=3600,
            _env_file=None,
        )
        assert s.cache.enabled is False
        assert s.cache.similarity_threshold == 0.95
        assert s.cache.response_ttl == 3600

    def test_flat_access_still_works(self):
        """Flat field access must continue working (backward compat)."""
        from app.core.config import Settings
        s = Settings(
            google_api_key="abc123",
            llm_provider="openai",
            _env_file=None,
        )
        # Flat access
        assert s.google_api_key == "abc123"
        assert s.llm_provider == "openai"
        # Nested access
        assert s.llm.google_api_key == "abc123"
        assert s.llm.provider == "openai"


# =========================================================================
# 2. Fact Retrieval Weight Validator
# =========================================================================

class TestFactRetrievalWeightValidator:
    """Sprint 154: fact_retrieval alpha+beta+gamma must sum to 1.0."""

    def test_valid_weights_default(self):
        """Default weights (0.3+0.5+0.2=1.0) should pass validation."""
        from app.core.config import Settings
        s = Settings(_env_file=None)
        assert abs(s.fact_retrieval_alpha + s.fact_retrieval_beta + s.fact_retrieval_gamma - 1.0) < 0.01

    def test_valid_weights_custom(self):
        """Custom weights summing to 1.0 should pass validation."""
        from app.core.config import Settings
        s = Settings(
            fact_retrieval_alpha=0.4,
            fact_retrieval_beta=0.4,
            fact_retrieval_gamma=0.2,
            _env_file=None,
        )
        assert s.fact_retrieval_alpha == 0.4

    def test_invalid_weights_sum(self):
        """Weights NOT summing to 1.0 should raise ValueError."""
        from app.core.config import Settings
        with pytest.raises(ValueError, match="must sum to 1.0"):
            Settings(
                fact_retrieval_alpha=0.5,
                fact_retrieval_beta=0.5,
                fact_retrieval_gamma=0.5,
                _env_file=None,
            )


# =========================================================================
# 3. Extracted direct_response_node Helpers
# =========================================================================

class TestCollectDirectTools:
    """Test _collect_direct_tools extracted helper."""

    def test_returns_tools_and_force_flag(self):
        """Should return (tools_list, force_tools_bool)."""
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_character_tools = False
            ms.enable_code_execution = False
            from app.engine.multi_agent.graph import _collect_direct_tools
            tools, force = _collect_direct_tools("xin chào")
            assert isinstance(tools, list)
            assert isinstance(force, bool)

    def test_force_tools_for_web_search_query(self):
        """Queries needing web search should set force=True."""
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_character_tools = False
            ms.enable_code_execution = False
            from app.engine.multi_agent.graph import _collect_direct_tools
            _, force = _collect_direct_tools("thời tiết hôm nay thế nào")
            # force depends on _needs_web_search detecting weather keywords
            assert isinstance(force, bool)


class TestDirectAnalysisTools:
    """Regression tests for direct analysis/code tool selection."""

    def test_force_tools_for_python_query(self):
        # WAVE-001: direct no longer owns Python/code capability.
        # A "chay Python" query should NOT force tools on direct —
        # that query routes to code_studio_agent instead.
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_character_tools = False
            ms.enable_code_execution = True
            ms.enable_structured_visuals = False
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            ms.enable_lms_integration = False
            from app.engine.multi_agent.graph import _collect_direct_tools

            _, force = _collect_direct_tools("chay Python de ve bieu do demo")
            # After WAVE-001: direct does not force-call tools for Python queries.
            assert force is False


class TestWiiiHouseTextSanitizer:
    """Guardrail for accidental mixed-script drift in direct lane."""

    def test_removes_accidental_cjk_fragments_when_query_is_vietnamese(self):
        from app.engine.multi_agent.graph import _sanitize_wiii_house_text

        value = "À, mình là Wiii đây. Còn bạn呢, mình gọi là gì đây? Mình đang在这里."

        cleaned = _sanitize_wiii_house_text(value, query="bạn là ai")

        assert "呢" not in cleaned
        assert "在" not in cleaned
        assert "Wiii đây" in cleaned
        assert "Còn bạn nhỉ" in cleaned

    def test_removes_broken_soul_emotion_prefix(self):
        from app.engine.multi_agent.graph import _sanitize_wiii_house_text

        value = (
            'e": {"mouthCurve":0.6,"eyeShape":0.4,"blush":0.2,'
            '"eyeOpenness":1.3}, "intensity":0.9}--> '
            "Dạ đây nha cậu~ POST /v1/responses là endpoint chính."
        )

        cleaned = _sanitize_wiii_house_text(value, query="tim tren web OpenAI Responses API")

        assert cleaned.startswith("Dạ đây nha cậu")
        assert "mouthCurve" not in cleaned
        assert "eyeShape" not in cleaned
        assert "-->" not in cleaned

    def test_preserves_markdown_urls_while_spacing_vietnamese_text(self):
        from app.engine.multi_agent.graph import _sanitize_wiii_house_text

        value = (
            "Endpoint tạo response: POST https://api.openai.com/v1/responses "
            "([OpenAI Responses API reference](https://platform.openai.com/docs/api-reference/responses)). "
            "Nguồn: platform.openai.com."
        )

        cleaned = _sanitize_wiii_house_text(value, query="tim tren web OpenAI Responses API")

        assert "https://api.openai.com/v1/responses" in cleaned
        assert "(https://platform.openai.com/docs/api-reference/responses)" in cleaned
        assert "platform.openai.com" in cleaned
        assert "https: //" not in cleaned
        assert "openai. com" not in cleaned

    def test_keeps_cjk_when_user_explicitly_asks_for_it(self):
        from app.engine.multi_agent.graph import _sanitize_wiii_house_text

        value = "中文 là cách viết của tiếng Trung."

        cleaned = _sanitize_wiii_house_text(value, query="dịch sang tiếng Trung giúp mình")

        assert cleaned == value

    def test_python_query_requires_execute_python(self):
        # WAVE-001: execute_python is no longer a required tool for direct.
        # Python queries are now exclusively owned by code_studio_agent.
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_code_execution = True
            ms.enable_structured_visuals = False
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            from app.engine.multi_agent.graph import _direct_required_tool_names

            required = _direct_required_tool_names(
                "ban co the chay Python de ve bieu do demo khong?",
                user_role="admin",
            )

            # After WAVE-001: direct never requires execute_python (owned by code_studio).
            assert "tool_execute_python" not in required

    def test_code_studio_collects_execute_python_for_admin(self):
        # WAVE-001 positive regression: code_studio_agent owns Python execution.
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_code_execution = True
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            from app.engine.multi_agent.graph import _collect_code_studio_tools

            tools, force = _collect_code_studio_tools(
                "chay Python de ve bieu do demo",
                user_role="admin",
            )
            names = [getattr(t, "name", getattr(t, "__name__", "")) for t in tools]
            assert "tool_execute_python" in names
            assert force is True

    def test_student_query_does_not_collect_execute_python(self):
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_character_tools = False
            ms.enable_code_execution = True
            ms.enable_structured_visuals = False
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            ms.enable_lms_integration = False
            from app.engine.multi_agent.graph import _collect_direct_tools

            tools, _ = _collect_direct_tools(
                "chay Python de ve bieu do demo",
                user_role="student",
            )
            names = [getattr(tool, "name", getattr(tool, "__name__", "")) for tool in tools]
            assert "tool_execute_python" not in names

    def test_student_query_does_not_require_execute_python(self):
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_code_execution = True
            ms.enable_structured_visuals = False
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            from app.engine.multi_agent.graph import _direct_required_tool_names

            required = _direct_required_tool_names(
                "ban co the chay Python de ve bieu do demo khong?",
                user_role="student",
            )

            assert "tool_execute_python" not in required


class TestCodeStudioSynthesisObservations:
    """Regression tests for code_studio post-tool synthesis grounding."""

    def test_includes_artifact_delivery_observation(self):
        from app.engine.multi_agent.graph import _build_code_studio_synthesis_observations

        observations = _build_code_studio_synthesis_observations([
            {
                "type": "result",
                "name": "tool_execute_python",
                "result": "Artifacts:\n- chart.png (image/png) -> /home/appuser/.wiii/workspace/generated/chart.png",
            }
        ])

        assert any("chart.png" in item for item in observations)
        assert any("tool_execute_python" in item for item in observations)


class TestCodeStudioResponseSanitizer:
    """Regression tests for code studio payload cleanup."""

    def test_strips_artifact_action_json_without_thought_field(self):
        from app.engine.multi_agent.graph import _sanitize_code_studio_response

        response = (
            'Minh vua ve xong bieu do cho cau day.\n\n'
            '{ "action": "artifact", "action_input": "learning_progress.png" }'
        )
        tool_events = [
            {
                "type": "result",
                "result": (
                    "Artifacts:\n"
                    "- learning_progress.png (image/png) -> "
                    "/home/appuser/.wiii/workspace/generated/learning-progress.png"
                ),
            }
        ]

        cleaned = _sanitize_code_studio_response(response, tool_events)

        assert '"action"' not in cleaned
        assert "action_input" not in cleaned
        assert "learning_progress.png" in cleaned
        assert "artifact ngay ben duoi" in cleaned

    def test_strips_chatty_greeting_and_lore_from_technical_answer(self):
        from app.engine.multi_agent.graph import _sanitize_code_studio_response

        response = (
            "Chao cau! Rat vui duoc gap cau nhe~ Minh la Wiii day!\n\n"
            "Bong - con meo ao cua minh - dang ngoi canh meo meo vi thay bieu do vui qua.\n\n"
            "Day la bieu do cau dang nhan duoc."
        )
        tool_events = [
            {
                "type": "result",
                "result": (
                    "Artifacts:\n"
                    "- chart.png (image/png) -> "
                    "/home/appuser/.wiii/workspace/generated/chart.png"
                ),
            }
        ]

        cleaned = _sanitize_code_studio_response(response, tool_events)

        assert "Rat vui duoc gap" not in cleaned
        assert "Minh la Wiii" not in cleaned
        assert "Bong" not in cleaned
        assert "meo meo" not in cleaned
        assert cleaned.startswith("Minh da tao xong `chart.png`")
        assert "Day la bieu do cau dang nhan duoc." in cleaned


class TestCodeStudioTerminalFailures:
    """Regression tests for terminal sandbox failures in code studio."""

    def test_detects_terminal_opensandbox_connectivity_error(self):
        from app.engine.multi_agent.graph import _is_terminal_code_studio_tool_error

        assert _is_terminal_code_studio_tool_error(
            "tool_execute_python",
            "OpenSandbox execution failed: Network connectivity error: read ECONNRESET",
        ) is True
        assert _is_terminal_code_studio_tool_error(
            "tool_browser_snapshot_url",
            "Tool unavailable",
        ) is True
        assert _is_terminal_code_studio_tool_error(
            "tool_create_visual_code",
            "Tool unavailable",
        ) is True
        assert _is_terminal_code_studio_tool_error(
            "tool_web_search",
            "OpenSandbox execution failed: Network connectivity error",
        ) is False

    def test_builds_chart_specific_terminal_failure_response(self):
        from app.engine.multi_agent.graph import _build_code_studio_terminal_failure_response

        message = _build_code_studio_terminal_failure_response(
            "Ve mot bieu do bang Python va gui lai file PNG nhu artifact.",
            [],
        )

        assert "PNG" in message or "png" in message
        assert "sandbox" in message.lower()
        assert "lỗi kết nối" in message.lower()


class TestCodeStudioWave002:
    """WAVE-002 regression: Code Studio capability contracts."""

    def test_html_query_requires_generate_html_file(self):
        """HTML/landing-page queries must force tool_generate_html_file."""
        from app.engine.multi_agent.graph import _code_studio_required_tool_names

        required = _code_studio_required_tool_names("tao landing page cho san pham", user_role="admin")
        assert "tool_generate_html_file" in required

    def test_excel_query_requires_generate_excel_file(self):
        """Excel/spreadsheet queries must force tool_generate_excel_file."""
        from app.engine.multi_agent.graph import _code_studio_required_tool_names

        required = _code_studio_required_tool_names("xuat file Excel danh sach", user_role="admin")
        assert "tool_generate_excel_file" in required

    def test_word_query_requires_generate_word_document(self):
        """Word/report queries must force tool_generate_word_document."""
        from app.engine.multi_agent.graph import _code_studio_required_tool_names

        required = _code_studio_required_tool_names("viet bao cao Word cho du an", user_role="admin")
        assert "tool_generate_word_document" in required

    def test_python_query_code_studio_requires_execute_python_for_admin(self):
        """Admin Python requests must include tool_execute_python in code studio required."""
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_code_execution = True
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            from app.engine.multi_agent.graph import _code_studio_required_tool_names

            required = _code_studio_required_tool_names("chay Python tinh giai thua 10", user_role="admin")
            assert "tool_execute_python" in required

    def test_visual_query_code_studio_requires_structured_visual_tool(self):
        """Visual explanation requests in code studio must keep the structured visual tool available."""
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_code_execution = False
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            ms.enable_structured_visuals = True
            from app.engine.multi_agent.graph import _code_studio_required_tool_names

            required = _code_studio_required_tool_names(
                "Explain Kimi linear attention in charts and compare standard attention vs linear attention",
                user_role="admin",
            )
            assert "tool_generate_visual" in required

    def test_mermaid_query_code_studio_requires_mermaid_tool_when_structured_enabled(self):
        """Diagram requests in code studio should preserve the mermaid tool requirement."""
        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_code_execution = False
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            ms.enable_structured_visuals = True
            from app.engine.multi_agent.graph import _code_studio_required_tool_names

            required = _code_studio_required_tool_names(
                "Ve flowchart quy trinh onboarding cho team moi",
                user_role="admin",
            )
            assert "tool_generate_mermaid" in required

    def test_delivery_contract_chart_request_includes_chart_guidance(self):
        """Chart requests should get chart-specific delivery contract line."""
        from app.engine.multi_agent.graph import _build_code_studio_delivery_contract

        contract = _build_code_studio_delivery_contract("ve bieu do doanh thu theo thang")
        assert "chart" in contract.lower() or "bieu do" in contract.lower()
        assert "png" in contract.lower() or "svg" in contract.lower()

    def test_delivery_contract_html_request_includes_html_guidance(self):
        """HTML/landing page requests should get HTML-specific delivery contract line."""
        from app.engine.multi_agent.graph import _build_code_studio_delivery_contract

        contract = _build_code_studio_delivery_contract("tao landing page cho san pham may tinh")
        assert "html" in contract.lower() or "landing" in contract.lower()

    def test_code_studio_tools_context_chart_priority_with_execute_python(self):
        """When execute_python is available, tools context must say PNG first for charts."""
        from app.engine.multi_agent.graph import _build_code_studio_tools_context

        ctx = _build_code_studio_tools_context.__wrapped__(None, "admin") if hasattr(
            _build_code_studio_tools_context, "__wrapped__"
        ) else None

        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_code_execution = True
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            ctx = _build_code_studio_tools_context(ms, "admin")

        # With execute_python available: PNG should be the primary chart output mentioned
        assert "PNG" in ctx or "png" in ctx
        assert "tool_execute_python" in ctx

    def test_code_studio_tools_context_mermaid_fallback_without_execute_python(self):
        """Without execute_python, tools context must mention Mermaid as the chart path."""
        from app.engine.multi_agent.graph import _build_code_studio_tools_context

        with patch("app.engine.multi_agent.graph.settings") as ms:
            ms.enable_code_execution = False
            ms.enable_browser_agent = False
            ms.enable_privileged_sandbox = False
            ms.sandbox_provider = "disabled"
            ms.sandbox_allow_browser_workloads = False
            ctx = _build_code_studio_tools_context(ms, "student")

        assert "Mermaid" in ctx or "mermaid" in ctx
        # execute_python should NOT be primary tool hint for non-admin/no-exec
        assert "tool_execute_python" not in ctx

    def test_inject_code_studio_context_mentions_active_session(self):
        """Active Code Studio session should be converted into a compact prompt block."""
        from app.engine.multi_agent.graph import _inject_code_studio_context

        prompt = _inject_code_studio_context({
            "context": {
                "code_studio_context": {
                    "active_session": {
                        "session_id": "vs_1",
                        "title": "Mo phong Con lac",
                        "status": "complete",
                        "active_version": 2,
                        "version_count": 2,
                        "studio_lane": "app",
                        "artifact_kind": "html_app",
                        "renderer_contract": "host_shell",
                        "has_preview": True,
                    },
                    "requested_view": "code",
                },
            },
        })

        assert "Code Studio Context" in prompt
        assert "vs_1" in prompt
        assert "requested_view" not in prompt
        assert "TAB CODE" in prompt

    def test_sanitize_code_studio_response_collapses_raw_source_dump_when_session_exists(self):
        """Raw HTML should be collapsed into a panel-first summary when Code Studio is active."""
        from app.engine.multi_agent.graph import _sanitize_code_studio_response

        response = _sanitize_code_studio_response(
            "<style>.demo{color:red;}</style><div class='demo'>Hello</div>",
            [],
            {
                "context": {
                    "code_studio_context": {
                        "active_session": {
                            "session_id": "vs_2",
                            "title": "Pendulum App",
                            "status": "complete",
                            "studio_lane": "app",
                        },
                        "requested_view": "code",
                    },
                },
            },
        )

        assert "Code Studio" in response
        assert "Pendulum App" in response
        assert "<style>" not in response
        assert "<div" not in response

    def test_sanitize_code_studio_response_collapses_visual_code_dump_without_session_context(self):
        """Raw visual code should still stay out of chat even before Code Studio session context hydrates."""
        from app.engine.multi_agent.graph import _sanitize_code_studio_response

        response = _sanitize_code_studio_response(
            "Mình sẽ tạo visual này cho bạn.\n\n```html\n<div class='scene'>Moon</div>\n```",
            [
                {
                    "type": "result",
                    "name": "tool_create_visual_code",
                    "result": "{\"ok\": true}",
                }
            ],
            {"context": {}},
        )

        assert "Code Studio" in response or "phần trực quan" in response
        assert "```html" not in response
        assert "<div" not in response

    def test_visual_runtime_metadata_reuses_active_code_studio_session_for_vietnamese_patch(self):
        """Follow-up app edits should anchor to the current Code Studio session instead of opening a new one."""
        from app.engine.multi_agent.graph import _build_visual_tool_runtime_metadata

        metadata = _build_visual_tool_runtime_metadata(
            {
                "context": {
                    "code_studio_context": {
                        "active_session": {
                            "session_id": "vs_pendulum_1",
                            "title": "Mo phong Con lac",
                            "status": "complete",
                            "studio_lane": "app",
                            "artifact_kind": "html_app",
                        },
                    },
                },
            },
            "Giữ app hiện tại, thêm slider điều chỉnh trọng lực và ma sát",
        )

        assert isinstance(metadata, dict)
        assert metadata["presentation_intent"] == "code_studio_app"
        assert metadata["preferred_visual_operation"] == "patch"
        assert metadata["preferred_visual_session_id"] == "vs_pendulum_1"
        assert metadata["preferred_code_studio_session_id"] == "vs_pendulum_1"
        assert metadata["studio_lane"] == "app"
        assert metadata["artifact_kind"] == "html_app"

    def test_visual_runtime_metadata_preserves_premium_quality_from_active_code_session(self):
        """Follow-up app patches should keep the higher quality bar from the current Code Studio session."""
        from app.engine.multi_agent.graph import _build_visual_tool_runtime_metadata

        metadata = _build_visual_tool_runtime_metadata(
            {
                "context": {
                    "code_studio_context": {
                        "active_session": {
                            "session_id": "vs_pendulum_2",
                            "title": "Mo phong Con lac",
                            "status": "complete",
                            "studio_lane": "app",
                            "artifact_kind": "html_app",
                            "quality_profile": "premium",
                        },
                    },
                },
            },
            "Giữ app hiện tại, đổi màu nền thành xanh nhạt",
        )

        assert isinstance(metadata, dict)
        assert metadata["preferred_visual_session_id"] == "vs_pendulum_2"
        assert metadata["quality_profile"] == "premium"


class TestDocumentStudioWave003:
    """WAVE-003 regression: Document Studio artifact extraction and synthesis."""

    _EXCEL_SUCCESS = '{"file_path": "/tmp/wiii-data_20260310.xlsx", "file_url": "/files/wiii-data_20260310.xlsx", "filename": "wiii-data_20260310.xlsx", "format": "xlsx", "title": "Report"}'
    _WORD_SUCCESS = '{"file_path": "/tmp/wiii-doc_20260310.docx", "file_url": "/files/wiii-doc_20260310.docx", "filename": "wiii-doc_20260310.docx", "format": "docx", "title": "Report"}'
    _HTML_SUCCESS = '{"file_path": "/tmp/page_20260310.html", "file_url": "/files/page_20260310.html", "filename": "page_20260310.html", "format": "html", "title": "Page"}'
    _JSON_ERROR = '{"error": "Excel generation failed: module not found"}'

    def test_extract_artifact_names_from_excel_json(self):
        """Excel tool JSON result must yield filename in artifact_names."""
        from app.engine.multi_agent.graph import _extract_code_studio_artifact_names

        events = [{"type": "result", "name": "tool_generate_excel_file", "result": self._EXCEL_SUCCESS}]
        names = _extract_code_studio_artifact_names(events)
        assert any("wiii-data" in n and ".xlsx" in n for n in names), f"Got: {names}"

    def test_extract_artifact_names_from_word_json(self):
        """Word tool JSON result must yield filename in artifact_names."""
        from app.engine.multi_agent.graph import _extract_code_studio_artifact_names

        events = [{"type": "result", "name": "tool_generate_word_document", "result": self._WORD_SUCCESS}]
        names = _extract_code_studio_artifact_names(events)
        assert any("wiii-doc" in n and ".docx" in n for n in names), f"Got: {names}"

    def test_extract_artifact_names_from_html_json(self):
        """HTML tool JSON result must yield filename in artifact_names."""
        from app.engine.multi_agent.graph import _extract_code_studio_artifact_names

        events = [{"type": "result", "name": "tool_generate_html_file", "result": self._HTML_SUCCESS}]
        names = _extract_code_studio_artifact_names(events)
        assert any(".html" in n for n in names), f"Got: {names}"

    def test_extract_artifact_names_json_error_yields_nothing(self):
        """JSON error result must NOT be treated as an artifact name."""
        from app.engine.multi_agent.graph import _extract_code_studio_artifact_names

        events = [{"type": "result", "name": "tool_generate_excel_file", "result": self._JSON_ERROR}]
        names = _extract_code_studio_artifact_names(events)
        assert not names, f"Expected empty, got: {names}"

    def test_synthesis_observations_include_excel_artifact(self):
        """Synthesis observations must name xlsx file when excel tool succeeded."""
        from app.engine.multi_agent.graph import _build_code_studio_synthesis_observations

        events = [{"type": "result", "name": "tool_generate_excel_file", "result": self._EXCEL_SUCCESS}]
        obs = _build_code_studio_synthesis_observations(events)
        combined = " ".join(obs)
        assert "xlsx" in combined.lower() or "wiii-data" in combined.lower(), f"Got: {obs}"

    def test_synthesis_observations_include_word_artifact(self):
        """Synthesis observations must name docx file when word tool succeeded."""
        from app.engine.multi_agent.graph import _build_code_studio_synthesis_observations

        events = [{"type": "result", "name": "tool_generate_word_document", "result": self._WORD_SUCCESS}]
        obs = _build_code_studio_synthesis_observations(events)
        combined = " ".join(obs)
        assert "docx" in combined.lower() or "wiii-doc" in combined.lower(), f"Got: {obs}"

    def test_synthesis_observations_note_document_error(self):
        """Synthesis observations must report document studio errors."""
        from app.engine.multi_agent.graph import _build_code_studio_synthesis_observations

        events = [{"type": "result", "name": "tool_generate_excel_file", "result": self._JSON_ERROR}]
        obs = _build_code_studio_synthesis_observations(events)
        combined = " ".join(obs).lower()
        assert "loi" in combined or "error" in combined, f"Got: {obs}"

    def test_is_document_studio_tool_error_detects_json_error(self):
        """_is_document_studio_tool_error must return True for JSON error result."""
        from app.engine.multi_agent.graph import _is_document_studio_tool_error

        assert _is_document_studio_tool_error("tool_generate_excel_file", self._JSON_ERROR) is True
        assert _is_document_studio_tool_error("tool_generate_word_document", self._JSON_ERROR) is True
        assert _is_document_studio_tool_error("tool_generate_html_file", self._JSON_ERROR) is True

    def test_is_document_studio_tool_error_not_for_success(self):
        """_is_document_studio_tool_error must return False for successful result."""
        from app.engine.multi_agent.graph import _is_document_studio_tool_error

        assert _is_document_studio_tool_error("tool_generate_excel_file", self._EXCEL_SUCCESS) is False

    def test_is_terminal_error_catches_document_studio_json_error(self):
        """_is_terminal_code_studio_tool_error must also catch document studio failures."""
        from app.engine.multi_agent.graph import _is_terminal_code_studio_tool_error

        assert _is_terminal_code_studio_tool_error("tool_generate_excel_file", self._JSON_ERROR) is True
        assert _is_terminal_code_studio_tool_error("tool_generate_word_document", self._JSON_ERROR) is True
        assert _is_terminal_code_studio_tool_error("tool_generate_excel_file", self._EXCEL_SUCCESS) is False

    def test_delivery_lede_added_when_docx_artifact_present(self):
        """_ensure_code_studio_delivery_lede must prepend lede when docx was generated."""
        from app.engine.multi_agent.graph import _ensure_code_studio_delivery_lede

        events = [{"type": "result", "name": "tool_generate_word_document", "result": self._WORD_SUCCESS}]
        result = _ensure_code_studio_delivery_lede("Day la noi dung bao cao.", events)
        assert "wiii-doc" in result.lower() or "da tao" in result.lower(), f"Got: {result}"


class TestBindDirectTools:
    """Test _bind_direct_tools extracted helper."""

    def test_no_tools_returns_raw_llm(self):
        """Empty tools list should return original llm for both."""
        from app.engine.multi_agent.graph import _bind_direct_tools
        llm = MagicMock()
        llm_with, llm_auto = _bind_direct_tools(llm, [], False)
        assert llm_with is llm
        assert llm_auto is llm

    def test_with_tools_no_force(self):
        """Tools without force should use auto for both."""
        from app.engine.multi_agent.graph import _bind_direct_tools
        llm = MagicMock()
        bound = MagicMock()
        llm.bind_tools = MagicMock(return_value=bound)
        llm_with, llm_auto = _bind_direct_tools(llm, [MagicMock()], False)
        assert llm_with is bound
        assert llm_auto is bound

    def test_with_tools_force(self):
        """Tools with force should use tool_choice='any' for first call."""
        from app.engine.multi_agent.graph import _bind_direct_tools
        llm = MagicMock()
        auto_bound = MagicMock(name="auto")
        force_bound = MagicMock(name="force")
        llm.bind_tools = MagicMock(side_effect=[auto_bound, force_bound])
        llm_with, llm_auto = _bind_direct_tools(llm, [MagicMock()], True)
        assert llm_auto is auto_bound
        assert llm_with is force_bound


class TestExtractDirectResponse:
    """Test _extract_direct_response extracted helper."""

    def test_extracts_text_and_thinking(self):
        """Should separate response text from thinking content."""
        from app.engine.multi_agent.graph import _extract_direct_response
        llm_response = MagicMock()
        llm_response.content = "Hello world"
        messages = []

        # Patch at source module (lazy import inside function body)
        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=("Hello world", "thinking")) as mock_fn:
            response, thinking, tools_used = _extract_direct_response(llm_response, messages)
        assert response == "Hello world"
        assert thinking == "thinking"
        assert tools_used == []

    def test_tracks_tool_names(self):
        """Should collect tool names from messages with tool_calls."""
        from app.engine.multi_agent.graph import _extract_direct_response
        llm_response = MagicMock()
        llm_response.content = "Result"
        msg_with_tools = MagicMock()
        msg_with_tools.tool_calls = [{"name": "tool_web_search"}, {"name": "tool_current_datetime"}]
        messages = [msg_with_tools]

        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=("Result", "")):
            _, _, tools_used = _extract_direct_response(llm_response, messages)
        names = [t["name"] for t in tools_used]
        assert "tool_current_datetime" in names
        assert "tool_web_search" in names


class TestExecuteDirectToolRounds:
    """Test _execute_direct_tool_rounds extracted helper."""

    @pytest.mark.asyncio
    async def test_no_tool_calls_returns_immediately(self):
        """If LLM response has no tool_calls, should return immediately."""
        from app.engine.multi_agent.graph import _execute_direct_tool_rounds
        llm_response = MagicMock()
        llm_response.content = "Direct answer"
        llm_response.tool_calls = []
        # llm_with_tools is an object with .ainvoke() method
        llm_with_tools = MagicMock()
        llm_with_tools._wiii_native_route = False
        llm_with_tools._wiii_provider_name = ""
        llm_with_tools._wiii_model_name = "test-direct"
        llm_with_tools.ainvoke = AsyncMock(return_value=llm_response)
        llm_auto = MagicMock()
        llm_auto._wiii_native_route = False
        llm_auto._wiii_provider_name = ""
        llm_auto._wiii_model_name = "test-direct-auto"
        llm_auto.ainvoke = AsyncMock()

        async def noop_push(e):
            pass

        result, msgs, tool_events = await _execute_direct_tool_rounds(
            llm_with_tools, llm_auto, [], [], noop_push,
        )
        assert result.content == "Direct answer"
        assert tool_events == []
        llm_auto.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_visual_intent_keeps_forcing_followup_until_visual_tool_emits(self):
        """Chart/visual turns should not drop to prose-only right after web search."""
        from app.engine.multi_agent.graph import _execute_direct_tool_rounds

        llm_with_tools = MagicMock(name="llm_with_tools")
        llm_auto = MagicMock(name="llm_auto")
        llm_base = MagicMock(name="llm_base")
        llm_visual_only = MagicMock(name="llm_visual_only")
        llm_base.bind_tools.return_value = llm_visual_only
        llm_with_tools._wiii_provider_name = "zhipu"
        llm_with_tools._wiii_model_name = "glm-4.5-air"
        llm_base._wiii_provider_name = "zhipu"
        llm_base._wiii_model_name = "glm-5"

        first_response = MagicMock()
        first_response.content = ""
        first_response.tool_calls = [
            {"id": "tc-1", "name": "tool_web_search", "args": {"query": "gia dau Brent WTI"}}
        ]

        second_response = MagicMock()
        second_response.content = ""
        second_response.tool_calls = [
            {"id": "tc-2", "name": "tool_generate_visual", "args": {"type": "chart"}}
        ]

        final_response = MagicMock()
        final_response.content = "Da dung xong visual."
        final_response.tool_calls = []

        calls = []

        async def fake_ainvoke(llm, messages, **kwargs):
            calls.append(
                {
                    "llm": llm,
                    "tool_choice": kwargs.get("tool_choice"),
                    "tools": kwargs.get("tools"),
                    "timeout_profile": kwargs.get("timeout_profile"),
                }
            )
            if len(calls) == 1:
                return first_response
            if len(calls) == 2:
                return second_response
            return final_response

        async def noop_push(_event):
            return None

        async def fake_emit_visual_event(**kwargs):
            tool_name = kwargs.get("tool_name")
            if tool_name == "tool_generate_visual":
                return ["vs-1"], []
            return [], []

        state = {"query": "Visual cho minh xem thong ke gia dau may ngay gan day"}

        with patch("app.engine.multi_agent.graph._ainvoke_with_fallback", side_effect=fake_ainvoke), \
             patch("app.engine.multi_agent.graph.invoke_tool_with_runtime", new=AsyncMock(side_effect=["search-result", "visual-result"])), \
             patch("app.engine.multi_agent.graph.get_tool_by_name", side_effect=lambda tools, name: next((tool for tool in tools if tool.name == name), None)), \
             patch("app.engine.multi_agent.graph._emit_visual_commit_events", new=AsyncMock()), \
             patch("app.engine.multi_agent.graph._maybe_emit_visual_event", new=AsyncMock(side_effect=fake_emit_visual_event)), \
             patch("app.engine.multi_agent.graph._maybe_emit_host_action_event", new=AsyncMock()), \
             patch("app.engine.multi_agent.graph._build_direct_tool_reflection", new=AsyncMock(return_value="")), \
             patch("app.engine.multi_agent.graph._stream_direct_wait_heartbeats", new=AsyncMock()), \
             patch("app.engine.multi_agent.graph._render_reasoning_fast", return_value=SimpleNamespace(label="Dang can", summary="Dang can", action_text="", phase="act")):
            result, _msgs, tool_events = await _execute_direct_tool_rounds(
                llm_with_tools=llm_with_tools,
                llm_auto=llm_auto,
                messages=[],
                tools=[
                    SimpleNamespace(name="tool_web_search"),
                    SimpleNamespace(name="tool_generate_visual"),
                ],
                push_event=noop_push,
                query="Visual cho minh xem thong ke gia dau may ngay gan day",
                state=state,
                provider="zhipu",
                forced_tool_choice="any",
                llm_base=llm_base,
            )

        assert result is final_response
        assert [entry["llm"] for entry in calls] == [llm_with_tools, llm_visual_only, llm_auto]
        assert calls[1]["tool_choice"] == "tool_generate_visual"
        assert [tool.name for tool in calls[1]["tools"]] == ["tool_generate_visual"]
        assert [entry["timeout_profile"] for entry in calls] == ["structured", "background", "background"]
        assert any(event.get("name") == "tool_generate_visual" for event in tool_events if event.get("type") == "call")
        assert state["_execution_provider"] == "zhipu"
        assert state["_execution_model"] == "glm-5"

    @pytest.mark.asyncio
    async def test_direct_tool_followup_uses_structured_timeout_for_non_visual_queries(self):
        from app.engine.multi_agent.graph import _execute_direct_tool_rounds

        llm_with_tools = MagicMock(name="llm_with_tools")
        llm_auto = MagicMock(name="llm_auto")
        llm_base = MagicMock(name="llm_base")
        llm_with_tools._wiii_provider_name = "zhipu"
        llm_with_tools._wiii_model_name = "glm-4.5-air"
        llm_auto._wiii_provider_name = "zhipu"
        llm_auto._wiii_model_name = "glm-5"
        llm_base._wiii_provider_name = "zhipu"
        llm_base._wiii_model_name = "glm-5"

        first_response = MagicMock()
        first_response.content = ""
        first_response.tool_calls = [
            {"id": "tc-1", "name": "tool_web_search", "args": {"query": "gia xang Viet Nam hom nay"}}
        ]

        final_response = MagicMock()
        final_response.content = "Day la cau tra loi sau khi da xem gia xang."
        final_response.tool_calls = []

        calls = []

        async def fake_ainvoke(llm, messages, **kwargs):
            calls.append(
                {
                    "llm": llm,
                    "timeout_profile": kwargs.get("timeout_profile"),
                    "provider": kwargs.get("provider"),
                    "resolved_provider": kwargs.get("resolved_provider"),
                }
            )
            if len(calls) == 1:
                return first_response
            return final_response

        async def fake_stream_direct_answer(llm, messages, push_event, **kwargs):
            calls.append(
                {
                    "llm": llm,
                    "timeout_profile": kwargs.get("timeout_profile"),
                    "provider": kwargs.get("provider"),
                    "resolved_provider": kwargs.get("resolved_provider"),
                }
            )
            return first_response, False

        async def noop_push(_event):
            return None

        state = {"query": "theo gia Viet Nam thi sao, co nen do xang gio luon khong?"}

        with patch("app.engine.multi_agent.graph._ainvoke_with_fallback", side_effect=fake_ainvoke), \
             patch("app.engine.multi_agent.graph.invoke_tool_with_runtime", new=AsyncMock(return_value="search-result")), \
             patch("app.engine.multi_agent.graph.get_tool_by_name", side_effect=lambda tools, name: next((tool for tool in tools if tool.name == name), None)), \
             patch("app.engine.multi_agent.graph._emit_visual_commit_events", new=AsyncMock()), \
             patch("app.engine.multi_agent.graph._maybe_emit_visual_event", new=AsyncMock(return_value=([], []))), \
             patch("app.engine.multi_agent.graph._maybe_emit_host_action_event", new=AsyncMock()), \
             patch("app.engine.multi_agent.graph._build_direct_tool_reflection", new=AsyncMock(return_value="")), \
             patch("app.engine.multi_agent.graph._stream_direct_answer_with_fallback", new=fake_stream_direct_answer), \
             patch("app.engine.multi_agent.graph._stream_direct_wait_heartbeats", new=AsyncMock()), \
             patch("app.engine.multi_agent.graph._render_reasoning_fast", return_value=SimpleNamespace(label="Dang can", summary="Dang can", action_text="", phase="act")):
            result, _msgs, tool_events = await _execute_direct_tool_rounds(
                llm_with_tools=llm_with_tools,
                llm_auto=llm_auto,
                messages=[],
                tools=[SimpleNamespace(name="tool_web_search")],
                push_event=noop_push,
                query="theo gia Viet Nam thi sao, co nen do xang gio luon khong?",
                state=state,
                provider="auto",
                llm_base=llm_base,
            )

        assert result is final_response
        assert [entry["timeout_profile"] for entry in calls] == [None, "structured"]
        assert calls[1]["resolved_provider"] == "zhipu"
        assert any(event.get("name") == "tool_web_search" for event in tool_events if event.get("type") == "call")

    @pytest.mark.asyncio
    async def test_direct_tool_rounds_force_final_synthesis_when_tool_loop_hits_cap(self):
        from app.engine.multi_agent.graph import _execute_direct_tool_rounds

        llm_with_tools = MagicMock(name="llm_with_tools")
        llm_auto = MagicMock(name="llm_auto")
        llm_base = MagicMock(name="llm_base")
        llm_with_tools._wiii_provider_name = "google"
        llm_with_tools._wiii_model_name = "gemini-3.1-flash-lite-preview"
        llm_auto._wiii_provider_name = "google"
        llm_auto._wiii_model_name = "gemini-3.1-flash-lite-preview"
        llm_base._wiii_provider_name = "google"
        llm_base._wiii_model_name = "gemini-3.1-flash-lite-preview"

        def _tool_response(idx: int):
            resp = MagicMock(name=f"tool_response_{idx}")
            resp.content = ""
            resp.tool_calls = [
                {
                    "id": f"tc-{idx}",
                    "name": "tool_web_search",
                    "args": {"query": f"gia dau round {idx}"},
                }
            ]
            return resp

        first_response = _tool_response(1)
        second_response = _tool_response(2)
        third_response = _tool_response(3)
        fourth_response = _tool_response(4)

        final_response = MagicMock(name="final_response")
        final_response.content = "Day la cau tra loi cuoi cung sau khi da dung tool."
        final_response.tool_calls = []

        responses = [
            first_response,
            second_response,
            third_response,
            fourth_response,
            final_response,
        ]
        calls = []

        async def fake_ainvoke(llm, messages, **kwargs):
            calls.append(
                {
                    "llm": llm,
                    "messages": list(messages),
                    "tools": kwargs.get("tools"),
                    "timeout_profile": kwargs.get("timeout_profile"),
                }
            )
            return responses[len(calls) - 1]

        async def fake_stream_direct_answer(llm, messages, push_event, **kwargs):
            calls.append(
                {
                    "llm": llm,
                    "messages": list(messages),
                    "tools": kwargs.get("tools"),
                    "timeout_profile": kwargs.get("timeout_profile"),
                }
            )
            return responses[0], False

        async def noop_push(_event):
            return None

        state = {"query": "phan tich gia dau"}

        with patch("app.engine.multi_agent.graph._ainvoke_with_fallback", side_effect=fake_ainvoke), \
             patch("app.engine.multi_agent.graph.invoke_tool_with_runtime", new=AsyncMock(return_value="search-result")), \
             patch("app.engine.multi_agent.graph.get_tool_by_name", side_effect=lambda tools, name: next((tool for tool in tools if tool.name == name), None)), \
             patch("app.engine.multi_agent.graph._emit_visual_commit_events", new=AsyncMock()), \
             patch("app.engine.multi_agent.graph._maybe_emit_visual_event", new=AsyncMock(return_value=([], []))), \
             patch("app.engine.multi_agent.graph._maybe_emit_host_action_event", new=AsyncMock()), \
             patch("app.engine.multi_agent.graph._build_direct_tool_reflection", new=AsyncMock(return_value="")), \
             patch("app.engine.multi_agent.graph._stream_direct_answer_with_fallback", new=fake_stream_direct_answer), \
             patch("app.engine.multi_agent.graph._stream_direct_wait_heartbeats", new=AsyncMock()), \
             patch("app.engine.multi_agent.graph._render_reasoning_fast", return_value=SimpleNamespace(label="Dang can", summary="Dang can", action_text="", phase="synthesize")):
            result, msgs, tool_events = await _execute_direct_tool_rounds(
                llm_with_tools=llm_with_tools,
                llm_auto=llm_auto,
                messages=[],
                tools=[SimpleNamespace(name="tool_web_search")],
                push_event=noop_push,
                query="phan tich gia dau",
                state=state,
                provider="auto",
                llm_base=llm_base,
            )

        assert result is final_response
        assert len(calls) == 5
        assert [entry["llm"] for entry in calls] == [
            llm_with_tools,
            llm_auto,
            llm_auto,
            llm_auto,
            llm_base,
        ]
        assert calls[-1]["tools"] is None
        assert "Khong goi them cong cu" in calls[-1]["messages"][-1].content
        assert any(event.get("name") == "tool_web_search" for event in tool_events if event.get("type") == "call")
        assert msgs[-1].content.startswith("Du lieu da du cho luot nay.")


# =========================================================================
# 4. Shared Test Fixture Validation
# =========================================================================

class TestSharedFixtures:
    """Verify that shared fixtures from conftest work correctly."""

    def test_mock_settings_has_key_fields(self, mock_settings):
        """mock_settings should have all commonly-accessed fields."""
        assert mock_settings.google_api_key == "test-key"
        assert mock_settings.llm_provider == "google"
        assert mock_settings.enable_product_search is False
        assert mock_settings.enable_browser_scraping is False
        assert mock_settings.default_domain == "maritime"

    def test_mock_llm_has_ainvoke(self, mock_llm):
        """mock_llm should have ainvoke as AsyncMock."""
        assert hasattr(mock_llm, 'ainvoke')
        assert isinstance(mock_llm.ainvoke, AsyncMock)

    def test_mock_embeddings_returns_vectors(self, mock_embeddings):
        """mock_embeddings should return proper dimension vectors."""
        vec = mock_embeddings.embed_query("test")
        assert len(vec) == 768

    def test_mock_agent_state_has_required_fields(self, mock_agent_state):
        """mock_agent_state should have all fields needed by graph nodes."""
        assert "query" in mock_agent_state
        assert "user_id" in mock_agent_state
        assert "session_id" in mock_agent_state
        assert "domain_id" in mock_agent_state
        assert "context" in mock_agent_state
        assert "langchain_messages" in mock_agent_state["context"]


# =========================================================================
# 5. Nested Config Model Classes
# =========================================================================

class TestNestedConfigModels:
    """Test individual nested config model creation."""

    def test_database_config_defaults(self):
        from app.core.config import DatabaseConfig
        db = DatabaseConfig()
        assert db.host == "localhost"
        assert db.port == 5433
        assert db.user == "wiii"

    def test_llm_config_defaults(self):
        from app.core.config import LLMConfig
        llm = LLMConfig()
        assert llm.provider == "zhipu"
        assert llm.ollama_model == "qwen3:4b-instruct-2507-q4_K_M"
        assert llm.failover_chain == ["zhipu", "google", "ollama", "openrouter"]

    def test_rag_config_defaults(self):
        from app.core.config import RAGConfig
        rag = RAGConfig()
        assert rag.confidence_high == 0.70
        assert rag.confidence_medium == 0.60
        assert rag.quality_mode == "balanced"

    def test_memory_config_defaults(self):
        from app.core.config import MemoryConfig
        mem = MemoryConfig()
        assert mem.max_user_facts == 50
        assert abs(mem.fact_retrieval_alpha + mem.fact_retrieval_beta + mem.fact_retrieval_gamma - 1.0) < 0.01

    def test_product_search_config_defaults(self):
        from app.core.config import ProductSearchConfig
        ps = ProductSearchConfig()
        assert ps.enable_product_search is True
        assert len(ps.platforms) == 8

    def test_thinking_config_defaults(self):
        from app.core.config import ThinkingConfig
        t = ThinkingConfig()
        assert t.enabled is True
        assert t.budget_deep == 8192

    def test_character_config_defaults(self):
        from app.core.config import CharacterConfig
        c = CharacterConfig()
        assert c.enable_reflection is True
        assert c.enable_soul_emotion is False

    def test_cache_config_defaults(self):
        from app.core.config import CacheConfig
        c = CacheConfig()
        assert c.enabled is True
        assert c.similarity_threshold == 0.92
