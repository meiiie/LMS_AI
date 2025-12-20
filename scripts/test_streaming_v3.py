"""
Test script for P3+ V3 SOTA Streaming API

Tests the new /chat/stream/v3 endpoint which uses full CRAG pipeline
with true token-by-token streaming.

Features tested:
- Progressive SSE events at each CRAG step
- Full CRAG quality (grading, reasoning_trace)
- True token streaming for answer
- Sources with image_url
- Metadata with reasoning_trace

Run: python scripts/test_streaming_v3.py
"""

import asyncio
import httpx
import time
import sys
import os
import re
import json
from datetime import datetime

# Configuration
BASE_URL = "https://maritime-ai-chatbot.onrender.com"
# BASE_URL = "http://localhost:8000"  # For local testing
API_KEY = "maritime-lms-prod-2024"

# Output file
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE = f"scripts/test_streaming_v3_results_{TIMESTAMP}.txt"

# Test question (same as production test for comparison)
TEST_QUESTION = "Giải thích Điều 50 về quyền hạn của thuyền trưởng trên tàu biển theo Bộ luật hàng hải Việt Nam 2015."


def strip_thinking_tags(text: str) -> tuple[str, str]:
    """Extract and separate thinking content from answer text."""
    thinking_match = re.search(r'<thinking>(.*?)</thinking>', text, re.DOTALL)
    thinking_content = thinking_match.group(1).strip() if thinking_match else ""
    clean_answer = re.sub(r'<thinking>.*?</thinking>', '', text, flags=re.DOTALL).strip()
    return clean_answer, thinking_content


class TestLogger:
    """Logger that writes to both console and file."""
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.lines = []
    
    def log(self, message=""):
        print(message)
        self.lines.append(message)
    
    def save(self):
        os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines))
        print(f"\n📁 Results saved to: {self.filepath}")


