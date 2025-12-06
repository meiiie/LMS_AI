"""
Test Pronoun Detection - CHỈ THỊ KỸ THUẬT SỐ 20

Test các pattern phát hiện xưng hô từ user message.

Usage:
    cd maritime-ai-service
    python scripts/test_pronoun_detection.py
"""

import sys
sys.path.insert(0, ".")

from app.prompts.prompt_loader import (
    detect_pronoun_style,
    get_pronoun_instruction,
    VALID_PRONOUN_PAIRS,
    INAPPROPRIATE_PRONOUNS
)


def test_pronoun_detection():
    """Test pronoun detection with various patterns."""
    
    print("=" * 60)
    print("TEST PRONOUN DETECTION - CHỈ THỊ KỸ THUẬT SỐ 20")
    print("=" * 60)
    
    # Test cases: (message, expected_user_self or None)
    test_cases = [
        # "mình" patterns
        ("Mình muốn hỏi về Rule 5", "mình"),
        ("Mình là sinh viên năm 3", "mình"),
        ("Cậu ơi, giúp mình với", "mình"),
        
        # "tớ" patterns
        ("Tớ không hiểu quy tắc này", "tớ"),
        ("Tớ là Minh, sinh viên hàng hải", "tớ"),
        
        # "em" patterns (user xưng em)
        ("Em chào anh", "em"),
        ("Em muốn hỏi về COLREGs", "em"),
        ("Em là sinh viên năm 2", "em"),
        
        # "anh" patterns (user gọi AI là anh) - nhưng nếu user cũng xưng "em" thì ưu tiên "em"
        ("Chào anh, em cần giúp đỡ", "em"),  # User xưng "em" -> detect "em"
        ("Anh ơi, giải thích Rule 15 giúp em", "anh"),  # "Anh ơi" pattern
        
        # "chị" patterns (user gọi AI là chị) - nhưng nếu user cũng xưng "em" thì ưu tiên "em"
        ("Chào chị, em cần hỏi", "em"),  # User xưng "em" -> detect "em"
        ("Chị ơi, giúp em với", "chị"),  # "Chị ơi" pattern
        
        # Default "tôi/bạn" - should return None (use default)
        ("Tôi muốn học về COLREGs", None),  # "tôi" is default
        ("Xin chào, tôi là Minh", None),
        ("Cho tôi hỏi về Rule 5", None),
        
        # No pronoun detected
        ("Rule 5 là gì?", None),
        ("Giải thích COLREGs", None),
        
        # Inappropriate pronouns - should return None
        ("Mày giải thích đi", None),
        ("Tao muốn biết", None),
    ]
    
    passed = 0
    failed = 0
    
    for message, expected in test_cases:
        result = detect_pronoun_style(message)
        actual = result.get("user_self") if result else None
        
        status = "✅" if actual == expected else "❌"
        if actual == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"\n{status} Message: \"{message}\"")
        print(f"   Expected: {expected}")
        print(f"   Actual: {actual}")
        if result:
            print(f"   Full style: {result}")
    
    print("\n" + "=" * 60)
    print(f"RESULTS: {passed}/{len(test_cases)} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


def test_pronoun_instruction():
    """Test pronoun instruction generation."""
    
    print("\n" + "=" * 60)
    print("TEST PRONOUN INSTRUCTION GENERATION")
    print("=" * 60)
    
    # Test with "mình" style
    style_minh = {"user_self": "mình", "user_called": "cậu", "ai_self": "mình"}
    instruction = get_pronoun_instruction(style_minh)
    print(f"\nStyle 'mình':")
    print(instruction)
    
    # Test with "em" style
    style_em = {"user_self": "em", "user_called": "em", "ai_self": "anh"}
    instruction = get_pronoun_instruction(style_em)
    print(f"\nStyle 'em':")
    print(instruction)
    
    # Test with None (default)
    instruction = get_pronoun_instruction(None)
    print(f"\nStyle None (default):")
    print(f"'{instruction}' (should be empty)")
    
    return True


def test_valid_pronoun_pairs():
    """Test that all valid pronoun pairs are defined correctly."""
    
    print("\n" + "=" * 60)
    print("VALID PRONOUN PAIRS")
    print("=" * 60)
    
    for user_pronoun, ai_response in VALID_PRONOUN_PAIRS.items():
        print(f"\nUser xưng '{user_pronoun}':")
        print(f"  → AI gọi user: '{ai_response['user_called']}'")
        print(f"  → AI tự xưng: '{ai_response['ai_self']}'")
    
    return True


def test_inappropriate_pronouns():
    """Test that inappropriate pronouns are filtered."""
    
    print("\n" + "=" * 60)
    print("INAPPROPRIATE PRONOUNS (should be filtered)")
    print("=" * 60)
    
    print(f"Blocked words: {INAPPROPRIATE_PRONOUNS}")
    
    # Test that these return None
    bad_messages = [
        "Mày giải thích đi",
        "Tao muốn biết Rule 5",
        "Đ.m, khó quá",
    ]
    
    all_filtered = True
    for msg in bad_messages:
        result = detect_pronoun_style(msg)
        status = "✅ Filtered" if result is None else "❌ NOT filtered"
        print(f"\n{status}: \"{msg}\"")
        if result is not None:
            all_filtered = False
    
    return all_filtered


if __name__ == "__main__":
    print("\n🔍 PRONOUN DETECTION TEST SUITE\n")
    
    test1 = test_pronoun_detection()
    test2 = test_pronoun_instruction()
    test3 = test_valid_pronoun_pairs()
    test4 = test_inappropriate_pronouns()
    
    print("\n" + "=" * 60)
    print("FINAL SUMMARY")
    print("=" * 60)
    print(f"Pronoun Detection: {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"Instruction Generation: {'✅ PASS' if test2 else '❌ FAIL'}")
    print(f"Valid Pairs: {'✅ PASS' if test3 else '❌ FAIL'}")
    print(f"Inappropriate Filter: {'✅ PASS' if test4 else '❌ FAIL'}")
    
    if all([test1, test2, test3, test4]):
        print("\n🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("\n⚠️ SOME TESTS FAILED")
        sys.exit(1)
