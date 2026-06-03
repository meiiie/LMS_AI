"""Opt-in Wiii Connect Facebook post replay evidence.

This probe exercises the real FastAPI preview/apply endpoints for a Facebook
Page post with a local provider boundary. It proves that preview approval is
recorded in the durable operation ledger, the first apply consumes it, and a
second apply is blocked before provider execution.

Example:
    WIII_LIVE_WIII_CONNECT_FACEBOOK_POST_REPLAY=1 python scripts/probe_live_wiii_connect_facebook_post_replay.py --allow-run --out wiii-connect-facebook-post-replay-evidence.json
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

import httpx
from fastapi import FastAPI


SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from runtime_evidence_output import emit_json_payload  # noqa: E402


ENV_FLAG = "WIII_LIVE_WIII_CONNECT_FACEBOOK_POST_REPLAY"
SCHEMA_VERSION = "wiii.live_wiii_connect_facebook_post_replay.v1"
DEFAULT_ORG_ID = "live-wiii-connect-facebook-post-org"
DEFAULT_USER_ID = "live-wiii-connect-facebook-post-user"
DEFAULT_SESSION_ID = f"live-wiii-connect-facebook-post-{uuid.uuid4().hex[:12]}"
DEFAULT_REQUEST_ID = f"req-live-wiii-connect-facebook-post-{uuid.uuid4().hex[:12]}"
RAW_MESSAGE_MARKER = "WIII_CONNECT_FACEBOOK_POST_REPLAY_MARKER"
RAW_PAGE_ID = "9876543210"
FAKE_CONNECTION_ID = "ca_wiii_connect_facebook_post_replay"
FAKE_API_KEY = "local-facebook-post-fake-key"
FAKE_AUTH_CONFIG_ID = "authcfg_facebook_post_replay"
IDENTIFIER_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)


class _FakeStorage:
    def __init__(self, records: tuple[Any, ...]) -> None:
        self.records = records
        self.audit_records: list[tuple[Any, str, str]] = []
        self.operation_approvals: dict[str, dict[str, Any]] = {}
        self.operation_approval_appends = 0
        self.operation_approval_consumes = 0
        self.list_calls: list[dict[str, Any]] = []
        self.get_calls: list[dict[str, Any]] = []

    def status(self, *, probe_database: bool = True) -> Any:
        from app.engine.wiii_connect.persistent_storage import (
            WiiiConnectPersistentStorageStatus,
        )

        return WiiiConnectPersistentStorageStatus(
            enabled=True,
            persistent=True,
            connection_table_ready=True,
            audit_ledger_ready=True,
            operation_approval_table_ready=True,
            reason="ready",
        )

    def expire_stale_pending_connections(self, **kwargs: Any) -> int:
        return 0

    def list_connection_records(self, **kwargs: Any) -> tuple[Any, ...]:
        self.list_calls.append(dict(kwargs))
        return self.records

    def get_connection_record(self, **kwargs: Any) -> Any | None:
        self.get_calls.append(dict(kwargs))
        provider_slug = str(kwargs.get("provider_slug") or "")
        connection_id = str(kwargs.get("connection_id") or "")
        for record in self.records:
            if (
                getattr(record, "provider_slug", "") == provider_slug
                and getattr(record, "connection_id", "") == connection_id
            ):
                return record
        return None

    def append_audit_record(
        self,
        record: Any,
        *,
        organization_id: str,
        user_id: str,
    ) -> bool:
        serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
        _raise_if_contains_forbidden(serialized, allow_safe_field_names=True)
        self.audit_records.append((record, organization_id, user_id))
        return True

    def append_operation_approval_record(
        self,
        record: Any,
        *,
        organization_id: str,
        user_id: str,
    ) -> bool:
        serialized = json.dumps(record.to_public_metadata(), sort_keys=True)
        _raise_if_contains_forbidden(serialized, allow_safe_field_names=True)
        self.operation_approval_appends += 1
        self.operation_approvals[record.preview_evidence_id] = {
            "record": record,
            "consumed": False,
        }
        return True

    def consume_operation_approval_record(
        self,
        *,
        preview_evidence_id: str,
        request_fingerprint: str,
        organization_id: str,
        user_id: str,
        provider_slug: str,
        action_slug: str,
        consumed_at: datetime | None = None,
    ) -> Any:
        from app.engine.wiii_connect.operation_approval import (
            WiiiConnectOperationApprovalDecision,
        )

        self.operation_approval_consumes += 1
        stored = self.operation_approvals.get(preview_evidence_id)
        if stored is None:
            return WiiiConnectOperationApprovalDecision(
                status="blocked",
                reason="approval_record_missing",
                provider_slug=provider_slug,
                action_slug=action_slug,
                preview_evidence_id_present=bool(preview_evidence_id),
                request_fingerprint_present=bool(request_fingerprint),
                persistent=True,
                blocked=True,
            )
        if stored["consumed"]:
            return WiiiConnectOperationApprovalDecision(
                status="blocked",
                reason="approval_record_already_consumed",
                provider_slug=provider_slug,
                action_slug=action_slug,
                preview_evidence_id_present=True,
                request_fingerprint_present=True,
                persistent=True,
                blocked=True,
            )
        record = stored["record"]
        if record.request_fingerprint != request_fingerprint:
            return WiiiConnectOperationApprovalDecision(
                status="blocked",
                reason="approval_fingerprint_mismatch",
                provider_slug=provider_slug,
                action_slug=action_slug,
                preview_evidence_id_present=True,
                request_fingerprint_present=True,
                persistent=True,
                blocked=True,
            )
        stored["consumed"] = True
        return WiiiConnectOperationApprovalDecision(
            status="consumed",
            reason="approval_consumed",
            provider_slug=provider_slug,
            action_slug=action_slug,
            preview_evidence_id_present=True,
            request_fingerprint_present=True,
            persistent=True,
            consumed=True,
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
        RAW_MESSAGE_MARKER: "<redacted-message-marker>",
        RAW_PAGE_ID: "<redacted-page-id>",
        FAKE_CONNECTION_ID: "<redacted-connection-id>",
        FAKE_API_KEY: "<redacted-sensitive-field>",
        FAKE_AUTH_CONFIG_ID: "<redacted-sensitive-field>",
        "Bearer ": "<redacted-sensitive-field> ",
        "provider-managed://": "<redacted-connection-ref>",
        "wcn_": "<redacted-connection-ref>",
        "approval_token": "<redacted-sensitive-field>",
        "connected_account_id": "<redacted-sensitive-field>",
        "connection_ref": "<redacted-sensitive-field>",
        "page_id": "<redacted-sensitive-field>",
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
        "error_code": "wiii_connect_facebook_post_replay_failed",
        "error_message": _redact_failure_text(exc, args),
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "raw_marker_absent": True,
            "raw_request_identifiers_included": False,
            "provider_arguments_included": False,
            "provider_response_included": False,
            "request_payload_included": False,
            "approval_credential_included": False,
            "opaque_connection_identifier_included": False,
            "selected_page_value_included": False,
            "raw_secret_included": False,
            "failure_error_redacted": True,
        },
    }


def _forbidden_tokens() -> tuple[str, ...]:
    return (
        RAW_MESSAGE_MARKER,
        RAW_PAGE_ID,
        FAKE_CONNECTION_ID,
        FAKE_API_KEY,
        FAKE_AUTH_CONFIG_ID,
        "wcn_",
        "approval_token",
        "connected_account_id",
        "connection_ref",
        "page_id",
        "api_key",
        "access_token",
        "authorization",
    )


def _raise_if_contains_forbidden(
    rendered: str,
    *,
    allow_safe_field_names: bool = False,
) -> None:
    allowed_field_names = {"approval_token", "connection_ref", "page_id"}
    leaked = [
        token
        for token in _forbidden_tokens()
        if not (allow_safe_field_names and token in allowed_field_names)
        and token.casefold() in rendered.casefold()
    ]
    if leaked:
        raise RuntimeError(f"Wiii Connect Facebook post replay leaked forbidden data: {leaked}")


def _require_live_run(args: argparse.Namespace) -> None:
    if not args.allow_run:
        raise SystemExit("--allow-run is required; this probe imports live Wiii runtime code")
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to run the Wiii Connect Facebook post replay probe")

    from app.core.config import settings

    if settings.environment == "production" and not args.allow_production:
        raise SystemExit("Refusing to run against production without --allow-production")


def _fake_composio_config() -> Any:
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioAdapterConfig,
    )

    return WiiiConnectComposioAdapterConfig(
        enabled=True,
        api_key=FAKE_API_KEY,
        api_key_present=True,
        auth_config_by_provider={"facebook": FAKE_AUTH_CONFIG_ID},
        readonly_execute_enabled=True,
        readonly_action_allowlist_by_provider={
            "facebook": ("FACEBOOK_LIST_MANAGED_PAGES",),
        },
        apply_execute_enabled=True,
        apply_action_allowlist_by_provider={
            "facebook": (
                "FACEBOOK_CREATE_POST",
                "FACEBOOK_CREATE_PHOTO_POST",
            ),
        },
    )


def _connected_facebook_record() -> Any:
    from app.engine.wiii_connect import (
        WiiiConnectConnectionRecordV1,
        WiiiConnectScopeGrant,
        WiiiConnectVaultSecretRef,
    )

    return WiiiConnectConnectionRecordV1(
        connection_id=FAKE_CONNECTION_ID,
        provider_slug="facebook",
        state="connected",
        scopes=WiiiConnectScopeGrant(read=True, preview=True, apply=True),
        vault_ref=WiiiConnectVaultSecretRef(
            provider_slug="facebook",
            connection_id=FAKE_CONNECTION_ID,
            vault_key_id="provider-managed://composio/facebook-post-replay",
        ),
    )


def _build_authenticated_app(args: argparse.Namespace) -> FastAPI:
    from app.api.v1.wiii_connect import router as wiii_connect_router
    from app.core.security import require_auth
    from app.core.security_models import AuthenticatedUser

    app = FastAPI()
    app.include_router(wiii_connect_router)
    app.dependency_overrides[require_auth] = lambda: AuthenticatedUser(
        user_id=args.user_id,
        auth_method="probe",
        role="admin",
        organization_id=args.organization_id,
        session_id=args.session_id,
    )
    return app


@contextmanager
def _patched_provider_boundary(storage: _FakeStorage) -> Iterator[dict[str, Any]]:
    from app.api.v1 import wiii_connect as wiii_connect_api
    from app.engine.wiii_connect.composio_adapter import (
        WiiiConnectComposioExecuteResult,
        WiiiConnectComposioToolSchemaResult,
    )

    originals = {
        "config": wiii_connect_api.build_composio_adapter_config,
        "storage": wiii_connect_api.get_wiii_connect_persistent_storage,
        "schema": wiii_connect_api.verify_composio_tool_schema,
        "execute": wiii_connect_api.execute_composio_tool,
    }
    observed: dict[str, Any] = {
        "execute_call_count": 0,
        "execute_argument_count": 0,
        "required_arguments_present": False,
        "connected_account_seen": False,
    }

    async def fake_verify_schema(**kwargs: Any) -> Any:
        return WiiiConnectComposioToolSchemaResult(
            ready=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            request_id=kwargs.get("request_id") or "",
            schema_present=True,
            argument_keys=("page_id", "message", "published"),
            required_argument_keys=("page_id", "message"),
        )

    async def fake_execute(**kwargs: Any) -> Any:
        arguments = kwargs.get("arguments")
        if not isinstance(arguments, Mapping):
            arguments = {}
        observed["execute_call_count"] = int(observed["execute_call_count"]) + 1
        observed["execute_argument_count"] = len(arguments)
        observed["required_arguments_present"] = bool(
            arguments.get("page_id") == RAW_PAGE_ID
            and arguments.get("message") == RAW_MESSAGE_MARKER
            and arguments.get("published") is True
        )
        observed["connected_account_seen"] = kwargs.get("connected_account_id") == FAKE_CONNECTION_ID
        return WiiiConnectComposioExecuteResult(
            ready=True,
            successful=True,
            provider_slug=kwargs["provider_slug"],
            action_slug=kwargs["action_slug"],
            reason="ready",
            request_id=kwargs.get("request_id") or "",
            status_code=200,
            data_keys=("id",),
            log_id_present=True,
        )

    wiii_connect_api.build_composio_adapter_config = _fake_composio_config
    wiii_connect_api.get_wiii_connect_persistent_storage = lambda: storage
    wiii_connect_api.verify_composio_tool_schema = fake_verify_schema
    wiii_connect_api.execute_composio_tool = fake_execute
    try:
        yield observed
    finally:
        wiii_connect_api.build_composio_adapter_config = originals["config"]
        wiii_connect_api.get_wiii_connect_persistent_storage = originals["storage"]
        wiii_connect_api.verify_composio_tool_schema = originals["schema"]
        wiii_connect_api.execute_composio_tool = originals["execute"]


def _ledger_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    ledger = payload.get("approval_ledger")
    if not isinstance(ledger, Mapping):
        return {}
    metadata = ledger.get("metadata")
    if not isinstance(metadata, Mapping):
        metadata = {}
    return {
        "version": ledger.get("version"),
        "status": ledger.get("status"),
        "reason": ledger.get("reason"),
        "provider_slug": ledger.get("provider_slug"),
        "action_slug": ledger.get("action_slug"),
        "preview_evidence_id_present": bool(ledger.get("preview_evidence_id_present")),
        "request_fingerprint_present": bool(ledger.get("request_fingerprint_present")),
        "persistent": bool(ledger.get("persistent")),
        "consumed": bool(ledger.get("consumed")),
        "blocked": bool(ledger.get("blocked")),
        "metadata": {
            "selected_connection_present": bool(metadata.get("selected_connection_present")),
            "selected_page_present": bool(metadata.get("page_selected")),
            "message_length": int(metadata.get("message_length") or 0),
            "image_present": bool(metadata.get("image_present")),
        },
    }


def _gateway_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    gateway = payload.get("gateway")
    if not isinstance(gateway, Mapping):
        return {}
    scope_policy = gateway.get("scope_policy")
    if not isinstance(scope_policy, Mapping):
        scope_policy = {}
    return {
        "status": gateway.get("status"),
        "reason": gateway.get("reason"),
        "scope_policy": {
            "status": scope_policy.get("status"),
            "reason": scope_policy.get("reason"),
            "required_scopes": list(scope_policy.get("required_scopes") or []),
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
        "required_argument_count": len(schema.get("required_argument_keys") or []),
    }


def _execution_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    execution = payload.get("execution")
    if not isinstance(execution, Mapping):
        return {}
    return {
        "status": execution.get("status"),
        "reason": execution.get("reason"),
        "successful": bool(execution.get("successful")),
        "data_key_count": len(execution.get("data_keys") or []),
        "log_id_present": bool(execution.get("log_id_present")),
    }


def _audit_summary(storage: _FakeStorage) -> dict[str, Any]:
    stages: list[str] = []
    statuses: list[str] = []
    event_kinds: list[str] = []
    for record, _organization_id, _user_id in storage.audit_records:
        metadata = record.to_public_metadata()
        event_kinds.append(str(metadata.get("event_kind") or ""))
        statuses.append(str(metadata.get("status") or ""))
        record_metadata = metadata.get("metadata")
        if isinstance(record_metadata, Mapping):
            stage = str(record_metadata.get("stage") or "")
            if stage:
                stages.append(stage)
    return {
        "record_count": len(storage.audit_records),
        "event_kinds": event_kinds,
        "statuses": statuses,
        "stages": stages,
    }


def _storage_scope_summary(storage: _FakeStorage, args: argparse.Namespace) -> dict[str, Any]:
    calls = [*storage.list_calls, *storage.get_calls]
    return {
        "list_call_count": len(storage.list_calls),
        "get_call_count": len(storage.get_calls),
        "all_calls_org_scoped": all(
            call.get("organization_id") == args.organization_id for call in calls
        ),
        "all_calls_user_scoped": all(call.get("user_id") == args.user_id for call in calls),
        "facebook_provider_filter_seen": any(
            call.get("provider_slug") == "facebook" for call in calls
        ),
        "connection_lookup_count": sum(1 for call in calls if call.get("connection_id")),
        "raw_identifiers_included": False,
    }


def _assert_probe_summary(summary: dict[str, Any]) -> None:
    rendered = json.dumps(summary, ensure_ascii=False, sort_keys=True)
    _raise_if_contains_forbidden(rendered)

    if summary.get("status") != "pass":
        raise RuntimeError("Probe summary did not pass")
    if summary.get("provider") != "facebook":
        raise RuntimeError("Probe did not target Facebook")
    if summary.get("action") != "FACEBOOK_CREATE_POST":
        raise RuntimeError("Probe did not target Facebook post creation")
    runtime = summary.get("runtime", {})
    for key in (
        "request_id_hash_present",
        "session_id_hash_present",
        "organization_id_hash_present",
        "user_id_hash_present",
    ):
        if runtime.get(key) is not True:
            raise RuntimeError(f"Runtime hash marker {key} must be true")
    if runtime.get("raw_identifiers_included") is not False:
        raise RuntimeError("Runtime summary must not include raw identifiers")
    if summary.get("preview", {}).get("status") != "ready":
        raise RuntimeError("Preview was not ready")
    if summary.get("preview", {}).get("approval_ledger", {}).get("status") != "pending":
        raise RuntimeError("Preview did not record a pending approval")
    if summary.get("preview", {}).get("approval_credential_hash_present") is not True:
        raise RuntimeError("Preview did not record approval credential hash presence")
    if summary.get("preview", {}).get("preview_evidence_id_hash_present") is not True:
        raise RuntimeError("Preview did not record preview evidence hash presence")
    if summary.get("apply", {}).get("status") != "succeeded":
        raise RuntimeError("First apply did not succeed")
    if summary.get("apply", {}).get("approval_ledger", {}).get("status") != "consumed":
        raise RuntimeError("First apply did not consume approval")
    if summary.get("apply", {}).get("execution", {}).get("successful") is not True:
        raise RuntimeError("First apply did not record successful execution")
    if summary.get("replay", {}).get("status") != "blocked":
        raise RuntimeError("Replay apply was not blocked")
    if summary.get("replay", {}).get("reason") != "approval_record_already_consumed":
        raise RuntimeError("Replay apply was blocked for the wrong reason")
    if summary.get("replay", {}).get("approval_ledger", {}).get("status") != "blocked":
        raise RuntimeError("Replay did not record blocked approval ledger status")
    storage_scope = summary.get("storage_scope", {})
    if storage_scope.get("all_calls_org_scoped") is not True:
        raise RuntimeError("Storage calls were not organization scoped")
    if storage_scope.get("all_calls_user_scoped") is not True:
        raise RuntimeError("Storage calls were not user scoped")
    if summary.get("provider_execute_call_count") != 1:
        raise RuntimeError("Provider executor should be called exactly once")
    provider_executor = summary.get("provider_executor", {})
    for key in (
        "raw_arguments_included",
        "raw_response_included",
        "provider_account_identifier_included",
    ):
        if provider_executor.get(key) is not False:
            raise RuntimeError(f"Provider executor marker {key} must be false")
    if summary.get("operation_approval", {}).get("append_count") != 1:
        raise RuntimeError("Expected one operation approval append")
    if summary.get("operation_approval", {}).get("consume_count") != 2:
        raise RuntimeError("Expected two operation approval consume attempts")
    if summary.get("audits", {}).get("record_count", 0) < 3:
        raise RuntimeError("Expected at least three backend audit records")
    privacy = summary.get("privacy", {})
    for key in (
        "raw_content_included",
        "provider_arguments_included",
        "provider_response_included",
        "request_payload_included",
        "approval_credential_included",
        "opaque_connection_identifier_included",
        "selected_page_value_included",
        "audit_metadata_raw_content_included",
        "raw_request_identifiers_included",
    ):
        if privacy.get(key) is not False:
            raise RuntimeError(f"Privacy marker {key} must be false")


async def _run_wiii_connect_facebook_post_replay(args: argparse.Namespace) -> dict[str, Any]:
    from app.engine.wiii_connect.adapter_v1 import public_connection_ref

    storage = _FakeStorage((_connected_facebook_record(),))
    app = _build_authenticated_app(args)
    request_body = {
        "connection_ref": public_connection_ref("facebook", FAKE_CONNECTION_ID),
        "page_id": RAW_PAGE_ID,
        "message": RAW_MESSAGE_MARKER,
        "surface": "desktop",
    }
    with _patched_provider_boundary(storage) as observed:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            preview_response = await client.post(
                "/wiii-connect/providers/facebook/facebook-post/preview",
                json=request_body,
                headers={"X-Request-ID": args.request_id},
            )
            preview_payload = preview_response.json()
            apply_body = {
                **request_body,
                "approval_token": preview_payload.get("approval_token"),
                "preview_evidence_id": preview_payload.get("preview_evidence_id"),
            }
            apply_response = await client.post(
                "/wiii-connect/providers/facebook/facebook-post/apply",
                json=apply_body,
                headers={"X-Request-ID": args.request_id},
            )
            replay_response = await client.post(
                "/wiii-connect/providers/facebook/facebook-post/apply",
                json=apply_body,
                headers={"X-Request-ID": args.request_id},
            )

    preview_payload = preview_response.json()
    apply_payload = apply_response.json()
    replay_payload = replay_response.json()
    summary = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "status": "pass",
        "provider": "facebook",
        "action": "FACEBOOK_CREATE_POST",
        "runtime": {
            "path": "external_app_action",
            "mutation": "apply",
            "request_id_hash": _hash(args.request_id),
            "request_id_hash_present": bool(_hash(args.request_id)),
            "session_id_hash": _hash(args.session_id),
            "session_id_hash_present": bool(_hash(args.session_id)),
            "organization_id_hash": _hash(args.organization_id),
            "organization_id_hash_present": bool(_hash(args.organization_id)),
            "user_id_hash_present": bool(_hash(args.user_id)),
            "raw_identifiers_included": False,
        },
        "preview": {
            "status": preview_payload.get("status"),
            "reason": preview_payload.get("reason"),
            "http_status": preview_response.status_code,
            "preview_evidence_id_present": bool(preview_payload.get("preview_evidence_id")),
            "preview_evidence_id_hash_present": bool(
                _hash(preview_payload.get("preview_evidence_id"))
            ),
            "approval_credential_present": bool(preview_payload.get("approval_token")),
            "approval_credential_hash_present": bool(_hash(preview_payload.get("approval_token"))),
            "gateway": _gateway_summary(preview_payload),
            "approval_ledger": _ledger_summary(preview_payload),
            "raw_response_payload_included": False,
        },
        "apply": {
            "status": apply_payload.get("status"),
            "reason": apply_payload.get("reason"),
            "http_status": apply_response.status_code,
            "approval_credential_hash_present": bool(_hash(apply_body.get("approval_token"))),
            "preview_evidence_id_hash_present": bool(_hash(apply_body.get("preview_evidence_id"))),
            "gateway": _gateway_summary(apply_payload),
            "schema": _schema_summary(apply_payload),
            "execution": _execution_summary(apply_payload),
            "approval_ledger": _ledger_summary(apply_payload),
            "raw_response_payload_included": False,
        },
        "replay": {
            "status": replay_payload.get("status"),
            "reason": replay_payload.get("reason"),
            "http_status": replay_response.status_code,
            "gateway_evaluated": bool(replay_payload.get("gateway")),
            "schema_evaluated": bool(replay_payload.get("schema")),
            "execution_attempted": bool(replay_payload.get("execution")),
            "approval_ledger": _ledger_summary(replay_payload),
            "approval_credential_hash_present": bool(_hash(apply_body.get("approval_token"))),
            "preview_evidence_id_hash_present": bool(_hash(apply_body.get("preview_evidence_id"))),
            "raw_response_payload_included": False,
        },
        "operation_approval": {
            "append_count": storage.operation_approval_appends,
            "consume_count": storage.operation_approval_consumes,
            "persistent": True,
            "preview_evidence_id_hash_present": bool(_hash(preview_payload.get("preview_evidence_id"))),
        },
        "provider_executor": {
            "call_count": observed.get("execute_call_count"),
            "argument_count": observed.get("execute_argument_count"),
            "required_arguments_present": observed.get("required_arguments_present"),
            "connected_account_seen": observed.get("connected_account_seen"),
            "raw_arguments_included": False,
            "raw_response_included": False,
            "provider_account_identifier_included": False,
        },
        "provider_execute_call_count": observed.get("execute_call_count"),
        "storage_scope": _storage_scope_summary(storage, args),
        "audits": _audit_summary(storage),
        "privacy": {
            "identifier_strategy": "presence_hash_or_count_only",
            "raw_content_included": False,
            "provider_arguments_included": False,
            "provider_response_included": False,
            "request_payload_included": False,
            "approval_credential_included": False,
            "opaque_connection_identifier_included": False,
            "selected_page_value_included": False,
            "audit_metadata_raw_content_included": False,
            "raw_request_identifiers_included": False,
        },
    }
    _assert_probe_summary(summary)
    return summary


async def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    _require_live_run(args)
    return await _run_wiii_connect_facebook_post_replay(args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run an opt-in Wiii Connect Facebook post preview/apply replay probe.",
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
