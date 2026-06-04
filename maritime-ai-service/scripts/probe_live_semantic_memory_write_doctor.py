"""Opt-in semantic-memory write doctor evidence.

This probe exercises Wiii's semantic-memory write audit and doctor path without
calling an LLM or writing to external storage. It appends real write-audit
events through the session-event-log interface, builds the recent doctor report,
builds the aggregate history report, and emits only hash/count/status evidence.

Example:
    WIII_LIVE_SEMANTIC_MEMORY_WRITE_DOCTOR=1 python scripts/probe_live_semantic_memory_write_doctor.py --allow-run --out semantic-memory-write-evidence.json
"""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
import re
import sys
import uuid
from collections.abc import Iterator, Mapping
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


ENV_FLAG = "WIII_LIVE_SEMANTIC_MEMORY_WRITE_DOCTOR"
SCHEMA_VERSION = "wiii.live_semantic_memory_write_doctor.v1"
DEFAULT_USER_ID = "user-semantic-memory-private"
DEFAULT_ORG_ID = "org-semantic-memory-private"
DEFAULT_SESSION_ID = f"session-semantic-memory-{uuid.uuid4().hex[:12]}"
DEFAULT_REQUEST_ID = f"req-semantic-memory-{uuid.uuid4().hex[:12]}"
RAW_MESSAGE_MARKER = "PRIVATE SEMANTIC MEMORY MESSAGE access_token=raw-memory-message-token"
RAW_RESPONSE_MARKER = "PRIVATE SEMANTIC MEMORY RESPONSE authorization=raw-memory-response-token"
RAW_CROSS_ORG_MARKER = "PRIVATE CROSS ORG MEMORY content"
IDENTIFIER_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _hash(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _redact_error(value: Any) -> str:
    try:
        from app.engine.runtime.event_payload_sanitizer import (
            redact_runtime_secret_text,
        )

        return redact_runtime_secret_text(str(value))
    except Exception:  # noqa: BLE001
        return str(value)


def _redact_failure_text(value: Any, args: argparse.Namespace | None = None) -> str:
    text = _redact_error(value)[:1000]
    text = IDENTIFIER_RE.sub(
        lambda match: _hash(match.group(0)) or "<redacted-identifier>",
        text,
    )
    replacements = {
        RAW_MESSAGE_MARKER: "<redacted-memory-marker>",
        RAW_RESPONSE_MARKER: "<redacted-memory-marker>",
        RAW_CROSS_ORG_MARKER: "<redacted-memory-marker>",
        "PRIVATE SEMANTIC MEMORY MESSAGE": "<redacted-memory-marker>",
        "PRIVATE SEMANTIC MEMORY RESPONSE": "<redacted-memory-marker>",
        "PRIVATE CROSS ORG MEMORY": "<redacted-memory-marker>",
        "PRIVATE SEMANTIC MEMORY": "<redacted-memory-marker>",
        "PRIVATE CROSS ORG": "<redacted-memory-marker>",
        "raw-memory-message-token": "<redacted-sensitive-field>",
        "raw-memory-response-token": "<redacted-sensitive-field>",
        "api_key": "<redacted-sensitive-field>",
        "access_token": "<redacted-sensitive-field>",
        "authorization": "<redacted-sensitive-field>",
    }
    if args is not None:
        for raw_value in (
            getattr(args, "user_id", None),
            getattr(args, "organization_id", None),
            getattr(args, "session_id", None),
            getattr(args, "request_id", None),
        ):
            if not raw_value:
                continue
            replacements[str(raw_value)] = _hash(raw_value) or "<redacted-value>"
    for raw, replacement in replacements.items():
        text = re.sub(re.escape(raw), replacement, text, flags=re.IGNORECASE)
    return text


def _failure_payload(exc: Exception, args: argparse.Namespace) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "generated_at": _utc_now(),
        "error_code": "semantic_memory_write_doctor_failed",
        "error_message": _redact_failure_text(exc, args),
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
            "raw_request_identifier_included": False,
            "raw_secret_included": False,
            "failure_error_redacted": True,
        },
    }


def _forbidden_tokens() -> tuple[str, ...]:
    return (
        RAW_MESSAGE_MARKER,
        RAW_RESPONSE_MARKER,
        RAW_CROSS_ORG_MARKER,
        DEFAULT_USER_ID,
        DEFAULT_ORG_ID,
        "session-semantic-memory-",
        "access_token",
        "authorization",
        "raw-memory-message-token",
        "raw-memory-response-token",
        "PRIVATE SEMANTIC MEMORY",
        "PRIVATE CROSS ORG",
    )


