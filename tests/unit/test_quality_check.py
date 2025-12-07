"""
Quality check for Chat API responses.
"""
import requests
import json

BASE_URL = "https://maritime-ai-chatbot.onrender.com"

def test_chat_quality():
    """Test chat response quality."""
    
    queries = [
        "Quy tắc 15 COLREGs nói gì về tình huống cắt hướng?",
        "Tàu nào phải nhường đường trong tình huống cắt hướng theo COLREGs?",
        "Rule 15 crossing situation explanation"
    ]
    
    for query in queries:
        print(f"\n{'='*60}")
        print(f"QUERY: {query}")
        print('='*60)
        
        try:
            response = requests.post(
                f"{BASE_URL}/api/v1/chat",
                json={
                    "message": query,
                    "user_id": "quality_test",
                    "role": "student"
                },
                headers={"X-API-Key": "test-key"},
                timeout=60
            )
            
            if response.status_code != 200:
                print(f"ERROR: Status {response.status_code}")
                print(response.text[:500])
                continue
            
            data = response.json()
            
            # Answer
            answer = data.get("answer", "")
            print(f"\nANSWER ({len(answer)} chars):")
            print(answer[:500] + "..." if len(answer) > 500 else answer)
            
            # Sources
            sources = data.get("sources", [])
            print(f"\nSOURCES ({len(sources)}):")
            for i, s in enumerate(sources[:5], 1):
                title = s.get("title", "N/A")
                print(f"  {i}. {title}")
            
            # Suggestions
            suggestions = data.get("suggestions", [])
            print(f"\nSUGGESTIONS ({len(suggestions)}):")
            for s in suggestions:
                print(f"  - {s}")
            
            # Quality check
            print("\nQUALITY CHECK:")
            
            # Check if Rule 15 is mentioned in sources
            rule15_in_sources = any("15" in str(s.get("title", "")) or "crossing" in str(s.get("title", "")).lower() for s in sources)
            print(f"  - Rule 15 in sources: {'✅' if rule15_in_sources else '❌'}")
            
            # Check if answer mentions key concepts
            answer_lower = answer.lower()
            has_give_way = "nhường" in answer_lower or "give-way" in answer_lower or "give way" in answer_lower
            has_stand_on = "giữ" in answer_lower or "stand-on" in answer_lower or "stand on" in answer_lower
            has_starboard = "phải" in answer_lower or "starboard" in answer_lower or "mạn phải" in answer_lower
            
            print(f"  - Mentions give-way: {'✅' if has_give_way else '❌'}")
            print(f"  - Mentions stand-on: {'✅' if has_stand_on else '❌'}")
            print(f"  - Mentions starboard: {'✅' if has_starboard else '❌'}")
            
        except Exception as e:
            print(f"ERROR: {e}")

if __name__ == "__main__":
    test_chat_quality()
