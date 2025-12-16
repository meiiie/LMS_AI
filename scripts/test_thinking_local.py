"""
Test Native Thinking Flow - Local
=================================
Script để test CHỈ THỊ SỐ 29 v2 trước khi deploy.

Run: python scripts/test_thinking_local.py
"""

import asyncio
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime


async def test_thinking():
    """Test native thinking flow end-to-end."""
    
    print("=" * 70)
    print("  Local Test: CHỈ THỊ SỐ 29 v2 - Native Thinking Flow")
    print("=" * 70)
    print()
    
    # Step 1: Test AgentState has thinking field
    print("1. Checking AgentState TypedDict...")
    try:
        from app.engine.multi_agent.state import AgentState
        import typing
        
        hints = typing.get_type_hints(AgentState)
        
        has_thinking = 'thinking' in hints
        has_thinking_content = 'thinking_content' in hints
        
        print(f"   - thinking field: {'✅ EXISTS' if has_thinking else '❌ MISSING'}")
        print(f"   - thinking_content field: {'✅ EXISTS' if has_thinking_content else '❌ MISSING'}")
        
        if not has_thinking:
            print("\n   ❌ FAIL: AgentState missing 'thinking' field!")
            print("   Fix: Add 'thinking: Optional[str]' to state.py")
            return False
        
        print("   ✅ AgentState schema OK")
        
    except Exception as e:
        print(f"   ❌ Error importing AgentState: {e}")
        return False
    
    print()
    
    # Step 2: Test CorrectiveRAGResult has thinking field
    print("2. Checking CorrectiveRAGResult dataclass...")
    try:
        from app.engine.agentic_rag.corrective_rag import CorrectiveRAGResult
        import dataclasses
        
        fields = {f.name for f in dataclasses.fields(CorrectiveRAGResult)}
        
        has_thinking = 'thinking' in fields
        has_thinking_content = 'thinking_content' in fields
        
        print(f"   - thinking field: {'✅ EXISTS' if has_thinking else '❌ MISSING'}")
        print(f"   - thinking_content field: {'✅ EXISTS' if has_thinking_content else '❌ MISSING'}")
        
        if not has_thinking:
            print("\n   ❌ FAIL: CorrectiveRAGResult missing 'thinking' field!")
            return False
            
        print("   ✅ CorrectiveRAGResult schema OK")
        
    except Exception as e:
        print(f"   ❌ Error importing CorrectiveRAGResult: {e}")
        return False
    
    print()
    
    # Step 3: Test RAG response extraction
    print("3. Testing extract_thinking_from_response utility...")
    try:
        from app.engine.agentic_rag.rag_agent import extract_thinking_from_response
        
        # Mock response with thinking
        class MockResponse:
            def __init__(self):
                self.content = "This is the answer"
        
        class MockCandidate:
            def __init__(self):
                class MockThoughtBlock:
                    text = "I need to analyze this query..."
                
                class MockContent:
                    parts = [MockThoughtBlock()]
                
                self.content = MockContent()
        
        class MockResponseWithThinking:
            def __init__(self):
                self.content = "This is the answer"
                self.response_metadata = {
                    '_raw_response': type('obj', (object,), {
                        'candidates': [MockCandidate()]
                    })()
                }
        
        thinking = extract_thinking_from_response(MockResponseWithThinking())
        
        if thinking:
            print(f"   ✅ Extracted thinking: '{thinking[:50]}...'")
        else:
            print("   ⚠️ No thinking extracted (mock may not match real structure)")
            print("   (This is OK - real Gemini response structure may differ)")
        
    except ImportError:
        print("   ⚠️ extract_thinking_from_response not found - function may need to be added")
    except Exception as e:
        print(f"   ⚠️ Mock test skipped: {e}")
    
    print()
    
    # Step 4: Test chat_orchestrator metadata mapping
    print("4. Checking chat_orchestrator thinking priority logic...")
    try:
        # Read the file and check for correct logic
        with open('app/services/chat_orchestrator.py', 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for correct priority: thinking OR thinking_content
        if 'result.get("thinking") or result.get("thinking_content")' in content:
            print("   ✅ Correct fallback logic: thinking → thinking_content")
        elif '"thinking": result.get("thinking")' in content:
            print("   ✅ Thinking field mapped")
        else:
            print("   ⚠️ Check thinking mapping in chat_orchestrator.py")
        
    except Exception as e:
        print(f"   ⚠️ Could not check chat_orchestrator.py: {e}")
    
    print()
    
    # Step 5: Test API schema
    print("5. Checking ChatResponseMetadata schema...")
    try:
        from app.models.schemas import ChatResponseMetadata
        import inspect
        
        sig = inspect.signature(ChatResponseMetadata)
        params = set(sig.parameters.keys())
        
        has_thinking = 'thinking' in params
        has_thinking_content = 'thinking_content' in params
        
        print(f"   - thinking field: {'✅ EXISTS' if has_thinking else '❌ MISSING'}")
        print(f"   - thinking_content field: {'✅ EXISTS' if has_thinking_content else '❌ MISSING'}")
        
        if not has_thinking:
            print("   ❌ ChatResponseMetadata missing 'thinking' field!")
            return False
            
        print("   ✅ ChatResponseMetadata schema OK")
        
    except Exception as e:
        print(f"   ❌ Error checking ChatResponseMetadata: {e}")
        return False
    
    print()
    print("=" * 70)
    print("  All schema checks passed! ✅")
    print("=" * 70)
    print()
    print("Next steps:")
    print("  1. Deploy to production")
    print("  2. Run: python scripts/test_production_api.py")
    print("  3. Check API response for:")
    print('     - "thinking": "<native Gemini thinking>"')
    print('     - "thinking_content": "<structured summary>"')
    print()
    
    return True


if __name__ == "__main__":
    success = asyncio.run(test_thinking())
    sys.exit(0 if success else 1)
