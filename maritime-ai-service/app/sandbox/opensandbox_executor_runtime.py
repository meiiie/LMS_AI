"""Execution/runtime helpers for the OpenSandbox executor shell."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shlex
from datetime import timedelta
from typing import Any, Optional
from urllib.parse import urlparse

from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    sanitize_runtime_payload,
)


def _safe_metadata(value: Any) -> dict[str, Any]:
    safe_value = sanitize_runtime_payload(value or {})
    return safe_value if isinstance(safe_value, dict) else {}


def build_network_policy_impl(
    network_mode: Any,
    network_policy_cls: Any,
) -> Any:
    """Translate Wiii's coarse network policy into an OpenSandbox policy."""
    if getattr(network_mode, "value", network_mode) == "disabled":
        return network_policy_cls(defaultAction="deny", egress=[])
    return None


def build_connection_config_impl(
    *,
    base_url: str,
    api_key: Optional[str],
    timeout_seconds: int,
    sdk: Any,
) -> Any:
    """Create an SDK connection config from the configured base URL."""
    parsed = urlparse(base_url)
    protocol = parsed.scheme or "http"
    request_timeout = timedelta(seconds=max(timeout_seconds + 10, 30))
    return sdk.connection_config(
        api_key=api_key,
        domain=base_url,
        protocol=protocol,
        request_timeout=request_timeout,
        use_server_proxy=False,
    )


def build_provider_metadata_impl(
    *,
    provider_value: str,
    plan: Any,
    request: Any,
) -> dict[str, Any]:
    """Expose provider plan details alongside execution results."""
    metadata = _safe_metadata(request.metadata)
    metadata.update(
        {
            "provider": provider_value,
            "planned_image": plan.image,
            "planned_template": plan.image,
            "planned_network_mode": plan.network_mode.value,
            "planned_timeout_seconds": plan.timeout_seconds,
            "planned_workload_kind": request.workload_kind.value,
            "labels": plan.labels,
        }
    )
    if request.organization_id:
        metadata.setdefault("organization_id", request.organization_id)
    if request.user_id:
        user_id_hash = hash_runtime_identifier(request.user_id)
        if user_id_hash:
            metadata.setdefault("user_id_hash", user_id_hash)
    if request.session_id:
        metadata.setdefault("session_id", request.session_id)
    if request.request_id:
        metadata.setdefault("request_id", request.request_id)
    return _safe_metadata(metadata)


