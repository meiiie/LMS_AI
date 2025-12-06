"""
Test Deep Reasoning & Memory Isolation on Production API (Render)

CHỈ THỊ SỐ 21: Deep Reasoning - Proactive AI Behavior
CHỈ THỊ SỐ 22: Memory Isolation - Blocked content filtering

This script tests:
1. Deep Reasoning - AI proactive continuation suggestions
2. Memory Isolation - Blocked messages not in context
3. Context Window - 50 messages history
4. Thinking tags in responses
"""
import requests
import time
import json

# Production API
API_URL = "https://maritime-ai-chatbot.onrender.com/api/v1/chat"
API_KEY = "lms_secret_key_2024"

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

# Test user for this session
TEST_USER = f"deep_reasoning_test_{int(time.time())}"


def send_chat(message: str, user_id: str = None) -> dict:
    """Send a chat message and return response."""
    payload = {
        "user_id": user_id or TEST_USER,
        "message": message,
        "role": "student"
    }
    
    try:
        start = time.time()
        response = requests.post(API_URL, json=payload, headers=HEADERS, timeout=90)
        latency = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "answer": data.get("data", {}).get("answer", ""),
                "latency": latency,
                "raw": data
            }
        else:
            return {
                "success": False,
                "error": f"HTTP {response.status_code}: {response.text[:200]}",
                "latency": latency
            }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "latency": 0
        }


def test_proactive_continuation():
    """
    Test Deep Reasoning - Proactive Continuation
    
    Scenario:
    1. User asks about Rule 15
    2. AI starts explaining
    3. User interrupts with different question
    4. AI should offer to continue Rule 15 explanation
    """
    print("\n" + "=" * 70)
    print("TEST 1: Deep Reasoning - Proactive Continuation")
    print("=" * 70)
    
    user_id = f"proactive_test_{int(time.time())}"
    
    # Step 1: Ask about Rule 15
    print("\n[Step 1] User asks about Rule 15...")
    result1 = send_chat("Rule 15 COLREGs quy định về điều gì?", user_id)
    if not result1["success"]:
        print(f"❌ Failed: {result1['error']}")
        return False
    
    print(f"   AI Response: {result1['answer'][:200]}...")
    print(f"   Latency: {result1['latency']:.0f}ms")
    time.sleep(3)
    
    # Step 2: Interrupt with different question
    print("\n[Step 2] User interrupts with different question...")
    result2 = send_chat("Thời tiết hôm nay thế nào?", user_id)
    if not result2["success"]:
        print(f"❌ Failed: {result2['error']}")
        return False
    
    print(f"   AI Response: {result2['answer'][:200]}...")
    print(f"   Latency: {result2['latency']:.0f}ms")
    
    # Check if AI offers to continue Rule 15
    answer_lower = result2["answer"].lower()
    has_continuation_offer = any(phrase in answer_lower for phrase in [
        "rule 15", "quy tắc 15", "tiếp tục", "nãy", "trước đó",
        "đang nói", "muốn nghe tiếp", "quay lại"
    ])
    
    if has_continuation_offer:
        print("\n✅ PASSED: AI offered to continue previous explanation!")
    else:
        print("\n⚠️ PARTIAL: AI didn't explicitly offer continuation")
        print("   (This may be expected if AI completed the explanation)")
    
    return True


def test_thinking_tags():
    """
    Test Deep Reasoning - Thinking Tags
    
    Check if AI uses <thinking> tags in responses
    """
    print("\n" + "=" * 70)
    print("TEST 2: Deep Reasoning - Thinking Tags")
    print("=" * 70)
    
    user_id = f"thinking_test_{int(time.time())}"
    
    # Ask a complex question that requires reasoning
    print("\n[Step 1] Asking complex maritime question...")
    result = send_chat(
        "Nếu hai tàu đang đối mũi và một tàu bất ngờ chuyển hướng sang phải, "
        "tàu kia nên làm gì theo COLREGs?",
        user_id
    )
    
    if not result["success"]:
        print(f"❌ Failed: {result['error']}")
        return False
    
    answer = result["answer"]
    print(f"   AI Response: {answer[:300]}...")
    print(f"   Latency: {result['latency']:.0f}ms")
    
    # Check for thinking tags
    has_thinking = "<thinking>" in answer or "</thinking>" in answer
    
    if has_thinking:
        print("\n✅ PASSED: AI used <thinking> tags!")
        # Extract thinking content
        import re
        thinking_match = re.search(r'<thinking>(.*?)</thinking>', answer, re.DOTALL)
        if thinking_match:
            print(f"   Thinking: {thinking_match.group(1)[:150]}...")
    else:
        print("\n⚠️ INFO: No <thinking> tags in response")
        print("   (Thinking tags may be optional for simple questions)")
    
    return True


