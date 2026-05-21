"""Direct prompt turn-contract and force-skill helpers."""

from __future__ import annotations

from app.engine.multi_agent.state import AgentState


def _build_force_skill_directive(state: AgentState) -> str:
    """High-priority TOP-of-system-prompt directive for @-mention force-bind.

    Phase F5 (2026-05-06) — when user typed `@wiii-pointy ...` or `@web-search ...`
    in chat input, frontend parses + sets `force_skills` in chat request.
    Tools are bound + pruned to honour the explicit invocation, but NVIDIA
    DeepSeek (and other smaller models) still occasionally generate prose
    instead of calling the tool. This directive plus `tool_choice="any"`
    (set in bind_direct_tools when force_tools=True) gives the LLM
    near-deterministic guidance on what to do FIRST.

    Pattern follows Anthropic Computer Use 2026:
      - Lead with positive imperative ("YOU MUST call ... NOW")
      - List the exact tool names available
      - Inject the page inventory inline so LLM has the data to pick
        the right `selector` without round-tripping through
        ``tool_pointy_inventory``.
    """
    if not isinstance(state, dict):
        return ""
    try:
        from app.engine.multi_agent.tool_collection import (
            _force_skills_from_state,
        )
    except Exception:
        return ""
    forced = _force_skills_from_state(state)
    if not forced:
        return ""

    lines: list[str] = ["[USER FORCE-BOUND PLUGINS via @-mention — bắt buộc invoke]"]

    if "wiii-pointy" in forced:
        # Inline inventory so LLM does NOT need to call tool_pointy_inventory
        # first. Saves a round-trip on host_ui_navigation queries.
        targets = _extract_pointy_inventory(state)
        target_lines = []
        for t in targets[:12]:
            tid = t.get("id", "")
            label = t.get("label", "") or ""
            role = t.get("role", "") or ""
            if not tid:
                continue
            target_lines.append(
                f'  - id="{tid}" role={role} label="{label}"'
                f'\n    → call: tool_pointy_show(selector="{tid}", caption="...")'
            )
        if target_lines:
            lines.append(
                "User invoked **@wiii-pointy** — bạn PHẢI gọi `tool_pointy_show` "
                "NGAY trong response này (KHÔNG được trả prose 'mình đang trỏ' "
                "mà không invoke). Inventory hiện có trên màn hình:"
            )
            lines.extend(target_lines)
            lines.append(
                "Chọn 1 id phù hợp nhất với câu hỏi (ví dụ 'nút gửi tin nhắn' "
                "→ id chứa 'send' hoặc 'chat-send', hoặc id `auto:...` có label khớp)."
            )
        else:
            lines.append(
                "User invoked **@wiii-pointy** nhưng inventory hiện trống. "
                "Gọi `tool_pointy_inventory()` trước để refresh, rồi gọi "
                "`tool_pointy_show()` với id từ kết quả."
            )
        lines.append(
            "Selector PHẢI là exact id nguyên văn từ inventory. Synthetic ids "
            "dạng `auto:button:...` là HỢP LỆ. KHÔNG thêm `#`, KHÔNG generate "
            "CSS selector, KHÔNG dùng `[aria-label=...]`, và KHÔNG dịch/đổi id."
        )

    if "web-search" in forced:
        lines.append(
            "User invoked **@web-search** — bạn PHẢI gọi `tool_web_search` với "
            "query phù hợp NGAY trong response này, KHÔNG dùng kiến thức training "
            "thuần (user explicit chọn realtime web)."
        )

    if "visual-code-gen" in forced:
        lines.append(
            "User invoked **@visual-code-gen** — bạn PHẢI gọi "
            "`tool_create_visual_code` với code_html phù hợp NGAY, KHÔNG mô tả "
            "bằng prose thuần (user explicit chọn visual artifact)."
        )

    return "\n".join(lines)


def _extract_pointy_inventory(state: AgentState) -> list[dict]:
    """Pull `available_targets` from host_context.page.metadata.

    Returns ordered list of target dicts với keys: id, label, role,
    click_safe, click_kind, visible. Empty list when no inventory
    published (no PageScanner running or empty DOM).
    """
    if not isinstance(state, dict):
        return []
    ctx = state.get("context") or {}
    if not isinstance(ctx, dict):
        return []
    host = ctx.get("host_context") or state.get("host_context") or {}
    if not isinstance(host, dict):
        return []
    page = host.get("page") or {}
    if not isinstance(page, dict):
        return []
    metadata = page.get("metadata") or {}
    if not isinstance(metadata, dict):
        return []
    targets = metadata.get("available_targets") or []
    if not isinstance(targets, list):
        return []
    return [t for t in targets if isinstance(t, dict)]


def _force_skills_for_turn(state: AgentState) -> set[str]:
    """Read force-bound skill ids from the current turn context."""
    if not isinstance(state, dict):
        return set()
    force_skills = state.get("force_skills")
    if not force_skills:
        ctx = state.get("context")
        if isinstance(ctx, dict):
            force_skills = ctx.get("force_skills")
    if isinstance(force_skills, (list, tuple, set)):
        return {str(skill).strip().lower() for skill in force_skills if skill}
    return set()


def _build_direct_turn_contract(state: AgentState) -> str:
    """UI-TARS-inspired discipline layer for direct turns.

    Wiii has many context blocks (memory, host UI, skills, tools). This
    lightweight envelope makes their priority explicit without flattening
    Wiii's voice into a rigid state machine.
    """
    targets = _extract_pointy_inventory(state)
    forced = _force_skills_for_turn(state)
    lines = [
        "## WIII DIRECT TURN CONTRACT",
        "- Current turn wins: treat the final user message as the active instruction.",
        "- Use history, memory, RAG, host context, and capability notes as evidence/continuity, not as competing tasks.",
        "- If old context conflicts with the current turn, follow the current turn and mention the assumption only when useful.",
        "- Tool discipline: call a tool only when this turn needs live data, retrieval, file/UI action, visual artifact work, or an explicit force-bound skill.",
        "- Never carry a previous turn's tool route into a simple social/emotional turn.",
    ]
    if forced:
        lines.append(
            "- Force-bound skills for THIS turn: "
            + ", ".join(sorted(forced))
            + ". Satisfy those first, then keep the visible answer concise."
        )
    if targets:
        lines.extend(
            [
                f"- Pointy inventory is available ({len(targets)} targets). Use exact ids from available_targets only; synthetic `auto:...` ids are valid.",
                "- Normal Wiii Desktop/Web UI-location route: answer briefly, then append `[POINT:<exact-id>]` once.",
                "- If a higher-priority @wiii-pointy/tool directive is present, call `tool_pointy_show` instead and do not add a duplicate `[POINT:...]` tag.",
                "- Do not invent CSS selectors, `#id`, `[aria-label=...]`, translated ids, or ids that are not in inventory.",
            ]
        )
    return "\n".join(lines)
