"""
Test Guardian Agent - CHỈ THỊ KỸ THUẬT SỐ 21

Test LLM-based content moderation.

Usage:
    cd maritime-ai-service
    python scripts/test_guardian_agent.py
"""

import asyncio
import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from app.engine.guardian_agent import (
    GuardianAgent,
    GuardianConfig,
    GuardianDecision,
    PronounValidationResult
)


async def test_skip_patterns():
    """Test that simple greetings skip LLM."""
    print("=" * 60)
    print("TEST: Skip Patterns (Simple Greetings)")
    print("=" * 60)
    
    agent = GuardianAgent()
    
    skip_messages = [
        "Chào",
        "Hello",
        "Hi",
        "Xin chào",
        "Cảm ơn",
        "Thanks",
        "Bye",
    ]
    
    for msg in skip_messages:
        decision = await agent.validate_message(msg)
        status = "✅ SKIP" if not decision.used_llm else "❌ USED LLM"
        print(f"{status}: '{msg}' -> {decision.action}")
    
    return True


async def test_pronoun_requests():
    """Test custom pronoun request validation."""
    print("\n" + "=" * 60)
    print("TEST: Custom Pronoun Requests")
    print("=" * 60)
    
    agent = GuardianAgent()
    
    test_cases = [
        # (message, should_approve)
        ("Gọi tôi là công chúa nhé", True),
        ("Gọi tôi là thuyền trưởng", True),
        ("Gọi tôi là đ.m", False),
        ("Xưng hô với tôi là hoàng tử", True),
        ("Bạn là trẫm của tôi nhé", True),
    ]
    
    for msg, should_approve in test_cases:
        print(f"\nMessage: '{msg}'")
        print(f"Expected: {'APPROVE' if should_approve else 'REJECT'}")
        
        result = await agent.validate_pronoun_request(msg)
        
        status = "✅" if result.approved == should_approve else "❌"
        print(f"{status} Result: approved={result.approved}")
        if result.approved:
            print(f"   Pronouns: user_called='{result.user_called}', ai_self='{result.ai_self}'")
        else:
            print(f"   Reason: {result.rejection_reason}")
    
    return True


async def test_contextual_filtering():
    """Test contextual content filtering."""
    print("\n" + "=" * 60)
    print("TEST: Contextual Content Filtering")
    print("=" * 60)
    
    agent = GuardianAgent()
    
    test_cases = [
        # (message, expected_action, context)
        ("Cướp biển là gì trong hàng hải?", "ALLOW", "maritime"),
        ("Rule về piracy trong COLREGs", "ALLOW", "maritime"),
        ("Mày là đồ ngu", "BLOCK", None),
        ("Tao muốn biết về Rule 5", "BLOCK", None),
        ("Tàu cướp biển có quy định gì?", "ALLOW", "maritime"),
    ]
    
    for msg, expected, context in test_cases:
        print(f"\nMessage: '{msg}'")
        print(f"Context: {context or 'None'}")
        print(f"Expected: {expected}")
        
        decision = await agent.validate_message(msg, context=context)
        
        status = "✅" if decision.action == expected else "❌"
        print(f"{status} Result: {decision.action}")
        if decision.reason:
            print(f"   Reason: {decision.reason}")
        print(f"   Used LLM: {decision.used_llm}, Latency: {decision.latency_ms}ms")
    
    return True


async def test_caching():
    """Test decision caching."""
    print("\n" + "=" * 60)
    print("TEST: Decision Caching")
    print("=" * 60)
    
    agent = GuardianAgent()
    
    message = "Giải thích Rule 5 về quan sát"
    
    # First call - should use LLM
    print(f"\nFirst call: '{message}'")
    decision1 = await agent.validate_message(message)
    print(f"Used LLM: {decision1.used_llm}, Cached: {decision1.cached}, Latency: {decision1.latency_ms}ms")
    
    # Second call - should use cache
    print(f"\nSecond call (same message):")
    decision2 = await agent.validate_message(message)
    print(f"Used LLM: {decision2.used_llm}, Cached: {decision2.cached}, Latency: {decision2.latency_ms}ms")
    
    if decision2.cached:
        print("✅ Caching works!")
    else:
        print("❌ Caching not working")
    
    return decision2.cached


async def test_fallback():
    """Test fallback to rule-based filtering."""
    print("\n" + "=" * 60)
    print("TEST: Fallback Mechanism")
    print("=" * 60)
    
    # Create agent with LLM disabled
    config = GuardianConfig(enable_llm=False)
    agent = GuardianAgent(config=config)
    
    test_cases = [
        ("Chào bạn", "ALLOW"),
        ("Mày là đồ ngu", "BLOCK"),
        ("Rule 5 là gì?", "ALLOW"),
    ]
    
    for msg, expected in test_cases:
        print(f"\nMessage: '{msg}'")
        print(f"Expected: {expected}")
        
        decision = await agent.validate_message(msg)
        
        status = "✅" if decision.action == expected else "❌"
        print(f"{status} Result: {decision.action}")
        print(f"   Used LLM: {decision.used_llm} (should be False)")
    
    return True


async def main():
    print("\n🛡️ GUARDIAN AGENT TEST SUITE\n")
    
    test1 = await test_skip_patterns()
    test2 = await test_pronoun_requests()
    test3 = await test_contextual_filtering()
    test4 = await test_caching()
    test5 = await test_fallback()
    
    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)
    print(f"Skip Patterns: {'✅' if test1 else '❌'}")
    print(f"Pronoun Requests: {'✅' if test2 else '❌'}")
    print(f"Contextual Filtering: {'✅' if test3 else '❌'}")
    print(f"Caching: {'✅' if test4 else '❌'}")
    print(f"Fallback: {'✅' if test5 else '❌'}")
    
    if all([test1, test2, test3, test4, test5]):
        print("\n🎉 ALL TESTS PASSED!")
    else:
        print("\n⚠️ SOME TESTS NEED ATTENTION")


if __name__ == "__main__":
    asyncio.run(main())
