"""Unit tests for the privileged OpenSandbox execution abstraction."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.sandbox import (
    OpenSandboxExecutor,
    SandboxExecutionRequest,
    SandboxNetworkMode,
    SandboxProvider,
    SandboxWorkloadKind,
    get_sandbox_executor,
    reset_sandbox_executor,
)
from app.sandbox.opensandbox_executor import OpenSandboxSdk


def _make_settings(**overrides) -> Settings:
    defaults = {
        "environment": "development",
        "api_key": "test-key",
        "google_api_key": "test-google-key",
        "sandbox_allow_browser_workloads": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


class TestSandboxConfigValidators:
    def test_accepts_opensandbox_provider(self):
        settings = _make_settings(sandbox_provider="opensandbox")
        assert settings.sandbox_provider == "opensandbox"

    def test_rejects_unknown_sandbox_provider(self):
        with pytest.raises(ValidationError, match="sandbox_provider must be one of"):
            _make_settings(sandbox_provider="unknown")

    def test_accepts_opensandbox_network_mode(self):
        settings = _make_settings(opensandbox_network_mode="egress")
        assert settings.opensandbox_network_mode == "egress"

    def test_rejects_unknown_network_mode(self):
        with pytest.raises(
            ValidationError,
            match="opensandbox_network_mode must be one of",
        ):
            _make_settings(opensandbox_network_mode="internet")


class TestSandboxFactory:
    def teardown_method(self):
        reset_sandbox_executor()

    def test_returns_none_when_disabled(self):
        settings = _make_settings(enable_privileged_sandbox=False)
        with patch("app.sandbox.factory.get_settings", return_value=settings):
            reset_sandbox_executor()
            assert get_sandbox_executor() is None

    def test_returns_opensandbox_executor(self):
        settings = _make_settings(
            enable_privileged_sandbox=True,
            sandbox_provider="opensandbox",
            opensandbox_base_url="http://opensandbox.local",
        )
        with patch("app.sandbox.factory.get_settings", return_value=settings):
            reset_sandbox_executor()
            executor = get_sandbox_executor()

        assert isinstance(executor, OpenSandboxExecutor)
        assert executor.provider == SandboxProvider.OPENSANDBOX


class TestOpenSandboxExecutor:
    def _make_executor(self, **overrides) -> OpenSandboxExecutor:
        settings_kwargs = {
            "enable_privileged_sandbox": True,
            "sandbox_provider": "opensandbox",
            "opensandbox_base_url": "http://opensandbox.local",
            "opensandbox_code_template": "python-dev",
            "opensandbox_browser_template": "browser-dev",
            "opensandbox_network_mode": "egress",
            "sandbox_default_timeout_seconds": 180,
        }
        settings_kwargs.update(overrides)
        settings = _make_settings(**settings_kwargs)
        return OpenSandboxExecutor.from_settings(settings)

    def test_selects_code_template_for_python(self):
        executor = self._make_executor()
        request = SandboxExecutionRequest(workload_kind=SandboxWorkloadKind.PYTHON)
        assert executor.select_template(request) == "python-dev"

    def test_selects_browser_template_for_browser(self):
        executor = self._make_executor()
        request = SandboxExecutionRequest(workload_kind=SandboxWorkloadKind.BROWSER)
        assert executor.select_template(request) == "browser-dev"

    def test_plan_uses_executor_network_mode_by_default(self):
        executor = self._make_executor()
        request = SandboxExecutionRequest(workload_kind=SandboxWorkloadKind.COMMAND)

        plan = executor.plan(request)

        assert plan.network_mode.value == "egress"
        assert plan.timeout_seconds == 180

    def test_build_labels_captures_execution_scope(self):
        executor = self._make_executor()
        request = SandboxExecutionRequest(
            workload_kind=SandboxWorkloadKind.PYTHON,
            organization_id="org_123",
            user_id="user_456",
            session_id="sess_789",
            request_id="req_abc",
        )

        labels = executor.build_labels(request)

        assert labels["wiii.provider"] == "opensandbox"
        assert labels["wiii.org"] == "org_123"
        assert labels["wiii.user"].startswith("sha256:")
        assert labels["wiii.session"] == "sess_789"
        assert labels["wiii.request"] == "req_abc"
        assert labels["wiii.workload"] == "python"
        assert "user_456" not in str(labels)

    def test_build_network_policy_denies_all_when_disabled(self):
        captured = {}

        class _NetworkPolicy:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        executor = self._make_executor(opensandbox_network_mode="disabled")
        policy = executor.build_network_policy(
            SandboxNetworkMode.DISABLED,
            _NetworkPolicy,
        )

        assert isinstance(policy, _NetworkPolicy)
        assert captured["defaultAction"] == "deny"
        assert captured["egress"] == []

    @pytest.mark.asyncio
    async def test_healthcheck_uses_configured_path(self):
        called = {}

        class _Response:
            status_code = 204

        class _Client:
            def __init__(self, *, timeout):
                called["timeout"] = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, url, headers=None):
                called["url"] = url
                called["headers"] = headers
                return _Response()

        executor = self._make_executor(
            opensandbox_healthcheck_path="/readyz",
            opensandbox_api_key="secret-token",
        )

        with patch("app.sandbox.opensandbox_executor.httpx.AsyncClient", _Client):
            ok = await executor.healthcheck()

        assert ok is True
        assert called["url"] == "http://opensandbox.local/readyz"
        assert called["headers"]["Authorization"] == "Bearer secret-token"
        assert called["timeout"] == 5.0

    @pytest.mark.asyncio
    async def test_execute_returns_dependency_error_when_sdk_missing(self):
        executor = self._make_executor()
        request = SandboxExecutionRequest(
            workload_kind=SandboxWorkloadKind.PYTHON,
            code="print('hello')",
        )

        with patch(
            "app.sandbox.opensandbox_executor._load_opensandbox_sdk",
            side_effect=ImportError("missing opensandbox"),
        ):
            result = await executor.execute(request)

        assert result.success is False
        assert "OpenSandbox SDK is not installed" in (result.error or "")
        assert "missing opensandbox" in result.metadata["dependency_error"]

    @pytest.mark.asyncio
    async def test_execute_runs_python_in_opensandbox(self):
        captured = {}

        class _ConnectionConfig:
            def __init__(self, **kwargs):
                captured["connection_config"] = kwargs

        class _WriteEntry:
            def __init__(self, *, path, data, mode=755):
                self.path = path
                self.data = data
                self.mode = mode

        class _RunCommandOpts:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class _Files:
            async def write_files(self, entries):
                captured.setdefault("files", [])
                captured["files"].extend(
                    {"path": entry.path, "data": entry.data, "mode": entry.mode}
                    for entry in entries
                )

        class _Commands:
            async def run(self, command, *, opts):
                captured["command"] = command
                captured["opts"] = opts.kwargs
                return SimpleNamespace(
                    id="exec-789",
                    logs=SimpleNamespace(
                        stdout=[SimpleNamespace(text="Hello from sandbox\n")],
                        stderr=[],
                    ),
                    result=[SimpleNamespace(text="42")],
                    error=None,
                )

        class _SandboxInstance:
            id = "sandbox-123"
            files = _Files()
            commands = _Commands()

            async def kill(self):
                captured["killed"] = True

            async def close(self):
                captured["closed"] = True

        class _Sandbox:
            @staticmethod
            async def create(template, **kwargs):
                captured["template"] = template
                captured["sandbox_kwargs"] = kwargs
                return _SandboxInstance()

        sdk = OpenSandboxSdk(
            code_interpreter=object,
            connection_config=_ConnectionConfig,
            network_policy=object,
            run_command_opts=_RunCommandOpts,
            sandbox=_Sandbox,
            supported_language=object,
            write_entry=_WriteEntry,
        )

        executor = self._make_executor()
        request = SandboxExecutionRequest(
            workload_kind=SandboxWorkloadKind.PYTHON,
            code="print('hello')",
            files={"data/input.txt": "payload"},
            metadata={
                "purpose": "unit-test",
                "access_token": "raw-access-token",
            },
            working_directory="/workspace",
            organization_id="org_123",
            user_id="user_456",
            session_id="sess_789",
            request_id="req_abc",
        )

        with patch(
            "app.sandbox.opensandbox_executor._load_opensandbox_sdk",
            return_value=sdk,
        ):
            result = await executor.execute(request)

        assert result.success is True
        assert result.stdout == "Hello from sandbox\n42"
        assert result.exit_code == 0
        assert result.error is None
        assert result.sandbox_id == "sandbox-123"
        assert result.metadata["provider"] == "opensandbox"
        assert result.metadata["execution_id"] == "exec-789"
        assert result.metadata["sandbox_id"] == "sandbox-123"
        assert result.metadata["purpose"] == "unit-test"
        assert result.metadata["request_id"] == "req_abc"
        assert result.metadata["session_id"] == "sess_789"
        assert result.metadata["organization_id"] == "org_123"
        assert result.metadata["user_id_hash"].startswith("sha256:")
        assert "user_456" not in str(result.metadata)
        assert "raw-access-token" not in str(result.metadata)
        assert "access_token" not in str(result.metadata)

        assert captured["template"] == "python-dev"
        assert captured["command"] == "mkdir -p /workspace && cd /workspace && python /tmp/wiii_exec.py"
        assert captured["opts"]["timeout"].total_seconds() == 180

        sandbox_kwargs = captured["sandbox_kwargs"]
        assert sandbox_kwargs["env"] is None
        assert sandbox_kwargs["network_policy"] is None
        assert sandbox_kwargs["metadata"]["wiii.org"] == "org_123"
        assert sandbox_kwargs["metadata"]["wiii.user"].startswith("sha256-")
        assert sandbox_kwargs["metadata"]["wiii.session"] == "sess_789"
        assert sandbox_kwargs["metadata"]["wiii.request"] == "req_abc"
        assert sandbox_kwargs["metadata"]["wiii.template"] == "python-dev"
        assert sandbox_kwargs["metadata"]["wiii.network_mode"] == "egress"
        assert sandbox_kwargs["metadata"]["wiii.meta.keepalive_seconds"] == "600"
        assert sandbox_kwargs["metadata"]["wiii.meta.purpose"] == "unit-test"
        assert "user_456" not in str(sandbox_kwargs["metadata"])
        assert "raw-access-token" not in str(sandbox_kwargs["metadata"])
        assert "access_token" not in str(sandbox_kwargs["metadata"])

        config_kwargs = captured["connection_config"]
        assert config_kwargs["api_key"] is None
        assert config_kwargs["domain"] == "http://opensandbox.local"
        assert config_kwargs["protocol"] == "http"
        assert config_kwargs["use_server_proxy"] is False
        assert config_kwargs["request_timeout"].total_seconds() == 190

        assert captured["files"][0] == {"path": "data/input.txt", "data": "payload", "mode": 644}
        assert captured["files"][1]["path"] == "/tmp/wiii_exec.py"
        assert "__wiii_os.chdir(\"/workspace\")" in captured["files"][1]["data"]
        assert captured["killed"] is True
        assert captured["closed"] is True

    @pytest.mark.asyncio
    async def test_execute_rejects_browser_workloads_when_disabled(self):
        executor = self._make_executor()
        request = SandboxExecutionRequest(workload_kind=SandboxWorkloadKind.BROWSER)

        result = await executor.execute(request)

        assert result.success is False
        assert "not enabled" in (result.error or "")

    @pytest.mark.asyncio
    async def test_execute_runs_browser_workload_when_enabled(self):
        captured = {}

        class _ConnectionConfig:
            def __init__(self, **kwargs):
                captured["connection_config"] = kwargs

        class _WriteEntry:
            def __init__(self, *, path, data, mode=755):
                self.path = path
                self.data = data
                self.mode = mode

        class _RunCommandOpts:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class _Files:
            async def write_files(self, entries):
                captured["files"] = [
                    {"path": entry.path, "data": entry.data, "mode": entry.mode}
                    for entry in entries
                ]

        class _Commands:
            async def run(self, command, *, opts):
                captured["command"] = command
                captured["opts"] = opts.kwargs
                return SimpleNamespace(
                    id="exec-browser",
                    logs=SimpleNamespace(
                        stdout=[SimpleNamespace(text="browser ready\n")],
                        stderr=[],
                    ),
                    result=[],
                    error=None,
                )

        class _SandboxInstance:
            id = "sandbox-browser"
            files = _Files()
            commands = _Commands()

            async def kill(self):
                captured["killed"] = True

            async def close(self):
                captured["closed"] = True

        class _Sandbox:
            @staticmethod
            async def create(template, **kwargs):
                captured["template"] = template
                captured["sandbox_kwargs"] = kwargs
                return _SandboxInstance()

        sdk = OpenSandboxSdk(
            code_interpreter=object,
            connection_config=_ConnectionConfig,
            network_policy=object,
            run_command_opts=_RunCommandOpts,
            sandbox=_Sandbox,
            supported_language=object,
            write_entry=_WriteEntry,
        )

        executor = self._make_executor(sandbox_allow_browser_workloads=True)
        request = SandboxExecutionRequest(
            workload_kind=SandboxWorkloadKind.BROWSER,
            command=["node", "runner.js", "--url", "https://example.com"],
            files={"runner.js": "console.log('ok')"},
            working_directory="/workspace",
        )

        with patch(
            "app.sandbox.opensandbox_executor._load_opensandbox_sdk",
            return_value=sdk,
        ):
            result = await executor.execute(request)

        assert result.success is True
        assert result.stdout == "browser ready"
        assert result.sandbox_id == "sandbox-browser"
        assert result.metadata["planned_template"] == "browser-dev"
        assert result.metadata["planned_workload_kind"] == "browser"

        assert captured["template"] == "browser-dev"
        assert captured["command"] == "node runner.js --url https://example.com"
        assert captured["opts"]["working_directory"] == "/workspace"
        assert captured["opts"]["timeout"].total_seconds() == 180
        assert captured["files"] == [
            {"path": "runner.js", "data": "console.log('ok')", "mode": 644}
        ]
        assert captured["killed"] is True
        assert captured["closed"] is True

    @pytest.mark.asyncio
    async def test_execute_harvests_generated_files_as_artifacts(self):
        class _SearchEntry:
            def __init__(self, *, path, pattern, recursive=False):
                self.path = path
                self.pattern = pattern
                self.recursive = recursive

        class _ConnectionConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class _WriteEntry:
            def __init__(self, *, path, data, mode=755):
                self.path = path
                self.data = data
                self.mode = mode

        class _RunCommandOpts:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class _Files:
            async def write_files(self, entries):
                return None

            async def search(self, entry):
                if entry.path != "/workspace":
                    return []
                if entry.pattern == "*.png":
                    return [SimpleNamespace(path="/workspace/chart.png")]
                if entry.pattern == "*.html":
                    return [SimpleNamespace(path="/workspace/report.html")]
                if entry.pattern == "*.docx":
                    return [SimpleNamespace(path="/workspace/brief.docx")]
                return []

            async def read_file(self, path):
                if path.endswith(".png"):
                    return b"\x89PNG\r\n\x1a\nbinary"
                if path.endswith(".html"):
                    return "<html><body><h1>Hello</h1></body></html>"
                if path.endswith(".docx"):
                    return b"PK\x03\x04word"
                raise RuntimeError("unexpected file read")

        class _Commands:
            async def run(self, command, *, opts):
                return SimpleNamespace(
                    id="exec-artifacts",
                    logs=SimpleNamespace(stdout=[], stderr=[]),
                    result=[],
                    error=None,
                )

        class _SandboxInstance:
            id = "sandbox-artifacts"
            files = _Files()
            commands = _Commands()

            async def kill(self):
                return None

            async def close(self):
                return None

        class _Sandbox:
            @staticmethod
            async def create(template, **kwargs):
                return _SandboxInstance()

        sdk = OpenSandboxSdk(
            code_interpreter=object,
            connection_config=_ConnectionConfig,
            network_policy=object,
            run_command_opts=_RunCommandOpts,
            sandbox=_Sandbox,
            supported_language=object,
            write_entry=_WriteEntry,
            search_entry=_SearchEntry,
        )

        executor = self._make_executor()
        request = SandboxExecutionRequest(
            workload_kind=SandboxWorkloadKind.PYTHON,
            code="print('hello')",
            working_directory="/workspace",
        )

        with patch(
            "app.sandbox.opensandbox_executor._load_opensandbox_sdk",
            return_value=sdk,
        ):
            result = await executor.execute(request)

        assert result.success is True
        assert [artifact.name for artifact in result.artifacts] == [
            "report.html",
            "chart.png",
            "brief.docx",
        ]
        assert result.metadata["artifact_count"] == 3

        html_artifact = result.artifacts[0]
        assert html_artifact.content_type == "text/html"
        assert html_artifact.url
        assert "/api/v1/generated-files/" in (html_artifact.url or "")
        assert "generated" in (html_artifact.path or "")
        assert html_artifact.metadata["published_from_sandbox"] is True
        assert html_artifact.metadata["sandbox_path"] == "/workspace/report.html"
        assert html_artifact.metadata["inline_encoding"] == "text"
        assert "<h1>Hello</h1>" in html_artifact.metadata["inline_content"]

        chart_artifact = result.artifacts[1]
        assert chart_artifact.content_type == "image/png"
        assert chart_artifact.url
        assert "generated" in (chart_artifact.path or "")
        assert chart_artifact.metadata["inline_encoding"] == "base64"

        docx_artifact = result.artifacts[2]
        assert docx_artifact.content_type.endswith("wordprocessingml.document")
        assert docx_artifact.url
        assert "generated" in (docx_artifact.path or "")
        assert "inline_content" not in docx_artifact.metadata

    @pytest.mark.asyncio
    async def test_harvest_uses_read_bytes_for_binary_artifacts(self):
        class _SearchEntry:
            def __init__(self, *, path, pattern, recursive=False):
                self.path = path
                self.pattern = pattern
                self.recursive = recursive

        class _ConnectionConfig:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class _WriteEntry:
            def __init__(self, *, path, data, mode=755):
                self.path = path
                self.data = data
                self.mode = mode

        class _RunCommandOpts:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class _Files:
            async def write_files(self, entries):
                return None

            async def search(self, entry):
                if entry.path == "/workspace" and entry.pattern == "*.png":
                    return [SimpleNamespace(path="/workspace/chart.png")]
                return []

            async def read_bytes(self, path):
                assert path == "/workspace/chart.png"
                return b"\x89PNG\r\n\x1a\nbinary"

            async def read_file(self, path):
                raise AssertionError("binary artifact should be read with read_bytes")

        class _Commands:
            async def run(self, command, *, opts):
                return SimpleNamespace(
                    id="exec-artifacts-bytes",
                    logs=SimpleNamespace(stdout=[], stderr=[]),
                    result=[],
                    error=None,
                )

        class _SandboxInstance:
            id = "sandbox-artifacts-bytes"
            files = _Files()
            commands = _Commands()

            async def kill(self):
                return None

            async def close(self):
                return None

        class _Sandbox:
            @staticmethod
            async def create(template, **kwargs):
                return _SandboxInstance()

        sdk = OpenSandboxSdk(
            code_interpreter=object,
            connection_config=_ConnectionConfig,
            network_policy=object,
            run_command_opts=_RunCommandOpts,
            sandbox=_Sandbox,
            supported_language=object,
            write_entry=_WriteEntry,
            search_entry=_SearchEntry,
        )

        executor = self._make_executor()
        request = SandboxExecutionRequest(
            workload_kind=SandboxWorkloadKind.PYTHON,
            code="print('hello')",
            working_directory="/workspace",
        )

        with patch(
            "app.sandbox.opensandbox_executor._load_opensandbox_sdk",
            return_value=sdk,
        ):
            result = await executor.execute(request)

        assert result.success is True
        assert len(result.artifacts) == 1
        chart_artifact = result.artifacts[0]
        assert chart_artifact.content_type == "image/png"
        assert chart_artifact.url
        assert chart_artifact.metadata["published_from_sandbox"] is True
        assert chart_artifact.metadata["inline_encoding"] == "base64"
