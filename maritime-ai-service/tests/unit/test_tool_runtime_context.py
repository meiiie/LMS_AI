"""Tests for shared tool runtime context propagation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import structlog

from app.engine.tools.runtime_context import (
    build_sandbox_execution_context,
    build_tool_runtime_context,
    build_runtime_correlation_metadata,
    emit_tool_bus_event,
    filter_tools_for_role,
    tool_runtime_scope,
)


class TestToolRuntimeContext:
    def teardown_method(self):
        structlog.contextvars.clear_contextvars()

    @patch("app.engine.tools.registry.get_tool_registry")
    def test_filter_tools_for_role_uses_registry_roles(self, mock_get_registry):
        tool_student = SimpleNamespace(name="tool_student")
        tool_admin = SimpleNamespace(name="tool_admin")

        registry = MagicMock()
        registry.get_info.side_effect = lambda name: {
            "tool_student": SimpleNamespace(roles=["student", "admin"]),
            "tool_admin": SimpleNamespace(roles=["admin"]),
        }.get(name)
        mock_get_registry.return_value = registry

        student_tools = filter_tools_for_role([tool_student, tool_admin], "student")
        admin_tools = filter_tools_for_role([tool_student, tool_admin], "admin")

        assert [tool.name for tool in student_tools] == ["tool_student"]
        assert [tool.name for tool in admin_tools] == ["tool_student", "tool_admin"]

    def test_emit_tool_bus_event_injects_runtime_node(self):
        queue = MagicMock()

        with patch(
            "app.engine.multi_agent.graph_streaming._get_event_queue",
            return_value=queue,
        ):
            with tool_runtime_scope(
                build_tool_runtime_context(
                    event_bus_id="bus-1",
                    request_id="req-1",
                    node="tutor_agent",
                    source="agentic_loop",
                )
            ):
                ok = emit_tool_bus_event(
                    {
                        "type": "artifact",
                        "content": {"artifact_id": "a1"},
                    }
                )

        assert ok is True
        queue.put_nowait.assert_called_once_with(
            {
                "type": "artifact",
                "content": {
                    "artifact_id": "a1",
                    "metadata": {
                        "request_id": "req-1",
                        "node": "tutor_agent",
                        "request_source": "agentic_loop",
                    },
                },
                "node": "tutor_agent",
            }
        )

    def test_build_sandbox_execution_context_uses_current_runtime_scope(self):
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
                metadata={
                    "trace_id": "trace-1",
                    "access_token": "raw-runtime-token",
                },
            ).for_tool("tool_execute_python", tool_call_id="tc-1")
        ):
            context = build_sandbox_execution_context(
                "tool_execute_python",
                approval_scope="privileged_execution",
                metadata={"origin": "unit-test", "api_key": "raw-api-key"},
            )

        assert context.tool_name == "tool_execute_python"
        assert context.source == "agentic_loop"
        assert context.organization_id == "org-1"
        assert context.user_id == "user-1"
        assert context.session_id == "sess-1"
        assert context.request_id == "req-1"
        assert context.approval_scope == "privileged_execution"
        assert context.metadata["trace_id"] == "trace-1"
        assert context.metadata["node"] == "direct"
        assert context.metadata["tool_call_id"] == "tc-1"
        assert context.metadata["origin"] == "unit-test"
        serialized = str(context.metadata)
        assert "raw-runtime-token" not in serialized
        assert "raw-api-key" not in serialized
        assert "access_token" not in serialized
        assert "api_key" not in serialized

    def test_build_tool_runtime_context_prefers_bound_request_id(self):
        structlog.contextvars.bind_contextvars(request_id="http-req-1")

        context = build_tool_runtime_context(
            event_bus_id="bus-1",
            session_id="sess-1",
            source="agentic_loop",
        )

        assert context.request_id == "http-req-1"

    def test_build_runtime_correlation_metadata_includes_runtime_metadata(self):
        with tool_runtime_scope(
            build_tool_runtime_context(
                request_id="req-1",
                session_id="sess-1",
                organization_id="org-1",
                user_id="user-1",
                user_role="admin",
                node="direct",
                source="mcp_http",
                metadata={
                    "mcp_call_id": "mcp-call-1",
                    "access_token": "raw-access-token",
                },
            ).for_tool("tool_browser_snapshot_url", tool_call_id="tc-1")
        ):
            metadata = build_runtime_correlation_metadata()

        assert metadata["request_id"] == "req-1"
        assert metadata["session_id"] == "sess-1"
        assert metadata["organization_id"] == "org-1"
        assert metadata["user_id_hash"].startswith("sha256:")
        assert metadata["user_role"] == "admin"
        assert metadata["node"] == "direct"
        assert metadata["request_source"] == "mcp_http"
        assert metadata["tool_name"] == "tool_browser_snapshot_url"
        assert metadata["tool_call_id"] == "tc-1"
        assert metadata["mcp_call_id"] == "mcp-call-1"
        assert "user_id" not in metadata
        assert "access_token" not in metadata
        assert "raw-access-token" not in str(metadata)
