"""
Test Maritime AI Chatbot API on Render
CHỈ THỊ KỸ THUẬT SỐ 06

Test the deployed API at https://maritime-ai-chatbot.onrender.com
"""
import asyncio
import httpx
from uuid import uuid4


# Render API URL
BASE_URL = "https://maritime-ai-chatbot.onrender.com"
# Local API URL (for local testing)
LOCAL_URL = "http://localhost:8000"


async def test_health(base_url: str):
    """Test health endpoint."""
    print(f"\n[1] Testing Health Endpoint: {base_url}/api/v1/health")
    print("-" * 50)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(f"{base_url}/api/v1/health")
            print(f"Status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"✅ Health: {data.get('status', 'unknown')}")
                print(f"   Version: {data.get('version', 'unknown')}")
                print(f"   Environment: {data.get('environment', 'unknown')}")
                if 'components' in data:
                    for name, comp in data['components'].items():
                        status = comp.get('status', 'unknown')
                        print(f"   - {name}: {status}")
                return True
            else:
                print(f"❌ Error: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Connection failed: {e}")
            return False


async def test_chat(base_url: str, message: str, user_id: str = None):
    """Test chat endpoint."""
    user_id = user_id or f"test_user_{uuid4().hex[:8]}"
    
    print(f"\n[CHAT] User: {message[:50]}...")
    print("-" * 50)
    
    payload = {
        "user_id": user_id,
        "message": message,
        "role": "student",
        "context": {"course_id": "COLREGs_101"}
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": "test-api-key-123"  # Default API key
    }
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{base_url}/api/v1/chat",
                json=payload,
                headers=headers
            )
            
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if data.get('status') == 'success':
                    answer = data.get('data', {}).get('answer', 'No answer')
                    # Truncate for display
                    answer_preview = answer[:300] + "..." if len(answer) > 300 else answer
                    print(f"✅ AI: {answer_preview}")
                    
                    # Show sources
                    sources = data.get('data', {}).get('sources', [])
                    if sources:
                        print(f"\n   Sources ({len(sources)}):")
                        for src in sources[:3]:
                            print(f"   - {src.get('title', 'Unknown')}")
                    
                    # Show suggested questions
                    suggestions = data.get('data', {}).get('suggested_questions', [])
                    if suggestions:
                        print(f"\n   Suggested questions:")
                        for q in suggestions[:3]:
                            print(f"   - {q}")
                    
                    return True
                else:
                    print(f"❌ Error: {data}")
                    return False
            else:
                print(f"❌ Error {response.status_code}: {response.text[:200]}")
                return False
                
        except Exception as e:
            print(f"❌ Request failed: {e}")
            return False


async def main():
    """Run all tests."""
    print("=" * 60)
    print("MARITIME AI CHATBOT - API TEST")
    print("CHỈ THỊ KỸ THUẬT SỐ 06")
    print("=" * 60)
    
    # Choose URL
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--local":
        base_url = LOCAL_URL
        print(f"\n🔧 Testing LOCAL: {base_url}")
    else:
        base_url = BASE_URL
        print(f"\n🌐 Testing RENDER: {base_url}")
    
    # Test health
    health_ok = await test_health(base_url)
    
    if not health_ok:
        print("\n⚠️ Health check failed. Server may be starting up...")
        print("   Render free tier may take 30-60 seconds to wake up.")
        return
    
    # Test user ID for conversation continuity
    user_id = f"test_e2e_{uuid4().hex[:8]}"
    print(f"\n[INFO] Test User ID: {user_id}")
    
    # Test conversations
    test_messages = [
        "Xin chào, tôi là Minh, tôi là sinh viên hàng hải năm 3",
        "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng",
        "Khi hai tàu cắt hướng nhau, tàu nào phải nhường đường?",
        "Còn quy tắc 13 về tàu vượt thì sao?",
    ]
    
    print("\n" + "=" * 60)
    print("CHAT CONVERSATION TEST")
    print("=" * 60)
    
    success_count = 0
    for msg in test_messages:
        if await test_chat(base_url, msg, user_id):
            success_count += 1
        await asyncio.sleep(1)  # Small delay between requests
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Health Check: {'✅ PASS' if health_ok else '❌ FAIL'}")
    print(f"Chat Tests: {success_count}/{len(test_messages)} passed")
    
    if health_ok and success_count == len(test_messages):
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print("\n⚠️ Some tests failed. Check the output above.")


if __name__ == "__main__":
    asyncio.run(main())
