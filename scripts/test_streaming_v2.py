"""
Test script for P3 SOTA Streaming API v2

Tests the new /chat/stream/v2 endpoint which uses true token-by-token streaming.
Saves detailed results to test_results_*.txt file.

IMPORTANT: Uses same test question as test_production_api.py for fair comparison.

Run: python scripts/test_streaming_v2.py
"""

import asyncio
import httpx
import time
import sys
import os
from datetime import datetime

# Configuration
BASE_URL = "https://maritime-ai-chatbot.onrender.com"
# BASE_URL = "http://localhost:8000"  # For local testing
API_KEY = "maritime-lms-prod-2024"

# Output file
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUTPUT_FILE = f"scripts/test_streaming_v2_results_{TIMESTAMP}.txt"

# SAME QUESTION as test_production_api.py for fair comparison
# Cold path test: Use Điều 50 to avoid semantic cache hits
TEST_QUESTIONS = [
    {
        "question": "Giải thích Điều 50 về quyền hạn của thuyền trưởng trên tàu biển theo Bộ luật hàng hải Việt Nam 2015.",
        "name": "Điều 50 - Quyền hạn thuyền trưởng (same as production_api.py)"
    },
    {
        "question": "Quy tắc 15 COLREGs quy định thế nào về tình huống cắt mũi nhau?",
        "name": "Rule 15 COLREGs - Crossing situation"
    }
]


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


