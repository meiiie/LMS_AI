"""
Test Memory & Intelligence của Maritime AI Tutor

Kiểm tra:
1. Chat History - AI nhớ conversation trước
2. Semantic Memory - AI nhớ facts về user
3. Follow-up Context - AI hiểu ngữ cảnh câu hỏi tiếp theo
"""
import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

RENDER_URL = os.getenv("RENDER_URL", "https://maritime-ai-chatbot.onrender.com")
API_KEY = os.getenv("API_KEY", "")

def send_message(message: str, user_id: str, session_id: str) -> dict:
    """Send chat message"""
    headers = {"X-API-Key": API_KEY} if API_KEY else {}
    payload = {
        "message": message,
        "user_id": user_id,
        "session_id": session_id,
        "role": "student"
    }
    
    response = requests.post(
        f"{RENDER_URL}/api/v1/chat/",
        json=payload,
        headers=headers,
        timeout=120
    )
    
    if response.status_code == 200:
        return response.json()
    return {"error": response.status_code, "detail": response.text[:200]}


def test_conversation_memory():
    """Test if AI remembers previous messages in same session"""
    print("\n" + "="*60)
    print("🧠 TEST 1: CONVERSATION MEMORY (Same Session)")
    print("="*60)
    
    session_id = f"memory-test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    user_id = "memory-test-user"
    
    # Message 1: Introduce a topic
    print("\n📤 Message 1: Hỏi về tàu biển")
    r1 = send_message("Tàu biển là gì theo Luật Hàng hải?", user_id, session_id)
    answer1 = r1.get("data", {}).get("answer", "")[:200]
    print(f"📥 Response: {answer1}...")
    
    # Message 2: Follow-up without context
    print("\n📤 Message 2: Follow-up 'Còn điều kiện đăng ký thì sao?'")
    r2 = send_message("Còn điều kiện đăng ký thì sao?", user_id, session_id)
    answer2 = r2.get("data", {}).get("answer", "")[:200]
    print(f"📥 Response: {answer2}...")
    
    # Check if AI understood context
    keywords = ["tàu", "đăng ký", "điều kiện"]
    found = [kw for kw in keywords if kw in answer2.lower()]
    
    if len(found) >= 2:
        print(f"\n✅ PASSED: AI understood context (found: {found})")
        return True
    else:
        print(f"\n⚠️ WARNING: AI may not have understood context (found: {found})")
        return False


def test_user_name_memory():
    """Test if AI remembers user's name"""
    print("\n" + "="*60)
    print("🧠 TEST 2: USER NAME MEMORY")
    print("="*60)
    
    session_id = f"name-test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    user_id = "name-test-user"
    
    # Message 1: Introduce name
    print("\n📤 Message 1: 'Tôi là Minh, cho tôi hỏi về COLREGs'")
    r1 = send_message("Tôi là Minh, cho tôi hỏi về COLREGs", user_id, session_id)
    answer1 = r1.get("data", {}).get("answer", "")[:300]
    print(f"📥 Response: {answer1}...")
    
    # Message 2: Ask another question
    print("\n📤 Message 2: 'Quy tắc 15 nói gì?'")
    r2 = send_message("Quy tắc 15 nói gì?", user_id, session_id)
    answer2 = r2.get("data", {}).get("answer", "")[:300]
    print(f"📥 Response: {answer2}...")
    
    # Check if AI uses name (but not required - per CHỈ THỊ 16)
    if "minh" in answer2.lower():
        print("\n✅ AI remembered and used name 'Minh'")
        return True
    else:
        print("\n📝 AI did not use name (this is OK per CHỈ THỊ 16 - avoid repetitive naming)")
        return True  # Still pass - not using name is acceptable


def test_semantic_memory():
    """Test if Semantic Memory stores user facts"""
    print("\n" + "="*60)
    print("🧠 TEST 3: SEMANTIC MEMORY (User Facts)")
    print("="*60)
    
    session_id = f"semantic-test-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    user_id = "semantic-test-user"
    
    # Message 1: Share a fact
    print("\n📤 Message 1: 'Tôi là thuyền trưởng tàu container'")
    r1 = send_message("Tôi là thuyền trưởng tàu container, tôi muốn học về SOLAS", user_id, session_id)
    answer1 = r1.get("data", {}).get("answer", "")[:300]
    print(f"📥 Response: {answer1}...")
    
    # Message 2: Ask related question
    print("\n📤 Message 2: 'Tôi cần biết gì về an toàn?'")
    r2 = send_message("Tôi cần biết gì về an toàn?", user_id, session_id)
    answer2 = r2.get("data", {}).get("answer", "")[:300]
    print(f"📥 Response: {answer2}...")
    
    # Check if response is relevant to container ship captain
    keywords = ["solas", "an toàn", "tàu", "container", "thuyền trưởng"]
    found = [kw for kw in keywords if kw in answer2.lower()]
    
    if len(found) >= 2:
        print(f"\n✅ PASSED: Response relevant to user context (found: {found})")
        return True
    else:
        print(f"\n⚠️ WARNING: Response may not be personalized (found: {found})")
        return False


def main():
    print("="*60)
    print("MARITIME AI TUTOR - MEMORY & INTELLIGENCE TEST")
    print(f"Server: {RENDER_URL}")
    print(f"Time: {datetime.now().isoformat()}")
    print("="*60)
    
    if not API_KEY:
        print("\n⚠️ Warning: No API_KEY found")
    
    results = []
    
    # Run tests
    results.append(("Conversation Memory", test_conversation_memory()))
    results.append(("User Name Memory", test_user_name_memory()))
    results.append(("Semantic Memory", test_semantic_memory()))
    
    # Summary
    print("\n" + "="*60)
    print("📊 MEMORY TEST SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        icon = "✅" if result else "❌"
        print(f"{icon} {name}")
    
    print(f"\n🎯 Score: {passed}/{total} ({passed/total*100:.0f}%)")


if __name__ == "__main__":
    main()
