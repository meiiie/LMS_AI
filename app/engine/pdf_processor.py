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

from PyPDF2 import PdfReader

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
    Processes PDF documents for Knowledge Graph ingestion.
    
    Handles text extraction and intelligent chunking with
    sentence boundary preservation and overlap.
    
    **Feature: knowledge-ingestion**
    **Validates: Requirements 2.1, 2.2, 2.5, 3.1, 3.2, 3.4**
    """
    
    # Sentence ending patterns
    SENTENCE_ENDINGS = re.compile(r'[.!?]\s+')
    
    # Section header patterns (common in maritime docs)
    HEADER_PATTERNS = re.compile(
        r'^(Rule\s+\d+|CHAPTER\s+\d+|Section\s+\d+|Article\s+\d+|Part\s+[A-Z])',
        re.IGNORECASE | re.MULTILINE
    )
    
    def __init__(
        self,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
        min_chunk_size: int = 200
    ):
        """
        Initialize PDF Processor.
        
        Args:
            chunk_size: Target size for each chunk (default 800 chars)
            chunk_overlap: Overlap between consecutive chunks (default 100 chars)
            min_chunk_size: Minimum chunk size to avoid tiny fragments
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.min_chunk_size = min_chunk_size
    
    def extract_text(self, file_path: str) -> str:
        """
        Extract all text content from a PDF file.
        
        Args:
            file_path: Path to the PDF file
            
        Returns:
            Extracted text with preserved paragraph structure
            
        Raises:
            ValueError: If file is not a valid PDF
            FileNotFoundError: If file does not exist
            
        **Validates: Requirements 2.1, 2.2, 2.5**
        """
        path = Path(file_path)
        
        if not path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")
        
        if not path.suffix.lower() == '.pdf':
            raise ValueError(f"File is not a PDF: {file_path}")
        
        try:
            reader = PdfReader(file_path)
            text_parts = []
            
            for page_num, page in enumerate(reader.pages):
                page_text = page.extract_text()
                if page_text:
                    # Preserve page structure with marker
                    text_parts.append(f"[Page {page_num + 1}]\n{page_text}")
                else:
                    logger.warning(f"No text extracted from page {page_num + 1}")
            
            # Join with double newline to preserve paragraph structure
            full_text = "\n\n".join(text_parts)
            
            # Clean up excessive whitespace while preserving structure
            full_text = re.sub(r'\n{3,}', '\n\n', full_text)
            full_text = re.sub(r' {2,}', ' ', full_text)
            
            logger.info(f"Extracted {len(full_text)} chars from {len(reader.pages)} pages")
            return full_text
            
        except Exception as e:
            logger.error(f"Failed to extract text from PDF: {e}")
            raise ValueError(f"Unable to process PDF file: {e}")
    
    def chunk_text(
        self,
        text: str,
        chunk_size: Optional[int] = None,
        overlap: Optional[int] = None
    ) -> List[Chunk]:
        """
        Split text into chunks with sentence boundary preservation.
        
        Args:
            text: Text to chunk
            chunk_size: Override default chunk size
            overlap: Override default overlap
            
        Returns:
            List of Chunk objects
            
        **Validates: Requirements 3.1, 3.2, 3.4**
        """
        if not text or len(text) < self.min_chunk_size:
            if text:
                return [Chunk(index=0, content=text, start_char=0, end_char=len(text))]
            return []
        
        target_size = chunk_size or self.chunk_size
        target_overlap = overlap or self.chunk_overlap
        
        chunks = []
        current_pos = 0
        chunk_index = 0
        
        while current_pos < len(text):
            # Calculate end position
            end_pos = min(current_pos + target_size, len(text))
            
            # If not at the end, find sentence boundary
            if end_pos < len(text):
                # Look for sentence ending within the chunk
                chunk_text = text[current_pos:end_pos]
                
                # Find the last sentence ending
                last_sentence_end = self._find_last_sentence_end(chunk_text)
                
                if last_sentence_end > self.min_chunk_size:
                    end_pos = current_pos + last_sentence_end
            
            # Extract chunk content
            chunk_content = text[current_pos:end_pos].strip()
            
            if chunk_content:
                chunks.append(Chunk(
                    index=chunk_index,
                    content=chunk_content,
                    start_char=current_pos,
                    end_char=end_pos
                ))
                chunk_index += 1
            
            # Move position with overlap
            if end_pos >= len(text):
                break
            
            # Calculate next position (subtract overlap)
            current_pos = end_pos - target_overlap
            
            # Ensure we make progress
            if current_pos <= chunks[-1].start_char if chunks else 0:
                current_pos = end_pos
        
        logger.info(f"Created {len(chunks)} chunks from {len(text)} chars")
        return chunks
    
    def _find_last_sentence_end(self, text: str) -> int:
        """
        Find the position of the last sentence ending in text.
        
        Returns position after the sentence ending punctuation,
        or -1 if no sentence ending found.
        """
        # Find all sentence endings
        matches = list(self.SENTENCE_ENDINGS.finditer(text))
        
        if matches:
            # Return position after the last match
            last_match = matches[-1]
            return last_match.end()
        
        # Fallback: look for any punctuation followed by space
        for i in range(len(text) - 1, -1, -1):
            if text[i] in '.!?:' and i < len(text) - 1:
                return i + 1
        
        return -1
    
    def detect_structure(self, text: str) -> DocumentStructure:
        """
        Detect document structure (headers, sections).
        
        Args:
            text: Document text
            
        Returns:
            DocumentStructure with detected elements
        """
        # Find section headers
        sections = self.HEADER_PATTERNS.findall(text)
        
        # Try to extract title (first non-empty line)
        lines = text.split('\n')
        title = None
        for line in lines:
            line = line.strip()
            if line and not line.startswith('[Page'):
                title = line[:100]  # Limit title length
                break
        
        # Count pages
        page_markers = re.findall(r'\[Page \d+\]', text)
        
        return DocumentStructure(
            title=title,
            total_pages=len(page_markers),
            total_chars=len(text),
            sections=sections
        )
    
    def generate_title(self, chunk: Chunk) -> str:
        """
        Generate a descriptive title from chunk content.
        
        Uses first sentence or first N characters.
        
        **Validates: Requirements 4.2**
        """
        content = chunk.content.strip()
        
        # Remove page markers
        content = re.sub(r'\[Page \d+\]\s*', '', content)
        
        # Try to get first sentence
        match = self.SENTENCE_ENDINGS.search(content)
        if match and match.start() < 150:
            title = content[:match.start() + 1].strip()
        else:
            # Use first 100 chars
            title = content[:100].strip()
            if len(content) > 100:
                title += "..."
        
        # Clean up
        title = re.sub(r'\s+', ' ', title)
        return title
    
    @staticmethod
    def compute_hash(content: bytes) -> str:
        """
        Compute SHA-256 hash of content for duplicate detection.
        
        **Validates: Requirements 4.4**
        """
        return hashlib.sha256(content).hexdigest()
