"""
ARCHIVED: Legacy PDF Processor for Neo4j Knowledge Ingestion

This file has been archived as part of the sparse-search-migration.
PDF processing is now handled by:
- PyMuPDF (fitz) for PDF to image conversion
- Gemini Vision for text extraction
- SemanticChunker for intelligent chunking

Original location: app/engine/pdf_processor.py
Archived date: 2025-12-09
Reason: Replaced by multimodal pipeline (vision_extractor.py + chunking_service.py)

See: .kiro/specs/semantic-chunking/design.md for new chunking approach.
"""

# Original content below for reference
# =====================================

"""
PDF Processor for Knowledge Ingestion.

Extracts text from PDF documents and chunks it for Neo4j storage.

Feature: knowledge-ingestion
Requirements: 2.1, 2.2, 2.5, 3.1, 3.2, 3.4
"""

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# from pypdf import PdfReader  # Still available but not used in new pipeline

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """Represents a text chunk from a document."""
    index: int
    content: str
    start_char: int
    end_char: int
    
    @property
    def length(self) -> int:
        return len(self.content)


@dataclass
class DocumentStructure:
    """Represents the structure of a parsed document."""
    title: Optional[str]
    total_pages: int
    total_chars: int
    sections: List[str]


class PDFProcessor:
    """
    ARCHIVED: Processes PDF documents for Neo4j Knowledge Graph ingestion.
    
    This has been replaced by:
    - multimodal_ingestion_service.py: PDF → Images → Vision → Text
    - chunking_service.py: SemanticChunker with maritime-specific patterns
    
    **Feature: knowledge-ingestion**
    **Validates: Requirements 2.1, 2.2, 2.5, 3.1, 3.2, 3.4**
    """
    pass  # Implementation archived - see original file in git history
