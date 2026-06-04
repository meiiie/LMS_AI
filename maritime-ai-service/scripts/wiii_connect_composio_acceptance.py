#!/usr/bin/env python3
"""Live acceptance harness for Wiii Connect's Composio adapter.

The harness talks only to Wiii backend endpoints. It never calls Composio
directly and it redacts control-plane identifiers from normal output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from runtime_evidence_output import emit_json_payload  # noqa: E402


DEFAULT_BACKEND_URL = "http://localhost:8080"
DEFAULT_PROVIDER = "gmail"
DEFAULT_ACTION = "GMAIL_FETCH_EMAILS"
DEFAULT_ACTION_BY_PROVIDER = {
    "facebook": "FACEBOOK_LIST_MANAGED_PAGES",
    "gmail": "GMAIL_FETCH_EMAILS",
}
DEFAULT_DEMO_EMAIL = "dev@localhost"
DEFAULT_DEMO_NAME = "Dev User"
DEFAULT_DEMO_ROLE = "admin"
DEFAULT_EXPECTED_PLATFORM_ROLE = "platform_admin"
SCOPE_POLICY_VERSION = "wiii_connect_scope_policy.v1"
SCHEMA_VERSION = "wiii.live_wiii_connect_composio_acceptance.v1"
LEGACY_SCHEMA_VERSION = "wiii_connect_composio_acceptance_evidence.v1"
PREFLIGHT_SCHEMA_VERSION = "wiii.connect_composio_acceptance_preflight.v1"
SETUP_CONTRACT_VERSION = "wiii.live_evidence_setup_contract.v1"
ENV_FLAG = "WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE"
TOKEN_ENV = "WIII_ACCEPTANCE_BEARER_TOKEN"
TARGET_ENV = "WIII_ACCEPTANCE_TARGET_ENV"
COMMIT_SHA_ENV = "WIII_ACCEPTANCE_COMMIT_SHA"
PUBLIC_CONNECTION_REF_PREFIX = "wcn_"

SENSITIVE_EXACT_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "authorization_url",
    "code",
    "connected_account_id",
    "connection_id",
    "connection_ref",
    "credential",
    "password",
    "redirect_url",
    "refresh_token",
    "secret",
    "state",
    "token",
    "vault_key_id",
}
SENSITIVE_KEY_MARKERS = (
    "token",
    "secret",
    "password",
    "credential",
    "api_key",
    "authorization",
    "connected_account",
    "connection_id",
    "vault",
)


class AcceptanceFailure(RuntimeError):
    """Raised when the live acceptance contract is not satisfied."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> dict[str, Any]:
        return parse_json_object(self.text(), source=self.url)


