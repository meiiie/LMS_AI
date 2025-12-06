# -*- coding: utf-8 -*-
"""Test Anti-Repetition specifically for sequential rules."""
import requests
import time
import sys
import io

# Fix encoding for Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def test_anti_repetition():
    """Test that AI doesn't start with Vietnamese 'À' repeatedly."""
    base_url = "http://localhost:8000"
    test_user = f"test_anti_rep_{int(time.time())}"
    headers = {"X-API-Key": "test-api-key-123"}
    
    print("=== Testing Anti-Repetition for Sequential Rules ===")
    print()
    
    # Sequential rule questions
    questions = [
        "Quy tac 5 ve quan sat la gi?",
        "Quy tac 6 ve toc do an toan thi sao?", 
        "Con quy tac 7 ve nguy co va cham?",
        "Quy tac 8 ve hanh dong tranh va cham?",
        "Quy tac 9 ve luong hep?"
    ]
    
    responses = []
    openings = []
    a_count = 0
    
    for i, question in enumerate(questions, 1):
        print(f"{i}. {question}")
        
        chat_data = {
            "message": question,
            "user_id": test_user,
            "role": "student"
        }
        
        try:
            response = requests.post(f"{base_url}/api/v1/chat", json=chat_data, headers=headers, timeout=60)
            if response.status_code == 200:
                result = response.json()
                data = result.get('data', result)
                message = data.get('answer', data.get('message', '')) if isinstance(data, dict) else ''
                
                # Extract first 50 characters as opening
                opening = message[:50] if message else ''
                openings.append(opening)
                responses.append(message)
                
                print(f"   Opening: {opening}...")
                
                # Check for Vietnamese 'À,' or 'À ' at the beginning
                msg_stripped = message.strip()
                starts_with_a = (
                    msg_stripped.startswith('À,') or 
                    msg_stripped.startswith('À ') or
                    msg_stripped.startswith('À,') or  # Different Unicode representation
                    msg_stripped.startswith('A,') or
                    msg_stripped.startswith('A ')
                )
                if starts_with_a:
                    a_count += 1
                    print(f"   Starts with 'À': ❌ YES")
                else:
                    print(f"   Starts with 'À': ✅ NO")
                
            else:
                print(f"   Error: {response.status_code} - {response.text}")
                openings.append("ERROR")
                
        except Exception as e:
            print(f"   Error: {e}")
            openings.append("ERROR")
        
        print()
    
    # Analysis
    print("=== ANALYSIS ===")
    print(f"Total questions: {len(questions)}")
    print(f"Responses starting with 'À': {a_count}/{len(responses)} ({a_count/len(responses)*100:.1f}%)")
    
    # Check uniqueness
    unique_openings = len(set(openings))
    print(f"Unique openings: {unique_openings}/{len(openings)} ({unique_openings/len(openings)*100:.1f}%)")
    
    # Show all openings
    print("\nAll openings:")
    for i, opening in enumerate(openings, 1):
        print(f"  {i}. {opening}...")
    
    # Success criteria: max 1 response starting with 'À'
    success = a_count <= 1 and unique_openings >= len(openings) - 1
    print(f"\n{'🎉 SUCCESS' if success else '❌ FAILED'}: Anti-repetition test")
    print(f"   Criteria: Max 1 response starting with 'À', got {a_count}")
    
    return success

if __name__ == "__main__":
    test_anti_repetition()
