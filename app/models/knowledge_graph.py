"""
Knowledge Graph domain models for GraphRAG.

This module defines the data structures for the maritime knowledge graph,
including nodes, relationships, and the IKnowledgeGraph interface.

**Feature: maritime-ai-tutor**
**Validates: Requirements 4.1, 4.4, 4.5, 4.6**
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    """Return current UTC time as timezone-aware datetime."""
    return datetime.now(timezone.utc)


class NodeType(str, Enum):
    """Types of nodes in the maritime knowledge graph."""
    CONCEPT = "CONCEPT"          # General maritime concepts
    REGULATION = "REGULATION"    # SOLAS, COLREGs, MARPOL regulations
    SHIP_TYPE = "SHIP_TYPE"      # Types of vessels
    ACCIDENT = "ACCIDENT"        # Maritime accidents/incidents
    PROCEDURE = "PROCEDURE"      # Standard operating procedures
    EQUIPMENT = "EQUIPMENT"      # Maritime equipment


class RelationType(str, Enum):
    """Types of relationships between knowledge nodes."""
    REGULATES = "REGULATES"      # Regulation -> Concept
    APPLIES_TO = "APPLIES_TO"    # Regulation -> ShipType
    CAUSED_BY = "CAUSED_BY"      # Accident -> Concept
    RELATED_TO = "RELATED_TO"    # Concept -> Concept
    REFERENCES = "REFERENCES"    # Regulation -> Regulation
    REQUIRES = "REQUIRES"        # Procedure -> Equipment
    PART_OF = "PART_OF"          # Concept -> Concept (hierarchy)


class Relation(BaseModel):
    """
    Represents a relationship between knowledge nodes.
    
    **Validates: Requirements 4.4**
    """
    type: RelationType = Field(..., description="Type of relationship")
    target_id: str = Field(..., min_length=1, description="Target node ID")
    properties: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional relationship properties"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "REGULATES",
                "target_id": "concept_fire_safety",
                "properties": {"chapter": "II-2"}
            }
        }
    }


class KnowledgeNode(BaseModel):
    """
    Represents a node in the maritime knowledge graph.
    
    Nodes contain structured information about maritime concepts,
    regulations, ship types, and accidents.
    
    **Validates: Requirements 4.1, 4.4**
    """
    id: str = Field(..., min_length=1, description="Unique node identifier")
    node_type: NodeType = Field(..., description="Type of knowledge node")
    title: str = Field(..., min_length=1, description="Node title")
    content: str = Field(..., min_length=1, description="Full content/description")
    source: str = Field(default="", description="Source document reference")
    relations: List[Relation] = Field(
        default_factory=list,
        description="Outgoing relationships"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "id": "solas_ch2_reg10",
                "node_type": "REGULATION",
                "title": "SOLAS Chapter II-2 Regulation 10",
                "content": "Fire safety measures for passenger ships...",
                "source": "SOLAS 2020 Consolidated Edition",
                "relations": [
                    {"type": "REGULATES", "target_id": "concept_fire_safety"}
                ]
            }
        }
    }
    
    def has_relation_type(self, relation_type: RelationType) -> bool:
        """Check if node has a specific relation type."""
        return any(r.type == relation_type for r in self.relations)
    
    def get_relations_by_type(self, relation_type: RelationType) -> List[Relation]:
        """Get all relations of a specific type."""
        return [r for r in self.relations if r.type == relation_type]


class GraphContext(BaseModel):
    """
    Context retrieved from knowledge graph for a query.
    
    Contains nodes and their relationships for RAG context.
    """
    nodes: List[KnowledgeNode] = Field(default_factory=list)
    query: str = Field(default="")
    total_results: int = Field(default=0)


class Citation(BaseModel):
    """
    Source citation for RAG responses.
    
    **Validates: Requirements 4.1**
    """
    node_id: str = Field(..., description="Referenced node ID")
    title: str = Field(..., description="Citation title")
    source: str = Field(..., description="Source document")
    relevance_score: float = Field(
        default=0.0, 
        ge=0.0, 
        le=1.0,
        description="Relevance score"
    )
    image_url: Optional[str] = Field(default=None, description="URL ảnh trang tài liệu (CHỈ THỊ 26)")
    page_number: Optional[int] = Field(default=None, description="Page number in PDF (Feature: source-highlight-citation)")
    document_id: Optional[str] = Field(default=None, description="Document ID (Feature: source-highlight-citation)")
    bounding_boxes: Optional[list] = Field(default=None, description="Normalized coordinates for highlighting (Feature: source-highlight-citation)")


class IKnowledgeGraph(Protocol):
    """
    Interface for Knowledge Graph operations.
    
    Defines the contract for graph-based knowledge retrieval.
    """
    
    async def hybrid_search(
        self, 
        query: str, 
        limit: int = 10
    ) -> List[KnowledgeNode]:
        """
        Perform hybrid search combining vector and graph traversal.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of relevant KnowledgeNodes
        """
        ...
    
    async def traverse_relations(
        self, 
        node_id: str, 
        relation_types: List[RelationType]
    ) -> List[KnowledgeNode]:
        """
        Traverse graph from a node following specific relation types.
        
        Args:
            node_id: Starting node ID
            relation_types: Types of relations to follow
            
        Returns:
            List of connected KnowledgeNodes
        """
        ...
    
    async def get_context(
        self, 
        node_ids: List[str]
    ) -> GraphContext:
        """
        Get full context for a list of nodes.
        
        Args:
            node_ids: List of node IDs
            
        Returns:
            GraphContext with nodes and relationships
        """
        ...
    
    async def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """Get a single node by ID."""
        ...
    
    async def add_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """Add a new node to the graph."""
        ...
    
    def is_available(self) -> bool:
        """Check if the knowledge graph is available."""
        ...
