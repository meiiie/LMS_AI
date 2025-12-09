"""
Test Deployed Flow - Kiểm tra luồng logic trên API đã deploy

Test các luồng:
1. Memory Loading: Insights + Context
2. Thinking/Reasoning: <thinking> tag
3. Follow-up Context: Câu hỏi mơ hồ
4. Memory Saving: Ghi nhớ tên user
5. Tool Usage: tool_maritime_search, tool_save_user_info

Usage:
    python scripts/test_deployed_flow.py
"""

import asyncio
import httpx
import json
import time
from datetime import datetime

# Configuration
BASE_URL = "https://maritime-ai-chatbot.onrender.com"  # Render URL
API_KEY = "secret_key_cho_team_lms"  # Production API key
TEST_USER_ID = f"test_flow_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

# Headers
HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY
}


async def send_message(client: httpx.AsyncClient, message: str, session_id: str = None) -> dict:
    """Send a message to the chat API."""
    payload = {
        "user_id": TEST_USER_ID,
        "message": message,
        "role": "student"
    }
    if session_id:
        payload["session_id"] = session_id
    
    try:
        response = await client.post(
            f"{BASE_URL}/api/v1/chat",
            json=payload,
            headers=HEADERS,
            timeout=60.0  # Longer timeout for cold start
        )
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def print_response(response: dict, test_name: str):
    """Pretty print response."""
    print(f"\n{'='*60}")
    print(f"TEST: {test_name}")
    print(f"{'='*60}")
    
    if "error" in response:
        print(f"❌ ERROR: {response['error']}")
        return
    
    if response.get("status") == "success":
        data = response.get("data", {})
        answer = data.get("answer", "")
        sources = data.get("sources", [])
        metadata = response.get("metadata", {})
        
        # Check for <thinking> tag
        has_thinking = "<thinking>" in answer
        
        # Extract thinking content if present
        thinking_content = ""
        if has_thinking:
            import re
            match = re.search(r'<thinking>(.*?)</thinking>', answer, re.DOTALL)
            if match:
                thinking_content = match.group(1).strip()[:200] + "..."
        
        print(f"✅ Status: success")
        print(f"📝 Answer length: {len(answer)} chars")
        print(f"🧠 Has <thinking>: {has_thinking}")
        if thinking_content:
            print(f"   Thinking preview: {thinking_content}")
        print(f"📚 Sources: {len(sources)}")
        print(f"⚙️ Agent: {metadata.get('agent_type', 'N/A')}")
        print(f"🔧 Tools used: {metadata.get('tools_used', [])}")
        print(f"⏱️ Processing time: {metadata.get('processing_time', 'N/A')}s")
        
        # Print answer preview
        answer_preview = answer.replace("<thinking>", "").split("</thinking>")[-1].strip()[:300]
        print(f"\n📄 Answer preview:\n{answer_preview}...")
        
        if sources:
            print(f"\n📖 Sources:")
            for s in sources[:3]:
                print(f"   - {s.get('title', 'N/A')}")
    else:
        print(f"❌ Status: {response.get('status', 'unknown')}")
        print(f"Message: {response.get('message', response)}")


async def test_health(client: httpx.AsyncClient):
    """Test health endpoint."""
    print("\n" + "="*60)
    print("TEST: Health Check")
    print("="*60)
    
    try:
        response = await client.get(f"{BASE_URL}/health", timeout=30.0)
        data = response.json()
        print(f"✅ Status: {data.get('status', 'unknown')}")
        print(f"📊 Components: {json.dumps(data.get('components', {}), indent=2)}")
    except Exception as e:
        print(f"❌ Error: {e}")


