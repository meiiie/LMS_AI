import json
import re
from typing import Any, Callable

from app.engine.tools.visual_code_runtime_contract import (
    resolve_visual_code_runtime_contract,
)


def tool_generate_visual_impl(
    *,
    visual_type: str = "chart",
    spec_json: str = "{}",
    title: str = "",
    summary: str = "",
    subtitle: str = "",
    visual_session_id: str = "",
    operation: str = "open",
    renderer_kind: str = "",
    shell_variant: str = "",
    patch_strategy: str = "",
    narrative_anchor: str = "",
    runtime_manifest_json: str = "",
    code_html: str = "",
    core_structured_visual_types: tuple[str, ...],
    resolve_code_html: Callable[[str, str, str, dict[str, Any]], str | None],
    build_multi_figure_payloads: Callable[..., list[Any]],
    builders: dict[str, Callable[[dict[str, Any], str], str]],
    logger: Any,
    runtime_metadata_text: Callable[[str, str], str],
    should_keep_structured_renderer: Callable[[str], bool],
    resolve_renderer_kind: Callable[[str, dict[str, Any], str], str],
    apply_runtime_patch_defaults: Callable[..., tuple[str, str]],
    build_auto_grouped_payloads: Callable[..., list[Any]],
    resolve_fallback_html: Callable[[str, dict[str, Any], str, str | None], str | None],
    normalize_visual_payload: Callable[..., Any],
    log_visual_telemetry: Callable[..., None],
) -> str:
    valid_types = core_structured_visual_types
    if visual_type not in valid_types:
        valid = ", ".join(valid_types)
        return f"Error: visual_type '{visual_type}' không hợp lệ cho visual runtime. Chọn một trong: {valid}"

    if operation not in {"open", "patch"}:
        return "Error: operation phải là 'open' hoặc 'patch'."

    try:
        spec = json.loads(spec_json)
        if not isinstance(spec, dict):
            return "Error: spec_json phải là một JSON object."
    except json.JSONDecodeError as exc:
        return f"Error: JSON không hợp lệ: {exc}"

    resolved_code_html = resolve_code_html(code_html, visual_type, title, spec)

    runtime_manifest = None
    if runtime_manifest_json.strip():
        try:
            runtime_manifest = json.loads(runtime_manifest_json)
            if not isinstance(runtime_manifest, dict):
                return "Error: runtime_manifest_json phải là một JSON object."
        except json.JSONDecodeError as exc:
            return f"Error: runtime_manifest_json không hợp lệ: {exc}"

    if isinstance(spec.get("figures"), list) and spec.get("figures"):
        group_payloads = build_multi_figure_payloads(
            default_visual_type=visual_type,
            raw_group={
                **spec,
                "type": visual_type,
                "title": title,
                "summary": summary,
                "subtitle": subtitle,
                "operation": operation,
                "renderer_kind": renderer_kind,
                "shell_variant": shell_variant,
                "patch_strategy": patch_strategy,
                "narrative_anchor": narrative_anchor,
                "runtime_manifest": runtime_manifest,
            },
        )
        if not group_payloads:
            return "Error: Không thể tạo nhóm figure từ spec_json.figures."

        for payload in group_payloads:
            log_visual_telemetry(
                "tool_generate_visual",
                visual_id=payload.id,
                visual_session_id=payload.visual_session_id,
                visual_type=payload.type,
                renderer_kind=payload.renderer_kind,
                shell_variant=payload.shell_variant,
                patch_strategy=payload.patch_strategy,
                runtime=payload.runtime,
                lifecycle_event=payload.lifecycle_event,
                figure_group_id=payload.figure_group_id,
                figure_index=payload.figure_index,
                figure_total=payload.figure_total,
                pedagogical_role=payload.pedagogical_role,
            )
        return json.dumps(
            [payload.model_dump(mode="json") for payload in group_payloads],
            ensure_ascii=False,
        )

    builder = builders.get(visual_type)
    builder_html = None
    if builder is not None:
        try:
            builder_html = builder(spec, title)
        except Exception as exc:
            logger.warning("Structured visual fallback HTML failed for type=%s: %s", visual_type, exc)

    renderer_kind = renderer_kind.strip()
    hint = runtime_metadata_text("renderer_kind_hint", "").strip()
    intent_mode = runtime_metadata_text("visual_intent_mode", "").strip()
    if not renderer_kind:
        if hint:
            renderer_kind = hint
        elif intent_mode == "template" and not resolved_code_html:
            renderer_kind = "template"
        else:
            renderer_kind = "inline_html"

    if resolved_code_html:
        renderer_kind = "inline_html"
    resolved_renderer_kind = resolve_renderer_kind(visual_type, spec, renderer_kind)
    resolved_visual_session_id, resolved_operation = apply_runtime_patch_defaults(
        visual_session_id=visual_session_id,
        operation=operation,
    )
    if not resolved_code_html:
        auto_group_payloads = build_auto_grouped_payloads(
            visual_type=visual_type,
            spec=spec,
            title=title,
            summary=summary,
            subtitle=subtitle,
            operation=resolved_operation,
            renderer_kind=resolved_renderer_kind,
            shell_variant=shell_variant,
            patch_strategy=patch_strategy,
            narrative_anchor=narrative_anchor,
            runtime_manifest=runtime_manifest,
        )
        if auto_group_payloads:
            for payload in auto_group_payloads:
                log_visual_telemetry(
                    "tool_generate_visual",
                    visual_id=payload.id,
                    visual_session_id=payload.visual_session_id,
                    visual_type=payload.type,
                    renderer_kind=payload.renderer_kind,
                    shell_variant=payload.shell_variant,
                    patch_strategy=payload.patch_strategy,
                    runtime=payload.runtime,
                    lifecycle_event=payload.lifecycle_event,
                    figure_group_id=payload.figure_group_id,
                    figure_index=payload.figure_index,
                    figure_total=payload.figure_total,
                    pedagogical_role=payload.pedagogical_role,
                    auto_grouped=True,
                )
            return json.dumps(
                [payload.model_dump(mode="json") for payload in auto_group_payloads],
                ensure_ascii=False,
            )

    fallback_html = resolved_code_html or resolve_fallback_html(visual_type, spec, title, builder_html)

    payload = normalize_visual_payload(
        visual_type=visual_type,
        spec=spec,
        title=title,
        summary=summary,
        subtitle=subtitle,
        visual_session_id=resolved_visual_session_id,
        operation=resolved_operation,
        renderer_kind=resolved_renderer_kind,
        shell_variant=shell_variant,
        patch_strategy=patch_strategy,
        narrative_anchor=narrative_anchor,
        fallback_html=fallback_html,
        runtime_manifest=runtime_manifest,
    )
    log_visual_telemetry(
        "tool_generate_visual",
        visual_id=payload.id,
        visual_session_id=payload.visual_session_id,
        visual_type=payload.type,
        renderer_kind=payload.renderer_kind,
        shell_variant=payload.shell_variant,
        patch_strategy=payload.patch_strategy,
        runtime=payload.runtime,
        lifecycle_event=payload.lifecycle_event,
    )
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)


