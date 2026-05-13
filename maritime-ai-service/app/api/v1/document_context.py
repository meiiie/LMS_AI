"""Per-turn document context parsing for chat uploads.

This endpoint converts user-selected documents to Markdown so the desktop
client can attach the result as structured chat context without permanently
ingesting the file into org knowledge.
"""

from __future__ import annotations

import logging
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import RequireAuth
from app.core.config import settings
from app.ports.document_parser import ParsedDocument

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/document-context", tags=["Document Context"])

MAX_DOCUMENT_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_VIDEO_UPLOAD_BYTES = 80 * 1024 * 1024
MAX_MARKDOWN_CHARS = 30_000
MAX_SECTION_TITLES = 24
MAX_SECTION_SNIPPETS = 80
MAX_SECTION_SNIPPET_CHARS = 1_500
MAX_SECTION_SNIPPET_TOTAL_CHARS = 80_000
MAX_EXTRACTED_IMAGES = 5
MAX_EMBEDDED_ASSETS = 20

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".xls",
    ".csv",
    ".txt",
    ".md",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".m4v",
    ".mov",
    ".webm",
    ".mkv",
}
ALLOWED_EXTENSIONS = DOCUMENT_EXTENSIONS | VIDEO_EXTENSIONS

EXTENSION_LABELS = ", ".join(sorted(ALLOWED_EXTENSIONS))


class DocumentContextExtractedImage(BaseModel):
    id: str
    label: str | None = None
    timestamp_seconds: float | None = None
    media_type: str = "image/jpeg"
    data: str
    detail: Literal["auto", "low", "high"] = "low"


class DocumentContextEmbeddedAsset(BaseModel):
    id: str
    kind: Literal["image", "figure", "picture", "table"] = "image"
    label: str | None = None
    page: int | None = None
    text: str | None = None
    bbox: dict[str, float] | None = None
    has_data: bool = False


class DocumentContextSectionSnippet(BaseModel):
    title: str
    markdown: str
    char_start: int
    char_end: int
    source_pages: list[int] = Field(default_factory=list)
    page_start: int | None = None
    page_end: int | None = None


class DocumentContextParseResponse(BaseModel):
    file_name: str
    mime_type: str | None = None
    media_kind: Literal["document", "video"] = "document"
    size_bytes: int
    parser: str = "markitdown"
    parser_chain: list[str] = Field(default_factory=list)
    parser_warning: str | None = None
    provenance_level: Literal[
        "text_only",
        "structured_text",
        "page_marker",
        "page_layout",
    ] = "text_only"
    title: str | None = None
    page_count: int | None = None
    section_titles: list[str] = Field(default_factory=list)
    section_snippets: list[DocumentContextSectionSnippet] = Field(default_factory=list)
    markdown: str
    char_count: int
    truncated: bool = False
    extracted_images: list[DocumentContextExtractedImage] = Field(default_factory=list)
    extracted_image_count: int = 0
    embedded_assets: list[DocumentContextEmbeddedAsset] = Field(default_factory=list)
    embedded_asset_count: int = 0
    figure_count: int = 0
    table_count: int = 0


def _safe_upload_name(file: UploadFile) -> str:
    name = Path(file.filename or "").name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing file name.",
        )
    return name


def _validate_extension(file_name: str) -> str:
    ext = Path(file_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {ext or '(none)'}. Supported: {EXTENSION_LABELS}.",
        )
    return ext


def _build_markitdown_parser():
    try:
        from app.adapters.markitdown_parser import (
            MarkItDownConfig,
            MarkItDownParserAdapter,
        )
    except ImportError as exc:
        logger.warning("MarkItDown import failed: %s", exc)
        return None

    parser = MarkItDownParserAdapter(
        MarkItDownConfig(
            enable_plugins=getattr(settings, "markitdown_enable_plugins", False),
        )
    )
    if not getattr(parser, "is_available", False):
        return None
    return parser