async def test_streaming_v2(logger: TestLogger):
    """Test the new v2 streaming endpoint with true token streaming."""
    logger.log("=" * 70)
    logger.log("P3 SOTA STREAMING TEST - /api/v1/chat/stream/v2")
    logger.log("=" * 70)
    
    results = []
    
    for i, test in enumerate(TEST_QUESTIONS, 1):
        question = test["question"]
        test_name = test["name"]
        
        logger.log(f"\n{'='*70}")
        logger.log(f"TEST {i}/{len(TEST_QUESTIONS)}: {test_name}")
        logger.log(f"{'='*70}")
        
        payload = {
            "user_id": f"test-streaming-v2-{TIMESTAMP}",
            "message": question,
            "role": "student"
        }
        
        logger.log(f"\n📤 Request: {question}")
        logger.log("-" * 70)
        
        start_time = time.time()
        first_token_time = None
        token_count = 0
        thinking_events = []
        full_answer = []  # Collect all answer tokens
        sources_received = False
        sources_count = 0
        error_message = None
        
        async with httpx.AsyncClient() as client:
            try:
                async with client.stream(
                    "POST",
                    f"{BASE_URL}/api/v1/chat/stream/v2",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Key": API_KEY,
                        "Accept": "text/event-stream"
                    },
                    timeout=180  # Same timeout as production test
                ) as resp:
                    logger.log(f"Status: {resp.status_code}")
                    logger.log(f"Content-Type: {resp.headers.get('content-type')}")
                    logger.log("-" * 70)
                    
                    if resp.status_code != 200:
                        content = await resp.aread()
                        error_message = content.decode()[:500]
                        logger.log(f"❌ Error: {error_message}")
                        results.append({
                            "question": question,
                            "name": test_name,
                            "success": False,
                            "error": error_message
                        })
                        continue
                    
                    logger.log("\n📨 Events received:\n")
                    
                    current_event = None
                    
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        
                        if line.startswith("event:"):
                            current_event = line.replace("event:", "").strip()
                            
                            if current_event == "answer" and first_token_time is None:
                                first_token_time = time.time() - start_time
                                logger.log(f"\n   ⚡ FIRST TOKEN TIME: {first_token_time:.2f}s")
                                logger.log("-" * 70)
                        
                        elif line.startswith("data:"):
                            data = line.replace("data:", "").strip()
                            
                            if current_event == "thinking":
                                thinking_events.append(data[:100])
                                logger.log(f"   🔄 thinking: {data[:80]}...")
                            
                            elif current_event == "answer":
                                token_count += 1
                                # Collect FULL answer content
                                try:
                                    import json
                                    parsed = json.loads(data)
                                    content = parsed.get("content", "")
                                    full_answer.append(content)
                                except:
                                    # If not JSON, append raw data
                                    full_answer.append(data)
                                
                                if token_count <= 5:
                                    logger.log(f"   📝 answer token #{token_count}: {data[:80]}...")
                                elif token_count == 6:
                                    logger.log(f"   📝 ... (streaming more tokens)")
                            
                            elif current_event == "sources":
                                sources_received = True
                                try:
                                    import json
                                    parsed = json.loads(data)
                                    if isinstance(parsed, dict) and "sources" in parsed:
                                        sources_count = len(parsed.get("sources", []))
                                    elif isinstance(parsed, list):
                                        sources_count = len(parsed)
                                except:
                                    pass
                                logger.log(f"   📚 sources: {sources_count} sources received")
                            
                            elif current_event == "metadata":
                                logger.log(f"   📊 metadata: {data[:100]}...")
                            
                            elif current_event == "done":
                                logger.log(f"   ✅ done")
                            
                            elif current_event == "error":
                                error_message = data
                                logger.log(f"   ❌ error: {data}")
                    
                    total_time = time.time() - start_time
                    
                    # Join full answer
                    answer_text = "".join(full_answer)
                    answer_length = len(answer_text)
                    
                    logger.log(f"\n{'='*70}")
                    logger.log("TEST RESULTS")
                    logger.log(f"{'='*70}")
                    logger.log(f"   Question:        {question[:60]}...")
                    logger.log(f"   Total tokens:    {token_count}")
                    logger.log(f"   Answer length:   {answer_length} chars")
                    logger.log(f"   Thinking events: {len(thinking_events)}")
                    logger.log(f"   First token:     {first_token_time:.2f}s" if first_token_time else "   First token:     N/A")
                    logger.log(f"   Total time:      {total_time:.2f}s")
                    logger.log(f"   Sources:         {sources_count if sources_received else 'None'}")
                    logger.log(f"   Error:           {error_message or 'None'}")
                    
                    # Show answer preview (first 500 chars)
                    if answer_text:
                        logger.log(f"\n   📝 FULL ANSWER PREVIEW (first 500 chars):")
                        logger.log("-" * 70)
                        preview = answer_text[:500]
                        for line in preview.split('\n'):
                            logger.log(f"   {line}")
                        if len(answer_text) > 500:
                            logger.log(f"   ... ({answer_length - 500} more chars)")
                    else:
                        logger.log(f"\n   ⚠️ NO ANSWER TEXT RECEIVED!")
                    
                    # Evaluate
                    success = (
                        first_token_time is not None and 
                        first_token_time < 40 and  # Allow up to 40s for first token
                        token_count > 0 and
                        answer_length > 100 and  # Must have substantial answer
                        error_message is None
                    )
                    
                    results.append({
                        "question": question,
                        "name": test_name,
                        "success": success,
                        "first_token_time": first_token_time,
                        "total_time": total_time,
                        "token_count": token_count,
                        "answer_length": answer_length,
                        "sources_count": sources_count,
                        "error": error_message
                    })
                    
            except Exception as e:
                logger.log(f"❌ Exception: {e}")
                import traceback
                logger.log(traceback.format_exc())
                results.append({
                    "question": question,
                    "name": test_name,
                    "success": False,
                    "error": str(e)
                })
    
    return results


