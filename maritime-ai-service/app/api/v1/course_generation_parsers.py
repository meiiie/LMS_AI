"""Parser helpers for course generation uploads."""

from __future__ import annotations

import asyncio
import os


def try_build_docling_parser(*, settings_obj, logger):
    try:
        from app.adapters.docling_parser import DoclingConfig, DoclingParserAdapter

        parser = DoclingParserAdapter(
            DoclingConfig(
                vlm_backend=getattr(settings_obj, "docling_vlm_backend", "none"),
                vlm_api_url=getattr(settings_obj, "docling_vlm_api_url", "") or "",
                vlm_api_key=getattr(settings_obj, "docling_vlm_api_key", "") or "",
                vlm_model=getattr(
                    settings_obj,
                    "docling_vlm_model",
                    "gemini-3.1-flash-lite",
                ),
            )
        )
        if parser.is_available:
            return parser
        logger.warning("Docling not installed, using pymupdf fallback where possible")
        return None
    except ImportError:
        logger.warning("Docling not installed, using pymupdf fallback where possible")
        return None


def try_build_markitdown_parser(*, settings_obj, logger):
    try:
        from app.adapters.markitdown_parser import (
            MarkItDownConfig,
            MarkItDownParserAdapter,
        )

        parser = MarkItDownParserAdapter(
            MarkItDownConfig(
                enable_plugins=getattr(
                    settings_obj,
                    "markitdown_enable_plugins",
                    False,
                )
            )
        )
        if parser.is_available:
            return parser
    except ImportError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning("MarkItDown parser unavailable: %s", exc)
    return None


def ensure_docling_available(ext: str, *, settings_obj, logger) -> None:
    if try_build_markitdown_parser(settings_obj=settings_obj, logger=logger) is not None:
        return
    if try_build_docling_parser(settings_obj=settings_obj, logger=logger) is None:
        raise RuntimeError(
            f"{ext} uploads require MarkItDown or Docling support. "
            "Install MarkItDown/Docling or upload a PDF instead."
        )


class BasicPdfParser:
    """Fallback parser using pymupdf (already installed)."""

    async def parse(self, file_path: str, options: dict | None = None):
        from app.ports.document_parser import ParsedDocument

        def _extract():
            if os.path.splitext(file_path)[1].lower() != ".pdf":
                raise RuntimeError("Basic parser only supports PDF uploads")
            try:
                import pymupdf

                doc = pymupdf.open(file_path)
                pages = [page.get_text() for page in doc]
                markdown = "\n\n---\n\n".join(
                    f"<!-- page {i + 1} -->\n{text}" for i, text in enumerate(pages)
                )
                return ParsedDocument(
                    markdown=markdown,
                    page_count=len(pages),
                    metadata={
                        "title": os.path.basename(file_path),
                        "parser": "pymupdf_basic",
                        "parser_chain": ["pymupdf_basic"],
                        "provenance_level": "page_marker",
                    },
                    section_map={},
                    images=[],
                    assets=[],
                )
            except ImportError:
                with open(file_path, "r", errors="ignore", encoding="utf-8") as handle:
                    text = handle.read()
                return ParsedDocument(
                    markdown=text,
                    page_count=1,
                    metadata={
                        "title": os.path.basename(file_path),
                        "parser": "text_fallback",
                        "parser_chain": ["text_fallback"],
                        "provenance_level": "text_only",
                    },
                    section_map={},
                    images=[],
                    assets=[],
                )

        return await asyncio.to_thread(_extract)

    def supported_formats(self):
        return ["pdf"]


def get_parser(file_path: str, *, settings_obj, logger):
    """Get document parser: MarkItDown/Docling when available, pymupdf fallback."""
    ext = os.path.splitext(file_path)[1].lower()
    should_use_rich_parser = getattr(settings_obj, "use_docling_for_course_gen", False) or ext in {
        ".docx",
        ".pptx",
        ".xlsx",
    }
    if should_use_rich_parser:
        if getattr(settings_obj, "use_docling_for_course_gen", False):
            parser = try_build_docling_parser(settings_obj=settings_obj, logger=logger)
            if parser is not None:
                return parser

        markitdown_parser = try_build_markitdown_parser(
            settings_obj=settings_obj,
            logger=logger,
        )
        if markitdown_parser is not None:
            return markitdown_parser

        parser = try_build_docling_parser(settings_obj=settings_obj, logger=logger)
        if parser is not None:
            return parser
        if ext in {".docx", ".pptx", ".xlsx"}:
            raise RuntimeError(
                f"{ext} uploads require MarkItDown or Docling to be installed"
            )

    return BasicPdfParser()