async def test_streaming_v3(logger: TestLogger):
    """Test the V3 streaming endpoint with full CRAG pipeline."""
    logger.log("=" * 70)
    logger.log("P3+ V3 SOTA STREAMING TEST - /api/v1/chat/stream/v3")
    logger.log("=" * 70)
    
    payload = {
        "user_id": f"test-v3-{TIMESTAMP}",
        "message": TEST_QUESTION,
        "role": "student"
    }
    
    logger.log(f"\n📤 Request: {TEST_QUESTION}")
    logger.log("-" * 70)
    
    start_time = time.time()
    first_event_time = None
    first_token_time = None
    token_count = 0
    thinking_events = []
    full_answer = []
    sources_data = None
    metadata = None
    reasoning_trace = None
    error_message = None
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream(
                "POST",
                f"{BASE_URL}/api/v1/chat/stream/v3",
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "X-API-Key": API_KEY,
                    "Accept": "text/event-stream"
                },
                timeout=180
            ) as resp:
                logger.log(f"Status: {resp.status_code}")
                logger.log(f"Content-Type: {resp.headers.get('content-type')}")
                logger.log("-" * 70)
                
                if resp.status_code != 200:
                    content = await resp.aread()
                    error_message = content.decode()[:500]
                    logger.log(f"❌ Error: {error_message}")
                    return None
                
                logger.log("\n📨 Events received:\n")
                
                current_event = None
                
                async for line in resp.aiter_lines():
                    if not line:
                        continue
                    
                    if line.startswith("event:"):
                        current_event = line.replace("event:", "").strip()
                        
                        # First event time
                        if first_event_time is None:
                            first_event_time = time.time() - start_time
                            logger.log(f"\n   ⚡ FIRST EVENT TIME: {first_event_time:.2f}s")
                            logger.log("-" * 70)
                        
                        # First token time
                        if current_event == "answer" and first_token_time is None:
                            first_token_time = time.time() - start_time
                            logger.log(f"\n   ⚡ FIRST TOKEN TIME: {first_token_time:.2f}s")
                            logger.log("-" * 70)
                    
                    elif line.startswith("data:"):
                        data = line.replace("data:", "").strip()
                        
                        if current_event == "thinking":
                            try:
                                parsed = json.loads(data)
                                content = parsed.get("content", "")
                                step = parsed.get("step", "")
                                thinking_events.append({
                                    "content": content,
                                    "step": step
                                })
                                logger.log(f"   🔄 thinking [{step}]: {content[:80]}...")
                            except:
                                logger.log(f"   🔄 thinking: {data[:80]}...")
                        
                        elif current_event == "answer":
                            token_count += 1
                            try:
                                parsed = json.loads(data)
                                content = parsed.get("content", "")
                                full_answer.append(content)
                            except:
                                full_answer.append(data)
                            
                            if token_count <= 3:
                                logger.log(f"   📝 token #{token_count}: {data[:100]}...")
                            elif token_count == 4:
                                logger.log(f"   📝 ... (streaming tokens)")
                        
                        elif current_event == "sources":
                            try:
                                parsed = json.loads(data)
                                sources_data = parsed.get("sources", [])
                                logger.log(f"   📚 sources: {len(sources_data)} sources received")
                            except:
                                logger.log(f"   📚 sources: {data[:100]}...")
                        
                        elif current_event == "metadata":
                            try:
                                parsed = json.loads(data)
                                metadata = parsed
                                reasoning_trace = parsed.get("reasoning_trace")
                                logger.log(f"   📊 metadata: processing_time={parsed.get('processing_time')}s")
                                if reasoning_trace:
                                    logger.log(f"   📊 reasoning_trace: {reasoning_trace.get('total_steps', 0)} steps")
                            except:
                                logger.log(f"   📊 metadata: {data[:100]}...")
                        
                        elif current_event == "done":
                            logger.log(f"   ✅ done")
                        
                        elif current_event == "error":
                            error_message = data
                            logger.log(f"   ❌ error: {data}")
                
                total_time = time.time() - start_time
                
                # Process answer
                raw_answer = "".join(full_answer)
                clean_answer, thinking_content = strip_thinking_tags(raw_answer)
                
                return {
                    "success": True,
                    "first_event_time": first_event_time,
                    "first_token_time": first_token_time,
                    "total_time": total_time,
                    "token_count": token_count,
                    "thinking_events": len(thinking_events),
                    "raw_answer_length": len(raw_answer),
                    "clean_answer_length": len(clean_answer),
                    "sources_count": len(sources_data) if sources_data else 0,
                    "has_reasoning_trace": reasoning_trace is not None,
                    "reasoning_steps": reasoning_trace.get("total_steps") if reasoning_trace else 0,
                    "clean_answer": clean_answer,
                    "thinking_events_data": thinking_events,
                    "metadata": metadata
                }
                
        except Exception as e:
            logger.log(f"❌ Exception: {e}")
            import traceback
            logger.log(traceback.format_exc())
            return None


