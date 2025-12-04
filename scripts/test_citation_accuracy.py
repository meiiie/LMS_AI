"""
Test Citation Accuracy - Kiểm tra độ chính xác của citations
Đánh giá xem citations có thực sự liên quan đến câu hỏi không.
"""
import asyncio
import sys
import os
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def calculate_relevance_score(query: str, citation_title: str, citation_source: str) -> float:
    """
    Tính điểm relevance của citation với query.
    
    Returns:
        float: 0.0 - 1.0 (1.0 = hoàn toàn liên quan)
    """
    query_lower = query.lower()
    title_lower = citation_title.lower()
    source_lower = citation_source.lower()
    
    score = 0.0
    
    # Extract rule/chapter numbers from query
    rule_pattern = r'rule\s*(\d+)|quy\s*tắc\s*(\d+)|chapter\s*(\w+)'
    query_matches = re.findall(rule_pattern, query_lower)
    query_numbers = [m for group in query_matches for m in group if m]
    
    # Check if citation title contains the same rule/chapter
    title_matches = re.findall(rule_pattern, title_lower)
    title_numbers = [m for group in title_matches for m in group if m]
    
    # Exact rule match = high score
    for qn in query_numbers:
        if qn in title_numbers:
            score += 0.5
    
    # Keyword matching
    keywords = {
        'colregs': ['colreg', 'quy tắc', 'rule'],
        'solas': ['solas', 'an toàn', 'safety'],
        'marpol': ['marpol', 'ô nhiễm', 'pollution'],
        'crossing': ['crossing', 'cắt hướng', 'cross'],
        'visibility': ['visibility', 'tầm nhìn', 'restricted'],
        'overtaking': ['overtaking', 'vượt', 'overtake'],
        'head-on': ['head-on', 'đối đầu', 'meeting'],
    }
    
    for topic, kws in keywords.items():
        query_has = any(kw in query_lower for kw in kws)
        title_has = any(kw in title_lower for kw in kws)
        
        if query_has and title_has:
            score += 0.2
    
    return min(score, 1.0)


async def test_citation_accuracy():
    """Test độ chính xác của citations."""
    print("=" * 70)
    print("TEST: CITATION ACCURACY ANALYSIS")
    print("=" * 70)
    
    from app.services.hybrid_search_service import get_hybrid_search_service
    
    # Use singleton to avoid connection pool issues
    hybrid_search = get_hybrid_search_service()
    
    # Test cases với expected citations
    test_cases = [
        {
            "query": "Rule 15 crossing situation",
            "expected_keywords": ["rule 15", "crossing"],
            "description": "COLREGs Rule 15"
        },
        {
            "query": "Rule 19 restricted visibility",
            "expected_keywords": ["rule 19", "visibility", "restricted"],
            "description": "COLREGs Rule 19"
        },
        {
            "query": "Rule 13 overtaking vessel",
            "expected_keywords": ["rule 13", "overtaking"],
            "description": "COLREGs Rule 13"
        },
        {
            "query": "Rule 6 safe speed",
            "expected_keywords": ["rule 6", "safe speed"],
            "description": "COLREGs Rule 6"
        },
        {
            "query": "Quy tắc 15 COLREGs tình huống cắt hướng",
            "expected_keywords": ["rule 15", "crossing", "quy tắc 15"],
            "description": "COLREGs Rule 15 (Vietnamese)"
        },
    ]
    
    total_citations = 0
    relevant_citations = 0
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*70}")
        print(f"TEST {i}: {test['description']}")
        print(f"Query: {test['query']}")
        print("-" * 70)
        
        try:
            results = await hybrid_search.search(test['query'], limit=5)
            
            print(f"\n📚 CITATIONS ANALYSIS:")
            
            test_relevant = 0
            for j, result in enumerate(results, 1):
                relevance = calculate_relevance_score(
                    test['query'], 
                    result.title or "",
                    result.source or ""
                )
                
                is_relevant = relevance >= 0.3
                status = "✅" if is_relevant else "❌"
                
                title = result.title or "No title"
                print(f"\n  {j}. {status} {title[:60]}...")
                print(f"     Source: {result.source}")
                print(f"     RRF Score: {result.rrf_score:.4f}")
                print(f"     Relevance: {relevance:.2f}")
                
                total_citations += 1
                if is_relevant:
                    relevant_citations += 1
                    test_relevant += 1
            
            accuracy = (test_relevant / len(results) * 100) if results else 0
            print(f"\n  📊 Test Accuracy: {test_relevant}/{len(results)} ({accuracy:.1f}%)")
            
        except Exception as e:
            print(f"❌ ERROR: {e}")
    
    # Summary
    print(f"\n{'='*70}")
    print("📊 OVERALL SUMMARY")
    print(f"{'='*70}")
    
    overall_accuracy = (relevant_citations / total_citations * 100) if total_citations else 0
    print(f"\nTotal Citations: {total_citations}")
    print(f"Relevant Citations: {relevant_citations}")
    print(f"Overall Accuracy: {overall_accuracy:.1f}%")
    
    if overall_accuracy >= 70:
        print("\n✅ PASS - Citation accuracy is acceptable")
    elif overall_accuracy >= 50:
        print("\n⚠️ WARNING - Citation accuracy needs improvement")
    else:
        print("\n❌ FAIL - Citation accuracy is too low")
    
    print(f"\n{'='*70}")