def join_url(base_url: str, path: str) -> str:
    """Join a base URL and absolute path without adding dependencies."""

    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def parse_json_object(raw_text: str, *, source: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AcceptanceFailure(f"Invalid JSON from {source}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AcceptanceFailure(f"Expected JSON object from {source}")
    return payload


def parse_json_argument_object(raw_text: str) -> dict[str, Any]:
    if not raw_text.strip():
        return {}
    return parse_json_object(raw_text, source="--arguments-json")


def request_bytes(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 15.0,
) -> HttpResponse:
    request_headers = {
        "User-Agent": "wiii-connect-composio-acceptance/1.0",
        **(headers or {}),
    }
    body: bytes | None = None
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(
        url,
        data=body,
        headers=request_headers,
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResponse(
                status=response.status,
                headers=dict(response.headers.items()),
                body=response.read(),
                url=url,
            )
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        raise AcceptanceFailure(
            f"{method.upper()} {url} -> HTTP {exc.code}: "
            f"{json_for_log(body_text)}"
        ) from exc
    except urllib.error.URLError as exc:
        raise AcceptanceFailure(f"{method.upper()} {url} failed: {exc.reason}") from exc
    except (TimeoutError, socket.timeout) as exc:
        raise AcceptanceFailure(
            f"{method.upper()} {url} timed out after {timeout:.1f}s"
        ) from exc


def json_for_log(value: Any) -> str:
    return json.dumps(redact_for_log(value), ensure_ascii=False, sort_keys=True)


def redact_for_log(value: Any) -> Any:
    """Return a logging-safe projection without tokens or connection IDs."""

    if isinstance(value, dict):
        safe: dict[str, Any] = {}
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in SENSITIVE_EXACT_KEYS or any(
                marker in normalized for marker in SENSITIVE_KEY_MARKERS
            ):
                safe[str(key)] = "[redacted]"
            else:
                safe[str(key)] = redact_for_log(item)
        return safe
    if isinstance(value, list):
        return [redact_for_log(item) for item in value]
    if isinstance(value, tuple):
        return [redact_for_log(item) for item in value]
    if isinstance(value, str):
        if _looks_sensitive_string(value):
            return "[redacted]"
        return value
    return value


def is_public_connection_ref(value: Any) -> bool:
    return isinstance(value, str) and value.strip().startswith(
        PUBLIC_CONNECTION_REF_PREFIX,
    )


def opaque_ref(value: str) -> str:
    if not value:
        return "missing"
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def find_adapter(payload: dict[str, Any], provider_kind: str) -> dict[str, Any]:
    for adapter in payload.get("adapters", []):
        if isinstance(adapter, dict) and adapter.get("provider_kind") == provider_kind:
            return adapter
    raise AcceptanceFailure(f"Adapter kind {provider_kind!r} was not returned")


def find_provider(payload: dict[str, Any], provider_slug: str) -> dict[str, Any]:
    normalized = normalize_provider(provider_slug)
    for provider in payload.get("providers", []):
        if isinstance(provider, dict) and provider.get("slug") == normalized:
            return provider
    raise AcceptanceFailure(f"Provider {normalized!r} was not in the registry")


def find_action(payload: dict[str, Any], action_slug: str) -> dict[str, Any]:
    normalized = normalize_action(action_slug)
    for action in payload.get("actions", []):
        if isinstance(action, dict) and action.get("slug") == normalized:
            return action
    raise AcceptanceFailure(f"Action {normalized!r} was not in the curated catalog")


def first_connected_connection(payload: dict[str, Any]) -> dict[str, Any] | None:
    for connection in payload.get("connections", []):
        connection_ref = (
            connection.get("connection_ref") if isinstance(connection, dict) else None
        )
        if (
            isinstance(connection, dict)
            and connection.get("active") is True
            and connection.get("state") == "connected"
            and is_public_connection_ref(connection_ref)
        ):
            return connection
    return None


def activation_blocker_summary(payload: dict[str, Any]) -> str:
    """Return a compact, redacted summary of failed activation gates."""

    gates = payload.get("gates")
    if not isinstance(gates, list):
        return "gates_missing"
    blockers: list[str] = []
    for gate in gates:
        if not isinstance(gate, dict) or gate.get("ready") is True:
            continue
        key = _safe_report_text(gate.get("key") or "unknown")
        reason = _safe_report_text(gate.get("reason") or "blocked")
        blockers.append(f"{key}:{reason}")
    return ", ".join(blockers[:8]) or "none"


def activation_readiness_report_lines(payload: dict[str, Any]) -> list[str]:
    """Return a human-readable, redacted activation-readiness report."""

    provider = _safe_report_text(payload.get("provider_slug") or "unknown")
    status = _safe_report_text(payload.get("status") or "unknown")
    lines = [
        (
            f"provider={provider} status={status} "
            f"ready_to_connect={payload.get('ready_to_connect') is True} "
            f"ready_to_execute_readonly={payload.get('ready_to_execute_readonly') is True}"
        )
    ]
    gates = payload.get("gates")
    if not isinstance(gates, list):
        lines.append("blocked_gates=gates_missing")
        return lines

    blockers: list[str] = []
    for gate in gates:
        if not isinstance(gate, dict) or gate.get("ready") is True:
            continue
        key = _safe_report_text(gate.get("key") or "unknown")
        reason = _safe_report_text(gate.get("reason") or "blocked")
        required_next = gate.get("required_next")
        if isinstance(required_next, list):
            next_steps = ",".join(
                _safe_report_text(item) for item in required_next[:5]
            )
        else:
            next_steps = ""
        suffix = f" next={next_steps}" if next_steps else ""
        blockers.append(f"- {key}: {reason}{suffix}")
    if blockers:
        lines.append("blocked_gates:")
        lines.extend(blockers[:12])
    else:
        lines.append("blocked_gates=none")
    return lines


def print_activation_readiness_report(payload: dict[str, Any]) -> None:
    print("[REPORT] activation readiness")
    for line in activation_readiness_report_lines(payload):
        print(f"[REPORT] {line}")


def assert_activation_ready(
    payload: dict[str, Any],
    *,
    flag: str,
    label: str,
) -> None:
    """Fail closed unless one readiness flag is explicitly true."""

    if payload.get(flag) is True:
        return
    raise AcceptanceFailure(
        f"Activation readiness does not report {label}: "
        f"{flag}={payload.get(flag)!r} status={payload.get('status')!r} "
        f"blockers={activation_blocker_summary(payload)}"
    )


def assert_scope_policy_allowed(
    payload: dict[str, Any],
    *,
    label: str,
) -> str:
    """Require Wiii-owned scope policy evidence before provider execution."""

    gateway = payload.get("execution_gateway")
    if gateway is None:
        gateway = payload
    if not isinstance(gateway, dict):
        raise AcceptanceFailure(f"{label} omitted execution gateway evidence")
    scope_policy = gateway.get("scope_policy")
    if not isinstance(scope_policy, dict):
        raise AcceptanceFailure(f"{label} omitted scope_policy evidence")
    version = str(scope_policy.get("version") or "")
    if version != SCOPE_POLICY_VERSION:
        raise AcceptanceFailure(
            f"{label} scope_policy version mismatch: version={version!r}"
        )
    if scope_policy.get("status") != "allowed" or scope_policy.get("reason") != "allowed":
        raise AcceptanceFailure(
            f"{label} scope policy not allowed: "
            f"status={scope_policy.get('status')!r} reason={scope_policy.get('reason')!r}"
        )
    required_scopes = scope_policy.get("required_scopes")
    allowed_scopes = scope_policy.get("allowed_scopes")
    if not isinstance(required_scopes, list) or "read" not in required_scopes:
        raise AcceptanceFailure(
            f"{label} scope_policy missing required read scope: "
            f"required_scopes={required_scopes!r}"
        )
    if not isinstance(allowed_scopes, list) or "read" not in allowed_scopes:
        raise AcceptanceFailure(
            f"{label} scope_policy does not allow read scope: "
            f"allowed_scopes={allowed_scopes!r}"
        )
    return "scope_policy=allowed required_scopes=read"


def normalize_provider(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_")


def normalize_action(value: str) -> str:
    return str(value or "").strip().upper().replace("-", "_")


def _looks_sensitive_string(value: str) -> bool:
    text = value.strip()
    lowered = text.lower()
    if not text:
        return False
    if lowered.startswith(("bearer ", "sk-", "tp-")):
        return True
    if "access_token=" in lowered or "refresh_token=" in lowered:
        return True
    if (
        "wiii_state=" in lowered
        or "connected_account_id=" in lowered
        or "connection_ref=" in lowered
        or "connection_id=" in lowered
    ):
        return True
    return False


def _safe_report_text(value: Any) -> str:
    text = str(value or "").strip().replace(" ", "_")
    if not text:
        return "unknown"
    if _looks_sensitive_string(text):
        return "[redacted]"
    lowered = text.lower()
    if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
        return "[redacted]"
    return text[:160]


def _redact_acceptance_failure_text(
    value: Any,
    args: argparse.Namespace | None = None,
) -> str:
    text = str(value or "")[:1000]
    text = re.sub(r"\bBearer\s+[A-Za-z0-9._~+/=-]{6,}", "Bearer [redacted]", text)
    replacements = {
        ENV_FLAG: "live_composio_acceptance_flag",
        TOKEN_ENV: "acceptance_bearer_token",
        "authorization": "[redacted-sensitive-field]",
        "access_token": "[redacted-sensitive-field]",
        "refresh_token": "[redacted-sensitive-field]",
        "api_key": "[redacted-sensitive-field]",
        "connected_account_id": "[redacted-sensitive-field]",
        "connection_id": "[redacted-sensitive-field]",
        "connection_ref": "[redacted-sensitive-field]",
    }
    if args is not None:
        for raw_value in (
            getattr(args, "backend_url", None),
            getattr(args, "bearer_token", None),
            getattr(args, "org_id", None),
            getattr(args, "redirect_uri", None),
            getattr(args, "connection_ref", None),
            getattr(args, "arguments_json", None),
        ):
            raw = str(raw_value or "")
            if raw:
                replacements[raw] = opaque_ref(raw)
    for raw, replacement in replacements.items():
        text = re.sub(re.escape(raw), replacement, text, flags=re.IGNORECASE)
    return text


def check_status_key(value: Any) -> str:
    text = str(value or "").strip().lower()
    safe = "".join(char if char.isalnum() else "_" for char in text)
    return "_".join(part for part in safe.split("_") if part)[:80] or "unknown"


def _list_count(value: Any) -> int:
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return 0


def _scope_policy_summary(payload: dict[str, Any]) -> dict[str, Any]:
    gateway = payload.get("execution_gateway")
    source = gateway if isinstance(gateway, dict) else payload
    scope_policy = source.get("scope_policy") if isinstance(source, dict) else None
    if not isinstance(scope_policy, dict):
        return {
            "version": "",
            "status": "missing",
            "reason": "missing",
            "read_required": False,
            "read_allowed": False,
            "required_scope_count": 0,
            "allowed_scope_count": 0,
        }
    required_scopes = scope_policy.get("required_scopes")
    allowed_scopes = scope_policy.get("allowed_scopes")
    required = required_scopes if isinstance(required_scopes, list) else []
    allowed = allowed_scopes if isinstance(allowed_scopes, list) else []
    return {
        "version": str(scope_policy.get("version") or ""),
        "status": check_status_key(scope_policy.get("status") or ""),
        "reason": check_status_key(scope_policy.get("reason") or ""),
        "read_required": "read" in required,
        "read_allowed": "read" in allowed,
        "required_scope_count": len(required),
        "allowed_scope_count": len(allowed),
    }


def _schema_summary(schema: Any, *, supplied_argument_keys: list[str]) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {
            "status": "missing",
            "schema_present": False,
            "provider_slug": "",
            "action_slug": "",
            "argument_key_count": 0,
            "required_argument_key_count": 0,
            "required_argument_keys_present": False,
            "raw_schema_included": False,
        }
    argument_keys = schema.get("argument_keys")
    required_keys = schema.get("required_argument_keys")
    safe_argument_keys = argument_keys if isinstance(argument_keys, list) else []
    safe_required_keys = required_keys if isinstance(required_keys, list) else []
    supplied = {str(key) for key in supplied_argument_keys}
    required = {str(key) for key in safe_required_keys}
    return {
        "status": check_status_key(schema.get("status") or ""),
        "schema_present": schema.get("schema_present") is True,
        "provider_slug": normalize_provider(str(schema.get("provider_slug") or "")),
        "action_slug": normalize_action(str(schema.get("action_slug") or "")),
        "argument_key_count": len(safe_argument_keys),
        "required_argument_key_count": len(safe_required_keys),
        "required_argument_keys_present": required.issubset(supplied),
        "raw_schema_included": False,
    }


def _execution_summary(execution: Any) -> dict[str, Any]:
    if not isinstance(execution, dict):
        return {
            "status": "missing",
            "successful": False,
            "provider_slug": "",
            "action_slug": "",
            "status_code": 0,
            "data_key_count": 0,
            "error_present": False,
            "session_info_present": False,
            "log_id_present": False,
            "provider_response_included": False,
        }
    data_keys = execution.get("data_keys")
    return {
        "status": check_status_key(execution.get("status") or ""),
        "successful": execution.get("successful") is True,
        "provider_slug": normalize_provider(str(execution.get("provider_slug") or "")),
        "action_slug": normalize_action(str(execution.get("action_slug") or "")),
        "status_code": int(execution.get("status_code") or 0),
        "data_key_count": _list_count(data_keys),
        "error_present": execution.get("error_present") is True,
        "session_info_present": execution.get("session_info_present") is True,
        "log_id_present": execution.get("log_id_present") is True,
        "provider_response_included": False,
    }


def _backend_url_preflight(raw_url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(str(raw_url or ""))
    hostname = (parsed.hostname or "").strip().lower()
    valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
    placeholder = hostname in {"wiii.example.com", "example.com"}
    origin = f"{parsed.scheme}://{parsed.netloc}" if valid else ""
    return {
        "valid": valid,
        "placeholder": placeholder,
        "scheme": parsed.scheme if parsed.scheme in {"http", "https"} else "",
        "host_hash_present": bool(hostname),
        "origin_hash_present": bool(opaque_ref(origin)) if origin else False,
        "raw_backend_url_included": False,
    }


def _arguments_preflight(raw_value: str) -> dict[str, Any]:
    try:
        parsed = parse_json_argument_object(raw_value)
    except AcceptanceFailure:
        return {
            "valid_json_object": False,
            "argument_key_count": 0,
            "arguments_present": False,
            "raw_arguments_included": False,
        }
    return {
        "valid_json_object": True,
        "argument_key_count": len(parsed),
        "arguments_present": bool(parsed),
        "raw_arguments_included": False,
    }


def _preflight_required_next(
    args: argparse.Namespace,
    *,
    backend: dict[str, Any],
    auth: dict[str, Any],
    arguments: dict[str, Any],
    live_env_flag_set: bool,
) -> list[str]:
    required_next: list[str] = []
    if not getattr(args, "allow_live", False):
        required_next.append("pass_allow_live")
    if not live_env_flag_set:
        required_next.append("set_live_composio_acceptance_flag")
    if backend.get("valid") is not True or backend.get("placeholder") is True:
        required_next.append("configure_backend_url")
    if args.auth_mode == "bearer" and auth.get("bearer_token_present") is not True:
        required_next.append("configure_acceptance_bearer_token")
    if (
        args.execute_readonly
        or args.require_execution_ready
        or args.disconnect
    ) and not args.expect_connected:
        required_next.append("pass_expect_connected")
    if args.execute_readonly and not args.require_execution_ready:
        required_next.append("pass_require_execution_ready")
    if args.execute_readonly and arguments.get("valid_json_object") is not True:
        required_next.append("fix_arguments_json")
    return required_next


def build_composio_acceptance_preflight(args: argparse.Namespace) -> dict[str, Any]:
    env_token = os.environ.get(TOKEN_ENV, "")
    bearer_from_argument = bool(str(getattr(args, "bearer_token", "") or "").strip())
    bearer_from_environment = bool(env_token.strip())
    auth = {
        "mode": args.auth_mode,
        "bearer_token_present": (
            args.auth_mode != "dev-login"
            and (bearer_from_argument or bearer_from_environment)
        ),
        "bearer_source": (
            "argument"
            if bearer_from_argument
            else "environment"
            if bearer_from_environment and args.auth_mode != "dev-login"
            else "none"
        ),
        "dev_login_allowed_by_mode": args.auth_mode in {"auto", "dev-login"},
        "bearer_value_included": False,
        "bearer_env_name_included": False,
    }
    backend = _backend_url_preflight(args.backend_url)
    arguments = _arguments_preflight(str(getattr(args, "arguments_json", "{}") or "{}"))
    live_env_flag_set = os.getenv(ENV_FLAG) == "1"
    required_next = _preflight_required_next(
        args,
        backend=backend,
        auth=auth,
        arguments=arguments,
        live_env_flag_set=live_env_flag_set,
    )
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "pass" if not required_next else "fail",
        "requested_provider": normalize_provider(args.provider),
        "requested_action": normalize_action(args.action),
        "allow_live_acknowledged": bool(args.allow_live),
        "live_env_flag_set": live_env_flag_set,
        "live_backend_call_attempted": False,
        "provider_execution_attempted": False,
        "backend": backend,
        "authentication": auth,
        "flags": {
            "expect_connected": bool(args.expect_connected),
            "require_execution_ready": bool(args.require_execution_ready),
            "execute_readonly": bool(args.execute_readonly),
            "skip_connect_link": bool(args.skip_connect_link),
            "explicit_connection_selection_present": bool(args.connection_ref),
        },
        "arguments": arguments,
        "required_next": required_next,
        "setup_contract": composio_setup_contract(args, required_next),
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "bearer_value_included": False,
            "bearer_env_name_included": False,
            "raw_backend_url_included": False,
            "raw_connection_selection_included": False,
            "raw_arguments_included": False,
            "provider_payload_included": False,
            "provider_response_included": False,
        },
    }


def safe_composio_preflight_summary(args: argparse.Namespace) -> dict[str, Any]:
    preflight = build_composio_acceptance_preflight(args)
    flags = preflight.get("flags") if isinstance(preflight.get("flags"), dict) else {}
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": preflight.get("generated_at"),
        "status": preflight.get("status"),
        "requested_provider": preflight.get("requested_provider"),
        "requested_action": preflight.get("requested_action"),
        "allow_live_acknowledged": preflight.get("allow_live_acknowledged"),
        "live_env_flag_set": preflight.get("live_env_flag_set"),
        "live_backend_call_attempted": False,
        "provider_execution_attempted": False,
        "backend": preflight.get("backend"),
        "authentication": preflight.get("authentication"),
        "flags": {
            "expect_connected": flags.get("expect_connected") is True,
            "require_execution_ready": flags.get("require_execution_ready") is True,
            "execute_readonly": flags.get("execute_readonly") is True,
            "skip_connect_link": flags.get("skip_connect_link") is True,
            "explicit_connection_selection_present": flags.get(
                "explicit_connection_selection_present"
            )
            is True,
        },
        "arguments": preflight.get("arguments"),
        "required_next": preflight.get("required_next")
        if isinstance(preflight.get("required_next"), list)
        else [],
        "setup_contract": preflight.get("setup_contract")
        if isinstance(preflight.get("setup_contract"), dict)
        else composio_setup_contract(args, []),
        "privacy": preflight.get("privacy")
        if isinstance(preflight.get("privacy"), dict)
        else {},
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise AcceptanceFailure("preflight required_next must be a string list")
    if value != list(dict.fromkeys(value)):
        raise AcceptanceFailure("preflight required_next must not contain duplicates")
    if any(not item for item in value):
        raise AcceptanceFailure("preflight required_next must not contain empty strings")
    return list(value)


def _safe_bool_map(value: Any, keys: set[str]) -> dict[str, bool]:
    source = value if isinstance(value, dict) else {}
    return {key: source.get(key) is True for key in keys}


def load_composio_preflight_summary(
    path: Path,
    args: argparse.Namespace,
) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise AcceptanceFailure("--failure-preflight-json must point at a regular file")
    try:
        raw_payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as exc:  # noqa: BLE001
        raise AcceptanceFailure(
            f"--failure-preflight-json could not be read as JSON: {exc}"
        ) from exc
    if not isinstance(raw_payload, dict):
        raise AcceptanceFailure("--failure-preflight-json root must be a JSON object")
    if raw_payload.get("schema_version") != PREFLIGHT_SCHEMA_VERSION:
        raise AcceptanceFailure(
            "--failure-preflight-json schema_version does not match Composio preflight"
        )
    if raw_payload.get("status") != "fail":
        raise AcceptanceFailure("--failure-preflight-json status must be fail")
    if raw_payload.get("live_backend_call_attempted") is not False:
        raise AcceptanceFailure(
            "--failure-preflight-json live_backend_call_attempted must be false"
        )
    if raw_payload.get("provider_execution_attempted") is not False:
        raise AcceptanceFailure(
            "--failure-preflight-json provider_execution_attempted must be false"
        )
    required_next = _string_list(raw_payload.get("required_next"))
    setup_contract = raw_payload.get("setup_contract")
    if not isinstance(setup_contract, dict):
        raise AcceptanceFailure("--failure-preflight-json setup_contract must be an object")
    if setup_contract.get("requirement_id") != "wiii-connect-composio-acceptance":
        raise AcceptanceFailure(
            "--failure-preflight-json setup_contract.requirement_id is invalid"
        )
    if setup_contract.get("required_next") != required_next:
        raise AcceptanceFailure(
            "--failure-preflight-json setup_contract.required_next must match required_next"
        )
    backend = raw_payload.get("backend") if isinstance(raw_payload.get("backend"), dict) else {}
    authentication = (
        raw_payload.get("authentication")
        if isinstance(raw_payload.get("authentication"), dict)
        else {}
    )
    arguments = (
        raw_payload.get("arguments") if isinstance(raw_payload.get("arguments"), dict) else {}
    )
    flags = raw_payload.get("flags") if isinstance(raw_payload.get("flags"), dict) else {}
    privacy = raw_payload.get("privacy") if isinstance(raw_payload.get("privacy"), dict) else {}
    return {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "generated_at": raw_payload.get("generated_at"),
        "status": raw_payload.get("status"),
        "requested_provider": normalize_provider(raw_payload.get("requested_provider")),
        "requested_action": normalize_action(raw_payload.get("requested_action")),
        "allow_live_acknowledged": raw_payload.get("allow_live_acknowledged") is True,
        "live_env_flag_set": raw_payload.get("live_env_flag_set") is True,
        "live_backend_call_attempted": False,
        "provider_execution_attempted": False,
        "backend": {
            "valid": backend.get("valid") is True,
            "placeholder": backend.get("placeholder") is True,
            "scheme": backend.get("scheme") if backend.get("scheme") in {"http", "https"} else "",
            "host_hash_present": backend.get("host_hash_present") is True,
            "origin_hash_present": backend.get("origin_hash_present") is True,
            "raw_backend_url_included": False,
        },
        "authentication": {
            "mode": authentication.get("mode")
            if authentication.get("mode") in {"auto", "bearer", "dev-login"}
            else args.auth_mode,
            "bearer_token_present": authentication.get("bearer_token_present") is True,
            "bearer_source": authentication.get("bearer_source")
            if authentication.get("bearer_source") in {"argument", "environment", "none"}
            else "none",
            "dev_login_allowed_by_mode": authentication.get("dev_login_allowed_by_mode")
            is True,
            "bearer_value_included": False,
            "bearer_env_name_included": False,
        },
        "flags": _safe_bool_map(
            flags,
            {
                "expect_connected",
                "require_execution_ready",
                "execute_readonly",
                "skip_connect_link",
                "explicit_connection_selection_present",
            },
        ),
        "arguments": {
            "valid_json_object": arguments.get("valid_json_object") is True,
            "argument_key_count": int(arguments.get("argument_key_count") or 0)
            if isinstance(arguments.get("argument_key_count"), int)
            and int(arguments.get("argument_key_count") or 0) >= 0
            else 0,
            "arguments_present": arguments.get("arguments_present") is True,
            "raw_arguments_included": False,
        },
        "required_next": required_next,
        "setup_contract": setup_contract,
        "privacy": {
            "secret_values_included": False,
            "credential_names_included": False,
            "bearer_value_included": False,
            "bearer_env_name_included": False,
            "raw_backend_url_included": False,
            "raw_connection_selection_included": False,
            "raw_arguments_included": False,
            "provider_payload_included": False,
            "provider_response_included": False,
            **{key: value for key, value in privacy.items() if value is False},
        },
    }


def failed_composio_acceptance_evidence_payload(
    args: argparse.Namespace,
    *,
    reason: Any,
    preflight_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    preflight = preflight_summary or safe_composio_preflight_summary(args)
    required_next = preflight["required_next"]
    preflight_flags = (
        preflight.get("flags") if isinstance(preflight.get("flags"), dict) else {}
    )
    preflight_arguments = (
        preflight.get("arguments") if isinstance(preflight.get("arguments"), dict) else {}
    )
    authentication = (
        preflight.get("authentication")
        if isinstance(preflight.get("authentication"), dict)
        else {}
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "schema": LEGACY_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "fail",
        "error_code": "composio_acceptance_setup_blocked",
        "error_message": _redact_acceptance_failure_text(reason, args),
        "provider": preflight.get("requested_provider") or normalize_provider(args.provider),
        "action": preflight.get("requested_action") or normalize_action(args.action),
        "auth_mode": authentication.get("mode") or args.auth_mode,
        "live_backend_call_attempted": False,
        "provider_execution_attempted": False,
        "required_next": required_next,
        "setup_contract": preflight["setup_contract"],
        "preflight_summary": preflight,
        "summary": {
            "passed": 0,
            "failed": 1,
            "total": 1,
            "success": False,
        },
        "flags": {
            "expect_connected": preflight_flags.get("expect_connected") is True,
            "require_execution_ready": preflight_flags.get("require_execution_ready")
            is True,
            "execute_readonly": preflight_flags.get("execute_readonly") is True,
            "skip_connect_link": preflight_flags.get("skip_connect_link") is True,
            "explicit_connection_selection_supplied": preflight_flags.get(
                "explicit_connection_selection_present"
            )
            is True,
            "arguments_present": preflight_arguments.get("arguments_present") is True,
        },
        "runtime": {
            "path": "external_app_action",
            "mutation": "read",
            "argument_key_count": int(preflight_arguments.get("argument_key_count") or 0),
            "arguments_present": preflight_arguments.get("arguments_present") is True,
            "check_count": 0,
            "observed_section_count": 0,
        },
        "evidence_contract": {
            "backend_only_harness": True,
            "external_provider_execution": False,
            "requires_connected_account": bool(
                preflight_flags.get("expect_connected") is True
                or preflight_flags.get("require_execution_ready") is True
                or preflight_flags.get("execute_readonly") is True
            ),
            "requires_readonly_execution": preflight_flags.get("execute_readonly")
            is True,
            "diagnostic_only": True,
        },
        "privacy": {
            "identifier_strategy": "hash_or_count_only",
            "raw_content_included": False,
            "provider_payload_included": False,
            "provider_arguments_included": False,
            "provider_response_included": False,
            "raw_schema_included": False,
            "connect_link_included": False,
            "bearer_value_included": False,
            "bearer_env_name_included": False,
            "raw_backend_url_included": False,
            "raw_connection_locator_included": False,
        },
        "checks": [],
    }


def composio_setup_contract(
    args: argparse.Namespace,
    required_next: list[str],
) -> dict[str, Any]:
    credential_slots = (
        ["acceptance_bearer_token"] if args.auth_mode == "bearer" else []
    )
    external_setup = ["staging_or_live_backend"]
    if args.expect_connected or args.require_execution_ready or args.execute_readonly:
        external_setup.append("connected_provider_account")
    if args.require_execution_ready or args.execute_readonly:
        external_setup.extend(
            [
                "readonly_action_schema",
                "execution_gateway_scope_policy",
            ]
        )
    return {
        "version": SETUP_CONTRACT_VERSION,
        "requirement_id": "wiii-connect-composio-acceptance",
        "required_next": list(required_next),
        "workflow_inputs_required": [
            "backend_url",
            "auth_mode",
            "provider",
            "allow_live",
            "expect_connected",
            "require_execution_ready",
            "execute_readonly",
            "arguments_json",
        ],
        "environment_flags_required": ["live_composio_acceptance_flag"],
        "credential_slots_required": credential_slots,
        "external_setup_required": list(dict.fromkeys(external_setup)),
        "dispatch_ready": not required_next,
    }


class WiiiConnectComposioAcceptance:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.token = ""
        self.selected_connection_ref = ""
        self.passed = 0
        self.failed = 0
        self.started_at = datetime.now(UTC)
        self.check_records: list[dict[str, Any]] = []
        self.observations: dict[str, Any] = {}

    def observe(self, section: str, value: dict[str, Any]) -> None:
        self.observations[check_status_key(section)] = value

    def api_url(self, path: str) -> str:
        return join_url(self.args.backend_url, path)

    def provider_callback_url(self) -> str:
        if self.args.redirect_uri:
            return self.args.redirect_uri
        return self.api_url(
            f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}/callback"
        )

    def auth_headers(self) -> dict[str, str]:
        if not self.token:
            raise AcceptanceFailure("No bearer token available")
        headers = {"Authorization": f"Bearer {self.token}"}
        if self.args.org_id:
            headers["X-Organization-ID"] = self.args.org_id
        return headers

    def run_check(self, name: str, func: Callable[[], str]) -> bool:
        start = time.monotonic()
        try:
            detail = func()
        except AcceptanceFailure as exc:
            self.failed += 1
            elapsed = time.monotonic() - start
            self.check_records.append(
                self.check_record(
                    name,
                    status="failed",
                    elapsed=elapsed,
                    detail=str(exc),
                )
            )
            print(f"[FAIL] {name} - {exc}")
            return False
        except Exception as exc:  # pragma: no cover - defensive CLI boundary
            self.failed += 1
            elapsed = time.monotonic() - start
            self.check_records.append(
                self.check_record(
                    name,
                    status="failed",
                    elapsed=elapsed,
                    detail=f"unexpected error: {exc}",
                )
            )
            print(f"[FAIL] {name} - unexpected error: {exc}")
            return False
        elapsed = time.monotonic() - start
        suffix = f" - {detail}" if detail else ""
        self.check_records.append(
            self.check_record(
                name,
                status="passed",
                elapsed=elapsed,
                detail=detail,
            )
        )
        print(f"[PASS] {name} ({elapsed:.1f}s){suffix}")
        self.passed += 1
        return True

    def run(self) -> int:
        self.run_check("backend health", self.check_backend_health)
        self.run_check("authentication", self.authenticate)
        if self.token:
            if self.args.readiness_report_only:
                self.run_check(
                    "activation readiness report",
                    self.check_activation_readiness_report,
                )
            else:
                self.run_check("provider registry", self.check_provider_registry)
                self.run_check("adapter readiness", self.check_adapter_readiness)
                self.run_check("storage readiness", self.check_storage_readiness)
                self.run_check("audit readiness", self.check_audit_readiness)
                self.run_check(
                    "activation readiness connect",
                    self.check_activation_ready_to_connect,
                )
                if self.should_check_execution_policy():
                    self.run_check("curated actions", self.check_curated_actions)
                    self.run_check(
                        "gateway fail-closed control",
                        self.check_gateway_blocks_missing_connection,
                    )
                if self.should_issue_connect_link():
                    self.run_check("connect link preflight", self.check_connect_link)
                self.run_check("connection listing", self.check_connections)
                if self.should_check_execution_policy():
                    self.run_check(
                        "activation readiness execution",
                        self.check_activation_ready_to_execute,
                    )
                    self.run_check(
                        "execution gateway allowed",
                        self.check_execution_gateway_allowed,
                    )
                if self.args.execute_readonly:
                    self.run_check(
                        "read-only provider execution",
                        self.check_readonly_execution,
                    )
                if self.args.disconnect:
                    self.run_check("backend-owned disconnect", self.check_disconnect)

        total = self.passed + self.failed
        print(f"\nResult: {self.passed}/{total} checks passed")
        if evidence_output_path(self.args):
            self.write_evidence_json()
        return 1 if self.failed else 0

    def check_record(
        self,
        name: str,
        *,
        status: str,
        elapsed: float,
        detail: str,
    ) -> dict[str, Any]:
        return {
            "name": str(name),
            "status": status,
            "elapsed_seconds": round(float(elapsed), 3),
            "detail": redact_for_log(str(detail or "")),
        }

    def should_issue_connect_link(self) -> bool:
        """Issue Connect Links only during the initial connection phase."""

        if self.args.skip_connect_link:
            return False
        return not (
            self.args.expect_connected
            or self.args.require_execution_ready
            or self.args.execute_readonly
            or self.args.disconnect
        )

    def should_check_execution_policy(self) -> bool:
        """Run action/gateway checks only for read-only execution acceptance."""

        return bool(self.args.require_execution_ready or self.args.execute_readonly)

    def evidence_payload(self) -> dict[str, Any]:
        parsed_backend = urllib.parse.urlsplit(self.args.backend_url)
        backend_origin = ""
        if parsed_backend.scheme and parsed_backend.netloc:
            backend_origin = f"{parsed_backend.scheme}://{parsed_backend.netloc}"
        success = self.failed == 0
        argument_keys = self.argument_keys()
        observations = dict(self.observations)
        return redact_for_log(
            {
                "schema_version": SCHEMA_VERSION,
                "schema": LEGACY_SCHEMA_VERSION,
                "generated_at": datetime.now(UTC).isoformat(),
                "started_at": self.started_at.isoformat(),
                "status": "pass" if success else "fail",
                "backend_origin": backend_origin or "[invalid_backend_url]",
                "target_env": getattr(self.args, "target_env", "")
                or os.environ.get(TARGET_ENV, "")
                or "unspecified",
                "commit_sha": getattr(self.args, "commit_sha", "")
                or os.environ.get(COMMIT_SHA_ENV, "")
                or "unspecified",
                "provider": normalize_provider(self.args.provider),
                "action": normalize_action(self.args.action),
                "auth_mode": self.args.auth_mode,
                "flags": {
                    "readiness_report_only": bool(
                        getattr(self.args, "readiness_report_only", False)
                    ),
                    "skip_connect_link": bool(
                        getattr(self.args, "skip_connect_link", False)
                    ),
                    "print_connect_url": bool(
                        getattr(self.args, "print_connect_url", False)
                    ),
                    "expect_connected": bool(
                        getattr(self.args, "expect_connected", False)
                    ),
                    "require_execution_ready": bool(
                        getattr(self.args, "require_execution_ready", False)
                    ),
                    "execute_readonly": bool(
                        getattr(self.args, "execute_readonly", False)
                    ),
                    "disconnect": bool(getattr(self.args, "disconnect", False)),
                    "explicit_connection_selected": bool(
                        getattr(self.args, "connection_ref", "")
                    ),
                    "connection_selected_for_action": bool(
                        getattr(self.args, "connection_ref", "")
                        or self.selected_connection_ref
                    ),
                    "arguments_present": bool(
                        parse_json_argument_object(
                            getattr(self.args, "arguments_json", "{}")
                        )
                    ),
                },
                "runtime": {
                    "path": "external_app_action",
                    "mutation": "read",
                    "argument_key_count": len(argument_keys),
                    "arguments_present": bool(argument_keys),
                    "check_count": len(self.check_records),
                    "observed_section_count": len(observations),
                },
                "evidence_contract": {
                    "backend_only_harness": True,
                    "external_provider_execution": bool(
                        getattr(self.args, "execute_readonly", False)
                    ),
                    "requires_connected_account": bool(
                        getattr(self.args, "expect_connected", False)
                        or getattr(self.args, "require_execution_ready", False)
                        or getattr(self.args, "execute_readonly", False)
                    ),
                    "requires_readonly_execution": bool(
                        getattr(self.args, "execute_readonly", False)
                    ),
                },
                "summary": {
                    "passed": self.passed,
                    "failed": self.failed,
                    "total": self.passed + self.failed,
                    "success": success,
                },
                "check_statuses": {
                    check_status_key(record.get("name")): record.get("status")
                    for record in self.check_records
                },
                "backend": observations.get("backend", {}),
                "authentication": observations.get("authentication", {}),
                "provider_registry": observations.get("provider_registry", {}),
                "adapter": observations.get("adapter", {}),
                "storage": observations.get("storage", {}),
                "audit_ledger": observations.get("audit_ledger", {}),
                "activation": {
                    "connect": observations.get("activation_connect", {}),
                    "execution": observations.get("activation_execution", {}),
                },
                "curated_action": observations.get("curated_action", {}),
                "gateway_fail_closed": observations.get("gateway_fail_closed", {}),
                "connection_selection": observations.get("connection_selection", {}),
                "execution_gateway": observations.get("execution_gateway", {}),
                "readonly_execution": observations.get("readonly_execution", {}),
                "privacy": {
                    "identifier_strategy": "hash_or_count_only",
                    "raw_content_included": False,
                    "opaque_connection_included": False,
                    "provider_payload_included": False,
                    "provider_arguments_included": False,
                    "provider_response_included": False,
                    "raw_schema_included": False,
                    "connect_link_included": False,
                    "bearer_value_included": False,
                    "bearer_env_name_included": False,
                },
                "checks": self.check_records,
            }
        )

    def write_evidence_json(self) -> None:
        path = validate_evidence_path(evidence_output_path(self.args))
        emit_json_payload(self.evidence_payload(), path)
        print(f"[INFO] Wrote redacted evidence JSON: {path}")

    def check_backend_health(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url("/api/v1/health"),
            timeout=self.args.timeout,
        ).json()
        status = check_status_key(payload.get("status") or "ok")
        self.observe("backend", {"health_status": status, "origin_present": True})
        return status

    def authenticate(self) -> str:
        env_token = os.environ.get(TOKEN_ENV, "")
        token = (
            ""
            if self.args.auth_mode == "dev-login"
            else (self.args.bearer_token or env_token).strip()
        )
        if token:
            self.token = token
            self.observe(
                "authentication",
                {
                    "status": "authenticated",
                    "mode": "bearer",
                    "source": "argument" if self.args.bearer_token else "environment",
                    "bearer_value_included": False,
                    "bearer_env_name_included": False,
                },
            )
            return "bearer auth supplied"
        if self.args.auth_mode == "bearer":
            raise AcceptanceFailure(
                "No bearer credential supplied. Pass --bearer-token or configure "
                "the acceptance bearer secret."
            )
        status = request_bytes(
            "GET",
            self.api_url("/api/v1/auth/dev-login/status"),
            timeout=self.args.timeout,
        ).json()
        if status.get("enabled") is not True:
            raise AcceptanceFailure(
                "dev-login is disabled and no bearer token was supplied"
            )
        payload = request_bytes(
            "POST",
            self.api_url("/api/v1/auth/dev-login"),
            payload={
                "email": self.args.demo_email,
                "name": self.args.demo_name,
                "role": self.args.demo_role,
            },
            timeout=self.args.timeout,
        ).json()
        token = payload.get("access_token")
        user = payload.get("user")
        if not isinstance(token, str) or not token:
            raise AcceptanceFailure("dev-login did not return an access token")
        if not isinstance(user, dict):
            raise AcceptanceFailure("dev-login did not return a user object")
        if user.get("platform_role") != self.args.expected_platform_role:
            raise AcceptanceFailure(
                "dev-login user lacks expected platform role "
                f"{self.args.expected_platform_role!r}"
            )
        self.token = token
        self.observe(
            "authentication",
            {
                "status": "authenticated",
                "mode": "dev_login",
                "platform_role_verified": True,
                "bearer_value_included": False,
                "bearer_env_name_included": False,
            },
        )
        return "dev-login authenticated"

    def check_provider_registry(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url("/api/v1/wiii-connect/providers"),
            headers=self.auth_headers(),
            timeout=self.args.timeout,
        ).json()
        provider = find_provider(payload, self.args.provider)
        if provider.get("provider_kind") != "composio":
            raise AcceptanceFailure(
                f"{self.args.provider} provider kind is {provider.get('provider_kind')!r}"
            )
        self.observe(
            "provider_registry",
            {
                "provider_slug": normalize_provider(self.args.provider),
                "provider_kind": "composio",
                "provider_found": True,
            },
        )
        return f"{provider.get('slug')} kind=composio"

    def check_adapter_readiness(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url("/api/v1/wiii-connect/provider-adapters/status"),
            headers=self.auth_headers(),
            timeout=self.args.timeout,
        ).json()
        adapter = find_adapter(payload, "composio")
        missing = [
            key
            for key in ("bound", "configured", "authorization_ready")
            if adapter.get(key) is not True
        ]
        if missing:
            raise AcceptanceFailure(
                "Composio adapter is not ready: "
                f"missing={missing} reason={adapter.get('reason')!r}"
            )
        if (self.args.require_execution_ready or self.args.execute_readonly) and adapter.get(
            "can_execute_actions"
        ) is not True:
            raise AcceptanceFailure("Composio adapter cannot execute curated actions")
        self.observe(
            "adapter",
            {
                "bound": adapter.get("bound") is True,
                "configured": adapter.get("configured") is True,
                "auth_ready": adapter.get("authorization_ready") is True,
                "can_execute_actions": adapter.get("can_execute_actions") is True,
            },
        )
        return (
            "authorization_ready=true "
            f"can_execute_actions={bool(adapter.get('can_execute_actions'))}"
        )

    def check_storage_readiness(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url("/api/v1/wiii-connect/storage/status?probe_database=true"),
            headers=self.auth_headers(),
            timeout=self.args.timeout,
        ).json()
        required = ("persistent", "connection_table_ready", "audit_ledger_ready")
        missing = [key for key in required if payload.get(key) is not True]
        if missing:
            raise AcceptanceFailure(
                f"Wiii Connect storage is not ready: missing={missing} "
                f"reason={payload.get('reason')!r}"
            )
        self.observe(
            "storage",
            {
                "persistent": payload.get("persistent") is True,
                "connection_table_ready": payload.get("connection_table_ready") is True,
                "audit_ledger_ready": payload.get("audit_ledger_ready") is True,
            },
        )
        return "postgres tables ready"

    def check_audit_readiness(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url("/api/v1/wiii-connect/audit-ledger/status?probe_database=true"),
            headers=self.auth_headers(),
            timeout=self.args.timeout,
        ).json()
        if payload.get("persistent") is not True:
            raise AcceptanceFailure(
                f"Audit ledger is not persistent: reason={payload.get('reason')!r}"
            )
        self.observe("audit_ledger", {"persistent": True})
        return "persistent=true"

    def check_curated_actions(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}/actions"
            ),
            headers=self.auth_headers(),
            timeout=self.args.timeout,
        ).json()
        action = find_action(payload, self.args.action)
        if action.get("mutation") != "read":
            raise AcceptanceFailure(f"{self.args.action} is not read-only")
        if (self.args.require_execution_ready or self.args.execute_readonly) and action.get(
            "enabled"
        ) is not True:
            raise AcceptanceFailure(f"{self.args.action} is not runtime-enabled")
        self.observe(
            "curated_action",
            {
                "provider_slug": normalize_provider(self.args.provider),
                "action_slug": normalize_action(self.args.action),
                "mutation": "read",
                "enabled": action.get("enabled") is True,
            },
        )
        return (
            f"{action.get('slug')} mutation=read enabled={bool(action.get('enabled'))}"
        )

    def check_gateway_blocks_missing_connection(self) -> str:
        payload = request_bytes(
            "POST",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}/execution-decision"
            ),
            headers=self.auth_headers(),
            payload={
                "surface": "acceptance_harness",
                "action_slug": self.args.action,
                "path": "external_app_action",
                "mutation": "read",
                "argument_keys": self.argument_keys(),
            },
            timeout=self.args.timeout,
        ).json()
        if payload.get("status") == "allowed":
            raise AcceptanceFailure("Gateway allowed execution without a connection")
        if payload.get("reason") != "connection_selection_required":
            raise AcceptanceFailure(
                "Gateway did not enforce explicit connection selection: "
                f"reason={payload.get('reason')!r}"
            )
        self.observe(
            "gateway_fail_closed",
            {
                "status": check_status_key(payload.get("status") or ""),
                "reason": "connection_selection_required",
                "missing_connection_selection_blocked": True,
                "provider_execution_attempted": False,
            },
        )
        return f"blocked reason={payload.get('reason')}"

    def activation_readiness_payload(
        self,
        *,
        connection_ref: str = "",
    ) -> dict[str, Any]:
        params = {
            "probe_database": "true",
            "action_slug": self.args.action,
        }
        if connection_ref:
            params["connection_ref"] = connection_ref
        query = urllib.parse.urlencode(params)
        return request_bytes(
            "GET",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}"
                f"/activation-readiness?{query}"
            ),
            headers=self.auth_headers(),
            timeout=self.args.timeout,
        ).json()

    def check_activation_ready_to_connect(self) -> str:
        payload = self.activation_readiness_payload()
        assert_activation_ready(
            payload,
            flag="ready_to_connect",
            label="connect-ready",
        )
        self.observe(
            "activation_connect",
            {
                "status": check_status_key(payload.get("status") or ""),
                "ready_to_connect": True,
                "ready_to_execute_readonly": payload.get("ready_to_execute_readonly")
                is True,
            },
        )
        return (
            "ready_to_connect=true "
            f"ready_to_execute_readonly={bool(payload.get('ready_to_execute_readonly'))}"
        )

    def check_activation_ready_to_execute(self) -> str:
        connection_ref = self.connection_ref_for_action()
        payload = self.activation_readiness_payload(connection_ref=connection_ref)
        assert_activation_ready(
            payload,
            flag="ready_to_execute_readonly",
            label="read-only execution-ready",
        )
        scope_detail = assert_scope_policy_allowed(
            payload,
            label="activation readiness",
        )
        self.observe(
            "activation_execution",
            {
                "status": check_status_key(payload.get("status") or ""),
                "ready_to_execute_readonly": True,
                "selected_connection_hash_present": True,
                "scope_policy": _scope_policy_summary(payload),
            },
        )
        return (
            "ready_to_execute_readonly=true "
            f"{scope_detail} connection={opaque_ref(connection_ref)}"
        )

    def check_activation_readiness_report(self) -> str:
        connection_ref = (self.args.connection_ref or "").strip()
        payload = self.activation_readiness_payload(connection_ref=connection_ref)
        print_activation_readiness_report(payload)
        return f"blockers={activation_blocker_summary(payload)}"

    def check_connect_link(self) -> str:
        payload = request_bytes(
            "POST",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}/authorization-url"
            ),
            headers=self.auth_headers(),
            payload={
                "surface": "acceptance_harness",
                "redirect_uri": self.provider_callback_url(),
                "probe_database": True,
                "requested_scopes": {"read": True},
                "request_metadata": {"harness": "wiii_connect_composio_acceptance"},
            },
            timeout=self.args.timeout,
        ).json()
        if payload.get("status") != "ready":
            raise AcceptanceFailure(
                f"Connect Link was not issued: reason={payload.get('reason')!r} "
                f"required_next={payload.get('required_next')!r}"
            )
        authorization_url = str(payload.get("authorization_url") or "")
        if not authorization_url:
            raise AcceptanceFailure("Connect Link decision omitted authorization_url")
        if self.args.print_connect_url:
            print(f"[INFO] Open this operator-only Connect Link: {authorization_url}")
        self.observe(
            "connect_link",
            {
                "status": "ready",
                "link_present": True,
                "raw_link_included": False,
            },
        )
        return "connect_link_present=true"

    def check_connections(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}/connections"
                "?probe_database=true"
            ),
            headers=self.auth_headers(),
            timeout=self.args.timeout,
        ).json()
        if payload.get("status") != "ready":
            raise AcceptanceFailure(
                f"Connection list is not ready: reason={payload.get('reason')!r}"
            )
        connection = first_connected_connection(payload)
        if connection is None:
            if (
                self.args.expect_connected
                or self.args.require_execution_ready
                or self.args.execute_readonly
                or self.args.disconnect
            ):
                raise AcceptanceFailure("No active connected account was returned")
            self.observe(
                "connection_selection",
                {
                    "list_status": "ready",
                    "account_count": _list_count(payload.get("connections")),
                    "active_connection_found": False,
                    "selected_connection_hash_present": False,
                    "opaque_connection_included": False,
                },
            )
            return "ready; no active account required for this run"
        self.selected_connection_ref = str(
            connection.get("connection_ref") or ""
        )
        self.observe(
            "connection_selection",
            {
                "list_status": "ready",
                "account_count": _list_count(payload.get("connections")),
                "active_connection_found": True,
                "selected_connection_hash_present": True,
                "selected_connection_source": "listing"
                if not getattr(self.args, "connection_ref", "")
                else "explicit",
                "opaque_connection_included": False,
            },
        )
        return f"active_connection={opaque_ref(self.selected_connection_ref)}"

    def check_execution_gateway_allowed(self) -> str:
        connection_ref = self.connection_ref_for_action()
        payload = request_bytes(
            "POST",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}/execution-decision"
            ),
            headers=self.auth_headers(),
            payload={
                "surface": "acceptance_harness",
                "connection_ref": connection_ref,
                "action_slug": self.args.action,
                "path": "external_app_action",
                "mutation": "read",
                "argument_keys": self.argument_keys(),
            },
            timeout=self.args.timeout,
        ).json()
        if payload.get("status") != "allowed":
            raise AcceptanceFailure(
                f"Gateway did not allow read-only action: reason={payload.get('reason')!r}"
            )
        scope_detail = assert_scope_policy_allowed(
            payload,
            label="execution gateway",
        )
        self.observe(
            "execution_gateway",
            {
                "status": "allowed",
                "reason": check_status_key(payload.get("reason") or "allowed"),
                "selected_connection_hash_present": True,
                "argument_key_count": len(self.argument_keys()),
                "scope_policy": _scope_policy_summary(payload),
                "provider_execution_attempted": False,
            },
        )
        return f"allowed {scope_detail} connection={opaque_ref(connection_ref)}"

    def check_readonly_execution(self) -> str:
        connection_ref = self.connection_ref_for_action()
        payload = request_bytes(
            "POST",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}/execute"
            ),
            headers=self.auth_headers(),
            payload={
                "surface": "acceptance_harness",
                "connection_ref": connection_ref,
                "action_slug": self.args.action,
                "path": "external_app_action",
                "mutation": "read",
                "argument_keys": self.argument_keys(),
                "arguments": self.arguments(),
            },
            timeout=self.args.execution_timeout,
        ).json()
        if payload.get("status") != "succeeded":
            raise AcceptanceFailure(
                "Read-only execution did not succeed: "
                f"status={payload.get('status')!r} reason={payload.get('reason')!r} "
                f"schema={json_for_log(payload.get('schema'))} "
                f"execution={json_for_log(payload.get('execution'))}"
            )
        execution = (
            payload.get("execution")
            if isinstance(payload.get("execution"), dict)
            else {}
        )
        schema = payload.get("schema") if isinstance(payload.get("schema"), dict) else {}
        schema_summary = _schema_summary(
            schema,
            supplied_argument_keys=self.argument_keys(),
        )
        execution_summary = _execution_summary(execution)
        if schema_summary["status"] != "ready" or schema_summary["schema_present"] is not True:
            raise AcceptanceFailure(
                "Read-only execution omitted live schema readiness proof"
            )
        if execution_summary["status"] != "succeeded" or execution_summary["successful"] is not True:
            raise AcceptanceFailure(
                "Read-only execution omitted successful execution metadata"
            )
        self.observe(
            "readonly_execution",
            {
                "status": check_status_key(payload.get("status") or ""),
                "reason": check_status_key(payload.get("reason") or ""),
                "provider_slug": normalize_provider(self.args.provider),
                "action_slug": normalize_action(self.args.action),
                "selected_connection_hash_present": True,
                "schema": schema_summary,
                "execution": execution_summary,
                "provider_payload_included": False,
            },
        )
        return f"succeeded data_keys={execution.get('data_keys', [])}"

    def check_disconnect(self) -> str:
        connection_ref = self.connection_ref_for_action()
        payload = request_bytes(
            "DELETE",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}"
                f"/connections/{urllib.parse.quote(connection_ref)}"
            ),
            headers=self.auth_headers(),
            payload={"surface": "acceptance_harness"},
            timeout=self.args.timeout,
        ).json()
        if payload.get("local_disabled") is not True:
            raise AcceptanceFailure(
                "Disconnect did not disable local Wiii state: "
                f"{json_for_log(payload)}"
            )
        if payload.get("status") != "succeeded":
            raise AcceptanceFailure(
                f"Provider disconnect did not succeed: {json_for_log(payload)}"
            )
        return f"local_disabled=true connection={opaque_ref(connection_ref)}"

    def argument_keys(self) -> list[str]:
        argument_keys = str(getattr(self.args, "argument_keys", "") or "")
        if argument_keys:
            return [
                item.strip()
                for item in argument_keys.split(",")
                if item.strip()
            ]
        return sorted(self.arguments().keys())

    def arguments(self) -> dict[str, Any]:
        return parse_json_argument_object(
            str(getattr(self.args, "arguments_json", "{}") or "{}")
        )

    def connection_ref_for_action(self) -> str:
        candidate = (self.args.connection_ref or self.selected_connection_ref).strip()
        if not candidate:
            raise AcceptanceFailure(
                "No connected account selected. Run with --expect-connected after OAuth "
                "or pass --connection-ref explicitly."
            )
        if not is_public_connection_ref(candidate):
            raise AcceptanceFailure(
                "Selected connection_ref is not a Wiii opaque ref. Pass the wcn_* "
                "value returned by the backend connection list; do not pass raw "
                "provider connection IDs."
            )
        return candidate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify Wiii Connect Composio readiness through Wiii backend policy. "
            "No provider calls are made directly from this harness."
        )
    )
    parser.add_argument("--backend-url", default=DEFAULT_BACKEND_URL)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument(
        "--action",
        default="",
        help=(
            "Curated action slug. Defaults to the selected provider's safe "
            "read-only diagnostic action."
        ),
    )
    parser.add_argument(
        "--auth-mode",
        choices=("auto", "bearer", "dev-login"),
        default="auto",
        help="auto uses --bearer-token/WIII_ACCEPTANCE_BEARER_TOKEN first, then dev-login.",
    )
    parser.add_argument("--bearer-token", default="")
    parser.add_argument("--org-id", default="")
    parser.add_argument("--redirect-uri", default="")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--execution-timeout", type=float, default=45.0)
    parser.add_argument("--demo-email", default=DEFAULT_DEMO_EMAIL)
    parser.add_argument("--demo-name", default=DEFAULT_DEMO_NAME)
    parser.add_argument("--demo-role", default=DEFAULT_DEMO_ROLE)
    parser.add_argument(
        "--expected-platform-role",
        default=DEFAULT_EXPECTED_PLATFORM_ROLE,
    )
    parser.add_argument("--skip-connect-link", action="store_true")
    parser.add_argument(
        "--readiness-report-only",
        action="store_true",
        help=(
            "Fetch and print the redacted activation-readiness report, then stop. "
            "Does not issue Connect Links, list provider accounts, execute, or disconnect."
        ),
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help=(
            "Check live evidence setup without calling the backend or provider. "
            "Writes a diagnostic payload when --out/--evidence-json is supplied."
        ),
    )
    parser.add_argument(
        "--failure-from-preflight",
        action="store_true",
        help=(
            "Write a failed registered evidence artifact from sanitized preflight "
            "setup diagnostics without calling the backend or provider."
        ),
    )
    parser.add_argument(
        "--failure-preflight-json",
        default="",
        help=(
            "Validated preflight JSON to embed in --failure-from-preflight output. "
            "Use the exact file produced by --preflight-only."
        ),
    )
    parser.add_argument("--print-connect-url", action="store_true")
    parser.add_argument("--expect-connected", action="store_true")
    parser.add_argument("--require-execution-ready", action="store_true")
    parser.add_argument("--execute-readonly", action="store_true")
    parser.add_argument("--disconnect", action="store_true")
    parser.add_argument(
        "--connection-ref",
        default="",
        help="Opaque Wiii connection_ref selected from the backend connection list.",
    )
    parser.add_argument("--argument-keys", default="")
    parser.add_argument("--arguments-json", default="{}")
    parser.add_argument(
        "--target-env",
        default="",
        help=f"Optional target environment label for evidence JSON; env fallback {TARGET_ENV}.",
    )
    parser.add_argument(
        "--commit-sha",
        default="",
        help=f"Optional deployed commit SHA for evidence JSON; env fallback {COMMIT_SHA_ENV}.",
    )
    parser.add_argument(
        "--evidence-json",
        default="",
        help=(
            "Write a sanitized JSON evidence artifact. Do not point this at "
            ".env files, logs, screenshots, coverage, dist, or dependency folders."
        ),
    )
    parser.add_argument(
        "--out",
        default="",
        help=(
            "Write UTF-8 JSON. Live runtime evidence requires "
            f"{ENV_FLAG}=1 and --allow-live; --preflight-only writes diagnostics."
        ),
    )
    parser.add_argument(
        "--allow-live",
        action="store_true",
        help="Acknowledge that --out may call a credentialed backend/provider path.",
    )
    return parser