def tool_create_visual_code_impl(
    *,
    code_html: str,
    title: str = "",
    subtitle: str = "",
    visual_session_id: str = "",
    runtime_presentation_intent: Callable[[], str],
    runtime_studio_lane: Callable[[], str],
    runtime_artifact_kind: Callable[[], str],
    runtime_metadata_text: Callable[[str, str], str],
    runtime_quality_profile: Callable[[], str],
    runtime_code_studio_version: Callable[[], int],
    maybe_upgrade_code_studio_output: Callable[..., str],
    validate_code_studio_output: Callable[..., str | None],
    quality_score_visual_output: Callable[[str, str], tuple[int, list[str]]],
    wrap_html: Callable[[str, str, str, str], str],
    apply_runtime_patch_defaults: Callable[..., tuple[str, str]],
    normalize_visual_payload: Callable[..., Any],
    log_visual_telemetry: Callable[..., None],
    logger: Any,
) -> str:
    raw = code_html.strip() if isinstance(code_html, str) else ""
    if not raw:
        return (
            "Error: code_html là BẮT BUỘC — không để trống. "
            "Viết HTML/CSS/SVG/JS trực tiếp với đồ họa thật. "
            "Ít nhất phải có <style> + HTML elements + visual content (SVG, divs styled, canvas). "
            "Xem VISUAL_CODE_GEN.md để tham khảo patterns."
        )

    min_code_html_length = 50
    if len(raw) < min_code_html_length:
        return (
            f"Error: code_html quá ngắn ({len(raw)} ký tự). "
            "Viết HTML/CSS/SVG hoàn chỉnh — model tự quyết complexity phù hợp với nội dung."
        )

    stripped = raw.lstrip()
    if stripped.lower().startswith("<!doctype") or stripped.lower().startswith("<html"):
        head_styles = re.findall(r"(?si)<style[^>]*>.*?</style>", raw)
        raw = re.sub(r"(?si)<!DOCTYPE[^>]*>\s*", "", raw)
        raw = re.sub(r"(?si)</?html[^>]*>\s*", "", raw)
        raw = re.sub(r"(?si)<head[^>]*>.*?</head>\s*", "", raw)
        raw = re.sub(r"(?si)</?body[^>]*>\s*", "", raw)
        if head_styles:
            raw = "\n".join(head_styles) + "\n" + raw.strip()
        raw = raw.strip()

    from app.core.config import get_settings

    if not getattr(get_settings(), "enable_llm_code_gen_visuals", False):
        return "Error: Visual code generation chưa được bật (enable_llm_code_gen_visuals=False)."

    runtime_contract = resolve_visual_code_runtime_contract(
        presentation_intent=runtime_presentation_intent(),
        studio_lane=runtime_studio_lane(),
        artifact_kind=runtime_artifact_kind(),
        requested_visual_type=runtime_metadata_text("visual_requested_type", "concept"),
        quality_profile=runtime_quality_profile(),
        code_studio_version=runtime_code_studio_version(),
        app_category=runtime_metadata_text("app_category", ""),
        user_query=runtime_metadata_text("visual_user_query", ""),
        planning_profile=runtime_metadata_text("planning_profile", ""),
    )
    if runtime_contract.is_blocked_for_code_studio:
        return (
            "Error: tool_create_visual_code khong phai lane dung cho article figure/chart runtime. "
            "Hay dung tool_generate_visual de tao figure giai thich hoac chart runtime chuan."
        )

    raw = maybe_upgrade_code_studio_output(
        raw,
        title=title,
        subtitle=subtitle,
        requested_visual_type=runtime_contract.resolved_visual_type,
        studio_lane=runtime_contract.studio_lane,
        artifact_kind=runtime_contract.artifact_kind,
        quality_profile=runtime_contract.quality_profile,
    )

    quality_error = validate_code_studio_output(
        raw,
        requested_visual_type=runtime_contract.resolved_visual_type,
        studio_lane=runtime_contract.studio_lane,
        artifact_kind=runtime_contract.artifact_kind,
        quality_profile=runtime_contract.quality_profile,
    )
    if quality_error:
        return quality_error

    raw_len = len(raw)
    if raw_len > 500:
        quality_score, quality_deficiencies = quality_score_visual_output(
            raw,
            runtime_contract.resolved_visual_type,
        )
        logger.info(
            "[QUALITY_GATE] raw=%d chars, score=%d/10, type=%s, deficiencies=%d",
            raw_len,
            quality_score,
            runtime_contract.resolved_visual_type,
            len(quality_deficiencies),
        )
        if quality_score < 6 and quality_deficiencies:
            return (
                f"Quality score {quality_score}/10 — chua dat. Hay sua cac van de sau:\n"
                + "\n".join(f"- {d}" for d in quality_deficiencies)
                + "\n\nViet lai code_html hoan chinh hon."
            )

    if raw.lstrip().lower().startswith("<!doctype") or raw.lstrip().lower().startswith("<html"):
        # Even for full documents, inject tweaks protocol if not already present
        if "EDITMODE-BEGIN" not in raw:
            from app.engine.tools.visual_html_core import _tweaks_inject
            tweaks_block = _tweaks_inject()
            if "</body>" in raw:
                final_html = raw.replace("</body>", f"{tweaks_block}</body>", 1)
            else:
                final_html = raw + tweaks_block
        else:
            final_html = raw
    else:
        css_parts = []
        body_content = raw
        style_pattern = re.compile(r"<style[^>]*>(.*?)</style>", re.DOTALL | re.IGNORECASE)
        for match in style_pattern.finditer(raw):
            css_parts.append(match.group(1))
        body_content = style_pattern.sub("", body_content).strip()
        final_html = wrap_html("\n".join(css_parts), body_content, title, subtitle)

    safe_title = title.strip() or "Visual"
    safe_summary = f"{safe_title} — custom visual code"

    resolved_visual_session_id, resolved_operation = apply_runtime_patch_defaults(
        visual_session_id=visual_session_id,
        operation="open",
    )

    payload = normalize_visual_payload(
        visual_type=runtime_contract.resolved_visual_type,
        spec={},
        title=safe_title,
        summary=safe_summary,
        subtitle=subtitle,
        visual_session_id=resolved_visual_session_id,
        operation=resolved_operation,
        renderer_kind=runtime_contract.renderer_kind,
        shell_variant=runtime_contract.shell_variant,
        patch_strategy=runtime_contract.patch_strategy,
        narrative_anchor="after-lead",
        fallback_html=final_html,
        runtime_manifest=runtime_contract.runtime_manifest,
        metadata=runtime_contract.payload_metadata(),
    )
    log_visual_telemetry(
        "tool_create_visual_code",
        visual_id=payload.id,
        visual_session_id=payload.visual_session_id,
        renderer_kind=payload.renderer_kind,
        has_code_html=True,
    )
    return json.dumps(payload.model_dump(mode="json"), ensure_ascii=False)
