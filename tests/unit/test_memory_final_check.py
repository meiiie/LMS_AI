"""
Final Memory Check - Verify facts are being stored via chat
"""
import asyncio
import httpx
import os
import uuid
from dotenv import load_dotenv

load_dotenv()

BASE_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = os.getenv("LMS_API_KEY", "secret_key_cho_team_lms")

HEADERS = {
    "X-API-Key": API_KEY,
    "Content-Type": "application/json"
}

async def test_chat_and_verify_facts():
    """Test chat then verify facts are stored"""
    print("\n" + "="*60)
    print("FINAL MEMORY CHECK")
    print("="*60)
    
    # Generate unique user
    user_id = f"final_test_{uuid.uuid4().hex[:8]}"
    session_id = f"session_{uuid.uuid4().hex[:8]}"
    
    print(f"User ID: {user_id}")
    print(f"Session ID: {session_id}")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        # Step 1: Check initial state (should be 0 facts)
        print("\n--- Step 1: Initial State ---")
        response = await client.get(
            f"{BASE_URL}/api/v1/memories/{user_id}",
            headers=HEADERS
        )
        data = response.json()
        print(f"Initial facts: {data.get('total', 0)}")
        
        # Step 2: Send chat message with personal info
        print("\n--- Step 2: Send Chat Message ---")
        message = "Xin chào! Tôi là Trần Văn Bình, thuyền trưởng tàu container, đang muốn ôn lại COLREGs"
        
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
            ai_response = response.json().get("data", {}).get("answer", "")[:100]
            print(f"AI Response: {ai_response}...")
            print("✅ Chat successful")
        else:
            print(f"❌ Chat failed: {response.status_code}")
            print(f"   Error: {response.text[:200]}")
            return
        
        # Step 3: Wait for background task to complete
        print("\n--- Step 3: Waiting for background task (10s) ---")
        await asyncio.sleep(10)
        
        # Step 4: Check facts after chat
        print("\n--- Step 4: Check Facts After Chat ---")
        response = await client.get(
            f"{BASE_URL}/api/v1/memories/{user_id}",
            headers=HEADERS
        )
        data = response.json()
        total = data.get('total', 0)
        facts = data.get('data', [])
        
        print(f"Total facts: {total}")
        
        if total > 0:
            print("✅ Facts were extracted and stored!")
            print("\nExtracted Facts:")
            for fact in facts:
                print(f"  - [{fact.get('type')}] {fact.get('value')}")
        else:
            print("❌ No facts stored - background task may have failed")
            print("\nPossible issues:")
            print("  1. Background task not running")
            print("  2. LLM extraction failed")
            print("  3. Fact type validation rejected all facts")
        
        # Step 5: Send another message and check again
        print("\n--- Step 5: Send Another Message ---")
        message2 = "Tôi đặc biệt quan tâm đến Rule 15 về tình huống cắt hướng"
        
        response = await client.post(
            f"{BASE_URL}/api/v1/chat",
            headers=HEADERS,
            json={
                "message": message2,
                "user_id": user_id,
                "session_id": session_id,
                "role": "student"
            }
        )
        
        if response.status_code == 200:
            print("✅ Second message sent")
        
        # Wait and check again
        print("\n--- Step 6: Final Check (after 10s) ---")
        await asyncio.sleep(10)
        
        response = await client.get(
            f"{BASE_URL}/api/v1/memories/{user_id}",
            headers=HEADERS
        )
        data = response.json()
        total = data.get('total', 0)
        facts = data.get('data', [])
        
        print(f"Final total facts: {total}")
        if facts:
            print("\nAll Facts:")
            for fact in facts:
                print(f"  - [{fact.get('type')}] {fact.get('value')}")

async def main():
    await test_chat_and_verify_facts()

if __name__ == "__main__":
    asyncio.run(main())
