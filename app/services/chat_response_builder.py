"""
Chat Response Builder - Response Formatting Operations

Extracts response building logic from ChatService for cleaner code organization.

**Validates: Requirements 1.1, 1.6, 2.4**
**Feature: source-highlight-citation**
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.models.schemas import Source, SourceInfo

logger = logging.getLogger(__name__)


@dataclass
class FormattedResponse:
    """Formatted chat response ready for API."""
    message: str
    sources: List[SourceInfo] = field(default_factory=list)
    suggested_questions: List[str] = field(default_factory=list)
    tools_used: List[Dict] = field(default_factory=list)
    topics: List[str] = field(default_factory=list)


class ChatResponseBuilder:
    """
    Builds and formats chat responses.
    
    Handles:
    - Source merging (same page sources)
    - Source formatting for API
    - Suggested questions generation
    - Evidence images handling
    
    **Validates: Requirements 1.1, 1.6, 2.4**
    """
    
    def merge_same_page_sources(self, sources: List[dict]) -> List[dict]:
        """
        Merge sources from the same page into single entries with combined bounding_boxes.
        
        Feature: source-highlight-citation
        **Validates: Requirements 2.4**
        
        Args:
            sources: List of source dicts with page_number, document_id, bounding_boxes
            
        Returns:
            Merged list where same-page sources are combined
        """
        if not sources:
            return []
        
        # Group by (document_id, page_number)
        page_groups: Dict[tuple, dict] = {}
        
        for source in sources:
            doc_id = source.get("document_id", "")
            page_num = source.get("page_number", 0)
            key = (doc_id, page_num)
            
            if key not in page_groups:
                # First source for this page - copy it
                page_groups[key] = {
                    "title": source.get("title", ""),
                    "content": source.get("content", ""),
                    "page_number": page_num,
                    "document_id": doc_id,
                    "image_url": source.get("image_url"),
                    "node_id": source.get("node_id", ""),
                    "bounding_boxes": list(source.get("bounding_boxes", []) or [])
                }
            else:
                # Merge with existing source
                existing = page_groups[key]
                
                # Combine bounding boxes
                new_boxes = source.get("bounding_boxes", []) or []
                if new_boxes:
                    existing["bounding_boxes"].extend(new_boxes)
                
                # Combine content (with separator if both have content)
                new_content = source.get("content", "")
                if new_content and existing["content"]:
                    existing["content"] = f"{existing['content']}\n\n{new_content}"
                elif new_content:
                    existing["content"] = new_content
                
                # Use image_url from first valid source
                if not existing["image_url"] and source.get("image_url"):
                    existing["image_url"] = source.get("image_url")
        
        # Convert back to list, sorted by page number
        merged = list(page_groups.values())
        merged.sort(key=lambda x: (x.get("document_id", ""), x.get("page_number", 0)))
        
        logger.debug(f"Merged {len(sources)} sources into {len(merged)} unique pages")
        
        return merged
    
    def format_sources_for_api(self, sources: List[dict]) -> List[SourceInfo]:
        """
        Format sources for API response.
        
        Args:
            sources: List of raw source dicts
            
        Returns:
            List of SourceInfo objects
        """
        formatted = []
        for source in sources:
            source_info = SourceInfo(
                title=source.get("title", ""),
                content=source.get("content", ""),
                page_number=source.get("page_number", 0),
                document_id=source.get("document_id", ""),
                image_url=source.get("image_url"),
                bounding_boxes=source.get("bounding_boxes", [])
            )
            formatted.append(source_info)
        return formatted
    
    def build_response(
        self,
        message: str,
        sources: Optional[List[dict]] = None,
        merge_sources: bool = True,
        tools_used: Optional[List[Dict]] = None,
        topics: Optional[List[str]] = None,
        suggested_questions: Optional[List[str]] = None
    ) -> FormattedResponse:
        """
        Build a complete formatted response.
        
        Args:
            message: Response message text
            sources: Raw source list
            merge_sources: Whether to merge same-page sources
            tools_used: List of tools used
            topics: Detected topics
            suggested_questions: AI-generated follow-up questions
            
        Returns:
            FormattedResponse object
        """
        # Process sources
        processed_sources = []
        if sources:
            if merge_sources:
                merged = self.merge_same_page_sources(sources)
                processed_sources = self.format_sources_for_api(merged)
            else:
                processed_sources = self.format_sources_for_api(sources)
        
        return FormattedResponse(
            message=message,
            sources=processed_sources,
            suggested_questions=suggested_questions or [],
            tools_used=tools_used or [],
            topics=topics or []
        )


# Singleton instance
_response_builder: Optional[ChatResponseBuilder] = None


def get_chat_response_builder() -> ChatResponseBuilder:
    """Get or create ChatResponseBuilder singleton."""
    global _response_builder
    if _response_builder is None:
        _response_builder = ChatResponseBuilder()
    return _response_builder
