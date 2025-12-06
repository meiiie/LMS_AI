"""
Test Deep Reasoning implementation - CHỈ THỊ SỐ 21
"""
import sys
sys.path.insert(0, '.')

from dataclasses import dataclass
from app.engine.conversation_analyzer import ConversationAnalyzer, get_conversation_analyzer

@dataclass
class MockMessage:
    role: str
    content: str

def test_conversation_analyzer():
    print("=" * 60)
    print("TEST: ConversationAnalyzer - Deep Reasoning")
    print("=" * 60)
    
    analyzer = get_conversation_analyzer()
    
    # Test 1: Detect incomplete explanation with "đầu tiên"
    print("\n[Test 1] Incomplete explanation detection")
    messages = [
        MockMessage('user', 'Rule 15 là gì?'),
        MockMessage('assistant', 'Rule 15 quy định về tình huống cắt hướng. Đầu tiên, tàu nhường đường phải tránh cắt mũi tàu được nhường đường.'),
        MockMessage('user', 'Thời tiết hôm nay thế nào?'),
    ]
    
    context = analyzer.analyze(messages)
    print(f"  Incomplete explanations: {context.incomplete_explanations}")
    print(f"  Last topic: {context.last_explanation_topic}")
    print(f"  User interrupted: {context.user_interrupted}")
    print(f"  Should offer continuation: {context.should_offer_continuation}")
    
    # Test 2: Build proactive context
    print("\n[Test 2] Proactive context building")
    proactive = analyzer.build_proactive_context(context)
    if proactive:
        print(f"  Proactive hint generated: YES")
        print(f"  Content: {proactive[:150]}...")
    else:
        print(f"  Proactive hint generated: NO")
    
    # Test 3: Topic extraction
    print("\n[Test 3] Topic extraction")
    test_contents = [
        "Rule 15 quy định về tình huống cắt hướng",
        "Theo COLREGs, tàu phải...",
        "SOLAS yêu cầu tàu phải có...",
        "Điều 25 của Bộ luật Hàng hải",
    ]
    for content in test_contents:
        topic = analyzer.extract_topic(content)
        print(f"  '{content[:40]}...' -> Topic: {topic}")
    
    # Test 4: Continuation request detection
    print("\n[Test 4] Continuation request detection")
    test_cases = [
        ("tiếp tục đi", "Rule 15", True),
        ("nói thêm về Rule 15", "Rule 15", True),
        ("thời tiết hôm nay thế nào?", "Rule 15", False),
        ("chi tiết hơn được không?", "SOLAS", True),
    ]
    for user_msg, topic, expected in test_cases:
        result = analyzer.is_continuation_request(user_msg, topic)
        status = "✅" if result == expected else "❌"
        print(f"  {status} '{user_msg}' (topic: {topic}) -> {result}")
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)

if __name__ == "__main__":
    test_conversation_analyzer()