def _raise_if_contains_forbidden(rendered: str) -> None:
    leaked = [
        token for token in _forbidden_tokens() if token.casefold() in rendered.casefold()
    ]
    if leaked:
        raise RuntimeError(f"Semantic-memory write evidence leaked forbidden data: {leaked}")


def _require_live_run(args: argparse.Namespace) -> None:
    if not args.allow_run:
        raise SystemExit("--allow-run is required; this probe imports live Wiii runtime code")
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to run the semantic-memory write doctor probe")

    from app.core.config import settings

    if settings.environment == "production" and not args.allow_production:
        raise SystemExit("Refusing to run against production without --allow-production")


@contextmanager
def _patched_session_event_log(log: Any) -> Iterator[None]:
    from app.engine.runtime import session_event_log

    original = getattr(session_event_log, "_singleton", None)
    session_event_log._singleton = log
    try:
        yield
    finally:
        session_event_log._singleton = original


def _doctor_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    summary = report.get("summary")
    source = report.get("source")
    privacy = report.get("privacy")
    return {
        "version": report.get("version"),
        "status": report.get("status"),
        "summary": dict(summary) if isinstance(summary, Mapping) else {},
        "write_kinds": dict(report.get("write_kinds") or {}),
        "write_statuses": dict(report.get("write_statuses") or {}),
        "organization_contexts": dict(report.get("organization_contexts") or {}),
        "warnings": dict(report.get("warnings") or {}),
        "source": dict(source) if isinstance(source, Mapping) else {},
        "privacy": dict(privacy) if isinstance(privacy, Mapping) else {},
    }


def _history_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    source = report.get("source")
    privacy = report.get("privacy")
    return {
        "version": report.get("version"),
        "bucket_strategy": report.get("bucket_strategy"),
        "identifier_strategy": report.get("identifier_strategy"),
        "buckets": list(report.get("buckets") or []),
        "source": dict(source) if isinstance(source, Mapping) else {},
        "privacy": dict(privacy) if isinstance(privacy, Mapping) else {},
    }


def _runtime_flow_doctor_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": report.get("version"),
        "status": report.get("status"),
        "summary": dict(report.get("summary") or {}),
        "finalization_statuses": dict(report.get("finalization_statuses") or {}),
        "post_turn_lifecycle_ledger": dict(
            report.get("post_turn_lifecycle_ledger") or {}
        ),
        "source": dict(report.get("source") or {}),
        "privacy": dict(report.get("privacy") or {}),
    }


def _runtime_flow_history_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "version": report.get("version"),
        "bucket_strategy": report.get("bucket_strategy"),
        "identifier_strategy": report.get("identifier_strategy"),
        "buckets": list(report.get("buckets") or []),
        "post_turn_lifecycle_ledger": dict(
            report.get("post_turn_lifecycle_ledger") or {}
        ),
        "source": dict(report.get("source") or {}),
        "privacy": dict(report.get("privacy") or {}),
    }


class _LifecycleSchedulingProbeSemanticMemory:
    def is_available(self) -> bool:
        return True