async def test_flow():
    """Test complete flow."""
    print("\n" + "#"*60)
    print("# MARITIME AI TUTOR - DEPLOYED FLOW TEST")
    print(f"# URL: {BASE_URL}")
    print(f"# User ID: {TEST_USER_ID}")
    print(f"# Time: {datetime.now().isoformat()}")
    print("#"*60)
    
    async with httpx.AsyncClient() as client:
        # Test 0: Health check
        await test_health(client)
        
        # Test 1: Giới thiệu bản thân (Memory Save)
        print("\n\n" + "="*60)
        print("FLOW TEST 1: MEMORY SAVE - Giới thiệu bản thân")
        print("="*60)
        response1 = await send_message(client, "Xin chào, tôi là Hùng, sinh viên năm 3 Đại học Hàng hải")
        print_response(response1, "Giới thiệu bản thân")
        session_id = response1.get("metadata", {}).get("session_id")
        
        await asyncio.sleep(2)  # Wait for background tasks
        
        # Test 2: Hỏi kiến thức (RAG + Thinking)
        print("\n\n" + "="*60)
        print("FLOW TEST 2: RAG + THINKING - Hỏi về Rule 15")
        print("="*60)
        response2 = await send_message(client, "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng", session_id)
        print_response(response2, "Hỏi về Rule 15")
        
        await asyncio.sleep(2)
        
        # Test 3: Follow-up question (Context Understanding)
        print("\n\n" + "="*60)
        print("FLOW TEST 3: FOLLOW-UP CONTEXT - Câu hỏi nối tiếp")
        print("="*60)
        response3 = await send_message(client, "Còn quy tắc 16 thì sao?", session_id)
        print_response(response3, "Follow-up: Quy tắc 16")
        
        await asyncio.sleep(2)
        
        # Test 4: Ambiguous question (Context Inference)
        print("\n\n" + "="*60)
        print("FLOW TEST 4: AMBIGUOUS QUESTION - Câu hỏi mơ hồ")
        print("="*60)
        response4 = await send_message(client, "Tàu nào phải nhường đường?", session_id)
        print_response(response4, "Ambiguous: Tàu nào nhường đường?")
        
        await asyncio.sleep(2)
        
        # Test 5: Memory Recall (Check if name is remembered)
        print("\n\n" + "="*60)
        print("FLOW TEST 5: MEMORY RECALL - Kiểm tra ghi nhớ tên")
        print("="*60)
        response5 = await send_message(client, "Bạn còn nhớ tên tôi không?", session_id)
        print_response(response5, "Memory Recall: Tên user")
        
        # Check if name "Hùng" is in response
        answer5 = response5.get("data", {}).get("answer", "")
        if "Hùng" in answer5 or "hùng" in answer5.lower():
            print("\n✅ MEMORY TEST PASSED: AI nhớ tên user là Hùng")
        else:
            print("\n⚠️ MEMORY TEST: Không tìm thấy tên 'Hùng' trong response")
        
        await asyncio.sleep(2)
        
        # Test 6: Empathy (Non-RAG response)
        print("\n\n" + "="*60)
        print("FLOW TEST 6: EMPATHY - Chia sẻ cảm xúc")
        print("="*60)
        response6 = await send_message(client, "Học nhiều quá mệt quá", session_id)
        print_response(response6, "Empathy: Mệt mỏi")
        
        # Summary
        print("\n\n" + "#"*60)
        print("# TEST SUMMARY")
        print("#"*60)
        
        tests = [
            ("Memory Save", response1),
            ("RAG + Thinking", response2),
            ("Follow-up Context", response3),
            ("Ambiguous Question", response4),
            ("Memory Recall", response5),
            ("Empathy", response6),
        ]
        
        passed = 0
        for name, resp in tests:
            if resp.get("status") == "success":
                passed += 1
                print(f"✅ {name}: PASSED")
            else:
                print(f"❌ {name}: FAILED")
        
        print(f"\n📊 Result: {passed}/{len(tests)} tests passed")
        
        # CHỈ THỊ SỐ 27: Verify API Transparency features
        print("\n\n" + "#"*60)
        print("# CHỈ THỊ SỐ 27: API TRANSPARENCY VERIFICATION")
        print("#"*60)
        
        # Check tools_used in RAG responses
        rag_responses = [response2, response3, response4]
        tools_used_count = 0
        thinking_count = 0
        
        for i, resp in enumerate(rag_responses, 2):
            metadata = resp.get("metadata", {})
            tools_used = metadata.get("tools_used", [])
            answer = resp.get("data", {}).get("answer", "")
            has_thinking = "<thinking>" in answer
            
            if tools_used:
                tools_used_count += 1
                print(f"✅ Test {i}: tools_used populated: {[t.get('name') for t in tools_used]}")
            else:
                print(f"⚠️ Test {i}: tools_used is empty")
            
            if has_thinking:
                thinking_count += 1
                print(f"✅ Test {i}: <thinking> tag present")
            else:
                print(f"⚠️ Test {i}: <thinking> tag missing (RAG query should have it)")
        
        # Check empathy response (should have empty tools_used)
        empathy_tools = response6.get("metadata", {}).get("tools_used", [])
        empathy_thinking = "<thinking>" in response6.get("data", {}).get("answer", "")
        
        if not empathy_tools:
            print(f"✅ Empathy: tools_used correctly empty")
        else:
            print(f"⚠️ Empathy: tools_used should be empty but has {empathy_tools}")
        
        print(f"\n📊 API Transparency: {tools_used_count}/3 RAG responses have tools_used")
        print(f"📊 Thinking Tags: {thinking_count}/3 RAG responses have <thinking>")


if __name__ == "__main__":
    asyncio.run(test_flow())
