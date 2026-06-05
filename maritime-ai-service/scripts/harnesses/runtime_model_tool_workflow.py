"""Live workflow harness for provider pinning and explicit tool routing.

This is intentionally small and task-specific. It follows the workflow pattern:
classify cases, execute live turns, verify each case against a rubric, then
synthesize a pass/fail report. The harness calls /api/v1/chat/stream/v3, so it
is opt-in and expects a local/dev service to be running.

Environment:
    WIII_HARNESS_BASE_URL       default: http://127.0.0.1:8000
    WIII_HARNESS_API_KEY        default: local-dev-key
    WIII_HARNESS_PROVIDER       default: nvidia
    WIII_HARNESS_MODEL          default: nvidia/nemotron-3-ultra-550b-a55b
    WIII_HARNESS_ORG_ID         default: default
    WIII_HARNESS_USER_ID        default: runtime-model-tool-harness
    WIII_HARNESS_AUTH_ORG_HEADER default: 0
    WIII_HARNESS_FETCH_URL      default: https://www.iana.org/about
    WIII_HARNESS_FETCH_EXPECTED default: About us

Example:
    python scripts/harnesses/runtime_model_tool_workflow.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_API_KEY = "local-dev-key"
DEFAULT_PROVIDER = "nvidia"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
DEFAULT_ORG_ID = "default"
DEFAULT_USER_ID = "runtime-model-tool-harness"

QWEN_DEFAULT_MARKERS = (
    "qwen/qwen3-next-80b-a3b-instruct",
    "qwen3-next-80b-a3b-instruct",
)
CODE_STUDIO_MARKERS = (
    "code_studio",
    "code studio",
    "tool_create_visual_code",
    "visual-code-gen",
    "visual_code",
    "code_open",
    "code_delta",
    "code_complete",
)
FETCH_TOOL_MARKERS = (
    "tool_fetch_url",
    "fetch_url",
    "web_fetch",
    "WEB_FETCH",
)
CASUAL_RAG_LEAK_MARKERS = (
    "rag",
    "colreg",
    "colregs",
    "solas",
    "marpol",
    "nguon rag",
    "nguồn rag",
    "nguon tai lieu",
    "nguồn tài liệu",
    "knowledge base",
)


@dataclass(frozen=True)
class WorkflowCase:
    case_id: str
    lane: str
    prompt: str
    verifier: str
    expected_text: str = ""
    timeout_seconds: float = 180.0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _json_default(value: Any) -> str:
    return str(value)


def _print_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default))


def _decode_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def _collect_sse_events(response: httpx.Response) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current_event = "message"
    async for line in response.aiter_lines():
        line = line.rstrip("\n")
        if not line.strip():
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip() or "message"
            continue
        if not line.startswith("data:"):
            continue
        data_str = line.split(":", 1)[1].lstrip()
        events.append(
            {
                "event": current_event,
                "data": _decode_json_object(data_str) or data_str,
            }
        )
    return events


def _extract_last_runtime_flow_ledger(
    events: Iterable[Mapping[str, Any]],
) -> dict[str, Any] | None:
    for event in reversed(list(events)):
        data = event.get("data")
        if not isinstance(data, Mapping):
            continue
        ledger = data.get("runtime_flow_ledger")
        if isinstance(ledger, dict):
            return ledger
    return None


def _event_counts(events: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    return dict(Counter(str(event.get("event") or "message") for event in events))


def _iter_text(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _iter_text(item)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_text(item)
        return
    yield str(value)


def _combined_text(events: Iterable[Mapping[str, Any]]) -> str:
    return "\n".join(_iter_text(list(events)))


def _collect_answer_text(events: Iterable[Mapping[str, Any]]) -> str:
    parts: list[str] = []
    for event in events:
        if event.get("event") != "answer":
            continue
        data = event.get("data")
        if isinstance(data, Mapping):
            value = data.get("content") or data.get("answer") or data.get("text")
            if isinstance(value, str):
                parts.append(value)
        elif isinstance(data, str):
            parts.append(data)
    return "".join(parts).strip()


def _contains_any(haystack: str, needles: Iterable[str]) -> bool:
    folded = haystack.casefold()
    return any(needle.casefold() in folded for needle in needles)


def _actual_code_studio_seen(
    events: Iterable[Mapping[str, Any]],
    route: Mapping[str, Any] | None = None,
) -> bool:
    if isinstance(route, Mapping):
        lane = str(route.get("lane") or "").strip().casefold()
        reason = str(route.get("reason") or "").strip().casefold()
        if lane == "code_studio" or reason == "code_studio":
            return True
    code_event_names = {"code_open", "code_delta", "code_complete"}
    code_tool_names = {
        "tool_create_visual_code",
        "tool_generate_visual_code",
        "visual-code-gen",
        "visual_code",
    }
    for event in events:
        event_name = str(event.get("event") or "").strip().casefold()
        if event_name in code_event_names:
            return True
        if event_name != "tool_call":
            continue
        data = event.get("data")
        content = data.get("content") if isinstance(data, Mapping) else None
        if isinstance(content, Mapping):
            tool_name = str(content.get("name") or "").strip().casefold()
            if tool_name in code_tool_names:
                return True
    return False


def _model_tail(model: str) -> str:
    return str(model or "").strip().split("/")[-1].casefold()


def _same_model(left: str, right: str) -> bool:
    left_clean = str(left or "").strip().casefold()
    right_clean = str(right or "").strip().casefold()
    if not left_clean or not right_clean:
        return False
    return left_clean == right_clean or _model_tail(left_clean) == _model_tail(right_clean)


def _runtime_sections(ledger: Mapping[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not isinstance(ledger, Mapping):
        return {}, {}, {}
    runtime = ledger.get("runtime")
    route = ledger.get("route")
    request = ledger.get("request")
    return (
        runtime if isinstance(runtime, dict) else {},
        route if isinstance(route, dict) else {},
        request if isinstance(request, dict) else {},
    )


def _short(value: str, limit: int = 260) -> str:
    clean = " ".join(str(value or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "..."


def _verify_model_pin(
    *,
    events: list[dict[str, Any]],
    expected_provider: str,
    expected_model: str,
) -> tuple[bool, list[str], dict[str, Any]]:
    ledger = _extract_last_runtime_flow_ledger(events)
    runtime, route, request = _runtime_sections(ledger)
    combined = _combined_text(events)
    answer_text = _collect_answer_text(events)
    runtime_provider = str(runtime.get("provider") or "")
    runtime_model = str(runtime.get("model") or "")
    failover_used = bool(runtime.get("failover_used"))

    errors: list[str] = []
    if runtime_provider.casefold() != expected_provider.casefold():
        errors.append(f"runtime_provider={runtime_provider or '<missing>'}")
    if not _same_model(runtime_model, expected_model):
        errors.append(f"runtime_model={runtime_model or '<missing>'}")
    if failover_used:
        errors.append("failover_used=true")
    if runtime_model and _contains_any(runtime_model, QWEN_DEFAULT_MARKERS):
        errors.append("runtime_model_is_qwen_default")

    evidence = {
        "runtime_provider": runtime_provider or None,
        "runtime_model": runtime_model or None,
        "requested_provider": request.get("provider"),
        "requested_model": request.get("model"),
        "route_lane": route.get("lane"),
        "route_reason": route.get("reason"),
        "failover_used": failover_used,
        "answer_snippet": _short(answer_text),
        "qwen_default_marker_seen_anywhere": _contains_any(
            combined,
            QWEN_DEFAULT_MARKERS,
        ),
    }
    return not errors, errors, evidence


def _verify_explicit_fetch(
    *,
    events: list[dict[str, Any]],
    expected_provider: str,
    expected_model: str,
    expected_text: str,
) -> tuple[bool, list[str], dict[str, Any]]:
    model_pass, model_errors, model_evidence = _verify_model_pin(
        events=events,
        expected_provider=expected_provider,
        expected_model=expected_model,
    )
    ledger = _extract_last_runtime_flow_ledger(events)
    _, route, _ = _runtime_sections(ledger)
    combined = _combined_text(events)
    answer_text = _collect_answer_text(events)
    code_studio_seen = _actual_code_studio_seen(events, route)

    errors: list[str] = []
    if not model_pass:
        errors.extend(model_errors)
    if not _contains_any(combined, FETCH_TOOL_MARKERS):
        errors.append("fetch_tool_marker_missing")
    expected_text = str(expected_text or "About us").strip()
    expected_seen = expected_text.casefold() in combined.casefold()
    if not expected_seen:
        errors.append("expected_fetch_text_missing")
    expected_answer_seen = expected_text.casefold() in answer_text.casefold()
    if not expected_answer_seen:
        errors.append("expected_fetch_text_missing_in_answer")
    if code_studio_seen:
        errors.append("code_studio_marker_seen")

    evidence = {
        **model_evidence,
        "route_lane": route.get("lane"),
        "route_reason": route.get("reason"),
        "fetch_tool_marker_seen": _contains_any(combined, FETCH_TOOL_MARKERS),
        "expected_text": expected_text,
        "expected_text_seen": expected_seen,
        "expected_text_seen_in_answer": expected_answer_seen,
        "code_studio_marker_seen": code_studio_seen,
        "answer_snippet": _short(answer_text),
    }
    return not errors, errors, evidence


def _verify_casual_chat(
    *,
    events: list[dict[str, Any]],
    expected_provider: str,
    expected_model: str,
) -> tuple[bool, list[str], dict[str, Any]]:
    model_pass, model_errors, model_evidence = _verify_model_pin(
        events=events,
        expected_provider=expected_provider,
        expected_model=expected_model,
    )
    ledger = _extract_last_runtime_flow_ledger(events)
    _, route, _ = _runtime_sections(ledger)
    answer_text = _collect_answer_text(events)
    source_event_count = sum(1 for event in events if event.get("event") == "sources")
    tool_call_count = sum(1 for event in events if event.get("event") == "tool_call")
    answer_has_rag_leak = _contains_any(answer_text, CASUAL_RAG_LEAK_MARKERS)
    code_studio_seen = _actual_code_studio_seen(events, route)

    errors: list[str] = []
    if not model_pass:
        errors.extend(model_errors)
    if not answer_text:
        errors.append("answer_missing")
    if source_event_count:
        errors.append("sources_emitted_for_casual_chat")
    if tool_call_count:
        errors.append("tool_call_emitted_for_casual_chat")
    if answer_has_rag_leak:
        errors.append("rag_or_domain_source_leak_in_casual_answer")
    if code_studio_seen:
        errors.append("code_studio_marker_seen")

    evidence = {
        **model_evidence,
        "route_lane": route.get("lane"),
        "route_reason": route.get("reason"),
        "source_event_count": source_event_count,
        "tool_call_count": tool_call_count,
        "answer_has_rag_leak": answer_has_rag_leak,
        "code_studio_marker_seen": code_studio_seen,
        "answer_snippet": _short(answer_text),
    }
    return not errors, errors, evidence


def _cases() -> list[WorkflowCase]:
    fetch_url = os.getenv("WIII_HARNESS_FETCH_URL", "https://www.iana.org/about").strip()
    fetch_expected = os.getenv("WIII_HARNESS_FETCH_EXPECTED", "About us").strip() or "About us"
    return [
        WorkflowCase(
            case_id="model_pin_short_chat",
            lane="provider-routing",
            prompt=(
                "Tra loi mot cau ngan bang tieng Viet: "
                "harness-nemotron-pin-ok."
            ),
            verifier="runtime_provider_model_must_match_request_without_rag_leak",
            timeout_seconds=150.0,
        ),
        WorkflowCase(
            case_id="casual_chat_no_rag_leak",
            lane="natural-chat-routing",
            prompt="Xin chao Wiii, dap lai that ngan bang tieng Viet.",
            verifier="casual_chat_must_not_emit_rag_sources_or_tools",
            timeout_seconds=150.0,
        ),
        WorkflowCase(
            case_id="explicit_web_fetch_h1",
            lane="tool-routing",
            prompt=(
                f"Dung web_fetch doc H1 cua {fetch_url} "
                "roi tra loi mot dong ngan gon."
            ),
            verifier="fetch_url_tool_must_run_and_not_enter_code_studio",
            expected_text=fetch_expected,
            timeout_seconds=150.0,
        ),
    ]


async def _run_case(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: str,
    user_id: str,
    organization_id: str,
    send_auth_org_header: bool,
    provider: str,
    model: str,
    role: str,
    domain_id: str,
    case: WorkflowCase,
) -> dict[str, Any]:
    request_id = f"req-harness-{case.case_id}-{uuid.uuid4().hex[:8]}"
    session_id = f"harness-{case.case_id}-{uuid.uuid4().hex[:8]}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-API-Key": api_key,
        "X-User-ID": user_id,
        "X-Role": role,
        "X-Request-ID": request_id,
    }
    if send_auth_org_header:
        headers["X-Organization-ID"] = organization_id
    payload = {
        "user_id": user_id,
        "message": case.prompt,
        "role": role,
        "domain_id": domain_id,
        "organization_id": organization_id,
        "session_id": session_id,
        "thread_id": session_id,
        "provider": provider,
        "model": model,
        "thinking_effort": "low",
    }

    started = time.monotonic()
    async with asyncio.timeout(case.timeout_seconds):
        async with client.stream(
            "POST",
            f"{base_url.rstrip('/')}/api/v1/chat/stream/v3",
            headers=headers,
            json=payload,
            timeout=httpx.Timeout(
                timeout=case.timeout_seconds,
                read=case.timeout_seconds,
            ),
        ) as response:
            status_code = response.status_code
            response.raise_for_status()
            events = await _collect_sse_events(response)
    duration_ms = int((time.monotonic() - started) * 1000)

    if case.case_id == "explicit_web_fetch_h1":
        passed, errors, evidence = _verify_explicit_fetch(
            events=events,
            expected_provider=provider,
            expected_model=model,
            expected_text=case.expected_text,
        )
    elif case.case_id in {"casual_chat_no_rag_leak", "model_pin_short_chat"}:
        passed, errors, evidence = _verify_casual_chat(
            events=events,
            expected_provider=provider,
            expected_model=model,
        )
    else:
        passed, errors, evidence = _verify_model_pin(
            events=events,
            expected_provider=provider,
            expected_model=model,
        )

    return {
        "case_id": case.case_id,
        "lane": case.lane,
        "status": "pass" if passed else "fail",
        "verifier": case.verifier,
        "duration_ms": duration_ms,
        "status_code": status_code,
        "event_counts": _event_counts(events),
        "terminal_event": events[-1].get("event") if events else None,
        "errors": errors,
        "evidence": evidence,
        "request": {
            "request_id": request_id,
            "session_id": session_id,
            "provider": provider,
            "model": model,
            "prompt_char_count": len(case.prompt),
        },
    }


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    selected_cases = [case for case in _cases() if not args.case or case.case_id in args.case]
    if not selected_cases:
        raise SystemExit("No cases selected")

    results: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        for case in selected_cases:
            try:
                results.append(
                    await _run_case(
                        client=client,
                        base_url=args.base_url,
                        api_key=args.api_key,
                        user_id=args.user_id,
                        organization_id=args.organization_id,
                        send_auth_org_header=args.send_auth_org_header,
                        provider=args.provider,
                        model=args.model,
                        role=args.role,
                        domain_id=args.domain_id,
                        case=case,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - harness should report all failures.
                results.append(
                    {
                        "case_id": case.case_id,
                        "lane": case.lane,
                        "status": "fail",
                        "verifier": case.verifier,
                        "errors": [f"{type(exc).__name__}: {_short(str(exc), 400)}"],
                        "evidence": {},
                        "request": {
                            "provider": args.provider,
                            "model": args.model,
                            "prompt_char_count": len(case.prompt),
                        },
                    }
                )

    passed = all(item.get("status") == "pass" for item in results)
    return {
        "schema_version": "wiii.runtime_model_tool_workflow.v1",
        "generated_at": _utc_now(),
        "status": "pass" if passed else "fail",
        "workflow": {
            "pattern": [
                "classify-and-act",
                "loop-until-selected-cases-complete",
                "adversarial-verifier-rubric",
                "synthesize-report",
            ],
            "case_count": len(results),
            "live_endpoint": "/api/v1/chat/stream/v3",
        },
        "target": {
            "base_url": args.base_url,
            "provider": args.provider,
            "model": args.model,
            "organization_id": args.organization_id,
        },
        "results": results,
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("WIII_HARNESS_BASE_URL", DEFAULT_BASE_URL),
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("WIII_HARNESS_API_KEY", DEFAULT_API_KEY),
        help="Local/dev API key. Do not pass production secrets into reports.",
    )
    parser.add_argument(
        "--provider",
        default=os.getenv("WIII_HARNESS_PROVIDER", DEFAULT_PROVIDER),
    )
    parser.add_argument(
        "--model",
        default=os.getenv("WIII_HARNESS_MODEL", DEFAULT_MODEL),
    )
    parser.add_argument(
        "--organization-id",
        default=os.getenv("WIII_HARNESS_ORG_ID", DEFAULT_ORG_ID),
    )
    parser.add_argument(
        "--send-auth-org-header",
        action="store_true",
        default=os.getenv("WIII_HARNESS_AUTH_ORG_HEADER", "0").strip().lower()
        in {"1", "true", "yes", "on"},
        help=(
            "Also send X-Organization-ID. Keep off for local API-key harness "
            "unless the selected user is a member of the org."
        ),
    )
    parser.add_argument(
        "--user-id",
        default=os.getenv("WIII_HARNESS_USER_ID", DEFAULT_USER_ID),
    )
    parser.add_argument("--role", default=os.getenv("WIII_HARNESS_ROLE", "student"))
    parser.add_argument("--domain-id", default=os.getenv("WIII_HARNESS_DOMAIN_ID", "maritime"))
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.getenv("WIII_HARNESS_HTTP_TIMEOUT", "240")),
    )
    parser.add_argument(
        "--case",
        action="append",
        choices=[case.case_id for case in _cases()],
        help="Run one case. Repeat to run multiple selected cases.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    report = asyncio.run(_run(args))
    _print_json(report)
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
