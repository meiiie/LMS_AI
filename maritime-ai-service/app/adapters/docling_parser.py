"""
DoclingParserAdapter — Docling-based document parser.

Converts PDF, DOCX, PPTX, HTML, LaTeX, images into structured Markdown.
- Digital pages: local AI models (DocLayNet + TableFormer), 0 API cost
- Scanned pages: VLM provider (Gemini, Ollama, etc.), configurable

Maritime-specific: detects Điều, Khoản, Chương, Rule, Section headings
for chapter-to-page mapping used by EXPAND node.

Design spec v2.0 (2026-03-22).
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Optional

from app.ports.document_parser import DocumentParserPort, ParsedDocument

logger = logging.getLogger(__name__)


@dataclass
class DoclingConfig:
    """Configuration for Docling document converter."""

    vlm_backend: str = "none"  # "gemini" | "ollama" | "granite_local" | "none"
    vlm_api_url: str = ""
    vlm_api_key: str = ""
    vlm_model: str = "gemini-3.1-flash-lite"
    vlm_concurrency: int = 3
    standard_pipeline: bool = True  # DocLayNet + TableFormer for digital pages


class DoclingParserAdapter(DocumentParserPort):
    """Parse documents using IBM Docling (Apache 2.0, 55K+ stars).

    Requires: pip install docling
    Or use Docling Serve: docker pull doclingproject/docling-serve

    Falls back gracefully if Docling is not installed.
    """

    def __init__(self, config: Optional[DoclingConfig] = None):
        self._config = config or DoclingConfig()
        self._converter = None
        self._init_converter()

    def _init_converter(self):
        """Initialize Docling DocumentConverter with configured pipeline."""
        try:
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.base_models import InputFormat

            format_options = {}

            if self._config.vlm_backend != "none" and self._config.vlm_api_url:
                try:
                    from docling.pipeline.vlm_pipeline import VlmPipeline
                    from docling.datamodel.pipeline_options import (
                        VlmPipelineOptions,
                        VlmConvertOptions,
                    )
                    from docling.datamodel.vlm_engine_options import (
                        ApiVlmEngineOptions,
                        VlmEngineType,
                    )

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
                    logger.info("Docling: VLM pipeline enabled (backend=%s)", self._config.vlm_backend)
                except ImportError:
                    logger.warning("Docling VLM pipeline not available, using standard pipeline only")

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
        """Convert document to structured Markdown via Docling."""
        if self._converter is None:
            raise NotImplementedError(
                "Docling is not installed. Install with: pip install docling"
            )

        logger.info("Docling: parsing %s", file_path)
        def _convert() -> ParsedDocument:
            result = self._converter.convert(file_path)
            doc = result.document

            markdown = doc.export_to_markdown()
            section_map = self._extract_section_map(doc)
            images = self._extract_images(doc)
            page_count = len(doc.pages) if hasattr(doc, "pages") else 0

            metadata = {
                "title": doc.name if hasattr(doc, "name") else "",
                "language": self._detect_language(markdown),
            }

            logger.info(
                "Docling: parsed %d pages, %d sections, %d images, %d chars markdown",
                page_count,
                len(section_map),
                len(images),
                len(markdown),
            )

            return ParsedDocument(
                markdown=markdown,
                page_count=page_count,
                metadata=metadata,
                section_map=section_map,
                images=images,
            )

        return await asyncio.to_thread(_convert)

    def _extract_section_map(self, doc) -> dict[str, list[int]]:
        """Map headings to page numbers — maritime-specific patterns."""
        section_map: dict[str, list[int]] = {}
        try:
            for item in doc.iterate_items():
                if hasattr(item, "label") and item.label in (
                    "section_header",
                    "title",
                ):
                    text = item.text if hasattr(item, "text") else str(item)
                    # Vietnamese maritime document patterns
                    for pattern in [
                        r"Chương\s+(\S+)",
                        r"Điều\s+(\d+)",
                        r"Khoản\s+(\d+)",
                        r"Phần\s+(\S+)",
                        r"Chapter\s+(\S+)",
                        r"Section\s+(\d+)",
                        r"Rule\s+(\d+)",
                        r"Part\s+(\S+)",
                    ]:
                        match = re.search(pattern, text)
                        if match:
                            key = match.group(0)
                            page = (
                                item.prov[0].page_no
                                if hasattr(item, "prov") and item.prov
                                else 0
                            )
                            section_map.setdefault(key, []).append(page)
        except Exception as e:
            logger.warning("Docling: section_map extraction failed: %s", e)
        return section_map

    def _extract_images(self, doc) -> list[dict]:
        """Extract image metadata from parsed document."""
        images = []
        try:
            for item in doc.iterate_items():
                if hasattr(item, "label") and item.label in ("picture", "figure"):
                    page = (
                        item.prov[0].page_no
                        if hasattr(item, "prov") and item.prov
                        else 0
                    )
                    images.append(
                        {
                            "page": page,
                            "label": item.label,
                            "text": item.text[:200] if hasattr(item, "text") else "",
                        }
                    )
        except Exception as e:
            logger.warning("Docling: image extraction failed: %s", e)
        return images

    def _detect_language(self, text: str) -> str:
        """Simple Vietnamese detection based on diacritics."""
        vi_chars = set("àáảãạăắằẳẵặâấầẩẫậèéẻẽẹêếềểễệìíỉĩịòóỏõọôốồổỗộơớờởỡợùúủũụưứừửữựỳýỷỹỵđ")
        sample = text[:2000].lower()
        vi_count = sum(1 for c in sample if c in vi_chars)
        return "vi" if vi_count > 20 else "en"

    def supported_formats(self) -> list[str]:
        return ["pdf", "docx", "pptx", "xlsx", "html", "png", "jpg", "tiff", "md", "latex"]
