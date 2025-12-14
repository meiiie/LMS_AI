"""
Test script for KG Builder Agent

Run: python -m scripts.test_kg_builder_agent
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.multi_agent.agents.kg_builder_agent import KGBuilderAgentNode, get_kg_builder_agent
from app.engine.multi_agent.state import AgentState


async def test_kg_builder_agent():
    """Test KG Builder Agent extraction"""
    print("=" * 60)
    print("Testing KG Builder Agent")
    print("=" * 60)
    
    # Get agent
    agent = get_kg_builder_agent()
    print(f"\n✅ KG Builder Agent created: {agent.is_available()}")
    
    # Test 1: Direct extraction
    print("\n📝 Test 1: Direct extraction")
    sample_text = """
    Điều 15 - Tình huống cắt hướng
    
    Khi hai tàu máy đi cắt hướng nhau có nguy cơ va chạm, tàu nào 
    nhìn thấy tàu kia ở bên mạn phải của mình phải nhường đường.
    
    Tham khảo Điều 7 (Nguy cơ va chạm) và Điều 8 (Hành động tránh va).
    """
    
    result = await agent.extract(sample_text, "COLREGs")
    
    print(f"\n📌 Entities ({len(result.entities)}):")
    for e in result.entities:
        print(f"   • [{e.entity_type}] {e.name}")
    
    print(f"\n🔗 Relations ({len(result.relations)}):")
    for r in result.relations:
        print(f"   • {r.source_id} --[{r.relation_type}]--> {r.target_id}")
    
    # Test 2: Process via state (multi-agent integration)
    print("\n" + "=" * 60)
    print("📝 Test 2: Process via AgentState (Multi-Agent)")
    print("=" * 60)
    
    state: AgentState = {
        "query": "Explain crossing situation rule",
        "context": {
            "text_for_extraction": sample_text,
            "source": "test_document"
        },
        "agent_outputs": {}
    }
    
    updated_state = await agent.process(state)
    
    kg_output = updated_state.get("agent_outputs", {}).get("kg_builder", {})
    print(f"\n✅ State updated:")
    print(f"   entity_count: {kg_output.get('entity_count', 0)}")
    print(f"   relation_count: {kg_output.get('relation_count', 0)}")
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    test1_pass = len(result.entities) > 0
    test2_pass = kg_output.get('entity_count', 0) > 0
    
    print(f"   Direct extraction: {'✅ PASS' if test1_pass else '❌ FAIL'}")
    print(f"   Multi-agent state: {'✅ PASS' if test2_pass else '❌ FAIL'}")
    
    return test1_pass and test2_pass  


if __name__ == "__main__":
    asyncio.run(test_kg_builder_agent())
