"""Hybrid document parser router for fast and precision parsing lanes."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.ports.document_parser import DocumentParserPort, ParsedDocument

ParserMode = Literal["auto", "fast", "precision"]

PRECISION_EXTENSIONS = {".pdf", ".docx", ".pptx"}
PROVENANCE_RANK = {
    "none": 0,
    "text_only": 1,
    "structured_text": 2,
    "page_marker": 3,
    "page_layout": 4,
}


@dataclass(frozen=True)
class RoutedParseResult:
    parsed: ParsedDocument
    warning: str = ""


class DocumentParserRouter(DocumentParserPort):
    """Route document parsing between MarkItDown and Docling.

    - fast: MarkItDown only.
    - precision: Docling first, MarkItDown fallback.
    - auto: MarkItDown first, then promote to Docling if provenance is weak.
    """

    def __init__(
        self,
        *,
        markitdown_parser: DocumentParserPort | None,
        docling_parser: DocumentParserPort | None,
        mode: ParserMode = "auto",
        logger_obj: logging.Logger | None = None,
    ):
        self._markitdown_parser = markitdown_parser
        self._docling_parser = docling_parser
        self._mode = mode
        self._logger = logger_obj or logging.getLogger(__name__)

    @property
    def is_available(self) -> bool:
        return self._markitdown_parser is not None or self._docling_parser is not None

    async def parse(self, file_path: str, options: dict | None = None) -> ParsedDocument:
        ext = Path(file_path).suffix.lower()
        result = await self._parse_routed(file_path, ext, options or {})
        if result.warning:
            metadata = dict(result.parsed.metadata or {})
            metadata["parser_warning"] = result.warning
            result.parsed.metadata = metadata
        return result.parsed

    async def _parse_routed(
        self,
        file_path: str,
        ext: str,
        options: dict,
    ) -> RoutedParseResult:
        if self._mode == "fast":
            return RoutedParseResult(await self._parse_markitdown_required(file_path, options))

        if self._mode == "precision":
            docling = await self._try_parse_docling(file_path, options)
            if docling is not None:
                return RoutedParseResult(docling)
            warning = "Docling precision parser unavailable; fell back to MarkItDown."
            return RoutedParseResult(
                await self._parse_markitdown_required(file_path, options),
                warning=warning,
            )

        markitdown = await self._try_parse_markitdown(file_path, options)
        if markitdown is None:
            docling = await self._try_parse_docling(file_path, options)
            if docling is not None:
                return RoutedParseResult(docling)
            raise RuntimeError("No document parser is available on this backend.")

        if ext in PRECISION_EXTENSIONS and self._should_promote_to_docling(markitdown):
            docling = await self._try_parse_docling(file_path, options)
            if docling is not None and self._is_precision_upgrade(docling, markitdown):
                metadata = dict(docling.metadata or {})
                metadata["parser_chain"] = ["markitdown", "docling"]
                metadata["parser_warning"] = (
                    "Auto mode promoted this document from MarkItDown to Docling "
                    "because the fast parse had weak page/layout provenance."
                )
                docling.metadata = metadata
                return RoutedParseResult(docling)
            return RoutedParseResult(
                markitdown,
                warning=(
                    "Auto mode detected weak page/layout provenance, but Docling "
                    "precision parsing was unavailable or did not improve the result."
                ),
            )

        return RoutedParseResult(markitdown)

    async def _parse_markitdown_required(
        self,
        file_path: str,
        options: dict,
    ) -> ParsedDocument:
        parsed = await self._try_parse_markitdown(file_path, options)
        if parsed is None:
            raise RuntimeError("MarkItDown parser is not available on this backend.")
        return parsed

    async def _try_parse_markitdown(
        self,
        file_path: str,
        options: dict,
    ) -> ParsedDocument | None:
        if self._markitdown_parser is None:
            return None
        try:
            return await self._markitdown_parser.parse(file_path, options=options)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("MarkItDown parse failed: %s", exc)
            return None

    async def _try_parse_docling(
        self,
        file_path: str,
        options: dict,
    ) -> ParsedDocument | None:
        if self._docling_parser is None:
            return None
        try:
            return await self._docling_parser.parse(file_path, options=options)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("Docling parse failed: %s", exc)
            return None

    def _should_promote_to_docling(self, parsed: ParsedDocument) -> bool:
        metadata = parsed.metadata or {}
        provenance = str(metadata.get("provenance_level") or "text_only")
        if PROVENANCE_RANK.get(provenance, 0) <= PROVENANCE_RANK["text_only"]:
            return True
        return bool(parsed.markdown) and not parsed.section_map and not parsed.images

    def _is_precision_upgrade(
        self,
        candidate: ParsedDocument,
        baseline: ParsedDocument,
    ) -> bool:
        candidate_rank = PROVENANCE_RANK.get(
            str((candidate.metadata or {}).get("provenance_level") or "none"),
            0,
        )
        baseline_rank = PROVENANCE_RANK.get(
            str((baseline.metadata or {}).get("provenance_level") or "none"),
            0,
        )
        if candidate_rank > baseline_rank:
            return True
        if len(candidate.section_map or {}) > len(baseline.section_map or {}):
            return True
        return len(candidate.images or []) > len(baseline.images or [])

    def supported_formats(self) -> list[str]:
        formats: set[str] = set()
        for parser in (self._markitdown_parser, self._docling_parser):
            if parser is not None:
                formats.update(parser.supported_formats())
        return sorted(formats)


def normalize_parser_mode(value: str | None) -> ParserMode:
    normalized = str(value or "auto").strip().lower()
    if normalized in {"fast", "markitdown"}:
        return "fast"
    if normalized in {"precision", "docling"}:
        return "precision"
    return "auto"