def _build_docling_parser():
    try:
        from app.adapters.docling_parser import DoclingConfig, DoclingParserAdapter
    except ImportError as exc:
        logger.warning("Docling import failed: %s", exc)
        return None

    parser = DoclingParserAdapter(
        DoclingConfig(
            vlm_backend=getattr(settings, "docling_vlm_backend", "none"),
            vlm_api_url=getattr(settings, "docling_vlm_api_url", "") or "",
            vlm_api_key=getattr(settings, "docling_vlm_api_key", "") or "",
            vlm_model=getattr(settings, "docling_vlm_model", "gemini-3.1-flash-lite"),
        )
    )
    if not getattr(parser, "is_available", False):
        return None
    return parser


def _build_parser(parser_mode: str | None = None):
    from app.adapters.document_parser_router import (
        DocumentParserRouter,
        normalize_parser_mode,
    )

    configured_mode = parser_mode or getattr(settings, "document_context_parser_mode", "auto")
    mode = normalize_parser_mode(configured_mode)
    parser = DocumentParserRouter(
        markitdown_parser=_build_markitdown_parser(),
        docling_parser=_build_docling_parser(),
        mode=mode,
        logger_obj=logger,
    )
    if not parser.is_available:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="No document parser is available on this backend.",
        )
    return parser


def _build_video_parser():
    try:
        from app.adapters.video_context_parser import (
            VideoContextParserAdapter,
            VideoContextParserConfig,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Video parser is not installed on this backend.",
        ) from exc

    parser = VideoContextParserAdapter(
        VideoContextParserConfig(
            enable_markitdown_transcript=True,
        )
    )
    if not getattr(parser, "is_available", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Video parsing requires ffmpeg and ffprobe on the backend.",
        )
    return parser


def _clean_section_title(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip(" #\t\r\n"))[:180]


def _score_section_title(value: str) -> int:
    normalized = (
        re.sub(r"[\u0300-\u036f]", "", unicodedata.normalize("NFD", str(value or "").lower()))
        .replace("đ", "d")
        .replace("Đ", "D")
    )
    if re.search(r"\b(giang vien|giao vien|teacher|instructor)\b", normalized):
        return 100
    if re.search(
        r"(tao khoa|soan|chuong va bai|cau hoi|bai tap|xuat ban|quiz|video tuong tac)",
        normalized,
    ):
        return 85
    if re.search(r"\b(hoc vien|student|learner)\b", normalized):
        return 65
    if re.search(r"\b(quan ly|admin|manager)\b", normalized):
        return 55
    if re.search(r"(checklist|quy trinh|van hanh|troubleshoot|xu ly loi)", normalized):
        return 45
    return 0


def _section_pages(section_map: dict[str, list[int]], title: str) -> list[int]:
    pages = section_map.get(title) or section_map.get(_clean_section_title(title)) or []
    clean_pages: list[int] = []
    for page in pages:
        try:
            parsed_page = int(page)
        except (TypeError, ValueError):
            continue
        if parsed_page > 0 and parsed_page not in clean_pages:
            clean_pages.append(parsed_page)
    return clean_pages


