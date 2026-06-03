"""Privacy-safe audit events for semantic-memory writes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from app.engine.semantic_memory.privacy import hash_memory_identifier

logger = logging.getLogger(__name__)

SEMANTIC_MEMORY_WRITE_AUDIT_VERSION = "wiii.semantic_memory_write.v1"


@dataclass(frozen=True, slots=True)
class MemoryWriteScope:
    org_id: str | None
    state: str
    warnings: list[str] = field(default_factory=list)
    write_allowed: bool = True


def _settings_bool(value: Any) -> bool:
    return value is True


def _settings_text(value: Any, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def resolve_memory_write_scope() -> MemoryWriteScope:
    """Resolve the current tenant scope without exposing raw identifiers."""

    warnings: list[str] = []
    try:
        from app.core.config import settings

        default_org_id = _settings_text(
            getattr(settings, "default_organization_id", "default"),
            "default",
        )
        if not _settings_bool(getattr(settings, "enable_multi_tenant", False)):
            return MemoryWriteScope(
                org_id=default_org_id,
                state="single_tenant_default",
                warnings=warnings,
                write_allowed=True,
            )

        from app.core.org_context import get_current_org_id

        current_org_id = get_current_org_id()
        if isinstance(current_org_id, str) and current_org_id.strip():
            return MemoryWriteScope(
                org_id=current_org_id.strip(),
                state="request_scoped",
                warnings=warnings,
                write_allowed=True,
            )
        environment = _settings_text(
            getattr(settings, "environment", "development"),
            "development",
        )
        if environment in {"production", "staging"}:
            warnings.append("missing_org_context")
            return MemoryWriteScope(
                org_id=None,
                state="blocked_missing_org_context",
                warnings=warnings,
                write_allowed=False,
            )
        warnings.append("missing_org_context_defaulted")
        return MemoryWriteScope(
            org_id=default_org_id,
            state="defaulted",
            warnings=warnings,
            write_allowed=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Memory write scope resolution degraded: %s", exc)
        warnings.append("org_scope_resolution_failed")
        return MemoryWriteScope(
            org_id=None,
            state="unknown",
            warnings=warnings,
            write_allowed=False,
        )


def resolve_memory_read_scope() -> MemoryWriteScope:
    """Resolve the current tenant scope for memory reads.

    Read access uses the same fail-closed tenant boundary as writes so staging
    and production never silently recall memories from the default org when a
    request org context is missing.
    """

    return resolve_memory_write_scope()


def _hash_or_none(value: Any) -> str | None:
    return hash_memory_identifier(value)


def build_semantic_memory_write_audit(
    *,
    user_id: str,
    session_id: str | None,
    message: str,
    response: str,
    scope: MemoryWriteScope,
    write_kind: str = "interaction",
    message_saved: bool,
    response_saved: bool,
    extract_facts: bool,
    stored_fact_count: int,
    stored_insight_count: int = 0,
    status: str,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    """Build a raw-content-free summary of a semantic-memory write."""

    merged_warnings = [*scope.warnings, *(warnings or [])]
    return {
        "schema_version": SEMANTIC_MEMORY_WRITE_AUDIT_VERSION,
        "scope": {
            "user_id_hash": _hash_or_none(user_id),
            "session_id_hash": _hash_or_none(session_id),
            "organization_id_hash": _hash_or_none(scope.org_id),
            "organization_context": scope.state,
            "write_allowed": bool(scope.write_allowed),
        },
        "turn": {
            "message_char_count": len(message or ""),
            "response_char_count": len(response or ""),
        },
        "write": {
            "kind": write_kind,
            "status": status,
            "message_saved": bool(message_saved),
            "response_saved": bool(response_saved),
            "fact_extraction_requested": bool(extract_facts),
            "stored_fact_count": max(int(stored_fact_count or 0), 0),
            "stored_insight_count": max(int(stored_insight_count or 0), 0),
        },
        "warnings": sorted(set(merged_warnings)),
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }


async def append_semantic_memory_write_audit_event(
    *,
    session_id: str | None,
    org_id: str | None,
    payload: Mapping[str, Any],
) -> bool:
    """Append a memory-write audit event when a session log is available."""

    if not session_id:
        return False
    try:
        from app.engine.runtime.session_event_log import get_session_event_log

        await get_session_event_log().append(
            session_id=session_id,
            event_type="semantic_memory_write",
            payload=dict(payload),
            org_id=org_id,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("Semantic memory write audit append skipped: %s", exc)
        return False


__all__ = [
    "MemoryWriteScope",
    "SEMANTIC_MEMORY_WRITE_AUDIT_VERSION",
    "append_semantic_memory_write_audit_event",
    "build_semantic_memory_write_audit",
    "resolve_memory_read_scope",
    "resolve_memory_write_scope",
]
