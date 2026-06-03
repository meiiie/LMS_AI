"""OpenSandbox control-plane adapter for Wiii's privileged execution layer."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

from app.core.config import Settings
from app.engine.runtime.event_payload_sanitizer import (
    hash_runtime_identifier,
    sanitize_runtime_payload,
)
from app.sandbox.base import SandboxExecutor
from app.sandbox.opensandbox_artifacts import (
    attach_inline_content_impl,
    build_sandbox_file_artifact_impl,
    coerce_execution_artifact_impl,
    collect_artifacts_impl,
    encode_inline_image,
    filename_from_ref,
    guess_content_type,
    harvest_sandbox_files_impl,
    read_sandbox_file_content_impl,
    should_inline_file_impl,
)
from app.sandbox.opensandbox_runtime_support import (
    build_execution_result_impl,
    build_search_entry_impl,
    build_search_roots_impl,
    cleanup_sandbox_impl,
    coerce_text_content_impl,
    is_image_content_impl,
    normalize_path_impl,
    publish_harvested_file_impl,
    read_field_impl,
)
from app.sandbox.opensandbox_executor_runtime import (
    build_command_text_impl,
    build_connection_config_impl,
    build_network_policy_impl,
    build_provider_metadata_impl,
    build_sandbox_metadata_impl,
    execute_command_workload_impl,
    execute_impl,
    execute_python_workload_impl,
    extract_execution_artifacts_impl,
    healthcheck_impl,
    prepare_code_impl,
    stringify_metadata_value_impl,
    stage_files_impl,
    to_label_safe_value_impl,
    validate_request_impl,
    create_sandbox_impl,
)
from app.sandbox.models import (
    SandboxArtifact,
    SandboxExecutionRequest,
    SandboxExecutionResult,
    SandboxNetworkMode,
    SandboxProvider,
    SandboxWorkloadKind,
)

logger = logging.getLogger(__name__)


def _safe_metadata(value: Any) -> dict[str, Any]:
    safe_value = sanitize_runtime_payload(value or {})
    return safe_value if isinstance(safe_value, dict) else {}


@dataclass(slots=True)
class OpenSandboxExecutionPlan:
    """Resolved Wiii-side execution plan before provider API mapping."""

    image: str
    network_mode: SandboxNetworkMode
    timeout_seconds: int
    labels: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OpenSandboxSdk:
    """Optional OpenSandbox SDK surface loaded lazily at runtime."""

    code_interpreter: Any
    connection_config: Any
    network_policy: Any
    run_command_opts: Any
    sandbox: Any
    supported_language: Any
    write_entry: Any
    search_entry: Any = None


_ARTIFACT_GLOB_PATTERNS = (
    "*.html",
    "*.htm",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.webp",
    "*.svg",
    "*.csv",
    "*.json",
    "*.xlsx",
    "*.docx",
    "*.pdf",
    "*.md",
    "*.txt",
)
_TEXT_INLINE_LIMIT = 160_000
_IMAGE_INLINE_LIMIT = 2_500_000
_MAX_HARVESTED_ARTIFACTS = 12


def _load_opensandbox_sdk() -> OpenSandboxSdk:
    """Import the optional OpenSandbox SDK only when execution is requested."""
    from code_interpreter import CodeInterpreter, SupportedLanguage
    from opensandbox.adapters.converter.sandbox_model_converter import SandboxModelConverter
    from opensandbox import Sandbox
    from opensandbox.config import ConnectionConfig
    from opensandbox.models.execd import RunCommandOpts

    try:
        from opensandbox.models.filesystem import SearchEntry, WriteEntry
    except Exception:  # pragma: no cover - fallback for older SDK exports
        from opensandbox.models import SearchEntry, WriteEntry

    try:
        from opensandbox.models.sandboxes import NetworkPolicy
    except Exception:  # pragma: no cover - fallback for older SDK exports
        from opensandbox.models import NetworkPolicy

    if not getattr(SandboxModelConverter, "_wiii_endpoint_patch", False):
        original_to_sandbox_endpoint = SandboxModelConverter.to_sandbox_endpoint

        def _patched_to_sandbox_endpoint(api_endpoint: Any) -> Any:
            endpoint = original_to_sandbox_endpoint(api_endpoint)
            endpoint_value = getattr(endpoint, "endpoint", "")
            parsed = urlparse(
                endpoint_value if "://" in endpoint_value else f"http://{endpoint_value}"
            )
            if re.fullmatch(r"/proxy/\d+", parsed.path or "") and parsed.port:
                normalized = f"host.docker.internal:{parsed.port}"
                logger.warning(
                    "Normalizing OpenSandbox direct endpoint from '%s' to '%s'",
                    endpoint_value,
                    normalized,
                )
                endpoint.endpoint = normalized
            return endpoint

        SandboxModelConverter.to_sandbox_endpoint = staticmethod(_patched_to_sandbox_endpoint)
        SandboxModelConverter._wiii_endpoint_patch = True

    return OpenSandboxSdk(
        code_interpreter=CodeInterpreter,
        connection_config=ConnectionConfig,
        network_policy=NetworkPolicy,
        run_command_opts=RunCommandOpts,
        sandbox=Sandbox,
        supported_language=SupportedLanguage,
        write_entry=WriteEntry,
        search_entry=SearchEntry,
    )


class OpenSandboxExecutor(SandboxExecutor):
    """Adapter for an external OpenSandbox deployment."""

    def __init__(
        self,
        *,
        base_url: Optional[str],
        api_key: Optional[str],
        timeout_seconds: int,
        healthcheck_path: str,
        code_template: str,
        browser_template: str,
        network_mode: SandboxNetworkMode,
        keepalive_seconds: int,
        allow_browser_workloads: bool,
    ):
        self._base_url = (base_url or "").rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._healthcheck_path = healthcheck_path or "/health"
        self._code_template = code_template
        self._browser_template = browser_template
        self._network_mode = network_mode
        self._keepalive_seconds = keepalive_seconds
        self._allow_browser_workloads = allow_browser_workloads

    @classmethod
    def from_settings(cls, settings: Settings) -> "OpenSandboxExecutor":
        return cls(
            base_url=settings.opensandbox_base_url,
            api_key=settings.opensandbox_api_key,
            timeout_seconds=settings.sandbox_default_timeout_seconds,
            healthcheck_path=settings.opensandbox_healthcheck_path,
            code_template=settings.opensandbox_code_template,
            browser_template=settings.opensandbox_browser_template,
            network_mode=SandboxNetworkMode(settings.opensandbox_network_mode),
            keepalive_seconds=settings.opensandbox_keepalive_seconds,
            allow_browser_workloads=settings.sandbox_allow_browser_workloads,
        )

    @property
    def provider(self) -> SandboxProvider:
        return SandboxProvider.OPENSANDBOX

    def is_configured(self) -> bool:
        return bool(self._base_url)

    def select_image(self, request: SandboxExecutionRequest) -> str:
        """Select the OpenSandbox runtime image for this workload."""
        if request.runtime_template:
            return request.runtime_template
        if request.workload_kind == SandboxWorkloadKind.BROWSER:
            return self._browser_template
        return self._code_template

    def select_template(self, request: SandboxExecutionRequest) -> str:
        """Backward-compatible alias for older callers/tests."""
        return self.select_image(request)

    def build_labels(self, request: SandboxExecutionRequest) -> dict[str, str]:
        """Build stable labels for provider-side tracing and cleanup."""
        labels = {"wiii.provider": self.provider.value}
        if request.organization_id:
            labels["wiii.org"] = request.organization_id
        if request.user_id:
            user_id_hash = hash_runtime_identifier(request.user_id)
            if user_id_hash:
                labels["wiii.user"] = user_id_hash
        if request.session_id:
            labels["wiii.session"] = request.session_id
        if request.request_id:
            labels["wiii.request"] = request.request_id
        labels["wiii.workload"] = request.workload_kind.value
        return labels

    def plan(self, request: SandboxExecutionRequest) -> OpenSandboxExecutionPlan:
        """Resolve Wiii policy into an OpenSandbox-facing execution plan."""
        timeout_seconds = request.timeout_seconds or self._timeout_seconds
        network_mode = request.network_mode or self._network_mode
        metadata = {
            "keepalive_seconds": self._keepalive_seconds,
            **request.metadata,
        }
        return OpenSandboxExecutionPlan(
            image=self.select_image(request),
            network_mode=network_mode,
            timeout_seconds=timeout_seconds,
            labels=self.build_labels(request),
            metadata=_safe_metadata(metadata),
        )

    def build_network_policy(
        self,
        network_mode: SandboxNetworkMode,
        network_policy_cls: Any,
    ) -> Any:
        return build_network_policy_impl(network_mode, network_policy_cls)

    def build_connection_config(self, timeout_seconds: int, sdk: OpenSandboxSdk) -> Any:
        return build_connection_config_impl(
            base_url=self._base_url,
            api_key=self._api_key,
            timeout_seconds=timeout_seconds,
            sdk=sdk,
        )

    def build_provider_metadata(
        self,
        plan: OpenSandboxExecutionPlan,
        request: SandboxExecutionRequest,
    ) -> dict[str, Any]:
        return build_provider_metadata_impl(
            provider_value=self.provider.value,
            plan=plan,
            request=request,
        )

    def build_sandbox_metadata(
        self,
        plan: OpenSandboxExecutionPlan,
    ) -> dict[str, str]:
        return build_sandbox_metadata_impl(plan)

    def stringify_metadata_value(self, value: Any) -> str:
        return stringify_metadata_value_impl(value)

    def to_label_safe_value(self, value: Any) -> str:
        return to_label_safe_value_impl(value)

    def prepare_code(self, request: SandboxExecutionRequest) -> str:
        return prepare_code_impl(request)

    def build_command_text(self, request: SandboxExecutionRequest) -> str:
        return build_command_text_impl(request)

    async def healthcheck(self) -> bool:
        return await healthcheck_impl(
            is_configured=self.is_configured(),
            base_url=self._base_url,
            api_key=self._api_key,
            healthcheck_path=self._healthcheck_path,
            async_client_cls=httpx.AsyncClient,
            logger=logger,
        )

    async def execute(
        self,
        request: SandboxExecutionRequest,
    ) -> SandboxExecutionResult:
        plan = self.plan(request)
        provider_metadata = self.build_provider_metadata(plan, request)
        return await execute_impl(
            plan=plan,
            request=request,
            provider_metadata=provider_metadata,
            is_configured=self.is_configured(),
            allow_browser_workloads=self._allow_browser_workloads,
            load_sdk_fn=_load_opensandbox_sdk,
            validate_request_fn=self.validate_request,
            create_sandbox_fn=self.create_sandbox,
            stage_files_fn=self.stage_files,
            execute_python_workload_fn=self.execute_python_workload,
            execute_command_workload_fn=self.execute_command_workload,
            build_execution_result_fn=self.build_execution_result,
            cleanup_sandbox_fn=self.cleanup_sandbox,
            result_cls=SandboxExecutionResult,
            workload_kind_cls=SandboxWorkloadKind,
            logger=logger,
        )

    def validate_request(self, request: SandboxExecutionRequest) -> Optional[str]:
        return validate_request_impl(request)

    async def create_sandbox(
        self,
        *,
        plan: OpenSandboxExecutionPlan,
        request: SandboxExecutionRequest,
        sdk: OpenSandboxSdk,
    ) -> Any:
        return await create_sandbox_impl(
            plan=plan,
            request=request,
            sdk=sdk,
            build_sandbox_metadata_fn=self.build_sandbox_metadata,
            build_network_policy_fn=self.build_network_policy,
            build_connection_config_fn=self.build_connection_config,
        )

    async def stage_files(
        self,
        *,
        sandbox: Any,
        request: SandboxExecutionRequest,
        sdk: OpenSandboxSdk,
    ) -> None:
        await stage_files_impl(
            sandbox=sandbox,
            request=request,
            sdk=sdk,
        )

    async def execute_python_workload(
        self,
        *,
        sandbox: Any,
        request: SandboxExecutionRequest,
        plan: OpenSandboxExecutionPlan,
        sdk: OpenSandboxSdk,
    ) -> Any:
        return await execute_python_workload_impl(
            sandbox=sandbox,
            request=request,
            plan=plan,
            sdk=sdk,
            prepare_code_fn=self.prepare_code,
        )

    async def execute_command_workload(
        self,
        *,
        sandbox: Any,
        request: SandboxExecutionRequest,
        plan: OpenSandboxExecutionPlan,
        sdk: OpenSandboxSdk,
    ) -> Any:
        return await execute_command_workload_impl(
            sandbox=sandbox,
            request=request,
            plan=plan,
            sdk=sdk,
            build_command_text_fn=self.build_command_text,
        )

    async def build_execution_result(
        self,
        *,
        execution: Any,
        sandbox: Any,
        request: SandboxExecutionRequest,
        sdk: OpenSandboxSdk,
        sandbox_id: Optional[str],
        provider_metadata: dict[str, Any],
    ) -> SandboxExecutionResult:
        """Normalize the SDK execution model into Wiii's provider-neutral result."""
        return await build_execution_result_impl(
            execution=execution,
            sandbox=sandbox,
            request=request,
            sdk=sdk,
            sandbox_id=sandbox_id,
            provider_metadata=provider_metadata,
            collect_artifacts_fn=self.collect_artifacts,
            result_cls=SandboxExecutionResult,
        )

    async def collect_artifacts(
        self,
        *,
        execution: Any,
        sandbox: Any,
        request: SandboxExecutionRequest,
        sdk: OpenSandboxSdk,
    ) -> list[SandboxArtifact]:
        """Harvest explicit execution artifacts plus generated sandbox files."""
        return await collect_artifacts_impl(
            execution=execution,
            sandbox=sandbox,
            request=request,
            sdk=sdk,
            extract_execution_artifacts_fn=self._extract_execution_artifacts,
            harvest_sandbox_files_fn=self._harvest_sandbox_files,
            max_harvested_artifacts=_MAX_HARVESTED_ARTIFACTS,
        )

    def _extract_execution_artifacts(
        self,
        execution: Any,
    ) -> list[SandboxArtifact]:
        return extract_execution_artifacts_impl(
            execution,
            coerce_execution_artifact_fn=self._coerce_execution_artifact,
        )

    def _coerce_execution_artifact(self, item: Any) -> Optional[SandboxArtifact]:
        """Normalize loose SDK artifact objects into Wiii sandbox artifacts."""
        return coerce_execution_artifact_impl(
            item,
            read_field_fn=self._read_field,
            guess_content_type_fn=self._guess_content_type,
            filename_from_ref_fn=self._filename_from_ref,
            sandbox_artifact_cls=SandboxArtifact,
            attach_inline_content_fn=self._attach_inline_content,
        )

    async def _harvest_sandbox_files(
        self,
        *,
        sandbox: Any,
        request: SandboxExecutionRequest,
        sdk: OpenSandboxSdk,
    ) -> list[SandboxArtifact]:
        """Search common execution directories for user-visible generated files."""
        return await harvest_sandbox_files_impl(
            sandbox=sandbox,
            request=request,
            sdk=sdk,
            normalize_path_fn=self._normalize_path,
            build_search_roots_fn=self._build_search_roots,
            read_field_fn=self._read_field,
            build_sandbox_file_artifact_fn=self._build_sandbox_file_artifact,
            artifact_glob_patterns=_ARTIFACT_GLOB_PATTERNS,
            max_harvested_artifacts=_MAX_HARVESTED_ARTIFACTS,
            logger=logger,
        )

    async def _build_sandbox_file_artifact(
        self,
        *,
        files_api: Any,
        path: str,
    ) -> Optional[SandboxArtifact]:
        """Create an artifact record from a sandbox-side file path."""
        return await build_sandbox_file_artifact_impl(
            files_api=files_api,
            path=path,
            guess_content_type_fn=self._guess_content_type,
            sandbox_artifact_cls=SandboxArtifact,
            read_sandbox_file_content_fn=self._read_sandbox_file_content,
            publish_harvested_file_fn=self._publish_harvested_file,
            should_inline_file_fn=self._should_inline_file,
            attach_inline_content_fn=self._attach_inline_content,
            filename_from_ref_fn=self._filename_from_ref,
        )

    async def _read_sandbox_file_content(
        self,
        *,
        files_api: Any,
        path: str,
    ) -> Any:
        """Read a sandbox file using the most binary-safe API available."""
        return await read_sandbox_file_content_impl(
            files_api=files_api,
            path=path,
            logger=logger,
        )

    def _publish_harvested_file(
        self,
        filename: str,
        raw_content: Any,
    ) -> Optional[Path]:
        """Persist a harvested sandbox file into Wiii's generated workspace."""
        return publish_harvested_file_impl(filename, raw_content)

    def _build_search_roots(self, working_directory: Optional[str]) -> list[str]:
        return build_search_roots_impl(working_directory, self._normalize_path)

    def _build_search_entry(
        self,
        path: str,
        pattern: str,
        sdk: OpenSandboxSdk,
    ) -> Any:
        return build_search_entry_impl(path, pattern, sdk)

    def _attach_inline_content(
        self,
        artifact: SandboxArtifact,
        raw_content: Any,
        fallback_name: str,
    ) -> None:
        """Attach inline text/base64 content when it is useful and safe."""
        attach_inline_content_impl(
            artifact,
            raw_content,
            fallback_name,
            guess_content_type_fn=self._guess_content_type,
            is_image_content_fn=self._is_image_content,
            encode_inline_image_fn=self._encode_inline_image,
            coerce_text_content_fn=self._coerce_text_content,
            text_inline_limit=_TEXT_INLINE_LIMIT,
        )

    def _coerce_text_content(self, raw_content: Any) -> Optional[str]:
        return coerce_text_content_impl(raw_content)

    def _encode_inline_image(self, raw_content: Any) -> Optional[str]:
        return encode_inline_image(raw_content, image_inline_limit=_IMAGE_INLINE_LIMIT)

    def _guess_content_type(self, ref: Optional[str]) -> str:
        return guess_content_type(ref)

    def _filename_from_ref(self, ref: Optional[str]) -> Optional[str]:
        return filename_from_ref(ref)

    def _normalize_path(self, value: Optional[str]) -> str:
        return normalize_path_impl(value)

    def _read_field(self, item: Any, *names: str) -> Any:
        return read_field_impl(item, *names)

    def _should_inline_file(self, content_type: str, path: str) -> bool:
        return should_inline_file_impl(
            content_type,
            path,
            is_image_content_fn=self._is_image_content,
        )

    def _is_image_content(self, content_type: str) -> bool:
        return is_image_content_impl(content_type)

    async def cleanup_sandbox(self, sandbox: Any) -> None:
        await cleanup_sandbox_impl(sandbox=sandbox, logger=logger)
