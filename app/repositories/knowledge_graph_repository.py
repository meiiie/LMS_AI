"""
Knowledge Graph Repository for Neo4j operations.

This module provides the repository pattern implementation for
Knowledge Graph operations using Neo4j.

**Feature: maritime-ai-tutor**
**Validates: Requirements 4.1, 4.2, 4.4**
"""

import logging
from typing import Dict, List, Optional

from app.models.knowledge_graph import (
    Citation,
    GraphContext,
    KnowledgeNode,
    NodeType,
    Relation,
    RelationType,
)

logger = logging.getLogger(__name__)


class InMemoryKnowledgeGraphRepository:
    """
    In-memory implementation of Knowledge Graph repository.
    
    Used for development and testing. Production should use
    Neo4j-backed implementation.
    
    **Validates: Requirements 4.1, 4.2, 4.4**
    """
    
    def __init__(self):
        """Initialize with empty storage."""
        self._nodes: Dict[str, KnowledgeNode] = {}
        self._available = True
    
    async def hybrid_search(
        self, 
        query: str, 
        limit: int = 10
    ) -> List[KnowledgeNode]:
        """
        Perform hybrid search combining keyword and graph traversal.
        
        In production, this would combine:
        - Vector similarity search
        - Graph traversal for related nodes
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of relevant KnowledgeNodes with relations
            
        **Validates: Requirements 4.2**
        """
        if not self._available:
            return []
        
        query_lower = query.lower()
        query_words = set(query_lower.split())
        
        results = []
        for node in self._nodes.values():
            # Simple keyword matching
            title_lower = node.title.lower()
            content_lower = node.content.lower()
            
            score = 0
            for word in query_words:
                if word in title_lower:
                    score += 2  # Title matches weighted higher
                if word in content_lower:
                    score += 1
            
            if score > 0:
                results.append((node, score))
        
        # Sort by score and return top results
        results.sort(key=lambda x: x[1], reverse=True)
        return [node for node, _ in results[:limit]]

    
    async def traverse_relations(
        self, 
        node_id: str, 
        relation_types: List[RelationType],
        depth: int = 1
    ) -> List[KnowledgeNode]:
        """
        Traverse graph from a node following specific relation types.
        
        Args:
            node_id: Starting node ID
            relation_types: Types of relations to follow
            depth: How many hops to traverse
            
        Returns:
            List of connected KnowledgeNodes
            
        **Validates: Requirements 4.4**
        """
        if not self._available or node_id not in self._nodes:
            return []
        
        visited = set()
        result = []
        to_visit = [(node_id, 0)]
        
        while to_visit:
            current_id, current_depth = to_visit.pop(0)
            
            if current_id in visited or current_depth > depth:
                continue
            
            visited.add(current_id)
            node = self._nodes.get(current_id)
            
            if node and current_id != node_id:
                result.append(node)
            
            if node and current_depth < depth:
                for relation in node.relations:
                    if relation.type in relation_types:
                        if relation.target_id not in visited:
                            to_visit.append((relation.target_id, current_depth + 1))
        
        return result
    
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
        nodes = []
        for node_id in node_ids:
            node = self._nodes.get(node_id)
            if node:
                nodes.append(node)
        
        return GraphContext(
            nodes=nodes,
            total_results=len(nodes)
        )
    
    async def get_node(self, node_id: str) -> Optional[KnowledgeNode]:
        """Get a single node by ID."""
        return self._nodes.get(node_id)
    
    async def add_node(self, node: KnowledgeNode) -> KnowledgeNode:
        """Add a new node to the graph."""
        self._nodes[node.id] = node
        logger.debug(f"Added node: {node.id}")
        return node
    
    async def delete_node(self, node_id: str) -> bool:
        """Delete a node from the graph."""
        if node_id in self._nodes:
            del self._nodes[node_id]
            return True
        return False
    
    def is_available(self) -> bool:
        """Check if the knowledge graph is available."""
        return self._available
    
    def set_available(self, available: bool) -> None:
        """Set availability status (for testing)."""
        self._available = available
    
    def count(self) -> int:
        """Get total number of nodes."""
        return len(self._nodes)
    
    def clear(self) -> None:
        """Clear all nodes (for testing)."""
        self._nodes.clear()
    
    async def get_citations(
        self, 
        nodes: List[KnowledgeNode]
    ) -> List[Citation]:
        """
        Generate citations from knowledge nodes.
        
        Args:
            nodes: List of nodes to cite
            
        Returns:
            List of Citation objects
            
        **Validates: Requirements 4.1**
        """
        citations = []
        for i, node in enumerate(nodes):
            citation = Citation(
                node_id=node.id,
                title=node.title,
                source=node.source or "Maritime Knowledge Base",
                relevance_score=1.0 - (i * 0.1)  # Decreasing relevance
            )
            citations.append(citation)
        return citations
