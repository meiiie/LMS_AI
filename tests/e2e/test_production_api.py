"""
Production API Test Script for Maritime AI Service on Render.

Tests all major endpoints to verify production deployment.
"""

import httpx
import json
import time
from datetime import datetime

# Production URL
BASE_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = "secret_key_cho_team_lms"  # From .env.render

def test_health():
    """Test health endpoint."""
    print("\n" + "="*60)
    print("1. HEALTH CHECK")
    print("="*60)
    
    try:
        response = httpx.get(f"{BASE_URL}/health", timeout=30)
        print(f"Status: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_knowledge_stats():
    """Test knowledge stats endpoint."""
    print("\n" + "="*60)
    print("2. KNOWLEDGE STATS")
    print("="*60)
    
    try:
        response = httpx.get(f"{BASE_URL}/api/v1/knowledge/stats", timeout=30)
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Response: {json.dumps(data, indent=2)}")
        
        # Check for warning field
        if data.get("warning"):
            print(f"⚠️ Warning: {data['warning']}")
        else:
            print(f"✅ No warnings - DB connection OK")
        
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_knowledge_list():
    """Test knowledge list endpoint."""
    print("\n" + "="*60)
    print("3. KNOWLEDGE LIST")
    print("="*60)
    
    try:
        response = httpx.get(f"{BASE_URL}/api/v1/knowledge/list", timeout=30)
        print(f"Status: {response.status_code}")
        data = response.json()
        print(f"Documents count: {len(data.get('documents', []))}")
        
        if data.get("warning"):
            print(f"⚠️ Warning: {data['warning']}")
        else:
            print(f"✅ No warnings - DB connection OK")
        
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_chat_api():
    """Test chat API with a maritime question."""
    print("\n" + "="*60)
    print("4. CHAT API (RAG Query)")
    print("="*60)
    
    payload = {
        "user_id": "test_user_production",
        "message": "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng",
        "role": "student",
        "session_id": f"test_session_{int(time.time())}"
    }
    
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": API_KEY
    }
    
    try:
        print(f"Query: {payload['message']}")
        print("Waiting for response (may take 10-30s)...")
        
        response = httpx.post(
            f"{BASE_URL}/api/v1/chat",
            json=payload,
            headers=headers,
            timeout=60
        )
        
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n📝 Answer preview: {data.get('data', {}).get('answer', '')[:200]}...")
            
            sources = data.get('data', {}).get('sources', [])
            print(f"\n📚 Sources: {len(sources)}")
            for i, src in enumerate(sources[:3], 1):
                print(f"  {i}. {src.get('title', 'N/A')}")
            
            suggestions = data.get('data', {}).get('suggested_questions', [])
            print(f"\n💡 Suggestions: {len(suggestions)}")
            for i, q in enumerate(suggestions[:3], 1):
                print(f"  {i}. {q}")
            
            metadata = data.get('metadata', {})
            print(f"\n⚙️ Agent: {metadata.get('agent_type', 'N/A')}")
            print(f"⏱️ Processing time: {metadata.get('processing_time', 'N/A')}s")
            
            return True
        else:
            print(f"Error response: {response.text}")
            return False
            
    except Exception as e:
        print(f"Error: {e}")
        return False

def main():
    """Run all tests."""
    print("\n" + "="*60)
    print(f"MARITIME AI PRODUCTION TEST - {datetime.now()}")
    print(f"URL: {BASE_URL}")
    print("="*60)
    
    results = {
        "health": test_health(),
        "knowledge_stats": test_knowledge_stats(),
        "knowledge_list": test_knowledge_list(),
        "chat_api": test_chat_api()
    }
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
