"""Test delete chat history API."""
import requests
import json

BASE_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = "secret_key_cho_team_lms"

def test_delete_history():
    """Test delete history API with different scenarios."""
    
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    
    test_cases = [
        {
            "name": "Admin deletes any user's history",
            "user_id": "test_user_123",
            "payload": {
                "role": "admin",
                "requesting_user_id": "admin_user"
            },
            "expected_status": 200
        },
        {
            "name": "User deletes own history",
            "user_id": "student_456",
            "payload": {
                "role": "student",
                "requesting_user_id": "student_456"
            },
            "expected_status": 200
        },
        {
            "name": "User tries to delete another user's history (should fail)",
            "user_id": "other_user_789",
            "payload": {
                "role": "student",
                "requesting_user_id": "student_456"
            },
            "expected_status": 403
        },
        {
            "name": "Invalid role (should fail)",
            "user_id": "test_user_123",
            "payload": {
                "role": "invalid_role",
                "requesting_user_id": "test_user"
            },
            "expected_status": 403
        }
    ]
    
    print("=" * 60)
    print("TESTING DELETE CHAT HISTORY API")
    print("=" * 60)
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\n{i}. {test_case['name']}")
        print("-" * 40)
        
        try:
            response = requests.delete(
                f"{BASE_URL}/api/v1/chat/history/{test_case['user_id']}",
                json=test_case["payload"],
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
                print(f"Response: {json.dumps(response_data, indent=2)}")
            except:
                print(f"Response: {response.text}")
                
        except Exception as e:
            print(f"❌ ERROR: {e}")
    
    print("\n" + "=" * 60)
    print("DELETE HISTORY API TEST COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    test_delete_history()
