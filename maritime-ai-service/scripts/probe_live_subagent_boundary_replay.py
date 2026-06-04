"""Opt-in live parallel subagent boundary replay.

This probe exercises the real subagent executor, runtime-flow ledger, and
runtime-flow doctor without calling external providers or mutating durable
state. It is still opt-in because it imports the application runtime and should
only be run intentionally in local/staging diagnostics.

Example:
    WIII_LIVE_SUBAGENT_BOUNDARY_REPLAY=1 python scripts/probe_live_subagent_boundary_replay.py --allow-run --out subagent-boundary-evidence.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from runtime_evidence_output import emit_json_payload  # noqa: E402


ENV_FLAG = "WIII_LIVE_SUBAGENT_BOUNDARY_REPLAY"
SCHEMA_VERSION = "wiii.live_subagent_boundary_replay.v1"
EXPECTED_SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION = "wiii.subagent_boundary_trace.v1"
DEFAULT_SESSION_ID = f"live-subagent-boundary-{uuid.uuid4().hex[:12]}"
DEFAULT_REQUEST_ID = f"req-live-subagent-boundary-{uuid.uuid4().hex[:12]}"
DEFAULT_ORG_ID = "live-subagent-boundary-org"
RAW_MARKER = "PRIVATE_SUBAGENT_BOUNDARY_RAW_MARKER"
RAW_SECRET = "Bearer live-subagent-boundary-token"


def _json_print(payload: dict[str, Any]) -> None:
    emit_json_payload(payload)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(value: Any) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _redact_failure_text(value: Any, args: argparse.Namespace | None = None) -> str:
    text = str(value or "")
    try:
        from app.engine.runtime.event_payload_sanitizer import (
            redact_runtime_secret_text,
        )

        text = redact_runtime_secret_text(text, max_length=1000)
    except Exception:  # noqa: BLE001
        text = text[:1000]

    replacements = {
        RAW_MARKER: "<redacted-private-marker>",
        RAW_SECRET: "<redacted-secret>",
        "access_token": "<redacted-sensitive-field>",
        "api_key": "<redacted-sensitive-field>",
        "authorization": "<redacted-sensitive-field>",
    }
    if args is not None:
        for raw_identifier in (
            getattr(args, "request_id", None),
            getattr(args, "session_id", None),
            getattr(args, "organization_id", None),
        ):
            if not raw_identifier:
                continue
            replacements[str(raw_identifier)] = _hash(raw_identifier) or "<redacted-id>"
    for raw, replacement in replacements.items():
        text = re.sub(re.escape(raw), replacement, text, flags=re.IGNORECASE)
    return text


def _failure_payload(exc: Exception, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema": SCHEMA_VERSION,
        "status": "fail",
        "generated_at": _utc_now(),
        "error_code": "subagent_boundary_replay_failed",
        "error_message": _redact_failure_text(exc, args),
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_request_identifiers_included": False,
            "raw_secret_included": False,
            "failure_error_redacted": True,
        },
    }


def _require_live_run(args: argparse.Namespace) -> None:
    if not args.allow_run:
        raise SystemExit("--allow-run is required; this probe imports live Wiii runtime code")
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to run the live subagent boundary replay")

    from app.core.config import settings

    if settings.environment == "production" and not args.allow_production:
        raise SystemExit("Refusing to run against production without --allow-production")


def _base_parent_state(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "request_id": args.request_id,
        "session_id": args.session_id,
        "organization_id": args.organization_id,
        "safe_parent_fact": "parallel_subagent_boundary_probe",
        "conversation_summary": "Bounded public parent context.",
        "tool_call_events": [{"name": "raw_parent_tool", "payload": RAW_MARKER}],
        "thinking": f"{RAW_MARKER} parent private chain",
        "_thinking_history": [RAW_MARKER],
        "_tool_policy_session": {"authorization": RAW_SECRET},
        "access_token": RAW_SECRET,
        "provider_payload": {"raw": RAW_MARKER},
        "context": {
            "request_id": args.request_id,
            "host_surface": "diagnostic_probe",
        },
    }


async def _rag_probe_worker(state: dict[str, Any], **kwargs: Any):
    from app.engine.multi_agent.subagents.result import SubagentResult, SubagentStatus

    await asyncio.sleep(float(kwargs.get("delay_seconds") or 0.0))
    return SubagentResult(
        status=SubagentStatus.SUCCESS,
        confidence=0.91,
        output=f"{RAW_MARKER} rag child output {RAW_SECRET}",
        data={
            "finding_count": 2,
            "raw_payload": RAW_MARKER,
            "state_key_count": len(state),
            "kwargs_key_count": len(kwargs),
        },
        sources=[
            {
                "title": "COLREG source",
                "url": "https://example.test/colreg",
                "content": f"{RAW_MARKER} source body",
                "authorization": RAW_SECRET,
            },
            {
                "title": "Safe source",
                "source_type": "document",
                "page": 1,
            },
        ],
        tools_used=[
            {
                "name": "diagnostic_retriever",
                "status": "success",
                "raw_payload": RAW_MARKER,
            }
        ],
        evidence_images=[
            {
                "url": "https://example.test/evidence.png",
                "image_base64": RAW_MARKER,
            }
        ],
        thinking=f"{RAW_MARKER} child private thinking",
    )


async def _search_probe_worker(state: dict[str, Any], **kwargs: Any):
    from app.engine.multi_agent.subagents.result import SubagentResult, SubagentStatus

    await asyncio.sleep(float(kwargs.get("delay_seconds") or 0.0))
    return SubagentResult(
        status=SubagentStatus.PARTIAL,
        confidence=0.67,
        output=f"{RAW_MARKER} search child output {RAW_SECRET}",
        data={
            "candidate_count": 3,
            "state_key_count": len(state),
            "kwargs_key_count": len(kwargs),
        },
        sources=[
            {
                "title": "Search result",
                "url": "https://example.test/search",
                "content": RAW_MARKER,
            }
        ],
        tools_used=[
            {
                "name": "diagnostic_search",
                "status": "success",
                "duration_ms": 1,
            }
        ],
        thinking=f"{RAW_MARKER} search private thinking",
    )


def _report_for_result(agent_name: str, agent_type: str, result: Any) -> dict[str, Any]:
    payload = result.model_dump() if hasattr(result, "model_dump") else {}
    return {
        "agent_name": agent_name,
        "agent_type": agent_type,
        "status": str(getattr(result, "status", "unknown")),
        "result": payload,
    }


def _status_values(results: list[Any]) -> list[str]:
    values: list[str] = []
    for result in results:
        status = getattr(result, "status", "unknown")
        values.append(str(getattr(status, "value", status)))
    return values


def _safe_counts_from_reports(reports: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "report_count": len(reports),
        "source_count": sum(int(report.get("source_count") or 0) for report in reports),
        "tool_count": sum(int(report.get("tool_count") or 0) for report in reports),
        "state_projected_key_count": sum(
            int(report.get("state_projected_key_count") or 0) for report in reports
        ),
        "state_dropped_key_count": sum(
            int(report.get("state_dropped_key_count") or 0) for report in reports
        ),
        "output_char_count": sum(
            int(report.get("output_char_count") or 0) for report in reports
        ),
        "thinking_dropped_count": sum(
            1 for report in reports if report.get("thinking_dropped") is True
        ),
    }


def _warning_counts(warning_codes: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for code in warning_codes:
        key = str(code or "").strip()
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _result_boundaries(results: list[Any]) -> list[dict[str, Any]]:
    boundaries: list[dict[str, Any]] = []
    for result in results:
        payload = result.model_dump() if hasattr(result, "model_dump") else {}
        boundary = payload.get("boundary") if isinstance(payload, dict) else None
        if isinstance(boundary, dict):
            boundaries.append(boundary)
    return boundaries


def _aggregate_handoff_boundaries(results: list[Any]) -> dict[str, Any]:
    boundaries = _result_boundaries(results)
    state_projected = 0
    state_dropped = 0
    kwargs_projected = 0
    kwargs_dropped = 0
    raw_content_included = False
    schema_versions: set[str] = set()
    warning_codes: list[str] = []
    for boundary in boundaries:
        handoff = boundary.get("handoff") if isinstance(boundary, dict) else None
        if not isinstance(handoff, dict):
            continue
        schema_versions.add(str(handoff.get("schema_version") or ""))
        raw_content_included = raw_content_included or handoff.get("raw_content_included") is True
        warning_codes.extend(str(code) for code in handoff.get("warning_codes") or [])
        state = handoff.get("state") if isinstance(handoff.get("state"), dict) else {}
        kwargs = handoff.get("kwargs") if isinstance(handoff.get("kwargs"), dict) else {}
        state_projected += int(state.get("projected_key_count") or 0)
        state_dropped += int(state.get("dropped_key_count") or 0)
        kwargs_projected += int(kwargs.get("projected_key_count") or 0)
        kwargs_dropped += int(kwargs.get("dropped_key_count") or 0)
    return {
        "schema_versions": sorted(schema_versions),
        "boundary_count": len(boundaries),
        "state_projected_key_count": state_projected,
        "state_dropped_key_count": state_dropped,
        "kwargs_projected_key_count": kwargs_projected,
        "kwargs_dropped_key_count": kwargs_dropped,
        "warning_counts": _warning_counts(warning_codes),
        "raw_content_included": raw_content_included,
    }


def _aggregate_result_boundaries(results: list[Any]) -> dict[str, Any]:
    boundaries = _result_boundaries(results)
    schema_versions: set[str] = set()
    warning_codes: list[str] = []
    status_counts: dict[str, int] = {}
    raw_output_char_count = 0
    output_char_count = 0
    data_key_count = 0
    source_count = 0
    tool_count = 0
    evidence_image_count = 0
    thinking_dropped_count = 0
    raw_content_included = False
    for boundary in boundaries:
        result_boundary = boundary.get("result") if isinstance(boundary, dict) else None
        if not isinstance(result_boundary, dict):
            continue
        schema_versions.add(str(result_boundary.get("schema_version") or ""))
        warning_codes.extend(str(code) for code in result_boundary.get("warning_codes") or [])
        status = str(result_boundary.get("status") or "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
        raw_output_char_count += int(result_boundary.get("raw_output_char_count") or 0)
        output_char_count += int(result_boundary.get("output_char_count") or 0)
        data_key_count += int(result_boundary.get("data_key_count") or 0)
        source_count += int(result_boundary.get("source_count") or 0)
        tool_count += int(result_boundary.get("tool_count") or 0)
        evidence_image_count += int(result_boundary.get("evidence_image_count") or 0)
        thinking_dropped_count += 1 if result_boundary.get("thinking_dropped") is True else 0
        raw_content_included = raw_content_included or result_boundary.get("raw_content_included") is True
    return {
        "schema_versions": sorted(schema_versions),
        "boundary_count": len(boundaries),
        "status_counts": dict(sorted(status_counts.items())),
        "raw_output_char_count": raw_output_char_count,
        "output_char_count": output_char_count,
        "output_sanitized_or_truncated": raw_output_char_count > output_char_count,
        "data_key_count": data_key_count,
        "source_count": source_count,
        "tool_count": tool_count,
        "evidence_image_count": evidence_image_count,
        "thinking_dropped_count": thinking_dropped_count,
        "warning_counts": _warning_counts(warning_codes),
        "raw_content_included": raw_content_included,
    }


async def _run_parallel_boundary_replay(args: argparse.Namespace) -> dict[str, Any]:
    from app.engine.multi_agent.runtime_flow_doctor import (
        build_runtime_flow_doctor_report,
    )
    from app.engine.multi_agent.runtime_flow_ledger import (
        SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION,
        RuntimeFlowLedger,
        build_runtime_flow_trace_from_state,
    )
    from app.engine.multi_agent.subagents.config import SubagentConfig
    from app.engine.multi_agent.subagents.executor import execute_parallel_subagents

    parent_state = _base_parent_state(args)
    task_specs = [
        (
            _rag_probe_worker,
            SubagentConfig(name="rag_boundary_probe", timeout_seconds=10),
            parent_state,
            {
                "query": "bounded rag probe",
                "delay_seconds": args.worker_delay_seconds,
                "authorization": RAW_SECRET,
            },
        ),
        (
            _search_probe_worker,
            SubagentConfig(name="search_boundary_probe", timeout_seconds=10),
            parent_state,
            {
                "query": "bounded search probe",
                "delay_seconds": args.worker_delay_seconds,
                "api_key": RAW_SECRET,
            },
        ),
    ]

    started = time.monotonic()
    results = await execute_parallel_subagents(
        task_specs,
        max_concurrent=args.max_concurrent,
    )
    duration_ms = int((time.monotonic() - started) * 1000)
    subagent_reports = [
        _report_for_result("rag_boundary_probe", "retrieval", results[0]),
        _report_for_result("search_boundary_probe", "search", results[1]),
    ]
    trace = build_runtime_flow_trace_from_state(
        {
            "_turn_path_decision": {
                "version": "turn_path_decision.v1",
                "path": "parallel_subagent_boundary_probe",
                "reason": "live_subagent_boundary_replay",
            },
            "subagent_reports": subagent_reports,
        }
    )
    ledger = RuntimeFlowLedger(
        request_id=args.request_id,
        session_id=args.session_id,
        organization_id_hash=_hash(args.organization_id),
    )
    ledger.observe_metadata({"runtime_flow_trace": trace})
    ledger.record_event(type("DoneEvent", (), {"type": "done", "content": {}})())
    payload = ledger.to_payload()
    doctor = build_runtime_flow_doctor_report([payload])
    subagents = payload.get("subagents") if isinstance(payload.get("subagents"), dict) else {}
    reports = subagents.get("reports") if isinstance(subagents.get("reports"), list) else []
    if SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION != EXPECTED_SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION:
        raise RuntimeError("Imported subagent boundary schema does not match probe expectation")

    request_id_hash = _hash(args.request_id)
    session_id_hash = _hash(args.session_id)
    organization_id_hash = _hash(args.organization_id)
    summary = {
        "schema": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "pass",
        "request": {
            "request_id_hash": request_id_hash,
            "request_id_hash_present": bool(request_id_hash),
            "session_id_hash": session_id_hash,
            "session_id_hash_present": bool(session_id_hash),
            "organization_id_hash": organization_id_hash,
            "organization_id_hash_present": bool(organization_id_hash),
        },
        "execution": {
            "parallel_task_count": len(task_specs),
            "max_concurrent": args.max_concurrent,
            "duration_ms": duration_ms,
            "result_statuses": _status_values(results),
            "result_count_matches_task_count": len(results) == len(task_specs),
            "parallel_execution_configured": args.max_concurrent >= len(task_specs),
        },
        "runtime_ledger": {
            "schema_version": payload.get("schema_version"),
            "done_seen": bool(payload.get("stream", {}).get("done_seen")),
            "subagent_schema_version": subagents.get("schema_version"),
            "subagent_report_count": subagents.get("report_count"),
            "subagent_report_count_matches_execution": (
                int(subagents.get("report_count") or 0) == len(results)
            ),
            "raw_request_identifiers_included": False,
        },
        "subagents": {
            "schema_version": subagents.get("schema_version"),
            "report_count": subagents.get("report_count"),
            "raw_content_included": subagents.get("raw_content_included"),
            "warning_codes": subagents.get("warning_codes") or [],
            "warning_counts": _warning_counts(subagents.get("warning_codes") or []),
            "counts": _safe_counts_from_reports(reports),
        },
        "handoff_boundary": _aggregate_handoff_boundaries(results),
        "result_boundary": _aggregate_result_boundaries(results),
        "doctor": {
            "status": doctor.get("status"),
            "alert_codes": [
                alert.get("code")
                for alert in doctor.get("alerts", [])
                if isinstance(alert, dict)
            ],
            "subagents": doctor.get("subagents", {}),
        },
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_request_identifiers_included": False,
            "raw_secret_included": False,
        },
    }
    _assert_probe_summary(summary)
    if subagents.get("schema_version") != SUBAGENT_BOUNDARY_TRACE_SCHEMA_VERSION:
        raise RuntimeError("Runtime ledger did not emit the subagent boundary trace schema")
    return summary


def _assert_probe_summary(summary: dict[str, Any]) -> None:
    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    forbidden = (RAW_MARKER, RAW_SECRET, "access_token", "api_key", "authorization")
    leaked = [token for token in forbidden if token in rendered]
    if leaked:
        raise RuntimeError(
            f"Probe summary leaked raw child/secret marker(s): count={len(leaked)}"
        )

    request = summary.get("request")
    if not isinstance(request, dict):
        raise RuntimeError("Probe summary missing request hash evidence")
    for key in (
        "request_id_hash_present",
        "session_id_hash_present",
        "organization_id_hash_present",
    ):
        if request.get(key) is not True:
            raise RuntimeError(f"Probe summary missing {key}")

    subagents = summary.get("subagents")
    if not isinstance(subagents, dict):
        raise RuntimeError("Probe summary missing subagent evidence")
    if subagents.get("raw_content_included") is not False:
        raise RuntimeError("Subagent boundary raw_content_included must be false")
    if int(subagents.get("report_count") or 0) < 2:
        raise RuntimeError("Expected at least two subagent boundary reports")
    counts = subagents.get("counts")
    if not isinstance(counts, dict):
        raise RuntimeError("Probe summary missing subagent count aggregate")
    if int(counts.get("source_count") or 0) < 1:
        raise RuntimeError("Expected subagent source count evidence")
    if int(counts.get("tool_count") or 0) < 1:
        raise RuntimeError("Expected subagent tool count evidence")
    if int(counts.get("state_projected_key_count") or 0) < 1:
        raise RuntimeError("Expected subagent projected-key evidence")
    if int(counts.get("state_dropped_key_count") or 0) < 1:
        raise RuntimeError("Expected subagent dropped-key evidence")
    if int(counts.get("thinking_dropped_count") or 0) < 2:
        raise RuntimeError("Expected private-thinking drop evidence")
    warning_codes = set(subagents.get("warning_codes") or [])
    required_warnings = {
        "state_top_level_keys_dropped",
        "kwargs_top_level_keys_dropped",
        "subagent_output_sanitized_or_truncated",
        "subagent_thinking_dropped",
    }
    missing = sorted(required_warnings - warning_codes)
    if missing:
        raise RuntimeError(f"Expected subagent boundary warning(s) missing: {missing}")

    execution = summary.get("execution")
    if not isinstance(execution, dict):
        raise RuntimeError("Probe summary missing execution evidence")
    if execution.get("result_count_matches_task_count") is not True:
        raise RuntimeError("Subagent result count did not match task count")
    if execution.get("parallel_execution_configured") is not True:
        raise RuntimeError("Subagent replay did not configure parallel execution")

    runtime_ledger = summary.get("runtime_ledger")
    if not isinstance(runtime_ledger, dict):
        raise RuntimeError("Probe summary missing runtime-ledger evidence")
    if runtime_ledger.get("schema_version") != "wiii.runtime_flow_ledger.v1":
        raise RuntimeError("Runtime ledger schema evidence missing")
    if runtime_ledger.get("done_seen") is not True:
        raise RuntimeError("Runtime ledger did not record done event")
    if runtime_ledger.get("subagent_report_count_matches_execution") is not True:
        raise RuntimeError("Runtime ledger subagent report count mismatch")

    handoff_boundary = summary.get("handoff_boundary")
    if not isinstance(handoff_boundary, dict):
        raise RuntimeError("Probe summary missing handoff-boundary evidence")
    if handoff_boundary.get("raw_content_included") is not False:
        raise RuntimeError("Handoff boundary included raw content")
    if int(handoff_boundary.get("state_dropped_key_count") or 0) < 1:
        raise RuntimeError("Handoff boundary missing state dropped-key proof")
    if int(handoff_boundary.get("kwargs_dropped_key_count") or 0) < 1:
        raise RuntimeError("Handoff boundary missing kwargs dropped-key proof")

    result_boundary = summary.get("result_boundary")
    if not isinstance(result_boundary, dict):
        raise RuntimeError("Probe summary missing result-boundary evidence")
    if result_boundary.get("raw_content_included") is not False:
        raise RuntimeError("Result boundary included raw content")
    if result_boundary.get("output_sanitized_or_truncated") is not True:
        raise RuntimeError("Result boundary missing output sanitization proof")
    if int(result_boundary.get("thinking_dropped_count") or 0) < 2:
        raise RuntimeError("Result boundary missing private-thinking drop proof")

    doctor = summary.get("doctor")
    if not isinstance(doctor, dict):
        raise RuntimeError("Probe summary missing doctor evidence")
    doctor_subagents = doctor.get("subagents")
    if not isinstance(doctor_subagents, dict):
        raise RuntimeError("Probe summary missing doctor subagent aggregate")
    if int(doctor_subagents.get("report_count") or 0) < 2:
        raise RuntimeError("Doctor did not aggregate subagent boundary reports")
    if int(doctor_subagents.get("raw_content_flag_count") or 0) != 0:
        raise RuntimeError("Doctor reported raw subagent content")

    privacy = summary.get("privacy")
    if not isinstance(privacy, dict):
        raise RuntimeError("Probe summary missing privacy evidence")
    if privacy.get("raw_request_identifiers_included") is not False:
        raise RuntimeError("Probe summary included raw request identifiers")
    if privacy.get("raw_secret_included") is not False:
        raise RuntimeError("Probe summary included raw secrets")


async def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    _require_live_run(args)
    return await _run_parallel_boundary_replay(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an opt-in parallel subagent boundary replay probe.",
    )
    parser.add_argument("--allow-run", action="store_true", help="Permit runtime imports and execution.")
    parser.add_argument("--allow-production", action="store_true", help="Permit settings.environment=production.")
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--request-id", default=DEFAULT_REQUEST_ID)
    parser.add_argument("--organization-id", default=DEFAULT_ORG_ID)
    parser.add_argument("--max-concurrent", type=int, default=2)
    parser.add_argument("--worker-delay-seconds", type=float, default=0.01)
    parser.add_argument("--out", type=Path, default=None, help="Write UTF-8 JSON evidence to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = asyncio.run(_run_probe(args))
    except Exception as exc:  # noqa: BLE001
        emit_json_payload(_failure_payload(exc, args), args.out)
        return 1
    emit_json_payload(summary, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