class _LifecycleSchedulingProbeRunner:
    def __init__(self) -> None:
        self._semantic_memory = _LifecycleSchedulingProbeSemanticMemory()

    async def _store_semantic_interaction(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def _enqueue_or_run_semantic_memory_maintenance(
        self,
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        return None

    def schedule_non_semantic_tasks(self, **_kwargs: Any) -> Any:
        from app.services.background_tasks import BackgroundTaskScheduleSummary

        return BackgroundTaskScheduleSummary(task_count=0, groups=())


def _post_turn_lifecycle_scheduling_summary(args: argparse.Namespace) -> dict[str, Any]:
    from app.services.post_turn_lifecycle import (
        PostTurnLifecycleContext,
        schedule_post_turn_lifecycle,
    )

    scheduled_task_names: list[str] = []

    def background_save(task: Any, *_task_args: Any, **_task_kwargs: Any) -> None:
        scheduled_task_names.append(str(getattr(task, "__name__", "unknown")))

    result = schedule_post_turn_lifecycle(
        PostTurnLifecycleContext(
            background_save=background_save,
            background_runner=_LifecycleSchedulingProbeRunner(),
            user_id=args.user_id,
            session_id=args.session_id,
            message=RAW_MESSAGE_MARKER,
            response_text=RAW_RESPONSE_MARKER,
            organization_id=args.organization_id,
            transport_type="sync",
            skip_fact_extraction=False,
            ephemeral_direct_turn=False,
        )
    )
    summary = result.to_summary()
    return {
        "schema_version": summary.get("schema_version"),
        "status": summary.get("status"),
        "reason": summary.get("reason"),
        "semantic_memory_policy": summary.get("semantic_memory_policy"),
        "background_tasks_scheduled": summary.get("background_tasks_scheduled"),
        "background_schedule": dict(summary.get("background_schedule") or {}),
        "scheduled_task_count": len(scheduled_task_names),
        "scheduled_task_names": scheduled_task_names,
        "lifecycle_owned_semantic_scheduling": True,
        "compatibility_wrapper_used": False,
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "status_only",
        },
    }


def _runtime_flow_ledger_payload(
    args: argparse.Namespace,
    *,
    org_id: str,
    session_id: str,
    request_id: str,
    post_turn_lifecycle: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "wiii.runtime_flow_ledger.v1",
        "request": {
            "request_id": request_id,
            "session_id": session_id,
            "user_id_hash": _hash(args.user_id),
            "organization_id_hash": _hash(org_id),
        },
        "route": {
            "lane": "semantic_memory_write_doctor",
            "turn_path_decision": {"path": "semantic_memory_write_doctor"},
        },
        "context": {
            "uploaded_document_count": 0,
            "source_ref_count": 0,
            "memory_context_count": 0,
            "context_provenance": {
                "warnings": [],
                "privacy": {
                    "raw_content_included": False,
                    "identifier_strategy": "hash_or_count_only",
                },
            },
        },
        "tools": {"observed": [], "suppressed": []},
        "stream": {
            "transport": "sse_v3",
            "event_counts": {"metadata": 1, "done": 1},
            "metadata_seen": True,
            "done_seen": True,
        },
        "finalization": {
            "status": "saved",
            "post_turn_lifecycle": dict(post_turn_lifecycle),
        },
    }


async def _run_semantic_memory_write_doctor(args: argparse.Namespace) -> dict[str, Any]:
    from app.engine.runtime.session_event_log import InMemorySessionEventLog
    from app.engine.multi_agent.runtime_flow_doctor import (
        build_recent_runtime_flow_doctor_report_from_session_log,
        build_runtime_flow_doctor_history_from_session_log,
    )
    from app.engine.semantic_memory.write_audit import (
        MemoryWriteScope,
        SEMANTIC_MEMORY_WRITE_AUDIT_VERSION,
        append_semantic_memory_write_audit_event,
        build_semantic_memory_write_audit,
    )
    from app.engine.semantic_memory.write_doctor import (
        build_recent_semantic_memory_write_doctor_report_from_session_log,
        build_semantic_memory_write_doctor_history_from_session_log,
        build_semantic_memory_write_doctor_report,
    )

    log = InMemorySessionEventLog()
    post_turn_lifecycle = _post_turn_lifecycle_scheduling_summary(args)
    org_a = args.organization_id
    org_b = f"{args.organization_id}-other"
    session_a = args.session_id
    session_b = f"{args.session_id}-other"

    saved_payload = build_semantic_memory_write_audit(
        user_id=args.user_id,
        session_id=session_a,
        message=RAW_MESSAGE_MARKER,
        response=RAW_RESPONSE_MARKER,
        scope=MemoryWriteScope(org_id=org_a, state="request_scoped"),
        write_kind="interaction",
        message_saved=True,
        response_saved=True,
        extract_facts=True,
        stored_fact_count=2,
        stored_insight_count=0,
        status="saved",
    )
    degraded_payload = build_semantic_memory_write_audit(
        user_id=args.user_id,
        session_id=session_a,
        message=RAW_MESSAGE_MARKER,
        response=RAW_RESPONSE_MARKER,
        scope=MemoryWriteScope(org_id=org_a, state="request_scoped"),
        write_kind="insight_store",
        message_saved=False,
        response_saved=False,
        extract_facts=False,
        stored_fact_count=0,
        stored_insight_count=1,
        status="degraded",
        warnings=["insight_store_degraded"],
    )
    cross_org_payload = build_semantic_memory_write_audit(
        user_id=f"{args.user_id}-other",
        session_id=session_b,
        message=RAW_CROSS_ORG_MARKER,
        response=RAW_CROSS_ORG_MARKER,
        scope=MemoryWriteScope(org_id=org_b, state="request_scoped"),
        write_kind="interaction",
        message_saved=True,
        response_saved=True,
        extract_facts=True,
        stored_fact_count=4,
        stored_insight_count=0,
        status="saved",
    )
    blocked_payload = build_semantic_memory_write_audit(
        user_id=args.user_id,
        session_id=None,
        message=RAW_MESSAGE_MARKER,
        response=RAW_RESPONSE_MARKER,
        scope=MemoryWriteScope(
            org_id=None,
            state="blocked_missing_org_context",
            warnings=["missing_org_context"],
            write_allowed=False,
        ),
        write_kind="living_episode",
        message_saved=False,
        response_saved=False,
        extract_facts=True,
        stored_fact_count=0,
        stored_insight_count=0,
        status="blocked",
    )

    with _patched_session_event_log(log):
        append_results = [
            await append_semantic_memory_write_audit_event(
                session_id=session_a,
                org_id=org_a,
                payload=saved_payload,
            ),
            await append_semantic_memory_write_audit_event(
                session_id=session_a,
                org_id=org_a,
                payload=degraded_payload,
            ),
            await append_semantic_memory_write_audit_event(
                session_id=session_b,
                org_id=org_b,
                payload=cross_org_payload,
            ),
        ]
        await log.append(
            session_id=session_a,
            org_id=org_a,
            event_type="user_message",
            payload={"text": RAW_MESSAGE_MARKER},
        )
        await log.append(
            session_id=session_a,
            org_id=org_a,
            event_type="runtime_flow_ledger",
            payload={
                "runtime_flow_ledger": _runtime_flow_ledger_payload(
                    args,
                    org_id=org_a,
                    session_id=session_a,
                    request_id=args.request_id,
                    post_turn_lifecycle=post_turn_lifecycle,
                )
            },
        )
        await log.append(
            session_id=session_b,
            org_id=org_b,
            event_type="runtime_flow_ledger",
            payload={
                "runtime_flow_ledger": _runtime_flow_ledger_payload(
                    args,
                    org_id=org_b,
                    session_id=session_b,
                    request_id=f"{args.request_id}-other",
                    post_turn_lifecycle=post_turn_lifecycle,
                )
            },
        )

    org_report = await build_recent_semantic_memory_write_doctor_report_from_session_log(
        log,
        org_id=org_a,
        limit=20,
    )
    org_history = await build_semantic_memory_write_doctor_history_from_session_log(
        log,
        org_id=org_a,
        limit=20,
        bucket_limit=12,
    )
    runtime_flow_report = await build_recent_runtime_flow_doctor_report_from_session_log(
        log,
        org_id=org_a,
        limit=20,
    )
    runtime_flow_history = await build_runtime_flow_doctor_history_from_session_log(
        log,
        org_id=org_a,
        limit=20,
        bucket_limit=12,
    )
    blocked_report = build_semantic_memory_write_doctor_report([blocked_payload])
    org_semantic_events = await log.get_recent_events(
        org_id=org_a,
        event_type="semantic_memory_write",
        limit=20,
    )
    org_runtime_flow_events = await log.get_recent_events(
        org_id=org_a,
        event_type="runtime_flow_ledger",
        limit=20,
    )
    total_semantic_events = await log.get_recent_events(
        event_type="semantic_memory_write",
        limit=20,
    )
    total_runtime_flow_events = await log.get_recent_events(
        event_type="runtime_flow_ledger",
        limit=20,
    )
    total_events = await log.get_recent_events(limit=20)

    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "pass",
        "runtime": {
            "path": "semantic_memory_write_doctor",
            "request_id_hash": _hash(args.request_id),
            "session_id_hash": _hash(session_a),
            "organization_id_hash": _hash(org_a),
        },
        "semantic_memory_write": {
            "audit_schema_version": SEMANTIC_MEMORY_WRITE_AUDIT_VERSION,
            "event_type": "semantic_memory_write",
        },
        "post_turn_lifecycle": post_turn_lifecycle,
        "session_log": {
            "backend": "in_memory",
            "append_count": sum(1 for result in append_results if result),
            "total_event_count": len(total_events),
            "total_semantic_write_event_count": len(total_semantic_events),
            "org_scoped_semantic_write_event_count": len(org_semantic_events),
            "total_runtime_flow_ledger_event_count": len(total_runtime_flow_events),
            "org_scoped_runtime_flow_ledger_event_count": len(
                org_runtime_flow_events
            ),
            "cross_org_event_excluded": len(total_semantic_events) == 3
            and len(org_semantic_events) == 2,
            "cross_org_runtime_flow_ledger_excluded": (
                len(total_runtime_flow_events) == 2
                and len(org_runtime_flow_events) == 1
            ),
            "raw_non_memory_event_ignored": len(total_events) == 6
            and org_report.get("source", {}).get("semantic_memory_write_event_count") == 2,
        },
        "org_scoped_doctor": _doctor_summary(org_report),
        "org_scoped_history": _history_summary(org_history),
        "runtime_flow_doctor": _runtime_flow_doctor_summary(runtime_flow_report),
        "runtime_flow_doctor_history": _runtime_flow_history_summary(
            runtime_flow_history
        ),
        "blocked_missing_org_context": _doctor_summary(blocked_report),
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_user_identifier_included": False,
            "raw_session_identifier_included": False,
            "raw_organization_identifier_included": False,
        },
    }
    _assert_probe_summary(summary)
    return summary


