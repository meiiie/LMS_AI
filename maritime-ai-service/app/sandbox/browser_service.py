"""Browser workload orchestration on top of the privileged sandbox layer."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.core.config import settings
from app.engine.context.browser_agent import (
    get_browser_limiter,
    validate_browser_url,
)
from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)
from app.sandbox.models import SandboxExecutionResult
from app.sandbox.service import (
    SandboxExecutionContext,
    SandboxExecutionService,
    get_sandbox_execution_service,
)

logger = logging.getLogger(__name__)

_RUNNER_PATH = Path(__file__).with_name("runners") / "browser_runner.mjs"
_RESULT_SENTINEL = "__WIII_BROWSER_RESULT__"
_DEFAULT_SCREENSHOT_LABEL = "Browser page loaded"
_VALID_WAIT_UNTIL = {"load", "domcontentloaded", "networkidle", "commit"}
_BROWSER_WORKDIR = "/opt/wiii-browser"
_RUNNER_FILE = f"{_BROWSER_WORKDIR}/browser_runner.mjs"
_JOB_FILE = f"{_BROWSER_WORKDIR}/browser_job.json"


def _safe_metadata(value: Any) -> dict[str, Any]:
    safe_value = sanitize_runtime_payload(value or {})
    return safe_value if isinstance(safe_value, dict) else {}


@dataclass(slots=True)
class BrowserAutomationRequest:
    """High-level request for a sandboxed browser navigation task."""

    url: str
    capture_screenshot: bool = True
    screenshot_label: str = _DEFAULT_SCREENSHOT_LABEL
    wait_until: str = "networkidle"
    full_page: bool = True
    viewport_width: int = 1440
    viewport_height: int = 1024
    timeout_seconds: Optional[int] = None
    tool_name: str = "browser_playwright"
    source: str = "tool_registry"
    node: Optional[str] = None
    organization_id: Optional[str] = None
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class BrowserAutomationResult:
    """Structured result returned by the browser sandbox orchestration layer."""

    success: bool
    requested_url: str
    final_url: str = ""
    page_title: str = ""
    page_excerpt: str = ""
    response_status: Optional[int] = None
    screenshot_base64: str = ""
    screenshot_label: str = _DEFAULT_SCREENSHOT_LABEL
    stdout: str = ""
    stderr: str = ""
    error: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)
    sandbox_result: Optional[SandboxExecutionResult] = None


class BrowserSandboxService:
    """Provider-neutral browser orchestration backed by sandbox workload profiles."""

    profile_id = "browser_playwright"

    def __init__(
        self,
        *,
        sandbox_service: Optional[SandboxExecutionService] = None,
        limiter_provider: Callable[[], Any] = get_browser_limiter,
        default_timeout_seconds: int = 120,
    ):
        self._sandbox_service = sandbox_service or get_sandbox_execution_service()
        self._limiter_provider = limiter_provider
        self._default_timeout_seconds = default_timeout_seconds

    async def execute(self, request: BrowserAutomationRequest) -> BrowserAutomationResult:
        """Execute a browser navigation task through the sandbox service."""
        validation_error = self.validate_request(request)
        if validation_error:
            return BrowserAutomationResult(
                success=False,
                requested_url=request.url,
                screenshot_label=request.screenshot_label or _DEFAULT_SCREENSHOT_LABEL,
                error=validation_error,
            )

        sandbox_result = await self._sandbox_service.execute_profile(
            self.profile_id,
            command=self.build_command(),
            files=self.build_files(request),
            timeout_seconds=request.timeout_seconds or self._default_timeout_seconds,
            runtime_template=getattr(settings, "opensandbox_browser_template", None) or None,
            working_directory=_BROWSER_WORKDIR,
            context=self.build_execution_context(request),
            metadata=self.build_execution_metadata(request),
        )
        return self.parse_result(request, sandbox_result)

    def execute_sync(self, request: BrowserAutomationRequest) -> BrowserAutomationResult:
        """Synchronous helper for tool surfaces."""
        validation_error = self.validate_request(request)
        if validation_error:
            return BrowserAutomationResult(
                success=False,
                requested_url=request.url,
                screenshot_label=request.screenshot_label or _DEFAULT_SCREENSHOT_LABEL,
                error=validation_error,
            )

        sandbox_result = self._sandbox_service.execute_profile_sync(
            self.profile_id,
            command=self.build_command(),
            files=self.build_files(request),
            timeout_seconds=request.timeout_seconds or self._default_timeout_seconds,
            runtime_template=getattr(settings, "opensandbox_browser_template", None) or None,
            working_directory=_BROWSER_WORKDIR,
            context=self.build_execution_context(request),
            metadata=self.build_execution_metadata(request),
        )
        return self.parse_result(request, sandbox_result)

    def validate_request(self, request: BrowserAutomationRequest) -> Optional[str]:
        """Reject invalid URLs and excessive session rates before sandbox startup."""
        url = (request.url or "").strip()
        if not url:
            return "Browser automation requires a non-empty URL."
        if not validate_browser_url(url):
            return "Browser URL failed validation. Only public http/https targets are allowed."
        if request.wait_until not in _VALID_WAIT_UNTIL:
            return (
                "Browser wait_until must be one of: "
                + ", ".join(sorted(_VALID_WAIT_UNTIL))
            )
        if request.viewport_width < 320 or request.viewport_height < 320:
            return "Browser viewport is too small for stable rendering."
        if request.user_id:
            limiter = self._limiter_provider()
            if limiter is not None and not limiter.check_and_increment(request.user_id):
                return "Browser session rate limit exceeded for this user."
        return None

    def build_execution_context(self, request: BrowserAutomationRequest) -> SandboxExecutionContext:
        """Translate browser request metadata into the shared sandbox execution context."""
        context_metadata = _safe_metadata(request.metadata)
        if request.node:
            context_metadata.setdefault("node", request.node)
        return SandboxExecutionContext(
            tool_name=request.tool_name,
            source=request.source,
            organization_id=request.organization_id,
            user_id=request.user_id,
            session_id=request.session_id,
            request_id=request.request_id,
            approval_scope="browser_automation",
            metadata=context_metadata,
        )

    def build_execution_metadata(self, request: BrowserAutomationRequest) -> dict[str, Any]:
        """Attach browser-specific metadata to the sandbox run."""
        metadata = _safe_metadata(request.metadata)
        metadata.setdefault("target_url", request.url)
        metadata.setdefault("capture_screenshot", request.capture_screenshot)
        metadata.setdefault("wait_until", request.wait_until)
        metadata.setdefault("viewport", {
            "width": request.viewport_width,
            "height": request.viewport_height,
        })
        metadata.setdefault("result_format", "wiii.browser.v1")
        return _safe_metadata(metadata)

    def build_command(self) -> list[str]:
        """Return the stable command used for all browser workload runs."""
        return ["node", _RUNNER_FILE, _JOB_FILE]

    def build_files(self, request: BrowserAutomationRequest) -> dict[str, str]:
        """Stage the runner script and job payload into the sandbox."""
        return {
            _RUNNER_FILE: self.load_runner_source(),
            _JOB_FILE: json.dumps(
                self.build_job_payload(request),
                ensure_ascii=True,
                sort_keys=True,
            ),
        }

    def build_job_payload(self, request: BrowserAutomationRequest) -> dict[str, Any]:
        """Build the JSON payload consumed by the sandbox-side runner."""
        timeout_ms = int((request.timeout_seconds or self._default_timeout_seconds) * 1000)
        return {
            "url": request.url,
            "capture_screenshot": request.capture_screenshot,
            "screenshot_label": request.screenshot_label or _DEFAULT_SCREENSHOT_LABEL,
            "wait_until": request.wait_until,
            "full_page": request.full_page,
            "timeout_ms": timeout_ms,
            "viewport": {
                "width": request.viewport_width,
                "height": request.viewport_height,
            },
        }

    def load_runner_source(self) -> str:
        """Load the checked-in browser runner template."""
        return _RUNNER_PATH.read_text(encoding="utf-8")

    def parse_result(
        self,
        request: BrowserAutomationRequest,
        sandbox_result: SandboxExecutionResult,
    ) -> BrowserAutomationResult:
        """Convert the generic sandbox result into the browser-specific result model."""
        metadata = _safe_metadata(sandbox_result.metadata)
        if not sandbox_result.success:
            return BrowserAutomationResult(
                success=False,
                requested_url=request.url,
                screenshot_label=request.screenshot_label or _DEFAULT_SCREENSHOT_LABEL,
                stdout=sandbox_result.stdout,
                stderr=sandbox_result.stderr,
                error=redact_runtime_secret_text(
                    sandbox_result.error or "Browser sandbox execution failed."
                ),
                metadata=metadata,
                sandbox_result=sandbox_result,
            )

        payload = self.extract_payload(sandbox_result.stdout)
        if payload is None:
            return BrowserAutomationResult(
                success=False,
                requested_url=request.url,
                screenshot_label=request.screenshot_label or _DEFAULT_SCREENSHOT_LABEL,
                stdout=sandbox_result.stdout,
                stderr=sandbox_result.stderr,
                error=redact_runtime_secret_text(
                    "Browser sandbox did not return a structured result payload."
                ),
                metadata=metadata,
                sandbox_result=sandbox_result,
            )

        return BrowserAutomationResult(
            success=True,
            requested_url=request.url,
            final_url=str(payload.get("final_url") or payload.get("requested_url") or request.url),
            page_title=str(payload.get("title") or ""),
            page_excerpt=str(payload.get("excerpt") or ""),
            response_status=_safe_int(payload.get("response_status")),
            screenshot_base64=str(payload.get("screenshot_base64") or ""),
            screenshot_label=str(payload.get("label") or request.screenshot_label or _DEFAULT_SCREENSHOT_LABEL),
            stdout=sandbox_result.stdout,
            stderr=sandbox_result.stderr,
            metadata=metadata,
            sandbox_result=sandbox_result,
        )

    def extract_payload(self, stdout: str) -> Optional[dict[str, Any]]:
        """Extract the structured runner payload from noisy command stdout."""
        for line in reversed((stdout or "").splitlines()):
            if not line.startswith(_RESULT_SENTINEL):
                continue
            payload = line[len(_RESULT_SENTINEL):]
            try:
                loaded = json.loads(payload)
            except json.JSONDecodeError as exc:
                logger.warning("Invalid browser runner payload: %s", exc)
                return None
            return loaded if isinstance(loaded, dict) else None
        return None

    def build_tool_summary(self, result: BrowserAutomationResult) -> str:
        """Format a browser result into a compact tool-facing summary string."""
        if not result.success:
            parts = []
            if result.error:
                parts.append(f"Browser run failed: {result.error}")
            if result.stderr:
                parts.append(f"Stderr:\n{result.stderr.strip()}")
            return "\n\n".join(parts) if parts else "Browser run failed."

        parts = [
            "Browser run succeeded.",
            f"Title: {result.page_title or '(untitled)'}",
            f"Final URL: {result.final_url or result.requested_url}",
        ]
        if result.response_status is not None:
            parts.append(f"HTTP status: {result.response_status}")
        if result.page_excerpt:
            parts.append(f"Excerpt: {result.page_excerpt}")
        if result.screenshot_base64:
            parts.append("Screenshot captured in sandbox result.")
        return "\n".join(parts)

    def build_screenshot_bus_event(
        self,
        result: BrowserAutomationResult,
        *,
        node: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Build a browser_screenshot bus payload compatible with existing SSE flow."""
        if not result.success or not result.screenshot_base64:
            return None
        return {
            "type": "browser_screenshot",
            "content": {
                "url": result.final_url or result.requested_url,
                "image": result.screenshot_base64,
                "label": result.screenshot_label,
                "metadata": self.build_correlation_metadata(result),
            },
            "node": node,
        }

    def build_artifact_bus_event(
        self,
        result: BrowserAutomationResult,
        *,
        node: Optional[str] = None,
        artifact_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Build an artifact payload summarizing the browser session result."""
        return {
            "type": "artifact",
            "content": {
                "artifact_type": "document",
                "artifact_id": artifact_id or f"browser-{int(time.time() * 1000)}",
                "title": result.page_title or "Browser Capture",
                "content": self.build_artifact_document(result),
                "language": "",
                "metadata": {
                    "url": result.final_url or result.requested_url,
                    "response_status": result.response_status,
                    "success": result.success,
                    **self.build_correlation_metadata(result),
                },
            },
            "node": node,
        }

    def build_artifact_document(self, result: BrowserAutomationResult) -> str:
        """Create a markdown summary suitable for the artifact renderer."""
        lines = [
            f"# {result.page_title or 'Browser Capture'}",
            "",
            f"- Requested URL: {result.requested_url}",
            f"- Final URL: {result.final_url or result.requested_url}",
            f"- Success: {'yes' if result.success else 'no'}",
        ]
        if result.response_status is not None:
            lines.append(f"- HTTP status: {result.response_status}")
        if result.page_excerpt:
            lines.extend(["", "## Excerpt", "", result.page_excerpt])
        if result.error:
            lines.extend(["", "## Error", "", result.error])
        return "\n".join(lines)

    def build_correlation_metadata(
        self,
        result: BrowserAutomationResult,
    ) -> dict[str, Any]:
        """Expose sandbox correlation metadata in browser stream payloads."""
        metadata = _safe_metadata(result.metadata)
        sandbox_result = result.sandbox_result
        if sandbox_result and sandbox_result.sandbox_id:
            metadata.setdefault("sandbox_id", sandbox_result.sandbox_id)
        if sandbox_result and sandbox_result.duration_ms is not None:
            metadata.setdefault("duration_ms", sandbox_result.duration_ms)
        return _safe_metadata(metadata)


def _safe_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_browser_sandbox_service() -> BrowserSandboxService:
    """Create a browser sandbox service using current settings."""
    try:
        from app.core.config import get_settings

        settings = get_settings()
        default_timeout_seconds = int(getattr(settings, "browser_agent_timeout", 120))
    except Exception:
        default_timeout_seconds = 120
    return BrowserSandboxService(default_timeout_seconds=default_timeout_seconds)
