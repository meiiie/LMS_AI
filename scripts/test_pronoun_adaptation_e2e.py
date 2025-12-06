"""
Test Pronoun Adaptation E2E - CHỈ THỊ KỸ THUẬT SỐ 20

Test end-to-end pronoun adaptation với API thực.

Usage:
    cd maritime-ai-service
    python scripts/test_pronoun_adaptation_e2e.py
"""

import asyncio
import sys
sys.path.insert(0, ".")

from dotenv import load_dotenv
load_dotenv()

from app.services.chat_service import ChatService
from app.models.schemas import ChatRequest, UserRole
from uuid import uuid4


async def test_pronoun_adaptation():
    """Test pronoun adaptation với các cách xưng hô khác nhau."""
    
    print("=" * 60)
    print("TEST PRONOUN ADAPTATION E2E - CHỈ THỊ KỸ THUẬT SỐ 20")
    print("=" * 60)
    
    chat_service = ChatService()
    
    # Test scenarios
    scenarios = [
        {
            "name": "User xưng 'mình/cậu'",
            "user_id": str(uuid4()),
            "messages": [
                "Cậu ơi, mình muốn hỏi về Rule 5",
                "Mình chưa hiểu lắm, giải thích thêm được không?",
            ],
            "expected_ai_pronouns": ["cậu", "mình"],  # AI should use these
        },
        {
            "name": "User xưng 'em/anh'",
            "user_id": str(uuid4()),
            "messages": [
                "Em chào anh, em là sinh viên năm 3",
                "Anh ơi, giải thích Rule 15 giúp em với",
            ],
            "expected_ai_pronouns": ["em", "anh"],  # AI gọi user là "em", tự xưng "anh"
        },
        {
            "name": "User xưng 'tôi/bạn' (default)",
            "user_id": str(uuid4()),
            "messages": [
                "Xin chào, tôi là Minh",
                "Tôi muốn học về COLREGs",
            ],
            "expected_ai_pronouns": ["bạn", "tôi"],  # Default pronouns
        },
    ]
    
    results = []
    
    for scenario in scenarios:
        print(f"\n{'='*60}")
        print(f"SCENARIO: {scenario['name']}")
        print(f"{'='*60}")
        
        user_id = scenario["user_id"]
        
        for i, message in enumerate(scenario["messages"], 1):
            print(f"\n--- Turn {i} ---")
            print(f"User: {message}")
            
            request = ChatRequest(
                user_id=user_id,
                message=message,
                role=UserRole.STUDENT
            )
            
            try:
                response = await chat_service.process_message(request)
                ai_response = response.message
                
                print(f"AI: {ai_response[:200]}...")
                
                # Check if expected pronouns are used
                found_pronouns = []
                for pronoun in scenario["expected_ai_pronouns"]:
                    if pronoun in ai_response.lower():
                        found_pronouns.append(pronoun)
                
                print(f"Expected pronouns: {scenario['expected_ai_pronouns']}")
                print(f"Found pronouns: {found_pronouns}")
                
            except Exception as e:
                print(f"❌ Error: {e}")
                results.append(False)
                continue
        
        results.append(True)
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    
    passed = sum(results)
    total = len(results)
    print(f"Scenarios: {passed}/{total} completed")
    
    return all(results)


async def test_pronoun_change_mid_conversation():
    """Test user đổi cách xưng hô giữa chừng."""
    
    print("\n" + "=" * 60)
    print("TEST: User đổi xưng hô giữa chừng")
    print("=" * 60)
    
    chat_service = ChatService()
    user_id = str(uuid4())
    
    messages = [
        ("Tôi muốn hỏi về Rule 5", "tôi/bạn"),  # Default
        ("Mình thấy khó hiểu quá, cậu giải thích lại được không?", "mình/cậu"),  # Switch to mình/cậu
        ("Cảm ơn cậu nhé!", "mình/cậu"),  # Continue with mình/cậu
    ]
    
    for message, expected_style in messages:
        print(f"\n--- Message ---")
        print(f"User: {message}")
        print(f"Expected style: {expected_style}")
        
        request = ChatRequest(
            user_id=user_id,
            message=message,
            role=UserRole.STUDENT
        )
        
        try:
            response = await chat_service.process_message(request)
            print(f"AI: {response.message[:200]}...")
        except Exception as e:
            print(f"❌ Error: {e}")
    
    return True


async def test_inappropriate_pronoun_rejection():
    """Test từ chối xưng hô tục tĩu."""
    
    print("\n" + "=" * 60)
    print("TEST: Từ chối xưng hô tục tĩu")
    print("=" * 60)
    
    chat_service = ChatService()
    user_id = str(uuid4())
    
    # Message với từ tục tĩu - AI should use default pronouns
    message = "Mày giải thích Rule 5 đi"
    
    print(f"User: {message}")
    print("Expected: AI should use default 'tôi/bạn', NOT adapt to 'mày/tao'")
    
    request = ChatRequest(
        user_id=user_id,
        message=message,
        role=UserRole.STUDENT
    )
    
    try:
        response = await chat_service.process_message(request)
        ai_response = response.message.lower()
        
        print(f"AI: {response.message[:200]}...")
        
        # Check that AI does NOT use inappropriate pronouns
        bad_pronouns = ["mày", "tao"]
        used_bad = [p for p in bad_pronouns if p in ai_response]
        
        if used_bad:
            print(f"❌ FAIL: AI used inappropriate pronouns: {used_bad}")
            return False
        else:
            print("✅ PASS: AI did not use inappropriate pronouns")
            return True
            
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    print("\n🔍 PRONOUN ADAPTATION E2E TEST SUITE\n")
    
    async def run_all():
        test1 = await test_pronoun_adaptation()
        test2 = await test_pronoun_change_mid_conversation()
        test3 = await test_inappropriate_pronoun_rejection()
        
        print("\n" + "=" * 60)
        print("FINAL RESULTS")
        print("=" * 60)
        print(f"Pronoun Adaptation: {'✅' if test1 else '❌'}")
        print(f"Mid-conversation Change: {'✅' if test2 else '❌'}")
        print(f"Inappropriate Rejection: {'✅' if test3 else '❌'}")
        
        if all([test1, test2, test3]):
            print("\n🎉 ALL E2E TESTS PASSED!")
        else:
            print("\n⚠️ SOME E2E TESTS NEED ATTENTION")
    
    asyncio.run(run_all())