def _assert_probe_summary(summary: dict[str, Any]) -> None:
    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    _raise_if_contains_forbidden(rendered)

    if summary.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError("Semantic-memory evidence schema mismatch")
    if summary.get("status") != "pass":
        raise RuntimeError("Semantic-memory write doctor probe did not pass")
    if summary.get("runtime", {}).get("path") != "semantic_memory_write_doctor":
        raise RuntimeError("Probe did not record semantic_memory_write_doctor path")
    post_turn = summary.get("post_turn_lifecycle", {})
    if post_turn.get("schema_version") != "wiii.post_turn_lifecycle.v1":
        raise RuntimeError("Post-turn lifecycle schema mismatch")
    if post_turn.get("status") != "scheduled":
        raise RuntimeError("Post-turn lifecycle scheduling did not run")
    if post_turn.get("reason") != "post_turn_background_tasks_scheduled":
        raise RuntimeError("Post-turn lifecycle scheduling reason mismatch")
    if post_turn.get("semantic_memory_policy") != "extract_facts":
        raise RuntimeError("Post-turn lifecycle semantic-memory policy mismatch")
    if post_turn.get("background_tasks_scheduled") is not True:
        raise RuntimeError("Post-turn lifecycle did not schedule background tasks")
    if post_turn.get("lifecycle_owned_semantic_scheduling") is not True:
        raise RuntimeError("Semantic-memory scheduling is not lifecycle-owned")
    if post_turn.get("compatibility_wrapper_used") is not False:
        raise RuntimeError("Probe must not use the schedule_all compatibility wrapper")
    if post_turn.get("scheduled_task_count") != 2:
        raise RuntimeError("Expected two lifecycle-owned semantic-memory tasks")
    if post_turn.get("scheduled_task_names") != [
        "_store_semantic_interaction",
        "_enqueue_or_run_semantic_memory_maintenance",
    ]:
        raise RuntimeError("Unexpected lifecycle-owned semantic-memory task names")
    background_schedule = post_turn.get("background_schedule", {})
    if background_schedule.get("schema_version") != "wiii.background_task_schedule.v1":
        raise RuntimeError("Post-turn background schedule schema mismatch")
    if background_schedule.get("task_count") != 2:
        raise RuntimeError("Expected two post-turn background semantic tasks")
    groups = background_schedule.get("groups")
    if not isinstance(groups, list) or len(groups) != 2:
        raise RuntimeError("Expected two post-turn background schedule groups")
    if groups[0].get("group") != "semantic_memory_interaction":
        raise RuntimeError("Expected semantic-memory interaction schedule group")
    if groups[0].get("reason") != "extract_facts":
        raise RuntimeError("Expected fact extraction semantic-memory schedule")
    if groups[1].get("group") != "semantic_memory_maintenance":
        raise RuntimeError("Expected semantic-memory maintenance schedule group")
    if groups[1].get("reason") != "after_interaction_write":
        raise RuntimeError("Expected maintenance after interaction write")
    if post_turn.get("privacy", {}).get("raw_content_included") is not False:
        raise RuntimeError("Post-turn lifecycle privacy marker must be false")
    if summary.get("session_log", {}).get("append_count") != 3:
        raise RuntimeError("Expected three semantic-memory audit appends")
    if summary.get("session_log", {}).get("cross_org_event_excluded") is not True:
        raise RuntimeError("Org-scoped doctor did not exclude cross-org events")
    if (
        summary.get("session_log", {}).get("cross_org_runtime_flow_ledger_excluded")
        is not True
    ):
        raise RuntimeError("Runtime-flow doctor did not exclude cross-org ledgers")
    if summary.get("session_log", {}).get("raw_non_memory_event_ignored") is not True:
        raise RuntimeError("Doctor did not ignore non-memory raw session events")
    org_doctor = summary.get("org_scoped_doctor", {})
    if org_doctor.get("status") != "degraded":
        raise RuntimeError("Expected degraded org-scoped doctor report")
    if org_doctor.get("summary", {}).get("write_count") != 2:
        raise RuntimeError("Expected two org-scoped semantic-memory writes")
    if org_doctor.get("summary", {}).get("stored_fact_total") != 2:
        raise RuntimeError("Expected stored fact total from org-scoped writes")
    if org_doctor.get("summary", {}).get("stored_insight_total") != 1:
        raise RuntimeError("Expected stored insight total from org-scoped writes")
    if org_doctor.get("source", {}).get("org_scoped") is not True:
        raise RuntimeError("Recent doctor source must be org-scoped")
    org_history = summary.get("org_scoped_history", {})
    if org_history.get("version") != "wiii.semantic_memory_write_doctor_history.v1":
        raise RuntimeError("Semantic-memory history schema mismatch")
    if org_history.get("bucket_strategy") != "event_created_at_hour":
        raise RuntimeError("Semantic-memory history must use event_created_at_hour buckets")
    if org_history.get("identifier_strategy") != "aggregate_counts_only":
        raise RuntimeError("Semantic-memory history must stay aggregate-only")
    history_source = org_history.get("source", {})
    if history_source.get("semantic_memory_write_event_count") != 2:
        raise RuntimeError("History must summarize two org-scoped write events")
    if history_source.get("org_scoped") is not True:
        raise RuntimeError("History source must be org-scoped")
    if history_source.get("window") != "recent_semantic_memory_write_history":
        raise RuntimeError("History source window mismatch")
    buckets = org_history.get("buckets")
    if not isinstance(buckets, list) or len(buckets) != 1:
        raise RuntimeError("Expected one semantic-memory history bucket")
    history_bucket = buckets[0]
    if history_bucket.get("status") != "degraded":
        raise RuntimeError("Expected degraded semantic-memory history bucket")
    bucket_summary = history_bucket.get("summary", {})
    if bucket_summary.get("write_count") != 2:
        raise RuntimeError("Expected two writes in semantic-memory history bucket")
    if bucket_summary.get("stored_fact_total") != 2:
        raise RuntimeError("Expected stored fact total in semantic-memory history")
    if bucket_summary.get("stored_insight_total") != 1:
        raise RuntimeError("Expected stored insight total in semantic-memory history")
    if history_bucket.get("warnings", {}).get("insight_store_degraded") != 1:
        raise RuntimeError("Expected degraded insight warning in history bucket")
    if org_history.get("privacy", {}).get("raw_content_included") is not False:
        raise RuntimeError("History privacy marker raw_content_included must be false")
    runtime_flow_doctor = summary.get("runtime_flow_doctor", {})
    if runtime_flow_doctor.get("version") != "wiii.runtime_flow_doctor.v1":
        raise RuntimeError("Runtime-flow doctor schema mismatch")
    if runtime_flow_doctor.get("status") != "ready":
        raise RuntimeError("Runtime-flow doctor did not report ready")
    if runtime_flow_doctor.get("summary", {}).get("turn_count") != 1:
        raise RuntimeError("Runtime-flow doctor must summarize one org-scoped ledger")
    if runtime_flow_doctor.get("finalization_statuses", {}).get("saved") != 1:
        raise RuntimeError("Runtime-flow doctor did not see saved finalization")
    runtime_source = runtime_flow_doctor.get("source", {})
    if runtime_source.get("runtime_flow_ledger_event_count") != 1:
        raise RuntimeError("Runtime-flow doctor must use one org-scoped ledger event")
    if runtime_source.get("org_scoped") is not True:
        raise RuntimeError("Runtime-flow doctor source must be org-scoped")
    lifecycle_ledger = runtime_flow_doctor.get("post_turn_lifecycle_ledger", {})
    if lifecycle_ledger.get("version") != "wiii.post_turn_lifecycle_ledger.v1":
        raise RuntimeError("Post-turn lifecycle ledger schema mismatch")
    if lifecycle_ledger.get("event_count") != 1:
        raise RuntimeError("Post-turn lifecycle ledger event count mismatch")
    if lifecycle_ledger.get("missing_count") != 0:
        raise RuntimeError("Post-turn lifecycle ledger should not be missing")
    if lifecycle_ledger.get("background_tasks_scheduled_count") != 1:
        raise RuntimeError("Post-turn lifecycle ledger did not see scheduled tasks")
    lifecycle_background = lifecycle_ledger.get("background_schedule", {})
    if lifecycle_background.get("task_count") != 2:
        raise RuntimeError("Durable post-turn lifecycle task count mismatch")
    if lifecycle_background.get("group_counts", {}).get("semantic_memory_interaction") != 1:
        raise RuntimeError("Durable interaction task group was not counted")
    if lifecycle_background.get("group_counts", {}).get("semantic_memory_maintenance") != 1:
        raise RuntimeError("Durable maintenance task group was not counted")
    if lifecycle_ledger.get("privacy", {}).get("raw_content_included") is not False:
        raise RuntimeError("Post-turn lifecycle ledger privacy marker must be false")
    runtime_history = summary.get("runtime_flow_doctor_history", {})
    if runtime_history.get("version") != "wiii.runtime_flow_doctor_history.v1":
        raise RuntimeError("Runtime-flow doctor history schema mismatch")
    if runtime_history.get("bucket_strategy") != "event_created_at_hour":
        raise RuntimeError("Runtime-flow doctor history bucket strategy mismatch")
    runtime_history_source = runtime_history.get("source", {})
    if runtime_history_source.get("runtime_flow_ledger_event_count") != 1:
        raise RuntimeError("Runtime-flow history must summarize one ledger event")
    if runtime_history_source.get("org_scoped") is not True:
        raise RuntimeError("Runtime-flow history source must be org-scoped")
    if runtime_history_source.get("window") != "recent_runtime_flow_ledger_history":
        raise RuntimeError("Runtime-flow history source window mismatch")
    history_lifecycle = runtime_history.get("post_turn_lifecycle_ledger", {})
    if history_lifecycle.get("event_count") != 1:
        raise RuntimeError("Runtime-flow history lost post-turn lifecycle ledger count")
    history_buckets = runtime_history.get("buckets")
    if not isinstance(history_buckets, list) or len(history_buckets) != 1:
        raise RuntimeError("Expected one runtime-flow history bucket")
    if history_buckets[0].get("post_turn_lifecycle_ledger", {}).get("event_count") != 1:
        raise RuntimeError("Runtime-flow history bucket lacks lifecycle ledger proof")
    if runtime_history.get("privacy", {}).get("raw_content_included") is not False:
        raise RuntimeError("Runtime-flow history privacy marker must be false")
    blocked = summary.get("blocked_missing_org_context", {})
    if blocked.get("summary", {}).get("blocked_count") != 1:
        raise RuntimeError("Blocked missing-org write was not counted")
    if blocked.get("warnings", {}).get("missing_org_context") != 1:
        raise RuntimeError("Missing-org warning was not counted")
    privacy = summary.get("privacy", {})
    for key in (
        "raw_content_included",
        "raw_user_identifier_included",
        "raw_session_identifier_included",
        "raw_organization_identifier_included",
    ):
        if privacy.get(key) is not False:
            raise RuntimeError(f"Privacy marker {key} must be false")


async def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    _require_live_run(args)
    return await _run_semantic_memory_write_doctor(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an opt-in semantic-memory write doctor evidence probe.",
    )
    parser.add_argument("--allow-run", action="store_true", help="Permit runtime imports and local replay.")
    parser.add_argument("--allow-production", action="store_true", help="Permit settings.environment=production.")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--organization-id", default=DEFAULT_ORG_ID)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--request-id", default=DEFAULT_REQUEST_ID)
    parser.add_argument("--out", type=Path, default=None, help="Write UTF-8 JSON evidence to this path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = asyncio.run(_run_probe(args))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        emit_json_payload(_failure_payload(exc, args), args.out)
        return 1
    emit_json_payload(summary, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
