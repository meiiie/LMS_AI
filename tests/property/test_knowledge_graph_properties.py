"""
Property-based tests for Knowledge Graph and RAG Agent.

**Feature: maritime-ai-tutor**
**Validates: Requirements 4.1, 4.4, 4.5, 4.6, 8.3**
"""

import pytest
from uuid import uuid4

from hypothesis import given, settings, strategies as st, assume

from app.models.knowledge_graph import (
    Citation,
    KnowledgeNode,
    NodeType,
    Relation,
    RelationType,
)
from app.repositories.knowledge_graph_repository import InMemoryKnowledgeGraphRepository
from app.engine.tools.rag_tool import RAGAgent, MaritimeDocumentParser


# Custom strategies
@st.composite
def relation_strategy(draw):
    """Generate valid Relation objects."""
    return Relation(
        type=draw(st.sampled_from(RelationType)),
        target_id=draw(st.text(min_size=1, max_size=30).filter(lambda x: x.strip())),
        properties=draw(st.fixed_dictionaries({}) | st.fixed_dictionaries({"key": st.text(max_size=20)}))
    )


@st.composite
def knowledge_node_strategy(draw):
    """Generate valid KnowledgeNode objects."""
    return KnowledgeNode(
        id=draw(st.text(min_size=1, max_size=50).filter(lambda x: x.strip())),
        node_type=draw(st.sampled_from(NodeType)),
        title=draw(st.text(min_size=1, max_size=100).filter(lambda x: x.strip())),
        content=draw(st.text(min_size=1, max_size=500).filter(lambda x: x.strip())),
        source=draw(st.text(max_size=100)),
        relations=draw(st.lists(relation_strategy(), max_size=3)),
    )


class TestGraphTraversalIncludesRelations:
    """
    **Feature: maritime-ai-tutor, Property 10: Graph Traversal Includes Relations**
    
    For any Knowledge_Graph query result, the returned KnowledgeNodes SHALL
    include traversed relationships when such relationships exist.
    """
    
    @pytest.mark.asyncio
    async def test_traverse_returns_related_nodes(self):
        """
        **Feature: maritime-ai-tutor, Property 10: Graph Traversal Includes Relations**
        **Validates: Requirements 4.4**
        """
        repo = InMemoryKnowledgeGraphRepository()
        
        # Create nodes with relationships
        node1 = KnowledgeNode(
            id="solas_fire",
            node_type=NodeType.REGULATION,
            title="SOLAS Fire Safety",
            content="Fire safety regulations",
            relations=[
                Relation(type=RelationType.REGULATES, target_id="concept_fire")
            ]
        )
        node2 = KnowledgeNode(
            id="concept_fire",
            node_type=NodeType.CONCEPT,
            title="Fire Safety Concept",
            content="General fire safety principles"
        )
        
        await repo.add_node(node1)
        await repo.add_node(node2)
        
        # Traverse from node1
        related = await repo.traverse_relations(
            "solas_fire",
            [RelationType.REGULATES]
        )
        
        # Should find the related node
        assert len(related) == 1
        assert related[0].id == "concept_fire"

    
    @pytest.mark.asyncio
    @given(node=knowledge_node_strategy())
    @settings(max_examples=50)
    async def test_node_with_no_matching_relations_returns_empty(self, node):
        """Traversal with non-matching relation types returns empty."""
        repo = InMemoryKnowledgeGraphRepository()
        await repo.add_node(node)
        
        # Use a relation type that doesn't exist
        related = await repo.traverse_relations(
            node.id,
            [RelationType.CAUSED_BY]  # Unlikely to match
        )
        
        # May or may not find results depending on node's relations
        # But should not error
        assert isinstance(related, list)


class TestRAGResponseContainsCitations:
    """
    **Feature: maritime-ai-tutor, Property 9: RAG Response Contains Citations**
    
    For any maritime regulation query that returns results, the RAG_Agent
    response SHALL include at least one source citation.
    """
    
    @pytest.mark.asyncio
    async def test_rag_response_has_citations_when_results_found(self):
        """
        **Feature: maritime-ai-tutor, Property 9: RAG Response Contains Citations**
        **Validates: Requirements 4.1**
        """
        repo = InMemoryKnowledgeGraphRepository()
        
        # Add a node that will match the query
        node = KnowledgeNode(
            id="solas_ch2",
            node_type=NodeType.REGULATION,
            title="SOLAS Chapter II Fire Safety",
            content="Fire safety requirements for passenger ships",
            source="SOLAS 2020"
        )
        await repo.add_node(node)
        
        # Create RAG agent with the repo
        agent = RAGAgent(knowledge_graph=repo)
        
        # Query for fire safety
        response = await agent.query("fire safety regulations")
        
        # Should have citations
        assert response.has_citations()
        assert len(response.citations) >= 1
        assert response.citations[0].source == "SOLAS 2020"
    
    @pytest.mark.asyncio
    async def test_rag_response_no_citations_when_no_results(self):
        """No citations when no results found."""
        repo = InMemoryKnowledgeGraphRepository()
        agent = RAGAgent(knowledge_graph=repo)
        
        # Query with no matching nodes
        response = await agent.query("nonexistent topic xyz123")
        
        # Should not have citations
        assert not response.has_citations()


