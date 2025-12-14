"""
Output Processor - Response Formatting and Validation

Extracted from chat_service.py as part of Clean Architecture refactoring.
Handles all output processing: formatting, validation, source merging.

**Pattern:** Processor Service
**Spec:** CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure
"""

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from app.models.schemas import InternalChatResponse, Source, UserRole

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ProcessingResult:
    """Result of processing a chat request."""
    message: str
    agent_type: Any  # AgentType enum
    sources: Optional[List[Source]] = None
    blocked: bool = False
    metadata: dict = None


# =============================================================================
# OUTPUT PROCESSOR SERVICE
# =============================================================================

class OutputProcessor:
    """
    Handles all output processing for chat responses.
    
    Responsibilities:
    - Output validation (Guardrails)
    - Source merging (same-page sources)
    - Response formatting
    - Metadata building
    
    **Pattern:** Processor Service
    """
    
    def __init__(
        self,
        guardrails=None,
        response_builder=None
    ):
        """
        Initialize with dependencies.
        
        Args:
            guardrails: Guardrails for output validation
            response_builder: ChatResponseBuilder for source merging
        """
        self._guardrails = guardrails
        self._response_builder = response_builder
        
        logger.info("OutputProcessor initialized")
    
    async def validate_and_format(
        self,
        result: ProcessingResult,
        session_id: UUID,
        user_name: Optional[str] = None,
        user_role: UserRole = UserRole.STUDENT
    ) -> InternalChatResponse:
        """
        Validate and format the processing result into a response.
        
        Args:
            result: ProcessingResult from agent processing
            session_id: Session UUID
            user_name: User's name for personalization
            user_role: User's role
            
        Returns:
            InternalChatResponse ready for API serialization
        """
        message = result.message
        
        # Step 1: Validate output
        if self._guardrails:
            from app.engine.guardrails import ValidationStatus
            output_result = await self._guardrails.validate_output(message)
            if output_result.status == ValidationStatus.FLAGGED:
                message += "\n\n_Note: Please verify safety-critical information with official sources._"
        
        # Step 2: Build metadata
        response_metadata = {
            "session_id": str(session_id),
            "user_name": user_name,
            "user_role": user_role.value,
            **(result.metadata or {})
        }
        
        # Step 3: Create response
        return InternalChatResponse(
            response_id=uuid4(),
            message=message,
            agent_type=result.agent_type,
            sources=result.sources,
            metadata=response_metadata
        )
    
    def merge_same_page_sources(self, sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Merge sources from the same page into single entries with combined bounding_boxes.
        
        Feature: source-highlight-citation
        **Validates: Requirements 2.4**
        
        Args:
            sources: List of source dictionaries
            
        Returns:
            Merged list of sources
        """
        if self._response_builder:
            return self._response_builder.merge_same_page_sources(sources)
        
        # Fallback implementation if no response_builder
        if not sources:
            return []
        
        # Group by (document_id, page_number)
        page_groups: Dict[str, Dict[str, Any]] = {}
        
        for source in sources:
            doc_id = source.get("document_id")
            page_num = source.get("page_number")
            
            if doc_id and page_num:
                key = f"{doc_id}_{page_num}"
                if key not in page_groups:
                    page_groups[key] = {
                        **source,
                        "bounding_boxes": []
                    }
                
                # Merge bounding_boxes
                if source.get("bounding_boxes"):
                    page_groups[key]["bounding_boxes"].extend(source["bounding_boxes"])
            else:
                # No doc_id/page_num, add as-is
                key = source.get("node_id", str(len(page_groups)))
                if key not in page_groups:
                    page_groups[key] = source
        
        return list(page_groups.values())
    
    def format_sources(
        self,
        raw_sources: List[Dict[str, Any]]
    ) -> List[Source]:
        """
        Format raw source dictionaries into Source objects.
        
        Args:
            raw_sources: List of raw source dictionaries
            
        Returns:
            List of Source objects
        """
        if not raw_sources:
            return []
        
        # First merge same-page sources
        merged_sources = self.merge_same_page_sources(raw_sources)
        
        sources = []
        for s in merged_sources:
            sources.append(Source(
                node_id=s.get("node_id", ""),
                title=s.get("title", ""),
                source_type="knowledge_graph",
                content_snippet=s.get("content", "")[:200],  # Truncate for API
                image_url=s.get("image_url"),
                page_number=s.get("page_number"),
                document_id=s.get("document_id"),
                bounding_boxes=s.get("bounding_boxes")
            ))
        
        return sources
    
    def create_blocked_response(
        self,
        issues: List[str],
        refusal_message: Optional[str] = None
    ) -> InternalChatResponse:
        """
        Create response for blocked content.
        
        Args:
            issues: List of issues that caused blocking
            refusal_message: Custom refusal message
            
        Returns:
            InternalChatResponse with blocked metadata
        """
        from enum import Enum
        
        class AgentType(str, Enum):
            CHAT = "chat"
        
        message = refusal_message or "Xin lỗi, tôi không thể xử lý yêu cầu này."
        if self._guardrails:
            message = self._guardrails.get_refusal_message()
        
        return InternalChatResponse(
            response_id=uuid4(),
            message=message,
            agent_type=AgentType.CHAT,
            metadata={"blocked": True, "issues": issues}
        )
    
    def create_clarification_response(self, content: str) -> InternalChatResponse:
        """Create response requesting clarification."""
        from enum import Enum
        
        class AgentType(str, Enum):
            CHAT = "chat"
        
        return InternalChatResponse(
            response_id=uuid4(),
            message=content,
            agent_type=AgentType.CHAT,
            metadata={"requires_clarification": True}
        )


# =============================================================================
# SINGLETON
# =============================================================================

_output_processor: Optional[OutputProcessor] = None


def get_output_processor() -> OutputProcessor:
    """Get or create OutputProcessor singleton."""
    global _output_processor
    if _output_processor is None:
        _output_processor = OutputProcessor()
    return _output_processor


def init_output_processor(
    guardrails=None,
    response_builder=None
) -> OutputProcessor:
    """Initialize OutputProcessor with dependencies."""
    global _output_processor
    _output_processor = OutputProcessor(
        guardrails=guardrails,
        response_builder=response_builder
    )
    return _output_processor