def evidence_output_path(args: argparse.Namespace) -> str:
    return str(getattr(args, "out", "") or getattr(args, "evidence_json", "") or "")


def require_runtime_evidence_guard(args: argparse.Namespace) -> None:
    if not getattr(args, "out", ""):
        return
    if not getattr(args, "allow_live", False):
        raise SystemExit("--allow-live is required with --out")
    if os.getenv(ENV_FLAG) != "1":
        raise SystemExit(f"Set {ENV_FLAG}=1 to write registry runtime evidence")


def validate_evidence_path(raw_path: str) -> Path:
    text = str(raw_path or "").strip()
    if not text:
        raise AcceptanceFailure("--evidence-json path must not be empty")
    path = Path(text).expanduser()
    parts = [part.lower() for part in path.parts]
    filename = path.name.lower()
    blocked_parts = {
        ".git",
        ".env",
        ".venv",
        "node_modules",
        "dist",
        "dist-embed",
        "coverage",
        "logs",
        "screenshots",
        "__pycache__",
    }
    if filename.startswith(".env") or any(part in blocked_parts for part in parts):
        raise AcceptanceFailure(
            "--evidence-json path points at a forbidden local/secret/generated location"
        )
    if path.suffix.lower() != ".json":
        raise AcceptanceFailure("--evidence-json path must end with .json")
    return path


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    raw_args = parser.parse_args(argv)
    try:
        args = prepare_acceptance_args(raw_args)
    except SystemExit as exc:
        args = normalize_acceptance_args(raw_args)
        output_path = evidence_output_path(args)
        if output_path:
            emit_json_payload(
                failed_composio_acceptance_evidence_payload(
                    args,
                    reason=exc,
                ),
                validate_evidence_path(output_path),
            )
        print(_redact_acceptance_failure_text(exc, args), file=sys.stderr)
        return exc.code if isinstance(exc.code, int) else 1
    if getattr(args, "preflight_only", False):
        payload = build_composio_acceptance_preflight(args)
        output_path = evidence_output_path(args)
        emit_json_payload(
            payload,
            validate_evidence_path(output_path) if output_path else None,
        )
        return 0 if payload.get("status") == "pass" else 1
    if getattr(args, "failure_from_preflight", False):
        output_path = evidence_output_path(args)
        if not output_path:
            raise SystemExit("--failure-from-preflight requires --out or --evidence-json")
        if not getattr(args, "failure_preflight_json", ""):
            raise SystemExit("--failure-from-preflight requires --failure-preflight-json")
        try:
            preflight_summary = load_composio_preflight_summary(
                Path(args.failure_preflight_json).expanduser(),
                args,
            )
        except AcceptanceFailure as exc:
            print(_redact_acceptance_failure_text(exc, args), file=sys.stderr)
            return 1
        emit_json_payload(
            failed_composio_acceptance_evidence_payload(
                args,
                reason="preflight blocked live Composio acceptance",
                preflight_summary=preflight_summary,
            ),
            validate_evidence_path(output_path),
        )
        return 1
    harness = WiiiConnectComposioAcceptance(args)
    return harness.run()


def prepare_acceptance_args(args: argparse.Namespace) -> argparse.Namespace:
    args = normalize_acceptance_args(args)
    if getattr(args, "out", "") and getattr(args, "evidence_json", ""):
        if str(args.out).strip() != str(args.evidence_json).strip():
            raise SystemExit("--out and --evidence-json must not point to different files")
    if getattr(args, "out", ""):
        args.evidence_json = args.out
    if getattr(args, "preflight_only", False) or getattr(
        args,
        "failure_from_preflight",
        False,
    ):
        return args
    require_runtime_evidence_guard(args)
    return args


def normalize_acceptance_args(args: argparse.Namespace) -> argparse.Namespace:
    provider = str(getattr(args, "provider", "") or "").strip().lower()
    action = str(getattr(args, "action", "") or "").strip().upper().replace("-", "_")
    if not action:
        action = DEFAULT_ACTION_BY_PROVIDER.get(provider, DEFAULT_ACTION)
    args.action = action
    return args


if __name__ == "__main__":
    sys.exit(main())
