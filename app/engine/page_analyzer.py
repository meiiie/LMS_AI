"""
Page Analyzer for Hybrid Text/Vision Detection

Feature: hybrid-text-vision
Analyzes PDF pages to determine optimal extraction method:
- Text-only pages → Direct extraction via PyMuPDF (free, fast)
- Visual pages → Vision extraction via Gemini (accurate for tables/diagrams)

Goal: Reduce Gemini Vision API calls by 50-70%

**Validates: Requirements 1.1, 2.1, 2.2, 2.3, 2.4, 2.5**
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    import fitz

logger = logging.getLogger(__name__)


@dataclass
class PageAnalysisResult:
    """
    Result of page content analysis.
    
    Determines whether a page should use direct extraction (PyMuPDF)
    or vision extraction (Gemini Vision API).
    
    **Feature: hybrid-text-vision**
    **Property 1: Page Classification Completeness**
    """
    page_number: int
    has_images: bool = False
    has_tables: bool = False
    has_diagrams: bool = False
    has_maritime_signals: bool = False
    text_length: int = 0
    recommended_method: str = "direct"  # "direct" or "vision"
    confidence: float = 1.0  # 0.0-1.0
    detection_reasons: List[str] = field(default_factory=list)
    
    @property
    def is_visual_content(self) -> bool:
        """Check if page contains any visual content indicators"""
        return self.has_images or self.has_tables or self.has_diagrams or self.has_maritime_signals


class PageAnalyzer:
    """
    Analyzes PDF pages to determine optimal extraction method.
    
    Detection criteria for visual content:
    - Embedded images (via PyMuPDF get_images())
    - Table patterns (pipe characters, grid patterns)
    - Diagram keywords (hình, figure, sơ đồ)
    - Maritime signal keywords (đèn, tín hiệu, cờ)
    
    **Feature: hybrid-text-vision**
    **Property 2: Visual Content Detection Implies Vision**
    **Property 3: Plain Text Implies Direct**
    """
    
    # Table detection patterns
    DEFAULT_TABLE_PATTERNS = [
        r'\|[^|]+\|[^|]+\|',  # Markdown table: |col1|col2|
        r'[┌┐└┘├┤─│┬┴┼]',     # Unicode box drawing
        r'\+[-=]+\+',          # ASCII table: +---+
    ]
    
    # Diagram reference keywords (Vietnamese + English)
    DEFAULT_DIAGRAM_KEYWORDS = [
        'hình', 'figure', 'sơ đồ', 'biểu đồ', 'diagram',
        'minh họa', 'illustration', 'bản vẽ', 'drawing'
    ]
    
    # Maritime signal keywords
    DEFAULT_MARITIME_KEYWORDS = [
        'đèn', 'tín hiệu', 'cờ', 'còi', 'pháo hiệu',
        'light', 'signal', 'flag', 'whistle', 'flare',
        'đèn đỏ', 'đèn xanh', 'đèn trắng', 'đèn vàng',
        'red light', 'green light', 'white light',
        'mạn phải', 'mạn trái', 'starboard', 'port'
    ]
    
    def __init__(
        self,
        table_patterns: Optional[List[str]] = None,
        diagram_keywords: Optional[List[str]] = None,
        maritime_keywords: Optional[List[str]] = None,
        min_text_length: int = 100
    ):
        """
        Initialize PageAnalyzer with configurable patterns.
        
        Args:
            table_patterns: Regex patterns for table detection
            diagram_keywords: Keywords indicating diagram content
            maritime_keywords: Keywords indicating maritime signals
            min_text_length: Minimum text length for direct extraction
            
        **Validates: Requirements 3.1, 3.2**
        """
        self.table_patterns = table_patterns or self.DEFAULT_TABLE_PATTERNS
        self.diagram_keywords = diagram_keywords or self.DEFAULT_DIAGRAM_KEYWORDS
        self.maritime_keywords = maritime_keywords or self.DEFAULT_MARITIME_KEYWORDS
        self.min_text_length = min_text_length
        
        # Compile regex patterns for efficiency
        self._table_regex = [re.compile(p, re.IGNORECASE) for p in self.table_patterns]
        
        logger.info(
            f"PageAnalyzer initialized: {len(self.table_patterns)} table patterns, "
            f"{len(self.diagram_keywords)} diagram keywords, "
            f"{len(self.maritime_keywords)} maritime keywords"
        )
    
    def analyze_page(self, page: "fitz.Page", page_number: int = 1) -> PageAnalysisResult:
        """
        Analyze a single PDF page and recommend extraction method.
        
        Args:
            page: PyMuPDF page object
            page_number: 1-indexed page number
            
        Returns:
            PageAnalysisResult with recommendation
            
        **Property 1: Page Classification Completeness**
        **Validates: Requirements 1.1, 2.1, 2.2, 2.3, 2.4, 2.5**
        """
        result = PageAnalysisResult(page_number=page_number)
        
        try:
            # Check for embedded images
            images = page.get_images()
            if images:
                result.has_images = True
                result.detection_reasons.append(f"Found {len(images)} embedded image(s)")
            
            # Extract text for analysis
            text = page.get_text()
            result.text_length = len(text)
            text_lower = text.lower()
            
            # Check for table patterns
            for pattern in self._table_regex:
                if pattern.search(text):
                    result.has_tables = True
                    result.detection_reasons.append(f"Table pattern detected: {pattern.pattern}")
                    break
            
            # Check for diagram keywords
            for keyword in self.diagram_keywords:
                if keyword.lower() in text_lower:
                    result.has_diagrams = True
                    result.detection_reasons.append(f"Diagram keyword found: '{keyword}'")
                    break
            
            # Check for maritime signal keywords
            for keyword in self.maritime_keywords:
                if keyword.lower() in text_lower:
                    result.has_maritime_signals = True
                    result.detection_reasons.append(f"Maritime keyword found: '{keyword}'")
                    break
            
            # Determine recommended method
            if result.is_visual_content:
                result.recommended_method = "vision"
                result.confidence = 0.9
            elif result.text_length < self.min_text_length:
                # Short text might indicate scanned image or complex layout
                result.recommended_method = "vision"
                result.confidence = 0.7
                result.detection_reasons.append(
                    f"Text too short ({result.text_length} < {self.min_text_length})"
                )
            else:
                result.recommended_method = "direct"
                result.confidence = 0.95
                
        except Exception as e:
            logger.error(f"Error analyzing page {page_number}: {e}")
            # Default to vision on error (safer)
            result.recommended_method = "vision"
            result.confidence = 0.5
            result.detection_reasons.append(f"Analysis error: {str(e)}")
        
        logger.debug(
            f"Page {page_number} analysis: method={result.recommended_method}, "
            f"confidence={result.confidence:.2f}, reasons={result.detection_reasons}"
        )
        
        return result
    
    def should_use_vision(self, result: PageAnalysisResult) -> bool:
        """
        Determine if Vision API should be used based on analysis result.
        
        Args:
            result: PageAnalysisResult from analyze_page()
            
        Returns:
            True if Vision extraction is recommended
            
        **Property 4: Routing Follows Classification**
        **Validates: Requirements 1.2, 1.3**
        """
        return result.recommended_method == "vision"
    
    def analyze_text_content(self, text: str) -> dict:
        """
        Analyze raw text content for visual indicators.
        
        Useful for testing without actual PDF pages.
        
        Args:
            text: Text content to analyze
            
        Returns:
            Dict with detection results
        """
        text_lower = text.lower()
        
        has_tables = any(p.search(text) for p in self._table_regex)
        has_diagrams = any(kw.lower() in text_lower for kw in self.diagram_keywords)
        has_maritime = any(kw.lower() in text_lower for kw in self.maritime_keywords)
        
        return {
            'has_tables': has_tables,
            'has_diagrams': has_diagrams,
            'has_maritime_signals': has_maritime,
            'text_length': len(text),
            'is_visual': has_tables or has_diagrams or has_maritime
        }


# Singleton instance
_page_analyzer: Optional[PageAnalyzer] = None


def get_page_analyzer() -> PageAnalyzer:
    """Get or create singleton PageAnalyzer instance"""
    global _page_analyzer
    if _page_analyzer is None:
        _page_analyzer = PageAnalyzer()
    return _page_analyzer