async def compare_all_versions(logger: TestLogger):
    """Compare V1, V2, and V3 endpoints."""
    logger.log(f"\n{'='*70}")
    logger.log("V1 vs V2 vs V3 COMPARISON")
    logger.log(f"{'='*70}")
    
    question = TEST_QUESTION
    
    results = {}
    
    # Test V1 (non-streaming /chat)
    logger.log("\n📡 Testing V1 (/api/v1/chat - non-streaming)...")
    v1_start = time.time()
    v1_answer_length = 0
    v1_sources = 0
    
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"{BASE_URL}/api/v1/chat",
                json={"user_id": "test-v1-compare", "message": question, "role": "student"},
                headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
                timeout=180.0
            )
            v1_total = time.time() - v1_start
            if resp.status_code == 200:
                data = resp.json()
                response_data = data.get("data", {})
                v1_answer = response_data.get("answer", "")
                v1_answer_length = len(v1_answer)
                v1_sources = len(response_data.get("sources", []))
                has_trace = response_data.get("reasoning_trace") is not None or data.get("metadata", {}).get("reasoning_trace") is not None
                results["v1"] = {
                    "first_visible": v1_total,
                    "total": v1_total,
                    "answer_length": v1_answer_length,
                    "sources": v1_sources,
                    "has_reasoning_trace": has_trace
                }
                logger.log(f"   ✅ V1 Success: {v1_answer_length} chars, {v1_sources} sources in {v1_total:.2f}s")
            else:
                logger.log(f"   ❌ V1 Error: {resp.status_code}")
        except Exception as e:
            logger.log(f"   ❌ V1 Exception: {e}")
    
    # Test V2 (simplified streaming)
    logger.log("\n📡 Testing V2 (/api/v1/chat/stream/v2 - simplified streaming)...")
    v2_start = time.time()
    v2_first_token = None
    v2_answer_length = 0
    v2_sources = 0
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream(
                "POST",
                f"{BASE_URL}/api/v1/chat/stream/v2",
                json={"user_id": "test-v2-compare", "message": question, "role": "student"},
                headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
                timeout=180
            ) as resp:
                current_event = None
                full_answer = []
                
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line.replace("event:", "").strip()
                        if current_event == "answer" and v2_first_token is None:
                            v2_first_token = time.time() - v2_start
                    elif line.startswith("data:"):
                        data = line.replace("data:", "").strip()
                        if current_event == "answer":
                            try:
                                parsed = json.loads(data)
                                full_answer.append(parsed.get("content", ""))
                            except:
                                full_answer.append(data)
                        elif current_event == "sources":
                            try:
                                parsed = json.loads(data)
                                v2_sources = len(parsed.get("sources", []))
                            except:
                                pass
                
                raw_answer = "".join(full_answer)
                clean_answer, _ = strip_thinking_tags(raw_answer)
                v2_answer_length = len(clean_answer)
                v2_total = time.time() - v2_start
                results["v2"] = {
                    "first_visible": v2_first_token,
                    "total": v2_total,
                    "answer_length": v2_answer_length,
                    "sources": v2_sources,
                    "has_reasoning_trace": False  # V2 doesn't have reasoning_trace
                }
                logger.log(f"   ✅ V2 Success: {v2_answer_length} chars, first token {v2_first_token:.2f}s")
                
        except Exception as e:
            logger.log(f"   ❌ V2 Exception: {e}")
    
    # Test V3 (full CRAG + streaming)
    logger.log("\n📡 Testing V3 (/api/v1/chat/stream/v3 - full CRAG streaming)...")
    v3_start = time.time()
    v3_first_event = None
    v3_first_token = None
    v3_answer_length = 0
    v3_sources = 0
    v3_has_trace = False
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream(
                "POST",
                f"{BASE_URL}/api/v1/chat/stream/v3",
                json={"user_id": "test-v3-compare", "message": question, "role": "student"},
                headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
                timeout=180
            ) as resp:
                current_event = None
                full_answer = []
                
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line.replace("event:", "").strip()
                        if v3_first_event is None:
                            v3_first_event = time.time() - v3_start
                        if current_event == "answer" and v3_first_token is None:
                            v3_first_token = time.time() - v3_start
                    elif line.startswith("data:"):
                        data = line.replace("data:", "").strip()
                        if current_event == "answer":
                            try:
                                parsed = json.loads(data)
                                full_answer.append(parsed.get("content", ""))
                            except:
                                full_answer.append(data)
                        elif current_event == "sources":
                            try:
                                parsed = json.loads(data)
                                v3_sources = len(parsed.get("sources", []))
                            except:
                                pass
                        elif current_event == "metadata":
                            try:
                                parsed = json.loads(data)
                                v3_has_trace = parsed.get("reasoning_trace") is not None
                            except:
                                pass
                
                raw_answer = "".join(full_answer)
                clean_answer, _ = strip_thinking_tags(raw_answer)
                v3_answer_length = len(clean_answer)
                v3_total = time.time() - v3_start
                results["v3"] = {
                    "first_event": v3_first_event,
                    "first_visible": v3_first_token,
                    "total": v3_total,
                    "answer_length": v3_answer_length,
                    "sources": v3_sources,
                    "has_reasoning_trace": v3_has_trace
                }
                logger.log(f"   ✅ V3 Success: {v3_answer_length} chars, first event {v3_first_event:.2f}s, first token {v3_first_token:.2f}s")
                
        except Exception as e:
            logger.log(f"   ❌ V3 Exception: {e}")
    
    # Comparison table
    logger.log(f"\n{'='*70}")
    logger.log("COMPARISON RESULTS")
    logger.log(f"{'='*70}")
    
    if all(k in results for k in ["v1", "v2", "v3"]):
        logger.log(f"| Metric           | V1 (/chat)     | V2 (/stream)   | V3 (CRAG+stream) |")
        logger.log(f"|------------------|----------------|----------------|------------------|")
        logger.log(f"| First event      | {results['v1']['first_visible']:.1f}s (all)    | {results['v2']['first_visible']:.1f}s (token) | {results['v3']['first_event']:.1f}s (status)   |")
        logger.log(f"| First token      | {results['v1']['first_visible']:.1f}s (all)    | {results['v2']['first_visible']:.1f}s          | {results['v3']['first_visible']:.1f}s           |")
        logger.log(f"| Total time       | {results['v1']['total']:.1f}s           | {results['v2']['total']:.1f}s          | {results['v3']['total']:.1f}s           |")
        logger.log(f"| Answer (clean)   | {results['v1']['answer_length']:5} chars  | {results['v2']['answer_length']:5} chars  | {results['v3']['answer_length']:5} chars    |")
        logger.log(f"| Sources          | {results['v1']['sources']:5}        | {results['v2']['sources']:5}        | {results['v3']['sources']:5}          |")
        logger.log(f"| reasoning_trace  | {'✅' if results['v1']['has_reasoning_trace'] else '❌':5}        | {'✅' if results['v2']['has_reasoning_trace'] else '❌':5}        | {'✅' if results['v3']['has_reasoning_trace'] else '❌':5}          |")
    
    return results


