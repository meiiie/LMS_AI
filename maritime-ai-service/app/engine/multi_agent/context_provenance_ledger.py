"""Privacy-safe context provenance ledger for Wiii chat turns."""

from __future__ import annotations

import hashlib
from math import isfinite
from collections.abc import Iterable, Mapping
from typing import Any


CONTEXT_PROVENANCE_LEDGER_SCHEMA_VERSION = "wiii.context_provenance_ledger.v1"
_MAX_TOKEN_LENGTH = 96
_MAX_SEQUENCE_ITEMS = 24


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


def _append_unique(target: list[str], value: Any) -> None:
    token = _safe_token(value)
    if token and token not in target and len(target) < _MAX_SEQUENCE_ITEMS:
        target.append(token)


def _safe_token_list(values: Any) -> list[str]:
    if not isinstance(values, Iterable) or isinstance(values, (str, bytes, Mapping)):
        return []
    tokens: list[str] = []
    for value in values:
        _append_unique(tokens, value)
    return tokens


def _count_sequence(value: Any) -> int | None:
    if isinstance(value, (list, tuple, set)):
        return len(value)
    return None


def _char_count(value: Any) -> int:
    return len(str(value or "").strip())


def _positive_int(value: Any) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


def _safe_float(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    numeric = float(value)
    if not isfinite(numeric):
        return None
    return round(numeric, 4)


def _source_ref_items(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, (list, tuple)):
        return [
            item
            for item in (_plain_mapping(candidate) for candidate in value)
            if item
        ]
    if isinstance(value, Mapping):
        nested = value.get("source_refs") or value.get("source_references")
        if nested is None:
            nested = value.get("sources") or value.get("citations")
        return _source_ref_items(nested)
    return []


def _collect_source_refs(context: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    refs: list[Mapping[str, Any]] = []
    for key in ("source_refs", "source_references", "sources", "citations"):
        refs.extend(_source_ref_items(context.get(key)))

    document_context = _plain_mapping(context.get("document_context"))
    for key in ("source_refs", "source_references", "sources", "citations"):
        refs.extend(_source_ref_items(document_context.get(key)))

    attachments = document_context.get("attachments")
    if isinstance(attachments, list):
        for attachment in attachments:
            attachment_map = _plain_mapping(attachment)
            for key in ("source_refs", "source_references", "sources", "citations"):
                refs.extend(_source_ref_items(attachment_map.get(key)))

    return refs[:_MAX_SEQUENCE_ITEMS]


def _source_ref_kinds(source_refs: list[Mapping[str, Any]]) -> list[str]:
    kinds: list[str] = []
    for ref in source_refs:
        for key in ("kind", "source_type", "type", "content_type"):
            token = ref.get(key)
            if token:
                _append_unique(kinds, token)
                break
    return kinds


def _document_summary(context: Mapping[str, Any]) -> dict[str, Any]:
    document_context = _plain_mapping(context.get("document_context"))
    attachments = document_context.get("attachments")
    attachment_items = attachments if isinstance(attachments, list) else []
    parsers: list[str] = []
    parser_chain: list[str] = []
    media_kinds: list[str] = []
    provenance_levels: list[str] = []
    attachment_id_hashes: list[str] = []
    total_markdown_chars = 0
    usable_attachment_count = 0
    truncated_count = 0

    for index, attachment in enumerate(attachment_items, start=1):
        item = _plain_mapping(attachment)
        markdown_chars = _char_count(item.get("markdown"))
        if markdown_chars:
            usable_attachment_count += 1
            total_markdown_chars += markdown_chars
        if bool(item.get("truncated")):
            truncated_count += 1
        _append_unique(parsers, item.get("parser"))
        _append_unique(media_kinds, item.get("media_kind"))
        _append_unique(provenance_levels, item.get("provenance_level"))
        chain = item.get("parser_chain")
        if isinstance(chain, list):
            for parser_name in chain:
                _append_unique(parser_chain, parser_name)
        identifier = (
            item.get("document_id")
            or item.get("id")
            or item.get("file_id")
            or item.get("file_name")
            or item.get("name")
            or f"document-{index}"
        )
        identifier_hash = _hash_identifier(identifier)
        if identifier_hash and identifier_hash not in attachment_id_hashes:
            attachment_id_hashes.append(identifier_hash)

    source_refs = _collect_source_refs(context)
    return {
        "present": bool(document_context) or bool(attachment_items),
        "attachment_count": len(attachment_items),
        "usable_attachment_count": usable_attachment_count,
        "total_markdown_chars": total_markdown_chars,
        "truncated_count": truncated_count,
        "parser_names": parsers,
        "parser_chain_names": parser_chain,
        "media_kinds": media_kinds,
        "provenance_levels": provenance_levels,
        "attachment_id_hashes": attachment_id_hashes[:_MAX_SEQUENCE_ITEMS],
        "source_ref_count": len(source_refs),
        "source_ref_kinds": _source_ref_kinds(source_refs),
    }


def _conversation_summary(context: Mapping[str, Any]) -> dict[str, Any]:
    retrieval = _plain_mapping(context.get("history_retrieval_summary"))
    budget = _plain_mapping(context.get("context_budget_summary"))
    history_list_count = _count_sequence(context.get("history_list"))
    langchain_count = _count_sequence(context.get("langchain_messages"))
    history_chars = _char_count(context.get("conversation_history"))
    summary_chars = _char_count(context.get("conversation_summary"))
    return {
        "history_present": history_chars > 0 or bool(history_list_count),
        "history_char_count": history_chars,
        "history_item_count": history_list_count,
        "langchain_message_count": langchain_count,
        "history_retrieval_present": bool(retrieval),
        "history_retrieval_status": (
            _safe_token(retrieval.get("status")) if retrieval else None
        )
        or "unknown",
        "history_source": _safe_token(retrieval.get("source")),
        "persisted_history_item_count": _positive_int(
            retrieval.get("persisted_history_item_count")
        ),
        "fallback_history_item_count": _positive_int(
            retrieval.get("fallback_history_item_count")
        ),
        "selected_history_item_count": _positive_int(
            retrieval.get("selected_history_item_count")
        ),
        "history_org_scoped": bool(retrieval.get("org_scoped")),
        "history_user_name_present": bool(retrieval.get("user_name_present")),
        "history_raw_content_included": bool(retrieval.get("raw_content_included")),
        "history_warning_codes": _safe_token_list(retrieval.get("warning_codes")),
        "context_budget_present": bool(budget),
        "context_budget_status": (
            _safe_token(budget.get("status")) if budget else None
        )
        or "unknown",
        "context_budget_total": _positive_int(budget.get("total_budget")),
        "context_budget_used": _positive_int(budget.get("total_used")),
        "context_budget_utilization": _safe_float(budget.get("utilization")),
        "context_budget_needs_compaction": bool(budget.get("needs_compaction")),
        "context_budget_messages_included": _positive_int(
            budget.get("messages_included")
        ),
        "context_budget_messages_dropped": _positive_int(
            budget.get("messages_dropped")
        ),
        "context_budget_has_summary": bool(budget.get("has_summary")),
        "context_budget_raw_content_included": bool(
            budget.get("raw_content_included")
        ),
        "context_budget_warning_codes": _safe_token_list(
            budget.get("warning_codes")
        ),
        "summary_present": summary_chars > 0,
        "summary_char_count": summary_chars,
    }


def _memory_summary(context: Mapping[str, Any]) -> dict[str, Any]:
    memories = context.get("semantic_memories")
    if memories is None:
        memories = context.get("memories")
    retrieval = _plain_mapping(context.get("memory_retrieval_summary"))
    episodic = _plain_mapping(context.get("episodic_retrieval_summary"))
    memory_count = _count_sequence(memories)
    memory_types: list[str] = []
    if isinstance(memories, (list, tuple)):
        for memory in memories:
            item = _plain_mapping(memory)
            _append_unique(
                memory_types,
                item.get("memory_type") or item.get("type") or item.get("category"),
            )
    for memory_type in _safe_token_list(retrieval.get("memory_type_names")):
        _append_unique(memory_types, memory_type)

    user_fact_count = _count_sequence(context.get("user_facts"))
    retrieval_user_fact_count = _positive_int(retrieval.get("user_fact_count"))
    if retrieval_user_fact_count is not None:
        user_fact_count = retrieval_user_fact_count
    retrieval_memory_count = _positive_int(retrieval.get("semantic_memory_count"))
    if memory_count is None and retrieval_memory_count is not None:
        memory_count = retrieval_memory_count
    semantic_context_chars = _char_count(context.get("semantic_context"))
    core_memory_chars = _char_count(context.get("core_memory_block"))
    warning_codes = _safe_token_list(context.get("memory_warnings"))
    for warning in _safe_token_list(retrieval.get("warning_codes")):
        _append_unique(warning_codes, warning)
    for warning in _safe_token_list(episodic.get("warning_codes")):
        _append_unique(warning_codes, warning)
    if bool(episodic.get("raw_content_included")):
        _append_unique(warning_codes, "episodic_retrieval_raw_content_flagged")
    return {
        "semantic_context_present": semantic_context_chars > 0,
        "semantic_context_char_count": semantic_context_chars,
        "semantic_memory_count": memory_count,
        "semantic_memory_types": memory_types,
        "retrieval_present": bool(retrieval),
        "retrieval_status": _safe_token(retrieval.get("status")) or "unknown",
        "relevant_memory_count": _positive_int(
            retrieval.get("relevant_memory_count")
        ),
        "insight_count": _positive_int(retrieval.get("insight_count")),
        "fact_type_names": _safe_token_list(retrieval.get("fact_type_names")),
        "insight_category_names": _safe_token_list(
            retrieval.get("insight_category_names")
        ),
        "user_fact_count": user_fact_count,
        "core_memory_present": core_memory_chars > 0,
        "core_memory_char_count": core_memory_chars,
        "episodic_retrieval_present": bool(episodic),
        "episodic_retrieval_status": (
            _safe_token(episodic.get("status")) if episodic else None
        ) or "unknown",
        "episodic_match_count": (
            _positive_int(episodic.get("match_count")) if episodic else None
        ),
        "episodic_event_types": _safe_token_list(episodic.get("event_types")),
        "episodic_max_score": _safe_float(episodic.get("max_score")),
        "episodic_min_score": _safe_float(episodic.get("min_score")),
        "episodic_org_scoped": bool(episodic.get("org_scoped")),
        "episodic_current_session_excluded": bool(
            episodic.get("current_session_excluded")
        ),
        "episodic_raw_content_included": bool(
            episodic.get("raw_content_included")
        ),
        "warning_codes": warning_codes,
    }


def _host_summary(context: Mapping[str, Any]) -> dict[str, Any]:
    host_context = _plain_mapping(context.get("host_context"))
    host_capabilities = context.get("host_capabilities")
    available_actions = context.get("available_actions")
    capability_names = _safe_token_list(host_context.get("capabilities"))
    if not capability_names:
        capability_names = _safe_token_list(host_capabilities)
    surface = (
        host_context.get("surface")
        or host_context.get("host_surface")
        or host_context.get("host_type")
        or host_context.get("client")
        or context.get("client")
    )
    return {
        "host_context_present": bool(host_context),
        "surface": _safe_token(surface) or "unknown",
        "capability_names": capability_names,
        "available_action_count": _count_sequence(available_actions),
        "host_capabilities_present": bool(host_capabilities),
    }


def _warnings(
    *,
    conversation: Mapping[str, Any],
    documents: Mapping[str, Any],
    memory: Mapping[str, Any],
    host: Mapping[str, Any],
) -> list[str]:
    warnings: list[str] = []
    for warning in conversation.get("history_warning_codes") or []:
        _append_unique(warnings, warning)
    if bool(conversation.get("history_raw_content_included")):
        _append_unique(warnings, "chat_history_retrieval_raw_content_flagged")
    for warning in conversation.get("context_budget_warning_codes") or []:
        _append_unique(warnings, warning)
    if bool(conversation.get("context_budget_raw_content_included")):
        _append_unique(warnings, "context_budget_raw_content_flagged")
    if (
        int(documents.get("usable_attachment_count") or 0) > 0
        and int(documents.get("source_ref_count") or 0) == 0
    ):
        warnings.append("document_context_without_source_refs")
    if (
        bool(memory.get("semantic_context_present"))
        and memory.get("semantic_memory_count") is None
        and not bool(memory.get("retrieval_present"))
    ):
        warnings.append("memory_context_without_typed_items")
    for warning in memory.get("warning_codes") or []:
        _append_unique(warnings, warning)
    if (
        bool(host.get("host_context_present"))
        and not host.get("capability_names")
        and not host.get("host_capabilities_present")
    ):
        warnings.append("host_context_without_capabilities")
    if int(documents.get("truncated_count") or 0) > 0:
        warnings.append("document_context_truncated")
    return warnings


def build_context_provenance_ledger(context: Any) -> dict[str, Any]:
    """Build a bounded context provenance payload without raw user content."""

    context_map = _plain_mapping(context)
    conversation = _conversation_summary(context_map)
    documents = _document_summary(context_map)
    memory = _memory_summary(context_map)
    host = _host_summary(context_map)
    return {
        "schema_version": CONTEXT_PROVENANCE_LEDGER_SCHEMA_VERSION,
        "conversation": conversation,
        "documents": documents,
        "memory": memory,
        "host": host,
        "warnings": _warnings(
            conversation=conversation,
            documents=documents,
            memory=memory,
            host=host,
        ),
        "privacy": {
            "raw_content_included": False,
            "identifier_strategy": "hash_or_count_only",
        },
    }


def build_request_context_provenance_ledger(chat_request: Any) -> dict[str, Any]:
    """Build provenance from the user_context shape before full context assembly."""

    user_context = _context_value(chat_request, "user_context")
    user_context_map = _plain_mapping(user_context)
    if not user_context_map:
        return build_context_provenance_ledger({})
    return build_context_provenance_ledger(user_context_map)


__all__ = [
    "CONTEXT_PROVENANCE_LEDGER_SCHEMA_VERSION",
    "build_context_provenance_ledger",
    "build_request_context_provenance_ledger",
]
