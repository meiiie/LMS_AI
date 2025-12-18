"""
Vision Extractor for Multimodal RAG

CHỈ THỊ KỸ THUẬT SỐ 26: Vision-based Document Understanding
Uses Gemini 3 Flash (via settings.google_model) to extract text from document images.

**Feature: multimodal-rag-vision**
**Validates: Requirements 3.1, 3.2, 3.3, 8.1**

MIGRATION NOTE (12/2025):
- Migrated from google-generativeai (deprecated 31/8/2025) to google-genai SDK
- google-genai>=1.53.0 provides unified API for embeddings + vision
"""
import logging
import re
import time
import io
from typing import Optional, List
from dataclasses import dataclass, field

from google import genai
from google.genai import types
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ExtractionResult:
    """Result of vision extraction"""
    text: str
    has_tables: bool = False
    has_diagrams: bool = False
    headings_found: List[str] = field(default_factory=list)
    success: bool = True
    error: Optional[str] = None
    processing_time: float = 0.0


class VisionExtractor:
    """
    Gemini Vision-based text extraction for maritime documents.
    
    Extracts text from document images while preserving:
    - Article headings (Điều, Khoản)
    - Table structures (converted to Markdown)
    - Diagram descriptions (colors, positions, meanings)
    
    **Property 1: Table to Markdown Conversion**
    **Property 2: Diagram Description Completeness**
    **Property 5: Heading Preservation**
    """
    
    # Maritime-specific extraction prompt (CHỈ THỊ 26)
    MARITIME_EXTRACTION_PROMPT = """Đóng vai chuyên gia số hóa dữ liệu Hàng hải. 
Hãy nhìn bức ảnh này và mô tả lại toàn bộ nội dung thành văn bản định dạng Markdown.

HƯỚNG DẪN CHI TIẾT:
1. Giữ nguyên các tiêu đề (Điều, Khoản, Mục, Chương).
2. Nếu có Bảng biểu: Chuyển thành Markdown Table với header và separator (|---|).
3. Nếu có Hình vẽ (Đèn hiệu/Tàu bè): Mô tả chi tiết:
   - Màu sắc của đèn (đỏ, xanh, trắng, vàng)
   - Vị trí của đèn (mũi, lái, cột, mạn)
   - Ý nghĩa tín hiệu
4. Không bỏ sót bất kỳ chữ nào trên trang.
5. Giữ nguyên số hiệu điều luật (Rule 15, Điều 15, etc.)

OUTPUT FORMAT:
- Sử dụng Markdown headers (##, ###) cho tiêu đề
- Sử dụng Markdown tables cho bảng biểu
- Sử dụng bullet points cho danh sách
- Mô tả hình ảnh trong block [Hình: ...]"""

    # Rate limiting
    MAX_REQUESTS_PER_MINUTE = 10
    REQUEST_INTERVAL = 60.0 / MAX_REQUESTS_PER_MINUTE  # 6 seconds between requests
    
    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None
    ):
        """
        Initialize Vision Extractor.
        
        Args:
            model: Gemini model name (defaults to settings.google_model)
            api_key: Google API key (defaults to settings)
        """
        # SOTA Pattern: Use centralized config, no hardcoded model names
        self.model_name = model or settings.google_model
        self.api_key = api_key or settings.google_api_key
        
        # Initialize google-genai client (new unified SDK)
        self._client = None
        self._last_request_time = 0.0
    
    @property
    def client(self) -> genai.Client:
        """Lazy initialization of Gemini client"""
        if self._client is None:
            self._client = genai.Client(api_key=self.api_key)
        return self._client
    
    def _rate_limit(self):
        """Apply rate limiting between requests"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.REQUEST_INTERVAL:
            sleep_time = self.REQUEST_INTERVAL - elapsed
            logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
            time.sleep(sleep_time)
        self._last_request_time = time.time()
    
    async def extract_from_url(self, image_url: str) -> ExtractionResult:
        """
        Extract text from image URL using Vision Model.
        
        Args:
            image_url: Public URL of the image
            
        Returns:
            ExtractionResult with extracted text and metadata
        """
        start_time = time.time()
        
        try:
            # Apply rate limiting
            self._rate_limit()
            
            # Generate content from image URL using new SDK
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_text(text=self.MARITIME_EXTRACTION_PROMPT),
                            types.Part.from_uri(file_uri=image_url, mime_type="image/jpeg")
                        ]
                    )
                ]
            )
            
            text = response.text
            processing_time = time.time() - start_time
            
            # Analyze extraction result
            result = self._analyze_extraction(text)
            result.processing_time = processing_time
            
            logger.info(
                f"Extracted {len(text)} chars from image, "
                f"tables={result.has_tables}, diagrams={result.has_diagrams}, "
                f"headings={len(result.headings_found)}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Vision extraction failed: {e}")
            return ExtractionResult(
                text="",
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )
    
    async def extract_from_image(self, image: Image.Image) -> ExtractionResult:
        """
        Extract text from PIL Image using Vision Model.
        
        Args:
            image: PIL Image object
            
        Returns:
            ExtractionResult with extracted text and metadata
        """
        start_time = time.time()
        
        try:
            # Apply rate limiting
            self._rate_limit()
            
            # Convert PIL Image to bytes for new SDK
            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=85)
            image_bytes = buffer.getvalue()
            
            # Generate content from image bytes using new SDK
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=[
                    types.Content(
                        parts=[
                            types.Part.from_text(text=self.MARITIME_EXTRACTION_PROMPT),
                            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")
                        ]
                    )
                ]
            )
            
            text = response.text
            processing_time = time.time() - start_time
            
            # Analyze extraction result
            result = self._analyze_extraction(text)
            result.processing_time = processing_time
            
            logger.info(
                f"Extracted {len(text)} chars from image, "
                f"tables={result.has_tables}, diagrams={result.has_diagrams}"
            )
            
            return result
            
        except Exception as e:
            logger.error(f"Vision extraction failed: {e}")
            return ExtractionResult(
                text="",
                success=False,
                error=str(e),
                processing_time=time.time() - start_time
            )
    
    def _analyze_extraction(self, text: str) -> ExtractionResult:
        """
        Analyze extracted text for tables, diagrams, and headings.
        
        Args:
            text: Extracted text content
            
        Returns:
            ExtractionResult with analysis metadata
        """
        # Check for Markdown tables
        has_tables = bool(re.search(r'\|.*\|.*\|', text) and re.search(r'\|[-:]+\|', text))
        
        # Check for diagram descriptions
        diagram_keywords = ['đèn', 'đỏ', 'xanh', 'trắng', 'vàng', 'mũi', 'lái', 'cột', 'mạn', 'hình']
        has_diagrams = any(keyword in text.lower() for keyword in diagram_keywords)
        
        # Extract headings (Điều, Khoản, Rule)
        headings_found = []
        
        # Vietnamese headings
        dieu_matches = re.findall(r'Điều\s+\d+', text)
        headings_found.extend(dieu_matches)
        
        khoan_matches = re.findall(r'Khoản\s+\d+', text)
        headings_found.extend(khoan_matches)
        
        # English headings
        rule_matches = re.findall(r'Rule\s+\d+', text, re.IGNORECASE)
        headings_found.extend(rule_matches)
        
        return ExtractionResult(
            text=text,
            has_tables=has_tables,
            has_diagrams=has_diagrams,
            headings_found=list(set(headings_found)),  # Remove duplicates
            success=True
        )
    
    def validate_extraction(self, result: ExtractionResult) -> bool:
        """
        Validate extraction result meets quality standards.
        
        Args:
            result: ExtractionResult to validate
            
        Returns:
            True if extraction is valid
            
        **Property 16: No Text Content Skipped**
        """
        if not result.success:
            return False
        
        # Check minimum text length (at least some content)
        if len(result.text.strip()) < 50:
            logger.warning("Extraction too short, may have missed content")
            return False
        
        return True


# Singleton instance
_vision_extractor: Optional[VisionExtractor] = None


def get_vision_extractor() -> VisionExtractor:
    """Get or create singleton VisionExtractor instance"""
    global _vision_extractor
    if _vision_extractor is None:
        _vision_extractor = VisionExtractor()
    return _vision_extractor
