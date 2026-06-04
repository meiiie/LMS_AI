"""Phase 15 SubagentRunner ↔ ChatService bridge — Runtime Migration #207.

Locks the production wire shape:
- description + context_hints become the child's user-message body.
- ChatService.process_message returns InternalChatResponse → coerced into
  SubagentResult with sources, tool counts, and the child session id.
- Source coercion is defensive (model_dump or dict; anything else dropped).
- get_subagent_runner() auto-wires the default callable on first call.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest


def _enable_isolation(monkeypatch):
    from app.core import config as config_module

    monkeypatch.setattr(
        config_module.settings, "enable_subagent_isolation", True, raising=False
    )


@pytest.fixture
def fake_internal_response():
    src = SimpleNamespace(
        model_dump=lambda: {"id": "doc-1", "page": 5}
    )
    return SimpleNamespace(
        message="Trả lời từ child agent.",
        sources=[src],
        metadata={
            "tools_used": [{"name": "search"}, {"name": "lookup"}],
            "latency_ms": 320,
        },
    )


# ── description formatting ──

def test_format_description_plain():
    from app.engine.runtime.subagent_chatservice_bridge import _format_description
    from app.engine.runtime.subagent_runner import SubagentTask

    out = _format_description(
        SubagentTask(description="Tìm Rule 13 COLREGs", parent_session_id="p1")
    )
    assert out == "Tìm Rule 13 COLREGs"


def test_format_description_with_context_hints():
    from app.engine.runtime.subagent_chatservice_bridge import _format_description
    from app.engine.runtime.subagent_runner import SubagentTask

    out = _format_description(
        SubagentTask(
            description="Tóm tắt phần 1",
            parent_session_id="p1",
            context_hints={"chapter": "Phần 1: Tổng quan", "level": "beginner"},
        )
    )
    assert "Tóm tắt phần 1" in out
    assert "chapter: Phần 1: Tổng quan" in out
    assert "level: beginner" in out


# ── source / tool-call coercion ──

def test_format_description_sanitizes_and_bounds_context_hints():
    from app.engine.runtime.subagent_chatservice_bridge import _format_description
    from app.engine.runtime.subagent_runner import SubagentTask

    out = _format_description(
        SubagentTask(
            description="safe summary",
            parent_session_id="p1",
            context_hints={
                "focus": (
                    "navigation Bearer raw-bearer-token-123 "
                    "api_key=raw-api-key-inline"
                ),
                "access_token": "raw-access-token",
                "document_context": "A" * 900,
            },
        )
    )

    assert "safe summary" in out
    assert "<redacted-secret>" in out
    assert "raw-bearer-token-123" not in out
    assert "raw-api-key-inline" not in out
    assert "raw-access-token" not in out
    assert "access_token" not in out
    assert "A" * 600 not in out


def test_coerce_sources_handles_pydantic_and_dict():
    from app.engine.runtime.subagent_chatservice_bridge import _coerce_sources

    pydantic_like = SimpleNamespace(model_dump=lambda: {"id": "p1"})
    plain_dict = {"id": "p2"}
    bad_value = "not-a-source"
    response = SimpleNamespace(sources=[pydantic_like, plain_dict, bad_value])
    out = _coerce_sources(response)
    assert out == [{"id": "p1"}, {"id": "p2"}]


def test_coerce_sources_returns_safe_citation_metadata_only():
    from app.engine.runtime.subagent_chatservice_bridge import _coerce_sources

    response = SimpleNamespace(
        sources=[
            {
                "id": "doc-1",
                "page": 5,
                "title": "COLREG Bearer raw-source-token-123",
                "content": "raw document text must stay in child log only",
                "content_snippet": "raw snippet",
                "access_token": "raw-access-token",
                "provider_payload": {"id": "raw-provider"},
                "bounding_boxes": [{"x": i} for i in range(20)],
            }
        ]
    )

    out = _coerce_sources(response)

    assert out[0]["id"] == "doc-1"
    assert out[0]["page"] == 5
    assert "<redacted-secret>" in out[0]["title"]
    assert len(out[0]["bounding_boxes"]) == 8
    serialized = str(out)
    assert "content" not in serialized
    assert "raw document text" not in serialized
    assert "raw snippet" not in serialized
    assert "raw-access-token" not in serialized
    assert "raw-provider" not in serialized


def test_coerce_sources_no_sources_attribute():
    from app.engine.runtime.subagent_chatservice_bridge import _coerce_sources

    assert _coerce_sources(SimpleNamespace()) == []


def test_count_tool_calls_prefers_tools_used():
    from app.engine.runtime.subagent_chatservice_bridge import _count_tool_calls

    response = SimpleNamespace(metadata={"tools_used": [1, 2, 3]})
    assert _count_tool_calls(response) == 3


def test_count_tool_calls_falls_back_to_tool_calls():
    from app.engine.runtime.subagent_chatservice_bridge import _count_tool_calls

    response = SimpleNamespace(metadata={"tool_calls": [1, 2]})
    assert _count_tool_calls(response) == 2


def test_count_tool_calls_returns_zero_for_unknown_shape():
    from app.engine.runtime.subagent_chatservice_bridge import _count_tool_calls

    assert _count_tool_calls(SimpleNamespace(metadata={})) == 0
    assert _count_tool_calls(SimpleNamespace()) == 0


# ── end-to-end run via the bridge ──

async def test_bridge_runs_chatservice_and_builds_subagent_result(
    monkeypatch, fake_internal_response
):
    _enable_isolation(monkeypatch)

    from app.engine.runtime.subagent_chatservice_bridge import (
        chatservice_subagent_runner,
    )
    from app.engine.runtime.subagent_runner import SubagentTask

    fake_service = SimpleNamespace(
        process_message=AsyncMock(return_value=fake_internal_response)
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        task = SubagentTask(
            description="Giải thích Rule 13",
            parent_session_id="p1",
            parent_org_id="org-A",
            context_hints={"focus": "navigation"},
        )
        result = await chatservice_subagent_runner(task, "child-xyz")

    assert result.status == "success"
    assert result.summary == "Trả lời từ child agent."
    assert result.child_session_id == "child-xyz"
    assert result.tool_calls_made == 2
    assert result.sources == [{"id": "doc-1", "page": 5}]
    # ChatService received exactly one ChatRequest with the expected fields.
    fake_service.process_message.assert_awaited_once()
    chat_request = fake_service.process_message.await_args.args[0]
    assert "Giải thích Rule 13" in chat_request.message
    assert "focus: navigation" in chat_request.message
    assert chat_request.session_id == "child-xyz"
    assert chat_request.organization_id == "org-A"


async def test_bridge_propagates_chatservice_exception(monkeypatch):
    _enable_isolation(monkeypatch)

    from app.engine.runtime.subagent_chatservice_bridge import (
        chatservice_subagent_runner,
    )
    from app.engine.runtime.subagent_runner import SubagentTask

    fake_service = SimpleNamespace(
        process_message=AsyncMock(side_effect=RuntimeError("provider down"))
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        with pytest.raises(RuntimeError, match="provider down"):
            await chatservice_subagent_runner(
                SubagentTask(description="x", parent_session_id="p1"),
                "child-xyz",
            )


# ── singleton auto-wiring ──

async def test_get_subagent_runner_auto_wires_default(
    monkeypatch, fake_internal_response
):
    _enable_isolation(monkeypatch)
    from app.engine.runtime import subagent_runner as runner_module

    runner_module._reset_for_tests()
    fake_service = SimpleNamespace(
        process_message=AsyncMock(return_value=fake_internal_response)
    )
    with patch(
        "app.services.chat_service.get_chat_service", return_value=fake_service
    ):
        runner = runner_module.get_subagent_runner()
        # _runner is bound on first access — no manual wire required.
        assert runner._runner is not None
        from app.engine.runtime.subagent_runner import SubagentTask

        result = await runner.run(
            SubagentTask(description="hi", parent_session_id="p1")
        )
    assert result.status == "success"
    assert result.summary == "Trả lời từ child agent."
    runner_module._reset_for_tests()
