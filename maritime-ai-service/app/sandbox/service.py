"""Orchestration layer for manifest-driven sandbox execution."""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from queue import Queue
from typing import Any, Callable, Optional

from app.engine.runtime.event_payload_sanitizer import sanitize_runtime_payload
from app.sandbox.catalog import (
    SandboxWorkloadCatalog,
    SandboxWorkloadProfile,
    get_sandbox_workload_catalog,
)
from app.sandbox.factory import get_sandbox_executor
from app.sandbox.models import (
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxNetworkMode,
)

logger = logging.getLogger(__name__)


def _safe_metadata(value: Any) -> dict[str, Any]:
    safe_value = sanitize_runtime_payload(value or {})
    return safe_value if isinstance(safe_value, dict) else {}


@dataclass(slots=True)
class SandboxExecutionContext:
    """Request-scoped metadata attached to sandbox runs."""

    tool_name: str = ""
    source: str = "tool_registry"
    organization_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    approval_scope: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class SandboxExecutionService:
    """Translate workload profiles into provider-neutral execution requests."""

    def __init__(
        self,
        *,
        catalog_provider: Callable[[], SandboxWorkloadCatalog] = get_sandbox_workload_catalog,
        executor_provider: Callable[[], Any] = get_sandbox_executor,
    ):
        self._catalog_provider = catalog_provider
        self._executor_provider = executor_provider

    def get_profile(self, profile_id: str) -> Optional[SandboxWorkloadProfile]:
        """Resolve a workload profile from the manifest catalog."""
        return self._catalog_provider().get(profile_id)

    def build_request(
        self,
        profile_id: str,
        *,
        code: Optional[str] = None,
        command: Optional[list[str]] = None,
        files: Optional[dict[str, str]] = None,
        env: Optional[dict[str, str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
        network_mode: Optional[SandboxNetworkMode] = None,
        runtime_template: Optional[str] = None,
        working_directory: Optional[str] = None,
        context: Optional[SandboxExecutionContext] = None,
    ) -> SandboxExecutionRequest:
        """Build a provider-neutral request from a declarative workload profile."""
        profile = self.get_profile(profile_id)
        if profile is None:
            raise ValueError(f"Unknown sandbox workload profile '{profile_id}'.")

        context = context or SandboxExecutionContext()
        merged_metadata = self._build_metadata(
            profile=profile,
            context=context,
            metadata=metadata,
        )

        return SandboxExecutionRequest(
            workload_kind=profile.workload_kind,
            code=code,
            command=list(command) if command else None,
            files=dict(files or {}),
            env=dict(env or {}),
            metadata=merged_metadata,
            timeout_seconds=timeout_seconds or profile.timeout_seconds,
            network_mode=network_mode or profile.network_mode,
            runtime_template=runtime_template or profile.runtime_template,
            working_directory=working_directory or profile.working_directory,
            organization_id=context.organization_id,
            user_id=context.user_id,
            session_id=context.session_id,
            request_id=context.request_id,
        )

    async def execute_profile(
        self,
        profile_id: str,
        *,
        code: Optional[str] = None,
        command: Optional[list[str]] = None,
        files: Optional[dict[str, str]] = None,
        env: Optional[dict[str, str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
        network_mode: Optional[SandboxNetworkMode] = None,
        runtime_template: Optional[str] = None,
        working_directory: Optional[str] = None,
        context: Optional[SandboxExecutionContext] = None,
    ) -> SandboxExecutionResult:
        """Execute a manifest-defined workload using the configured sandbox backend."""
        request = self.build_request(
            profile_id,
            code=code,
            command=command,
            files=files,
            env=env,
            metadata=metadata,
            timeout_seconds=timeout_seconds,
            network_mode=network_mode,
            runtime_template=runtime_template,
            working_directory=working_directory,
            context=context,
        )
        executor = self._executor_provider()
        if executor is None:
            return SandboxExecutionResult(
                success=False,
                error="No privileged sandbox executor is configured for this deployment.",
                metadata=dict(request.metadata),
            )
        return await executor.execute(request)

    def execute_profile_sync(
        self,
        profile_id: str,
        *,
        code: Optional[str] = None,
        command: Optional[list[str]] = None,
        files: Optional[dict[str, str]] = None,
        env: Optional[dict[str, str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        timeout_seconds: Optional[int] = None,
        network_mode: Optional[SandboxNetworkMode] = None,
        runtime_template: Optional[str] = None,
        working_directory: Optional[str] = None,
        context: Optional[SandboxExecutionContext] = None,
    ) -> SandboxExecutionResult:
        """Sync helper for LangChain tool surfaces that cannot await directly."""
        return run_awaitable_sync(
            self.execute_profile(
                profile_id,
                code=code,
                command=command,
                files=files,
                env=env,
                metadata=metadata,
                timeout_seconds=timeout_seconds,
                network_mode=network_mode,
                runtime_template=runtime_template,
                working_directory=working_directory,
                context=context,
            )
        )

    def _build_metadata(
        self,
        *,
        profile: SandboxWorkloadProfile,
        context: SandboxExecutionContext,
        metadata: Optional[dict[str, Any]],
    ) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        merged.update(profile.metadata)
        merged.update(context.metadata)
        merged.update(metadata or {})

        merged.setdefault("profile_id", profile.profile_id)
        merged.setdefault("profile_name", profile.display_name)
        merged.setdefault("execution_backend", profile.execution_backend)
        merged.setdefault("workload_kind", profile.workload_kind.value)
        if profile.capabilities:
            merged.setdefault("capabilities", list(profile.capabilities))
        approval_scope = context.approval_scope or profile.approval_scope
        if approval_scope:
            merged.setdefault("approval_scope", approval_scope)
        if context.tool_name:
            merged.setdefault("tool_name", context.tool_name)
        if context.source:
            merged.setdefault("request_source", context.source)
        if context.request_id:
            merged.setdefault("request_id", context.request_id)
        if context.session_id:
            merged.setdefault("session_id", context.session_id)
        if context.organization_id:
            merged.setdefault("organization_id", context.organization_id)
        if context.user_id:
            merged.setdefault("user_id", context.user_id)
        return _safe_metadata(merged)


def run_awaitable_sync(awaitable):
    """Run an awaitable from sync code without leaking event-loop details."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)

    result_queue: Queue[tuple[bool, object]] = Queue(maxsize=1)

    def _runner() -> None:
        try:
            result_queue.put((True, asyncio.run(awaitable)))
        except BaseException as exc:  # pragma: no cover - propagated below
            result_queue.put((False, exc))

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()
    ok, payload = result_queue.get()
    if ok:
        return payload
    raise payload


def get_sandbox_execution_service() -> SandboxExecutionService:
    """Return a reusable orchestration service instance."""
    return SandboxExecutionService()
