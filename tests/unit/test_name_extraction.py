"""Test name extraction patterns."""
import re
from typing import Optional


def _extract_user_name_current(message: str) -> Optional[str]:
    """Current implementation."""
    patterns = [
        r'tên (?:là|tôi là|mình là)\s+(\w+)',
        r'mình tên là\s+(\w+)',
        r"(?:i'm|i am|my name is|call me)\s+(\w+)",
        r'tên\s+(\w+)',
    ]
    
    message_lower = message.lower()
    for pattern in patterns:
        match = re.search(pattern, message_lower, re.IGNORECASE)
        if match:
            name = match.group(1).capitalize()
            if name.lower() not in ['là', 'tôi', 'mình', 'the', 'a', 'an']:
                return name
    return None


def _extract_user_name_enhanced(message: str) -> Optional[str]:
    """Enhanced implementation with more Vietnamese patterns."""
    patterns = [
        # Vietnamese patterns
        r'tên (?:là|tôi là|mình là|em là)\s+(\w+)',
        r'mình tên là\s+(\w+)',
        r'(?:tôi|mình|em) là\s+(\w+)',  # "Tôi là Minh"
        r'(?:tôi|mình|em) tên\s+(\w+)',  # "Tôi tên Minh"
        r'gọi (?:tôi|mình|em) là\s+(\w+)',  # "Gọi tôi là Minh"
        r'tên\s+(\w+)',
        # English patterns
        r"(?:i'm|i am|my name is|call me)\s+(\w+)",
    ]
    
    # Common Vietnamese words that aren't names
    not_names = [
        'là', 'tôi', 'mình', 'em', 'anh', 'chị', 'bạn',
        'the', 'a', 'an', 'gì', 'đây', 'này', 'kia',
        'học', 'sinh', 'viên', 'giáo', 'sư'
    ]
    
    message_lower = message.lower()
    for pattern in patterns:
        match = re.search(pattern, message_lower, re.IGNORECASE)
        if match:
            name = match.group(1).capitalize()
            if name.lower() not in not_names:
                return name
    return None


def main():
    # Test cases
    test_cases = [
        ('Xin chào, tên tôi là Minh', 'Minh'),
        ('Mình tên là Hương', 'Hương'),
        ('Tên là Nam', 'Nam'),
        ('Hi, I am John', 'John'),
        ('My name is Alice', 'Alice'),
        ('Call me Bob', 'Bob'),
        ('Chào bạn, tôi là Lan', 'Lan'),  # Should work with enhanced
        ('Tôi tên Hùng', 'Hùng'),  # Should work with enhanced
        ('Em là Thảo', 'Thảo'),  # Should work with enhanced
        ('Gọi tôi là Tuấn', 'Tuấn'),  # Should work with enhanced
        ('Xin chào', None),  # No name
        ('Tôi là học sinh', None),  # "học" is not a name
    ]

    print('=== Testing Current Name Extraction ===')
    print()
    current_passed = 0
    for msg, expected in test_cases:
        result = _extract_user_name_current(msg)
        status = '✓' if result == expected else '✗'
        if result == expected:
            current_passed += 1
        print(f'{status} "{msg}" -> {result} (expected: {expected})')

    print()
    print(f'Current: {current_passed}/{len(test_cases)} passed')
    
    print()
    print('=== Testing Enhanced Name Extraction ===')
    print()
    enhanced_passed = 0
    for msg, expected in test_cases:
        result = _extract_user_name_enhanced(msg)
        status = '✓' if result == expected else '✗'
        if result == expected:
            enhanced_passed += 1
        print(f'{status} "{msg}" -> {result} (expected: {expected})')

    print()
    print(f'Enhanced: {enhanced_passed}/{len(test_cases)} passed')
    
    print()
    if enhanced_passed > current_passed:
        print(f'✅ Enhanced version is better: +{enhanced_passed - current_passed} cases')
    elif enhanced_passed == current_passed:
        print('➡️ Both versions perform equally')
    else:
        print(f'⚠️ Current version is better: +{current_passed - enhanced_passed} cases')


if __name__ == '__main__':
    main()
