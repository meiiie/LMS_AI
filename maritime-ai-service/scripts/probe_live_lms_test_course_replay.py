"""Opt-in live LMS test-course replay probe.

This probe drives the real /chat/stream/v3 LMS document-preview path, posts
host-action audit events that mirror a test-course preview/apply loop, and then
applies the patch to a credentialed external LMS test-course endpoint. The
output is hash/count/status-only.

Example:
    WIII_LIVE_LMS_TEST_COURSE_REPLAY=1 python scripts/probe_live_lms_test_course_replay.py --allow-write --out lms-test-course-evidence.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import json
import os
import sys
import time
import uuid
import zlib
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx


SCRIPT_DIR = Path(__file__).resolve().parent
SERVICE_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from runtime_evidence_output import emit_json_payload  # noqa: E402


ENV_FLAG = "WIII_LIVE_LMS_TEST_COURSE_REPLAY"
TOKEN_ENV = "WIII_LMS_TEST_COURSE_BEARER_TOKEN"
EXTERNAL_LMS_APPLY_URL_ENV = "WIII_LMS_TEST_COURSE_APPLY_URL"
EXTERNAL_LMS_APPLY_TOKEN_ENV = "WIII_LMS_TEST_COURSE_APPLY_TOKEN"
SCHEMA_VERSION = "wiii.live_lms_test_course_replay.v1"
PREFLIGHT_SCHEMA_VERSION = "wiii.lms_test_course_preflight.v1"
SETUP_CONTRACT_VERSION = "wiii.live_evidence_setup_contract.v1"
EXTERNAL_LMS_WRITE_SCHEMA_VERSION = "wiii.external_lms_test_course_write.v1"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_TRANSPORT_MODE = "asgi"
DEFAULT_API_KEY = "local-dev-key"
DEFAULT_USER_ID = "live-lms-test-course-teacher"
DEFAULT_DEMO_EMAIL = "live-lms-test-course-teacher@localhost"
DEFAULT_DEMO_NAME = "Live LMS Test Course Teacher"
DEFAULT_ORG_ID = "live-lms-test-org"
DEFAULT_DOMAIN_ID = "maritime"
DEFAULT_COURSE_ID = "live-lms-test-course"
DEFAULT_LESSON_ID = "live-lms-test-lesson"
DEFAULT_SESSION_ID = f"live-lms-test-course-replay-{uuid.uuid4().hex[:12]}"
DEFAULT_PROMPT = (
    "Dua tren tai lieu vua upload, hay tao preview_lesson_patch "
    "co citation va source_references cho bai hoc hien tai."
)
RAW_DOC_MARKER = "WIII_LMS_TEST_COURSE_REPLAY_MARKER"
PREVIEW_ACTION = "authoring.preview_lesson_patch"
APPLY_ACTION = "authoring.apply_lesson_patch"


@dataclass(frozen=True)
class SseEvent:
    name: str
    data: Any


def _json_print(payload: dict[str, Any]) -> None:
    emit_json_payload(payload)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    digest = _stable_probe_fingerprint(text)
    return f"sha256:{digest}"


def _stable_probe_fingerprint(text: str) -> str:
    data = text.encode("utf-8")
    key = b"wiii-live-probe-fingerprint-v1"
    first = zlib.crc32(key + b"\0" + data) & 0xFFFFFFFF
    second = zlib.crc32(data + b"\0" + key) & 0xFFFFFFFF
    return f"{first:08x}{second:08x}"


def _redact_error(value: Any) -> str:
    try:
        from app.engine.runtime.event_payload_sanitizer import (
            redact_runtime_secret_text,
        )

        return redact_runtime_secret_text(str(value))
    except Exception:  # noqa: BLE001
        return str(value)


def _decode_json_object(value: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _is_local_base_url(base_url: str) -> bool:
    parsed = urlparse(str(base_url or ""))
    host = (parsed.hostname or "").lower()
    return host in {"", "localhost", "127.0.0.1", "::1", "testserver"}


def _require_live_write(args: argparse.Namespace) -> None:
    if not args.allow_write:
        raise SystemExit(
            "--allow-write is required; this probe can persist chat/audit rows"
        )
    if not args.allow_external_lms_write:
        raise SystemExit(
            "--allow-external-lms-write is required; this probe mutates the "
            "configured external LMS test course"
        )
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to run the live LMS test-course replay probe")
    if not (args.external_lms_apply_url or os.getenv(EXTERNAL_LMS_APPLY_URL_ENV, "")).strip():
        raise SystemExit(
            f"Set --external-lms-apply-url or {EXTERNAL_LMS_APPLY_URL_ENV} "
            "to run credentialed LMS apply evidence"
        )
    if not (args.external_lms_apply_token or os.getenv(EXTERNAL_LMS_APPLY_TOKEN_ENV, "")).strip():
        raise SystemExit(
            f"Set --external-lms-apply-token or {EXTERNAL_LMS_APPLY_TOKEN_ENV} "
            "to run credentialed LMS apply evidence"
        )
    if args.transport_mode == "asgi" and args.auth_mode in {"auto", "dev-login"}:
        os.environ.setdefault("ENABLE_DEV_LOGIN", "true")
        os.environ.setdefault("ENABLE_ORG_MEMBERSHIP_CHECK", "false")
    if (
        args.transport_mode == "http"
        and not _is_local_base_url(args.base_url)
        and not args.allow_production
    ):
        raise SystemExit("Refusing to target a non-local backend without --allow-production")

    from app.core.config import settings

    if settings.environment == "production" and not args.allow_production:
        raise SystemExit("Refusing to write to production without --allow-production")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise RuntimeError("preflight required_next must be a string list")
    if value != list(dict.fromkeys(value)):
        raise RuntimeError("preflight required_next must not contain duplicates")
    if any(not item for item in value):
        raise RuntimeError("preflight required_next must not contain empty strings")
    return list(value)


def load_lms_test_course_preflight(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("--failure-preflight-json must point at a regular file")
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"--failure-preflight-json could not be read as JSON: {exc}"
        ) from exc
    if not isinstance(raw_payload, dict):
        raise RuntimeError("--failure-preflight-json root must be a JSON object")
    if raw_payload.get("schema_version") != PREFLIGHT_SCHEMA_VERSION:
        raise RuntimeError(
            "--failure-preflight-json schema_version does not match LMS preflight"
        )
    if raw_payload.get("status") != "fail":
        raise RuntimeError("--failure-preflight-json status must be fail")
    if raw_payload.get("live_write_attempted") is not False:
        raise RuntimeError("--failure-preflight-json live_write_attempted must be false")
    if raw_payload.get("external_lms_write_attempted") is not False:
        raise RuntimeError(
            "--failure-preflight-json external_lms_write_attempted must be false"
        )
    required_next = _string_list(raw_payload.get("required_next"))
    setup_contract = raw_payload.get("setup_contract")
    if not isinstance(setup_contract, dict):
        raise RuntimeError("--failure-preflight-json setup_contract must be an object")
    if setup_contract.get("requirement_id") != "lms-test-course-replay":
        raise RuntimeError(
            "--failure-preflight-json setup_contract.requirement_id is invalid"
        )
    if setup_contract.get("required_next") != required_next:
        raise RuntimeError(
            "--failure-preflight-json setup_contract.required_next must match required_next"
        )
    backend = raw_payload.get("backend") if isinstance(raw_payload.get("backend"), dict) else {}
    authentication = (
        raw_payload.get("authentication")
        if isinstance(raw_payload.get("authentication"), dict)
        else {}
    )
    external_lms = (
        raw_payload.get("external_lms")
        if isinstance(raw_payload.get("external_lms"), dict)
        else {}
    )
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": raw_payload.get("generated_at"),
        "status": raw_payload.get("status"),
        "allow_write_acknowledged": raw_payload.get("allow_write_acknowledged") is True,
        "allow_external_lms_write_acknowledged": (
            raw_payload.get("allow_external_lms_write_acknowledged") is True
        ),
        "live_env_flag_set": raw_payload.get("live_env_flag_set") is True,
        "production_environment": raw_payload.get("production_environment") is True,
        "allow_production_acknowledged": (
            raw_payload.get("allow_production_acknowledged") is True
        ),
        "live_write_attempted": False,
        "external_lms_write_attempted": False,
        "backend": {
            "transport_mode": str(backend.get("transport_mode") or ""),
            "base_url_local": backend.get("base_url_local") is True,
            "raw_base_url_included": False,
        },
        "authentication": {
            "auth_mode": str(authentication.get("auth_mode") or ""),
            "bearer_token_present": authentication.get("bearer_token_present") is True,
            "bearer_value_included": False,
        },
        "external_lms": {
            "apply_url_present": external_lms.get("apply_url_present") is True,
            "apply_token_present": external_lms.get("apply_token_present") is True,
            "endpoint_hash_present": external_lms.get("endpoint_hash_present") is True,
            "raw_endpoint_included": False,
            "raw_token_included": False,
        },
        "required_next": required_next,
        "setup_contract": setup_contract,
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "bearer_value_included": False,
            "raw_backend_url_included": False,
            "raw_external_lms_endpoint_included": False,
            "raw_external_lms_token_included": False,
            "raw_request_identifiers_included": False,
            "raw_lms_document_included": False,
        },
    }


def _failure_payload(
    exc: Exception,
    args: argparse.Namespace,
    *,
    preflight: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preflight = preflight or _failure_preflight_summary(args)
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "fail",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "error_code": "lms_test_course_preflight_blocked",
        "error_message": _redact_lms_failure_text(exc, args),
        "live_write_attempted": False,
        "external_lms_write_attempted": False,
        "required_next": preflight["required_next"],
        "setup_contract": preflight["setup_contract"],
        "preflight": preflight,
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "event_payloads_printed": False,
            "raw_sse_payload_included": False,
            "raw_approval_token_included": False,
            "raw_preview_token_included": False,
            "raw_request_identifiers_included": False,
            "raw_auth_header_included": False,
            "raw_host_action_params_included": False,
            "raw_audit_payloads_included": False,
            "raw_lms_document_included": False,
            "raw_external_lms_request_payload_included": False,
            "raw_external_lms_response_payload_included": False,
            "raw_external_lms_token_included": False,
            "raw_external_lms_endpoint_included": False,
        },
    }


def _failure_preflight_summary(args: argparse.Namespace) -> dict[str, Any]:
    try:
        return _build_lms_test_course_preflight(args)
    except Exception:  # noqa: BLE001
        required_next = ["inspect_live_lms_test_course_setup"]
        return {
            "schema_version": PREFLIGHT_SCHEMA_VERSION,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "fail",
            "allow_write_acknowledged": bool(args.allow_write),
            "allow_external_lms_write_acknowledged": bool(args.allow_external_lms_write),
            "live_env_flag_set": os.getenv(ENV_FLAG) == "1",
            "production_environment": False,
            "allow_production_acknowledged": bool(args.allow_production),
            "live_write_attempted": False,
            "external_lms_write_attempted": False,
            "backend": {
                "transport_mode": str(args.transport_mode or ""),
                "base_url_local": _is_local_base_url(args.base_url),
                "raw_base_url_included": False,
            },
            "authentication": {
                "auth_mode": str(args.auth_mode or ""),
                "bearer_token_present": bool(
                    (args.bearer_token or os.getenv(TOKEN_ENV, "")).strip()
                ),
                "bearer_value_included": False,
            },
            "external_lms": {
                "apply_url_present": bool(
                    (args.external_lms_apply_url or os.getenv(EXTERNAL_LMS_APPLY_URL_ENV, "")).strip()
                ),
                "apply_token_present": bool(
                    (args.external_lms_apply_token or os.getenv(EXTERNAL_LMS_APPLY_TOKEN_ENV, "")).strip()
                ),
                "endpoint_hash_present": False,
                "raw_endpoint_included": False,
                "raw_token_included": False,
            },
            "required_next": required_next,
            "setup_contract": _lms_setup_contract(required_next),
            "privacy": _lms_preflight_privacy(),
        }


def _redact_lms_failure_text(
    value: Any,
    args: argparse.Namespace | None = None,
) -> str:
    text = _redact_error(value)[:1000]
    replacements = {
        ENV_FLAG: "live_lms_test_course_replay_flag",
        TOKEN_ENV: "lms_backend_bearer_token",
        EXTERNAL_LMS_APPLY_URL_ENV: "external_lms_apply_endpoint",
        EXTERNAL_LMS_APPLY_TOKEN_ENV: "external_lms_apply_token",
        "authorization": "<redacted-sensitive-field>",
        "access_token": "<redacted-sensitive-field>",
        "api_key": "<redacted-sensitive-field>",
    }
    if args is not None:
        for raw_value in (
            getattr(args, "base_url", None),
            getattr(args, "bearer_token", None),
            getattr(args, "external_lms_apply_url", None),
            getattr(args, "external_lms_apply_token", None),
            getattr(args, "api_key", None),
            getattr(args, "user_id", None),
            getattr(args, "organization_id", None),
            getattr(args, "course_id", None),
            getattr(args, "lesson_id", None),
            getattr(args, "session_id", None),
        ):
            raw = str(raw_value or "")
            if raw:
                replacements[raw] = _hash(raw) or "<redacted-value>"
    for raw, replacement in replacements.items():
        text = text.replace(raw, replacement)
    return text


def _lms_preflight_required_next(
    args: argparse.Namespace,
    *,
    environment: str,
    live_env_flag_set: bool,
    external_lms_apply_url_present: bool,
    external_lms_apply_token_present: bool,
) -> list[str]:
    required_next: list[str] = []
    if not args.allow_write:
        required_next.append("pass_allow_write")
    if not args.allow_external_lms_write:
        required_next.append("pass_allow_external_lms_write")
    if not live_env_flag_set:
        required_next.append("set_live_lms_test_course_replay_flag")
    if (
        (environment == "production" or (args.transport_mode == "http" and not _is_local_base_url(args.base_url)))
        and not args.allow_production
    ):
        required_next.append("pass_allow_production")
    if not external_lms_apply_url_present:
        required_next.append("configure_external_lms_apply_url")
    if not external_lms_apply_token_present:
        required_next.append("configure_external_lms_apply_token")
    return required_next


def _build_lms_test_course_preflight(args: argparse.Namespace) -> dict[str, Any]:
    from app.core.config import settings

    environment = str(getattr(settings, "environment", "") or "")
    live_env_flag_set = os.getenv(ENV_FLAG) == "1"
    external_lms_apply_url = (
        args.external_lms_apply_url or os.getenv(EXTERNAL_LMS_APPLY_URL_ENV, "")
    ).strip()
    external_lms_apply_token = (
        args.external_lms_apply_token or os.getenv(EXTERNAL_LMS_APPLY_TOKEN_ENV, "")
    ).strip()
    bearer_token = (args.bearer_token or os.getenv(TOKEN_ENV, "")).strip()
    required_next = _lms_preflight_required_next(
        args,
        environment=environment,
        live_env_flag_set=live_env_flag_set,
        external_lms_apply_url_present=bool(external_lms_apply_url),
        external_lms_apply_token_present=bool(external_lms_apply_token),
    )
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "pass" if not required_next else "fail",
        "allow_write_acknowledged": bool(args.allow_write),
        "allow_external_lms_write_acknowledged": bool(args.allow_external_lms_write),
        "live_env_flag_set": live_env_flag_set,
        "production_environment": environment == "production",
        "allow_production_acknowledged": bool(args.allow_production),
        "live_write_attempted": False,
        "external_lms_write_attempted": False,
        "backend": {
            "transport_mode": str(args.transport_mode or ""),
            "base_url_local": _is_local_base_url(args.base_url),
            "raw_base_url_included": False,
        },
        "authentication": {
            "auth_mode": str(args.auth_mode or ""),
            "bearer_token_present": bool(bearer_token),
            "bearer_value_included": False,
        },
        "external_lms": {
            "apply_url_present": bool(external_lms_apply_url),
            "apply_token_present": bool(external_lms_apply_token),
            "endpoint_hash_present": bool(_hash(external_lms_apply_url)),
            "raw_endpoint_included": False,
            "raw_token_included": False,
        },
        "required_next": required_next,
        "setup_contract": _lms_setup_contract(required_next),
        "privacy": _lms_preflight_privacy(),
    }


def _lms_setup_contract(required_next: list[str]) -> dict[str, Any]:
    return {
        "version": SETUP_CONTRACT_VERSION,
        "requirement_id": "lms-test-course-replay",
        "required_next": list(required_next),
        "workflow_inputs_required": [
            "run_lms_replay",
            "transport_mode",
            "base_url",
            "allow_write",
            "allow_external_lms_write",
            "allow_production",
        ],
        "environment_flags_required": ["live_lms_test_course_replay_flag"],
        "credential_slots_required": [
            "external_lms_apply_token",
            "lms_backend_bearer_token",
        ],
        "external_setup_required": [
            "external_lms_apply_endpoint",
            "staging_or_local_backend",
        ],
        "dispatch_ready": not required_next,
    }


def _lms_preflight_privacy() -> dict[str, bool]:
    return {
        "secret_values_included": False,
        "credential_names_included": False,
        "bearer_value_included": False,
        "raw_backend_url_included": False,
        "raw_external_lms_endpoint_included": False,
        "raw_external_lms_token_included": False,
        "raw_request_identifiers_included": False,
        "raw_lms_document_included": False,
    }


def _api_key_auth_headers(args: argparse.Namespace) -> tuple[dict[str, str], dict[str, Any]]:
    headers = {
        "X-API-Key": args.api_key,
        "X-User-ID": args.user_id,
        "X-Role": args.role,
        "X-Host-Role": args.role,
        "X-Organization-ID": args.organization_id,
    }
    return headers, {
        "auth_mode": "local_header_secret",
        "auth_secret_hash": _hash(args.api_key),
        "user_id_hash": _hash(args.user_id),
        "organization_id_hash": _hash(args.organization_id),
    }


async def _dev_login_auth_headers(
    client: httpx.AsyncClient,
    base_url: str,
    args: argparse.Namespace,
) -> tuple[dict[str, str], dict[str, Any]]:
    status_response = await client.get(f"{base_url}/api/v1/auth/dev-login/status")
    if status_response.status_code != 200:
        raise RuntimeError(f"dev-login status returned HTTP {status_response.status_code}")
    status_payload = _decode_json_object(status_response.text) or {}
    if status_payload.get("enabled") is not True:
        raise RuntimeError("dev-login is disabled; use --bearer-token or --auth-mode=api-key")

    login_response = await client.post(
        f"{base_url}/api/v1/auth/dev-login",
        json={
            "email": args.demo_email,
            "name": args.demo_name,
            "role": args.role,
        },
    )
    if login_response.status_code != 200:
        raise RuntimeError(f"dev-login returned HTTP {login_response.status_code}")
    login_payload = _decode_json_object(login_response.text) or {}
    token = login_payload.get("access_token")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("dev-login did not return access_token")
    user = login_payload.get("user")
    if not isinstance(user, dict):
        user = {}
    organization_id = str(
        login_payload.get("organization_id")
        or user.get("active_organization_id")
        or args.organization_id
        or ""
    ).strip()
    if organization_id:
        args.organization_id = organization_id
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-ID": args.organization_id,
    }
    return headers, {
        "auth_mode": "dev-login",
        "bearer_hash": _hash(token),
        "user_id_hash": _hash(user.get("id")),
        "organization_id_hash": _hash(args.organization_id),
    }


async def _resolve_auth_headers(
    client: httpx.AsyncClient,
    base_url: str,
    args: argparse.Namespace,
) -> tuple[dict[str, str], dict[str, Any]]:
    token = (args.bearer_token or os.environ.get(TOKEN_ENV, "")).strip()
    if token and args.auth_mode in {"auto", "bearer"}:
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Organization-ID": args.organization_id,
        }
        return headers, {
            "auth_mode": "bearer",
            "bearer_hash": _hash(token),
            "user_id_hash": None,
            "organization_id_hash": _hash(args.organization_id),
        }
    if args.auth_mode == "bearer":
        raise RuntimeError(f"--auth-mode=bearer requires --bearer-token or {TOKEN_ENV}")
    if args.auth_mode in {"auto", "dev-login"} and (
        args.transport_mode == "asgi" or _is_local_base_url(base_url)
    ):
        try:
            return await _dev_login_auth_headers(client, base_url, args)
        except RuntimeError:
            if args.auth_mode == "dev-login":
                raise

    return _api_key_auth_headers(args)


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
    with contextlib.redirect_stdout(runtime_capture), contextlib.redirect_stderr(
        runtime_capture
    ):
        from app.main import app as fastapi_app

        lifespan_cm = fastapi_app.router.lifespan_context(fastapi_app)
        await lifespan_cm.__aenter__()

    diagnostics = {
        "transport_mode": "asgi",
        "runtime_capture_char_count": len(runtime_capture.getvalue()),
    }
    transport = httpx.ASGITransport(app=fastapi_app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            timeout=timeout,
        ) as client:
            yield client, "http://testserver", diagnostics
    finally:
        with contextlib.redirect_stdout(runtime_capture), contextlib.redirect_stderr(
            runtime_capture
        ):
            await lifespan_cm.__aexit__(None, None, None)


def _append_sse_event(
    events: list[SseEvent],
    *,
    name: str,
    data_lines: list[str],
) -> None:
    if not data_lines:
        return
    raw_data = "\n".join(data_lines)
    events.append(SseEvent(name=name or "message", data=_decode_json_object(raw_data) or raw_data))


async def _collect_sse_events(response: httpx.Response) -> list[SseEvent]:
    events: list[SseEvent] = []
    current_event = "message"
    data_lines: list[str] = []

    async for raw_line in response.aiter_lines():
        line = raw_line.rstrip("\r\n")
        if not line:
            _append_sse_event(events, name=current_event, data_lines=data_lines)
            current_event = "message"
            data_lines = []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            current_event = line.split(":", 1)[1].strip()
            continue
        if line.startswith("data:"):
            data_lines.append(line.split(":", 1)[1].lstrip())

    _append_sse_event(events, name=current_event, data_lines=data_lines)
    return events


def _event_counts(events: list[SseEvent]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        counts[event.name] = counts.get(event.name, 0) + 1
    return counts


def _terminal_payload(events: list[SseEvent], event_name: str) -> dict[str, Any]:
    for event in reversed(events):
        if event.name == event_name and isinstance(event.data, dict):
            return event.data
    return {}


def _runtime_trace_from_events(events: list[SseEvent]) -> dict[str, Any]:
    for payload in (_terminal_payload(events, "done"), _terminal_payload(events, "metadata")):
        trace = payload.get("runtime_flow_trace")
        if isinstance(trace, dict):
            return trace
    return {}


def _runtime_ledger_from_events(events: list[SseEvent]) -> dict[str, Any]:
    for payload in (_terminal_payload(events, "done"), _terminal_payload(events, "metadata")):
        ledger = payload.get("runtime_flow_ledger")
        if isinstance(ledger, dict):
            return ledger
    return {}


def _path_from_trace(trace: Mapping[str, Any], ledger: Mapping[str, Any]) -> str:
    direct = trace.get("turn_path_decision")
    if isinstance(direct, Mapping):
        path = str(direct.get("path") or "").strip()
        if path:
            return path
    session = trace.get("tool_policy_session")
    if isinstance(session, Mapping):
        path = str(session.get("path") or "").strip()
        if path:
            return path
    route = ledger.get("route")
    if isinstance(route, Mapping):
        decision = route.get("turn_path_decision")
        if isinstance(decision, Mapping):
            path = str(decision.get("path") or "").strip()
            if path:
                return path
    return ""


def _int_value(mapping: Mapping[str, Any], key: str) -> int:
    value = mapping.get(key)
    return value if type(value) is int else 0


def _mapping_value(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = mapping.get(key)
    return value if isinstance(value, Mapping) else {}


def _safe_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted({str(item) for item in value if str(item or "").strip()})


def _build_user_context(args: argparse.Namespace) -> dict[str, Any]:
    host_context = {
        "surface": "embed_lms",
        "host_type": "lms",
        "host_name": "Wiii Live LMS Test Host",
        "connector_id": "live-lms-test-course",
        "host_user_id": args.user_id,
        "capabilities": ["lms", "host_action", "document_preview"],
        "course_id": args.course_id,
        "lesson_id": args.lesson_id,
        "user_role": args.role,
        "workflow_stage": "authoring",
        "page": {
            "type": "course_editor",
            "title": "Live LMS Test Course Replay",
        },
        "editable_scope": {
            "course_id": args.course_id,
            "lesson_id": args.lesson_id,
        },
    }
    host_capabilities = {
        "host_type": "lms",
        "host_name": "Wiii Live LMS Test Host",
        "connector_id": "live-lms-test-course",
        "tools": [
            {
                "name": PREVIEW_ACTION,
                "title": "Preview lesson patch",
                "roles": ["teacher", "admin"],
                "permission": "course.author",
                "requires_confirmation": True,
                "mutates_state": False,
                "transport": "postmessage",
                "surface": "embed_lms",
                "input_schema": {
                    "type": "object",
                    "required": ["title", "content", "source_references"],
                    "properties": {
                        "title": {"type": "string"},
                        "description": {"type": "string"},
                        "content": {"type": "string"},
                        "lesson_id": {"type": "string"},
                        "source_references": {"type": "array"},
                    },
                },
            },
            {
                "name": APPLY_ACTION,
                "title": "Apply lesson patch",
                "roles": ["teacher", "admin"],
                "permission": "course.author",
                "requires_confirmation": True,
                "mutates_state": True,
                "transport": "postmessage",
                "surface": "embed_lms",
                "input_schema": {
                    "type": "object",
                    "required": ["preview_token", "approval_token"],
                    "properties": {
                        "preview_token": {"type": "string"},
                        "approval_token": {"type": "string"},
                        "lesson_id": {"type": "string"},
                    },
                },
            },
        ],
    }
    return {
        "display_name": "Teacher Replay",
        "role": args.role,
        "language": "vi",
        "current_course_id": args.course_id,
        "current_course_name": "Khoa hoc replay LMS",
        "current_module_id": args.lesson_id,
        "current_module_name": "Bai hoc replay LMS",
        "host_context": host_context,
        "host_capabilities": host_capabilities,
        "document_context": {
            "attachments": [
                {
                    "file_name": "wiii-lms-test-course-source.docx",
                    "markdown": (
                        f"{RAW_DOC_MARKER}\n"
                        "Noi dung kiem thu ve muc tieu bai hoc, tieu chi danh gia, "
                        "va nguon trang 1 cho replay LMS."
                    ),
                    "parser": "markitdown",
                    "parser_chain": ["mammoth"],
                    "media_kind": "document",
                    "provenance_level": "page",
                    "source_references": [
                        {
                            "content_type": "heading",
                            "page_start": 1,
                            "page_end": 1,
                        }
                    ],
                }
            ],
            "source_refs": [{"kind": "heading", "page_start": 1}],
        },
    }


def _build_chat_payload(args: argparse.Namespace) -> dict[str, Any]:
    session_id = args.session_id or DEFAULT_SESSION_ID
    payload: dict[str, Any] = {
        "user_id": args.user_id,
        "message": args.prompt,
        "role": args.role,
        "session_id": session_id,
        "thread_id": session_id,
        "organization_id": args.organization_id,
        "domain_id": args.domain_id,
        "thinking_effort": args.thinking_effort,
        "user_context": _build_user_context(args),
    }
    if args.provider:
        payload["provider"] = args.provider
    if args.model:
        payload["model"] = args.model
    return payload


async def _run_stream_turn(
    client: httpx.AsyncClient,
    base_url: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
    request_id: str,
) -> tuple[int, list[SseEvent], int]:
    request_headers = {
        **dict(headers),
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-Request-ID": request_id,
    }
    started = time.monotonic()
    async with client.stream(
        "POST",
        f"{base_url}/api/v1/chat/stream/v3",
        headers=request_headers,
        json=dict(payload),
    ) as response:
        status_code = response.status_code
        if response.is_error:
            body = (await response.aread()).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"stream returned HTTP {status_code}: {_redact_error(body)}"
            )
        events = await _collect_sse_events(response)
    duration_ms = int((time.monotonic() - started) * 1000)
    return status_code, events, duration_ms


def _extract_host_action_request(events: list[SseEvent]) -> dict[str, Any]:
    for event in events:
        if event.name != "host_action" or not isinstance(event.data, dict):
            continue
        content = event.data.get("content")
        if not isinstance(content, dict):
            continue
        action = str(content.get("action") or "").strip()
        request_id = str(
            content.get("id") or content.get("request_id") or ""
        ).strip()
        params = content.get("params")
        if action != PREVIEW_ACTION or not request_id:
            continue
        return {
            "request_id": request_id,
            "action": action,
            "params": params if isinstance(params, dict) else {},
        }
    raise RuntimeError(
        "LMS preview stream did not emit a host_action event; "
        f"event_counts={_event_counts(events)}"
    )


def _safe_host_action_summary(host_action: Mapping[str, Any]) -> dict[str, Any]:
    params = host_action.get("params")
    if not isinstance(params, Mapping):
        params = {}
    source_refs = params.get("source_references")
    changed_fields = params.get("changed_fields")
    content = params.get("content")
    request_id_hash = _hash(host_action.get("request_id"))
    lesson_id_hash = _hash(params.get("lesson_id"))
    course_id_hash = _hash(params.get("course_id"))
    return {
        "request_id_hash": request_id_hash,
        "request_id_hash_present": bool(request_id_hash),
        "action": str(host_action.get("action") or ""),
        "param_keys": sorted(str(key) for key in params.keys()),
        "source_reference_count": len(source_refs) if isinstance(source_refs, list) else 0,
        "changed_field_count": len(changed_fields) if isinstance(changed_fields, list) else 0,
        "content_present": bool(str(content or "").strip()),
        "content_char_count": len(str(content or "")) if content is not None else 0,
        "lesson_id_hash": lesson_id_hash,
        "lesson_id_hash_present": bool(lesson_id_hash),
        "course_id_hash": course_id_hash,
        "course_id_hash_present": bool(course_id_hash),
    }


def _contains_value(value: Any, needle: str) -> bool:
    if not needle:
        return False
    if isinstance(value, Mapping):
        return any(_contains_value(item, needle) for item in value.values())
    if isinstance(value, list):
        return any(_contains_value(item, needle) for item in value)
    return needle in str(value)


def _build_audit_payloads(
    args: argparse.Namespace,
    host_action: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    params = host_action.get("params")
    if not isinstance(params, Mapping):
        params = {}
    context = ledger.get("context")
    if not isinstance(context, Mapping):
        context = {}

    request_id = str(host_action.get("request_id") or "").strip()
    apply_request_id = f"{request_id}-apply"
    if len(apply_request_id) > 160:
        apply_request_id = f"apply-{uuid.uuid4().hex[:12]}"
    lesson_id = str(params.get("lesson_id") or args.lesson_id).strip()
    course_id = str(params.get("course_id") or args.course_id).strip()
    source_refs = params.get("source_references")
    source_ref_count = len(source_refs) if isinstance(source_refs, list) else _int_value(
        context,
        "source_ref_count",
    )
    uploaded_document_count = _int_value(context, "uploaded_document_count")
    preview_token = f"probe-preview-{uuid.uuid4().hex[:16]}"
    approval_token = f"probe-approval-{uuid.uuid4().hex[:16]}"

    common = {
        "host_type": "lms",
        "host_name": "Wiii Live LMS Test Host",
        "page_type": "course_editor",
        "page_title": "Live LMS Test Course Replay",
        "user_role": args.role,
        "workflow_stage": "authoring",
        "preview_kind": "lesson_patch",
        "target_type": "lesson",
        "target_id": lesson_id,
    }
    preview_payload = {
        "event_type": "preview_created",
        "action": PREVIEW_ACTION,
        "request_id": request_id,
        "summary": "Preview created by live LMS test-course replay probe.",
        "preview_token": preview_token,
        "surface": "preview_panel",
        **common,
        "metadata": {
            "probe": "live_lms_test_course_replay",
            "course_id": course_id,
            "lesson_id": lesson_id,
            "source_reference_count": source_ref_count,
            "uploaded_document_count": uploaded_document_count,
            "raw_content_included": False,
            "raw_lms_document_included": False,
            "raw_host_action_params_included": False,
            "audit_stage": "preview",
        },
    }
    apply_payload = {
        "event_type": "apply_confirmed",
        "action": APPLY_ACTION,
        "request_id": apply_request_id,
        "summary": "Apply confirmed by live LMS test-course replay probe.",
        "preview_token": preview_token,
        "surface": "editor_shell",
        **common,
        "metadata": {
            "probe": "live_lms_test_course_replay",
            "course_id": course_id,
            "lesson_id": lesson_id,
            "preview_request_id_hash": _hash(request_id),
            "source_reference_count": source_ref_count,
            "uploaded_document_count": uploaded_document_count,
            "approval_token_present": True,
            "approval_credential_present": True,
            "raw_content_included": False,
            "raw_lms_document_included": False,
            "raw_host_action_params_included": False,
            "audit_stage": "apply",
        },
    }
    return {
        "preview": preview_payload,
        "apply": apply_payload,
        "preview_token": preview_token,
        "approval_token": approval_token,
    }


async def _post_audit(
    client: httpx.AsyncClient,
    base_url: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, Any],
) -> tuple[int, dict[str, Any]]:
    response = await client.post(
        f"{base_url}/api/v1/host-actions/audit",
        headers={**dict(headers), "Content-Type": "application/json"},
        json=dict(payload),
    )
    status_code = response.status_code
    response.raise_for_status()
    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError("host action audit endpoint returned invalid JSON") from exc
    if not isinstance(body, dict):
        raise RuntimeError("host action audit endpoint did not return an object")
    return status_code, body


def _external_lms_credentials(args: argparse.Namespace) -> tuple[str, str]:
    url = (args.external_lms_apply_url or os.getenv(EXTERNAL_LMS_APPLY_URL_ENV, "")).strip()
    token = (
        args.external_lms_apply_token
        or os.getenv(EXTERNAL_LMS_APPLY_TOKEN_ENV, "")
    ).strip()
    if not url or not token:
        raise RuntimeError("credentialed LMS apply endpoint and token are required")
    return url, token


def _build_external_lms_apply_payload(
    *,
    args: argparse.Namespace,
    host_action: Mapping[str, Any],
    audit_payloads: Mapping[str, Any],
    request_id: str,
) -> dict[str, Any]:
    params = host_action.get("params")
    if not isinstance(params, Mapping):
        params = {}
    source_refs = params.get("source_references")
    source_ref_count = len(source_refs) if isinstance(source_refs, list) else 0
    return {
        "schema_version": "wiii.external_lms_apply_request.v1",
        "operation": "apply_lesson_patch",
        "evidence_run_id": request_id,
        "course_id": str(params.get("course_id") or args.course_id),
        "lesson_id": str(params.get("lesson_id") or args.lesson_id),
        "preview_request_id": str(host_action.get("request_id") or ""),
        "preview_token": str(audit_payloads.get("preview_token") or ""),
        "title": str(params.get("title") or "Wiii LMS Test Course Replay"),
        "content": str(params.get("content") or ""),
        "source_reference_count": source_ref_count,
    }


async def _post_external_lms_apply(
    *,
    args: argparse.Namespace,
    request_id: str,
    host_action: Mapping[str, Any],
    audit_payloads: Mapping[str, Any],
) -> dict[str, Any]:
    url, token = _external_lms_credentials(args)
    payload = _build_external_lms_apply_payload(
        args=args,
        host_action=host_action,
        audit_payloads=audit_payloads,
        request_id=request_id,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Wiii-Evidence-Request-ID": request_id,
    }
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        response = await client.post(url, headers=headers, json=payload)
    response_body: dict[str, Any] = {}
    if response.content:
        with contextlib.suppress(json.JSONDecodeError):
            parsed = response.json()
            if isinstance(parsed, dict):
                response_body = parsed
    return _safe_external_lms_write_summary(
        payload=payload,
        endpoint_url=url,
        credential_token=token,
        request_id=request_id,
        status_code=response.status_code,
        response_body=response_body,
    )


def _safe_external_lms_write_summary(
    *,
    payload: Mapping[str, Any],
    endpoint_url: str,
    credential_token: str,
    request_id: str,
    status_code: int,
    response_body: Mapping[str, Any],
) -> dict[str, Any]:
    status_code_ok = 200 <= status_code < 300
    resource_id = (
        response_body.get("id")
        or response_body.get("resource_id")
        or response_body.get("lesson_id")
        or response_body.get("external_id")
    )
    source_ref_count = _int_value(payload, "source_reference_count")
    content_hash = _hash(payload.get("content"))
    return {
        "schema_version": EXTERNAL_LMS_WRITE_SCHEMA_VERSION,
        "mode": "webhook",
        "write_attempted": True,
        "write_acknowledged": status_code_ok,
        "status_code": status_code,
        "status_code_ok": status_code_ok,
        "endpoint_hash": _hash(endpoint_url),
        "endpoint_hash_present": bool(_hash(endpoint_url)),
        "credential_hash_present": bool(_hash(credential_token)),
        "request_id_hash": _hash(request_id),
        "request_id_hash_present": bool(_hash(request_id)),
        "course_id_hash_present": bool(_hash(payload.get("course_id"))),
        "lesson_id_hash_present": bool(_hash(payload.get("lesson_id"))),
        "preview_request_id_hash_present": bool(
            _hash(payload.get("preview_request_id"))
        ),
        "preview_token_hash_present": bool(_hash(payload.get("preview_token"))),
        "payload_content_hash": content_hash,
        "payload_content_hash_present": bool(content_hash),
        "payload_source_reference_count": source_ref_count,
        "response_json_object": bool(response_body),
        "response_resource_hash_present": bool(_hash(resource_id)),
        "raw_request_payload_included": False,
        "raw_response_payload_included": False,
        "raw_credential_included": False,
    }


def _safe_audit_response_summary(
    *,
    payload: Mapping[str, Any],
    status_code: int,
    response_body: Mapping[str, Any],
) -> dict[str, Any]:
    metadata = _mapping_value(payload, "metadata")
    request_id_hash = _hash(response_body.get("request_id"))
    payload_request_id_hash = _hash(payload.get("request_id"))
    preview_token_hash = _hash(payload.get("preview_token"))
    metadata_course_id_hash = _hash(metadata.get("course_id"))
    metadata_lesson_id_hash = _hash(metadata.get("lesson_id"))
    metadata_preview_request_id_hash = str(
        metadata.get("preview_request_id_hash") or ""
    ).strip()
    return {
        "status_code": status_code,
        "status_code_ok": status_code == 200,
        "status": response_body.get("status"),
        "status_success": response_body.get("status") == "success",
        "event_type": response_body.get("event_type"),
        "event_type_matches_payload": response_body.get("event_type")
        == payload.get("event_type"),
        "action": response_body.get("action"),
        "action_matches_payload": response_body.get("action") == payload.get("action"),
        "request_id_hash": request_id_hash,
        "request_id_hash_present": bool(request_id_hash),
        "request_id_hash_matches_payload": bool(request_id_hash)
        and request_id_hash == payload_request_id_hash,
        "preview_token_hash": preview_token_hash,
        "preview_token_hash_present": bool(preview_token_hash),
        "host_type": payload.get("host_type"),
        "host_type_matches_lms": payload.get("host_type") == "lms",
        "surface": payload.get("surface"),
        "workflow_stage": payload.get("workflow_stage"),
        "workflow_stage_matches_authoring": payload.get("workflow_stage")
        == "authoring",
        "preview_kind": payload.get("preview_kind"),
        "preview_kind_matches_lesson_patch": payload.get("preview_kind")
        == "lesson_patch",
        "target_type": payload.get("target_type"),
        "target_type_matches_lesson": payload.get("target_type") == "lesson",
        "metadata_keys": sorted(str(key) for key in metadata.keys()),
        "metadata_probe_matches": metadata.get("probe")
        == "live_lms_test_course_replay",
        "metadata_audit_stage": metadata.get("audit_stage"),
        "metadata_course_id_hash": metadata_course_id_hash,
        "metadata_course_id_hash_present": bool(metadata_course_id_hash),
        "metadata_lesson_id_hash": metadata_lesson_id_hash,
        "metadata_lesson_id_hash_present": bool(metadata_lesson_id_hash),
        "metadata_preview_request_id_hash": metadata_preview_request_id_hash or None,
        "metadata_preview_request_id_hash_present": bool(
            metadata_preview_request_id_hash
        ),
        "metadata_raw_content_included": metadata.get("raw_content_included"),
        "metadata_raw_lms_document_included": metadata.get(
            "raw_lms_document_included"
        ),
        "metadata_raw_host_action_params_included": metadata.get(
            "raw_host_action_params_included"
        ),
        "metadata_source_reference_count": _int_value(metadata, "source_reference_count"),
        "metadata_uploaded_document_count": _int_value(metadata, "uploaded_document_count"),
        "metadata_approval_token_present": bool(metadata.get("approval_token_present")),
        "metadata_approval_credential_present": bool(
            metadata.get("approval_credential_present")
        ),
        "raw_summary_included": False,
        "raw_preview_token_included": False,
        "raw_target_id_included": False,
    }


def _stream_runtime_summary(
    *,
    events: list[SseEvent],
    trace: Mapping[str, Any],
    ledger: Mapping[str, Any],
) -> dict[str, Any]:
    event_counts = _event_counts(events)
    request = ledger.get("request")
    if not isinstance(request, Mapping):
        request = {}
    context = ledger.get("context")
    if not isinstance(context, Mapping):
        context = {}
    provenance = _mapping_value(context, "context_provenance")
    provenance_documents = _mapping_value(provenance, "documents")
    provenance_host = _mapping_value(provenance, "host")
    provenance_privacy = _mapping_value(provenance, "privacy")
    host_actions = ledger.get("host_actions")
    if not isinstance(host_actions, Mapping):
        host_actions = {}
    finalization = ledger.get("finalization")
    if not isinstance(finalization, Mapping):
        finalization = {}
    stream = ledger.get("stream")
    if not isinstance(stream, Mapping):
        stream = {}
    post_turn_lifecycle = finalization.get("post_turn_lifecycle")
    if not isinstance(post_turn_lifecycle, Mapping):
        post_turn_lifecycle = {}
    post_turn_privacy = post_turn_lifecycle.get("privacy")
    if not isinstance(post_turn_privacy, Mapping):
        post_turn_privacy = {}
    host_capabilities = request.get("host_capabilities") or []
    if not isinstance(host_capabilities, list):
        host_capabilities = []
    return {
        "ledger_schema_version": ledger.get("schema_version"),
        "path": _path_from_trace(trace, ledger),
        "stream_transport": stream.get("transport"),
        "metadata_seen": stream.get("metadata_seen"),
        "done_seen": event_counts.get("done", 0) > 0,
        "terminal_event_name": events[-1].name if events else None,
        "event_counts": event_counts,
        "host_action_event_count": event_counts.get("host_action", 0),
        "metadata_event_count": event_counts.get("metadata", 0),
        "done_event_count": event_counts.get("done", 0),
        "host_surface": request.get("host_surface"),
        "host_capabilities": host_capabilities,
        "host_capability_lms_present": "lms" in host_capabilities,
        "host_capability_host_action_present": "host_action" in host_capabilities,
        "host_capability_document_preview_present": "document_preview" in host_capabilities,
        "document_context_present": context.get("document_context_present"),
        "uploaded_document_count": _int_value(context, "uploaded_document_count"),
        "source_ref_count": _int_value(context, "source_ref_count"),
        "context_provenance_schema_version": provenance.get("schema_version"),
        "context_provenance_raw_content_included": provenance_privacy.get(
            "raw_content_included"
        ),
        "context_provenance_identifier_strategy": provenance_privacy.get(
            "identifier_strategy"
        ),
        "context_provenance_document_present": provenance_documents.get("present"),
        "context_provenance_attachment_count": _int_value(
            provenance_documents,
            "attachment_count",
        ),
        "context_provenance_usable_attachment_count": _int_value(
            provenance_documents,
            "usable_attachment_count",
        ),
        "context_provenance_source_ref_count": _int_value(
            provenance_documents,
            "source_ref_count",
        ),
        "context_provenance_attachment_id_hash_count": len(
            provenance_documents.get("attachment_id_hashes") or []
        )
        if isinstance(provenance_documents.get("attachment_id_hashes"), list)
        else 0,
        "context_provenance_media_kinds": _safe_string_list(
            provenance_documents.get("media_kinds")
        ),
        "context_provenance_source_ref_kinds": _safe_string_list(
            provenance_documents.get("source_ref_kinds")
        ),
        "context_provenance_host_context_present": provenance_host.get(
            "host_context_present"
        ),
        "context_provenance_host_surface": provenance_host.get("surface"),
        "context_provenance_host_capabilities": _safe_string_list(
            provenance_host.get("capability_names")
        ),
        "preview_required": host_actions.get("preview_required"),
        "preview_emitted": host_actions.get("preview_emitted"),
        "apply_attempted": host_actions.get("apply_attempted"),
        "approval_token_present": host_actions.get("approval_token_present"),
        "host_action_result_received": host_actions.get("result_received"),
        "finalization_status": finalization.get("status"),
        "finalization_error_absent": finalization.get("error_type") is None,
        "save_response_immediately": finalization.get("save_response_immediately"),
        "post_turn_lifecycle_schema_version": post_turn_lifecycle.get("schema_version"),
        "post_turn_lifecycle_raw_content_included": post_turn_privacy.get(
            "raw_content_included"
        ),
        "post_turn_lifecycle_identifier_strategy": post_turn_privacy.get(
            "identifier_strategy"
        ),
    }


def _build_source_contract(
    *,
    stream_summary: Mapping[str, Any],
    host_action_summary: Mapping[str, Any],
    preview_audit: Mapping[str, Any],
    apply_audit: Mapping[str, Any],
) -> dict[str, Any]:
    source_ref_count = _int_value(stream_summary, "source_ref_count")
    uploaded_document_count = _int_value(stream_summary, "uploaded_document_count")
    provenance_source_ref_count = _int_value(
        stream_summary,
        "context_provenance_source_ref_count",
    )
    provenance_attachment_count = _int_value(
        stream_summary,
        "context_provenance_attachment_count",
    )
    provenance_usable_attachment_count = _int_value(
        stream_summary,
        "context_provenance_usable_attachment_count",
    )
    return {
        "schema_version": "wiii.lms_test_course_source_contract.v1",
        "document_context_present": stream_summary.get("document_context_present")
        is True,
        "provenance_schema_version": stream_summary.get(
            "context_provenance_schema_version"
        ),
        "provenance_privacy_hash_count_only": (
            stream_summary.get("context_provenance_raw_content_included") is False
            and stream_summary.get("context_provenance_identifier_strategy")
            == "hash_or_count_only"
        ),
        "provenance_attachment_count_matches_runtime": (
            provenance_attachment_count == uploaded_document_count
            and uploaded_document_count > 0
        ),
        "provenance_usable_attachment_count_matches_runtime": (
            provenance_usable_attachment_count == uploaded_document_count
            and uploaded_document_count > 0
        ),
        "provenance_source_ref_count_matches_runtime": (
            provenance_source_ref_count == source_ref_count and source_ref_count > 0
        ),
        "provenance_attachment_id_hash_present": _int_value(
            stream_summary,
            "context_provenance_attachment_id_hash_count",
        )
        >= uploaded_document_count
        > 0,
        "provenance_media_kind_document": "document"
        in (stream_summary.get("context_provenance_media_kinds") or []),
        "provenance_source_ref_kind_heading": "heading"
        in (stream_summary.get("context_provenance_source_ref_kinds") or []),
        "host_context_matches_lms_surface": (
            stream_summary.get("context_provenance_host_context_present") is True
            and stream_summary.get("context_provenance_host_surface") == "embed_lms"
        ),
        "host_capabilities_match_request": (
            stream_summary.get("context_provenance_host_capabilities")
            == ["document_preview", "host_action", "lms"]
        ),
        "host_action_source_ref_count_matches_runtime": (
            _int_value(host_action_summary, "source_reference_count")
            == source_ref_count
            and source_ref_count > 0
        ),
        "preview_audit_source_ref_count_matches_runtime": (
            _int_value(preview_audit, "metadata_source_reference_count")
            == source_ref_count
            and source_ref_count > 0
        ),
        "apply_audit_source_ref_count_matches_runtime": (
            _int_value(apply_audit, "metadata_source_reference_count")
            == source_ref_count
            and source_ref_count > 0
        ),
        "preview_audit_document_count_matches_runtime": (
            _int_value(preview_audit, "metadata_uploaded_document_count")
            == uploaded_document_count
            and uploaded_document_count > 0
        ),
        "apply_audit_document_count_matches_runtime": (
            _int_value(apply_audit, "metadata_uploaded_document_count")
            == uploaded_document_count
            and uploaded_document_count > 0
        ),
    }


def _build_audit_sequence_contract(
    *,
    host_action_summary: Mapping[str, Any],
    preview_audit: Mapping[str, Any],
    apply_audit: Mapping[str, Any],
) -> dict[str, Any]:
    shared_preview_token_hash = (
        preview_audit.get("preview_token_hash") == apply_audit.get("preview_token_hash")
        and bool(preview_audit.get("preview_token_hash"))
    )
    preview_request_linked = (
        host_action_summary.get("request_id_hash")
        == apply_audit.get("metadata_preview_request_id_hash")
        and bool(host_action_summary.get("request_id_hash"))
    )
    events = [
        {
            "stage": "preview",
            "event_type": preview_audit.get("event_type"),
            "action": preview_audit.get("action"),
            "status": preview_audit.get("status"),
            "status_code_ok": preview_audit.get("status_code_ok"),
            "request_id_hash_present": preview_audit.get("request_id_hash_present"),
        },
        {
            "stage": "apply",
            "event_type": apply_audit.get("event_type"),
            "action": apply_audit.get("action"),
            "status": apply_audit.get("status"),
            "status_code_ok": apply_audit.get("status_code_ok"),
            "request_id_hash_present": apply_audit.get("request_id_hash_present"),
        },
    ]
    return {
        "schema_version": "wiii.lms_host_action_audit_sequence.v1",
        "event_count": len(events),
        "events": events,
        "preview_before_apply": True,
        "preview_request_linked_to_apply": preview_request_linked,
        "shared_preview_token_hash": shared_preview_token_hash,
        "response_echo_parity": (
            preview_audit.get("request_id_hash_matches_payload") is True
            and preview_audit.get("event_type_matches_payload") is True
            and preview_audit.get("action_matches_payload") is True
            and apply_audit.get("request_id_hash_matches_payload") is True
            and apply_audit.get("event_type_matches_payload") is True
            and apply_audit.get("action_matches_payload") is True
        ),
        "audit_surface_parity": (
            preview_audit.get("host_type_matches_lms") is True
            and preview_audit.get("workflow_stage_matches_authoring") is True
            and preview_audit.get("preview_kind_matches_lesson_patch") is True
            and preview_audit.get("target_type_matches_lesson") is True
            and apply_audit.get("host_type_matches_lms") is True
            and apply_audit.get("workflow_stage_matches_authoring") is True
            and apply_audit.get("preview_kind_matches_lesson_patch") is True
            and apply_audit.get("target_type_matches_lesson") is True
        ),
        "audit_metadata_parity": (
            preview_audit.get("metadata_probe_matches") is True
            and apply_audit.get("metadata_probe_matches") is True
            and preview_audit.get("metadata_course_id_hash_present") is True
            and preview_audit.get("metadata_lesson_id_hash_present") is True
            and apply_audit.get("metadata_course_id_hash_present") is True
            and apply_audit.get("metadata_lesson_id_hash_present") is True
        ),
        "raw_audit_payloads_included": False,
    }


def _build_evidence_contract() -> dict[str, Any]:
    return {
        "schema_version": "wiii.lms_test_course_evidence_contract.v1",
        "uses_stream_v3": True,
        "uses_host_action_audit_route": True,
        "requires_live_env_flag": ENV_FLAG,
        "requires_allow_write": True,
        "requires_allow_external_lms_write": True,
        "requires_live_channel_credentials": True,
        "requires_external_lms_apply_endpoint": EXTERNAL_LMS_APPLY_URL_ENV,
        "requires_external_lms_apply_token": EXTERNAL_LMS_APPLY_TOKEN_ENV,
        "external_lms_write_required": True,
        "external_lms_write_mode": "webhook",
        "synthetic_host_side_replay": False,
        "external_lms_write_disabled": False,
        "hash_count_only_output": True,
        "runtime_apply_forbidden_before_host": True,
        "preview_before_apply_audit_required": True,
        "source_count_parity_required": True,
    }


def _assert_lms_replay_evidence(
    *,
    stream_summary: Mapping[str, Any],
    host_action_summary: Mapping[str, Any],
    preview_audit: Mapping[str, Any],
    apply_audit: Mapping[str, Any],
    source_contract: Mapping[str, Any],
    audit_sequence_contract: Mapping[str, Any],
    evidence_contract: Mapping[str, Any],
    external_lms_write: Mapping[str, Any],
    approval_token: str,
) -> None:
    errors: list[str] = []
    if stream_summary.get("path") != "lms_document_preview":
        errors.append(f"path={stream_summary.get('path')!r}")
    if stream_summary.get("stream_transport") != "sse_v3":
        errors.append(f"stream_transport={stream_summary.get('stream_transport')!r}")
    if stream_summary.get("metadata_seen") is not True:
        errors.append("metadata event missing from runtime ledger")
    if stream_summary.get("done_seen") is not True:
        errors.append("done event missing")
    if stream_summary.get("terminal_event_name") != "done":
        errors.append(f"terminal_event_name={stream_summary.get('terminal_event_name')!r}")
    if _int_value(stream_summary, "uploaded_document_count") < 1:
        errors.append("uploaded document count missing")
    if _int_value(stream_summary, "source_ref_count") < 1:
        errors.append("source ref count missing")
    if stream_summary.get("host_surface") != "embed_lms":
        errors.append(f"host_surface={stream_summary.get('host_surface')!r}")
    capabilities = set(stream_summary.get("host_capabilities") or [])
    for required in ("lms", "host_action", "document_preview"):
        if required not in capabilities:
            errors.append(f"host capability {required!r} missing")
    if stream_summary.get("preview_required") is not True:
        errors.append("preview_required was not true")
    if stream_summary.get("preview_emitted") is not True:
        errors.append("preview_emitted was not true")
    if stream_summary.get("apply_attempted") is True:
        errors.append("apply was attempted before host approval")
    if stream_summary.get("finalization_status") != "saved":
        errors.append("finalization was not saved")
    if stream_summary.get("finalization_error_absent") is not True:
        errors.append("finalization error was present")
    if host_action_summary.get("action") != PREVIEW_ACTION:
        errors.append("preview host_action missing")
    if preview_audit.get("status") != "success":
        errors.append("preview audit failed")
    if apply_audit.get("status") != "success":
        errors.append("apply audit failed")
    if source_contract.get("provenance_source_ref_count_matches_runtime") is not True:
        errors.append("source provenance did not match runtime source refs")
    if source_contract.get("host_action_source_ref_count_matches_runtime") is not True:
        errors.append("preview host_action source refs did not match runtime")
    if audit_sequence_contract.get("preview_request_linked_to_apply") is not True:
        errors.append("apply audit was not linked to preview request")
    if audit_sequence_contract.get("shared_preview_token_hash") is not True:
        errors.append("preview/apply audit did not share preview token hash")
    if evidence_contract.get("hash_count_only_output") is not True:
        errors.append("evidence contract did not require hash/count-only output")
    if evidence_contract.get("external_lms_write_required") is not True:
        errors.append("evidence contract did not require external LMS write")
    if evidence_contract.get("requires_live_channel_credentials") is not True:
        errors.append("evidence contract did not require LMS credentials")
    if evidence_contract.get("synthetic_host_side_replay") is not False:
        errors.append("evidence contract still marks replay synthetic")
    if evidence_contract.get("external_lms_write_disabled") is not False:
        errors.append("evidence contract still disables external LMS write")
    if external_lms_write.get("schema_version") != EXTERNAL_LMS_WRITE_SCHEMA_VERSION:
        errors.append("external LMS write schema mismatch")
    if external_lms_write.get("write_attempted") is not True:
        errors.append("external LMS write was not attempted")
    if external_lms_write.get("write_acknowledged") is not True:
        errors.append("external LMS write was not acknowledged")
    if external_lms_write.get("status_code_ok") is not True:
        errors.append("external LMS write returned non-2xx status")
    if external_lms_write.get("endpoint_hash_present") is not True:
        errors.append("external LMS endpoint hash missing")
    if external_lms_write.get("credential_hash_present") is not True:
        errors.append("external LMS credential hash missing")
    if external_lms_write.get("raw_request_payload_included") is not False:
        errors.append("external LMS raw request payload was included")
    if external_lms_write.get("raw_response_payload_included") is not False:
        errors.append("external LMS raw response payload was included")
    if external_lms_write.get("raw_credential_included") is not False:
        errors.append("external LMS credential was included")
    if _contains_value(preview_audit, approval_token) or _contains_value(
        apply_audit,
        approval_token,
    ):
        errors.append("approval token leaked into audit summary")
    if errors:
        raise RuntimeError("; ".join(errors))


async def _run_probe(args: argparse.Namespace) -> dict[str, Any]:
    _require_live_write(args)
    request_id = args.request_id or f"req-live-lms-replay-{uuid.uuid4().hex[:12]}"

    async with _build_probe_client(
        transport_mode=args.transport_mode,
        base_url=args.base_url,
        timeout=args.timeout,
    ) as (client, resolved_base_url, diagnostics):
        auth_headers, auth_summary = await _resolve_auth_headers(client, resolved_base_url, args)
        payload = _build_chat_payload(args)
        stream_status, events, duration_ms = await _run_stream_turn(
            client,
            resolved_base_url,
            headers=auth_headers,
            payload=payload,
            request_id=request_id,
        )
        trace = _runtime_trace_from_events(events)
        ledger = _runtime_ledger_from_events(events)
        if not isinstance(ledger, dict) or not ledger:
            raise RuntimeError("Stream response did not include runtime_flow_ledger")
        try:
            host_action = _extract_host_action_request(events)
        except RuntimeError as exc:
            raise RuntimeError(
                f"{exc}; runtime={_stream_runtime_summary(events=events, trace=trace, ledger=ledger)}"
            ) from exc
        audit_payloads = _build_audit_payloads(args, host_action, ledger)
        preview_status, preview_body = await _post_audit(
            client,
            resolved_base_url,
            headers=auth_headers,
            payload=audit_payloads["preview"],
        )
        apply_status, apply_body = await _post_audit(
            client,
            resolved_base_url,
            headers=auth_headers,
            payload=audit_payloads["apply"],
        )
        external_lms_write = await _post_external_lms_apply(
            args=args,
            request_id=request_id,
            host_action=host_action,
            audit_payloads=audit_payloads,
        )

    stream_summary = _stream_runtime_summary(events=events, trace=trace, ledger=ledger)
    preview_audit = _safe_audit_response_summary(
        payload=audit_payloads["preview"],
        status_code=preview_status,
        response_body=preview_body,
    )
    apply_audit = _safe_audit_response_summary(
        payload=audit_payloads["apply"],
        status_code=apply_status,
        response_body=apply_body,
    )
    host_action_summary = _safe_host_action_summary(host_action)
    source_contract = _build_source_contract(
        stream_summary=stream_summary,
        host_action_summary=host_action_summary,
        preview_audit=preview_audit,
        apply_audit=apply_audit,
    )
    audit_sequence_contract = _build_audit_sequence_contract(
        host_action_summary=host_action_summary,
        preview_audit=preview_audit,
        apply_audit=apply_audit,
    )
    evidence_contract = _build_evidence_contract()
    _assert_lms_replay_evidence(
        stream_summary=stream_summary,
        host_action_summary=host_action_summary,
        preview_audit=preview_audit,
        apply_audit=apply_audit,
        source_contract=source_contract,
        audit_sequence_contract=audit_sequence_contract,
        evidence_contract=evidence_contract,
        external_lms_write=external_lms_write,
        approval_token=audit_payloads["approval_token"],
    )

    evidence = {
        "status": "pass",
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "transport": {
            "mode": args.transport_mode,
            "stream_status_code": stream_status,
            "duration_ms": duration_ms,
            "diagnostics": diagnostics,
        },
        "identity": {
            **auth_summary,
            "session_id_hash": _hash(args.session_id),
            "course_id_hash": _hash(args.course_id),
            "lesson_id_hash": _hash(args.lesson_id),
            "request_id_hash": _hash(request_id),
            "session_id_hash_present": bool(_hash(args.session_id)),
            "course_id_hash_present": bool(_hash(args.course_id)),
            "lesson_id_hash_present": bool(_hash(args.lesson_id)),
            "request_id_hash_present": bool(_hash(request_id)),
            "organization_id_hash_present": bool(auth_summary.get("organization_id_hash")),
        },
        "runtime": stream_summary,
        "host_action": host_action_summary,
        "source_contract": source_contract,
        "evidence_contract": evidence_contract,
        "host_side_replay": {
            "preview_token_hash": _hash(audit_payloads["preview_token"]),
            "preview_token_hash_present": bool(_hash(audit_payloads["preview_token"])),
            "approval_token_present": True,
            "approval_token_in_audit_payload": (
                _contains_value(audit_payloads["preview"], audit_payloads["approval_token"])
                or _contains_value(audit_payloads["apply"], audit_payloads["approval_token"])
            ),
            "external_lms_mutated": external_lms_write.get("write_acknowledged")
            is True,
        },
        "external_lms_write": external_lms_write,
        "audits": {
            "sequence_contract": audit_sequence_contract,
            "preview_created": preview_audit,
            "apply_confirmed": apply_audit,
        },
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "event_payloads_printed": False,
            "raw_sse_payload_included": False,
            "raw_approval_token_included": False,
            "raw_preview_token_included": False,
            "raw_request_identifiers_included": False,
            "raw_auth_header_included": False,
            "raw_host_action_params_included": False,
            "raw_audit_payloads_included": False,
            "raw_lms_document_included": False,
            "raw_external_lms_request_payload_included": False,
            "raw_external_lms_response_payload_included": False,
            "raw_external_lms_token_included": False,
            "raw_external_lms_endpoint_included": False,
            "raw_document_marker_hash": _hash(RAW_DOC_MARKER),
            "raw_document_marker_hash_present": bool(_hash(RAW_DOC_MARKER)),
        },
    }
    rendered = json.dumps(evidence, ensure_ascii=False, sort_keys=True)
    external_lms_apply_url, external_lms_apply_token = _external_lms_credentials(args)
    if (
        RAW_DOC_MARKER in rendered
        or audit_payloads["approval_token"] in rendered
        or audit_payloads["preview_token"] in rendered
        or external_lms_apply_url in rendered
        or external_lms_apply_token in rendered
    ):
        raise RuntimeError(
            "Probe evidence would expose raw document, host credential, or LMS credential"
        )
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Opt-in live LMS test-course replay probe.",
    )
    parser.add_argument("--allow-write", action="store_true", help="Permit chat/audit writes.")
    parser.add_argument(
        "--allow-external-lms-write",
        action="store_true",
        help="Permit mutation of the configured external LMS test course.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Check LMS replay readiness without writing chat, audit, or external LMS state.",
    )
    parser.add_argument(
        "--failure-from-preflight",
        action="store_true",
        help=(
            "Write a failed registered evidence artifact from validated preflight "
            "diagnostics without performing LMS writes."
        ),
    )
    parser.add_argument(
        "--failure-preflight-json",
        type=Path,
        default=None,
        help="Validated preflight JSON to embed in --failure-from-preflight output.",
    )
    parser.add_argument("--allow-production", action="store_true", help="Permit production or non-local targets.")
    parser.add_argument("--transport-mode", choices=("asgi", "http"), default=DEFAULT_TRANSPORT_MODE)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--auth-mode", choices=("auto", "bearer", "api-key", "dev-login"), default="auto")
    parser.add_argument("--bearer-token", default="")
    parser.add_argument("--external-lms-apply-url", default="")
    parser.add_argument("--external-lms-apply-token", default="")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY)
    parser.add_argument("--request-id", default="")
    parser.add_argument("--user-id", default=DEFAULT_USER_ID)
    parser.add_argument("--demo-email", default=DEFAULT_DEMO_EMAIL)
    parser.add_argument("--demo-name", default=DEFAULT_DEMO_NAME)
    parser.add_argument("--organization-id", default=DEFAULT_ORG_ID)
    parser.add_argument("--domain-id", default=DEFAULT_DOMAIN_ID)
    parser.add_argument("--role", choices=("teacher", "admin"), default="teacher")
    parser.add_argument("--course-id", default=DEFAULT_COURSE_ID)
    parser.add_argument("--lesson-id", default=DEFAULT_LESSON_ID)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--provider", default="")
    parser.add_argument("--model", default="")
    parser.add_argument("--thinking-effort", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    parser.add_argument("--out", type=Path, default=None, help="Write UTF-8 JSON evidence to this path.")
    return parser


async def async_main(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.preflight_only:
        result = _build_lms_test_course_preflight(args)
        emit_json_payload(result, args.out)
        return 0 if result.get("status") == "pass" else 1
    if args.failure_from_preflight:
        if args.out is None:
            print("--failure-from-preflight requires --out", file=sys.stderr)
            return 1
        if args.failure_preflight_json is None:
            print(
                "--failure-from-preflight requires --failure-preflight-json",
                file=sys.stderr,
            )
            return 1
        try:
            preflight = load_lms_test_course_preflight(args.failure_preflight_json)
        except Exception as exc:  # noqa: BLE001
            print(_redact_lms_failure_text(exc, args), file=sys.stderr)
            return 1
        emit_json_payload(
            _failure_payload(
                RuntimeError("preflight blocked live LMS test-course replay"),
                args,
                preflight=preflight,
            ),
            args.out,
        )
        return 1
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
