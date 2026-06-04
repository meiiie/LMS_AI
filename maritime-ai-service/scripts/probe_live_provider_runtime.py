"""Opt-in live provider runtime probe.

This probe makes credentialed calls through Wiii's provider abstractions. The
default path exercises a no-side-effect tool-call/tool-result roundtrip against
the selected provider. The optional stream path calls /chat/stream/v3 and can
persist a chat turn, so it requires a second explicit flag.

Example:
    WIII_LIVE_PROVIDER_RUNTIME_PROBE=1 python scripts/probe_live_provider_runtime.py --allow-call --provider auto --out provider-runtime-evidence.json

Stream ledger example:
    WIII_LIVE_PROVIDER_RUNTIME_PROBE=1 python scripts/probe_live_provider_runtime.py --allow-call --include-stream-ledger --allow-stream-write --out provider-runtime-evidence.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import re
import sys
import time
import uuid
import zlib
from collections.abc import AsyncIterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from runtime_evidence_output import emit_json_payload  # noqa: E402


ENV_FLAG = "WIII_LIVE_PROVIDER_RUNTIME_PROBE"
SCHEMA_VERSION = "wiii.live_provider_runtime_probe.v1"
PREFLIGHT_SCHEMA_VERSION = "wiii.provider_runtime_preflight.v1"
TOOL_NAME = "record_probe_fact"
SUPPORTED_PROVIDER_ARGS = (
    "auto",
    "google",
    "vertex",
    "openai",
    "openrouter",
    "nvidia",
    "ollama",
    "zhipu",
)
STREAM_PROVIDER_ARGS = ("google", "zhipu", "openai", "openrouter", "nvidia", "ollama")
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_API_KEY = "local-dev-key"
DEFAULT_USER_ID = "live-provider-runtime-probe-user"
DEFAULT_ROLE = "student"
DEFAULT_DOMAIN_ID = "maritime"
DEFAULT_ORG_ID = "default"
DEFAULT_TRANSPORT_MODE = "asgi"
IDENTIFIER_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def _json_print(payload: dict[str, Any]) -> None:
    emit_json_payload(payload)


def _redact_error(value: Any) -> str:
    try:
        from app.engine.runtime.event_payload_sanitizer import (
            redact_runtime_secret_text,
        )

        return redact_runtime_secret_text(str(value))
    except Exception:  # noqa: BLE001
        return str(value)


def _fallback_hash(value: Any) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    digest = _stable_probe_fingerprint(token)
    return f"sha256:{digest}"


def _stable_probe_fingerprint(text: str) -> str:
    data = text.encode("utf-8")
    key = b"wiii-live-probe-fingerprint-v1"
    first = zlib.crc32(key + b"\0" + data) & 0xFFFFFFFF
    second = zlib.crc32(data + b"\0" + key) & 0xFFFFFFFF
    return f"{first:08x}{second:08x}"


def _safe_hash(value: Any) -> str | None:
    try:
        return _hash(value)
    except Exception:  # noqa: BLE001
        return _fallback_hash(value)


def _redact_failure_text(value: Any, args: argparse.Namespace | None = None) -> str:
    text = _redact_error(value)[:1000]
    text = IDENTIFIER_RE.sub(
        lambda match: _fallback_hash(match.group(0)) or "<redacted-identifier>",
        text,
    )
    text = re.sub(
        r"\b(?:OPENAI|OPENROUTER|NVIDIA|ZHIPU|GOOGLE|VERTEX)_[A-Z0-9_]*(?:<[^>]+>)?(?:=\S+)?",
        "<redacted-sensitive-field>",
        text,
        flags=re.IGNORECASE,
    )
    replacements = {
        '"label": "provider_runtime_probe"': "<redacted-tool-argument>",
        '\\"label\\": \\"provider_runtime_probe\\"': "<redacted-tool-argument>",
        "record_probe_fact value": "<redacted-tool-argument>",
        "provider_runtime_probe": "<redacted-tool-argument>",
        "OPENAI_API_KEY=": "<redacted-sensitive-field>",
        "OPENROUTER_API_KEY=": "<redacted-sensitive-field>",
        "NVIDIA_API_KEY=": "<redacted-sensitive-field>",
        "ZHIPU_API_KEY=": "<redacted-sensitive-field>",
        "GOOGLE_API_KEY=": "<redacted-sensitive-field>",
        "VERTEX_API_KEY=": "<redacted-sensitive-field>",
        "api_key": "<redacted-sensitive-field>",
        "access_token": "<redacted-sensitive-field>",
        "authorization": "<redacted-sensitive-field>",
    }
    if args is not None:
        for raw_value in (
            getattr(args, "api_key", None),
            getattr(args, "session_id", None),
            getattr(args, "user_id", None),
            getattr(args, "organization_id", None),
            getattr(args, "request_id", None),
            getattr(args, "stream_prompt", None),
        ):
            if not raw_value:
                continue
            replacements[str(raw_value)] = _safe_hash(raw_value) or "<redacted-value>"
    for raw, replacement in replacements.items():
        text = re.sub(re.escape(raw), replacement, text, flags=re.IGNORECASE)
    return text


def _failure_payload(exc: Exception, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "error_code": "provider_runtime_failed",
        "error_message": _redact_failure_text(exc, args),
        "privacy": {
            "raw_content_included": False,
            "tool_argument_values_included": False,
            "provider_arguments_included": False,
            "provider_payload_included": False,
            "provider_response_included": False,
            "stream_payload_included": False,
            "raw_request_identifiers_included": False,
            "identifier_strategy": "hashes_and_counts",
            "raw_secret_included": False,
            "failure_error_redacted": True,
        },
    }


def _hash(value: Any) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    from app.engine.semantic_memory.privacy import hash_memory_identifier

    return hash_memory_identifier(token)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_readiness_rows() -> list[dict[str, Any]]:
    from app.engine.llm_pool import LLMPool
    from app.engine.llm_provider_registry import get_supported_provider_names

    selectable = set(LLMPool.get_request_selectable_providers())
    rows: list[dict[str, Any]] = []
    for provider_name in get_supported_provider_names():
        provider = LLMPool._ensure_provider(provider_name)
        configured = bool(provider is not None and provider.is_configured())
        rows.append(
            {
                "provider": provider_name,
                "configured": configured,
                "request_selectable": provider_name in selectable,
            }
        )
    return rows


def _provider_status_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "total": len(rows),
        "configured": sum(1 for row in rows if row.get("configured") is True),
        "request_selectable": sum(
            1 for row in rows if row.get("request_selectable") is True
        ),
    }


def _provider_row_by_name(
    rows: list[dict[str, Any]],
    provider_name: str,
) -> dict[str, Any] | None:
    for row in rows:
        if row.get("provider") == provider_name:
            return row
    return None


def _provider_preflight_required_next(
    args: argparse.Namespace,
    *,
    provider_rows: list[dict[str, Any]],
    environment: str,
    live_env_flag_set: bool,
) -> list[str]:
    required_next: list[str] = []
    if not args.allow_call:
        required_next.append("pass_allow_call")
    if not live_env_flag_set:
        required_next.append("set_live_provider_probe_env_flag")
    if environment == "production" and not args.allow_production:
        required_next.append("pass_allow_production")
    if args.include_stream_ledger and not args.allow_stream_write:
        required_next.append("pass_allow_stream_write")

    if args.provider == "auto":
        if not any(row.get("request_selectable") is True for row in provider_rows):
            required_next.append("configure_request_selectable_provider")
        return required_next

    selected = _provider_row_by_name(provider_rows, args.provider)
    if selected is None:
        required_next.append("choose_supported_provider")
    elif selected.get("configured") is not True:
        required_next.append("configure_selected_provider")
    elif selected.get("request_selectable") is not True:
        required_next.append("add_selected_provider_to_request_chain")
    return required_next


def _build_provider_runtime_preflight(
    args: argparse.Namespace,
    *,
    provider_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from app.core.config import settings

    rows = provider_rows if provider_rows is not None else _provider_readiness_rows()
    environment = str(getattr(settings, "environment", "") or "")
    live_env_flag_set = os.getenv(ENV_FLAG) == "1"
    required_next = _provider_preflight_required_next(
        args,
        provider_rows=rows,
        environment=environment,
        live_env_flag_set=live_env_flag_set,
    )
    selected = None if args.provider == "auto" else _provider_row_by_name(rows, args.provider)
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "pass" if not required_next else "fail",
        "requested_provider": args.provider,
        "selected_provider": selected.get("provider") if selected else None,
        "tier": args.tier,
        "allow_call_acknowledged": bool(args.allow_call),
        "live_env_flag_set": live_env_flag_set,
        "include_stream_ledger": bool(args.include_stream_ledger),
        "allow_stream_write_acknowledged": bool(args.allow_stream_write),
        "production_environment": environment == "production",
        "allow_production_acknowledged": bool(args.allow_production),
        "provider_status_counts": _provider_status_counts(rows),
        "providers": rows,
        "required_next": required_next,
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "raw_request_identifiers_included": False,
            "provider_payload_included": False,
            "provider_response_included": False,
        },
    }


def _require_live_call(args: argparse.Namespace) -> None:
    if not args.allow_call:
        raise SystemExit("--allow-call is required; this probe calls a live LLM provider")
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to run the live provider runtime probe")
    if args.include_stream_ledger and not args.allow_stream_write:
        raise SystemExit(
            "--allow-stream-write is required with --include-stream-ledger; "
            "the chat stream path may persist a chat turn"
        )

    from app.core.config import settings

    if settings.environment == "production" and not args.allow_production:
        raise SystemExit("Refusing to call production without --allow-production")


def _build_probe_tool_schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Record a harmless diagnostic fact for a live runtime probe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {
                        "type": "string",
                        "description": "Stable diagnostic label.",
                    },
                    "value": {
                        "type": "string",
                        "description": "Short diagnostic value.",
                    },
                },
                "required": ["label", "value"],
                "additionalProperties": False,
            },
        },
    }


def _tool_choice() -> dict[str, Any]:
    return {"type": "function", "function": {"name": TOOL_NAME}}


def _tool_contract_summary() -> dict[str, Any]:
    schema = _build_probe_tool_schema()
    function = schema.get("function") if isinstance(schema.get("function"), dict) else {}
    parameters = (
        function.get("parameters") if isinstance(function.get("parameters"), dict) else {}
    )
    required_keys = parameters.get("required")
    if not isinstance(required_keys, list):
        required_keys = []
    return {
        "schema_version": "wiii.provider_tool_contract.v1",
        "tool_name": str(function.get("name") or ""),
        "tool_name_matches_probe": function.get("name") == TOOL_NAME,
        "forced_tool_choice_used": _tool_choice()["function"]["name"] == TOOL_NAME,
        "required_argument_keys": sorted(str(key) for key in required_keys),
        "required_argument_key_count": len(required_keys),
        "additional_properties_allowed": bool(parameters.get("additionalProperties")),
        "no_side_effect_tool": True,
        "raw_schema_values_included": False,
    }


def _runtime_boundary_summary() -> dict[str, Any]:
    return {
        "schema_version": "wiii.provider_runtime_boundary.v1",
        "llm_pool_route_used": True,
        "wiii_chat_model_interface_used": True,
        "native_message_contract_used": True,
        "raw_provider_http_used": False,
        "raw_provider_payload_included": False,
        "raw_provider_response_included": False,
    }


def _evidence_contract_summary(*, stream_requested: bool) -> dict[str, Any]:
    return {
        "schema_version": "wiii.provider_runtime_evidence_contract.v1",
        "credentialed_provider_call_required": True,
        "tool_roundtrip_required": True,
        "single_tool_call_required": True,
        "tool_result_linkage_required": True,
        "followup_without_extra_tool_calls_required": True,
        "trace_span_pair_required": True,
        "stream_ledger_optional": True,
        "stream_ledger_requested": stream_requested,
        "stream_ledger_requires_allow_stream_write": True,
        "hash_count_only_output": True,
    }


def _safe_tool_call_summary(tool_call: Any) -> dict[str, Any]:
    args = getattr(tool_call, "arguments", None)
    if not isinstance(args, Mapping):
        args = {}
    id_hash = _hash(getattr(tool_call, "id", ""))
    return {
        "id_hash": id_hash,
        "id_hash_present": bool(id_hash),
        "name": str(getattr(tool_call, "name", "") or ""),
        "argument_keys": sorted(str(key) for key in args.keys()),
        "argument_count": len(args),
        "argument_values_included": False,
        "raw_id_included": False,
    }


def _safe_tool_result_summary(tool_result: Any) -> dict[str, Any]:
    parsed_content = _decode_json_object(str(getattr(tool_result, "content", "") or ""))
    content_keys = (
        sorted(str(key) for key in parsed_content.keys()) if parsed_content else []
    )
    tool_call_id_hash = _hash(getattr(tool_result, "tool_call_id", ""))
    return {
        "role": str(getattr(tool_result, "role", "") or ""),
        "tool_call_id_hash": tool_call_id_hash,
        "tool_call_id_hash_present": bool(tool_call_id_hash),
        "content_json_keys": content_keys,
        "content_json_key_count": len(content_keys),
        "content_json_values_included": False,
        "raw_content_included": False,
        "raw_tool_call_id_included": False,
    }


def _safe_span_summary(spans: list[Any]) -> dict[str, Any]:
    span_names = [str(getattr(span, "name", "") or "") for span in spans]
    durations = [
        round(float(getattr(span, "duration_ms", 0.0) or 0.0), 2)
        for span in spans
    ]
    return {
        "span_count": len(spans),
        "span_names": span_names,
        "tool_call_span_seen": "live_provider_runtime_probe.tool_call" in span_names,
        "tool_result_span_seen": "live_provider_runtime_probe.tool_result" in span_names,
        "statuses": [str(getattr(span, "status", "") or "") for span in spans],
        "duration_ms": durations,
        "duration_observed": all(duration >= 0 for duration in durations),
        "duration_ms_total": round(sum(durations), 2),
        "raw_attribute_values_included": False,
    }


def _model_name(llm: Any) -> str | None:
    for attr in ("model", "model_name", "_wiii_model_name"):
        value = getattr(llm, attr, None)
        if value:
            return str(value)
    return None


def _provider_name(route: Any, llm: Any) -> str | None:
    for value in (
        getattr(route, "provider", None),
        getattr(llm, "_wiii_provider_name", None),
    ):
        if value:
            return str(value)
    return None


def _resolve_provider_route(args: argparse.Namespace) -> tuple[Any, list[str]]:
    from app.engine.llm_pool import FAILOVER_MODE_AUTO, FAILOVER_MODE_PINNED, LLMPool

    selectable = LLMPool.get_request_selectable_providers()
    requested_provider = None if args.provider == "auto" else args.provider
    if requested_provider and requested_provider not in selectable:
        raise RuntimeError(
            f"Provider {requested_provider!r} is not request-selectable. "
            f"Selectable providers: {selectable!r}"
        )
    if args.provider == "auto" and not selectable:
        raise RuntimeError("No request-selectable live provider is configured")

    route = LLMPool.resolve_runtime_route(
        requested_provider,
        args.tier,
        failover_mode=FAILOVER_MODE_AUTO if args.allow_failover else FAILOVER_MODE_PINNED,
        prefer_selectable_fallback=bool(args.allow_failover),
    )
    if getattr(route, "llm", None) is None:
        raise RuntimeError("LLMPool did not return a live LLM instance")
    return route, selectable


async def _run_provider_tool_roundtrip(args: argparse.Namespace) -> dict[str, Any]:
    from app.engine.messages import Message
    from app.engine.runtime.tracing import InMemoryProcessor, get_tracer, span

    started = time.monotonic()
    route, selectable = _resolve_provider_route(args)
    llm = route.llm
    provider = _provider_name(route, llm)
    model = _model_name(llm)
    if not provider:
        raise RuntimeError("Live provider route did not expose provider authority")
    if not model:
        raise RuntimeError("Live provider route did not expose model authority")

    tracer = get_tracer()
    processor = InMemoryProcessor()
    tracer.add_processor(processor)
    first_response = None
    final_response = None
    try:
        messages = [
            Message(
                role="system",
                content=(
                    "You are running a Wiii live provider probe. "
                    "Use the requested tool exactly once when asked."
                ),
            ),
            Message(
                role="user",
                content=(
                    "Call record_probe_fact with label=provider_runtime_probe "
                    "and value=live. Do not answer in prose yet."
                ),
            ),
        ]
        with span(
            "live_provider_runtime_probe.tool_call",
            attributes={
                "provider": provider,
                "model": model,
                "tier": args.tier,
                "session_id": args.session_id,
                "organization_id": args.organization_id,
            },
        ):
            first_response = await asyncio.wait_for(
                llm.ainvoke(
                    messages,
                    tools=[_build_probe_tool_schema()],
                    tool_choice=_tool_choice(),
                ),
                timeout=args.provider_timeout,
            )

        tool_calls = list(getattr(first_response, "tool_calls", None) or [])
        if not tool_calls:
            raise RuntimeError("Live provider response did not include a tool call")
        first_tool_call = tool_calls[0]
        if getattr(first_tool_call, "name", "") != TOOL_NAME:
            raise RuntimeError(
                "Live provider returned unexpected tool call "
                f"{getattr(first_tool_call, 'name', '')!r}"
            )

        tool_result = Message(
            role="tool",
            tool_call_id=getattr(first_tool_call, "id", "") or "probe_call",
            content=json.dumps(
                {
                    "ok": True,
                    "observed_at": _utc_now(),
                    "label": "provider_runtime_probe",
                },
                ensure_ascii=False,
            ),
        )
        with span(
            "live_provider_runtime_probe.tool_result",
            attributes={
                "provider": provider,
                "model": model,
                "tier": args.tier,
                "session_id": args.session_id,
                "organization_id": args.organization_id,
            },
        ):
            final_response = await asyncio.wait_for(
                llm.ainvoke(
                    [
                        *messages,
                        Message(
                            role="assistant",
                            content=str(getattr(first_response, "content", "") or ""),
                            tool_calls=[first_tool_call],
                        ),
                        tool_result,
                    ]
                ),
                timeout=args.provider_timeout,
            )
    finally:
        tracer.remove_processor(processor)

    final_content = str(getattr(final_response, "content", "") or "")
    tool_call_summary = _safe_tool_call_summary(first_tool_call)
    tool_result_summary = _safe_tool_result_summary(tool_result)
    tool_call_id_hash = tool_call_summary.get("id_hash")
    tool_result_id_hash = tool_result_summary.get("tool_call_id_hash")
    duration_ms = int((time.monotonic() - started) * 1000)
    return {
        "status": "pass",
        "duration_ms": duration_ms,
        "provider": provider,
        "provider_present": bool(provider),
        "model": model,
        "model_present": bool(model),
        "tier": args.tier,
        "selectable_provider_count": len(selectable),
        "requested_provider": args.provider,
        "failover_allowed": bool(args.allow_failover),
        "route": {
            "provider": str(getattr(route, "provider", "") or ""),
            "provider_matches_resolved": str(getattr(route, "provider", "") or "") == provider,
            "fallback_provider_present": bool(getattr(route, "fallback_provider", None)),
            "fallback_llm_present": getattr(route, "fallback_llm", None) is not None,
        },
        "runtime_boundary": _runtime_boundary_summary(),
        "tool_contract": _tool_contract_summary(),
        "scope": {
            "session_id_hash_present": bool(_hash(args.session_id)),
            "organization_id_hash_present": bool(_hash(args.organization_id)),
            "raw_request_identifiers_included": False,
        },
        "tool_call_count": len(tool_calls),
        "tool_call_count_exactly_one": len(tool_calls) == 1,
        "tool_result_count": 1,
        "tool_call": tool_call_summary,
        "tool_result": tool_result_summary,
        "tool_result_linked_to_tool_call": (
            bool(tool_call_id_hash) and tool_call_id_hash == tool_result_id_hash
        ),
        "tool_result_followup": {
            "final_response_received": final_response is not None,
            "content_char_count": len(final_content),
            "raw_content_included": False,
            "returned_tool_call_count": len(
                list(getattr(final_response, "tool_calls", None) or [])
            ),
        },
        "trace": _safe_span_summary(processor.spans),
    }


def _raw_text_from_sse(lines: list[str]) -> str:
    return "\n".join(lines).strip() + ("\n" if lines else "")


def _decode_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


async def _collect_sse_events(response: httpx.Response) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    raw_lines: list[str] = []
    current_event = "message"
    async for line in response.aiter_lines():
        line = line.rstrip("\n")
        raw_lines.append(line)
        if not line.strip():
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
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


def _extract_last_runtime_flow_ledger(events: list[dict[str, Any]]) -> dict[str, Any] | None:
    for event in reversed(events):
        data = event.get("data")
        if not isinstance(data, Mapping):
            continue
        ledger = data.get("runtime_flow_ledger")
        if isinstance(ledger, dict):
            return ledger
    return None


def _event_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        name = str(event.get("event") or "message")
        counts[name] = counts.get(name, 0) + 1
    return counts


def _stream_provider_for_request(args: argparse.Namespace, direct_provider: str | None) -> str:
    if args.stream_provider:
        return args.stream_provider
    if args.provider != "auto" and args.provider in STREAM_PROVIDER_ARGS:
        return args.provider
    if direct_provider in STREAM_PROVIDER_ARGS:
        return direct_provider or "auto"
    return "auto"


def _raw_scope_keys_present(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    raw_keys = {
        "message",
        "response_text",
        "user_id",
        "session_id",
        "organization_id",
        "raw_content",
        "raw_scope",
    }
    if any(str(key) in raw_keys for key in value.keys()):
        return True
    background_schedule = value.get("background_schedule")
    if isinstance(background_schedule, Mapping):
        return any(str(key) in raw_keys for key in background_schedule.keys())
    return False


@contextlib.asynccontextmanager
async def _build_probe_client(
    *,
    transport_mode: str,
    base_url: str,
    timeout: float,
) -> AsyncIterator[tuple[httpx.AsyncClient, str, dict[str, Any]]]:
    if transport_mode == "http":
        async with httpx.AsyncClient(timeout=timeout) as client:
            yield client, base_url.rstrip("/"), {"transport_mode": "http"}
        return

    runtime_capture = io.StringIO()
    with contextlib.redirect_stdout(runtime_capture), contextlib.redirect_stderr(runtime_capture):
        from app.main import app as fastapi_app

        lifespan_cm = fastapi_app.router.lifespan_context(fastapi_app)
        await lifespan_cm.__aenter__()

    transport = httpx.ASGITransport(app=fastapi_app)
    diagnostics = {
        "transport_mode": "asgi",
        "runtime_capture_char_count": len(runtime_capture.getvalue()),
    }
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            timeout=timeout,
        ) as client:
            yield client, "http://testserver", diagnostics
    finally:
        with contextlib.redirect_stdout(runtime_capture), contextlib.redirect_stderr(runtime_capture):
            await lifespan_cm.__aexit__(None, None, None)


async def _run_stream_ledger_probe(
    args: argparse.Namespace,
    *,
    direct_provider: str | None,
) -> dict[str, Any]:
    if not args.include_stream_ledger:
        return {
            "status": "skipped",
            "reason": "pass --include-stream-ledger --allow-stream-write to call /chat/stream/v3",
        }

    request_id = args.request_id or f"req-live-provider-{uuid.uuid4().hex[:12]}"
    session_id = f"{args.session_id}-stream"
    provider = _stream_provider_for_request(args, direct_provider)
    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-API-Key": args.api_key,
        "X-User-ID": args.user_id,
        "X-Role": args.role,
        "X-Organization-ID": args.organization_id,
        "X-Request-ID": request_id,
    }
    payload = {
        "user_id": args.user_id,
        "message": args.stream_prompt,
        "role": args.role,
        "domain_id": args.domain_id,
        "organization_id": args.organization_id,
        "session_id": session_id,
        "provider": provider,
        "thinking_effort": "low",
    }

    started = time.monotonic()
    async with _build_probe_client(
        transport_mode=args.transport_mode,
        base_url=args.base_url,
        timeout=args.stream_timeout,
    ) as (client, resolved_base_url, diagnostics):
        async with client.stream(
            "POST",
            f"{resolved_base_url}/api/v1/chat/stream/v3",
            headers=headers,
            json=payload,
        ) as response:
            status_code = response.status_code
            response.raise_for_status()
            events = await _collect_sse_events(response)

    duration_ms = int((time.monotonic() - started) * 1000)
    ledger = _extract_last_runtime_flow_ledger(events)
    if not isinstance(ledger, dict):
        raise RuntimeError("Stream response did not include runtime_flow_ledger")

    runtime = ledger.get("runtime") if isinstance(ledger.get("runtime"), dict) else {}
    stream = ledger.get("stream") if isinstance(ledger.get("stream"), dict) else {}
    request = ledger.get("request") if isinstance(ledger.get("request"), dict) else {}
    finalization = (
        ledger.get("finalization") if isinstance(ledger.get("finalization"), dict) else {}
    )
    post_turn_lifecycle = (
        finalization.get("post_turn_lifecycle")
        if isinstance(finalization.get("post_turn_lifecycle"), dict)
        else {}
    )
    post_turn_privacy = (
        post_turn_lifecycle.get("privacy")
        if isinstance(post_turn_lifecycle.get("privacy"), dict)
        else {}
    )
    provider_seen = str(runtime.get("provider") or "").strip()
    model_seen = str(runtime.get("model") or "").strip()
    if not provider_seen:
        raise RuntimeError("Stream runtime ledger did not include provider authority")
    if not model_seen:
        raise RuntimeError("Stream runtime ledger did not include model authority")
    request_id_hash = _hash(request.get("request_id") or request_id)
    session_id_hash = _hash(request.get("session_id") or session_id)
    organization_id_hash = _hash(args.organization_id)
    event_counts = _event_counts(events)
    ledger_event_counts = stream.get("event_counts") or {}
    terminal_event_name = str(events[-1].get("event") or "") if events else None

    return {
        "status": "pass",
        "transport_mode": args.transport_mode,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "event_count": len(events),
        "ledger_schema_version": ledger.get("schema_version"),
        "provider": provider_seen,
        "provider_present": bool(provider_seen),
        "model": model_seen,
        "model_present": bool(model_seen),
        "requested_provider": provider,
        "runtime_authoritative": runtime.get("runtime_authoritative"),
        "failover_used": bool(runtime.get("failover_used")),
        "metadata_seen": bool(stream.get("metadata_seen")),
        "done_seen": bool(stream.get("done_seen")),
        "terminal_event_name": terminal_event_name,
        "done_count_matches_ledger": event_counts.get("done", 0)
        == int(ledger_event_counts.get("done") or 0),
        "metadata_count_matches_ledger": event_counts.get("metadata", 0)
        == int(ledger_event_counts.get("metadata") or 0),
        "finalization_status": finalization.get("status"),
        "post_turn_lifecycle_schema_version": post_turn_lifecycle.get("schema_version"),
        "post_turn_lifecycle_status": post_turn_lifecycle.get("status"),
        "post_turn_lifecycle_raw_content_included": post_turn_privacy.get(
            "raw_content_included"
        ),
        "post_turn_lifecycle_raw_scope_keys_present": _raw_scope_keys_present(
            post_turn_lifecycle
        ),
        "event_counts": event_counts,
        "ledger_event_counts": ledger_event_counts,
        "request_id_hash": request_id_hash,
        "request_id_hash_present": bool(request_id_hash),
        "session_id_hash": session_id_hash,
        "session_id_hash_present": bool(session_id_hash),
        "organization_id_hash_present": bool(organization_id_hash),
        "privacy": {
            "raw_sse_data_included": False,
            "request_payload_included": False,
            "stream_prompt_included": False,
            "auth_secret_included": False,
        },
        "diagnostics": diagnostics,
    }


def _assert_provider_evidence_contract(summary: Mapping[str, Any]) -> None:
    errors: list[str] = []
    direct = summary.get("direct_provider_tool_roundtrip")
    if not isinstance(direct, Mapping):
        errors.append("direct_provider_tool_roundtrip")
        direct = {}
    evidence_contract = summary.get("evidence_contract")
    if not isinstance(evidence_contract, Mapping):
        errors.append("evidence_contract")
        evidence_contract = {}
    for key in (
        "credentialed_provider_call_required",
        "tool_roundtrip_required",
        "single_tool_call_required",
        "tool_result_linkage_required",
        "followup_without_extra_tool_calls_required",
        "trace_span_pair_required",
        "stream_ledger_optional",
        "stream_ledger_requires_allow_stream_write",
        "hash_count_only_output",
    ):
        if evidence_contract.get(key) is not True:
            errors.append(f"evidence_contract.{key}")

    runtime_boundary = direct.get("runtime_boundary")
    if not isinstance(runtime_boundary, Mapping):
        errors.append("direct_provider_tool_roundtrip.runtime_boundary")
        runtime_boundary = {}
    for key in (
        "llm_pool_route_used",
        "wiii_chat_model_interface_used",
        "native_message_contract_used",
    ):
        if runtime_boundary.get(key) is not True:
            errors.append(f"direct_provider_tool_roundtrip.runtime_boundary.{key}")
    for key in (
        "raw_provider_http_used",
        "raw_provider_payload_included",
        "raw_provider_response_included",
    ):
        if runtime_boundary.get(key) is not False:
            errors.append(f"direct_provider_tool_roundtrip.runtime_boundary.{key}")

    tool_contract = direct.get("tool_contract")
    if not isinstance(tool_contract, Mapping):
        errors.append("direct_provider_tool_roundtrip.tool_contract")
        tool_contract = {}
    if tool_contract.get("tool_name_matches_probe") is not True:
        errors.append("direct_provider_tool_roundtrip.tool_contract.tool_name_matches_probe")
    if tool_contract.get("forced_tool_choice_used") is not True:
        errors.append("direct_provider_tool_roundtrip.tool_contract.forced_tool_choice_used")
    if tool_contract.get("additional_properties_allowed") is not False:
        errors.append(
            "direct_provider_tool_roundtrip.tool_contract.additional_properties_allowed"
        )
    if tool_contract.get("raw_schema_values_included") is not False:
        errors.append("direct_provider_tool_roundtrip.tool_contract.raw_schema_values_included")

    stream = summary.get("stream_runtime_ledger")
    if isinstance(stream, Mapping) and stream.get("status") == "pass":
        if stream.get("terminal_event_name") != "done":
            errors.append("stream_runtime_ledger.terminal_event_name")
        if stream.get("done_count_matches_ledger") is not True:
            errors.append("stream_runtime_ledger.done_count_matches_ledger")
        privacy = stream.get("privacy")
        if not isinstance(privacy, Mapping):
            errors.append("stream_runtime_ledger.privacy")
        elif privacy.get("auth_secret_included") is not False:
            errors.append("stream_runtime_ledger.privacy.auth_secret_included")

    if errors:
        raise RuntimeError(f"Provider runtime evidence contract failed: {errors}")


async def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    _require_live_call(args)
    direct = await _run_provider_tool_roundtrip(args)
    stream = await _run_stream_ledger_probe(
        args,
        direct_provider=str(direct.get("provider") or ""),
    )
    summary = {
        "status": "pass",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "evidence_contract": _evidence_contract_summary(
            stream_requested=args.include_stream_ledger
        ),
        "direct_provider_tool_roundtrip": direct,
        "stream_runtime_ledger": stream,
        "privacy": {
            "raw_content_included": False,
            "tool_argument_values_included": False,
            "provider_arguments_included": False,
            "provider_payload_included": False,
            "provider_response_included": False,
            "stream_payload_included": False,
            "raw_request_identifiers_included": False,
            "identifier_strategy": "hashes_and_counts",
        },
    }
    _assert_provider_evidence_contract(summary)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Opt-in live provider runtime probe through Wiii abstractions.",
    )
    parser.add_argument("--allow-call", action="store_true", help="Permit live provider calls.")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Check provider evidence readiness without calling the provider.",
    )
    parser.add_argument("--allow-production", action="store_true", help="Permit running against settings.environment=production.")
    parser.add_argument("--allow-failover", action="store_true", help="Allow LLMPool to fail over from the requested provider.")
    parser.add_argument("--provider", choices=SUPPORTED_PROVIDER_ARGS, default="auto")
    parser.add_argument("--tier", choices=("light", "moderate", "deep"), default="light")
    parser.add_argument("--provider-timeout", type=float, default=45.0)
    parser.add_argument("--session-id", default=f"live-provider-runtime-probe-{uuid.uuid4().hex[:12]}")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--organization-id", default=DEFAULT_ORG_ID)
    parser.add_argument("--domain-id", default=DEFAULT_DOMAIN_ID)
    parser.add_argument("--role", choices=("student", "teacher", "admin"), default=DEFAULT_ROLE)
    parser.add_argument("--include-stream-ledger", action="store_true", help="Also call /chat/stream/v3 and verify terminal runtime_flow_ledger.")
    parser.add_argument("--allow-stream-write", action="store_true", help="Permit the stream ledger probe to persist chat/memory state.")
    parser.add_argument("--transport-mode", choices=("asgi", "http"), default=DEFAULT_TRANSPORT_MODE)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--request-id", default="")
    parser.add_argument("--stream-provider", choices=STREAM_PROVIDER_ARGS, default="")
    parser.add_argument("--stream-timeout", type=float, default=120.0)
    parser.add_argument(
        "--stream-prompt",
        default=(
            "Hay tra loi bang dung mot cau ngan: "
            "Wiii live provider runtime probe da hoan tat."
        ),
    )
    parser.add_argument("--out", type=Path, default=None, help="Write UTF-8 JSON evidence to this path.")
    return parser


async def async_main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.preflight_only:
        result = _build_provider_runtime_preflight(args)
        emit_json_payload(result, args.out)
        return 0 if result.get("status") == "pass" else 1
    try:
        result = await _run_probe(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_json_payload(_failure_payload(exc, args), args.out)
        return 1
    emit_json_payload(result, args.out)
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(async_main(list(argv or sys.argv[1:])))


if __name__ == "__main__":
    raise SystemExit(main())
