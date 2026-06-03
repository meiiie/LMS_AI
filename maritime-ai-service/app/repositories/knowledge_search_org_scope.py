"""Org-scope helpers for knowledge search repositories."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


KNOWLEDGE_SEARCH_MISSING_ORG_WARNING = "knowledge_search_blocked_missing_org_context"


@dataclass(frozen=True)
class KnowledgeSearchOrgScope:
    org_id: Optional[str]
    state: str
    warnings: list[str]
    write_allowed: bool


def resolve_knowledge_search_org_scope(
    organization_id: Optional[str] = None,
    *,
    write: bool = False,
) -> KnowledgeSearchOrgScope:
    if isinstance(organization_id, str) and organization_id.strip():
        return KnowledgeSearchOrgScope(
            org_id=organization_id.strip(),
            state="explicit",
            warnings=[],
            write_allowed=True,
        )

    from app.engine.semantic_memory.write_audit import (
        resolve_memory_read_scope,
        resolve_memory_write_scope,
    )

    scope = resolve_memory_write_scope() if write else resolve_memory_read_scope()
    return KnowledgeSearchOrgScope(
        org_id=scope.org_id,
        state=scope.state,
        warnings=list(scope.warnings),
        write_allowed=scope.write_allowed,
    )


def log_knowledge_search_scope_blocked(
    logger,
    operation: str,
    scope: KnowledgeSearchOrgScope,
    *,
    node_id: Optional[str] = None,
) -> None:
    warnings = list(scope.warnings)
    if "missing_org_context" in warnings:
        warnings.append(KNOWLEDGE_SEARCH_MISSING_ORG_WARNING)
    logger.warning(
        "[KNOWLEDGE_SEARCH] %s blocked node_hash=%s org_hash=%s org_scope=%s warnings=%s",
        operation,
        _hash_identifier(node_id),
        _hash_identifier(scope.org_id),
        scope.state,
        sorted(set(warnings)),
    )


def _hash_identifier(value) -> str | None:
    try:
        from app.engine.semantic_memory.privacy import hash_memory_identifier

        return hash_memory_identifier(value)
    except Exception:
        return None
