"""Generic tool dispatch helpers for direct tool-round execution."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from app.engine.multi_agent.tool_event_sanitizer import sanitize_tool_args_for_event
from app.engine.multi_agent.direct_tool_sources import (
    extract_source_infos_from_tool_result,
)
from app.engine.multi_agent.tool_policy_session import (
    tool_policy_denial_message,
    tool_policy_session_from_state,
)


@dataclass(slots=True)
class DirectToolDispatchResult:
    """Result of one normalized direct tool call dispatch."""

    tool_call_id: str
    tool_name: str
    tool_args: dict[str, Any]
    result: Any
    matched: bool


def normalize_tool_call(tool_call: Any) -> dict[str, Any]:
    """Normalize provider-specific tool call objects to Wiii's dict shape."""
    if isinstance(tool_call, dict):
        return tool_call
    return {
        "id": getattr(tool_call, "id", "") or "",
        "name": getattr(tool_call, "name", "") or "",
        "args": getattr(tool_call, "arguments", None)
        or getattr(tool_call, "args", None)
        or {},
    }


async def dispatch_direct_tool_call(
    *,
    tool_call: dict[str, Any],
    tool_round: int,
    tools: list[Any],
    query: str,
    state: dict[str, Any] | None = None,
    push_event,
    tool_call_events: list[dict[str, Any]],
    get_tool_by_name,
    invoke_tool_with_runtime,
    runtime_context_base: Any,
    is_search_tool_name,
    prefer_official_query_for_known_docs,
    summarize_tool_result_for_stream,
    logger_obj: logging.Logger,
) -> DirectToolDispatchResult:
    """Run one tool call and emit the stable SSE call/result event pair."""
    tool_call_id = str(tool_call.get("id") or f"tc_{tool_round}")
    tool_name = str(tool_call.get("name", "unknown"))
    tool_args = tool_call.get("args", {}) or {}
    if not isinstance(tool_args, dict):
        tool_args = {"value": tool_args}
        tool_call["args"] = tool_args

    policy_session = tool_policy_session_from_state(state)
    if policy_session is not None:
        policy_decision = policy_session.decision_for(tool_name.strip())
        if not policy_decision.allowed:
            result = tool_policy_denial_message(policy_decision)
            logger_obj.warning(
                "[DIRECT] Tool policy denied tool=%r path=%s reason=%s",
                tool_name,
                policy_decision.path,
                policy_decision.reason,
            )
            public_tool_args = sanitize_tool_args_for_event(tool_args)
            await push_event(
                {
                    "type": "tool_call",
                    "content": {
                        "name": tool_name,
                        "args": public_tool_args,
                        "id": tool_call_id,
                        "policy": {
                            "allowed": False,
                            "path": policy_decision.path,
                            "reason": policy_decision.reason,
                        },
                    },
                    "node": "direct",
                }
            )
            tool_call_events.append(
                {
                    "type": "call",
                    "name": tool_name,
                    "args": public_tool_args,
                    "id": tool_call_id,
                    "policy": {
                        "allowed": False,
                        "path": policy_decision.path,
                        "reason": policy_decision.reason,
                    },
                }
            )
            await push_event(
                {
                    "type": "tool_result",
                    "content": {
                        "name": tool_name,
                        "result": summarize_tool_result_for_stream(tool_name, result),
                        "id": tool_call_id,
                    },
                    "node": "direct",
                }
            )
            return DirectToolDispatchResult(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                tool_args=tool_args,
                result=result,
                matched=False,
            )

    if is_search_tool_name(tool_name):
        tool_args = prefer_official_query_for_known_docs(tool_args, query)
        tool_call["args"] = tool_args

    public_tool_args = sanitize_tool_args_for_event(tool_args)
    await push_event(
        {
            "type": "tool_call",
            "content": {"name": tool_name, "args": public_tool_args, "id": tool_call_id},
            "node": "direct",
        }
    )
    tool_call_events.append(
        {
            "type": "call",
            "name": tool_name,
            "args": public_tool_args,
            "id": tool_call_id,
        }
    )

    matched = get_tool_by_name(tools, tool_name.strip())
    try:
        if matched:
            result = await invoke_tool_with_runtime(
                matched,
                tool_args,
                tool_name=tool_name,
                runtime_context_base=runtime_context_base,
                tool_call_id=tool_call_id,
                query_snippet=str(tool_args.get("query", ""))[:100],
                prefer_async=False,
                run_sync_in_thread=True,
            )
        else:
            logger_obj.warning(
                "[DIRECT] LLM called unknown tool name=%r - skipping",
                tool_name,
            )
            result = (
                f"Lỗi: không tìm thấy tool `{tool_name}` trong registry. "
                "Hãy gọi đúng tên tool có sẵn."
            )
    except ValidationError as tool_error:
        logger_obj.warning(
            "[DIRECT] Tool %s rejected invalid input: %s",
            tool_name,
            tool_error,
        )
        public_errors = [
            {
                "field": ".".join(str(part) for part in error.get("loc", ())),
                "type": str(error.get("type") or "validation_error"),
            }
            for error in tool_error.errors()
        ]
        missing_fields = [
            error["field"]
            for error in public_errors
            if error["type"].startswith("missing") and error["field"]
        ]
        result = json.dumps(
            {
                "status": "validation_failed",
                "tool": tool_name,
                "message": "Tool input failed schema validation.",
                "missing_fields": missing_fields,
                "errors": public_errors,
            },
            ensure_ascii=False,
        )
    except Exception as tool_error:  # noqa: BLE001
        logger_obj.warning("[DIRECT] Tool %s failed: %s", tool_name, tool_error)
        result = "Tool unavailable"

    await push_event(
        {
            "type": "tool_result",
            "content": {
                "name": tool_name,
                "result": summarize_tool_result_for_stream(tool_name, result),
                "id": tool_call_id,
            },
            "node": "direct",
        }
    )
    sources = extract_source_infos_from_tool_result(tool_name, result)
    if sources:
        await push_event(
            {
                "type": "sources",
                "content": sources,
                "node": "direct",
            }
        )
    return DirectToolDispatchResult(
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        tool_args=tool_args,
        result=result,
        matched=bool(matched),
    )
