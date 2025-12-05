"""
Test Manual ReAct pattern với LangChain 1.x API.
Theo tài liệu: Dùng model.bind_tools() + manual loop
"""

import sys
import asyncio
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

print("=" * 60)
print("Testing Manual ReAct Pattern (LangChain 1.x)")
print("=" * 60)

# Test 1: Import tool decorator
print("\n1. Testing @tool decorator from langchain.tools...")
try:
    from langchain.tools import tool
    print("   ✅ from langchain.tools import tool - SUCCESS")
except ImportError:
    try:
        from langchain_core.tools import tool
        print("   ✅ from langchain_core.tools import tool - SUCCESS (fallback)")
    except ImportError as e:
        print(f"   ❌ FAILED - {e}")
        sys.exit(1)

# Test 2: Define tools
print("\n2. Defining tools...")

@tool(description="Search maritime regulations")
def search_maritime(query: str) -> str:
    """Search maritime knowledge base."""
    return f"Found info about: {query}"

@tool(description="Get user information")
def get_user_info(key: str) -> str:
    """Get saved user info."""
    return f"User {key}: Unknown"

print(f"   ✅ Tool 1: {search_maritime.name} - {search_maritime.description}")
print(f"   ✅ Tool 2: {get_user_info.name} - {get_user_info.description}")

# Test 3: ChatGoogleGenerativeAI with bind_tools
print("\n3. Testing ChatGoogleGenerativeAI.bind_tools()...")
try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    from app.core.config import settings
    
    llm = ChatGoogleGenerativeAI(
        google_api_key=settings.google_api_key,
        model=settings.google_model,
        temperature=0.7,
    )
    
    llm_with_tools = llm.bind_tools([search_maritime, get_user_info])
    print(f"   ✅ Model: {settings.google_model}")
    print(f"   ✅ bind_tools() - SUCCESS")
except Exception as e:
    print(f"   ❌ FAILED - {e}")
    sys.exit(1)

# Test 4: Manual ReAct loop
print("\n4. Testing Manual ReAct loop...")

async def manual_react(user_message: str, max_iterations: int = 3):
    """Manual ReAct implementation theo tài liệu."""
    from langchain_core.messages import HumanMessage, ToolMessage, SystemMessage
    
    tools = [search_maritime, get_user_info]
    tools_map = {t.name: t for t in tools}
    
    # System prompt
    system_prompt = """Bạn là Maritime AI Tutor. 
Khi user hỏi về luật hàng hải, hãy gọi tool search_maritime.
Trả lời bằng tiếng Việt."""
    
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_message)
    ]
    
    for i in range(max_iterations):
        print(f"\n   [Iteration {i+1}]")
        
        # Call LLM
        response = await llm_with_tools.ainvoke(messages)
        print(f"   Response type: {type(response).__name__}")
        
        # Check for tool calls
        tool_calls = getattr(response, 'tool_calls', [])
        print(f"   Tool calls: {len(tool_calls)}")
        
        if not tool_calls:
            # No tool calls = final answer
            content = response.content
            if isinstance(content, list):
                content = content[0].get('text', str(content)) if content else ""
            print(f"   ✅ Final answer: {content[:100]}...")
            return content
        
        # Execute tools
        messages.append(response)
        for tc in tool_calls:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            print(f"   Calling tool: {tool_name}({tool_args})")
            
            if tool_name in tools_map:
                result = tools_map[tool_name].invoke(tool_args)
                print(f"   Tool result: {result}")
            else:
                result = f"Tool {tool_name} not found"
            
            messages.append(ToolMessage(
                content=str(result),
                tool_call_id=tc.get("id", "")
            ))
    
    return "Max iterations reached"

# Run test
try:
    result = asyncio.run(manual_react("Quy tắc 15 COLREGs là gì?"))
    print(f"\n   ✅ Manual ReAct - SUCCESS")
    print(f"   Result: {result[:200]}...")
except Exception as e:
    print(f"\n   ❌ Manual ReAct - FAILED: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("Test Complete")
print("=" * 60)