async def compare_v1_v2(logger: TestLogger):
    """Compare v1 (non-streaming) vs v2 (streaming) using same question."""
    logger.log(f"\n{'='*70}")
    logger.log("V1 (production /chat) vs V2 (streaming) COMPARISON")
    logger.log(f"{'='*70}")
    
    question = "Giải thích Điều 50 về quyền hạn của thuyền trưởng trên tàu biển theo Bộ luật hàng hải Việt Nam 2015."
    
    # Test V1 (non-streaming /chat endpoint)
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
                v1_answer_length = len(response_data.get("answer", ""))
                v1_sources = len(response_data.get("sources", []))
                logger.log(f"   ✅ V1 Success: {v1_answer_length} chars, {v1_sources} sources in {v1_total:.2f}s")
            else:
                logger.log(f"   ❌ V1 Error: {resp.status_code}")
        except Exception as e:
            v1_total = time.time() - v1_start
            logger.log(f"   ❌ V1 Exception: {e}")
    
    # Test V2 (streaming)
    logger.log("\n📡 Testing V2 (/api/v1/chat/stream/v2 - streaming)...")
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
                                import json
                                parsed = json.loads(data)
                                full_answer.append(parsed.get("content", ""))
                            except:
                                full_answer.append(data)
                        elif current_event == "sources":
                            try:
                                import json
                                parsed = json.loads(data)
                                if isinstance(parsed, dict):
                                    v2_sources = len(parsed.get("sources", []))
                            except:
                                pass
                
                v2_answer_length = len("".join(full_answer))
                v2_total = time.time() - v2_start
                logger.log(f"   ✅ V2 Success: {v2_answer_length} chars, {v2_sources} sources")
                logger.log(f"      First token: {v2_first_token:.2f}s, Total: {v2_total:.2f}s")
                
        except Exception as e:
            v2_total = time.time() - v2_start
            logger.log(f"   ❌ V2 Exception: {e}")
    
    logger.log(f"\n{'='*70}")
    logger.log("COMPARISON RESULTS")
    logger.log(f"{'='*70}")
    logger.log(f"| Metric        | V1 (/chat)    | V2 (/stream/v2) | Difference     |")
    logger.log(f"|---------------|---------------|-----------------|----------------|")
    logger.log(f"| First visible | {v1_total:.2f}s (all)   | {v2_first_token:.2f}s (token) | {(v1_total/v2_first_token):.1f}x faster    |" if v2_first_token else "| First visible | N/A           | N/A             | N/A            |")
    logger.log(f"| Total time    | {v1_total:.2f}s        | {v2_total:.2f}s          | {'Similar' if abs(v1_total - v2_total) < 5 else 'Different'}        |")
    logger.log(f"| Answer length | {v1_answer_length} chars   | {v2_answer_length} chars      | {'Similar' if abs(v1_answer_length - v2_answer_length) < 100 else 'DIFFERENT!'}        |")
    logger.log(f"| Sources       | {v1_sources}            | {v2_sources}              | {'Same' if v1_sources == v2_sources else 'Different'}            |")
    
    return {
        "v1_total": v1_total,
        "v1_answer_length": v1_answer_length,
        "v2_first_token": v2_first_token,
        "v2_total": v2_total,
        "v2_answer_length": v2_answer_length,
    }


async def main():
    logger = TestLogger(OUTPUT_FILE)
    
    logger.log("=" * 70)
    logger.log("P3 SOTA STREAMING VERIFICATION")
    logger.log(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.log(f"Target: {BASE_URL}")
    logger.log("=" * 70)
    logger.log("\n⚠️  Using SAME test questions as test_production_api.py for fair comparison")
    
    # Run streaming tests
    results = await test_streaming_v2(logger)
    
    # Run V1 vs V2 comparison
    logger.log("\n\n")
    comparison = await compare_v1_v2(logger)
    
    # Summary
    logger.log(f"\n{'='*70}")
    logger.log("FINAL SUMMARY")
    logger.log(f"{'='*70}")
    
    success_count = sum(1 for r in results if r.get("success"))
    total_count = len(results)
    
    logger.log(f"   Tests passed:     {success_count}/{total_count}")
    
    first_tokens = [r.get("first_token_time") for r in results if r.get("first_token_time")]
    avg_first_token = sum(first_tokens) / len(first_tokens) if first_tokens else 0
    logger.log(f"   Avg first token:  {avg_first_token:.2f}s")
    logger.log(f"   Target:           <40s")
    
    avg_answer_len = sum(r.get("answer_length", 0) for r in results) / len(results)
    logger.log(f"   Avg answer len:   {avg_answer_len:.0f} chars")
    
    if success_count == total_count:
        logger.log(f"\n✅ ALL TESTS PASSED - P3 STREAMING WORKING!")
        status = 0
    else:
        logger.log(f"\n❌ SOME TESTS FAILED")
        for r in results:
            if not r.get("success"):
                logger.log(f"   - {r.get('name', 'Unknown')}: {r.get('error', 'Unknown error')}")
        status = 1
    
    logger.log(f"\n{'='*70}")
    
    # Save results
    logger.save()
    
    return status


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
