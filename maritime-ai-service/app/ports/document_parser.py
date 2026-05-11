"""
DocumentParserPort — Clean Architecture port for document conversion.

Abstracts the document parsing implementation so that Docling, pymupdf+Vision,
or any future parser can be swapped via configuration without changing business logic.

Design spec v2.0 (2026-03-22).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ParsedDocument:
    """Result of parsing a document into structured content."""

    markdown: str
    """Full structured markdown representation of the document."""

    page_count: int
    """Total number of pages in the source document."""

    metadata: dict = field(default_factory=dict)
    """Document metadata: title, authors, language detected, etc."""

    section_map: dict[str, list[int]] = field(default_factory=dict)
    """Heading text → page numbers mapping. Used by EXPAND node to
    query only relevant content for each chapter."""

    images: list[dict] = field(default_factory=list)
    """Extracted images with metadata (page, bounding box, URL)."""

    assets: list[dict] = field(default_factory=list)
    """Structured embedded assets such as figures, pictures, and tables."""


class DocumentParserPort(ABC):
    """Parse any document format into structured markdown.

    Implementations: DoclingParserAdapter, PyMuPDFVisionAdapter (legacy), MockParser (test).
    """

    @abstractmethod
    async def parse(self, file_path: str, options: dict | None = None) -> ParsedDocument:
        """Convert a document file to structured markdown.

        Args:
            file_path: Path to the uploaded document (PDF, DOCX, PPTX, etc.)
            options: Optional parser-specific options (language, max_pages, etc.)

        Returns:
            ParsedDocument with markdown, section_map, images, metadata.
        """
        ...

    @abstractmethod
    def supported_formats(self) -> list[str]:
        """Return list of supported file extensions (e.g., ['pdf', 'docx', 'pptx'])."""
        ...
