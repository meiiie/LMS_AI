"""
KG Builder Agent - Knowledge Graph Construction Specialist

Extracts entities and relations from documents/text using LLM.
Part of Multi-Agent System for document understanding.

**Feature: document-kg, multi-agent**
**CHỈ THỊ KỸ THUẬT SỐ 29: Automated Knowledge Graph Construction**
**SOTA 2025: LangChain with_structured_output + Pydantic**

**Integrated with agents/ framework for config and tracing.**
"""
import logging
from typing import Optional, List, Dict, Any

from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import settings
from app.engine.multi_agent.state import AgentState
from app.engine.agents import KG_BUILDER_AGENT_CONFIG, AgentConfig

logger = logging.getLogger(__name__)


# ============================================================================
# Pydantic Models for Structured Output
# ============================================================================

class EntityItem(BaseModel):
    """Entity extracted from text"""
    id: str = Field(..., description="Unique snake_case ID")
    entity_type: str = Field(..., description="Type: ARTICLE, REGULATION, VESSEL_TYPE, MANEUVER, EQUIPMENT, CONCEPT")
    name: str = Field(..., description="English name")
    name_vi: Optional[str] = Field(None, description="Vietnamese name")
    description: str = Field("", description="Brief description")


class RelationItem(BaseModel):
    """Relation between entities"""
    source_id: str = Field(..., description="Source entity ID")
    target_id: str = Field(..., description="Target entity ID")
    relation_type: str = Field(..., description="Type: REFERENCES, APPLIES_TO, REQUIRES, DEFINES, PART_OF")
    description: str = Field("", description="Relation description")


class ExtractionOutput(BaseModel):
    """Structured output for KG extraction"""
    entities: List[EntityItem] = Field(default_factory=list)
    relations: List[RelationItem] = Field(default_factory=list)


# ============================================================================
# System Prompt
# ============================================================================

SYSTEM_PROMPT = """Bạn là KG Builder Agent - chuyên gia xây dựng Knowledge Graph từ văn bản hàng hải.

Nhiệm vụ: Trích xuất entities và relations từ văn bản.

Entity Types:
- ARTICLE: Điều/khoản (Điều 15, Rule 7)
- REGULATION: Quy định (COLREGs, SOLAS)
- VESSEL_TYPE: Loại tàu (tàu máy, tàu buồm)
- MANEUVER: Thao tác (nhường đường, cắt hướng)
- EQUIPMENT: Thiết bị (radar, AIS)
- CONCEPT: Khái niệm (tốc độ an toàn)

Relation Types:
- REFERENCES: Tham chiếu
- APPLIES_TO: Áp dụng cho
- REQUIRES: Yêu cầu
- DEFINES: Định nghĩa
- PART_OF: Thuộc về

Quy tắc:
1. ID phải là snake_case
2. Điền cả name (tiếng Anh) và name_vi (tiếng Việt)
3. Chỉ trích xuất entities thực sự có trong văn bản"""


class KGBuilderAgentNode:
    """
    KG Builder Agent - Knowledge Graph construction specialist.
    
    Responsibilities:
    - Extract entities from text/documents
    - Extract relations between entities
    - Build structured knowledge for Neo4j
    
    **Feature: document-kg, multi-agent**
    
    Implements agents/ framework integration.
    """
    
    def __init__(self):
        """Initialize KG Builder Agent."""
        self._llm = None
        self._structured_llm = None
        self._config = KG_BUILDER_AGENT_CONFIG
        self._init_llm()
        logger.info(f"KGBuilderAgentNode initialized with config: {self._config.id}")
    
    def _init_llm(self):
        """Initialize LLM with structured output."""
        try:
            self._llm = ChatGoogleGenerativeAI(
                model=settings.google_model,
                google_api_key=settings.google_api_key,
                temperature=0.1
            )
            self._structured_llm = self._llm.with_structured_output(ExtractionOutput)
            logger.info("KG Builder LLM initialized with structured output")
        except Exception as e:
            logger.error(f"Failed to initialize KG Builder LLM: {e}")
            self._llm = None
            self._structured_llm = None
    
    async def extract(self, text: str, source: Optional[str] = None) -> ExtractionOutput:
        """
        Extract entities and relations from text.
        
        Args:
            text: Text content to extract from
            source: Optional source identifier
            
        Returns:
            ExtractionOutput with entities and relations
        """
        if not self._structured_llm:
            logger.warning("KG Builder LLM not available")
            return ExtractionOutput()
        
        try:
            user_content = f"""Nguồn: {source or 'unknown'}

Nội dung:
{text[:2500]}

Trích xuất entities và relations."""
            
            messages = [
                SystemMessage(content=SYSTEM_PROMPT),
                HumanMessage(content=user_content)
            ]
            
            result: ExtractionOutput = await self._structured_llm.ainvoke(messages)
            
            logger.info(f"Extracted {len(result.entities)} entities, {len(result.relations)} relations")
            return result
            
        except Exception as e:
            logger.error(f"KG extraction failed: {e}")
            return ExtractionOutput()
    
    async def process(self, state: AgentState) -> AgentState:
        """
        Process state as KG Builder node.
        
        Used in multi-agent graph when extraction is needed.
        
        Args:
            state: Current agent state
            
        Returns:
            Updated state with extracted entities
        """
        query = state.get("query", "")
        context = state.get("context", {})
        
        # Extract from query or provided text
        text_to_extract = context.get("text_for_extraction", query)
        source = context.get("source", "user_query")
        
        # Perform extraction
        result = await self.extract(text_to_extract, source)
        
        # Update state
        state["agent_outputs"] = state.get("agent_outputs", {})
        state["agent_outputs"]["kg_builder"] = {
            "entities": [e.model_dump() for e in result.entities],
            "relations": [r.model_dump() for r in result.relations],
            "entity_count": len(result.entities),
            "relation_count": len(result.relations)
        }
        
        # Store in state for other agents
        state["extracted_entities"] = result.entities
        state["extracted_relations"] = result.relations
        
        logger.info(f"[KG_BUILDER] Extracted {len(result.entities)} entities")
        
        return state
    
    def is_available(self) -> bool:
        """Check if LLM is available."""
        return self._structured_llm is not None


# Singleton
_kg_builder: Optional[KGBuilderAgentNode] = None


def get_kg_builder_agent() -> KGBuilderAgentNode:
    """Get or create KGBuilderAgent singleton."""
    global _kg_builder
    if _kg_builder is None:
        _kg_builder = KGBuilderAgentNode()
    return _kg_builder