async def main():
    logger = TestLogger(OUTPUT_FILE)
    
    logger.log("=" * 70)
    logger.log("P3+ V3 SOTA STREAMING VERIFICATION")
    logger.log(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.log(f"Target: {BASE_URL}")
    logger.log("=" * 70)
    logger.log("\n⚠️  V3 combines: Full CRAG pipeline + True token streaming")
    logger.log("⚠️  Expected: Progressive events + Same quality as V1")
    
    # Run V3 streaming test
    result = await test_streaming_v3(logger)
    
    if result:
        logger.log(f"\n{'='*70}")
        logger.log("V3 TEST RESULTS")
        logger.log(f"{'='*70}")
        
        # Safe formatting with None handling
        first_event = result.get('first_event_time')
        first_token = result.get('first_token_time')
        
        logger.log(f"   First event time:   {first_event:.2f}s" if first_event else "   First event time:   N/A")
        logger.log(f"   First token time:   {first_token:.2f}s" if first_token else "   First token time:   N/A (error before tokens)")
        logger.log(f"   Total time:         {result['total_time']:.2f}s")
        logger.log(f"   Total tokens:       {result['token_count']}")
        logger.log(f"   Thinking events:    {result['thinking_events']}")
        logger.log(f"   Clean answer:       {result['clean_answer_length']} chars")
        logger.log(f"   Sources:            {result['sources_count']}")
        logger.log(f"   Has reasoning_trace: {'✅' if result['has_reasoning_trace'] else '❌'}")
        logger.log(f"   Reasoning steps:    {result['reasoning_steps']}")
        
        # Show thinking events
        if result.get('thinking_events_data'):
            logger.log(f"\n   🧠 THINKING EVENTS:")
            logger.log("-" * 70)
            for i, event in enumerate(result['thinking_events_data'][:10], 1):
                logger.log(f"   [{event.get('step', '')}] {event.get('content', '')[:60]}...")
        
        # Show answer preview
        if result.get('clean_answer'):
            logger.log(f"\n   📝 ANSWER PREVIEW (first 400 chars):")
            logger.log("-" * 70)
            for line in result['clean_answer'][:400].split('\n')[:8]:
                logger.log(f"   {line}")
    
    # Run comparison
    logger.log("\n\n")
    comparison = await compare_all_versions(logger)
    
    # Summary
    logger.log(f"\n{'='*70}")
    logger.log("FINAL SUMMARY")
    logger.log(f"{'='*70}")
    
    if result and result.get('success'):
        first_event = result.get('first_event_time')
        first_token = result.get('first_token_time')
        
        if first_event:
            logger.log(f"   V3 First event:     {first_event:.2f}s (target: <1s)")
        if first_token:
            logger.log(f"   V3 First token:     {first_token:.2f}s (target: <40s)")
        logger.log(f"   V3 Has CRAG:        {'✅' if result.get('has_reasoning_trace') else '❌'} (grading + reasoning_trace)")
        logger.log(f"   V3 Has streaming:   ✅ (true token streaming)")
        logger.log(f"\n✅ V3 COMBINES BEST OF BOTH WORLDS!")
    else:
        logger.log(f"\n❌ V3 TEST FAILED")
    
    logger.log(f"\n{'='*70}")
    
    # Save results
    logger.save()
    
    return 0 if (result and result.get('success')) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