def stringify_metadata_value_impl(value: Any) -> str:
    """Normalize metadata values into provider-safe strings."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(value, ensure_ascii=True, sort_keys=True)


def to_label_safe_value_impl(value: Any) -> str:
    """Normalize metadata into a safe token for OpenSandbox server labels."""
    text = stringify_metadata_value_impl(value).strip()
    if not text:
        return "empty"

    normalized = text.lower()
    normalized = re.sub(r"[^a-z0-9._-]+", "-", normalized)
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-.")

    if normalized and len(normalized) <= 63:
        return normalized

    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    prefix = normalized[:48].rstrip("-.") if normalized else "meta"
    prefix = prefix or "meta"
    return f"{prefix}-{digest}"[:63].rstrip("-.")


def build_sandbox_metadata_impl(plan: Any) -> dict[str, str]:
    """Serialize labels and metadata for sandbox-side tracing."""
    metadata = {
        key: to_label_safe_value_impl(value)
        for key, value in {
            **plan.labels,
            "wiii.image": plan.image,
            "wiii.template": plan.image,
            "wiii.network_mode": plan.network_mode.value,
        }.items()
    }
    for key, value in plan.metadata.items():
        if value is None:
            continue
        metadata[f"wiii.meta.{key}"] = to_label_safe_value_impl(value)
    return metadata


def prepare_code_impl(request: Any) -> str:
    """Inject provider-managed setup before user code when needed."""
    code = request.code or ""
    if not request.working_directory:
        return code
    working_directory = json.dumps(request.working_directory, ensure_ascii=True)
    return (
        "import os as __wiii_os\n"
        f"__wiii_os.chdir({working_directory})\n"
        "del __wiii_os\n\n"
        f"{code}"
    )


def build_command_text_impl(request: Any) -> str:
    """Serialize a command workload into the shell string expected by SDK."""
    if not request.command:
        raise ValueError("OpenSandbox command/browser workloads require a command.")
    return shlex.join(str(part) for part in request.command)


async def healthcheck_impl(
    *,
    is_configured: bool,
    base_url: str,
    api_key: Optional[str],
    healthcheck_path: str,
    async_client_cls: Any,
    logger: Any,
) -> bool:
    """Probe the OpenSandbox control plane with a simple HTTP GET."""
    if not is_configured:
        return False

    path = healthcheck_path
    if not path.startswith("/"):
        path = f"/{path}"
    url = f"{base_url}{path}"
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with async_client_cls(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
        return 200 <= response.status_code < 300
    except Exception as exc:
        logger.debug("[OPENSANDBOX] healthcheck failed: %s", exc)
        return False


def validate_request_impl(request: Any) -> Optional[str]:
    """Fail early on unsupported or incomplete workload requests."""
    workload_kind = request.workload_kind
    if getattr(workload_kind, "value", workload_kind) == "python":
        if not (request.code or "").strip():
            return "OpenSandbox python execution requires non-empty code."
        return None

    if getattr(workload_kind, "value", workload_kind) in ("command", "browser"):
        if not request.command:
            return "OpenSandbox command/browser workloads require a command."
        return None

    return None


async def create_sandbox_impl(
    *,
    plan: Any,
    request: Any,
    sdk: Any,
    build_sandbox_metadata_fn: Any,
    build_network_policy_fn: Any,
    build_connection_config_fn: Any,
) -> Any:
    """Provision the remote sandbox instance for the workload."""
    return await sdk.sandbox.create(
        plan.image,
        timeout=timedelta(seconds=max(plan.timeout_seconds + 60, 120)),
        ready_timeout=timedelta(seconds=max(min(plan.timeout_seconds, 300), 90)),
        env=request.env or None,
        metadata=build_sandbox_metadata_fn(plan),
        network_policy=build_network_policy_fn(
            plan.network_mode,
            sdk.network_policy,
        ),
        connection_config=build_connection_config_fn(
            plan.timeout_seconds,
            sdk,
        ),
    )


async def stage_files_impl(
    *,
    sandbox: Any,
    request: Any,
    sdk: Any,
) -> None:
    """Write requested files into the sandbox before execution."""
    if not request.files:
        return
    await sandbox.files.write_files(
        [
            sdk.write_entry(path=path, data=content, mode=644)
            for path, content in request.files.items()
        ]
    )


async def execute_python_workload_impl(
    *,
    sandbox: Any,
    request: Any,
    plan: Any,
    sdk: Any,
    prepare_code_fn: Any,
) -> Any:
    """Run Python as a sandboxed script for broad image compatibility."""
    script_path = "/tmp/wiii_exec.py"
    await sandbox.files.write_files(
        [
            sdk.write_entry(
                path=script_path,
                data=prepare_code_fn(request),
                mode=0o644,
            )
        ]
    )
    working_directory = request.working_directory or "/workspace"
    command = (
        f"mkdir -p {shlex.quote(working_directory)} && "
        f"cd {shlex.quote(working_directory)} && "
        f"python {shlex.quote(script_path)}"
    )
    opts = sdk.run_command_opts(
        timeout=timedelta(seconds=plan.timeout_seconds),
    )
    return await sandbox.commands.run(command, opts=opts)


async def execute_command_workload_impl(
    *,
    sandbox: Any,
    request: Any,
    plan: Any,
    sdk: Any,
    build_command_text_fn: Any,
) -> Any:
    """Run a shell command workload through the lower-level command surface."""
    opts = sdk.run_command_opts(
        timeout=timedelta(seconds=plan.timeout_seconds),
        working_directory=request.working_directory,
    )
    return await sandbox.commands.run(
        build_command_text_fn(request),
        opts=opts,
    )


async def execute_impl(
    *,
    plan: Any,
    request: Any,
    provider_metadata: dict[str, Any],
    is_configured: bool,
    allow_browser_workloads: bool,
    load_sdk_fn: Any,
    validate_request_fn: Any,
    create_sandbox_fn: Any,
    stage_files_fn: Any,
    execute_python_workload_fn: Any,
    execute_command_workload_fn: Any,
    build_execution_result_fn: Any,
    cleanup_sandbox_fn: Any,
    result_cls: Any,
    workload_kind_cls: Any,
    logger: Any,
) -> Any:
    """Run a workload inside OpenSandbox using injected shell callbacks."""
    if not is_configured:
        return result_cls(
            success=False,
            error="OpenSandbox executor is not configured.",
            metadata=provider_metadata,
        )

    if (
        request.workload_kind == workload_kind_cls.BROWSER
        and not allow_browser_workloads
    ):
        return result_cls(
            success=False,
            error="Browser workloads are not enabled for OpenSandbox in this deployment.",
            metadata=provider_metadata,
        )

    try:
        sdk = load_sdk_fn()
    except ImportError as exc:
        return result_cls(
            success=False,
            error=(
                "OpenSandbox SDK is not installed. Install 'opensandbox' and "
                "'opensandbox-code-interpreter' to enable remote execution."
            ),
            metadata={
                **provider_metadata,
                "dependency_error": str(exc),
            },
        )

    validation_error = validate_request_fn(request)
    if validation_error:
        return result_cls(
            success=False,
            error=validation_error,
            metadata=provider_metadata,
        )

    sandbox = None
    try:
        sandbox = await create_sandbox_fn(
            plan=plan,
            request=request,
            sdk=sdk,
        )
        await stage_files_fn(
            sandbox=sandbox,
            request=request,
            sdk=sdk,
        )

        if request.workload_kind == workload_kind_cls.PYTHON:
            execution = await execute_python_workload_fn(
                sandbox=sandbox,
                request=request,
                plan=plan,
                sdk=sdk,
            )
        elif request.workload_kind in (
            workload_kind_cls.COMMAND,
            workload_kind_cls.BROWSER,
        ):
            execution = await execute_command_workload_fn(
                sandbox=sandbox,
                request=request,
                plan=plan,
                sdk=sdk,
            )
        else:
            return result_cls(
                success=False,
                error=(
                    f"OpenSandbox does not support workload kind "
                    f"'{request.workload_kind.value}'."
                ),
                metadata=provider_metadata,
            )

        return await build_execution_result_fn(
            execution=execution,
            sandbox=sandbox,
            request=request,
            sdk=sdk,
            sandbox_id=sandbox.id,
            provider_metadata=provider_metadata,
        )
    except asyncio.TimeoutError:
        return result_cls(
            success=False,
            error=f"OpenSandbox execution timed out after {plan.timeout_seconds}s.",
            exit_code=124,
            sandbox_id=getattr(sandbox, "id", None),
            metadata=provider_metadata,
        )
    except Exception as exc:
        logger.error("[OPENSANDBOX] execution failed: %s", exc, exc_info=True)
        return result_cls(
            success=False,
            error=f"OpenSandbox execution failed: {exc}",
            sandbox_id=getattr(sandbox, "id", None),
            metadata=provider_metadata,
        )
    finally:
        await cleanup_sandbox_fn(sandbox)


def extract_execution_artifacts_impl(
    execution: Any,
    *,
    coerce_execution_artifact_fn: Any,
) -> list[Any]:
    """Best-effort extraction from provider execution payloads."""
    artifacts: list[Any] = []
    for attr_name in ("artifacts", "files", "outputs", "result"):
        value = getattr(execution, attr_name, None)
        if not value or not isinstance(value, list):
            continue
        for item in value:
            artifact = coerce_execution_artifact_fn(item)
            if artifact is not None:
                artifacts.append(artifact)
    return artifacts
