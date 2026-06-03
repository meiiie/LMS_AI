"""Tests for sandbox execution orchestration service."""

from __future__ import annotations

from textwrap import dedent

import pytest

from app.sandbox.catalog import SandboxWorkloadCatalog
from app.sandbox.models import (
    SandboxExecutionResult,
    SandboxNetworkMode,
    SandboxWorkloadKind,
)
from app.sandbox.service import SandboxExecutionContext, SandboxExecutionService


def _make_catalog(tmp_path) -> SandboxWorkloadCatalog:
    (tmp_path / "python_exec.yaml").write_text(
        dedent(
            """
            id: python_exec
            display_name: Privileged Python Execution
            description: Execute Python source code inside the privileged sandbox.
            workload_kind: python
            runtime_template: code-interpreter
            network_mode: egress
            timeout_seconds: 120
            working_directory: /workspace
            approval_scope: privileged_execution
            execution_backend: opensandbox
            tool_names:
              - tool_execute_python
            capabilities:
              - python
            metadata:
              risk_level: high
            """
        ).strip(),
        encoding="utf-8",
    )
    return SandboxWorkloadCatalog(tmp_path)


class TestSandboxExecutionService:
    def test_build_request_applies_profile_defaults_and_context(self, tmp_path):
        catalog = _make_catalog(tmp_path)
        service = SandboxExecutionService(
            catalog_provider=lambda: catalog,
            executor_provider=lambda: None,
        )

        request = service.build_request(
            "python_exec",
            code="print('hello')",
            timeout_seconds=45,
            metadata={"job": "unit-test", "access_token": "raw-access-token"},
            context=SandboxExecutionContext(
                tool_name="tool_execute_python",
                source="tool_registry",
                organization_id="org_123",
                user_id="user_456",
                session_id="sess_789",
                request_id="req_abc",
            ),
        )

        assert request.workload_kind == SandboxWorkloadKind.PYTHON
        assert request.runtime_template == "code-interpreter"
        assert request.network_mode == SandboxNetworkMode.EGRESS
        assert request.timeout_seconds == 45
        assert request.working_directory == "/workspace"
        assert request.organization_id == "org_123"
        assert request.user_id == "user_456"
        assert request.session_id == "sess_789"
        assert request.request_id == "req_abc"
        assert request.metadata["profile_id"] == "python_exec"
        assert request.metadata["profile_name"] == "Privileged Python Execution"
        assert request.metadata["approval_scope"] == "privileged_execution"
        assert request.metadata["execution_backend"] == "opensandbox"
        assert request.metadata["request_source"] == "tool_registry"
        assert request.metadata["tool_name"] == "tool_execute_python"
        assert request.metadata["job"] == "unit-test"
        assert request.metadata["risk_level"] == "high"
        assert request.metadata["capabilities"] == ["python"]
        assert request.metadata["user_id_hash"].startswith("sha256:")
        serialized = str(request.metadata)
        assert "user_456" not in serialized
        assert "raw-access-token" not in serialized
        assert "access_token" not in serialized

    @pytest.mark.asyncio
    async def test_execute_profile_fails_closed_when_executor_missing(self, tmp_path):
        catalog = _make_catalog(tmp_path)
        service = SandboxExecutionService(
            catalog_provider=lambda: catalog,
            executor_provider=lambda: None,
        )

        result = await service.execute_profile(
            "python_exec",
            code="print('hello')",
        )

        assert result.success is False
        assert "No privileged sandbox executor is configured" in (result.error or "")
        assert result.metadata["profile_id"] == "python_exec"

    @pytest.mark.asyncio
    async def test_execute_profile_delegates_request_to_executor(self, tmp_path):
        captured = {}
        catalog = _make_catalog(tmp_path)

        class _Executor:
            async def execute(self, request):
                captured["request"] = request
                return SandboxExecutionResult(
                    success=True,
                    stdout="ok",
                    metadata=dict(request.metadata),
                )

        service = SandboxExecutionService(
            catalog_provider=lambda: catalog,
            executor_provider=lambda: _Executor(),
        )

        result = await service.execute_profile(
            "python_exec",
            code="print('hello')",
            context=SandboxExecutionContext(tool_name="tool_execute_python"),
        )

        assert result.success is True
        assert result.stdout == "ok"
        assert captured["request"].code == "print('hello')"
        assert captured["request"].metadata["tool_name"] == "tool_execute_python"
