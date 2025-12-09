"""
Test Conversation Analyzer locally

Kiểm tra logic phân tích ngữ cảnh hội thoại cho câu hỏi mơ hồ.
"""
import sys
sys.path.insert(0, '.')

from app.engine.conversation_analyzer import (
    ConversationAnalyzer, 
    ConversationContext,
    QuestionType,
    get_conversation_analyzer
)
from dataclasses import dataclass


@dataclass
class MockMessage:
    """Mock message for testing."""
    role: str
    content: str


def test_question_type_detection():
    """Test detection of question types."""
    print("="*70)
    print("TEST 1: QUESTION TYPE DETECTION")
    print("="*70)
    
    analyzer = get_conversation_analyzer()
    
    test_cases = [
        # Standalone questions
        ("Quy tắc 15 COLREGs là gì?", QuestionType.STANDALONE),
        ("Giải thích Rule 5", QuestionType.STANDALONE),
        ("Điều kiện đăng ký tàu biển Việt Nam là gì?", QuestionType.STANDALONE),
        
        # Follow-up questions
        ("Còn đèn xanh thì sao?", QuestionType.AMBIGUOUS),
        ("Thế quy tắc 16 thì sao?", QuestionType.AMBIGUOUS),
        ("Vậy phí bao nhiêu?", QuestionType.AMBIGUOUS),
        
        # Ambiguous questions
        ("Cần những giấy tờ gì?", QuestionType.AMBIGUOUS),
        ("Phí bao nhiêu?", QuestionType.AMBIGUOUS),
        ("Rồi sao?", QuestionType.AMBIGUOUS),
    ]
    
    passed = 0
    for question, expected_type in test_cases:
        detected = analyzer._detect_question_type(question)
        status = "✅" if detected == expected_type else "❌"
        if detected == expected_type:
            passed += 1
        print(f"{status} '{question}' -> {detected.value} (expected: {expected_type.value})")
    
    print(f"\nResult: {passed}/{len(test_cases)} passed")
    return passed == len(test_cases)


def test_topic_extraction():
    """Test extraction of current topic from conversation."""
    print("\n" + "="*70)
    print("TEST 2: TOPIC EXTRACTION")
    print("="*70)
    
    analyzer = get_conversation_analyzer()
    
    # Test case 1: Navigation lights
    messages1 = [
        MockMessage("user", "Khi thấy đèn đỏ trên tàu khác, tôi nên làm gì?"),
        MockMessage("assistant", "Đèn đỏ là đèn mạn trái. Khi bạn thấy đèn đỏ..."),
        MockMessage("user", "Còn đèn xanh thì sao?"),
    ]
    topic1 = analyzer._extract_current_topic(messages1)
    print(f"Navigation lights conversation -> Topic: {topic1}")
    assert topic1 == "navigation_lights", f"Expected 'navigation_lights', got '{topic1}'"
    print("✅ Correct!")
    
    # Test case 2: Ship registration
    messages2 = [
        MockMessage("user", "Điều kiện đăng ký tàu biển Việt Nam là gì?"),
        MockMessage("assistant", "Để đăng ký tàu biển, bạn cần..."),
        MockMessage("user", "Cần những giấy tờ gì?"),
    ]
    topic2 = analyzer._extract_current_topic(messages2)
    print(f"Ship registration conversation -> Topic: {topic2}")
    assert topic2 == "ship_registration", f"Expected 'ship_registration', got '{topic2}'"
    print("✅ Correct!")
    
    # Test case 3: COLREGs rules
    messages3 = [
        MockMessage("user", "Quy tắc 15 COLREGs nói về gì?"),
        MockMessage("assistant", "Quy tắc 15 về tình huống cắt hướng..."),
        MockMessage("user", "Còn quy tắc 16?"),
    ]
    topic3 = analyzer._extract_current_topic(messages3)
    print(f"COLREGs rules conversation -> Topic: {topic3}")
    assert topic3 == "colregs_rules", f"Expected 'colregs_rules', got '{topic3}'"
    print("✅ Correct!")
    
    return True


