"""Code Studio output surface helpers.

This module owns artifact-name extraction and final-delivery prompt assembly
for the Code Studio lane, keeping graph orchestration lighter.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.engine.multi_agent.direct_prompt_tool_context import (
    _build_code_studio_tools_context,
)
from app.engine.multi_agent.direct_prompts import (
    _build_direct_system_messages,
)
from app.engine.multi_agent.state import AgentState

_DOCUMENT_STUDIO_TOOLS = frozenset({
    "tool_generate_html_file",
    "tool_generate_excel_file",
    "tool_generate_word_document",
})
_DOCUMENT_STUDIO_EXTENSIONS = frozenset({".html", ".htm", ".xlsx", ".docx"})


def _extract_code_studio_artifact_names(tool_call_events: list[dict] | None) -> list[str]:
    """Extract artifact filenames from Code Studio tool result events."""
    import json as _json

    names: list[str] = []
    seen: set[str] = set()
    for event in tool_call_events or []:
        if not isinstance(event, dict) or event.get("type") != "result":
            continue
        tool_name = str(event.get("name", "")).strip()
        result = str(event.get("result", "") or "").strip()
        if not result:
            continue

        if tool_name in _DOCUMENT_STUDIO_TOOLS and result.startswith("{"):
            try:
                parsed = _json.loads(result)
                filename = str(parsed.get("filename", "")).strip()
                if filename and any(filename.lower().endswith(ext) for ext in _DOCUMENT_STUDIO_EXTENSIONS):
                    if filename not in seen:
                        seen.add(filename)
                        names.append(filename)
                    continue
            except Exception:
                pass

        for line in result.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            candidate = stripped[2:].split(" (", 1)[0].strip()
            if candidate and candidate not in seen:
                seen.add(candidate)
                names.append(candidate)

    return names


def _is_document_studio_tool_error(tool_name: str, result: object) -> bool:
    """Detect failed document studio tool calls (JSON error response)."""
    import json as _json

    if str(tool_name).strip() not in _DOCUMENT_STUDIO_TOOLS:
        return False
    result_str = str(result or "").strip()
    if not result_str.startswith("{"):
        return False
    try:
        parsed = _json.loads(result_str)
        return "error" in parsed
    except Exception:
        return False


def _build_code_studio_synthesis_observations(tool_call_events: list[dict] | None) -> list[str]:
    """Build synthesis observations from tool call results."""
    import json as _json

    observations: list[str] = []
    artifact_names = _extract_code_studio_artifact_names(tool_call_events)
    if artifact_names:
        observations.append("Da tao artifact co the mo ra ngay: " + ", ".join(artifact_names[:3]))

    for event in tool_call_events or []:
        if not isinstance(event, dict) or event.get("type") != "result":
            continue
        tool_name = str(event.get("name", "")).strip()
        result_text = str(event.get("result", "")).strip()
        if not result_text:
            continue

        if "Artifacts:" in result_text:
            if tool_name:
                observations.append(f"{tool_name} vua tra ve dau ra huu hinh.")
            continue

        if tool_name in _DOCUMENT_STUDIO_TOOLS and result_text.startswith("{"):
            try:
                parsed = _json.loads(result_text)
                if "error" not in parsed:
                    filename = parsed.get("filename", "")
                    fmt = parsed.get("format", tool_name)
                    if filename:
                        observations.append(
                            f"Da tao file {fmt.upper()} that: `{filename}` - san sang tai xuong hoac mo ngay."
                        )
                else:
                    observations.append(f"{tool_name} gap loi: {str(parsed['error'])[:120]}")
                continue
            except Exception:
                pass

        first_line = next((line.strip() for line in result_text.splitlines() if line.strip()), "")
        if first_line and not first_line.startswith("{"):
            prefix = f"{tool_name}: " if tool_name else ""
            observations.append(f"{prefix}{first_line[:180]}")

        if len(observations) >= 4:
            break

    return observations[:4]


def _build_code_studio_stream_summary_messages(
    state: AgentState,
    query: str,
    domain_name_vi: str,
    *,
    tool_call_events: list[dict] | None = None,
) -> list[Any]:
    """Build a final delivery-focused turn for streamed code-studio answers."""
    from app.engine.messages import Message
    from app.engine.messages_adapters import to_openai_dict

    ctx = state.get("context", {})
    messages = _build_direct_system_messages(
        state,
        query,
        domain_name_vi,
        role_name="code_studio_agent",
        tools_context_override=_build_code_studio_tools_context(
            settings,
            ctx.get("user_role", "student"),
            query,
        ),
        history_limit=0,
    )
    observations = _build_code_studio_synthesis_observations(tool_call_events)
    artifact_names = _extract_code_studio_artifact_names(tool_call_events)
    delivery_lines = [
        "Hay viet cau tra loi cuoi cung cho nguoi dung bang TIENG VIET CO DAU, tu nhien, am, va ro rang.",
        "Visible thinking da duoc stream rieng. O day chi tra ve answer cuoi, khong lap lai mot mo dau generic.",
        "Neu da tao xong artifact/app/visual, noi ro da tao gi, no dung de lam gi, va nguoi dung co the mo hoac patch tiep ngay bay gio.",
        "Neu turn nay chi moi xac nhan kha nang hoac can user noi ro hon, van tra loi co hon, co dau, va khong may moc.",
        "Khong duoc mat dau tieng Viet. Khong viet khong dau. Khong tra ve JSON, markdown fence, source code dump, hay <thinking> tags.",
        f"User query goc: {query}",
    ]
    if artifact_names:
        delivery_lines.append("Artifact vua tao: " + ", ".join(f"`{name}`" for name in artifact_names[:3]))
    if observations:
        delivery_lines.append("Observations:\n- " + "\n- ".join(observations[:4]))
    delivery_lines.append("Hay dua ra cau tra loi cuoi cung ngay bay gio, theo dung chat giong Code Studio cua Wiii.")
    messages[-1] = to_openai_dict(Message(role="user", content="\n\n".join(delivery_lines)))
    return messages
