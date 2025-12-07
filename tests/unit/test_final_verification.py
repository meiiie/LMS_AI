"""
Final Verification Test - Kiểm tra toàn bộ hệ thống Sources & Suggestions
Sau khi implement Title Match Boosting.
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def verify_citation_top1_accuracy():
    """Verify that correct citation is always at position #1."""
    print("=" * 70)
    print("🎯 FINAL VERIFICATION: TOP-1 CITATION ACCURACY")
    print("=" * 70)
    
    from app.services.hybrid_search_service import HybridSearchService
    
    service = HybridSearchService()
    
    # Test cases with expected top-1 result
    test_cases = [
        {
            "query": "Rule 15 crossing situation",
            "expected_title_contains": "Rule 15",
            "description": "COLREGs Rule 15"
        },
        {
            "query": "Rule 19 restricted visibility",
            "expected_title_contains": "Rule 19",
            "description": "COLREGs Rule 19"
        },
        {
            "query": "Rule 13 overtaking vessel",
            "expected_title_contains": "Rule 13",
            "description": "COLREGs Rule 13"
        },
        {
            "query": "Rule 6 safe speed",
            "expected_title_contains": "Rule 6",
            "description": "COLREGs Rule 6"
        },
        {
            "query": "Quy tắc 15 COLREGs cắt hướng",
            "expected_title_contains": "Rule 15",
            "description": "COLREGs Rule 15 (Vietnamese)"
        },
    ]
    
    passed = 0
    failed = 0
    
    for test in test_cases:
        results = await service.search(test['query'], limit=5)
        
        if results:
            top1 = results[0]
            is_correct = test['expected_title_contains'].lower() in top1.title.lower()
            
            if is_correct:
                print(f"✅ {test['description']}: {top1.title[:50]}... (RRF: {top1.rrf_score:.4f})")
                passed += 1
            else:
                print(f"❌ {test['description']}: Expected '{test['expected_title_contains']}' but got '{top1.title[:50]}'")
                failed += 1
        else:
            print(f"❌ {test['description']}: No results!")
            failed += 1
    
    print(f"\n{'='*70}")
    print(f"📊 TOP-1 ACCURACY: {passed}/{passed+failed} ({passed/(passed+failed)*100:.1f}%)")
    
    if failed == 0:
        print("🎉 ALL TESTS PASSED!")
    else:
        print(f"⚠️ {failed} tests failed")
    
    return failed == 0


async def verify_suggested_questions():
    """Verify suggested questions are relevant."""
    print(f"\n{'='*70}")
    print("🎯 FINAL VERIFICATION: SUGGESTED QUESTIONS")
    print("=" * 70)
    
    from app.api.v1.chat import _generate_suggested_questions
    
    test_cases = [
        {
            "user_message": "Quy tắc 15 COLREGs",
            "ai_response": "Quy tắc 15 về tình huống cắt hướng...",
            "expected_keywords": ["nhường đường", "áp dụng", "ngoại lệ"]
        },
        {
            "user_message": "SOLAS thiết bị cứu sinh",
            "ai_response": "SOLAS Chapter III...",
            "expected_keywords": ["thiết bị", "huấn luyện", "kiểm tra"]
        },
        {
            "user_message": "MARPOL xả thải",
            "ai_response": "MARPOL Annex I...",
            "expected_keywords": ["xả thải", "vùng biển", "xử phạt"]
        },
    ]
    
    passed = 0
    failed = 0
    
    for test in test_cases:
        suggestions = _generate_suggested_questions(
            test['user_message'],
            test['ai_response']
        )
        
        # Check if at least 2/3 expected keywords are covered
        covered = sum(1 for kw in test['expected_keywords'] 
                     if any(kw in s.lower() for s in suggestions))
        
        if covered >= 2:
            print(f"✅ {test['user_message'][:30]}...: {covered}/3 keywords covered")
            passed += 1
        else:
            print(f"❌ {test['user_message'][:30]}...: Only {covered}/3 keywords covered")
            failed += 1
    
    print(f"\n{'='*70}")
    print(f"📊 SUGGESTIONS QUALITY: {passed}/{passed+failed} ({passed/(passed+failed)*100:.1f}%)")
    
    if failed == 0:
        print("🎉 ALL TESTS PASSED!")
    
    return failed == 0


async def verify_full_chat_response():
    """Verify full chat response includes sources and suggestions."""
    print(f"\n{'='*70}")
    print("🎯 FINAL VERIFICATION: FULL CHAT RESPONSE")
    print("=" * 70)
    
    from app.services.chat_service import ChatService
    from app.models.schemas import ChatRequest, UserRole
    from uuid import uuid4
    
    service = ChatService()
    user_id = f"verify_{uuid4().hex[:8]}"
    
    test_cases = [
        {
            "message": "Giải thích quy tắc 15 COLREGs",
            "role": "student",
            "expected_source": "Rule 15"
        },
        {
            "message": "Rule 19 restricted visibility",
            "role": "student",
            "expected_source": "Rule 19"
        },
    ]
    
    passed = 0
    failed = 0
    
    for test in test_cases:
        request = ChatRequest(
            user_id=user_id,
            message=test['message'],
            role=UserRole(test['role'])
        )
        
        response = await service.process_message(request)
        
        # Check response has content
        has_content = len(response.message) > 100
        
        # Check sources exist and top source is correct
        has_sources = response.sources and len(response.sources) > 0
        top_source_correct = False
        if has_sources:
            top_source_correct = test['expected_source'].lower() in response.sources[0].title.lower()
        
        # Check metadata
        has_metadata = response.metadata is not None
        
        if has_content and has_sources and top_source_correct and has_metadata:
            print(f"✅ {test['message'][:40]}...")
            print(f"   - Response: {len(response.message)} chars")
            print(f"   - Top Source: {response.sources[0].title[:50]}...")
            print(f"   - Citations: {response.metadata.get('citation_count', 0)}")
            passed += 1
        else:
            print(f"❌ {test['message'][:40]}...")
            print(f"   - Content: {has_content}, Sources: {has_sources}, TopCorrect: {top_source_correct}")
            failed += 1
        
        await asyncio.sleep(1)  # Rate limit
    
    print(f"\n{'='*70}")
    print(f"📊 FULL RESPONSE: {passed}/{passed+failed} ({passed/(passed+failed)*100:.1f}%)")
    
    if failed == 0:
        print("🎉 ALL TESTS PASSED!")
    
    return failed == 0


async def main():
    """Run all verification tests."""
    print("\n" + "=" * 70)
    print("🔍 FINAL VERIFICATION - SOURCES & SUGGESTIONS")
    print("After Title Match Boosting Implementation")
    print("=" * 70)
    
    results = []
    
    # Test 1: Citation accuracy
    results.append(await verify_citation_top1_accuracy())
    
    # Test 2: Suggested questions
    results.append(await verify_suggested_questions())
    
    # Test 3: Full chat response
    results.append(await verify_full_chat_response())
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 FINAL SUMMARY")
    print("=" * 70)
    
    all_passed = all(results)
    
    print(f"\n✅ Citation Top-1 Accuracy: {'PASS' if results[0] else 'FAIL'}")
    print(f"✅ Suggested Questions: {'PASS' if results[1] else 'FAIL'}")
    print(f"✅ Full Chat Response: {'PASS' if results[2] else 'FAIL'}")
    
    if all_passed:
        print("\n🎉 ALL VERIFICATIONS PASSED!")
        print("Sources và Suggested Questions hoạt động chính xác!")
    else:
        print("\n⚠️ Some verifications failed. Please review.")
    
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
