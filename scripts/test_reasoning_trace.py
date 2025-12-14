"""
Test script for Reasoning Trace feature

Run: python -m scripts.test_reasoning_trace
"""
import asyncio
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.reasoning_tracer import ReasoningTracer, StepNames, get_reasoning_tracer
from app.models.schemas import ReasoningTrace, ReasoningStep


async def test_reasoning_tracer():
    """Test the ReasoningTracer class"""
    print("=" * 60)
    print("Testing Reasoning Trace (Explainability Layer)")
    print("=" * 60)
    
    # Create tracer
    tracer = get_reasoning_tracer()
    print("\n✅ ReasoningTracer created")
    
    # Simulate RAG pipeline steps
    print("\n📝 Simulating RAG pipeline...")
    
    # Step 1: Query Analysis
    await asyncio.sleep(0.1)  # Simulate work
    tracer.start_step(StepNames.QUERY_ANALYSIS, "Phân tích câu hỏi")
    await asyncio.sleep(0.15)
    tracer.end_step(
        result="Độ phức tạp: MODERATE, Intent: knowledge",
        confidence=0.9,
        details={"complexity": "MODERATE", "intent": "knowledge"}
    )
    print("   Step 1: query_analysis ✅")
    
    # Step 2: Retrieval
    tracer.start_step(StepNames.RETRIEVAL, "Tìm kiếm tài liệu")
    await asyncio.sleep(0.2)
    tracer.end_step(
        result="Tìm thấy 5 tài liệu về Điều 15 COLREGs",
        confidence=0.85,
        details={"doc_count": 5}
    )
    print("   Step 2: retrieval ✅")
    
    # Step 3: Grading
    tracer.start_step(StepNames.GRADING, "Đánh giá độ liên quan")
    await asyncio.sleep(0.18)
    tracer.end_step(
        result="Điểm: 7.5/10 - ĐẠT",
        confidence=0.75,
        details={"score": 7.5, "passed": True}
    )
    print("   Step 3: grading ✅")
    
    # Step 4: Generation
    tracer.start_step(StepNames.GENERATION, "Tạo câu trả lời")
    await asyncio.sleep(0.3)
    tracer.end_step(
        result="Tạo câu trả lời dựa trên 3 nguồn",
        confidence=0.88,
        details={"source_count": 3}
    )
    print("   Step 4: generation ✅")
    
    # Build trace
    trace = tracer.build_trace()
    
    print(f"\n{'=' * 60}")
    print("Reasoning Trace Result")
    print("=" * 60)
    
    print(f"\n📊 Summary:")
    print(f"   Total steps: {trace.total_steps}")
    print(f"   Total duration: {trace.total_duration_ms}ms")
    print(f"   Was corrected: {trace.was_corrected}")
    print(f"   Final confidence: {trace.final_confidence:.2f}")
    
    print(f"\n📋 Steps:")
    for i, step in enumerate(trace.steps):
        print(f"   {i+1}. {step.step_name}")
        print(f"      Description: {step.description}")
        print(f"      Result: {step.result}")
        print(f"      Confidence: {step.confidence}")
        print(f"      Duration: {step.duration_ms}ms")
    
    # Test JSON serialization
    print(f"\n{'=' * 60}")
    print("JSON Serialization")
    print("=" * 60)
    
    trace_json = trace.model_dump()
    print(json.dumps(trace_json, indent=2, ensure_ascii=False)[:1000] + "...")
    
    print(f"\n{'=' * 60}")
    print("Test Complete!")
    print("=" * 60)
    
    return True


async def test_with_correction():
    """Test tracer with query correction"""
    print("\n" + "=" * 60)
    print("Testing with Query Correction")
    print("=" * 60)
    
    tracer = ReasoningTracer()
    
    # Retrieval with no results
    tracer.start_step(StepNames.RETRIEVAL, "Tìm kiếm lần 1")
    tracer.end_step(result="Không tìm thấy tài liệu", confidence=0.0)
    
    # Query rewrite
    tracer.start_step(StepNames.QUERY_REWRITE, "Viết lại query")
    tracer.end_step(result="Query mới: 'Điều 15 COLREGs quy tắc cắt hướng'", confidence=0.8)
    tracer.record_correction("Không tìm thấy tài liệu với query gốc")
    
    # Retry retrieval
    tracer.start_step(StepNames.RETRIEVAL, "Tìm kiếm lần 2")
    tracer.end_step(result="Tìm thấy 3 tài liệu", confidence=0.8)
    
    # Generation
    tracer.start_step(StepNames.GENERATION, "Tạo câu trả lời")
    tracer.end_step(result="Đã tạo câu trả lời", confidence=0.85)
    
    trace = tracer.build_trace()
    
    print(f"\n📊 Correction Test Result:")
    print(f"   Was corrected: {trace.was_corrected}")
    print(f"   Correction reason: {trace.correction_reason}")
    print(f"   Total steps: {trace.total_steps}")
    
    assert trace.was_corrected == True
    assert trace.correction_reason is not None
    
    print("\n✅ Correction test passed!")
    
    return True


if __name__ == "__main__":
    asyncio.run(test_reasoning_tracer())
    asyncio.run(test_with_correction())
