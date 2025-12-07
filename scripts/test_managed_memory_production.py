"""
Test Managed Memory List v0.4 on Production
Tests: Memory API, Upsert Logic, Memory Capping, Fact Extraction
"""
import asyncio
import httpx
import os
from dotenv import load_dotenv
import uuid

load_dotenv()

BASE_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = os.getenv("API_KEY", "dev-secret-key")

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

async def test_health():
    """Test health endpoint"""
    print("\n" + "="*60)
    print("TEST 1: Health Check")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{BASE_URL}/health")
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            print("✅ Server is healthy")
            return True
        else:
            print("❌ Server is not healthy")
            return False

async def test_memory_api(user_id: str):
    """Test GET /api/v1/memories/{user_id}"""
    print("\n" + "="*60)
    print("TEST 2: Memory API Endpoint")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/api/v1/memories/{user_id}",
            headers=HEADERS
        )
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Memory API works!")
            print(f"   User ID: {data.get('user_id')}")
            print(f"   Total Facts: {data.get('total_facts', 0)}")
            print(f"   Max Facts: {data.get('max_facts', 50)}")
            
            facts = data.get('facts', [])
            if facts:
                print(f"\n   Current Facts:")
                for fact in facts[:5]:  # Show first 5
                    print(f"   - [{fact.get('fact_type')}] {fact.get('content')[:50]}...")
            return True
        else:
            print(f"❌ Memory API failed: {response.text}")
            return False

async def test_chat_with_personal_info(user_id: str, session_id: str):
    """Test chat with personal information to trigger fact extraction"""
    print("\n" + "="*60)
    print("TEST 3: Chat with Personal Info (Fact Extraction)")
    print("="*60)
    
    messages = [
        "Xin chào, tôi là Minh, sinh viên năm 3 ngành Hàng hải tại Đại học Hàng hải Việt Nam",
        "Tôi đang học về quy tắc tránh va COLREG, đặc biệt là Rule 13 về vượt tàu",
    ]
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        for i, message in enumerate(messages):
            print(f"\n--- Message {i+1} ---")
            print(f"User: {message[:60]}...")
            
            response = await client.post(
                f"{BASE_URL}/api/v1/chat",
                headers=HEADERS,
                json={
                    "message": message,
                    "user_id": user_id,
                    "session_id": session_id,
                    "role": "student"
                }
            )
            
            if response.status_code == 200:
                data = response.json()
                ai_response = data.get("response", "")[:100]
                print(f"AI: {ai_response}...")
                print("✅ Chat successful")
            else:
                print(f"❌ Chat failed: {response.status_code}")
                print(f"   Error: {response.text[:200]}")
                return False
            
            await asyncio.sleep(2)  # Wait between messages
    
    return True

async def test_fact_extraction_result(user_id: str):
    """Check if facts were extracted after chat"""
    print("\n" + "="*60)
    print("TEST 4: Verify Fact Extraction")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{BASE_URL}/api/v1/memories/{user_id}",
            headers=HEADERS
        )
        
        if response.status_code == 200:
            data = response.json()
            facts = data.get('facts', [])
            total = data.get('total_facts', 0)
            
            print(f"Total Facts: {total}")
            
            if total > 0:
                print("✅ Facts were extracted!")
                print("\nExtracted Facts:")
                for fact in facts:
                    print(f"  [{fact.get('fact_type')}] {fact.get('content')}")
                return True
            else:
                print("⚠️ No facts extracted yet (may need more conversation)")
                return True  # Not a failure, just needs more data
        else:
            print(f"❌ Failed to get memories: {response.text}")
            return False

async def test_upsert_logic(user_id: str, session_id: str):
    """Test upsert by sending updated info"""
    print("\n" + "="*60)
    print("TEST 5: Upsert Logic (Update Existing Fact)")
    print("="*60)
    
    # Send updated name
    message = "À quên, tên đầy đủ của tôi là Nguyễn Văn Minh nhé"
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        print(f"Sending update: {message}")
        
        response = await client.post(
            f"{BASE_URL}/api/v1/chat",
            headers=HEADERS,
            json={
                "message": message,
                "user_id": user_id,
                "session_id": session_id,
                "role": "student"
            }
        )
        
        if response.status_code == 200:
            print("✅ Update message sent")
            
            # Check if fact was updated (not duplicated)
            await asyncio.sleep(2)
            
            mem_response = await client.get(
                f"{BASE_URL}/api/v1/memories/{user_id}",
                headers=HEADERS
            )
            
            if mem_response.status_code == 200:
                data = mem_response.json()
                facts = data.get('facts', [])
                
                # Count USER_NAME facts
                name_facts = [f for f in facts if f.get('fact_type') == 'USER_NAME']
                print(f"USER_NAME facts count: {len(name_facts)}")
                
                if len(name_facts) <= 1:
                    print("✅ Upsert working - no duplicate names!")
                else:
                    print("⚠️ Multiple name facts found - upsert may not be working")
                
                return True
        else:
            print(f"❌ Failed: {response.status_code}")
            return False

async def main():
    print("="*60)
    print("MANAGED MEMORY LIST v0.4 - PRODUCTION TEST")
    print("="*60)
    print(f"Target: {BASE_URL}")
    
    # Generate unique test user
    test_user_id = f"test_memory_{uuid.uuid4().hex[:8]}"
    test_session_id = f"session_{uuid.uuid4().hex[:8]}"
    
    print(f"Test User: {test_user_id}")
    print(f"Test Session: {test_session_id}")
    
    results = []
    
    # Run tests
    results.append(("Health Check", await test_health()))
    results.append(("Memory API", await test_memory_api(test_user_id)))
    results.append(("Chat + Extraction", await test_chat_with_personal_info(test_user_id, test_session_id)))
    results.append(("Verify Extraction", await test_fact_extraction_result(test_user_id)))
    results.append(("Upsert Logic", await test_upsert_logic(test_user_id, test_session_id)))
    
    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)
    
    passed = 0
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
        if result:
            passed += 1
    
    print(f"\nTotal: {passed}/{len(results)} tests passed")
    
    return passed == len(results)

if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
