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
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


DEFAULT_BACKEND_URL = "http://localhost:8080"
DEFAULT_PROVIDER = "gmail"
DEFAULT_ACTION = "GMAIL_FETCH_EMAILS"
DEFAULT_DEMO_EMAIL = "dev@localhost"
DEFAULT_DEMO_NAME = "Dev User"
DEFAULT_DEMO_ROLE = "admin"
DEFAULT_EXPECTED_PLATFORM_ROLE = "platform_admin"
TOKEN_ENV = "WIII_ACCEPTANCE_BEARER_TOKEN"

SENSITIVE_EXACT_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "authorization_url",
    "code",
    "connected_account_id",
    "connection_id",
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
        if (
            isinstance(connection, dict)
            and connection.get("active") is True
            and connection.get("state") == "connected"
            and isinstance(connection.get("connection_id"), str)
            and connection.get("connection_id")
        ):
            return connection
    return None


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
    if "wiii_state=" in lowered or "connected_account_id=" in lowered:
        return True
    return False


class WiiiConnectComposioAcceptance:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.token = ""
        self.selected_connection_id = ""
        self.passed = 0
        self.failed = 0

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
            print(f"[FAIL] {name} - {exc}")
            return False
        except Exception as exc:  # pragma: no cover - defensive CLI boundary
            self.failed += 1
            print(f"[FAIL] {name} - unexpected error: {exc}")
            return False
        elapsed = time.monotonic() - start
        suffix = f" - {detail}" if detail else ""
        print(f"[PASS] {name} ({elapsed:.1f}s){suffix}")
        self.passed += 1
        return True

    def run(self) -> int:
        self.run_check("backend health", self.check_backend_health)
        self.run_check("authentication", self.authenticate)
        if self.token:
            self.run_check("provider registry", self.check_provider_registry)
            self.run_check("adapter readiness", self.check_adapter_readiness)
            self.run_check("storage readiness", self.check_storage_readiness)
            self.run_check("audit readiness", self.check_audit_readiness)
            self.run_check("curated actions", self.check_curated_actions)
            self.run_check(
                "gateway fail-closed control",
                self.check_gateway_blocks_missing_connection,
            )
            if not self.args.skip_connect_link:
                self.run_check("connect link preflight", self.check_connect_link)
            self.run_check("connection listing", self.check_connections)
            if self.args.require_execution_ready or self.args.execute_readonly:
                self.run_check(
                    "execution gateway allowed",
                    self.check_execution_gateway_allowed,
                )
            if self.args.execute_readonly:
                self.run_check("read-only provider execution", self.check_readonly_execution)
            if self.args.disconnect:
                self.run_check("backend-owned disconnect", self.check_disconnect)

        total = self.passed + self.failed
        print(f"\nResult: {self.passed}/{total} checks passed")
        return 1 if self.failed else 0

    def check_backend_health(self) -> str:
        payload = request_bytes(
            "GET",
            self.api_url("/api/v1/health"),
            timeout=self.args.timeout,
        ).json()
        return str(payload.get("status") or "ok")

    def authenticate(self) -> str:
        env_token = os.environ.get(TOKEN_ENV, "")
        token = (
            ""
            if self.args.auth_mode == "dev-login"
            else (self.args.bearer_token or env_token).strip()
        )
        if token:
            self.token = token
            return f"bearer token from {'argument' if self.args.bearer_token else TOKEN_ENV}"
        if self.args.auth_mode == "bearer":
            raise AcceptanceFailure(
                f"No bearer token supplied. Pass --bearer-token or set {TOKEN_ENV}."
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
        return f"dev-login user={user.get('email')}"

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
        return f"blocked reason={payload.get('reason')}"

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
        return "authorization_url_present=true"

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
            return "ready; no active account required for this run"
        self.selected_connection_id = str(connection["connection_id"])
        return f"active_connection={opaque_ref(self.selected_connection_id)}"

    def check_execution_gateway_allowed(self) -> str:
        connection_id = self.connection_id_for_action()
        payload = request_bytes(
            "POST",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}/execution-decision"
            ),
            headers=self.auth_headers(),
            payload={
                "surface": "acceptance_harness",
                "connection_id": connection_id,
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
        return f"allowed connection={opaque_ref(connection_id)}"

    def check_readonly_execution(self) -> str:
        connection_id = self.connection_id_for_action()
        payload = request_bytes(
            "POST",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}/execute"
            ),
            headers=self.auth_headers(),
            payload={
                "surface": "acceptance_harness",
                "connection_id": connection_id,
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
        return f"succeeded data_keys={execution.get('data_keys', [])}"

    def check_disconnect(self) -> str:
        connection_id = self.connection_id_for_action()
        payload = request_bytes(
            "DELETE",
            self.api_url(
                f"/api/v1/wiii-connect/providers/{urllib.parse.quote(self.args.provider)}"
                f"/connections/{urllib.parse.quote(connection_id)}"
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
        return f"local_disabled=true connection={opaque_ref(connection_id)}"

    def argument_keys(self) -> list[str]:
        if self.args.argument_keys:
            return [
                item.strip()
                for item in self.args.argument_keys.split(",")
                if item.strip()
            ]
        return sorted(self.arguments().keys())

    def arguments(self) -> dict[str, Any]:
        return parse_json_argument_object(self.args.arguments_json)

    def connection_id_for_action(self) -> str:
        candidate = (self.args.connection_id or self.selected_connection_id).strip()
        if not candidate:
            raise AcceptanceFailure(
                "No connected account selected. Run with --expect-connected after OAuth "
                "or pass --connection-id explicitly."
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
    parser.add_argument("--action", default=DEFAULT_ACTION)
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
    parser.add_argument("--print-connect-url", action="store_true")
    parser.add_argument("--expect-connected", action="store_true")
    parser.add_argument("--require-execution-ready", action="store_true")
    parser.add_argument("--execute-readonly", action="store_true")
    parser.add_argument("--disconnect", action="store_true")
    parser.add_argument("--connection-id", default="")
    parser.add_argument("--argument-keys", default="")
    parser.add_argument("--arguments-json", default="{}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    harness = WiiiConnectComposioAcceptance(args)
    return harness.run()


if __name__ == "__main__":
    sys.exit(main())
