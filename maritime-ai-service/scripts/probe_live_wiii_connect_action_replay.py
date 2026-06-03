"""Opt-in Wiii Connect external-app action replay evidence.

This probe exercises Wiii's OpenHuman-style integration lane without requiring
real Composio credentials. It runs the real action planner, integration lane,
provider-scoped worker, backend gateway, schema preflight, audit append, and
final-answer adapter. The provider adapter boundary is replaced with a local
fake schema/execute result so CI can prove the contract deterministically.

Example:
    WIII_LIVE_WIII_CONNECT_ACTION_REPLAY=1 python scripts/probe_live_wiii_connect_action_replay.py --allow-run --out wiii-connect-action-evidence.json
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


ENV_FLAG = "WIII_LIVE_WIII_CONNECT_ACTION_REPLAY"
SCHEMA_VERSION = "wiii.live_wiii_connect_action_replay.v1"
DEFAULT_ORG_ID = "live-wiii-connect-action-org"
DEFAULT_USER_ID = "live-wiii-connect-action-user"
DEFAULT_SESSION_ID = f"live-wiii-connect-action-{uuid.uuid4().hex[:12]}"
DEFAULT_REQUEST_ID = f"req-live-wiii-connect-action-{uuid.uuid4().hex[:12]}"
RAW_ARGUMENT_MARKER = "WIII_CONNECT_ACTION_REPLAY_RAW_ARGUMENT_MARKER"
RAW_SECRET_MARKER = "Bearer live-wiii-connect-action-token"
IDENTIFIER_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class _FakeStorage:
    def __init__(self, records: tuple[Any, ...]) -> None:
        self.records = records
        self.audit_records: list[tuple[Any, str, str]] = []
        self.list_calls: list[dict[str, Any]] = []

    def status(self, *, probe_database: bool = True) -> Any:
        from app.engine.wiii_connect.persistent_storage import (
            WiiiConnectPersistentStorageStatus,
        )

        return WiiiConnectPersistentStorageStatus(
            enabled=True,
            persistent=True,
            connection_table_ready=True,
            audit_ledger_ready=True,
            reason="ready",
        )

    def list_connection_records(self, **kwargs: Any) -> tuple[Any, ...]:
        self.list_calls.append(dict(kwargs))
        return self.records

    def append_audit_record(
        self,
        record: Any,
        *,
        organization_id: str,
        user_id: str,
    ) -> bool:
        self.audit_records.append((record, organization_id, user_id))
        return True


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
        RAW_ARGUMENT_MARKER: "<redacted-argument-marker>",
        RAW_SECRET_MARKER: "<redacted-sensitive-field>",
        "Bearer ": "<redacted-sensitive-field> ",
        "local-fake-key": "<redacted-sensitive-field>",
        "provider-managed://": "<redacted-connection-ref>",
        "ca_wiii_connect_action_replay": "<redacted-connection-id>",
        "connected_account_id": "<redacted-sensitive-field>",
        "connection_ref": "<redacted-sensitive-field>",
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
            getattr(args, "prompt", None),
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
        "error_code": "wiii_connect_action_replay_failed",
        "error_message": _redact_failure_text(exc, args),
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_prompt_included": False,
            "raw_request_identifiers_included": False,
            "provider_arguments_included": False,
            "provider_payload_included": False,
            "raw_audit_metadata_included": False,
            "opaque_connection_identifier_included": False,
            "final_answer_text_included": False,
            "raw_secret_included": False,
            "failure_error_redacted": True,
        },
    }


def _require_live_run(args: argparse.Namespace) -> None:
    if not args.allow_run:
        raise SystemExit("--allow-run is required; this probe imports live Wiii runtime code")
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to run the Wiii Connect action replay probe")

    from app.core.config import settings

    if settings.environment == "production" and not args.allow_production:
        raise SystemExit("Refusing to run against production without --allow-production")


def _fake_composio_config() -> Any:
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )

    return WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key="local-fake-key",
        api_key_present=True,
        auth_config_by_provider={"gmail": "authcfg_gmail"},
        readonly_execute_enabled=True,
        readonly_action_allowlist_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )


def _connected_gmail_record() -> Any:
    from app.engine.wiii_connect import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        WiiiConnectVaultSecretRef,
    )

    return WiiiConnectConnectionRecordV1(
        connection_id="ca_wiii_connect_action_replay",
        provider_slug="gmail",
        state="connected",
        scopes=WiiiConnectScopeGrant(read=True),
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug="gmail",
            connection_id="ca_wiii_connect_action_replay",
            vault_key_id="provider-managed://composio/ca_wiii_connect_action_replay",
        ),
    )


def _state_with_gmail_action_plan(args: argparse.Namespace) -> dict[str, Any]:
    from app.engine.multi_agent.external_app_action_runtime import (
        record_external_app_action_plan,
        resolve_external_app_action_plan,
    )

    state: dict[str, Any] = {
        "user_id": args.user_id,
        "organization_id": args.organization_id,
        "session_id": args.session_id,
        "request_id": args.request_id,
        "query": args.prompt,
        "context": {
            "user_role": "student",
            "request_id": args.request_id,
        },
    }
    plan = resolve_external_app_action_plan(
        query=args.prompt,
        state=state,
        ready_provider_slugs=("gmail",),
        action_allowlists_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
    )
    record_external_app_action_plan(state, plan)
    return state


@contextmanager
def _patched_provider_boundary(storage: _FakeStorage) -> Iterator[dict[str, Any]]:
    from app.engine.tools import wiii_connect_tools
    from app.engine.wiii_connect import backend_action_executor
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
    )

    originals = {
        "tool_config": wiii_connect_tools.build_composio_adapter_config,
        "storage": backend_action_executor.get_wiii_connect_persistent_storage,
        "schema": backend_action_executor.verify_composio_tool_schema,
        "execute": backend_action_executor.execute_composio_tool,
    }
    observed: dict[str, Any] = {"execute_argument_keys": (), "connected_account_seen": False}

    async def fake_verify_schema(**kwargs: Any) -> Any:
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            request_id=kwargs.get("request_id") or "",
            schema_present=True,
            argument_keys=("query", "max_results"),
            required_argument_keys=("query",),
        )

    async def fake_execute(**kwargs: Any) -> Any:
        arguments = kwargs.get("arguments")
        if isinstance(arguments, Mapping):
            observed["execute_argument_keys"] = tuple(sorted(str(key) for key in arguments))
        observed["connected_account_seen"] = bool(kwargs.get("connected_account_id"))
        return WiiiConnectComposioExecuteResult(
            ready=True,
            successful=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            request_id=kwargs.get("request_id") or "",
            status_code=200,
            data_keys=("messages",),
            log_id_present=True,
        )

    wiii_connect_tools.build_composio_adapter_config = _fake_composio_config
    backend_action_executor.get_wiii_connect_persistent_storage = lambda: storage
    backend_action_executor.verify_composio_tool_schema = fake_verify_schema
    backend_action_executor.execute_composio_tool = fake_execute
    try:
        yield observed
    finally:
        wiii_connect_tools.build_composio_adapter_config = originals["tool_config"]
        backend_action_executor.get_wiii_connect_persistent_storage = originals["storage"]
        backend_action_executor.verify_composio_tool_schema = originals["schema"]
        backend_action_executor.execute_composio_tool = originals["execute"]


def _metadata_from_state(state: Mapping[str, Any], key: str) -> dict[str, Any]:
    value = state.get(key)
    return dict(value) if isinstance(value, Mapping) else {}


def _gateway_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    gateway = payload.get("gateway")
    if not isinstance(gateway, Mapping):
        return {}
    scope = gateway.get("scope_policy")
    if not isinstance(scope, Mapping):
        scope = {}
    return {
        "version": gateway.get("version"),
        "status": gateway.get("status"),
        "reason": gateway.get("reason"),
        "connection_present": bool(gateway.get("connection_present")),
        "audit_persistent": bool(gateway.get("audit_persistent")),
        "scope_policy": {
            "version": scope.get("version"),
            "status": scope.get("status"),
            "reason": scope.get("reason"),
            "required_scopes": list(scope.get("required_scopes") or []),
            "required_scope_count": len(list(scope.get("required_scopes") or [])),
            "allowed_scopes": list(scope.get("allowed_scopes") or []),
            "allowed_scope_count": len(list(scope.get("allowed_scopes") or [])),
        },
    }


def _schema_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    schema = payload.get("schema")
    if not isinstance(schema, Mapping):
        return {}
    return {
        "status": schema.get("status"),
        "reason": schema.get("reason"),
        "schema_present": bool(schema.get("schema_present")),
        "argument_keys": list(schema.get("argument_keys") or []),
        "required_argument_keys": list(schema.get("required_argument_keys") or []),
        "hidden_argument_count": schema.get("hidden_argument_count"),
    }


def _execution_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    execution = payload.get("execution")
    if not isinstance(execution, Mapping):
        return {}
    return {
        "status": execution.get("status"),
        "reason": execution.get("reason"),
        "successful": bool(execution.get("successful")),
        "data_keys": list(execution.get("data_keys") or []),
        "data_key_count": len(list(execution.get("data_keys") or [])),
        "log_id_present": bool(execution.get("log_id_present")),
        "provider_payload_included": False,
    }


def _integration_worker_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    worker = data.get("integration_worker") if isinstance(data, Mapping) else None
    if not isinstance(worker, Mapping):
        return {}
    classification = worker.get("result_classification")
    argument_plan = worker.get("argument_plan")
    action_policy = worker.get("action_policy")
    return {
        "version": worker.get("version"),
        "delegate_version": worker.get("delegate_version"),
        "planner_version": worker.get("planner_version"),
        "worker_result_version": worker.get("worker_result_version"),
        "status": worker.get("status"),
        "reason": worker.get("reason"),
        "executor": worker.get("executor"),
        "provider_slug": worker.get("provider_slug"),
        "requested_provider_slug": worker.get("requested_provider_slug"),
        "allowed_provider_slugs": list(worker.get("allowed_provider_slugs") or []),
        "action_slug": worker.get("action_slug"),
        "selected_mutation": worker.get("selected_mutation"),
        "action_allowlist": list(worker.get("action_allowlist") or []),
        "prompt_present": bool(worker.get("prompt_present")),
        "stage_sequence": list(worker.get("stage_sequence") or []),
        "stage_sequence_ready": list(worker.get("stage_sequence") or [])
        == ["provider_gate", "action_policy", "ready"],
        "action_policy": {
            "reason": action_policy.get("reason")
            if isinstance(action_policy, Mapping)
            else None,
            "selected": bool(action_policy.get("selected"))
            if isinstance(action_policy, Mapping)
            else False,
        },
        "argument_plan": {
            "source": argument_plan.get("source") if isinstance(argument_plan, Mapping) else None,
            "argument_keys": list(argument_plan.get("argument_keys") or [])
            if isinstance(argument_plan, Mapping)
            else [],
            "argument_count": argument_plan.get("argument_count")
            if isinstance(argument_plan, Mapping)
            else None,
            "required_argument_keys_present": (
                isinstance(argument_plan, Mapping)
                and set(argument_plan.get("argument_keys") or []) == {"max_results", "query"}
            ),
        },
        "raw_prompt_included": False,
        "result_classification": {
            "version": classification.get("version")
            if isinstance(classification, Mapping)
            else None,
            "outcome": classification.get("outcome")
            if isinstance(classification, Mapping)
            else None,
            "status": classification.get("status")
            if isinstance(classification, Mapping)
            else None,
            "failed_stage": classification.get("failed_stage")
            if isinstance(classification, Mapping)
            else "",
        },
    }


def _audit_summary(storage: _FakeStorage) -> dict[str, Any]:
    stages: list[str] = []
    statuses: list[str] = []
    event_kinds: list[str] = []
    organization_hashes: list[str] = []
    user_hashes: list[str] = []
    for record, _organization_id, _user_id in storage.audit_records:
        metadata = record.to_public_metadata()
        event_kinds.append(str(metadata.get("event_kind") or ""))
        statuses.append(str(metadata.get("status") or ""))
        organization_hash = _hash(_organization_id)
        user_hash = _hash(_user_id)
        if organization_hash:
            organization_hashes.append(organization_hash)
        if user_hash:
            user_hashes.append(user_hash)
        record_metadata = metadata.get("metadata")
        if isinstance(record_metadata, Mapping):
            stage = str(record_metadata.get("stage") or "")
            if stage:
                stages.append(stage)
    unique_org_hashes = sorted(set(organization_hashes))
    unique_user_hashes = sorted(set(user_hashes))
    return {
        "record_count": len(storage.audit_records),
        "event_kinds": event_kinds,
        "statuses": statuses,
        "stages": stages,
        "execution_event_count": sum(1 for event in event_kinds if event == "execution"),
        "started_seen": "started" in statuses,
        "succeeded_seen": "succeeded" in statuses,
        "execute_stage_seen": "execute" in stages,
        "execute_result_stage_seen": "execute_result" in stages,
        "organization_hash_count": len(unique_org_hashes),
        "user_hash_count": len(unique_user_hashes),
        "all_records_org_scoped": len(unique_org_hashes) == 1,
        "all_records_user_scoped": len(unique_user_hashes) == 1,
        "raw_metadata_included": False,
    }


def _connection_lookup_summary(storage: _FakeStorage) -> dict[str, Any]:
    first = storage.list_calls[0] if storage.list_calls else {}
    org_hash = _hash(first.get("organization_id"))
    user_hash = _hash(first.get("user_id"))
    return {
        "list_call_count": len(storage.list_calls),
        "organization_id_hash_present": bool(org_hash),
        "user_id_hash_present": bool(user_hash),
        "provider_slug": first.get("provider_slug"),
        "provider_scope_matches": first.get("provider_slug") == "gmail",
        "record_count": len(storage.records),
        "raw_connection_identifier_included": False,
    }


def _assert_probe_summary(summary: dict[str, Any]) -> None:
    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    forbidden = (
        RAW_ARGUMENT_MARKER,
        RAW_SECRET_MARKER,
        "local-fake-key",
        "provider-managed://",
        "ca_wiii_connect_action_replay",
        "connected_account_id",
        "connection_ref",
        "api_key",
        "access_token",
        "authorization",
    )
    leaked = [token for token in forbidden if token.casefold() in rendered.casefold()]
    if leaked:
        raise RuntimeError(f"Wiii Connect action replay leaked forbidden data: {leaked}")

    if summary.get("status") != "pass":
        raise RuntimeError("Probe summary did not pass")
    if summary.get("runtime", {}).get("path") != "external_app_action":
        raise RuntimeError("Probe did not record external_app_action path")
    if summary.get("runtime", {}).get("plan", {}).get("status") != "ready":
        raise RuntimeError("External app action plan was not ready")
    if summary.get("runtime", {}).get("integration_lane", {}).get("executor") != "provider_worker":
        raise RuntimeError("Integration lane did not select provider_worker")
    if summary.get("integration_worker", {}).get("result_classification", {}).get("outcome") != "completed":
        raise RuntimeError("Integration worker did not complete")
    if summary.get("backend_gateway", {}).get("status") != "allowed":
        raise RuntimeError("Backend gateway did not allow the replay action")
    if summary.get("backend_executor", {}).get("execution", {}).get("status") != "succeeded":
        raise RuntimeError("Backend executor did not produce a succeeded result")
    if summary.get("audits", {}).get("record_count", 0) < 2:
        raise RuntimeError("Expected at least two backend audit records")
    required_true_paths = (
        ("runtime", "request_id_hash_present"),
        ("runtime", "session_id_hash_present"),
        ("runtime", "organization_id_hash_present"),
        ("runtime", "user_id_hash_present"),
        ("runtime", "prompt_hash_present"),
        ("runtime", "plan", "provider_ready"),
        ("runtime", "integration_lane", "visible_tool_count_matches"),
        ("integration_worker", "stage_sequence_ready"),
        ("integration_worker", "argument_plan", "required_argument_keys_present"),
        ("backend_gateway", "connection_present"),
        ("backend_gateway", "audit_persistent"),
        ("backend_executor", "schema", "schema_present"),
        ("backend_executor", "execution", "successful"),
        ("backend_executor", "execution", "log_id_present"),
        ("backend_executor", "execution", "provider_payload_included"),
        ("backend_executor", "required_arguments_present"),
        ("connection_lookup", "organization_id_hash_present"),
        ("connection_lookup", "user_id_hash_present"),
        ("connection_lookup", "provider_scope_matches"),
        ("audits", "started_seen"),
        ("audits", "succeeded_seen"),
        ("audits", "execute_stage_seen"),
        ("audits", "execute_result_stage_seen"),
        ("audits", "all_records_org_scoped"),
        ("audits", "all_records_user_scoped"),
        ("final_answer", "raw_answer_included"),
    )
    for path in required_true_paths:
        current: Any = summary
        for key in path:
            current = current.get(key) if isinstance(current, Mapping) else None
        if path[-1] in {"provider_payload_included", "raw_answer_included"}:
            if current is not False:
                raise RuntimeError(f"Expected {'.'.join(path)} false")
        elif current is not True:
            raise RuntimeError(f"Expected {'.'.join(path)} true")

    if summary.get("integration_worker", {}).get("stage_sequence") != [
        "provider_gate",
        "action_policy",
        "ready",
    ]:
        raise RuntimeError("Integration worker stage sequence did not prove ready path")
    if summary.get("audits", {}).get("execution_event_count", 0) < 2:
        raise RuntimeError("Expected execution audit event count")
    privacy = summary.get("privacy", {})
    for key in (
        "raw_content_included",
        "raw_prompt_included",
        "raw_request_identifiers_included",
        "provider_arguments_included",
        "provider_payload_included",
        "raw_audit_metadata_included",
        "opaque_connection_identifier_included",
        "final_answer_text_included",
    ):
        if privacy.get(key) is not False:
            raise RuntimeError(f"Privacy marker {key} must be false")


async def _run_wiii_connect_action_replay(args: argparse.Namespace) -> dict[str, Any]:
    from app.engine.multi_agent.external_app_action_runtime import (
        EXTERNAL_APP_ACTION_PLAN_STATE_KEY,
        external_app_action_final_answer,
    )
    from app.engine.multi_agent.external_app_integration_lane import (
        EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY,
    )
    from app.engine.tools import wiii_connect_tools
    from app.engine.tools.tool_capability_registry import (
        WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
    )

    storage = _FakeStorage((_connected_gmail_record(),))
    state = _state_with_gmail_action_plan(args)
    with _patched_provider_boundary(storage) as observed:
        result = await wiii_connect_tools.execute_wiii_connect_delegate_to_integration(
            state=state,
            provider_slug="gmail",
            prompt=args.prompt,
            arguments={
                "query": RAW_ARGUMENT_MARKER,
                "max_results": 1,
                "access_token": RAW_SECRET_MARKER,
            },
            allowed_provider_slugs=("gmail",),
            allowed_action_slugs_by_provider={"gmail": ("GMAIL_FETCH_EMAILS",)},
        )

    final_answer = external_app_action_final_answer(
        [
            {
                "type": "result",
                "name": WIII_CONNECT_DELEGATE_TO_INTEGRATION_TOOL,
                "result": json.dumps(result, ensure_ascii=False),
            }
        ]
    )
    plan = _metadata_from_state(state, EXTERNAL_APP_ACTION_PLAN_STATE_KEY)
    lane = _metadata_from_state(state, EXTERNAL_APP_INTEGRATION_LANE_STATE_KEY)
    request_id_hash = _hash(args.request_id)
    session_id_hash = _hash(args.session_id)
    organization_id_hash = _hash(args.organization_id)
    user_id_hash = _hash(args.user_id)
    prompt_hash = _hash(args.prompt)
    visible_tool_names = list(lane.get("visible_tool_names") or [])
    observed_argument_keys = list(observed.get("execute_argument_keys") or [])
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "pass",
        "runtime": {
            "path": "external_app_action",
            "request_id_hash": request_id_hash,
            "request_id_hash_present": bool(request_id_hash),
            "session_id_hash": session_id_hash,
            "session_id_hash_present": bool(session_id_hash),
            "organization_id_hash": organization_id_hash,
            "organization_id_hash_present": bool(organization_id_hash),
            "user_id_hash": user_id_hash,
            "user_id_hash_present": bool(user_id_hash),
            "prompt_hash": prompt_hash,
            "prompt_hash_present": bool(prompt_hash),
            "raw_prompt_included": False,
            "plan": {
                "version": plan.get("version"),
                "status": plan.get("status"),
                "kind": plan.get("kind"),
                "provider_slug": plan.get("provider_slug"),
                "provider_ready": plan.get("provider_slug") == "gmail",
                "action_allowlists_by_provider": plan.get("action_allowlists_by_provider") or {},
                "action_allowlist_count": len(
                    (plan.get("action_allowlists_by_provider") or {}).get("gmail", [])
                )
                if isinstance(plan.get("action_allowlists_by_provider"), Mapping)
                else 0,
            },
            "integration_lane": {
                "version": lane.get("version"),
                "status": lane.get("status"),
                "executor": lane.get("executor"),
                "provider_slug": lane.get("provider_slug"),
                "visible_tool_names": visible_tool_names,
                "visible_tool_count": len(visible_tool_names),
                "visible_tool_count_matches": len(visible_tool_names) == 2,
            },
        },
        "integration_worker": _integration_worker_summary(result),
        "backend_gateway": _gateway_summary(result),
        "backend_executor": {
            "schema": _schema_summary(result),
            "execution": _execution_summary(result),
            "observed_execute_argument_keys": observed_argument_keys,
            "observed_execute_argument_count": len(observed_argument_keys),
            "required_arguments_present": "query" in observed_argument_keys,
            "connected_account_seen": bool(observed.get("connected_account_seen")),
        },
        "connection_lookup": _connection_lookup_summary(storage),
        "final_answer": {
            "source": "external_app_action_final_answer",
            "present": bool(final_answer),
            "char_count": len(final_answer),
            "raw_answer_included": False,
        },
        "audits": _audit_summary(storage),
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_prompt_included": False,
            "raw_request_identifiers_included": False,
            "provider_arguments_included": False,
            "provider_payload_included": False,
            "raw_audit_metadata_included": False,
            "opaque_connection_identifier_included": False,
            "final_answer_text_included": False,
        },
    }
    _assert_probe_summary(summary)
    return summary


async def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    _require_live_run(args)
    return await _run_wiii_connect_action_replay(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an opt-in Wiii Connect external-app action replay probe.",
    )
    parser.add_argument("--allow-run", action="store_true", help="Permit runtime imports and local replay.")
    parser.add_argument("--allow-production", action="store_true", help="Permit settings.environment=production.")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--organization-id", default=DEFAULT_ORG_ID)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--request-id", default=DEFAULT_REQUEST_ID)
    parser.add_argument(
        "--prompt",
        default="Wiii doc Gmail moi nhat tu giao vien giup toi",
    )
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
