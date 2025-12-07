"""
Test Manual Chat API - Maritime AI Tutor
Verify citations, sources, and suggested questions
"""
import requests
import json

# API_URL = 'https://maritime-ai-service.onrender.com/api/v1/chat'
API_URL = 'http://localhost:8000/api/v1/chat'  # Local testing

def test_chat(message: str, role: str = "student"):
    """Test chat API with a message"""
    payload = {
        'user_id': 'test_user_manual',
        'message': message,
        'role': role,
        'session_id': 'manual_test_session_v2'
    }
    
    import os
    from dotenv import load_dotenv
    load_dotenv()
    api_key = os.getenv('API_KEY', 'test-api-key-123')
    
    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': api_key
    }
    
    print("=" * 70)
    print(f"QUERY: {message}")
    print(f"ROLE: {role}")
    print("-" * 70)
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=90)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            data = response.json()
            
            # Agent info
            agent_type = data.get("metadata", {}).get("agent_type", "N/A")
            proc_time = data.get("metadata", {}).get("processing_time", "N/A")
            print(f"\nAgent Type: {agent_type}")
            print(f"Processing Time: {proc_time}s")
            
            # Answer
            answer = data.get('data', {}).get('answer', 'N/A')
            print(f"\n{'='*20} ANSWER {'='*20}")
            if len(answer) > 600:
                print(answer[:600] + "...")
            else:
                print(answer)
            
            # Sources/Citations
            sources = data.get('data', {}).get('sources', [])
            print(f"\n{'='*20} SOURCES ({len(sources)}) {'='*20}")
            if sources:
                for i, src in enumerate(sources[:5], 1):
                    title = src.get("title", "N/A")
                    src_type = src.get("type", "N/A")
                    snippet = src.get("snippet", "")[:80] if src.get("snippet") else ""
                    print(f"  {i}. {title}")
                    print(f"     Type: {src_type}")
                    if snippet:
                        print(f"     Snippet: {snippet}...")
            else:
                print("  (No sources returned)")
            
            # Suggested Questions
            suggestions = data.get('data', {}).get('suggested_questions', [])
            print(f"\n{'='*20} SUGGESTIONS ({len(suggestions)}) {'='*20}")
            if suggestions:
                for i, q in enumerate(suggestions[:3], 1):
                    print(f"  {i}. {q}")
            else:
                print("  (No suggestions)")
            
            # Full metadata
            print(f"\n{'='*20} METADATA {'='*20}")
            metadata = data.get('metadata', {})
            for k, v in metadata.items():
                print(f"  {k}: {v}")
                
            return data
        else:
            print(f"Error: {response.text}")
            return None
    except Exception as e:
        print(f"Exception: {e}")
        return None


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("MARITIME AI TUTOR - MANUAL API TEST")
    print("=" * 70)
    
    # Test 1: COLREGs question (should trigger RAG)
    print("\n\n[TEST 1] COLREGs Question - Rule 15")
    test_chat("Giải thích quy tắc 15 COLREGs về tình huống cắt hướng")
    
    # Test 2: General maritime question
    print("\n\n[TEST 2] General Maritime Question")
    test_chat("Tàu nào phải nhường đường khi hai tàu cắt hướng nhau?")
    
    # Test 3: Vietnamese Maritime Law
    print("\n\n[TEST 3] Vietnamese Maritime Law")
    test_chat("Quy định về đăng ký tàu biển Việt Nam")
    
    print("\n\n" + "=" * 70)
    print("TEST COMPLETED")
    print("=" * 70)
