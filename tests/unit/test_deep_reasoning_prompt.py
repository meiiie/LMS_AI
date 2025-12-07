"""
Test Deep Reasoning Prompt Injection - CHỈ THỊ SỐ 21
Verify that <thinking> tags instructions are included in system prompt
"""
import sys
sys.path.insert(0, '.')

from app.prompts.prompt_loader import PromptLoader

def test_deep_reasoning_in_prompt():
    print("=" * 70)
    print("TEST: Deep Reasoning Prompt Injection")
    print("=" * 70)
    
    loader = PromptLoader()
    
    # Test 1: Student role (tutor.yaml)
    print("\n[Test 1] Student role - tutor.yaml")
    student_prompt = loader.build_system_prompt(
        role="student",
        user_name="Hùng"
    )
    
    has_thinking = "<thinking>" in student_prompt
    has_deep_reasoning = "DEEP REASONING" in student_prompt
    has_proactive = "proactive" in student_prompt.lower() or "chủ động" in student_prompt.lower()
    
    print(f"  Has <thinking> tags: {'✅' if has_thinking else '❌'}")
    print(f"  Has DEEP REASONING section: {'✅' if has_deep_reasoning else '❌'}")
    print(f"  Has proactive behavior: {'✅' if has_proactive else '❌'}")
    
    if has_deep_reasoning:
        # Find and print the Deep Reasoning section
        start = student_prompt.find("DEEP REASONING")
        end = student_prompt.find("="*60, start + 100)
        if end == -1:
            end = start + 500
        print(f"\n  Deep Reasoning section preview:")
        print(f"  {student_prompt[start:end][:300]}...")
    
    # Test 2: Teacher role (assistant.yaml)
    print("\n[Test 2] Teacher role - assistant.yaml")
    teacher_prompt = loader.build_system_prompt(
        role="teacher",
        user_name="Thầy Nam"
    )
    
    has_thinking_t = "<thinking>" in teacher_prompt
    has_deep_reasoning_t = "DEEP REASONING" in teacher_prompt
    
    print(f"  Has <thinking> tags: {'✅' if has_thinking_t else '❌'}")
    print(f"  Has DEEP REASONING section: {'✅' if has_deep_reasoning_t else '❌'}")
    
    # Test 3: Check prompt length
    print("\n[Test 3] Prompt lengths")
    print(f"  Student prompt: {len(student_prompt)} chars")
    print(f"  Teacher prompt: {len(teacher_prompt)} chars")
    
    # Summary
    print("\n" + "=" * 70)
    all_pass = has_thinking and has_deep_reasoning and has_thinking_t and has_deep_reasoning_t
    if all_pass:
        print("✅ ALL TESTS PASSED - Deep Reasoning is properly injected!")
    else:
        print("❌ SOME TESTS FAILED - Check the results above")
    print("=" * 70)
    
    return all_pass

if __name__ == "__main__":
    test_deep_reasoning_in_prompt()
