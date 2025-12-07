"""Test GET chat history API (CHỈ THỊ KỸ THUẬT SỐ 11)."""
import requests
import json

BASE_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = "secret_key_cho_team_lms"

def test_get_history():
    """Test GET history API with different scenarios."""
    
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    
    test_cases = [
        {
            "name": "Get history with default pagination",
            "user_id": "test_user_123",
            "params": {},
            "expected_status": 200
        },
        {
            "name": "Get history with custom limit",
            "user_id": "test_user_123",
            "params": {"limit": 10},
            "expected_status": 200
        },
        {
            "name": "Get history with offset",
            "user_id": "test_user_123",
            "params": {"limit": 5, "offset": 5},
            "expected_status": 200
        },
        {
            "name": "Get history with max limit (100)",
            "user_id": "test_user_123",
            "params": {"limit": 100},
            "expected_status": 200
        },
        {
            "name": "Get history - limit exceeds max (should cap at 100)",
            "user_id": "test_user_123",
            "params": {"limit": 200},
            "expected_status": 200
        }
    ]
    
    print("=" * 60)
    print("TESTING GET CHAT HISTORY API (CHỈ THỊ SỐ 11)")
    print("=" * 60)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. {test_case['name']}")
        print("-" * 40)
        
        try:
            response = requests.get(
                f"{BASE_URL}/api/v1/history/{test_case['user_id']}",
                params=test_case["params"],
                headers=headers,
                timeout=30
            )
            
            print(f"Status: {response.status_code}")
            print(f"Expected: {test_case['expected_status']}")
            
            if response.status_code == test_case["expected_status"]:
                print("✅ PASS")
            else:
                print("❌ FAIL")
            
            # Print response
            try:
                response_data = response.json()
                # Truncate data for display
                if "data" in response_data and len(response_data["data"]) > 2:
                    display_data = {
                        "data": response_data["data"][:2] + ["..."],
                        "pagination": response_data.get("pagination", {})
                    }
                else:
                    display_data = response_data
                print(f"Response: {json.dumps(display_data, indent=2, default=str)}")
            except:
                print(f"Response: {response.text[:200]}")
                
        except Exception as e:
            print(f"❌ ERROR: {e}")
    
    print("\n" + "=" * 60)
    print("GET HISTORY API TEST COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    test_get_history()
