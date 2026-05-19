"""Pointy selector and inventory policy for direct tool rounds.

This module owns server-side selector validation and host inventory formatting
so the direct tool-loop can depend on a small audited contract instead of
carrying Pointy policy inline.
"""

from __future__ import annotations

from typing import Any


def _validate_pointy_selector(selector: str, state: Any) -> str | None:
    """Validate LLM-provided pointy selector vs available_targets.

    Returns None khi selector OK, hoặc error message string khi hallucinated.
    Error message được trả về như tool_result để LLM thấy + correct round
    tiếp với exact id từ inventory.

    v3.0 anti-hallucination defense (server-side). Compound CSS, aria-label
    patterns, .class selectors đều bị reject vì:

    1. Bypass Wiii's data-wiii-id stable handle priority (architectural)
    2. Brittle vs UI refactors (Tailwind classes, BEM names change)
    3. Silent fail mode trên frontend khi không match real DOM
    """
    if not selector:
        return (
            "ERROR: Empty selector. Required: exact `id` from "
            "tool_pointy_inventory. Example: tool_pointy_show("
            'selector="chat-send-button", caption="..."). Call '
            "tool_pointy_inventory first if unsure."
        )

    # Exact Wiii ids include annotated handles (chat-send-button) and
    # scanner-generated synthetic ids (auto:button:gui-tin-nhan).
    import re
    wiii_id_re = re.compile(
        r"^(?:[a-zA-Z][a-zA-Z0-9_-]*|auto:[a-z0-9_-]+:[a-z0-9_-]+(?:-\d+)?)$"
    )
    is_wiii_id = bool(wiii_id_re.match(selector))

    # Verbose [data-wiii-id="..."] form cũng OK (Wiii's documented selector form).
    is_data_wiii_id_form = bool(
        re.match(r'^\[data-wiii-id=("[\w-]+"|\'[\w-]+\'|[\w-]+)\]$', selector)
    )

    # v9.0 F18: read inventory from BOTH state forms (dict + attr).
    # state can be plain dict (graph_stream_runtime) OR SimpleNamespace.
    def _read_inventory_ids(s: Any) -> list[str]:
        host = None
        if isinstance(s, dict):
            host = s.get("host_context") or (s.get("context") or {}).get("host_context")
        else:
            host = getattr(s, "host_context", None)
        if not isinstance(host, dict):
            return []
        page = host.get("page") or {}
        metadata = page.get("metadata") or {} if isinstance(page, dict) else {}
        targets = metadata.get("available_targets") or []
        if not isinstance(targets, list):
            return []
        return [str(t.get("id")) for t in targets if isinstance(t, dict) and t.get("id")]

    inventory_ids = _read_inventory_ids(state)
    if inventory_ids and selector in inventory_ids:
        return None

    # Bất kỳ form nào KHÔNG phải Wiii id và KHÔNG phải data-wiii-id form
    # → likely hallucination (compound CSS, aria-label, .class, ...).
    if not (is_wiii_id or is_data_wiii_id_form):
        examples = ", ".join(f'"{i}"' for i in inventory_ids[:3]) if inventory_ids else '"chat-send-button"'
        return (
            f"ERROR: Selector {selector!r} is NOT a valid Wiii Pointy id.\n"
            f"DO NOT generate CSS selectors, aria-label patterns, or .class selectors.\n"
            f"REQUIRED: exact id from current inventory. Synthetic auto ids like "
            f"`auto:button:gui-tin-nhan` are valid when they appear in inventory.\n"
            f"Available ids on this page: {inventory_ids[:10]}\n"
            f"Correct form: tool_pointy_show(selector={examples.split(',')[0] if examples else '...'}, caption=\"...\")"
        )

    # Wiii id form: verify exists trong available_targets if inventory available.
    if is_wiii_id and inventory_ids:
        available_list = sorted(set(inventory_ids))[:10]
        return (
            f"ERROR: id {selector!r} không có trong available_targets trên page hiện tại.\n"
            f"Available ids: {available_list}\n"
            f"Re-call tool_pointy_show với một id chính xác từ list trên, "
            f"hoặc nói prose nếu element không tồn tại."
        )

    return None