async def test_suggested_questions_quality():
    """Test chất lượng của suggested questions."""
    print("\n" + "=" * 70)
    print("TEST: SUGGESTED QUESTIONS QUALITY")
    print("=" * 70)
    
    from app.api.v1.chat import _generate_suggested_questions
    
    test_cases = [
        {
            "user_message": "Giải thích quy tắc 15 COLREGs",
            "ai_response": "Quy tắc 15 về tình huống cắt hướng...",
            "expected_topics": ["nhường đường", "áp dụng", "ngoại lệ"]
        },
        {
            "user_message": "SOLAS yêu cầu gì về thiết bị cứu sinh?",
            "ai_response": "SOLAS Chapter III quy định...",
            "expected_topics": ["thiết bị", "huấn luyện", "kiểm tra"]
        },
        {
            "user_message": "MARPOL quy định về xả thải dầu",
            "ai_response": "Theo MARPOL Annex I...",
            "expected_topics": ["xả thải", "vùng biển", "xử phạt"]
        },
        {
            "user_message": "Thời tiết hôm nay thế nào?",
            "ai_response": "Tôi không có thông tin về thời tiết...",
            "expected_topics": ["hàng hải", "colregs", "solas"]  # Non-maritime -> suggest maritime topics
        },
    ]
    
    for i, test in enumerate(test_cases, 1):
        print(f"\n{'='*70}")
        print(f"TEST {i}: {test['user_message'][:50]}...")
        print("-" * 70)
        
        suggestions = _generate_suggested_questions(
            test['user_message'],
            test['ai_response']
        )
        
        print(f"\n💡 SUGGESTED QUESTIONS:")
        for j, q in enumerate(suggestions, 1):
            print(f"  {j}. {q}")
        
        # Check if suggestions are relevant
        relevant_count = 0
        for topic in test['expected_topics']:
            for q in suggestions:
                if topic.lower() in q.lower():
                    relevant_count += 1
                    break
        
        relevance = (relevant_count / len(test['expected_topics']) * 100)
        print(f"\n  📊 Topic Coverage: {relevant_count}/{len(test['expected_topics'])} ({relevance:.1f}%)")
        
        if relevance >= 60:
            print("  ✅ Good - Suggestions are relevant")
        else:
            print("  ⚠️ Could be improved - Suggestions are generic")
    
    print(f"\n{'='*70}")


async def main():
    """Run all tests."""
    await test_citation_accuracy()
    await test_suggested_questions_quality()
    
    print("\n" + "=" * 70)
    print("🎉 ALL ACCURACY TESTS COMPLETED!")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
