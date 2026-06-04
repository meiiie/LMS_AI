"""Parse provider-emitted raw tool calls safely.

Some OpenAI-compatible models occasionally return a function-call object as
plain assistant text instead of the structured ``tool_calls`` channel. This
module only accepts complete tool-call shaped payloads whose tool name is
present in the bound tool inventory, so normal prose or examples remain visible.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any


_FENCED_JSON_RE = re.compile(
    r"^\s*```(?:json)?\s*(.*?)\s*```\s*$",
    re.DOTALL | re.IGNORECASE,
)
_FENCED_BLOCK_RE = re.compile(
    r"```([A-Za-z0-9_.:-]+)?\s*\n([\s\S]*?)```",
    re.IGNORECASE,
)
_TOOL_CALL_BLOCK_RE = re.compile(
    r"\[TOOL_CALL\]\s*([\s\S]*?)\s*\[/TOOL_CALL\]",
    re.IGNORECASE,
)
_XML_TOOL_CALL_RE = re.compile(
    r"<(?:[\w]+:)?(?:tool_call|function_call)>\s*([\s\S]*?)</(?:[\w]+:)?(?:tool_call|function_call)>",
    re.IGNORECASE,
)
_XML_INVOKE_RE = re.compile(
    r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>\s*([\s\S]*?)</invoke>",
    re.IGNORECASE,
)
_XML_PARAM_RE = re.compile(
    r"<parameter\s+name=[\"']([^\"']+)[\"'][^>]*>([\s\S]*?)</parameter>",
    re.IGNORECASE,
)
_TOOL_CODE_RE = re.compile(
    r"<tool_code>\s*\{([\s\S]*?)\}\s*</tool_code>",
    re.IGNORECASE,
)
_DSML_PIPES = r"[\uff5c|]+"
_RAW_XML_START_MARKERS = (
    "<tool_call",
    "<function_call",
    "<invoke",
    "<tool_code",
    "<|dsml",
    "<\uff5cdsml",
)
_TOOL_NAME_ALIASES = {
    "search": "tool_web_search",
    "web": "tool_web_search",
    "web_search": "tool_web_search",
    "websearch": "tool_web_search",
    "google_search": "tool_web_search",
    "google_search_retrieval": "tool_web_search",
    "google_search_grounding": "tool_web_search",
    "search_news": "tool_search_news",
    "news_search": "tool_search_news",
    "news": "tool_search_news",
    "search_legal": "tool_search_legal",
    "legal_search": "tool_search_legal",
    "legal": "tool_search_legal",
    "search_maritime": "tool_search_maritime",
    "maritime_search": "tool_search_maritime",
    "maritime": "tool_search_maritime",
    "web_fetch": "tool_fetch_url",
    "webfetch": "tool_fetch_url",
    "fetch_url": "tool_fetch_url",
    "fetch": "tool_fetch_url",
    "current_weather": "tool_current_weather",
    "weather": "tool_current_weather",
}


def tool_names_from_tools(tools: list[Any] | tuple[Any, ...] | set[Any] | None) -> set[str]:
    """Return tool names from LangChain-like tools or OpenAI function schemas."""
    names: set[str] = set()
    for tool in tools or []:
        candidate = ""
        if isinstance(tool, dict):
            function = tool.get("function") if isinstance(tool.get("function"), dict) else {}
            candidate = str(
                function.get("name")
                or tool.get("name")
                or tool.get("tool_name")
                or ""
            ).strip()
        else:
            candidate = str(
                getattr(tool, "name", "")
                or getattr(tool, "__name__", "")
                or ""
            ).strip()
        if candidate:
            names.add(candidate)
    return names


def _strip_json_fence(value: str) -> str:
    text = str(value or "").strip()
    match = _FENCED_JSON_RE.match(text)
    return match.group(1).strip() if match else text


def _normalize_allowed_tool_names(
    allowed_tool_names: set[str] | list[str] | tuple[str, ...] | None,
) -> set[str] | None:
    if allowed_tool_names is None:
        return None
    return {
        str(name).strip()
        for name in allowed_tool_names
        if str(name or "").strip()
    }


def _normalize_tool_name(value: Any) -> str:
    return str(value or "").strip().replace("-", "_")


def _resolve_allowed_tool_name(
    value: Any,
    *,
    allowed_tool_names: set[str] | None,
) -> str | None:
    raw = _normalize_tool_name(value)
    if not raw:
        return None
    candidates = [raw, _TOOL_NAME_ALIASES.get(raw.lower(), "")]
    for candidate in candidates:
        if not candidate:
            continue
        if allowed_tool_names is None or candidate in allowed_tool_names:
            return candidate
    return None


def _single_text_arg_name(tool_name: str) -> str | None:
    lowered = tool_name.lower()
    if lowered in {
        "tool_web_search",
        "tool_search_news",
        "tool_search_legal",
        "tool_search_maritime",
    } or "search" in lowered:
        return "query"
    if lowered == "tool_fetch_url" or "fetch" in lowered:
        return "url"
    if lowered == "tool_current_weather" or "weather" in lowered:
        return "city"
    return None


def _loads_json_object(value: str) -> Any | None:
    text = _strip_json_fence(value)
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def _coerce_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        args = dict(value)
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except Exception:
            parsed = {}
        args = dict(parsed) if isinstance(parsed, dict) else {}
    else:
        args = {}
    if "query" not in args and "q" in args:
        args["query"] = args.get("q")
    return args


def _coerce_tool_arguments(tool_name: str, value: Any) -> dict[str, Any]:
    args = _coerce_arguments(value)
    if not args and isinstance(value, str) and value.strip():
        arg_name = _single_text_arg_name(tool_name)
        if arg_name:
            args[arg_name] = value.strip()
    if tool_name == "tool_current_weather" and "city" not in args:
        for key in ("location", "query", "q"):
            if args.get(key):
                args["city"] = args[key]
                break
    if tool_name == "tool_fetch_url" and "url" not in args:
        for key in ("href", "link", "query"):
            if args.get(key):
                args["url"] = args[key]
                break
    if "query" not in args and "q" in args:
        args["query"] = args.get("q")
    return args


def _candidate_tool_call_objects(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("tool_calls"), list):
        return list(payload.get("tool_calls") or [])
    return [payload]


def _normalize_raw_tool_call(
    candidate: Any,
    *,
    allowed_tool_names: set[str] | None,
    index: int,
) -> dict[str, Any] | None:
    if not isinstance(candidate, dict):
        return None
    function = candidate.get("function") if isinstance(candidate.get("function"), dict) else {}
    name = _resolve_allowed_tool_name(
        candidate.get("name")
        or candidate.get("tool")
        or candidate.get("tool_name")
        or function.get("name")
        or "",
        allowed_tool_names=allowed_tool_names,
    )
    if not name:
        return None
    args = _coerce_tool_arguments(
        name,
        candidate.get("arguments")
        if "arguments" in candidate
        else candidate.get("args")
        if "args" in candidate
        else function.get("arguments")
    )
    call_id = str(candidate.get("id") or f"raw_tool_call_{index}").strip()
    return {"id": call_id, "name": name, "args": args}


def _normalize_dsml(value: str) -> str:
    if "DSML" not in value:
        return value
    text = value
    text = re.sub(
        rf"<\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*tool_calls\s*>",
        "<tool_call>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"<\s*/\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*tool_calls\s*>",
        "</tool_call>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"<\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*invoke\s+name=",
        '<invoke name=',
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"<\s*/\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*invoke\s*>",
        "</invoke>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"<\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*parameter\s+name=([\"'][^\"']+[\"'])[^>]*>",
        r"<parameter name=\1>",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        rf"<\s*/\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*parameter\s*>",
        "</parameter>",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _tool_call_from_name_args(
    name: Any,
    args: Any,
    *,
    allowed_tool_names: set[str] | None,
    index: int,
    call_id_prefix: str,
) -> dict[str, Any] | None:
    resolved_name = _resolve_allowed_tool_name(
        name,
        allowed_tool_names=allowed_tool_names,
    )
    if not resolved_name:
        return None
    return {
        "id": f"{call_id_prefix}_{index}",
        "name": resolved_name,
        "args": _coerce_tool_arguments(resolved_name, args),
    }


def _extract_tool_call_blocks(
    value: str,
    *,
    allowed_tool_names: set[str] | None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for match in _TOOL_CALL_BLOCK_RE.finditer(value):
        raw = match.group(1).strip()
        payload = _loads_json_object(raw)
        if payload is not None:
            for candidate in _candidate_tool_call_objects(payload):
                normalized = _normalize_raw_tool_call(
                    candidate,
                    allowed_tool_names=allowed_tool_names,
                    index=len(calls),
                )
                if normalized:
                    calls.append(normalized)
            continue
        name_match = re.search(
            r"(?:tool|name)\s*(?:=>|:|=)\s*[\"']?([A-Za-z0-9_.:-]+)",
            raw,
            re.IGNORECASE,
        )
        if not name_match:
            continue
        args: dict[str, Any] = {}
        for key in ("query", "q", "url", "href", "link", "city", "location"):
            arg_match = re.search(
                rf"{key}\s*(?:=>|:|=)\s*[\"']([^\"']+)[\"']",
                raw,
                re.IGNORECASE,
            )
            if arg_match:
                args[key] = arg_match.group(1).strip()
        call = _tool_call_from_name_args(
            name_match.group(1),
            args,
            allowed_tool_names=allowed_tool_names,
            index=len(calls),
            call_id_prefix="raw_tool_call_block",
        )
        if call:
            calls.append(call)
    return calls


def _extract_xml_tool_calls(
    value: str,
    *,
    allowed_tool_names: set[str] | None,
) -> list[dict[str, Any]]:
    normalized = _normalize_dsml(value)
    bodies = [match.group(1) for match in _XML_TOOL_CALL_RE.finditer(normalized)]
    if not bodies:
        bodies = [normalized]
    calls: list[dict[str, Any]] = []
    for body in bodies:
        for invoke in _XML_INVOKE_RE.finditer(body):
            args = {
                param.group(1).strip(): html.unescape(param.group(2).strip())
                for param in _XML_PARAM_RE.finditer(invoke.group(2))
            }
            call = _tool_call_from_name_args(
                invoke.group(1),
                args,
                allowed_tool_names=allowed_tool_names,
                index=len(calls),
                call_id_prefix="raw_xml_tool_call",
            )
            if call:
                calls.append(call)
    return calls


def _extract_fenced_tool_calls(
    value: str,
    *,
    allowed_tool_names: set[str] | None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for match in _FENCED_BLOCK_RE.finditer(value):
        tag = _normalize_tool_name(match.group(1)).strip()
        body = match.group(2).strip()
        lowered_tag = tag.lower()
        if lowered_tag in {"", "json"}:
            payload = _loads_json_object(body)
            if payload is None:
                continue
            for candidate in _candidate_tool_call_objects(payload):
                normalized = _normalize_raw_tool_call(
                    candidate,
                    allowed_tool_names=allowed_tool_names,
                    index=len(calls),
                )
                if normalized:
                    calls.append(normalized)
            continue
        if lowered_tag in {"xml", "tool_call", "function_call"}:
            calls.extend(
                _extract_xml_tool_calls(
                    body,
                    allowed_tool_names=allowed_tool_names,
                )
            )
            continue
        call = _tool_call_from_name_args(
            tag,
            body,
            allowed_tool_names=allowed_tool_names,
            index=len(calls),
            call_id_prefix="raw_fenced_tool_call",
        )
        if call:
            calls.append(call)
    return calls


def _extract_tool_code_calls(
    value: str,
    *,
    allowed_tool_names: set[str] | None,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for match in _TOOL_CODE_RE.finditer(value):
        raw = match.group(1)
        name_match = re.search(r"tool\s*=>\s*[\"']([^\"']+)[\"']", raw, re.IGNORECASE)
        if not name_match:
            continue
        args_match = re.search(r"args\s*=>\s*[\"']?([\s\S]*?)[\"']?\s*$", raw, re.IGNORECASE)
        args = args_match.group(1).strip().strip("'\"") if args_match else ""
        call = _tool_call_from_name_args(
            name_match.group(1),
            args,
            allowed_tool_names=allowed_tool_names,
            index=len(calls),
            call_id_prefix="raw_tool_code_call",
        )
        if call:
            calls.append(call)
    return calls


def classify_raw_tool_call_text_start(
    value: Any,
    *,
    allowed_tool_names: set[str] | list[str] | tuple[str, ...] | None = None,
) -> bool | None:
    """Return whether a streamed answer prefix should be buffered as a tool call.

    ``None`` means the prefix is still ambiguous and the caller should wait for
    more text. ``False`` means it is ordinary answer text and can be streamed.
    """

    text = str(value or "").lstrip()
    if not text:
        return None
    if text[0] == "{":
        return True
    if text[0] == "[":
        upper = text.upper()
        if "[TOOL_CALL]".startswith(upper):
            return None
        if upper.startswith("[TOOL_CALL]"):
            return True
        stripped_array = text[1:].lstrip()
        if not stripped_array:
            return None
        return stripped_array.startswith("{")
    if text.startswith("`"):
        if not "```".startswith(text[:3]) and not text.startswith("```"):
            return False
        if not text.startswith("```"):
            return None
        rest = text[3:]
        if "\n" not in rest and len(rest) < 96:
            return None
        tag = _normalize_tool_name(rest.splitlines()[0] if rest else "")
        if tag.lower() in {"", "json", "xml", "tool_call", "function_call"}:
            return True
        allowed = _normalize_allowed_tool_names(allowed_tool_names)
        return _resolve_allowed_tool_name(tag, allowed_tool_names=allowed) is not None
    if text.startswith("<"):
        lowered = text.lower()
        if any(marker.startswith(lowered) for marker in _RAW_XML_START_MARKERS):
            return None
        return any(lowered.startswith(marker) for marker in _RAW_XML_START_MARKERS)
    return False


def find_raw_tool_call_marker_index(
    value: Any,
    *,
    allowed_tool_names: set[str] | list[str] | tuple[str, ...] | None = None,
) -> int | None:
    """Return the start index of an explicit raw tool-call marker in mixed prose.

    This is intentionally narrower than full extraction: it only detects
    executable markers that can appear after a short natural-language preamble,
    so examples like ``[Image #1]`` or ordinary code fences keep streaming.
    """

    if not isinstance(value, str) or not value:
        return None
    allowed = _normalize_allowed_tool_names(allowed_tool_names)

    candidates: list[int] = []

    tool_call_marker = re.search(r"\[TOOL_CALL\]", value, re.IGNORECASE)
    if tool_call_marker:
        candidates.append(tool_call_marker.start())

    for match in re.finditer(r"```([A-Za-z0-9_.:-]*)?", value):
        tag = _normalize_tool_name(match.group(1) or "")
        lowered_tag = tag.lower()
        if _resolve_allowed_tool_name(tag, allowed_tool_names=allowed):
            candidates.append(match.start())
            continue
        if lowered_tag in {"tool_call", "function_call"}:
            candidates.append(match.start())
            continue
        if lowered_tag == "xml":
            body_preview = value[match.end(): match.end() + 240]
            if re.search(
                r"<(?:[\w]+:)?(?:tool_call|function_call)\b|<invoke\s+name=|<tool_code\b",
                body_preview,
                re.IGNORECASE,
            ):
                candidates.append(match.start())

    xml_marker = re.search(
        r"<(?:[\w]+:)?(?:tool_call|function_call)\b|<tool_code\b",
        value,
        re.IGNORECASE,
    )
    if xml_marker:
        candidates.append(xml_marker.start())

    for invoke in re.finditer(
        r"<invoke\s+name=[\"']([^\"']+)",
        value,
        re.IGNORECASE,
    ):
        if _resolve_allowed_tool_name(invoke.group(1), allowed_tool_names=allowed):
            candidates.append(invoke.start())

    dsml_marker = re.search(
        rf"<\s*{_DSML_PIPES}\s*DSML\s*{_DSML_PIPES}\s*(?:tool_calls|invoke)\b",
        value,
        re.IGNORECASE,
    )
    if dsml_marker:
        candidates.append(dsml_marker.start())

    return min(candidates) if candidates else None


def extract_raw_tool_calls_from_text(
    value: Any,
    *,
    allowed_tool_names: set[str] | list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Extract structured tool calls from assistant text fallback formats."""
    if not isinstance(value, str):
        return []
    allowed = _normalize_allowed_tool_names(allowed_tool_names)
    payload = _loads_json_object(value)
    calls: list[dict[str, Any]] = []
    if payload is not None:
        for index, candidate in enumerate(_candidate_tool_call_objects(payload)):
            normalized = _normalize_raw_tool_call(
                candidate,
                allowed_tool_names=allowed,
                index=index,
            )
            if normalized:
                calls.append(normalized)
        return calls
    calls.extend(_extract_fenced_tool_calls(value, allowed_tool_names=allowed))
    if calls:
        return calls
    calls.extend(_extract_tool_call_blocks(value, allowed_tool_names=allowed))
    if calls:
        return calls
    calls.extend(_extract_xml_tool_calls(value, allowed_tool_names=allowed))
    if calls:
        return calls
    calls.extend(_extract_tool_code_calls(value, allowed_tool_names=allowed))
    return calls