def _select_section_indices(candidates: list[dict[str, Any]]) -> list[int]:
    if len(candidates) <= MAX_SECTION_SNIPPETS:
        return list(range(len(candidates)))

    selected: set[int] = set(range(min(8, len(candidates))))
    selected.update(range(max(0, len(candidates) - 8), len(candidates)))

    priority_indices = sorted(
        range(len(candidates)),
        key=lambda idx: (
            -int(candidates[idx].get("priority") or 0),
            int(candidates[idx].get("start") or 0),
        ),
    )
    for index in priority_indices:
        if len(selected) >= MAX_SECTION_SNIPPETS:
            break
        if int(candidates[index].get("priority") or 0) <= 0:
            break
        selected.add(index)

    if len(selected) < MAX_SECTION_SNIPPETS:
        stride = max(1, len(candidates) // MAX_SECTION_SNIPPETS)
        for index in range(0, len(candidates), stride):
            selected.add(index)
            if len(selected) >= MAX_SECTION_SNIPPETS:
                break

    return sorted(selected)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _document_title_from_metadata(metadata: dict[str, Any], file_name: str) -> str:
    """Prefer the user's upload name when parsers only saw a temp file path."""
    title = str(metadata.get("title") or "").strip()
    if not title:
        return file_name

    stem = Path(title).stem
    suffix = Path(title).suffix
    if re.fullmatch(r"tmp[a-zA-Z0-9_-]{6,}", stem) and not suffix:
        return file_name
    return title


def _build_section_snippets(
    *,
    raw_markdown: str,
    section_map: dict[str, list[int]],
) -> list[DocumentContextSectionSnippet]:
    headings: list[dict[str, Any]] = []
    for match in re.finditer(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$", raw_markdown):
        title = _clean_section_title(match.group(1))
        if title:
            headings.append(
                {
                    "title": title,
                    "start": match.start(),
                    "priority": _score_section_title(title),
                }
            )
    if not headings:
        return []

    candidates: list[dict[str, Any]] = []
    for index, heading in enumerate(headings):
        start = int(heading["start"])
        end = int(headings[index + 1]["start"]) if index + 1 < len(headings) else len(raw_markdown)
        section_text = raw_markdown[start:end].strip()
        if not section_text:
            continue
        candidates.append({**heading, "end": end, "markdown": section_text})

    snippets: list[DocumentContextSectionSnippet] = []
    total_chars = 0
    for index in _select_section_indices(candidates):
        candidate = candidates[index]
        section_text = str(candidate["markdown"]).strip()
        snippet_text = section_text[:MAX_SECTION_SNIPPET_CHARS].rstrip()
        if len(snippet_text) < len(section_text):
            snippet_text = f"{snippet_text}\n\n[Section excerpt truncated]"
        if not snippet_text:
            continue
        if total_chars + len(snippet_text) > MAX_SECTION_SNIPPET_TOTAL_CHARS:
            break
        title = str(candidate["title"])
        pages = _section_pages(section_map, title)
        snippets.append(
            DocumentContextSectionSnippet(
                title=title,
                markdown=snippet_text,
                char_start=int(candidate["start"]),
                char_end=int(candidate["end"]),
                source_pages=pages,
                page_start=min(pages) if pages else None,
                page_end=max(pages) if pages else None,
            )
        )
        total_chars += len(snippet_text)
    return snippets


def _response_from_parsed(
    *,
    parsed: ParsedDocument,
    file_name: str,
    mime_type: str | None,
    size_bytes: int,
) -> DocumentContextParseResponse:
    raw_markdown = parsed.markdown or ""
    markdown = raw_markdown
    truncated = False
    if len(markdown) > MAX_MARKDOWN_CHARS:
        markdown = markdown[:MAX_MARKDOWN_CHARS].rstrip()
        truncated = True

    metadata: dict[str, Any] = parsed.metadata or {}
    media_kind = "video" if str(metadata.get("media_kind") or "").lower() == "video" else "document"
    parser = str(metadata.get("parser") or "markitdown")
    parser_chain = metadata.get("parser_chain")
    if not isinstance(parser_chain, list) or not parser_chain:
        parser_chain = [parser]
    parser_chain = [str(item) for item in parser_chain if str(item).strip()]
    provenance_level = str(metadata.get("provenance_level") or "text_only")
    if provenance_level not in {
        "text_only",
        "structured_text",
        "page_marker",
        "page_layout",
    }:
        provenance_level = "text_only"
    section_titles = [
        str(title).strip()
        for title in (parsed.section_map or {}).keys()
        if str(title).strip()
    ][:MAX_SECTION_TITLES]
    section_snippets = _build_section_snippets(
        raw_markdown=raw_markdown,
        section_map=parsed.section_map or {},
    )
    extracted_images: list[DocumentContextExtractedImage] = []
    for index, image in enumerate(parsed.images[:MAX_EXTRACTED_IMAGES], start=1):
        if not isinstance(image, dict):
            continue
        data = str(image.get("data") or "").strip()
        if not data:
            continue
        extracted_images.append(
            DocumentContextExtractedImage(
                id=str(image.get("id") or f"extracted-image-{index}"),
                label=str(image.get("label") or f"Image {index}"),
                timestamp_seconds=image.get("timestamp_seconds"),
                media_type=str(image.get("media_type") or "image/jpeg"),
                data=data,
                detail=image.get("detail") if image.get("detail") in {"auto", "low", "high"} else "low",
            )
        )
    embedded_assets: list[DocumentContextEmbeddedAsset] = []
    raw_assets = parsed.assets or parsed.images or []
    for index, asset in enumerate(raw_assets[:MAX_EMBEDDED_ASSETS], start=1):
        if not isinstance(asset, dict):
            continue
        kind = str(asset.get("kind") or asset.get("label") or "image").lower()
        if kind == "picture":
            kind = "image"
        if kind not in {"image", "figure", "picture", "table"}:
            kind = "image"
        page_value = asset.get("page")
        try:
            page = int(page_value) if page_value is not None else None
        except (TypeError, ValueError):
            page = None
        bbox = asset.get("bbox")
        embedded_assets.append(
            DocumentContextEmbeddedAsset(
                id=str(asset.get("id") or f"embedded-asset-{index}"),
                kind=kind,
                label=str(asset.get("label") or kind),
                page=page if page and page > 0 else None,
                text=str(asset.get("text") or "")[:500] or None,
                bbox=bbox if isinstance(bbox, dict) else None,
                has_data=bool(str(asset.get("data") or "").strip()),
            )
        )
    figure_count = _safe_int(metadata.get("figure_count"))
    table_count = _safe_int(metadata.get("table_count"))
    if figure_count <= 0:
        figure_count = sum(1 for asset in embedded_assets if asset.kind in {"image", "figure", "picture"})
    if table_count <= 0:
        table_count = sum(1 for asset in embedded_assets if asset.kind == "table")

    return DocumentContextParseResponse(
        file_name=file_name,
        mime_type=mime_type,
        media_kind=media_kind,
        size_bytes=size_bytes,
        parser=parser,
        parser_chain=parser_chain,
        parser_warning=str(metadata.get("parser_warning") or "") or None,
        provenance_level=provenance_level,
        title=_document_title_from_metadata(metadata, file_name),
        page_count=parsed.page_count,
        section_titles=section_titles,
        section_snippets=section_snippets,
        markdown=markdown,
        char_count=len(raw_markdown),
        truncated=truncated,
        extracted_images=extracted_images,
        extracted_image_count=len(extracted_images),
        embedded_assets=embedded_assets,
        embedded_asset_count=_safe_int(
            metadata.get("embedded_asset_count"),
            len(embedded_assets),
        ),
        figure_count=figure_count,
        table_count=table_count,
    )


@router.post("/parse", response_model=DocumentContextParseResponse)
async def parse_document_context(
    auth: RequireAuth,
    file: UploadFile = File(..., description="PDF, Word, PowerPoint, Excel, CSV, TXT, Markdown, or video file"),
    parser_mode: str = Form("auto", description="auto, fast, or precision"),
) -> DocumentContextParseResponse:
    """Parse an uploaded document into Markdown for the next chat turn."""
    file_name = _safe_upload_name(file)
    ext = _validate_extension(file_name)

    content = await file.read()
    size_bytes = len(content)
    if size_bytes <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File is empty.",
        )
    max_upload_bytes = MAX_VIDEO_UPLOAD_BYTES if ext in VIDEO_EXTENSIONS else MAX_DOCUMENT_UPLOAD_BYTES
    if size_bytes > max_upload_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {max_upload_bytes // 1024 // 1024}MB.",
        )

    parser_mode_value = parser_mode if isinstance(parser_mode, str) else "auto"
    parser = _build_video_parser() if ext in VIDEO_EXTENSIONS else _build_parser(parser_mode_value)
    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp_file:
            tmp_file.write(content)
            tmp_path = tmp_file.name

        parsed = await parser.parse(tmp_path, options={"source_name": file_name})
        logger.info(
            "[DOCUMENT_CONTEXT] user=%s file=%s bytes=%d chars=%d",
            getattr(auth, "user_id", "?"),
            file_name,
            size_bytes,
            len(parsed.markdown or ""),
        )
        return _response_from_parsed(
            parsed=parsed,
            file_name=file_name,
            mime_type=file.content_type,
            size_bytes=size_bytes,
        )
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.warning("[DOCUMENT_CONTEXT] parse failed for %s: %s", file_name, exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not parse this document into Markdown.",
        ) from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                logger.debug("[DOCUMENT_CONTEXT] temp cleanup failed: %s", tmp_path)
