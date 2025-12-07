"""Test FastAPI chat endpoint with Humanization & Stability features."""
import requests
import json

def test_chat_api():
    """Test chat API endpoint."""
    base_url = "http://localhost:8000"
    
    print("=== Testing FastAPI Chat Endpoint ===")
    print()
    
    # Test 1: Health check
    print("1. Health Check...")
    try:
        response = requests.get(f"{base_url}/health", timeout=10)
        print(f"   Status: {response.status_code}")
        print(f"   Response: {response.json()}")
    except Exception as e:
        print(f"   Error: {e}")
    print()
    
    # Test 2: User introduction
    print("2. User Introduction...")
    import time
    test_user = f"test_user_{int(time.time())}"
    chat_data = {
        "message": "Xin chào, tôi là Hùng, tôi là sinh viên hàng hải năm 3",
        "user_id": test_user,
        "role": "student"
    }
    headers = {"X-API-Key": "test-api-key-123"}
    
    try:
        response = requests.post(f"{base_url}/api/v1/chat", json=chat_data, headers=headers, timeout=60)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            # Handle nested response structure
            data = result.get('data', result)
            message = data.get('answer', data.get('message', '')) if isinstance(data, dict) else ''
            sources = data.get('sources', []) if isinstance(data, dict) else []
            metadata = result.get('metadata', {})
            print(f"   Message: {message[:200] if message else '(empty)'}...")
            print(f"   Sources: {len(sources)} sources")
            print(f"   Metadata: {metadata}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Error: {e}")
    print()
    
    # Test 3: Knowledge question
    print("3. Knowledge Question...")
    chat_data = {
        "message": "Quy tắc 15 COLREGs về tình huống cắt hướng là gì?",
        "user_id": test_user,
        "role": "student"
    }
    
    try:
        response = requests.post(f"{base_url}/api/v1/chat", json=chat_data, headers=headers, timeout=60)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            data = result.get('data', result)
            message = data.get('answer', data.get('message', '')) if isinstance(data, dict) else ''
            sources = data.get('sources', []) if isinstance(data, dict) else []
            print(f"   Message: {message[:200] if message else '(empty)'}...")
            print(f"   Sources: {len(sources)} sources")
            
            # Check if tools were used
            metadata = result.get('metadata', {})
            tools_used = metadata.get('tools_used', [])
            print(f"   Tools used: {len(tools_used)} tools")
            for tool in tools_used:
                print(f"     - {tool.get('name', 'unknown')}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Error: {e}")
    print()
    
    # Test 4: Empathy response
    print("4. Empathy Response...")
    chat_data = {
        "message": "Tôi thấy mệt quá, học nhiều quá rồi",
        "user_id": test_user,
        "role": "student"
    }
    
    try:
        response = requests.post(f"{base_url}/api/v1/chat", json=chat_data, headers=headers, timeout=60)
        print(f"   Status: {response.status_code}")
        if response.status_code == 200:
            result = response.json()
            data = result.get('data', result)
            message = data.get('answer', data.get('message', '')) if isinstance(data, dict) else ''
            print(f"   Message: {message[:200] if message else '(empty)'}...")
            
            # Check for empathy indicators
            empathy_words = ['hiểu', 'mệt', 'nghỉ', 'thôi', 'cố gắng']
            found_empathy = [w for w in empathy_words if w in message.lower()]
            print(f"   Empathy indicators: {found_empathy}")
        else:
            print(f"   Error: {response.text}")
    except Exception as e:
        print(f"   Error: {e}")
    
    print("\n=== FastAPI Test Complete ===")

if __name__ == "__main__":
    test_chat_api()
