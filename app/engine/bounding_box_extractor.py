"""
BoundingBoxExtractor - Extract and normalize bounding boxes from PDF pages.

Feature: source-highlight-citation
Validates: Requirements 1.1, 1.2, 1.4

This component extracts text positions from PDF pages using PyMuPDF (fitz)
and normalizes coordinates to percentage values (0-100) for responsive display.
"""
import logging
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple
import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


@dataclass
class BoundingBox:
    """
    Normalized bounding box with coordinates as percentage (0-100).
    
    Attributes:
        x0: Left edge (0-100)
        y0: Top edge (0-100)
        x1: Right edge (0-100)
        y1: Bottom edge (0-100)
    """
    x0: float
    y0: float
    x1: float
    y1: float
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "x0": round(self.x0, 2),
            "y0": round(self.y0, 2),
            "x1": round(self.x1, 2),
            "y1": round(self.y1, 2)
        }
    
    def is_valid(self) -> bool:
        """Check if bounding box has valid coordinates."""
        return (
            0 <= self.x0 <= 100 and
            0 <= self.y0 <= 100 and
            0 <= self.x1 <= 100 and
            0 <= self.y1 <= 100 and
            self.x0 < self.x1 and
            self.y0 < self.y1
        )


class BoundingBoxExtractor:
    """
    Extract and normalize bounding boxes from PDF pages.
    
    Uses PyMuPDF to extract text with position information and normalizes
    coordinates to percentage values for responsive frontend display.
    
    **Feature: source-highlight-citation**
    **Validates: Requirements 1.1, 1.2, 1.4**
    """
    
    def __init__(self):
        """Initialize the extractor."""
        self._similarity_threshold = 0.7  # For fuzzy text matching
    
    def extract_text_with_boxes(
        self,
        page: fitz.Page,
        text_content: str,
        fuzzy_match: bool = True
    ) -> List[BoundingBox]:
        """
        Extract bounding boxes for text content on a page.
        
        Args:
            page: PyMuPDF page object
            text_content: The text to find bounding boxes for
            fuzzy_match: Whether to use fuzzy matching for text
            
        Returns:
            List of normalized BoundingBox objects
            
        **Validates: Requirements 1.1, 1.2**
        """
        if not text_content or not text_content.strip():
            return []
        
        try:
            page_width = page.rect.width
            page_height = page.rect.height
            
            if page_width <= 0 or page_height <= 0:
                logger.warning("Invalid page dimensions")
                return []
            
            boxes = []
            
            # Method 1: Search for exact text instances
            text_instances = page.search_for(text_content[:100])  # Limit search length
            
            if text_instances:
                for rect in text_instances:
                    bbox = self.normalize_bbox(
                        (rect.x0, rect.y0, rect.x1, rect.y1),
                        page_width,
                        page_height
                    )
                    if bbox.is_valid():
                        boxes.append(bbox)
            
            # Method 2: If no exact match, try word-by-word matching
            if not boxes and fuzzy_match:
                boxes = self._extract_by_words(page, text_content, page_width, page_height)
            
            # Method 3: If still no match, get text blocks that might contain the content
            if not boxes:
                boxes = self._extract_from_blocks(page, text_content, page_width, page_height)
            
            # Merge overlapping boxes
            if len(boxes) > 1:
                boxes = self.merge_boxes(boxes)
            
            return boxes
            
        except Exception as e:
            logger.warning(f"Failed to extract bounding boxes: {e}")
            return []
    
    def _extract_by_words(
        self,
        page: fitz.Page,
        text_content: str,
        page_width: float,
        page_height: float
    ) -> List[BoundingBox]:
        """Extract boxes by matching individual words."""
        boxes = []
        words = text_content.split()[:20]  # Limit to first 20 words
        
        for word in words:
            if len(word) < 3:  # Skip short words
                continue
            instances = page.search_for(word)
            for rect in instances[:3]:  # Limit instances per word
                bbox = self.normalize_bbox(
                    (rect.x0, rect.y0, rect.x1, rect.y1),
                    page_width,
                    page_height
                )
                if bbox.is_valid():
                    boxes.append(bbox)
                    break  # Take first match per word
        
        return boxes
    
    def _extract_from_blocks(
        self,
        page: fitz.Page,
        text_content: str,
        page_width: float,
        page_height: float
    ) -> List[BoundingBox]:
        """Extract boxes from text blocks containing the content."""
        boxes = []
        
        try:
            # Get text blocks with positions
            blocks = page.get_text("dict")["blocks"]
            
            # Normalize search text
            search_text = text_content.lower()[:200]
            
            for block in blocks:
                if block.get("type") != 0:  # Skip non-text blocks
                    continue
                
                # Get block text
                block_text = ""
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        block_text += span.get("text", "") + " "
                
                # Check if block contains our text
                if search_text[:50] in block_text.lower():
                    bbox_raw = block.get("bbox")
                    if bbox_raw:
                        bbox = self.normalize_bbox(
                            bbox_raw,
                            page_width,
                            page_height
                        )
                        if bbox.is_valid():
                            boxes.append(bbox)
                            break  # Take first matching block
        
        except Exception as e:
            logger.debug(f"Block extraction failed: {e}")
        
        return boxes
    
    def normalize_bbox(
        self,
        bbox: Tuple[float, float, float, float],
        page_width: float,
        page_height: float
    ) -> BoundingBox:
        """
        Normalize raw coordinates to percentage (0-100).
        
        Args:
            bbox: Raw coordinates (x0, y0, x1, y1) in points
            page_width: Page width in points
            page_height: Page height in points
            
        Returns:
            Normalized BoundingBox with percentage values
            
        **Validates: Requirements 1.4**
        """
        x0, y0, x1, y1 = bbox
        
        # Normalize to percentage
        norm_x0 = (x0 / page_width) * 100 if page_width > 0 else 0
        norm_y0 = (y0 / page_height) * 100 if page_height > 0 else 0
        norm_x1 = (x1 / page_width) * 100 if page_width > 0 else 100
        norm_y1 = (y1 / page_height) * 100 if page_height > 0 else 100
        
        # Clamp values to 0-100 range
        norm_x0 = max(0, min(100, norm_x0))
        norm_y0 = max(0, min(100, norm_y0))
        norm_x1 = max(0, min(100, norm_x1))
        norm_y1 = max(0, min(100, norm_y1))
        
        return BoundingBox(
            x0=norm_x0,
            y0=norm_y0,
            x1=norm_x1,
            y1=norm_y1
        )
    
    def merge_boxes(self, boxes: List[BoundingBox]) -> List[BoundingBox]:
        """
        Merge overlapping or adjacent bounding boxes.
        
        Args:
            boxes: List of bounding boxes
            
        Returns:
            Merged list of bounding boxes
        """
        if len(boxes) <= 1:
            return boxes
        
        # Sort by y0 (top to bottom), then x0 (left to right)
        sorted_boxes = sorted(boxes, key=lambda b: (b.y0, b.x0))
        
        merged = []
        current = sorted_boxes[0]
        
        for box in sorted_boxes[1:]:
            # Check if boxes overlap or are adjacent (within 5% margin)
            if self._boxes_overlap(current, box, margin=5):
                # Merge boxes
                current = BoundingBox(
                    x0=min(current.x0, box.x0),
                    y0=min(current.y0, box.y0),
                    x1=max(current.x1, box.x1),
                    y1=max(current.y1, box.y1)
                )
            else:
                merged.append(current)
                current = box
        
        merged.append(current)
        return merged
    
    def _boxes_overlap(
        self,
        box1: BoundingBox,
        box2: BoundingBox,
        margin: float = 0
    ) -> bool:
        """Check if two boxes overlap or are within margin."""
        return not (
            box1.x1 + margin < box2.x0 or
            box2.x1 + margin < box1.x0 or
            box1.y1 + margin < box2.y0 or
            box2.y1 + margin < box1.y0
        )


# Singleton instance
_extractor: Optional[BoundingBoxExtractor] = None


def get_bounding_box_extractor() -> BoundingBoxExtractor:
    """Get singleton BoundingBoxExtractor instance."""
    global _extractor
    if _extractor is None:
        _extractor = BoundingBoxExtractor()
    return _extractor
