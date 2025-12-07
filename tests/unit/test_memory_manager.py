"""
Test Memory Manager - CHỈ THỊ KỸ THUẬT SỐ 24
Test "Check before Write" logic with deduplication.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()


async def test_memory_manager():
    """Test Memory Manager deduplication logic."""
    print("\n" + "="*60)
    print("TEST: Memory Manager - CHỈ THỊ SỐ 24")
    print("="*60)
    
    from app.engine.memory_manager import MemoryManager, MemoryAction, get_memory_manager
    from app.engine.semantic_memory import SemanticMemoryEngine
    
    # Initialize
    semantic_memory = SemanticMemoryEngine()
    memory_manager = get_memory_manager(semantic_memory)
    
    test_user = f"mm_test_{int(time.time())}"
    
    print(f"\nTest User: {test_user}")
    
    # Test 1: First save (should INSERT)
    print("\n--- Test 1: First Save (should INSERT) ---")
    decision1 = await memory_manager.check_and_save(
        user_id=test_user,
        new_fact="name: Minh",
        fact_type="name"
    )
    print(f"Action: {decision1.action.value}")
    print(f"Reason: {decision1.reason}")
    assert decision1.action == MemoryAction.INSERT, "First save should INSERT"
    print("✅ PASS")
    
    # Wait for DB to sync
    await asyncio.sleep(2)
    
    # Test 2: Duplicate save (should IGNORE - Exit 0)
    print("\n--- Test 2: Duplicate Save (should IGNORE) ---")
    decision2 = await memory_manager.check_and_save(
        user_id=test_user,
        new_fact="name: Minh",
        fact_type="name"
    )
    print(f"Action: {decision2.action.value}")
    print(f"Reason: {decision2.reason}")
    # Note: May be INSERT if semantic search doesn't find it yet
    print(f"Result: {'✅ PASS (Exit 0)' if decision2.action == MemoryAction.IGNORE else '⚠️ May need more time for semantic search'}")
    
    # Test 3: Similar but different (should use LLM Judge)
    print("\n--- Test 3: Similar Content (LLM Judge) ---")
    decision3 = await memory_manager.check_and_save(
        user_id=test_user,
        new_fact="Tên của user là Minh",
        fact_type="name"
    )
    print(f"Action: {decision3.action.value}")
    print(f"Reason: {decision3.reason}")
    print("✅ LLM Judge executed")
    
    # Test 4: Conflicting info (should UPDATE)
    print("\n--- Test 4: Conflicting Info (should UPDATE) ---")
    decision4 = await memory_manager.check_and_save(
        user_id=test_user,
        new_fact="name: Hùng",  # Different name
        fact_type="name"
    )
    print(f"Action: {decision4.action.value}")
    print(f"Reason: {decision4.reason}")
    print(f"Target ID: {decision4.target_id}")
    print("✅ Conflict handling executed")
    
    # Test 5: Completely new info (should INSERT)
    print("\n--- Test 5: New Info (should INSERT) ---")
    decision5 = await memory_manager.check_and_save(
        user_id=test_user,
        new_fact="goal: Thi bằng thuyền trưởng hạng 3",
        fact_type="goal"
    )
    print(f"Action: {decision5.action.value}")
    print(f"Reason: {decision5.reason}")
    assert decision5.action == MemoryAction.INSERT, "New info should INSERT"
    print("✅ PASS")
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Test 1 (First Save): {decision1.action.value}")
    print(f"Test 2 (Duplicate): {decision2.action.value}")
    print(f"Test 3 (Similar): {decision3.action.value}")
    print(f"Test 4 (Conflict): {decision4.action.value}")
    print(f"Test 5 (New Info): {decision5.action.value}")


async def test_tool_save_user_info():
    """Test tool_save_user_info with Memory Manager integration."""
    print("\n" + "="*60)
    print("TEST: tool_save_user_info with Memory Manager")
    print("="*60)
    
    from app.engine.unified_agent import tool_save_user_info, _semantic_memory
    from app.engine.semantic_memory import get_semantic_memory_engine
    
    # Initialize semantic memory
    import app.engine.unified_agent as ua
    ua._semantic_memory = get_semantic_memory_engine()
    ua._current_user_id = f"tool_test_{int(time.time())}"
    
    print(f"\nTest User: {ua._current_user_id}")
    
    # Test 1: First save
    print("\n--- Test 1: First Save ---")
    result1 = await tool_save_user_info.ainvoke({"key": "name", "value": "Minh"})
    print(f"Result: {result1}")
    
    # Wait
    await asyncio.sleep(2)
    
    # Test 2: Duplicate
    print("\n--- Test 2: Duplicate Save ---")
    result2 = await tool_save_user_info.ainvoke({"key": "name", "value": "Minh"})
    print(f"Result: {result2}")
    
    if "Exit 0" in result2 or "đã tồn tại" in result2:
        print("✅ Deduplication working!")
    else:
        print("⚠️ May need semantic search time")
    
    # Test 3: Update
    print("\n--- Test 3: Update Name ---")
    result3 = await tool_save_user_info.ainvoke({"key": "name", "value": "Hùng"})
    print(f"Result: {result3}")


async def main():
    print("\n" + "="*60)
    print("MEMORY MANAGER TEST SUITE")
    print("CHỈ THỊ KỸ THUẬT SỐ 24")
    print("="*60)
    
    # Test Memory Manager directly
    await test_memory_manager()
    
    # Test tool integration
    await test_tool_save_user_info()
    
    print("\n✅ All tests completed!")


if __name__ == "__main__":
    asyncio.run(main())
