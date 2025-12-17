"""
Semantic Chunking Service for Multimodal RAG

Feature: semantic-chunking
Splits extracted text into semantic chunks with maritime-specific intelligence.

**Feature: semantic-chunking**
**Validates: Requirements 1.1, 1.2, 2.1, 2.2, 2.3, 2.4, 3.1, 3.2, 3.3, 3.4, 5.1, 5.2, 5.3, 5.4**
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ChunkResult:
    """Result of semantic chunking for a single chunk"""
    chunk_index: int
    content: str
    content_type: str = "text"  # text, table, heading, diagram_reference, formula
    confidence_score: float = 1.0  # 0.0-1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    contextual_content: Optional[str] = None  # Contextual RAG: LLM-enriched content


class SemanticChunker:
    """
    Semantic chunking service optimized for maritime documents.
    
    Splits text into focused chunks with:
    - Content type detection (text, table, heading, diagram_reference, formula)
    - Confidence scoring based on chunk quality
    - Maritime document hierarchy extraction (Điều, Khoản, Rule)
    
    **Property 1: Chunk Size Bounds**
    **Property 3: Content Type Valid Enum**
    **Property 6: Confidence Score Bounds**
    """
    
    # Valid content types
    VALID_CONTENT_TYPES = {"text", "table", "heading", "diagram_reference", "formula"}
    
    def __init__(
        self,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
        min_chunk_size: Optional[int] = None
    ):
        """
        Initialize SemanticChunker.
        
        Args:
            chunk_size: Target chunk size (default from settings)
            chunk_overlap: Overlap between chunks (default from settings)
            min_chunk_size: Minimum chunk size (default from settings)
        """
        self.chunk_size = chunk_size or settings.chunk_size
        self.chunk_overlap = chunk_overlap or settings.chunk_overlap
        self.min_chunk_size = min_chunk_size or settings.min_chunk_size
        
        # Initialize LangChain text splitter
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=[
                "\n\n",  # Paragraph breaks
                "\n",    # Line breaks
                ". ",    # Sentence endings
                "! ",    # Exclamations
                "? ",    # Questions
                "; ",    # Semicolons
                ", ",    # Commas
                " ",     # Spaces
                ""       # Fallback
            ],
            length_function=len,
            is_separator_regex=False
        )
        
        # Maritime-specific patterns for hierarchy extraction
        self.maritime_patterns = {
            'article': re.compile(r'(Điều|điều|Article|article)\s+(\d+)', re.IGNORECASE),
            'clause': re.compile(r'(Khoản|khoản|Clause|clause)\s+(\d+)', re.IGNORECASE),
            'point': re.compile(r'(Điểm|điểm|Point|point)\s+([a-zA-Z])', re.IGNORECASE),
            'rule': re.compile(r'(Rule|rule)\s+(\d+)', re.IGNORECASE),
            'table': re.compile(r'(Bảng|bảng|Table|table)\s+(\d+)', re.IGNORECASE)
        }
        
        logger.info(
            f"SemanticChunker initialized: chunk_size={self.chunk_size}, "
            f"overlap={self.chunk_overlap}, min_size={self.min_chunk_size}"
        )
    
    async def chunk_page_content(
        self,
        text: str,
        page_metadata: Dict[str, Any]
    ) -> List[ChunkResult]:
        """
        Split page content into semantic chunks with maritime-specific intelligence.
        
        Args:
            text: Full text content from a page
            page_metadata: Metadata about the page (document_id, page_number, etc.)
            
        Returns:
            List of ChunkResult objects
            
        **Property 1: Chunk Size Bounds**
        **Property 2: Chunk Count Increases with Text Length**
        """
        if not text or not text.strip():
            logger.warning("Empty text provided for chunking")
            return []
        
        # Split text using LangChain
        raw_chunks = self.text_splitter.split_text(text)
        
        if not raw_chunks:
            logger.warning("No chunks generated from text")
            return []
        
        processed_chunks = []
        
        for i, chunk_text in enumerate(raw_chunks):
            chunk_text = chunk_text.strip()
            
            # Skip empty chunks
            if not chunk_text:
                continue
            
            # Merge very small chunks with previous if possible
            if len(chunk_text) < self.min_chunk_size and processed_chunks:
                # Merge with previous chunk
                prev_chunk = processed_chunks[-1]
                merged_content = prev_chunk.content + "\n" + chunk_text
                prev_chunk.content = merged_content
                # Recalculate confidence for merged chunk
                prev_chunk.confidence_score = self._calculate_confidence(
                    merged_content, prev_chunk.content_type
                )
                continue
            
            # Detect content type
            content_type = self._detect_content_type(chunk_text)
            
            # Calculate confidence score
            confidence_score = self._calculate_confidence(chunk_text, content_type)
            
            # Extract document hierarchy
            hierarchy = self._extract_document_hierarchy(chunk_text)
            
            # Build metadata
            metadata = self._build_metadata(chunk_text, page_metadata, content_type, hierarchy)
            
            processed_chunks.append(ChunkResult(
                chunk_index=len(processed_chunks),  # Sequential index
                content=chunk_text,
                content_type=content_type,
                confidence_score=confidence_score,
                metadata=metadata
            ))
        
        logger.info(
            f"Chunked page {page_metadata.get('page_number', '?')}: "
            f"{len(processed_chunks)} chunks from {len(text)} chars"
        )
        
        return processed_chunks
    
    def _detect_content_type(self, text: str) -> str:
        """
        Detect content type with maritime document intelligence.
        
        **Property 3: Content Type Valid Enum**
        **Property 4: Table Detection Accuracy**
        **Property 5: Heading Detection for Maritime Patterns**
        """
        text_lower = text.lower().strip()
        
        # Check for Markdown table patterns (| and ---)
        has_pipe = '|' in text
        has_separator = bool(re.search(r'\|[-:]+\|', text))
        if has_pipe and has_separator:
            return 'table'
        
        # Check for table-like structure (multiple columns with tabs or spaces)
        lines = text.split('\n')
        if len(lines) > 2:
            tab_lines = sum(1 for line in lines if '\t' in line or '  ' in line)
            if tab_lines > len(lines) * 0.5:
                return 'table'
        
        # Check for maritime legal patterns (heading)
        if self.maritime_patterns['article'].search(text):
            return 'heading'
        if self.maritime_patterns['clause'].search(text):
            return 'heading'
        if self.maritime_patterns['rule'].search(text):
            return 'heading'
        
        # Check for diagram/image references
        diagram_keywords = ['hình', 'sơ đồ', 'biểu đồ', 'figure', 'diagram', 'illustration']
        if any(keyword in text_lower for keyword in diagram_keywords):
            if re.search(r'(hình|sơ đồ|biểu đồ|figure|diagram)\s+\d+', text_lower):
                return 'diagram_reference'
        
        # Check for mathematical formulas
        if re.search(r'(\d+\s*[+\-*/=]\s*\d+)|(\d+\s*[×÷]\s*\d+)', text):
            return 'formula'
        
        # Default to text
        return 'text'
    
    def _calculate_confidence(self, chunk: str, content_type: str) -> float:
        """
        Calculate confidence score based on chunk quality and content type.
        
        **Property 6: Confidence Score Bounds**
        **Property 7: Short Chunk Confidence Penalty**
        **Property 8: Long Chunk Confidence Penalty**
        **Property 9: Structured Content Confidence Boost**
        """
        length = len(chunk.strip())
        
        # Base confidence based on length
        if length < self.min_chunk_size:
            # Short chunk penalty
            base_confidence = 0.6
        elif length > 1000:
            # Long chunk penalty
            base_confidence = 0.7
        else:
            # Optimal length
            base_confidence = 1.0
        
        # Boost for structured content types (heading, table)
        if content_type in ['heading', 'table']:
            boosted = base_confidence * 1.2
            return min(1.0, boosted)  # Cap at 1.0
        
        return base_confidence
    
    def _extract_document_hierarchy(self, chunk: str) -> Dict[str, Any]:
        """
        Extract document hierarchy information for maritime documents.
        
        **Property 11: Article Number Extraction**
        **Property 12: Clause Number Extraction**
        """
        hierarchy = {}
        
        # Extract article number
        if match := self.maritime_patterns['article'].search(chunk):
            hierarchy['article'] = match.group(2)
        
        # Extract clause number
        if match := self.maritime_patterns['clause'].search(chunk):
            hierarchy['clause'] = match.group(2)
        
        # Extract point identifier
        if match := self.maritime_patterns['point'].search(chunk):
            hierarchy['point'] = match.group(2).lower()
        
        # Extract rule number
        if match := self.maritime_patterns['rule'].search(chunk):
            hierarchy['rule'] = match.group(2)
        
        return hierarchy
    
    def _build_metadata(
        self,
        chunk: str,
        page_metadata: Dict[str, Any],
        content_type: str,
        hierarchy: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build comprehensive metadata for the chunk."""
        # Detect language
        vietnamese_chars = 'ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ'
        has_vietnamese = any(char in chunk.lower() for char in vietnamese_chars)
        
        return {
            'page_number': page_metadata.get('page_number'),
            'document_id': page_metadata.get('document_id'),
            'image_url': page_metadata.get('image_url'),
            'content_type': content_type,
            'section_hierarchy': hierarchy,
            'word_count': len(chunk.split()),
            'char_count': len(chunk),
            'language': 'vi' if has_vietnamese else 'en',
            'processing_timestamp': page_metadata.get('processing_timestamp'),
            'source_type': page_metadata.get('source_type', 'pdf')
        }


# Singleton instance
_chunker_instance: Optional[SemanticChunker] = None


def get_semantic_chunker() -> SemanticChunker:
    """Get or create singleton SemanticChunker instance"""
    global _chunker_instance
    if _chunker_instance is None:
        _chunker_instance = SemanticChunker()
    return _chunker_instance
