"""
Test Intent Classifier - Verify HOTFIX for Vietnamese keywords
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.graph import KNOWLEDGE_KEYWORDS, IntentClassifier, IntentType

def test_intent_classifier():
    """Test intent classification with Vietnamese keywords."""
    print("=" * 70)
    print("INTENT CLASSIFIER TEST - HOTFIX VERIFICATION")
    print("=" * 70)
    
    # Show keyword stats
    print(f"\nTotal KNOWLEDGE_KEYWORDS: {len(KNOWLEDGE_KEYWORDS)}")
    
    # Test messages
    test_cases = [
        # Should be KNOWLEDGE
        ("Giải thích quy tắc 15 COLREGs về tình huống cắt hướng", IntentType.KNOWLEDGE),
        ("Tàu nào phải nhường đường khi hai tàu cắt hướng nhau?", IntentType.KNOWLEDGE),
        ("Quy định về đăng ký tàu biển Việt Nam", IntentType.KNOWLEDGE),
        ("Rule 19 về tầm nhìn hạn chế", IntentType.KNOWLEDGE),
        ("Luật hàng hải Việt Nam quy định gì về thuyền viên?", IntentType.KNOWLEDGE),
        ("Khi nào tàu phải tránh va chạm?", IntentType.KNOWLEDGE),
        ("Điều kiện đăng kiểm tàu biển", IntentType.KNOWLEDGE),
        
        # Should be GENERAL (no maritime keywords)
        ("Hôm nay thời tiết thế nào?", IntentType.GENERAL),
        ("Xin chào, tôi là sinh viên", IntentType.GENERAL),
    ]
    
    classifier = IntentClassifier()
    passed = 0
    failed = 0
    
    print("\n" + "-" * 70)
    print("TEST RESULTS:")
    print("-" * 70)
    
    for message, expected_type in test_cases:
        intent = classifier.classify(message)
        status = "✅ PASS" if intent.type == expected_type else "❌ FAIL"
        
        if intent.type == expected_type:
            passed += 1
        else:
            failed += 1
        
        print(f"\n{status}")
        print(f"  Message: {message[:60]}...")
        print(f"  Expected: {expected_type.value}")
        print(f"  Got: {intent.type.value} (confidence: {intent.confidence})")
    
    print("\n" + "=" * 70)
    print(f"SUMMARY: {passed}/{len(test_cases)} passed, {failed} failed")
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = test_intent_classifier()
    exit(0 if success else 1)
