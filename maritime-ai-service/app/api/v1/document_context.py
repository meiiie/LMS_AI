"""Per-turn document context parsing for chat uploads.

This endpoint converts user-selected documents to Markdown so the desktop
client can attach the result as structured chat context without permanently
ingesting the file into org knowledge.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, File, HTTPException, UploadFile, status
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
MAX_EXTRACTED_IMAGES = 5

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


class DocumentContextParseResponse(BaseModel):
    file_name: str
    mime_type: str | None = None
    media_kind: Literal["document", "video"] = "document"
    size_bytes: int
    parser: str = "markitdown"
    title: str | None = None
    page_count: int | None = None
    section_titles: list[str] = Field(default_factory=list)
    markdown: str
    char_count: int
    truncated: bool = False
    extracted_images: list[DocumentContextExtractedImage] = Field(default_factory=list)
    extracted_image_count: int = 0


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


def _build_parser():
    try:
        from app.adapters.markitdown_parser import (
            MarkItDownConfig,
            MarkItDownParserAdapter,
        )
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MarkItDown is not installed on this backend.",
        ) from exc

    parser = MarkItDownParserAdapter(
        MarkItDownConfig(
            enable_plugins=getattr(settings, "markitdown_enable_plugins", False),
        )
    )
    if not getattr(parser, "is_available", False):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="MarkItDown parser is not available on this backend.",
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
    section_titles = [
        str(title).strip()
        for title in (parsed.section_map or {}).keys()
        if str(title).strip()
    ][:MAX_SECTION_TITLES]
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

    return DocumentContextParseResponse(
        file_name=file_name,
        mime_type=mime_type,
        media_kind=media_kind,
        size_bytes=size_bytes,
        parser=str(metadata.get("parser") or "markitdown"),
        title=str(metadata.get("title") or file_name),
        page_count=parsed.page_count,
        section_titles=section_titles,
        markdown=markdown,
        char_count=len(raw_markdown),
        truncated=truncated,
        extracted_images=extracted_images,
        extracted_image_count=len(extracted_images),
    )


@router.post("/parse", response_model=DocumentContextParseResponse)
async def parse_document_context(
    auth: RequireAuth,
    file: UploadFile = File(..., description="PDF, Word, PowerPoint, Excel, CSV, TXT, Markdown, or video file"),
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

    parser = _build_video_parser() if ext in VIDEO_EXTENSIONS else _build_parser()
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
