"""Tests for browser sandbox orchestration and tool wrapper."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest

from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier
from app.engine.tools import ToolAccess, ToolCategory, _init_extended_tools
from app.engine.tools.browser_sandbox_tools import (
    get_browser_sandbox_tools,
    tool_browser_snapshot_url,
)
from app.engine.tools.runtime_context import build_tool_runtime_context, tool_runtime_scope
from app.sandbox.browser_service import (
    BrowserAutomationRequest,
    BrowserAutomationResult,
    BrowserSandboxService,
)
from app.sandbox.models import SandboxExecutionResult


class TestBrowserSandboxService:
    def test_execute_sync_rejects_invalid_url_before_sandbox(self):
        class _SandboxService:
            def execute_profile_sync(self, *args, **kwargs):
                raise AssertionError("sandbox should not be called")

        service = BrowserSandboxService(
            sandbox_service=_SandboxService(),
            limiter_provider=lambda: None,
        )

        result = service.execute_sync(
            BrowserAutomationRequest(url="http://127.0.0.1/private")
        )

        assert result.success is False
        assert "failed validation" in (result.error or "")

    def test_execute_sync_rejects_rate_limited_user(self):
        class _Limiter:
            def check_and_increment(self, user_id):
                assert user_id == "user-1"
                return False

        class _SandboxService:
            def execute_profile_sync(self, *args, **kwargs):
                raise AssertionError("sandbox should not be called")

        service = BrowserSandboxService(
            sandbox_service=_SandboxService(),
            limiter_provider=lambda: _Limiter(),
        )

        result = service.execute_sync(
            BrowserAutomationRequest(url="https://example.com", user_id="user-1")
        )

        assert result.success is False
        assert "rate limit exceeded" in (result.error or "")

    def test_execute_sync_builds_browser_profile_request(self):
        captured = {}

        class _SandboxService:
            def execute_profile_sync(self, profile_id, **kwargs):
                captured["profile_id"] = profile_id
                captured["kwargs"] = kwargs
                payload = {
                    "requested_url": "https://example.com",
                    "final_url": "https://example.com/",
                    "title": "Example Domain",
                    "response_status": 200,
                    "excerpt": "Example content",
                    "screenshot_base64": "BASE64PNG",
                    "label": "Loaded page",
                }
                return SandboxExecutionResult(
                    success=True,
                    stdout=(
                        "warmup log\n"
                        "__WIII_BROWSER_RESULT__"
                        + json.dumps(payload, ensure_ascii=True)
                    ),
                    metadata={"execution_id": "exec-1"},
                )

        service = BrowserSandboxService(
            sandbox_service=_SandboxService(),
            limiter_provider=lambda: None,
            default_timeout_seconds=90,
        )

        result = service.execute_sync(
            BrowserAutomationRequest(
                url="https://example.com",
                tool_name="tool_browser_snapshot_url",
                source="tool_registry",
                request_id="req-1",
                session_id="sess-1",
                organization_id="org-1",
                user_id="user-1",
                node="browser_agent",
            )
        )

        assert result.success is True
        assert result.page_title == "Example Domain"
        assert result.final_url == "https://example.com/"
        assert result.response_status == 200
        assert result.screenshot_base64 == "BASE64PNG"
        assert result.metadata["execution_id"] == "exec-1"

        assert captured["profile_id"] == "browser_playwright"
        kwargs = captured["kwargs"]
        _runner_file = "/opt/wiii-browser/browser_runner.mjs"
        _job_file = "/opt/wiii-browser/browser_job.json"
        assert kwargs["command"] == ["node", _runner_file, _job_file]
        assert sorted(kwargs["files"].keys()) == sorted([_job_file, _runner_file])
        job = json.loads(kwargs["files"][_job_file])
        assert job["url"] == "https://example.com"
        assert job["capture_screenshot"] is True
        assert job["wait_until"] == "networkidle"
        assert job["timeout_ms"] == 90000
        assert kwargs["context"].tool_name == "tool_browser_snapshot_url"
        assert kwargs["context"].approval_scope == "browser_automation"
        assert kwargs["context"].request_id == "req-1"
        assert kwargs["metadata"]["target_url"] == "https://example.com"
        assert kwargs["metadata"]["result_format"] == "wiii.browser.v1"

    def test_build_execution_metadata_redacts_url_and_metadata_secrets(self):
        service = BrowserSandboxService(limiter_provider=lambda: None)

        metadata = service.build_execution_metadata(
            BrowserAutomationRequest(
                url="https://example.com/?token=raw-url-token",
                metadata={"api_key": "raw-api-key"},
            )
        )

        serialized = str(metadata)
        assert "raw-url-token" not in serialized
        assert "raw-api-key" not in serialized
        assert "api_key" not in serialized
        assert "<redacted-secret>" in metadata["target_url"]

    @pytest.mark.asyncio
    async def test_execute_async_reports_missing_structured_payload(self):
        class _SandboxService:
            async def execute_profile(self, profile_id, **kwargs):
                return SandboxExecutionResult(
                    success=True,
                    stdout="plain stdout without sentinel",
                )

        service = BrowserSandboxService(
            sandbox_service=_SandboxService(),
            limiter_provider=lambda: None,
        )

        result = await service.execute(
            BrowserAutomationRequest(url="https://example.com")
        )

        assert result.success is False
        assert "structured result payload" in (result.error or "")

    def test_build_bus_payloads(self):
        service = BrowserSandboxService(limiter_provider=lambda: None)
        result = BrowserAutomationResult(
            success=True,
            requested_url="https://example.com",
            final_url="https://example.com/final",
            page_title="Example Domain",
            page_excerpt="Example excerpt",
            response_status=200,
            screenshot_base64="BASE64PNG",
            screenshot_label="Loaded page",
            metadata={
                "execution_id": "exec-1",
                "request_id": "req-1",
                "user_id": "user-1",
                "access_token": "raw-access-token",
            },
            sandbox_result=SandboxExecutionResult(
                success=True,
                sandbox_id="sandbox-1",
            ),
        )

        screenshot_event = service.build_screenshot_bus_event(result, node="browser")
        artifact_event = service.build_artifact_bus_event(
            result,
            node="browser",
            artifact_id="browser-art-1",
        )

        assert screenshot_event == {
            "type": "browser_screenshot",
            "content": {
                "url": "https://example.com/final",
                "image": "BASE64PNG",
                "label": "Loaded page",
                "metadata": {
                    "execution_id": "exec-1",
                    "request_id": "req-1",
                    "user_id_hash": hash_runtime_identifier("user-1"),
                    "sandbox_id": "sandbox-1",
                    "redacted_secret_count": 1,
                },
            },
            "node": "browser",
        }
        assert artifact_event["type"] == "artifact"
        assert artifact_event["content"]["artifact_type"] == "document"
        assert artifact_event["content"]["artifact_id"] == "browser-art-1"
        assert artifact_event["content"]["metadata"]["execution_id"] == "exec-1"
        assert artifact_event["content"]["metadata"][
            "user_id_hash"
        ] == hash_runtime_identifier("user-1")
        assert artifact_event["content"]["metadata"]["sandbox_id"] == "sandbox-1"
        serialized = str(artifact_event["content"]["metadata"])
        assert "user-1" not in serialized
        assert "raw-access-token" not in serialized
        assert "access_token" not in serialized
        assert "Example excerpt" in artifact_event["content"]["content"]


class TestBrowserSandboxTool:
    def test_tool_wrapper_uses_browser_service(self):
        queue = MagicMock()

        class _Service:
            def execute_sync(self, request):
                assert request.url == "https://example.com"
                assert request.tool_name == "tool_browser_snapshot_url"
                assert request.user_id == "user-1"
                assert request.session_id == "sess-1"
                assert request.request_id == "req-1"
                assert request.node == "direct"
                assert request.metadata["mcp_call_id"] == "mcp-call-1"
                assert request.metadata["tool_call_id"] == "tc-1"
                return BrowserAutomationResult(
                    success=True,
                    requested_url=request.url,
                    final_url=request.url,
                    page_title="Example Domain",
                    screenshot_base64="BASE64PNG",
                    screenshot_label="Loaded page",
                )

            def build_tool_summary(self, result):
                assert result.page_title == "Example Domain"
                return "Browser run succeeded."

            def build_screenshot_bus_event(self, result, *, node=None):
                return {"type": "browser_screenshot", "content": {"label": result.screenshot_label}, "node": node}

            def build_artifact_bus_event(self, result, *, node=None, artifact_id=None):
                return {"type": "artifact", "content": {"artifact_id": "a1"}, "node": node}

        with patch(
            "app.engine.tools.browser_sandbox_tools.get_browser_sandbox_service",
            return_value=_Service(),
        ), patch(
            "app.engine.multi_agent.graph_streaming._get_event_queue",
            return_value=queue,
        ):
            with tool_runtime_scope(
                build_tool_runtime_context(
                    event_bus_id="bus-1",
                    request_id="req-1",
                    session_id="sess-1",
                    organization_id="org-1",
                    user_id="user-1",
                    user_role="admin",
                    node="direct",
                    source="agentic_loop",
                    metadata={"mcp_call_id": "mcp-call-1"},
                ).for_tool("tool_browser_snapshot_url", tool_call_id="tc-1")
            ):
                output = tool_browser_snapshot_url.invoke({"url": "https://example.com"})

        assert output == "Browser run succeeded."
        assert queue.put_nowait.call_count == 2
        user_hash = hash_runtime_identifier("user-1")
        queue.put_nowait.assert_has_calls([
            call({
                "type": "browser_screenshot",
                "content": {
                    "label": "Loaded page",
                    "metadata": {
                        "request_id": "req-1",
                        "session_id": "sess-1",
                        "organization_id": "org-1",
                        "user_id_hash": user_hash,
                        "user_role": "admin",
                        "node": "direct",
                        "request_source": "agentic_loop",
                        "tool_name": "tool_browser_snapshot_url",
                        "tool_call_id": "tc-1",
                        "mcp_call_id": "mcp-call-1",
                    },
                },
                "node": "direct",
            }),
            call({
                "type": "artifact",
                "content": {
                    "artifact_id": "a1",
                    "metadata": {
                        "request_id": "req-1",
                        "session_id": "sess-1",
                        "organization_id": "org-1",
                        "user_id_hash": user_hash,
                        "user_role": "admin",
                        "node": "direct",
                        "request_source": "agentic_loop",
                        "tool_name": "tool_browser_snapshot_url",
                        "tool_call_id": "tc-1",
                        "mcp_call_id": "mcp-call-1",
                    },
                },
                "node": "direct",
            }),
        ])

    def test_get_browser_sandbox_tools(self):
        tools = get_browser_sandbox_tools()
        assert [tool.name for tool in tools] == ["tool_browser_snapshot_url"]


class TestBrowserSandboxToolRegistration:
    @patch("app.engine.tools.get_tool_registry")
    @patch("app.core.config.get_settings")
    @patch("app.engine.tools.browser_sandbox_tools.get_browser_sandbox_tools")
    def test_extended_tools_register_browser_tool_when_enabled(
        self,
        mock_get_browser_tools,
        mock_get_settings,
        mock_get_registry,
    ):
        registry = mock_get_registry.return_value
        mock_tool = tool_browser_snapshot_url
        mock_get_browser_tools.return_value = [mock_tool]
        mock_get_settings.return_value = SimpleNamespace(
            enable_filesystem_tools=False,
            enable_code_execution=False,
            enable_skill_creation=False,
            enable_scheduler=False,
            enable_product_search=False,
            enable_visual_product_search=False,
            enable_lms_integration=False,
            enable_character_tools=False,
            enable_browser_agent=True,
            enable_privileged_sandbox=True,
            sandbox_provider="opensandbox",
            sandbox_allow_browser_workloads=True,
        )

        _init_extended_tools()

        registry.register.assert_called_once_with(
            mock_tool,
            ToolCategory.EXECUTION,
            ToolAccess.WRITE,
            roles=["admin"],
        )
