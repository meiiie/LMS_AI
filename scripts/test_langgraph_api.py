"""
Test LangGraph/LangChain API availability.
Kiểm tra xem API nào thực sự hoạt động với phiên bản hiện tại.
"""

import sys
sys.path.insert(0, ".")

print("=" * 60)
print("Testing LangGraph/LangChain API Availability")
print("=" * 60)

# Test 1: Check langchain version
print("\n1. Checking installed versions...")
try:
    import langchain
    print(f"   langchain: {langchain.__version__}")
except Exception as e:
    print(f"   langchain: ERROR - {e}")

try:
    import langchain_core
    print(f"   langchain-core: {langchain_core.__version__}")
except Exception as e:
    print(f"   langchain-core: ERROR - {e}")

try:
    import langgraph
    print(f"   langgraph: {langgraph.__version__}")
except Exception as e:
    print(f"   langgraph: ERROR - {e}")

try:
    import langchain_google_genai
    print(f"   langchain-google-genai: {langchain_google_genai.__version__}")
except Exception as e:
    print(f"   langchain-google-genai: ERROR - {e}")

# Test 2: Check create_agent from langchain.agents
print("\n2. Testing: from langchain.agents import create_agent")
try:
    from langchain.agents import create_agent
    print("   ✅ SUCCESS - create_agent available")
except ImportError as e:
    print(f"   ❌ FAILED - {e}")

# Test 3: Check create_react_agent from langgraph.prebuilt
print("\n3. Testing: from langgraph.prebuilt import create_react_agent")
try:
    from langgraph.prebuilt import create_react_agent
    print("   ✅ SUCCESS - create_react_agent available")
    
    # Check signature
    import inspect
    sig = inspect.signature(create_react_agent)
    params = list(sig.parameters.keys())
    print(f"   Parameters: {params}")
    
    if 'state_modifier' in params:
        print("   ⚠️  state_modifier is available (old API)")
    if 'prompt' in params:
        print("   ✅ prompt is available (new API)")
    if 'system_prompt' in params:
        print("   ✅ system_prompt is available")
        
except ImportError as e:
    print(f"   ❌ FAILED - {e}")

# Test 4: Check @tool decorator
print("\n4. Testing: @tool decorator")
try:
    from langchain_core.tools import tool
    
    @tool(description="Test tool")
    def test_tool(query: str) -> str:
        """Test tool docstring."""
        return f"Result: {query}"
    
    print(f"   ✅ SUCCESS - Tool created: {test_tool.name}")
    print(f"   Description: {test_tool.description}")
except Exception as e:
    print(f"   ❌ FAILED - {e}")

# Test 5: Check async tool
print("\n5. Testing: async @tool")
try:
    from langchain_core.tools import tool
    
    @tool(description="Async test tool")
    async def async_test_tool(query: str) -> str:
        """Async test tool."""
        return f"Async result: {query}"
    
    print(f"   ✅ SUCCESS - Async tool created: {async_test_tool.name}")
except Exception as e:
    print(f"   ❌ FAILED - {e}")

# Test 6: Check ChatGoogleGenerativeAI
print("\n6. Testing: ChatGoogleGenerativeAI")
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    print("   ✅ SUCCESS - ChatGoogleGenerativeAI available")
except Exception as e:
    print(f"   ❌ FAILED - {e}")

print("\n" + "=" * 60)
print("API Test Complete")
print("=" * 60)
