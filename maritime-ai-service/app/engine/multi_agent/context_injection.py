"""Context injection helpers for multi-agent graph prompt assembly.

Extracted from graph.py to keep graph orchestration slimmer and isolate
host/living/visual/widget/code-studio prompt block compilation.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.engine.character.living_context import (
    compile_living_context_block,
    format_living_context_prompt,
)
from app.engine.character.character_card import build_wiii_micro_house_prompt
from app.engine.context.capability_policy import (
    filter_host_actions_for_org,
    filter_host_capabilities_for_org,
)
from app.engine.context.host_context import (
    HostCapabilities,
    build_host_session_v1,
    build_operator_session_v1,
    format_host_capabilities_for_prompt,
    format_host_session_for_prompt,
    format_operator_session_for_prompt,
)
from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent

logger = logging.getLogger(__name__)


def _effective_host_user_role(state: dict, ctx: dict, host_ctx: Any) -> str | None:
    """Resolve host role without silently downgrading embedded teacher flows.

    LMS embeds can send the role in the shared chat context while the nested
    `host_context.user_role` is absent. Capability filtering must honor the
    explicit turn role in that case; otherwise authoring preview tools are
    filtered as if the teacher were a student.
    """

    candidates = [
        getattr(host_ctx, "user_role", None),
        ctx.get("host_role"),
        ctx.get("user_role"),
        state.get("host_role"),
        state.get("user_role"),
        state.get("role"),
    ]
    for candidate in candidates:
        value = getattr(candidate, "value", candidate)
        role = str(value or "").strip().lower()
        if role:
            return role
    return None


def _inject_host_context(state: dict) -> str:
    """Graph-level host context injection.

    Converts page_context (legacy) or host_context into a formatted prompt
    block once, then stores derived state for all agents to consume.
    """
    ctx = state.get("context", {})
    if not isinstance(ctx, dict):
        return ""

    raw_host = ctx.get("host_context")
    if raw_host:
        try:
            from app.engine.context.host_context import HostContext
            from app.engine.context.adapters import get_host_adapter

            host_ctx = HostContext(**raw_host) if isinstance(raw_host, dict) else raw_host
            effective_user_role = _effective_host_user_role(state, ctx, host_ctx)
            if effective_user_role and not host_ctx.user_role:
                host_ctx = host_ctx.model_copy(update={"user_role": effective_user_role})
            filtered_host_actions = filter_host_actions_for_org(
                host_ctx.available_actions or [],
                user_role=effective_user_role,
                organization_id=state.get("organization_id") or ctx.get("organization_id"),
                user_id=str(state.get("user_id") or ""),
            )
            host_ctx = host_ctx.model_copy(update={"available_actions": filtered_host_actions or None})
            state["host_context"] = host_ctx.model_dump(exclude_none=True)
            ctx["host_context"] = state["host_context"]
            adapter = get_host_adapter(host_ctx.host_type)
            formatted = adapter.format_context_for_prompt(host_ctx)

            raw_caps = ctx.get("host_capabilities")
            if raw_caps:
                try:
                    filtered_caps = filter_host_capabilities_for_org(
                        raw_caps,
                        user_role=effective_user_role,
                        organization_id=state.get("organization_id") or ctx.get("organization_id"),
                        user_id=str(state.get("user_id") or ""),
                    )
                    state["host_capabilities"] = filtered_caps
                    ctx["host_capabilities"] = filtered_caps
                    state["host_capabilities_prompt"] = format_host_capabilities_for_prompt(
                        filtered_caps,
                        user_role=effective_user_role,
                    )
                except Exception as exc:
                    logger.warning("[GRAPH] host capabilities format failed: %s", exc)

            try:
                from app.core.config import get_settings

                _settings = get_settings()
                if getattr(_settings, "enable_host_skills", False):
                    from app.engine.context.skill_loader import get_skill_loader

                    page_type = host_ctx.page.get("type", "unknown") if isinstance(host_ctx.page, dict) else "unknown"
                    loader = get_skill_loader()
                    skills = loader.load_skills(
                        host_ctx.host_type,
                        page_type,
                        user_role=effective_user_role,
                        workflow_stage=host_ctx.workflow_stage,
                    )
                    skill_prompt = loader.get_prompt_addition(skills)
                    if skill_prompt:
                        formatted = formatted + "\n\n" + skill_prompt
            except Exception as e:
                logger.warning("[GRAPH] Skill loading failed (non-fatal): %s", e)

            return formatted
        except Exception as e:
            logger.warning("[GRAPH] host_context format failed: %s", e)

    page_ctx = ctx.get("page_context")
    if page_ctx:
        try:
            from app.engine.context.host_context import from_legacy_page_context
            from app.engine.context.adapters import get_host_adapter

            page_dict = page_ctx if isinstance(page_ctx, dict) else (
                page_ctx.model_dump(exclude_none=True) if hasattr(page_ctx, "model_dump") else dict(page_ctx)
            )
            host_ctx = from_legacy_page_context(
                page_dict,
                student_state=ctx.get("student_state"),
                available_actions=ctx.get("available_actions"),
            )
            effective_user_role = _effective_host_user_role(state, ctx, host_ctx)
            if effective_user_role and not host_ctx.user_role:
                host_ctx = host_ctx.model_copy(update={"user_role": effective_user_role})
            filtered_host_actions = filter_host_actions_for_org(
                host_ctx.available_actions or [],
                user_role=effective_user_role,
                organization_id=state.get("organization_id") or ctx.get("organization_id"),
                user_id=str(state.get("user_id") or ""),
            )
            host_ctx = host_ctx.model_copy(update={"available_actions": filtered_host_actions or None})
            state["host_context"] = host_ctx.model_dump(exclude_none=True)
            ctx["host_context"] = state["host_context"]
            adapter = get_host_adapter(host_ctx.host_type)
            formatted = adapter.format_context_for_prompt(host_ctx)

            raw_caps = ctx.get("host_capabilities")
            if raw_caps:
                try:
                    filtered_caps = filter_host_capabilities_for_org(
                        raw_caps,
                        user_role=effective_user_role,
                        organization_id=state.get("organization_id") or ctx.get("organization_id"),
                        user_id=str(state.get("user_id") or ""),
                    )
                    state["host_capabilities"] = filtered_caps
                    ctx["host_capabilities"] = filtered_caps
                    state["host_capabilities_prompt"] = format_host_capabilities_for_prompt(
                        filtered_caps,
                        user_role=effective_user_role,
                    )
                except Exception as exc:
                    logger.warning("[GRAPH] legacy host capabilities format failed: %s", exc)

            try:
                from app.core.config import get_settings

                _settings = get_settings()
                if getattr(_settings, "enable_host_skills", False):
                    from app.engine.context.skill_loader import get_skill_loader

                    page_type = host_ctx.page.get("type", "unknown") if isinstance(host_ctx.page, dict) else "unknown"
                    loader = get_skill_loader()
                    skills = loader.load_skills(
                        host_ctx.host_type,
                        page_type,
                        user_role=effective_user_role,
                        workflow_stage=host_ctx.workflow_stage,
                    )
                    skill_prompt = loader.get_prompt_addition(skills)
                    if skill_prompt:
                        formatted = formatted + "\n\n" + skill_prompt
            except Exception as e:
                logger.warning("[GRAPH] Skill loading failed (non-fatal): %s", e)

            return formatted
        except Exception as e:
            logger.warning("[GRAPH] Legacy page_context format failed: %s", e)

    return ""


def _inject_document_context(state: dict) -> str:
    """Compile per-turn uploaded document Markdown into a shared prompt block."""
    ctx = state.get("context", {}) or {}
    if not isinstance(ctx, dict):
        return ""
    raw_document_context = ctx.get("document_context")
    if not raw_document_context:
        return ""
    try:
        from app.services.input_processor_context_runtime import (
            _render_document_context_for_prompt,
        )

        return _render_document_context_for_prompt(raw_document_context)
    except Exception as exc:
        logger.warning("[GRAPH] document_context format failed: %s", exc)
        return ""


def _summarize_host_action_feedback(feedback: dict[str, Any] | None) -> str | None:
    if not isinstance(feedback, dict):
        return None

    last_result = feedback.get("last_action_result")
    if not isinstance(last_result, dict):
        return None

    action = str(last_result.get("action") or "").strip()
    summary = str(last_result.get("summary") or "").strip()
    data = last_result.get("data")
    if not isinstance(data, dict):
        data = {}

    preview_available = bool(data.get("preview_available")) or bool(
        str(data.get("preview_token") or "").strip()
    )
    preview_kind = str(data.get("preview_kind") or "").strip()
    if preview_available:
        label = preview_kind or action or "preview"
        if summary:
            return f"{summary}. Dang cho xac nhan ro rang truoc khi apply."
        return f"Preview {label} san sang. Dang cho xac nhan ro rang truoc khi apply."

    if summary:
        return summary
    if action:
        status = "success" if last_result.get("success") else "failed"
        return f"Host action {action} {status}."
    return None


def _inject_operator_context(state: dict) -> str:
    """Compile a host-aware operator block from context + capabilities."""
    ctx = state.get("context", {}) or {}
    if not isinstance(ctx, dict):
        return ""

    raw_host = ctx.get("host_context")
    if not raw_host:
        page_ctx = ctx.get("page_context")
        if page_ctx:
            try:
                from app.engine.context.host_context import from_legacy_page_context

                page_dict = page_ctx if isinstance(page_ctx, dict) else (
                    page_ctx.model_dump(exclude_none=True) if hasattr(page_ctx, "model_dump") else dict(page_ctx)
                )
                raw_host = from_legacy_page_context(
                    page_dict,
                    student_state=ctx.get("student_state"),
                    available_actions=ctx.get("available_actions"),
                ).model_dump(exclude_none=True)
            except Exception as exc:
                logger.warning("[GRAPH] operator legacy host conversion failed: %s", exc)
                return ""
    if not raw_host:
        return ""

    try:
        from app.engine.context.host_context import HostContext

        host_ctx = HostContext(**raw_host) if isinstance(raw_host, dict) else raw_host
        raw_caps = state.get("host_capabilities") or ctx.get("host_capabilities")
        host_caps = HostCapabilities(**raw_caps) if isinstance(raw_caps, dict) else raw_caps
        operator_session = build_operator_session_v1(
            query=str(state.get("query") or ""),
            host_context=host_ctx,
            host_capabilities=host_caps,
            last_host_result=(
                _summarize_host_action_feedback(ctx.get("host_action_feedback"))
                or str((ctx.get("widget_feedback") or {}).get("summary") or "").strip()
                or None
            ),
            host_action_feedback=ctx.get("host_action_feedback"),
        )
        state["operator_session"] = operator_session.model_dump()
        return format_operator_session_for_prompt(operator_session)
    except Exception as exc:
        logger.warning("[GRAPH] operator context compile failed: %s", exc)
        return ""


def _inject_host_session(state: dict) -> str:
    """Compile a host-session overlay from host context + capabilities."""
    ctx = state.get("context", {}) or {}
    if not isinstance(ctx, dict):
        return ""

    raw_host = state.get("host_context") or ctx.get("host_context")
    if not raw_host:
        return ""

    try:
        from app.engine.context.host_context import HostContext

        host_ctx = HostContext(**raw_host) if isinstance(raw_host, dict) else raw_host
        raw_caps = state.get("host_capabilities") or ctx.get("host_capabilities")
        host_caps = HostCapabilities(**raw_caps) if isinstance(raw_caps, dict) else raw_caps
        host_session = build_host_session_v1(
            host_context=host_ctx,
            host_capabilities=host_caps,
        )
        state["host_session"] = host_session.model_dump(exclude_none=True)
        return format_host_session_for_prompt(host_session)
    except Exception as exc:
        logger.warning("[GRAPH] host session compile failed: %s", exc)
        return ""


def _inject_living_context(state: dict) -> str:
    """Compile a living context block for subtle, cognition-first prompt grounding."""
    query = str(state.get("query") or "").strip()
    if not query:
        return ""

    ctx = state.get("context", {}) or {}
    try:
        block = compile_living_context_block(
            query,
            context=ctx,
            user_id=str(state.get("user_id") or "__global__"),
            organization_id=state.get("organization_id") or ctx.get("organization_id"),
            domain_id=state.get("domain_id"),
        )
    except Exception as exc:
        logger.warning("[GRAPH] living context compile failed: %s", exc)
        return ""

    include_memory_blocks = bool(getattr(settings, "enable_memory_blocks", False))
    include_visual_cognition = bool(getattr(settings, "enable_living_visual_cognition", False))

    try:
        block_dump = block.model_dump(exclude_none=True)
    except Exception:
        block_dump = None
    if block_dump:
        state["living_context_block"] = block_dump
        if isinstance(ctx, dict):
            ctx["living_context_block"] = block_dump

    state["reasoning_policy"] = block.reasoning_policy.model_dump()
    if include_memory_blocks:
        memory_lines = ["## Memory Blocks V1"]
        for memory_block in block.memory_blocks:
            memory_lines.append(f"### {memory_block.namespace}")
            memory_lines.append(f"- summary: {memory_block.summary}")
            for item in memory_block.items[:4]:
                memory_lines.append(f"- {item}")
        state["memory_block_context"] = "\n".join(memory_lines)

    living_prompt = format_living_context_prompt(
        block,
        include_memory_blocks=include_memory_blocks,
        include_visual_cognition=include_visual_cognition,
    )

    house_bridge = build_wiii_micro_house_prompt(
        user_id=str(state.get("user_id") or "__global__"),
        organization_id=state.get("organization_id") or ctx.get("organization_id"),
        mood_hint=ctx.get("mood_hint"),
        personality_mode=ctx.get("personality_mode"),
        lane="living_context",
    ).strip()
    if house_bridge:
        return f"{house_bridge}\n\n{living_prompt}"
    return living_prompt


def _inject_visual_context(state: dict) -> str:
    """Format client-side inline visual context as prompt guidance for patchable visuals."""
    ctx = state.get("context", {})
    if not isinstance(ctx, dict):
        return ""

    raw_visual = ctx.get("visual_context")
    if not isinstance(raw_visual, dict) or not raw_visual:
        return ""

    last_session_id = str(raw_visual.get("last_visual_session_id") or "").strip()
    last_visual_type = str(raw_visual.get("last_visual_type") or "").strip()
    last_visual_title = str(raw_visual.get("last_visual_title") or "").strip()
    active_inline_visuals = raw_visual.get("active_inline_visuals")
    active_items = active_inline_visuals if isinstance(active_inline_visuals, list) else []

    lines = [
        "## Inline Visual Context",
        "- Neu user dang sua, lam ro, highlight, loc, hoac bien doi visual vua co trong chat, UU TIEN patch cung visual session thay vi tao visual moi.",
        "- Khi patch, goi tool_generate_visual voi visual_session_id cu va operation='patch'. Chi doi visual_type neu user yeu cau ro rang.",
        "- Chon renderer_kind phu hop: inline_html la mac dinh cho article figure/chart runtime theo kieu SVG-first; app cho simulation/mini tool.",
        "- Chart giai thich va article figure nen o lane article_figure/chart_runtime; app/widget/artifact moi dung lane code studio.",
        "- Sau khi goi tool_generate_visual, KHONG copy JSON vao answer. Viet narrative ngan + takeaway; frontend se tu dong cap nhat visual.",
    ]

    if last_session_id:
        lines.append(f"- Visual session gan nhat: {last_session_id}")
    if last_visual_type:
        lines.append(f"- Loai visual gan nhat: {last_visual_type}")
    if last_visual_title:
        lines.append(f"- Tieu de visual gan nhat: {last_visual_title}")

    query = str(ctx.get("last_user_message") or state.get("query") or "").strip()
    if query and last_session_id:
        from app.engine.multi_agent.visual_intent_resolver import detect_visual_patch_request

        if detect_visual_patch_request(query):
            prev_html = ""
            for item in active_items:
                if isinstance(item, dict) and str(item.get("visual_session_id", "")) == last_session_id:
                    prev_html = str(item.get("state_summary") or "").strip()
                    break
            if prev_html:
                lines.append("- CONVERSATIONAL EDIT: User muon chinh sua visual truoc do. Day la code HTML hien tai:")
                lines.append(f"```html\n{prev_html[:8000]}\n```")
                lines.append("- Neu day la article figure/chart runtime, uu tien patch bang tool_generate_visual voi visual_session_id cu.")
                lines.append("- Chi dung tool_create_visual_code de cap nhat neu visual truoc do la app/widget/artifact code-centric.")

    if active_items:
        lines.append("- Visual dang co san trong thread:")
        for index, item in enumerate(active_items[:4], start=1):
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("visual_session_id") or item.get("session_id") or "").strip()
            visual_type = str(item.get("type") or "").strip()
            title = str(item.get("title") or "").strip()
            status = str(item.get("status") or "").strip()
            renderer_kind = str(item.get("renderer_kind") or "").strip()
            shell_variant = str(item.get("shell_variant") or "").strip()
            state_summary = str(item.get("state_summary") or "").strip()
            summary = " | ".join(
                part for part in (session_id, visual_type, title, renderer_kind, shell_variant, status, state_summary) if part
            )
            if summary:
                lines.append(f"  {index}. {summary}")

    return "\n".join(lines)


def _inject_visual_cognition_context(state: dict) -> str:
    """Format lane-specific visual cognition guidance for SVG-first figures and Canvas-first simulations."""
    query = str(state.get("query") or "").strip()
    if not query:
        return ""

    visual_decision = resolve_visual_intent(query)
    if not visual_decision.force_tool:
        return ""

    lines = [
        "## Visual Cognition Contract",
        f"- Lane da chon: {visual_decision.presentation_intent}",
        f"- Render surface uu tien: {visual_decision.preferred_render_surface}",
        f"- Planning profile: {visual_decision.planning_profile}",
        f"- Thinking floor: {visual_decision.thinking_floor}",
        f"- Critic policy: {visual_decision.critic_policy}",
        f"- Living expression mode: {visual_decision.living_expression_mode}",
        "- LLM-first o tang planning: phan ra claim, scene, va nhip giai thich truoc khi render.",
        "- Runtime van do host quan ly: lane, shell, bridge, patch session, va safety khong duoc drift.",
    ]

    if visual_decision.presentation_intent == "article_figure":
        lines.extend([
            "- Article figure mac dinh la SVG-first. Moi figure nen chung minh mot claim ro rang thay vi gom tat ca vao mot widget lon.",
            "- Uu tien 2-3 figures nho khi yeu cau la explain/how it works/step by step/in charts.",
            "- Character-forward duoc the hien qua callout, note, nhan manh, va takeaway co tinh dong hanh.",
        ])
    elif visual_decision.presentation_intent == "chart_runtime":
        lines.extend([
            "- Chart runtime mac dinh la SVG-first va phai doc duoc ngay ca khi khong hover.",
            "- Chart can giu scale context, units, legend, source/provenance, va takeaway ngan gon.",
            "- Song dong nhung tiet che: giong Wiii o note/takeaway, khong bien chart thanh demo loe loet.",
        ])
    elif visual_decision.presentation_intent == "code_studio_app":
        lines.extend([
            "- Simulation premium mac dinh la Canvas-first, uu tien state model + render loop + controls + readout + feedback bridge.",
            "- Truoc khi code, can plan scene mo dau, model vat ly/trang thai, controls, readouts, va patch strategy.",
            "- Tinh song cua Wiii the hien qua cach dat scene, nhip motion, va takeaway sau tuong tac, khong phai chrome trang tri.",
        ])
    elif visual_decision.presentation_intent == "artifact":
        lines.extend([
            "- Artifact la HTML lane ben vung hon, uu tien host shell va kha nang tai su dung/persist.",
            "- Van giu narrative ro rang, nhung khong trinh bay nhu article figure inline.",
        ])

    try:
        from app.engine.character.character_card import get_wiii_character_card

        card = get_wiii_character_card()
        lines.append("## Living Visual Style")
        if visual_decision.living_expression_mode == "expressive":
            lines.append("- Neo phong cach song cua Wiii vao lane nay:")
            for line in card.reasoning_style[:3]:
                lines.append(f"  - {line}")
        else:
            lines.append("- Living style o lane nay nen tiet che, uu tien clarity va pedagogical fit.")
    except Exception:
        pass

    return "\n".join(lines)


def _inject_widget_feedback_context(state: dict) -> str:
    """Format recent widget/app outcomes as prompt guidance for the next turn."""
    ctx = state.get("context", {})
    if not isinstance(ctx, dict):
        return ""

    raw_feedback = ctx.get("widget_feedback")
    if not isinstance(raw_feedback, dict) or not raw_feedback:
        return ""

    items = raw_feedback.get("recent_widget_feedback")
    recent_items = items if isinstance(items, list) else []
    last_kind = str(raw_feedback.get("last_widget_kind") or "").strip()
    last_summary = str(raw_feedback.get("last_widget_summary") or "").strip()

    if not recent_items and not (last_kind or last_summary):
        return ""

    lines = [
        "## Widget Feedback Context",
        "- User vua tuong tac voi widget/app trong chat. Neu phu hop, hay phan tich ket qua nay de ca nhan hoa cau tra loi tiep theo.",
        "- Uu tien nhan xet tien do, diem manh, diem can on lai, va goi y buoc tiep theo dua tren ket qua widget.",
        "- Neu ket qua cho thay user gap kho khan, co the de xuat giai thich lai, bai tap bo sung, hoac ghi nho bang tool_character_note khi that su huu ich.",
    ]

    if last_kind:
        lines.append(f"- Loai widget gan nhat: {last_kind}")
    if last_summary:
        lines.append(f"- Tom tat ket qua gan nhat: {last_summary}")

    if recent_items:
        lines.append("- Ket qua widget gan day:")
        for index, item in enumerate(recent_items[:5], start=1):
            if not isinstance(item, dict):
                continue
            widget_kind = str(item.get("widget_kind") or "").strip()
            summary = str(item.get("summary") or "").strip()
            status = str(item.get("status") or "").strip()
            title = str(item.get("title") or "").strip()
            score = item.get("score")
            correct_count = item.get("correct_count")
            total_count = item.get("total_count")

            metrics = []
            if isinstance(score, (int, float)):
                metrics.append(f"score={score}")
            if isinstance(correct_count, (int, float)) and isinstance(total_count, (int, float)):
                metrics.append(f"correct={correct_count}/{total_count}")

            details = " | ".join(
                part for part in (
                    widget_kind,
                    title,
                    status,
                    summary,
                    ", ".join(metrics) if metrics else "",
                ) if part
            )
            if details:
                lines.append(f"  {index}. {details}")

    return "\n".join(lines)


def _inject_code_studio_context(state: dict) -> str:
    """Format active Code Studio session context for code/app follow-up turns."""
    ctx = state.get("context", {})
    if not isinstance(ctx, dict):
        return ""

    raw_context = ctx.get("code_studio_context")
    if not isinstance(raw_context, dict) or not raw_context:
        return ""

    active_session = raw_context.get("active_session")
    if not isinstance(active_session, dict):
        active_session = {}
    requested_view = str(raw_context.get("requested_view") or "").strip().lower()

    if not active_session and not requested_view:
        return ""

    lines = [
        "## Code Studio Context",
        "- Dang co mot Code Studio surface song trong chat cho app/widget/artifact gan day.",
        "- Neu user muon xem code, mo ta cau truc code, hoac patch app dang co, UU TIEN tiep tuc session Code Studio nay thay vi do nguyen van HTML/CSS/JS tho vao answer.",
        "- Khi da co Code Studio session dang mo, chi paste toan bo ma nguon vao answer neu user yeu cau rat ro rang phai dan day du code trong chat. Mac dinh, hay tom tat ngan, noi phan chinh, va de code day du trong panel Code Studio.",
        "- Neu user dang sua app/widget hien co, uu tien patch cung session hoac cung artifact thay vi tao mot session moi neu khong can thiet.",
    ]

    session_id = str(active_session.get("session_id") or "").strip()
    title = str(active_session.get("title") or "").strip()
    status = str(active_session.get("status") or "").strip()
    studio_lane = str(active_session.get("studio_lane") or "").strip()
    artifact_kind = str(active_session.get("artifact_kind") or "").strip()
    renderer_contract = str(active_session.get("renderer_contract") or "").strip()
    active_version = active_session.get("active_version")
    version_count = active_session.get("version_count")
    has_preview = active_session.get("has_preview")

    if session_id or title or status or studio_lane:
        details = " | ".join(
            part for part in (
                session_id,
                title,
                status,
                studio_lane,
                artifact_kind,
                renderer_contract,
                f"v{active_version}" if isinstance(active_version, int) else "",
                f"{version_count} versions" if isinstance(version_count, int) and version_count > 1 else "",
                "co preview" if has_preview else "",
            ) if part
        )
        if details:
            lines.append(f"- Session hien tai: {details}")

    if requested_view == "code":
        lines.append("- Luot nay user muon xem TAB CODE. Hanh vi mong doi: giu code surface la trung tam, tom tat ngan, KHONG do nguyen khoi source vao prose neu khong bi bat buoc.")
    elif requested_view == "preview":
        lines.append("- Luot nay user uu tien preview artifact/app hien tai hon la xem raw source.")

    return "\n".join(lines)