def test_context_inference():
    """Test inference of context for ambiguous questions."""
    print("\n" + "="*70)
    print("TEST 3: CONTEXT INFERENCE")
    print("="*70)
    
    analyzer = get_conversation_analyzer()
    
    # Test case 1: "Cần những giấy tờ gì?" after asking about ship registration
    messages1 = [
        MockMessage("user", "Điều kiện đăng ký tàu biển Việt Nam là gì?"),
        MockMessage("assistant", "Để đăng ký tàu biển, bạn cần đáp ứng các điều kiện sau..."),
        MockMessage("user", "Cần những giấy tờ gì?"),
    ]
    
    context1 = analyzer.analyze(messages1)
    print(f"\nConversation about ship registration:")
    print(f"  Question: 'Cần những giấy tờ gì?'")
    print(f"  Question type: {context1.question_type.value}")
    print(f"  Current topic: {context1.current_topic}")
    print(f"  Inferred context: {context1.inferred_context}")
    print(f"  Confidence: {context1.confidence:.2f}")
    
    assert context1.question_type == QuestionType.AMBIGUOUS, "Should be AMBIGUOUS"
    assert context1.current_topic == "ship_registration", "Topic should be ship_registration"
    assert context1.inferred_context is not None, "Should have inferred context"
    print("✅ Context correctly inferred!")
    
    # Test case 2: "Phí bao nhiêu?" after asking about ship registration
    messages2 = [
        MockMessage("user", "Điều kiện đăng ký tàu biển Việt Nam là gì?"),
        MockMessage("assistant", "Để đăng ký tàu biển, bạn cần đáp ứng các điều kiện sau..."),
        MockMessage("user", "Cần những giấy tờ gì?"),
        MockMessage("assistant", "Bạn cần chuẩn bị các giấy tờ sau..."),
        MockMessage("user", "Phí bao nhiêu?"),
    ]
    
    context2 = analyzer.analyze(messages2)
    print(f"\nConversation about ship registration (continued):")
    print(f"  Question: 'Phí bao nhiêu?'")
    print(f"  Question type: {context2.question_type.value}")
    print(f"  Current topic: {context2.current_topic}")
    print(f"  Inferred context: {context2.inferred_context}")
    print(f"  Confidence: {context2.confidence:.2f}")
    
    assert context2.question_type == QuestionType.AMBIGUOUS, "Should be AMBIGUOUS"
    assert context2.current_topic == "ship_registration", "Topic should be ship_registration"
    print("✅ Context correctly inferred!")
    
    return True


def test_context_prompt_building():
    """Test building of context prompt for AI."""
    print("\n" + "="*70)
    print("TEST 4: CONTEXT PROMPT BUILDING")
    print("="*70)
    
    analyzer = get_conversation_analyzer()
    
    messages = [
        MockMessage("user", "Điều kiện đăng ký tàu biển Việt Nam là gì?"),
        MockMessage("assistant", "Để đăng ký tàu biển, bạn cần đáp ứng các điều kiện sau..."),
        MockMessage("user", "Cần những giấy tờ gì?"),
    ]
    
    context = analyzer.analyze(messages)
    prompt = analyzer.build_context_prompt(context)
    
    print(f"Generated context prompt:\n{prompt}")
    
    assert "[CONTEXT ANALYSIS]" in prompt, "Should contain CONTEXT ANALYSIS header"
    assert "MƠ HỒ" in prompt or "NỐI TIẾP" in prompt, "Should indicate question type"
    print("\n✅ Context prompt correctly built!")
    
    return True


def main():
    print("="*70)
    print("CONVERSATION ANALYZER - LOCAL UNIT TESTS")
    print("="*70)
    
    results = []
    
    try:
        results.append(("Question Type Detection", test_question_type_detection()))
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        results.append(("Question Type Detection", False))
    
    try:
        results.append(("Topic Extraction", test_topic_extraction()))
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        results.append(("Topic Extraction", False))
    
    try:
        results.append(("Context Inference", test_context_inference()))
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        results.append(("Context Inference", False))
    
    try:
        results.append(("Context Prompt Building", test_context_prompt_building()))
    except Exception as e:
        print(f"❌ Test failed with error: {e}")
        results.append(("Context Prompt Building", False))
    
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"  {name}: {status}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