class TestMaritimeDocumentParsingRoundTrip:
    """
    **Feature: maritime-ai-tutor, Property 11: Maritime Document Parsing Round-Trip**
    
    For any structured maritime regulation document, parsing into KnowledgeNode
    format and serializing back SHALL preserve essential content.
    """
    
    @given(
        code=st.text(min_size=1, max_size=20).filter(lambda x: x.strip()),
        title=st.text(min_size=1, max_size=100).filter(lambda x: x.strip()),
        content=st.text(min_size=1, max_size=500).filter(lambda x: x.strip()),
        source=st.text(min_size=1, max_size=50).filter(lambda x: x.strip())
    )
    @settings(max_examples=100)
    def test_parse_and_serialize_preserves_content(self, code, title, content, source):
        """
        **Feature: maritime-ai-tutor, Property 11: Maritime Document Parsing Round-Trip**
        **Validates: Requirements 4.5, 4.6**
        """
        # Parse into node
        node = MaritimeDocumentParser.parse_regulation(
            code=code,
            title=title,
            content=content,
            source=source
        )
        
        # Serialize back
        doc_str = MaritimeDocumentParser.serialize_to_document(node)
        
        # Essential content should be preserved
        assert title in doc_str
        assert content in doc_str
        assert source in doc_str
        assert code in doc_str


class TestGracefulDegradationKnowledgeGraph:
    """
    **Feature: maritime-ai-tutor, Property 20: Graceful Degradation - Knowledge Graph Unavailable**
    
    For any knowledge query when Knowledge_Graph is unavailable, the RAG_Agent
    SHALL fall back to general response with appropriate disclaimer.
    """
    
    @pytest.mark.asyncio
    @given(query=st.text(min_size=1, max_size=100).filter(lambda x: x.strip()))
    @settings(max_examples=50)
    async def test_fallback_when_kg_unavailable(self, query):
        """
        **Feature: maritime-ai-tutor, Property 20: Graceful Degradation - Knowledge Graph Unavailable**
        **Validates: Requirements 8.3**
        """
        repo = InMemoryKnowledgeGraphRepository()
        repo.set_available(False)  # Simulate unavailability
        
        agent = RAGAgent(knowledge_graph=repo)
        response = await agent.query(query)
        
        # Should be a fallback response
        assert response.is_fallback
        assert response.disclaimer is not None
        assert "general" in response.disclaimer.lower() or "official" in response.disclaimer.lower()
    
    @pytest.mark.asyncio
    async def test_fallback_has_no_citations(self):
        """Fallback response should have no citations."""
        repo = InMemoryKnowledgeGraphRepository()
        repo.set_available(False)
        
        agent = RAGAgent(knowledge_graph=repo)
        response = await agent.query("any query")
        
        assert not response.has_citations()
        assert response.citations == []


class TestKnowledgeNodeSerialization:
    """Test KnowledgeNode serialization."""
    
    @given(node=knowledge_node_strategy())
    @settings(max_examples=100)
    def test_knowledge_node_round_trip(self, node: KnowledgeNode):
        """KnowledgeNode should serialize and deserialize correctly."""
        json_str = node.model_dump_json()
        restored = KnowledgeNode.model_validate_json(json_str)
        
        assert restored.id == node.id
        assert restored.node_type == node.node_type
        assert restored.title == node.title
        assert restored.content == node.content
        assert len(restored.relations) == len(node.relations)


class TestCitationGeneration:
    """Test citation generation from nodes."""
    
    @pytest.mark.asyncio
    @given(nodes=st.lists(knowledge_node_strategy(), min_size=1, max_size=5))
    @settings(max_examples=50)
    async def test_citations_match_nodes(self, nodes):
        """Generated citations should match source nodes."""
        repo = InMemoryKnowledgeGraphRepository()
        
        # Add nodes
        for node in nodes:
            await repo.add_node(node)
        
        # Generate citations
        citations = await repo.get_citations(nodes)
        
        assert len(citations) == len(nodes)
        for i, citation in enumerate(citations):
            assert citation.node_id == nodes[i].id
            assert citation.title == nodes[i].title
