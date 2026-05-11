"""MarkItDownParserAdapter - Microsoft MarkItDown document parser.

This adapter is intentionally optional. Wiii can import the adapter in a
production image that has not installed MarkItDown yet; parsing only becomes
available when the dependency is present.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.ports.document_parser import DocumentParserPort, ParsedDocument

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MarkItDownConfig:
    """Configuration for local MarkItDown conversion."""

    enable_plugins: bool = False
    local_only: bool = True


class MarkItDownParserAdapter(DocumentParserPort):
    """Parse common office/document formats to Markdown via MarkItDown."""

    _SUPPORTED_FORMATS = [
        "pdf",
        "docx",
        "pptx",
        "xlsx",
        "xls",
        "html",
        "htm",
        "csv",
        "json",
        "xml",
        "txt",
        "md",
        "epub",
        "zip",
        "wav",
        "mp3",
        "m4a",
        "mp4",
        "aiff",
        "flac",
        "jpg",
        "jpeg",
        "png",
        "gif",
        "webp",
    ]

    def __init__(self, config: Optional[MarkItDownConfig] = None):
        self._config = config or MarkItDownConfig()
        self._converter = None
        self._init_converter()

    def _init_converter(self) -> None:
        try:
            from markitdown import MarkItDown

            self._converter = MarkItDown(enable_plugins=self._config.enable_plugins)
            logger.info("MarkItDown DocumentConverter initialized")
        except ImportError:
            logger.warning(
                "MarkItDown not installed. MarkItDownParserAdapter will raise "
                "NotImplementedError on parse()."
            )
            self._converter = None

    @property
    def is_available(self) -> bool:
        return self._converter is not None

    async def parse(self, file_path: str, options: dict | None = None) -> ParsedDocument:
        """Convert a local document file to structured Markdown."""
        if self._converter is None:
            raise NotImplementedError(
                "MarkItDown is not installed. Install with: "
                "pip install 'markitdown[pdf,docx,pptx,xlsx,audio-transcription]'"
            )

        ext = Path(file_path).suffix.lower().lstrip(".")
        if ext not in self._SUPPORTED_FORMATS:
            raise ValueError(f"Unsupported MarkItDown file extension: .{ext}")

        def _convert() -> ParsedDocument:
            logger.info("MarkItDown: parsing %s", file_path)
            if self._config.local_only and hasattr(self._converter, "convert_local"):
                result = self._converter.convert_local(file_path)
            else:
                result = self._converter.convert(file_path)

            markdown = (
                getattr(result, "markdown", None)
                or getattr(result, "text_content", "")
                or str(result)
            )
            title = getattr(result, "title", None) or os.path.basename(file_path)
            section_map = self._extract_section_map(markdown)
            page_count = self._estimate_page_count(markdown)
            provenance_level = (
                "page_marker"
                if re.search(r"<!--\s*page\s+\d+\s*-->", markdown, re.IGNORECASE)
                else "text_only"
            )

            return ParsedDocument(
                markdown=markdown,
                page_count=page_count,
                metadata={
                    "title": title,
                    "parser": "markitdown",
                    "parser_chain": ["markitdown"],
                    "provenance_level": provenance_level,
                    "source_extension": ext,
                },
                section_map=section_map,
                images=[],
                assets=[],
            )

        return await asyncio.to_thread(_convert)

    def supported_formats(self) -> list[str]:
        return list(self._SUPPORTED_FORMATS)

    @staticmethod
    def _estimate_page_count(markdown: str) -> int:
        page_numbers = {
            int(match.group(1))
            for match in re.finditer(
                r"<!--\s*page\s+(\d+)\s*-->",
                markdown,
                re.IGNORECASE,
            )
        }
        return max(page_numbers) if page_numbers else 1

    @staticmethod
    def _extract_section_map(markdown: str) -> dict[str, list[int]]:
        section_map: dict[str, list[int]] = {}
        current_page = 1
        for line in markdown.splitlines():
            page_match = re.search(r"<!--\s*page\s+(\d+)\s*-->", line, re.IGNORECASE)
            if page_match:
                current_page = int(page_match.group(1))
                continue

            heading_match = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$", line)
            if not heading_match:
                continue
            heading = heading_match.group(2).strip()
            if heading:
                section_map.setdefault(heading, []).append(current_page)
        return section_map
