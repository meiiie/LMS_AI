"""
Deep check Memory System on Production
Kiểm tra chi tiết xem facts có được extract và lưu không
"""
import asyncio
import httpx
import os
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = os.getenv("LMS_API_KEY", "secret_key_cho_team_lms")

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

async def check_existing_users():
    """Check memories for existing users"""
    print("\n" + "="*60)
    print("CHECK EXISTING USERS' MEMORIES")
    print("="*60)
    
    # Test với user_id đã có facts
    test_users = [
        "memory_test_detailed",
        "test_memory_490bd867",
        "production_test_001"
    ]
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        for user_id in test_users:
            response = await client.get(
                f"{BASE_URL}/api/v1/memories/{user_id}",
                headers=HEADERS
            )
            
            print(f"\n{user_id}:")
            print(f"  Status: {response.status_code}")
            print(f"  Response: {response.text[:300]}...")
            
            if response.status_code == 200:
                data = response.json()
                # Check both possible response formats
                total = data.get('total_facts', data.get('total', 0))
                print(f"  Total: {total}")
                
                facts = data.get('facts', data.get('data', []))
                for fact in facts[:3]:
                    print(f"  - [{fact.get('fact_type', fact.get('type'))}] {fact.get('content', fact.get('value', ''))[:50]}...")

async def test_fact_extraction_detailed():
    """Test fact extraction với logging chi tiết"""
    print("\n" + "="*60)
    print("DETAILED FACT EXTRACTION TEST")
    print("="*60)
    
    user_id = "memory_test_detailed"
    session_id = "session_detailed_001"
    
    messages = [
        "Xin chào! Tôi tên là Nguyễn Văn An, sinh viên năm 4 ngành Điều khiển tàu biển",
        "Tôi đang chuẩn bị thi bằng thuyền trưởng hạng 3, cần ôn lại COLREGs",
        "Sở thích của tôi là đọc sách về hàng hải và chơi cờ vua"
    ]
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i, message in enumerate(messages):
            print(f"\n--- Sending message {i+1} ---")
            print(f"Message: {message}")
            
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
                answer = data.get("data", {}).get("answer", "")[:150]
                print(f"AI Response: {answer}...")
                print("✅ Message sent successfully")
            else:
                print(f"❌ Failed: {response.status_code} - {response.text[:200]}")
            
            await asyncio.sleep(3)  # Wait for processing
        
        # Check memories after conversation
        print("\n--- Checking memories after conversation ---")
        await asyncio.sleep(5)  # Extra wait for async processing
        
        mem_response = await client.get(
            f"{BASE_URL}/api/v1/memories/{user_id}",
            headers=HEADERS
        )
        
        if mem_response.status_code == 200:
            data = mem_response.json()
            total = data.get('total_facts', 0)
            print(f"\nTotal Facts Extracted: {total}")
            
            facts = data.get('facts', [])
            if facts:
                print("\nExtracted Facts:")
                for fact in facts:
                    print(f"  [{fact.get('fact_type')}] {fact.get('content')}")
                    print(f"    Created: {fact.get('created_at')}")
            else:
                print("⚠️ No facts found - checking if extraction is working...")
                
                # Check if semantic memory is available
                health_response = await client.get(f"{BASE_URL}/api/v1/health/detailed")
                if health_response.status_code == 200:
                    health = health_response.json()
                    print(f"\nHealth check: {health}")

async def main():
    print("="*60)
    print("MEMORY SYSTEM DEEP CHECK")
    print("="*60)
    
    await check_existing_users()
    await test_fact_extraction_detailed()

if __name__ == "__main__":
    asyncio.run(main())
