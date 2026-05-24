"""Uploaded document/video and image-input guards for the direct node."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.engine.multi_agent.document_preview_contract import (
    has_uploaded_document_context as _has_uploaded_document_context,
    looks_uploaded_document_course_request as _looks_uploaded_document_course_request,
    looks_uploaded_document_lesson_preview_request as _looks_uploaded_document_lesson_preview_request,
    uploaded_document_attachments_from_context as _uploaded_document_attachments,
)
from app.engine.multi_agent.direct_session_memory_runtime import (
    _with_requested_response_marker,
)
from app.engine.multi_agent.direct_text_utils import _fold_direct_text

logger = logging.getLogger(__name__)

def _image_payload_attr(image: Any, key: str, default: Any = None) -> Any:
    if isinstance(image, dict):
        return image.get(key, default)
    return getattr(image, key, default)


def _first_markdown_line(markdown: str, label: str) -> str:
    pattern = re.compile(rf"^\s*-\s*{re.escape(label)}:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(markdown or "")
    return match.group(1).strip() if match else ""


def _plain_markdown_excerpt(markdown: str, *, limit: int = 700) -> str:
    lines: list[str] = []
    for raw_line in (markdown or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("[Transcript unavailable:"):
            continue
        line = re.sub(r"^#{1,6}\s+", "", line)
        line = re.sub(r"^\s*[-*]\s+", "", line)
        line = line.replace("\\_", "_")
        if line:
            lines.append(line)
        if sum(len(item) for item in lines) >= limit:
            break
    return " ".join(lines)[:limit].strip()


def _build_uploaded_document_context_fallback_answer(
    query: str,
    ctx: dict[str, Any],
    *,
    provider_unstable: bool = True,
) -> str:
    """Provider-failure or deterministic answer for per-turn uploaded file context."""
    attachments = _uploaded_document_attachments(ctx)
    if not attachments:
        return ""

    lines = [
        (
            "Mình vẫn đọc được phần file đã parse trong lượt này, dù provider LLM/vision đang chưa ổn định."
            if provider_unstable
            else "Mình đọc được phần file đã parse trong lượt này."
        ),
    ]
    for index, item in enumerate(attachments[:3], start=1):
        markdown = str(item.get("markdown") or "")
        file_name = str(item.get("file_name") or f"file-{index}")
        media_kind = str(item.get("media_kind") or "document")
        parser = str(item.get("parser") or "markitdown")
        provenance_level = str(item.get("provenance_level") or "")
        char_count = item.get("char_count")
        extracted_image_count = item.get("extracted_image_count")
        embedded_asset_count = item.get("embedded_asset_count")

        lines.append("")
        provenance_text = f", provenance={provenance_level}" if provenance_level else ""
        lines.append(f"- File: `{file_name}` ({media_kind}, parser={parser}{provenance_text})")
        if isinstance(char_count, int):
            lines.append(f"- Nội dung parse được: khoảng {char_count} ký tự.")
        if isinstance(embedded_asset_count, int) and embedded_asset_count > 0:
            lines.append(
                f"- Parser phát hiện {embedded_asset_count} asset nhúng (hình/bảng); "
                "cần citation/vision rõ ràng trước khi mô tả chi tiết hình ảnh."
            )

        if media_kind == "video":
            duration = _first_markdown_line(markdown, "Duration")
            resolution = _first_markdown_line(markdown, "Resolution")
            has_audio = _first_markdown_line(markdown, "Has audio")
            if duration:
                lines.append(f"- Thời lượng video: {duration}.")
            if resolution:
                lines.append(f"- Độ phân giải: {resolution}.")
            if isinstance(extracted_image_count, int):
                lines.append(f"- Wiii đã trích {extracted_image_count} khung hình đại diện để gửi vào vision context.")
            if has_audio:
                lines.append(f"- Có audio: {has_audio}.")
            if "Transcript unavailable" in markdown:
                lines.append(
                    "- Transcript audio hiện chưa có; điều này chỉ nói rằng audio chưa được chuyển lời/ASR chưa khả dụng, "
                    "không chứng minh video không có giọng nói."
                )
        else:
            excerpt = _plain_markdown_excerpt(markdown)
            if excerpt:
                lines.append(f"- Trích đoạn đầu: {excerpt}")

    return _with_requested_response_marker(query, "\n".join(lines).strip())


def _uploaded_context_has_video(ctx: dict[str, Any]) -> bool:
    return any(
        str(item.get("media_kind") or "").strip().lower() == "video"
        for item in _uploaded_document_attachments(ctx)
    )


def _looks_uploaded_document_preview_request(query: str) -> bool:
    """Route document-to-course preview requests away from fact fast-paths."""
    folded = _fold_direct_text(query)
    if not folded:
        return False
    return _looks_uploaded_document_course_request(
        folded
    ) or _looks_uploaded_document_lesson_preview_request(
        folded
    )


def _looks_uploaded_context_fact_query(query: str, ctx: dict[str, Any]) -> bool:
    """Keep direct fact extraction from uploaded markdown off the slow LLM path."""
    if not _has_uploaded_document_context(ctx):
        return False
    folded = _fold_direct_text(query)
    if not folded:
        return False
    if _looks_uploaded_document_preview_request(query):
        return False
    if len([token for token in folded.split() if token]) > 90:
        return False
    fact_markers = (
        "bang",
        "char count",
        "csv",
        "doc vua upload",
        "docx",
        "eta",
        "file vua upload",
        "kpi",
        "latencybudget",
        "marker",
        "noi dung parse",
        "priority",
        "risk",
        "tom tat",
        "trich",
        "upload",
        "uu tien",
        "xlsx",
    )
    if any(marker in folded for marker in fact_markers):
        return True
    return _looks_uploaded_file_metadata_query(query, ctx)


def _looks_uploaded_file_metadata_query(query: str, ctx: dict[str, Any]) -> bool:
    """Keep simple uploaded-video fact questions deterministic and low-latency."""
    if not _uploaded_context_has_video(ctx):
        return False
    folded = _fold_direct_text(query)
    if not folded:
        return False
    metadata_markers = (
        "bao lau",
        "dai may",
        "dai bao",
        "thoi luong",
        "duration",
        "metadata",
        "do phan giai",
        "resolution",
        "fps",
        "frame",
        "khung hinh",
        "keyframe",
        "trich duoc",
        "bao nhieu khung",
        "may khung",
        "audio",
        "am thanh",
        "transcript",
    )
    return any(marker in folded for marker in metadata_markers)


def _looks_uploaded_file_visual_inspection_query(query: str) -> bool:
    folded = _fold_direct_text(query)
    frame_hint = any(
        marker in folded
        for marker in (
            "khung hinh",
            "keyframe",
            "frame",
            "anh trong video",
            "hinh anh",
            "video nay",
            "trong video",
        )
    )
    visual_action = any(
        marker in folded
        for marker in (
            "nhin",
            "thay gi",
            "mo ta",
            "kieu hinh",
            "noi dung",
            "trong do co gi",
            "co gi",
        )
    )
    return frame_hint and visual_action


def _provider_likely_supports_image_blocks(provider: str | None, model: str | None = None) -> bool:
    normalized_provider = str(provider or "").strip().lower()
    normalized_model = str(model or "").strip().lower()
    if normalized_provider in {"google", "zhipu"}:
        return True
    if normalized_provider == "openai":
        return any(marker in normalized_model for marker in ("gpt-4o", "gpt-4.1", "gpt-5", "vision"))
    if normalized_provider == "openrouter":
        return any(marker in normalized_model for marker in ("vision", "vl", "gpt-4o", "gpt-4.1", "gpt-5"))
    if normalized_provider == "nvidia":
        return any(
            marker in normalized_model
            for marker in (
                "vision",
                "vl",
                "neva",
                "paligemma",
                "gemma-3-",
                "gemma-3n-",
                "gemma-4-",
                "llama-4-maverick",
                "phi-4-multimodal",
                "ministral-14b-instruct",
                "mistral-large-3",
                "mistral-medium-3",
                "mistral-small-4",
                "kimi-k2.6",
                "qwen3.5-",
            )
        )
    return False


def _build_uploaded_document_visual_guard_answer(query: str, ctx: dict[str, Any]) -> str:
    base = _build_uploaded_document_context_fallback_answer(query, ctx)
    if not base:
        return ""
    guard = (
        "- Mình chưa mô tả nội dung thật bên trong các khung hình vì lượt này chưa chạy qua "
        "vision provider hợp lệ; nói khác đi, Wiii biết video đã có frame, nhưng không được đoán "
        "frame đó trông như thế nào."
    )
    if guard in base:
        return base
    return f"{base}\n{guard}"


async def _build_image_input_answer(query: str, images: list[Any]) -> str:
    first_base64 = next(
        (
            image
            for image in images
            if _image_payload_attr(image, "type", "base64") == "base64"
            and _image_payload_attr(image, "data", "")
        ),
        None,
    )
    if first_base64 is None:
        return _with_requested_response_marker(
            query,
            (
                "Mình thấy cậu đã gửi ảnh, nhưng hiện tại Wiii chỉ xử lý trực tiếp ảnh base64 "
                "trong chat. Hãy đính kèm lại ảnh trực tiếp trong khung chat để mình phân tích cho chắc."
            ),
        )

    try:
        from app.engine.vision_runtime import analyze_image_for_query

        result = await analyze_image_for_query(
            image_base64=_image_payload_attr(first_base64, "data", ""),
            query=query,
            media_type=_image_payload_attr(first_base64, "media_type", "image/jpeg"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[DIRECT] Vision image analysis failed: %s", exc)
        return _with_requested_response_marker(
            query,
            (
                "Mình đã nhận được ảnh, nhưng Vision runtime hiện bị lỗi khi phân tích. "
                "Mình không nên đoán nội dung ảnh; cậu thử gửi lại hoặc bật provider vision khả dụng nhé."
            ),
        )

    if getattr(result, "success", False) and str(getattr(result, "text", "")).strip():
        return _with_requested_response_marker(query, str(result.text).strip())

    return _with_requested_response_marker(
        query,
        (
            "Mình đã nhận được ảnh, nhưng hiện chưa có provider vision khả dụng để đọc ảnh này. "
            "Mình sẽ không đoán nội dung ảnh; hãy bật Vision runtime/provider vision rồi thử lại nhé."
        ),
    )