def _format_pointy_inventory(state: Any) -> str:
    """Format pointable elements + cursor state cho LLM.

    Reads ``state.host_context.page.metadata.available_targets`` (set
    bởi frontend qua HostContextStore Sprint 222 mechanism) plus
    ``state.host_context.page.metadata.cursor_state`` nếu có.

    v3.0 (Battleship): inventory text là PRESCRIPTIVE — mỗi item include
    inline directive ``→ call: tool_pointy_show(selector="<id>")`` để
    LLM khó ignore và không hallucinate compound CSS selectors.
    """
    if state is None:
        return "Pointy inventory unavailable (no chat state)."
    host_context = getattr(state, "host_context", None) or {}
    page = host_context.get("page", {}) if isinstance(host_context, dict) else {}
    metadata = page.get("metadata", {}) if isinstance(page, dict) else {}
    targets = metadata.get("available_targets") or []
    cursor_state = metadata.get("cursor_state")

    lines: list[str] = []
    if not targets:
        lines.append(
            "No pointable elements published by the host. The frontend "
            "may not have integrated PageScanner yet, or this turn ran "
            "without host_context. Use prose to describe locations."
        )
    else:
        visible = [t for t in targets if t.get("visible")]
        offscreen = [t for t in targets if not t.get("visible")]
        lines.append(
            f"Pointable elements ({len(visible)} visible, "
            f"{len(offscreen)} off-screen). USE EXACT id BELOW — DO NOT "
            f"generate CSS / compound / aria-label selectors:"
        )
        display = visible if visible else targets
        for t in display[:30]:
            tid = t.get("id") or t.get("selector") or "?"
            role = t.get("role", "other")
            label = t.get("label") or ""
            click_safe = " (click_safe)" if t.get("click_safe") else ""
            label_part = f' "{label}"' if label else ""
            offscreen_tag = " [offscreen]" if not t.get("visible") else ""
            # v3.0: prescriptive directive — LLM khó ignore inline call hint.
            lines.append(
                f'- id="{tid}" ({role}){label_part}{click_safe}{offscreen_tag}\n'
                f'  → call: tool_pointy_show(selector="{tid}", caption="...")'
            )
        if len(display) > 30:
            lines.append(f"… {len(display) - 30} more elements omitted.")

    if isinstance(cursor_state, dict):
        pos = cursor_state.get("position") or {}
        x = pos.get("x", "?")
        y = pos.get("y", "?")
        state_name = cursor_state.get("awarenessState", "?")
        last = cursor_state.get("currentSelector")
        last_part = f' last_target="{last}"' if last else ""
        lines.append(
            f"Wiii cursor: pos=({x}, {y}) state={state_name}{last_part}"
        )

    # User's real OS cursor (Wiii Pointy v2.5).
    user_cursor = metadata.get("user_cursor_state")
    if isinstance(user_cursor, dict):
        upos = user_cursor.get("position")
        if isinstance(upos, dict):
            ux = upos.get("x", "?")
            uy = upos.get("y", "?")
            idle = user_cursor.get("idle_ms", 0)
            hovered = user_cursor.get("hovered_id")
            hovered_label = user_cursor.get("hovered_label")
            clicked = user_cursor.get("recently_clicked", False)
            parts = [f"User cursor: pos=({ux}, {uy}) idle={idle}ms"]
            if hovered:
                hover_part = f' hovering="{hovered}"'
                if hovered_label:
                    hover_part += f' (label="{hovered_label}")'
                parts.append(hover_part)
            if clicked:
                parts.append("recently_clicked=true")
            lines.append(" ".join(parts))
        else:
            lines.append("User cursor: not yet tracked.")

    # User's attention/presence (Wiii Pointy v2.6 — tab visibility, blur, idle
    # + v2.7 behavior counters: copy/paste/right-click + selected text).
    attention = metadata.get("user_attention")
    if isinstance(attention, dict):
        status = attention.get("status", "?")
        blurs = attention.get("blur_count", 0)
        tab_switches = attention.get("tab_switch_count", 0)
        away_ms = attention.get("total_away_ms", 0)
        last_away = attention.get("last_away_duration_ms", 0)
        parts = [f"User attention: status={status}"]
        if blurs > 0 or tab_switches > 0:
            parts.append(f"blurs={blurs} tab_switches={tab_switches}")
        if away_ms > 0:
            parts.append(f"total_away={away_ms // 1000}s")
        if last_away > 0 and status == "active":
            parts.append(f"just_returned (was away {last_away // 1000}s)")
        # v2.7 behavior counters
        copies = attention.get("copy_count", 0)
        pastes = attention.get("paste_count", 0)
        right_clicks = attention.get("context_menu_count", 0)
        if copies or pastes or right_clicks:
            parts.append(
                f"behaviour: copies={copies} pastes={pastes} right_clicks={right_clicks}"
            )
        lines.append(" ".join(parts))
        # Last selected text on its own line for readability.
        selected = attention.get("last_selected_text")
        if isinstance(selected, str) and selected.strip():
            preview = selected[:60].replace("\n", " ")
            lines.append(f'User selected text: "{preview}"')

    return "\n".join(lines)