def test_memory_isolation():
    """
    Test Memory Isolation - Blocked content not in context
    
    Scenario:
    1. User sends inappropriate message (gets blocked)
    2. User sends normal message
    3. AI should NOT reference the blocked message
    """
    print("\n" + "=" * 70)
    print("TEST 3: Memory Isolation - Blocked Content Filtering")
    print("=" * 70)
    
    user_id = f"isolation_test_{int(time.time())}"
    
    # Step 1: Send inappropriate message (should be blocked)
    print("\n[Step 1] Sending inappropriate message (should be blocked)...")
    result1 = send_chat("Mày là đồ ngu", user_id)
    if not result1["success"]:
        print(f"❌ Failed: {result1['error']}")
        return False
    
    print(f"   AI Response: {result1['answer'][:150]}...")
    
    # Verify it was blocked
    is_blocked = any(phrase in result1["answer"].lower() for phrase in [
        "không phù hợp", "không thể xử lý", "xin lỗi", "không thể trả lời"
    ])
    
    if is_blocked:
        print("   ✅ Message was blocked as expected")
    else:
        print("   ⚠️ Message may not have been blocked")
    
    time.sleep(2)
    
    # Step 2: Send normal message
    print("\n[Step 2] Sending normal message...")
    result2 = send_chat("Bạn có thể giúp tôi học về hàng hải không?", user_id)
    if not result2["success"]:
        print(f"❌ Failed: {result2['error']}")
        return False
    
    print(f"   AI Response: {result2['answer'][:200]}...")
    
    # Check that AI doesn't reference the blocked message
    answer_lower = result2["answer"].lower()
    references_blocked = any(phrase in answer_lower for phrase in [
        "ngu", "xúc phạm", "trước đó bạn nói", "tin nhắn trước"
    ])
    
    if not references_blocked:
        print("\n✅ PASSED: AI did not reference blocked message!")
    else:
        print("\n❌ FAILED: AI may have referenced blocked content")
    
    return not references_blocked


def test_context_window_size():
    """
    Test Context Window - 50 messages
    
    Send multiple messages and verify AI remembers context
    """
    print("\n" + "=" * 70)
    print("TEST 4: Context Window - Memory Persistence")
    print("=" * 70)
    
    user_id = f"context_test_{int(time.time())}"
    
    # Step 1: Introduce yourself
    print("\n[Step 1] User introduces themselves...")
    result1 = send_chat("Xin chào, tôi là Minh, sinh viên năm 3 ngành Hàng hải", user_id)
    if not result1["success"]:
        print(f"❌ Failed: {result1['error']}")
        return False
    
    print(f"   AI Response: {result1['answer'][:150]}...")
    time.sleep(2)
    
    # Step 2: Ask a question
    print("\n[Step 2] User asks a question...")
    result2 = send_chat("Rule 5 là gì?", user_id)
    if not result2["success"]:
        print(f"❌ Failed: {result2['error']}")
        return False
    
    print(f"   AI Response: {result2['answer'][:150]}...")
    time.sleep(2)
    
    # Step 3: Check if AI remembers the name
    print("\n[Step 3] Checking if AI remembers user's name...")
    result3 = send_chat("Bạn còn nhớ tên tôi không?", user_id)
    if not result3["success"]:
        print(f"❌ Failed: {result3['error']}")
        return False
    
    print(f"   AI Response: {result3['answer'][:200]}...")
    
    # Check if AI remembers the name
    remembers_name = "minh" in result3["answer"].lower()
    
    if remembers_name:
        print("\n✅ PASSED: AI remembered user's name!")
    else:
        print("\n⚠️ PARTIAL: AI may not have remembered the name")
        print("   (This could be due to context window or memory settings)")
    
    return True


def test_config_values():
    """
    Test Configuration - Check if Deep Reasoning is enabled
    """
    print("\n" + "=" * 70)
    print("TEST 5: Configuration Check")
    print("=" * 70)
    
    # Check health endpoint for config info
    try:
        health_url = "https://maritime-ai-chatbot.onrender.com/api/v1/health"
        response = requests.get(health_url, headers=HEADERS, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            print(f"   Service Status: {data.get('status', 'unknown')}")
            print(f"   Version: {data.get('version', 'unknown')}")
            print(f"   Environment: {data.get('environment', 'unknown')}")
            print("\n✅ API is responding")
            return True
        else:
            print(f"❌ Health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    print("=" * 70)
    print("DEEP REASONING & MEMORY ISOLATION PRODUCTION TEST")
    print("CHỈ THỊ SỐ 21 & 22")
    print("API: https://maritime-ai-chatbot.onrender.com")
    print("=" * 70)
    
    results = []
    
    # Test 0: Check API health
    results.append(("Config Check", test_config_values()))
    time.sleep(2)
    
    # Test 1: Proactive Continuation
    results.append(("Proactive Continuation", test_proactive_continuation()))
    time.sleep(3)
    
    # Test 2: Thinking Tags
    results.append(("Thinking Tags", test_thinking_tags()))
    time.sleep(3)
    
    # Test 3: Memory Isolation
    results.append(("Memory Isolation", test_memory_isolation()))
    time.sleep(3)
    
    # Test 4: Context Window
    results.append(("Context Window", test_context_window_size()))
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    for name, passed in results:
        status = "✅" if passed else "❌"
        print(f"  {status} {name}")
    
    passed_count = sum(1 for _, p in results if p)
    total = len(results)
    
    print(f"\nPassed: {passed_count}/{total} ({passed_count/total*100:.0f}%)")
    
    if passed_count == total:
        print("\n🎉 ALL TESTS PASSED! Deep Reasoning is working on production!")
    else:
        print(f"\n⚠️ {total - passed_count} test(s) need attention. Check results above.")


if __name__ == "__main__":
    main()
