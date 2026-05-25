"""Privacy-safe runtime flow ledger for Wiii chat turns."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.engine.multi_agent.context_provenance_ledger import (
    build_context_provenance_ledger,
    build_request_context_provenance_ledger,
)


RUNTIME_FLOW_LEDGER_SCHEMA_VERSION = "wiii.runtime_flow_ledger.v1"
_MAX_TOKEN_LENGTH = 96
_MAX_SEQUENCE_ITEMS = 24


def _hash_identifier(value: Any) -> str | None:
    token = str(value or "").strip()
    if not token:
        return None
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def _safe_token(value: Any, *, max_length: int = _MAX_TOKEN_LENGTH) -> str | None:
    if value is None:
        return None
    token = str(value).strip()
    if not token:
        return None
    token = " ".join(token.split())
    if len(token) > max_length:
        return token[: max_length - 1] + "..."
    return token


def _safe_token_list(values: Any) -> list[str]:
    if not isinstance(values, (list, tuple, set)):
        return []
    tokens: list[str] = []
    for value in values:
        token = _safe_token(value)
        if token and token not in tokens:
            tokens.append(token)
        if len(tokens) >= _MAX_SEQUENCE_ITEMS:
            break
    return tokens


def _plain_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "model_dump"):
        model_value = value.model_dump()
        return model_value if isinstance(model_value, Mapping) else {}
    if hasattr(value, "dict"):
        dict_value = value.dict()
        return dict_value if isinstance(dict_value, Mapping) else {}
    return {}


def _context_value(source: Any, key: str) -> Any:
    if isinstance(source, Mapping):
        return source.get(key)
    return getattr(source, key, None)


def _host_context_from_request(chat_request: Any) -> Mapping[str, Any]:
    user_context = _context_value(chat_request, "user_context")
    host_context = _context_value(user_context, "host_context")
    return _plain_mapping(host_context)


def _document_context_from_request(chat_request: Any) -> Mapping[str, Any]:
    user_context = _context_value(chat_request, "user_context")
    document_context = _context_value(user_context, "document_context")
    return _plain_mapping(document_context)


def _uploaded_document_count(chat_request: Any) -> int:
    document_context = _document_context_from_request(chat_request)
    attachments = document_context.get("attachments")
    if not isinstance(attachments, list):
        return 0
    return sum(
        1
        for item in attachments
        if isinstance(item, Mapping) and bool(str(item.get("markdown") or "").strip())
    )


def _host_surface(host_context: Mapping[str, Any]) -> str:
    for key in ("surface", "host_surface", "app_surface", "client", "source"):
        token = _safe_token(host_context.get(key))
        if token:
            return token
    return "unknown"


def _host_capabilities(host_context: Mapping[str, Any]) -> list[str]:
    capabilities = _safe_token_list(host_context.get("capabilities"))
    if capabilities:
        return capabilities
    if not host_context:
        return []
    safe_keys = {
        "lms",
        "document_preview",
        "host_action",
        "pointy",
        "visual",
        "code_studio",
    }
    return sorted(key for key in safe_keys if bool(host_context.get(key)))


def _source_count(value: Any) -> int:
    if isinstance(value, (list, tuple)):
        return len(value)
    if isinstance(value, Mapping):
        sources = (
            value.get("sources")
            or value.get("source_refs")
            or value.get("source_references")
            or value.get("citations")
        )
        if isinstance(sources, (list, tuple)):
            return len(sources)
    return 0


def _event_tool_name(event_type: str, content: Any) -> str | None:
    if event_type in {
        "visual",
        "visual_open",
        "visual_patch",
        "visual_commit",
        "visual_dispose",
    }:
        return "visual_runtime"
    if event_type in {"code_open", "code_delta", "code_complete"}:
        return "code_studio"
    if event_type == "preview":
        return "preview"
    if not isinstance(content, Mapping):
        if event_type in {"tool_call", "tool_result", "host_action", "pointy_action"}:
            return event_type
        return None
    for key in ("tool_name", "name", "tool", "action", "type"):
        token = _safe_token(content.get(key))
        if token:
            return token
    if event_type in {"tool_call", "tool_result", "host_action", "pointy_action"}:
        return event_type
    return None


def _preserve_provenance_section(
    provenance: dict[str, Any],
    previous: Mapping[str, Any],
    *,
    section: str,
    count_key: str,
) -> None:
    current_section = provenance.get(section)
    previous_section = previous.get(section)
    if not isinstance(current_section, Mapping) or not isinstance(
        previous_section,
        Mapping,
    ):
        return
    if int(current_section.get(count_key) or 0) == 0 and int(
        previous_section.get(count_key) or 0
    ) > 0:
        provenance[section] = dict(previous_section)


def _preserve_request_provenance(
    provenance: dict[str, Any],
    previous: dict[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(previous, Mapping):
        return provenance
    _preserve_provenance_section(
        provenance,
        previous,
        section="documents",
        count_key="usable_attachment_count",
    )
    current_host = provenance.get("host")
    previous_host = previous.get("host")
    if (
        isinstance(current_host, Mapping)
        and isinstance(previous_host, Mapping)
        and not current_host.get("host_context_present")
        and previous_host.get("host_context_present")
    ):
        provenance["host"] = dict(previous_host)
    warnings = provenance.get("warnings")
    documents = provenance.get("documents")
    if isinstance(warnings, list) and isinstance(documents, Mapping):
        if (
            int(documents.get("usable_attachment_count") or 0) > 0
            and int(documents.get("source_ref_count") or 0) == 0
            and "document_context_without_source_refs" not in warnings
        ):
            warnings.append("document_context_without_source_refs")
    return provenance


@dataclass
class RuntimeFlowLedger:
    """Mutable recorder that serializes to a stable, privacy-safe payload."""

    request_id: str | None
    provider_requested: str | None = None
    model_requested: str | None = None
    session_id: str | None = None
    user_id_hash: str | None = None
    organization_id_hash: str | None = None
    domain_id: str | None = None
    host_surface: str = "unknown"
    host_capabilities: list[str] = field(default_factory=list)
    document_context_present: bool = False
    uploaded_document_count: int = 0
    route_lane: str = "preparing"
    route_reason: str | None = None
    selected_agent: str | None = None
    final_agent: str | None = None
    provider: str | None = None
    model: str | None = None
    runtime_authoritative: bool | None = None
    fallback_used: bool = False
    fallback_reason: str | None = None
    failover_used: bool = False
    observed_tools: list[str] = field(default_factory=list)
    suppressed_tools: list[str] = field(default_factory=list)
    event_counts: dict[str, int] = field(default_factory=dict)
    event_sequence_tail: list[str] = field(default_factory=list)
    metadata_seen: bool = False
    done_seen: bool = False
    source_ref_count: int = 0
    memory_context_count: int | None = None
    context_provenance: dict[str, Any] | None = None
    preview_required: bool = False
    preview_emitted: bool = False
    approval_token_present: bool = False
    approval_token_hash: str | None = None
    apply_attempted: bool = False
    mutation_blocked_reason: str | None = None
    finalization_status: str = "pending"
    finalization_error_type: str | None = None
    save_response_immediately: bool | None = None

    @classmethod
    def from_chat_request(
        cls,
        *,
        chat_request: Any,
        request_id: str | None,
    ) -> "RuntimeFlowLedger":
        host_context = _host_context_from_request(chat_request)
        uploaded_count = _uploaded_document_count(chat_request)
        host_capabilities = _host_capabilities(host_context)
        return cls(
            request_id=_safe_token(request_id),
            provider_requested=_safe_token(_context_value(chat_request, "provider")),
            model_requested=_safe_token(_context_value(chat_request, "model")),
            user_id_hash=_hash_identifier(_context_value(chat_request, "user_id")),
            host_surface=_host_surface(host_context),
            host_capabilities=host_capabilities,
            document_context_present=uploaded_count > 0,
            uploaded_document_count=uploaded_count,
            context_provenance=build_request_context_provenance_ledger(
                chat_request
            ),
            preview_required=uploaded_count > 0 and "lms" in host_capabilities,
        )

    def mark_prepared_turn(
        self,
        *,
        session_id: Any,
        organization_id: Any,
        domain_id: Any,
    ) -> None:
        self.session_id = _safe_token(session_id)
        self.organization_id_hash = _hash_identifier(organization_id)
        self.domain_id = _safe_token(domain_id)

    def mark_route(
        self,
        lane: str,
        *,
        reason: str | None = None,
        fallback_used: bool | None = None,
        fallback_reason: str | None = None,
    ) -> None:
        self.route_lane = _safe_token(lane) or "unknown"
        self.route_reason = _safe_token(reason)
        if fallback_used is not None:
            self.fallback_used = fallback_used
        if fallback_reason:
            self.fallback_reason = _safe_token(fallback_reason)

    def mark_execution_input(self, execution_input: Any) -> None:
        self.provider = self.provider or _safe_token(
            _context_value(execution_input, "provider")
        )
        self.model = self.model or _safe_token(
            _context_value(execution_input, "model")
        )
        context = _plain_mapping(_context_value(execution_input, "context"))
        self.context_provenance = _preserve_request_provenance(
            build_context_provenance_ledger(context),
            self.context_provenance,
        )
        documents = self.context_provenance.get("documents", {})
        if isinstance(documents, Mapping):
            uploaded_count = int(documents.get("usable_attachment_count") or 0)
            if uploaded_count > 0:
                self.document_context_present = True
                self.uploaded_document_count = max(
                    self.uploaded_document_count,
                    uploaded_count,
                )
            self.source_ref_count = max(
                self.source_ref_count,
                int(documents.get("source_ref_count") or 0),
            )

        source_refs = (
            context.get("source_refs")
            or context.get("sources")
            or context.get("source_references")
            or context.get("citations")
        )
        self.source_ref_count = max(self.source_ref_count, _source_count(source_refs))
        memories = context.get("memories") or context.get("semantic_memories")
        if isinstance(memories, (list, tuple)):
            self.memory_context_count = len(memories)
        memory = self.context_provenance.get("memory", {})
        if isinstance(memory, Mapping) and isinstance(
            memory.get("semantic_memory_count"),
            int,
        ):
            self.memory_context_count = memory.get("semantic_memory_count")

    def record_event(self, event: Any) -> None:
        event_type = _safe_token(getattr(event, "type", None)) or "unknown"
        content = getattr(event, "content", None)
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        self.event_sequence_tail.append(event_type)
        if len(self.event_sequence_tail) > _MAX_SEQUENCE_ITEMS:
            self.event_sequence_tail = self.event_sequence_tail[-_MAX_SEQUENCE_ITEMS:]
        if event_type == "metadata":
            self.metadata_seen = True
        elif event_type == "done":
            self.done_seen = True
        elif event_type == "sources":
            self.source_ref_count = max(self.source_ref_count, _source_count(content))
        elif event_type in {
            "tool_call",
            "tool_result",
            "host_action",
            "pointy_action",
            "preview",
            "visual",
            "visual_open",
            "visual_patch",
            "visual_commit",
            "visual_dispose",
            "code_open",
            "code_delta",
            "code_complete",
        }:
            self._record_tool_event(event_type, content)

    def record_wire_event(self, event_type: str) -> None:
        event_type = _safe_token(event_type) or "unknown"
        self.event_counts[event_type] = self.event_counts.get(event_type, 0) + 1
        self.event_sequence_tail.append(event_type)
        if len(self.event_sequence_tail) > _MAX_SEQUENCE_ITEMS:
            self.event_sequence_tail = self.event_sequence_tail[-_MAX_SEQUENCE_ITEMS:]
        if event_type == "metadata":
            self.metadata_seen = True
        elif event_type == "done":
            self.done_seen = True

    def observe_metadata(self, metadata: Mapping[str, Any]) -> None:
        self.metadata_seen = True
        self.provider = self.provider or _safe_token(metadata.get("provider"))
        self.model = self.model or _safe_token(metadata.get("model"))
        runtime_authoritative = metadata.get("runtime_authoritative")
        if isinstance(runtime_authoritative, bool):
            self.runtime_authoritative = runtime_authoritative
        self.selected_agent = self.selected_agent or _safe_token(metadata.get("agent_type"))

        routing_metadata = metadata.get("routing_metadata")
        if isinstance(routing_metadata, Mapping):
            self.selected_agent = self.selected_agent or _safe_token(
                routing_metadata.get("selected_agent")
                or routing_metadata.get("target_agent")
            )
            self.final_agent = self.final_agent or _safe_token(
                routing_metadata.get("final_agent")
            )
            if not self.route_reason:
                self.route_reason = _safe_token(
                    routing_metadata.get("method") or routing_metadata.get("intent")
                )

        failover = metadata.get("failover")
        if isinstance(failover, Mapping):
            switched = failover.get("switched")
            self.failover_used = bool(switched)
            self.fallback_reason = self.fallback_reason or _safe_token(
                failover.get("last_reason_code") or failover.get("last_reason_category")
            )

        token = metadata.get("approval_token")
        token_hash = metadata.get("approval_token_hash")
        if token:
            self.approval_token_present = True
            self.approval_token_hash = _hash_identifier(token)
        elif token_hash:
            self.approval_token_present = True
            self.approval_token_hash = _safe_token(token_hash)

    def mark_finalization(
        self,
        status: str,
        *,
        error: Exception | None = None,
        save_response_immediately: bool | None = None,
    ) -> None:
        self.finalization_status = _safe_token(status) or "unknown"
        self.finalization_error_type = type(error).__name__ if error else None
        self.save_response_immediately = save_response_immediately

    def _record_tool_event(self, event_type: str, content: Any) -> None:
        tool_name = _event_tool_name(event_type, content)
        if tool_name and tool_name not in self.observed_tools:
            self.observed_tools.append(tool_name)
        if event_type == "preview":
            self.preview_emitted = True
        if isinstance(content, Mapping):
            action = _safe_token(
                content.get("action") or content.get("type") or content.get("name")
            )
            if action and "preview" in action.lower():
                self.preview_emitted = True
            if action and "apply" in action.lower():
                self.apply_attempted = True
            token = content.get("approval_token")
            token_hash = content.get("approval_token_hash")
            if token:
                self.approval_token_present = True
                self.approval_token_hash = _hash_identifier(token)
            elif token_hash:
                self.approval_token_present = True
                self.approval_token_hash = _safe_token(token_hash)

    def to_payload(self) -> dict[str, Any]:
        self._refresh_suppressed_tools()
        return {
            "schema_version": RUNTIME_FLOW_LEDGER_SCHEMA_VERSION,
            "request": {
                "request_id": self.request_id,
                "session_id": self.session_id,
                "user_id_hash": self.user_id_hash,
                "organization_id_hash": self.organization_id_hash,
                "domain_id": self.domain_id,
                "host_surface": self.host_surface,
                "host_capabilities": list(self.host_capabilities),
            },
            "context": {
                "document_context_present": self.document_context_present,
                "uploaded_document_count": self.uploaded_document_count,
                "source_ref_count": self.source_ref_count,
                "memory_context_count": self.memory_context_count,
                "context_provenance": self.context_provenance,
            },
            "route": {
                "lane": self.route_lane,
                "reason": self.route_reason,
                "selected_agent": self.selected_agent,
                "final_agent": self.final_agent,
            },
            "runtime": {
                "requested_provider": self.provider_requested,
                "requested_model": self.model_requested,
                "provider": self.provider,
                "model": self.model,
                "runtime_authoritative": self.runtime_authoritative,
                "fallback_used": self.fallback_used,
                "fallback_reason": self.fallback_reason,
                "failover_used": self.failover_used,
            },
            "tools": {
                "observed": list(self.observed_tools),
                "suppressed": list(self.suppressed_tools),
            },
            "stream": {
                "transport": "sse_v3",
                "event_counts": dict(self.event_counts),
                "event_sequence_tail": list(self.event_sequence_tail),
                "metadata_seen": self.metadata_seen,
                "done_seen": self.done_seen,
            },
            "host_actions": {
                "preview_required": self.preview_required,
                "preview_emitted": self.preview_emitted,
                "approval_token_present": self.approval_token_present,
                "approval_token_hash": self.approval_token_hash,
                "apply_attempted": self.apply_attempted,
                "mutation_blocked_reason": self.mutation_blocked_reason,
            },
            "finalization": {
                "status": self.finalization_status,
                "error_type": self.finalization_error_type,
                "save_response_immediately": self.save_response_immediately,
            },
        }

    def _refresh_suppressed_tools(self) -> None:
        suppressed: list[str] = []
        if "host_action" not in self.host_capabilities and not self.event_counts.get(
            "host_action"
        ):
            suppressed.append("host_action")
        if "pointy" not in self.host_capabilities and not self.event_counts.get(
            "pointy_action"
        ):
            suppressed.append("pointy_action")
        if (
            self.route_lane not in {"visual_fast_path", "native_turn"}
            and "visual_runtime" not in self.observed_tools
        ):
            suppressed.append("visual_runtime")
        if (
            "code_studio" not in self.host_capabilities
            and "code_studio" not in self.observed_tools
        ):
            suppressed.append("code_studio")
        self.suppressed_tools = suppressed


__all__ = [
    "RUNTIME_FLOW_LEDGER_SCHEMA_VERSION",
    "RuntimeFlowLedger",
]
