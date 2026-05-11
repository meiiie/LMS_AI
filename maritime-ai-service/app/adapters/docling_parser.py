"""Docling-based document parser.

Docling is the precision parser lane for documents where page/layout
provenance matters. It complements MarkItDown rather than replacing it:
MarkItDown remains the fast LLM-ready Markdown converter, while Docling gives
Wiii stronger page, figure, table, and layout signals when available.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.ports.document_parser import DocumentParserPort, ParsedDocument

logger = logging.getLogger(__name__)

OFFICE_EXTENSIONS = {"docx", "pptx", "xlsx"}


@dataclass
class DoclingConfig:
    """Configuration for Docling document conversion."""

    vlm_backend: str = "none"  # "gemini" | "ollama" | "granite_local" | "none"
    vlm_api_url: str = ""
    vlm_api_key: str = ""
    vlm_model: str = "gemini-3.1-flash-lite"
    vlm_concurrency: int = 3
    standard_pipeline: bool = True


class DoclingParserAdapter(DocumentParserPort):
    """Parse documents using Docling when the optional dependency exists."""

    def __init__(self, config: Optional[DoclingConfig] = None):
        self._config = config or DoclingConfig()
        self._converter = None
        self._init_converter()

    def _init_converter(self) -> None:
        try:
            from docling.datamodel.base_models import InputFormat
            from docling.document_converter import DocumentConverter, PdfFormatOption

            format_options = {}
            if self._config.vlm_backend != "none" and self._config.vlm_api_url:
                try:
                    from docling.datamodel.pipeline_options import (
                        VlmConvertOptions,
                        VlmPipelineOptions,
                    )
                    from docling.datamodel.vlm_engine_options import (
                        ApiVlmEngineOptions,
                        VlmEngineType,
                    )
                    from docling.pipeline.vlm_pipeline import VlmPipeline

                    vlm_engine = ApiVlmEngineOptions(
                        runtime_type=VlmEngineType.API,
                        url=self._config.vlm_api_url,
                        headers={"Authorization": f"Bearer {self._config.vlm_api_key}"},
                        params={
                            "model": self._config.vlm_model,
                            "max_completion_tokens": 4096,
                        },
                        timeout=120,
                        concurrency=self._config.vlm_concurrency,
                    )
                    vlm_options = VlmConvertOptions(engine_options=vlm_engine)
                    format_options[InputFormat.PDF] = PdfFormatOption(
                        pipeline_cls=VlmPipeline,
                        pipeline_options=VlmPipelineOptions(vlm_options=vlm_options),
                    )
                    logger.info(
                        "Docling: VLM pipeline enabled (backend=%s)",
                        self._config.vlm_backend,
                    )
                except ImportError:
                    logger.warning(
                        "Docling VLM pipeline not available, using standard pipeline only"
                    )

            self._converter = DocumentConverter(format_options=format_options)
            logger.info("Docling DocumentConverter initialized")
        except ImportError:
            logger.warning(
                "Docling not installed (pip install docling). "
                "DoclingParserAdapter will raise NotImplementedError on parse()."
            )
            self._converter = None

    @property
    def is_available(self) -> bool:
        return self._converter is not None

    async def parse(self, file_path: str, options: dict | None = None) -> ParsedDocument:
        """Convert a document to Markdown plus page-grounded metadata."""
        if self._converter is None:
            raise NotImplementedError(
                "Docling is not installed. Install with: pip install docling"
            )

        logger.info("Docling: parsing %s", file_path)

        def _convert() -> ParsedDocument:
            result = self._converter.convert(file_path)
            doc = result.document

            raw_markdown = doc.export_to_markdown()
            section_map = self._extract_section_map(doc)
            assets = self._extract_assets(doc)
            images = [
                asset
                for asset in assets
                if asset.get("kind") in {"image", "figure", "picture"}
            ]
            page_count = len(doc.pages) if hasattr(doc, "pages") else 0
            has_page_provenance = page_count > 0 or any(section_map.values()) or any(
                asset.get("page") for asset in assets
            )
            markdown = self._inject_page_markers(raw_markdown, section_map)

            source_extension = Path(file_path).suffix.lower().lstrip(".")
            office_layout_converter = self._office_layout_converter()
            metadata = {
                "title": getattr(doc, "name", "") or Path(file_path).name,
                "language": self._detect_language(markdown),
                "parser": "docling",
                "parser_chain": ["docling"],
                "provenance_level": "page_layout" if has_page_provenance else "structured_text",
                "has_page_provenance": has_page_provenance,
                "source_extension": source_extension,
                "office_layout_converter": office_layout_converter or "",
                "section_count": len(section_map),
                "embedded_asset_count": len(assets),
                "figure_count": sum(
                    1 for item in assets if item.get("kind") in {"image", "figure", "picture"}
                ),
                "table_count": sum(1 for item in assets if item.get("kind") == "table"),
            }
            if source_extension in OFFICE_EXTENSIONS and not office_layout_converter:
                metadata["parser_warning"] = (
                    "Docling parsed Office structure, but no LibreOffice converter "
                    "is available for page/layout and embedded image export. "
                    "Set DOCLING_LIBREOFFICE_CMD or use the production precision image."
                )

            logger.info(
                "Docling: parsed %d pages, %d sections, %d assets, %d chars markdown",
                page_count,
                len(section_map),
                len(assets),
                len(markdown),
            )

            return ParsedDocument(
                markdown=markdown,
                page_count=page_count,
                metadata=metadata,
                section_map=section_map,
                images=images,
                assets=assets,
            )

        return await asyncio.to_thread(_convert)

    def _extract_section_map(self, doc) -> dict[str, list[int]]:
        """Map generic headings and maritime aliases to page numbers."""
        section_map: dict[str, list[int]] = {}
        try:
            for item in self._iter_doc_items(doc):
                label = self._label_name(item)
                if label not in {"section_header", "title"}:
                    continue
                text = self._item_text(item)
                if not text:
                    continue
                page = self._first_page(item)
                self._append_section_page(section_map, text, page)
                for pattern in (
                    r"Ch\u01b0\u01a1ng\s+(\S+)",
                    r"\u0110i\u1ec1u\s+(\d+)",
                    r"Kho\u1ea3n\s+(\d+)",
                    r"Ph\u1ea7n\s+(\S+)",
                    r"Chapter\s+(\S+)",
                    r"Section\s+(\d+)",
                    r"Rule\s+(\d+)",
                    r"Part\s+(\S+)",
                ):
                    match = re.search(pattern, text, re.IGNORECASE)
                    if match:
                        self._append_section_page(section_map, match.group(0), page)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Docling: section_map extraction failed: %s", exc)
        return section_map

    def _extract_assets(self, doc) -> list[dict]:
        """Extract page-grounded figure/table metadata from a Docling document."""
        assets: list[dict] = []
        try:
            index = 1
            for item in self._iter_doc_items(doc):
                label = self._label_name(item)
                if label not in {"picture", "figure", "table"}:
                    continue
                kind = "image" if label in {"picture", "figure"} else "table"
                page = self._first_page(item)
                assets.append(
                    {
                        "id": f"docling-{kind}-{index}",
                        "kind": kind,
                        "page": page if page > 0 else None,
                        "label": label,
                        "text": self._item_text(item)[:500],
                        "bbox": self._first_bbox(item),
                        "source": "docling",
                    }
                )
                index += 1
        except Exception as exc:  # noqa: BLE001
            logger.warning("Docling: asset extraction failed: %s", exc)
        return assets

    @staticmethod
    def _iter_doc_items(doc):
        """Yield Docling items across both pre- and post-2.x iterate APIs."""
        for entry in doc.iterate_items():
            if isinstance(entry, tuple) and entry:
                yield entry[0]
            else:
                yield entry

    @staticmethod
    def _office_layout_converter() -> str:
        configured = str(os.getenv("DOCLING_LIBREOFFICE_CMD") or "").strip()
        if configured and Path(configured).exists():
            return configured
        return shutil.which("soffice") or shutil.which("libreoffice") or ""

    @staticmethod
    def _label_name(item) -> str:
        label = getattr(item, "label", "")
        value = getattr(label, "value", label)
        return str(value or "").split(".")[-1].lower()

    @staticmethod
    def _item_text(item) -> str:
        text = getattr(item, "text", "")
        if not text:
            text = getattr(item, "caption", "")
        return re.sub(r"\s+", " ", str(text or "")).strip()

    @staticmethod
    def _first_page(item) -> int:
        prov = getattr(item, "prov", None)
        if not prov:
            return 0
        try:
            return int(getattr(prov[0], "page_no", 0) or 0)
        except (TypeError, ValueError, IndexError):
            return 0

    @staticmethod
    def _first_bbox(item) -> dict | None:
        prov = getattr(item, "prov", None)
        if not prov:
            return None
        bbox = getattr(prov[0], "bbox", None)
        if bbox is None:
            return None
        out: dict[str, float] = {}
        for key in ("l", "t", "r", "b", "x0", "y0", "x1", "y1"):
            value = getattr(bbox, key, None)
            if value is not None:
                try:
                    out[key] = float(value)
                except (TypeError, ValueError):
                    pass
        return out or None

    @staticmethod
    def _append_section_page(
        section_map: dict[str, list[int]],
        title: str,
        page: int,
    ) -> None:
        clean = re.sub(r"\s+", " ", str(title or "").strip(" #\t\r\n"))[:180]
        if not clean:
            return
        pages = section_map.setdefault(clean, [])
        if page > 0 and page not in pages:
            pages.append(page)

    @staticmethod
    def _inject_page_markers(markdown: str, section_map: dict[str, list[int]]) -> str:
        if not markdown or "<!-- page " in markdown.lower():
            return markdown
        heading_to_page = {
            title.strip().lower(): min(pages)
            for title, pages in section_map.items()
            if title and pages
        }
        if not heading_to_page:
            return markdown
        lines: list[str] = []
        last_page = 0
        for line in markdown.splitlines():
            match = re.match(r"^(\s{0,3}#{1,6}\s+)(.+?)\s*$", line)
            if match:
                page = heading_to_page.get(match.group(2).strip().lower())
                if page and page != last_page:
                    lines.append(f"<!-- page {page} -->")
                    last_page = page
            lines.append(line)
        return "\n".join(lines)

    def _detect_language(self, text: str) -> str:
        """Simple Vietnamese detection based on diacritics."""
        vi_chars = set(
            "àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệ"
            "ìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ"
        )
        sample = text[:2000].lower()
        vi_count = sum(1 for char in sample if char in vi_chars)
        return "vi" if vi_count > 20 else "en"

    def supported_formats(self) -> list[str]:
        return ["pdf", "docx", "pptx", "xlsx", "html", "png", "jpg", "tiff", "md", "latex"]
