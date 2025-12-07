"""
Test script for EnhancedPromptLoader (Task 1.2)
Validates: Requirements 1.2, 7.1, 7.3
"""

import sys
sys.path.insert(0, '.')

from app.prompts.prompt_loader import PromptLoader, get_prompt_loader


def test_basic_prompt():
    """Test basic build_system_prompt works."""
    print("=== Test 1: Basic prompt ===")
    loader = PromptLoader()
    prompt = loader.build_system_prompt('student')
    assert prompt is not None
    assert len(prompt) > 100
    print("✅ Basic prompt generated successfully")
    return True


def test_variation_parameters():
    """Test build_system_prompt with variation parameters."""
    print("\n=== Test 2: Variation parameters ===")
    loader = PromptLoader()
    
    prompt = loader.build_system_prompt(
        role='student',
        user_name='Minh',
        recent_phrases=['Về vấn đề này...', 'Đúng rồi, để tôi giải thích...'],
        is_follow_up=True,
        name_usage_count=2,
        total_responses=5
    )
    
    assert 'VARIATION' in prompt, "Missing VARIATION section"
    assert 'FOLLOW-UP' in prompt, "Missing follow-up instruction"
    assert 'TRÁNH' in prompt, "Missing phrases to avoid"
    print("✅ Variation parameters work correctly")
    return True


def test_name_usage_control():
    """Test name usage frequency control (20-30%)."""
    print("\n=== Test 3: Name usage control ===")
    loader = PromptLoader()
    
    # Case 1: Low usage (< 20%) - should suggest using name
    prompt_low = loader.build_system_prompt(
        role='student',
        user_name='Hùng',
        name_usage_count=1,
        total_responses=10
    )
    assert 'Có thể dùng tên' in prompt_low, "Should suggest using name when ratio < 20%"
    print("  ✅ Low usage: suggests using name")
    
    # Case 2: High usage (>= 30%) - should NOT use name
    prompt_high = loader.build_system_prompt(
        role='student',
        user_name='Hùng',
        name_usage_count=4,
        total_responses=10
    )
    assert 'KHÔNG dùng tên' in prompt_high, "Should NOT use name when ratio >= 30%"
    print("  ✅ High usage: prevents using name")
    
    return True


def test_empathy_detection():
    """Test empathy detection from user messages."""
    print("\n=== Test 4: Empathy detection ===")
    loader = PromptLoader()
    
    # Frustration keywords
    assert loader.detect_empathy_needed('Tôi mệt quá rồi', 'student') == True
    print("  ✅ Detects 'mệt'")
    
    assert loader.detect_empathy_needed('Học chán quá', 'student') == True
    print("  ✅ Detects 'chán'")
    
    assert loader.detect_empathy_needed('Khó quá không hiểu gì cả', 'student') == True
    print("  ✅ Detects 'khó quá'")
    
    # Basic needs
    assert loader.detect_empathy_needed('Đói quá', 'student') == True
    print("  ✅ Detects 'đói'")
    
    # Normal question - no empathy needed
    assert loader.detect_empathy_needed('Quy tắc 5 là gì?', 'student') == False
    print("  ✅ Normal question: no empathy")
    
    return True


def test_variation_phrases():
    """Test get_variation_phrases method."""
    print("\n=== Test 5: Variation phrases ===")
    loader = PromptLoader()
    
    # Test openings.knowledge
    knowledge_phrases = loader.get_variation_phrases('student', 'openings', 'knowledge')
    assert len(knowledge_phrases) > 0, "Should have knowledge opening phrases"
    print(f"  ✅ Knowledge openings: {len(knowledge_phrases)} phrases")
    
    # Test openings.empathy
    empathy_phrases = loader.get_variation_phrases('student', 'openings', 'empathy')
    assert len(empathy_phrases) > 0, "Should have empathy opening phrases"
    print(f"  ✅ Empathy openings: {len(empathy_phrases)} phrases")
    
    # Test transitions
    transitions = loader.get_variation_phrases('student', 'transitions')
    assert len(transitions) > 0, "Should have transition phrases"
    print(f"  ✅ Transitions: {len(transitions)} phrases")
    
    return True


def test_random_opening():
    """Test get_random_opening with exclusion."""
    print("\n=== Test 6: Random opening with exclusion ===")
    loader = PromptLoader()
    
    # Get first opening
    opening1 = loader.get_random_opening('student', 'knowledge')
    assert opening1 is not None
    print(f"  First opening: '{opening1}'")
    
    # Get second opening, excluding first
    opening2 = loader.get_random_opening('student', 'knowledge', exclude_phrases=[opening1])
    assert opening2 is not None
    assert opening2 != opening1, "Should return different phrase"
    print(f"  Second opening (different): '{opening2}'")
    
    print("  ✅ Exclusion works correctly")
    return True


def test_empathy_response_template():
    """Test get_empathy_response_template method."""
    print("\n=== Test 7: Empathy response templates ===")
    loader = PromptLoader()
    
    frustration_template = loader.get_empathy_response_template('student', 'frustration')
    assert frustration_template is not None
    assert '{suggestion}' in frustration_template
    print(f"  ✅ Frustration template: '{frustration_template[:50]}...'")
    
    basic_needs_template = loader.get_empathy_response_template('student', 'basic_needs')
    assert basic_needs_template is not None
    print(f"  ✅ Basic needs template: '{basic_needs_template[:50]}...'")
    
    return True


def test_singleton():
    """Test get_prompt_loader singleton."""
    print("\n=== Test 8: Singleton pattern ===")
    loader1 = get_prompt_loader()
    loader2 = get_prompt_loader()
    assert loader1 is loader2, "Should return same instance"
    print("  ✅ Singleton works correctly")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing EnhancedPromptLoader (Task 1.2)")
    print("Validates: Requirements 1.2, 7.1, 7.3")
    print("=" * 60)
    
    tests = [
        test_basic_prompt,
        test_variation_parameters,
        test_name_usage_control,
        test_empathy_detection,
        test_variation_phrases,
        test_random_opening,
        test_empathy_response_template,
        test_singleton,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            failed += 1
    
    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
