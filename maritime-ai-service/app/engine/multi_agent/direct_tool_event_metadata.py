"""Structured metadata for direct tool result stream events."""

from __future__ import annotations

import json
import unicodedata
from typing import Any
from urllib.parse import urlparse


TOOL_RESULT_METADATA_VERSION = "tool_result_metadata.v1"


def _normalize_tool_name(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _fold_text(value: str) -> str:
    normalized = str(value or "").replace("đ", "d").replace("Đ", "D")
    return (
        unicodedata.normalize("NFD", normalized)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )


def _is_weather_tool(tool_name: str) -> bool:
    normalized = _normalize_tool_name(tool_name)
    return (
        normalized in {"tool_current_weather", "current_weather"}
        or "current_weather" in normalized
        or normalized.endswith("_weather")
    )


def _is_search_tool(tool_name: str) -> bool:
    normalized = _normalize_tool_name(tool_name)
    return any(
        token in normalized
        for token in (
            "web_search",
            "search_news",
            "search_legal",
            "search_maritime",
            "search_products",
            "search_shopping",
        )
    )


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str):
        return {}
    text = value.strip()
    if not text.startswith("{"):
        return {}
    try:
        parsed = json.loads(text)
    except Exception:  # noqa: BLE001
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _source_domains(sources: list[dict[str, Any]]) -> list[str]:
    domains: list[str] = []
    for source in sources:
        url = str(source.get("url") or "")
        if not url:
            continue
        domain = urlparse(url).netloc.replace("www.", "")
        if domain and domain not in domains:
            domains.append(domain)
    return domains


def _weather_status_metadata(result: Any) -> dict[str, str]:
    payload = _parse_json_object(result)
    status = _fold_text(str(payload.get("status") or ""))
    reason = _fold_text(
        str(
            payload.get("reason_code")
            or payload.get("reason")
            or payload.get("error_code")
            or ""
        )
    )
    code = f"{status} {reason}"
    folded = _fold_text(" ".join(str(result or "").split()))

    if (
        "provider_unconfigured" in code
        or "not_configured" in code
        or "missing_api_key" in code
        or "chua co ket noi thoi tiet truc tiep" in folded
    ):
        return {"status": "unavailable", "reason_code": "provider_unconfigured"}
    if (
        "missing_location" in code
        or "needs_location" in code
        or "location_required" in code
        or "ban muon xem nhiet do" in folded
        or "thanh pho nao" in folded
        or "can them dia diem" in folded
    ):
        return {"status": "needs_input", "reason_code": "missing_location"}
    if (
        "no_data" in code
        or "unavailable" in code
        or "error" in code
        or "chua lay duoc thoi tiet" in folded
        or "khong co du lieu thoi tiet" in folded
    ):
        return {"status": "unavailable", "reason_code": "no_data"}
    if str(result or "").strip():
        return {"status": "completed", "reason_code": "current_weather"}
    return {"status": "unavailable", "reason_code": "empty_result"}


def build_tool_result_event_metadata(
    tool_name: str,
    result: Any,
    *,
    sources: list[dict[str, Any]] | None = None,
    matched: bool = True,
    skipped_reason: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return optional machine-readable metadata for the UI tool timeline."""

    metadata: dict[str, Any] = {
        "schema_version": TOOL_RESULT_METADATA_VERSION,
        "status": "completed",
        "result_kind": "text",
    }
    if skipped_reason:
        metadata.update(
            {
                "status": "skipped",
                "reason_code": skipped_reason,
                "skipped": True,
            }
        )
    if policy:
        metadata["policy"] = dict(policy)
        if policy.get("allowed") is False:
            metadata.update(
                {
                    "status": "blocked",
                    "reason_code": str(policy.get("reason") or "policy_denied"),
                    "result_kind": "policy",
                }
            )
    if not matched:
        metadata.update({"status": "failed", "reason_code": "unknown_tool"})

    payload = _parse_json_object(result)
    if payload.get("status") == "validation_failed":
        metadata.update(
            {
                "status": "validation_failed",
                "reason_code": "schema_validation",
                "result_kind": "validation",
            }
        )
        if payload.get("missing_fields"):
            metadata["missing_fields"] = list(payload.get("missing_fields") or [])
    elif str(result or "").strip() == "Tool unavailable":
        metadata.update({"status": "failed", "reason_code": "tool_unavailable"})

    if _is_weather_tool(tool_name):
        metadata.update({"result_kind": "weather"})
        metadata.update(_weather_status_metadata(result))

    source_list = sources or []
    if source_list:
        metadata.update(
            {
                "result_kind": "web_sources" if _is_search_tool(tool_name) else "sources",
                "source_count": len(source_list),
                "domains": _source_domains(source_list)[:5],
            }
        )
    return metadata
