"""
Test script for P3 SOTA Streaming API v2

Tests the new /chat/stream/v2 endpoint which uses true token-by-token streaming.
Saves detailed results to test_results_*.txt file.

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


class TestLogger:
    """Logger that writes to both console and file."""
    
    def __init__(self, filepath):
        self.filepath = filepath
        self.lines = []
    
    def log(self, message=""):
        print(message)
        self.lines.append(message)
    
    def save(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(self.lines))
        print(f"\n📁 Results saved to: {self.filepath}")


async def test_streaming_v2(logger: TestLogger):
    """Test the new v2 streaming endpoint with true token streaming."""
    logger.log("=" * 70)
    logger.log("P3 SOTA STREAMING TEST - /api/v1/chat/stream/v2")
    logger.log("=" * 70)
    
    test_questions = [
        "Điều 15 Luật Hàng hải 2015 quy định gì về thuyền trưởng?",
        "Quy tắc 15 COLREGs quy định thế nào?",
    ]
    
    results = []
    
    for i, question in enumerate(test_questions, 1):
        logger.log(f"\n{'='*70}")
        logger.log(f"TEST {i}/{len(test_questions)}")
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
        answer_preview = ""
        sources_received = False
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
                    timeout=120
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
                                # Collect answer content
                                try:
                                    import json
                                    parsed = json.loads(data)
                                    content = parsed.get("content", "")
                                    if len(answer_preview) < 200:
                                        answer_preview += content
                                except:
                                    pass
                                
                                if token_count <= 3:
                                    logger.log(f"   📝 answer token #{token_count}: {data[:60]}...")
                                elif token_count == 4:
                                    logger.log(f"   📝 ... (streaming {token_count}+ tokens)")
                            
                            elif current_event == "sources":
                                sources_received = True
                                logger.log(f"   📚 sources: {data[:100]}...")
                            
                            elif current_event == "metadata":
                                logger.log(f"   📊 metadata: {data[:100]}...")
                            
                            elif current_event == "done":
                                logger.log(f"   ✅ done")
                            
                            elif current_event == "error":
                                error_message = data
                                logger.log(f"   ❌ error: {data}")
                    
                    total_time = time.time() - start_time
                    
                    logger.log(f"\n{'='*70}")
                    logger.log("TEST RESULTS")
                    logger.log(f"{'='*70}")
                    logger.log(f"   Question:        {question[:50]}...")
                    logger.log(f"   Total tokens:    {token_count}")
                    logger.log(f"   Thinking events: {len(thinking_events)}")
                    logger.log(f"   First token:     {first_token_time:.2f}s" if first_token_time else "   First token:     N/A")
                    logger.log(f"   Total time:      {total_time:.2f}s")
                    logger.log(f"   Sources:         {'✅' if sources_received else '❌'}")
                    logger.log(f"   Error:           {error_message or 'None'}")
                    
                    if answer_preview:
                        logger.log(f"\n   Answer preview:")
                        logger.log(f"   {answer_preview[:200]}...")
                    
                    # Evaluate
                    success = (
                        first_token_time is not None and 
                        first_token_time < 30 and 
                        token_count > 0 and
                        error_message is None
                    )
                    
                    results.append({
                        "question": question,
                        "success": success,
                        "first_token_time": first_token_time,
                        "total_time": total_time,
                        "token_count": token_count,
                        "sources_received": sources_received,
                        "error": error_message
                    })
                    
            except Exception as e:
                logger.log(f"❌ Exception: {e}")
                import traceback
                logger.log(traceback.format_exc())
                results.append({
                    "question": question,
                    "success": False,
                    "error": str(e)
                })
    
    return results


async def compare_v1_v2(logger: TestLogger):
    """Compare v1 (fake streaming) vs v2 (true streaming)."""
    logger.log(f"\n{'='*70}")
    logger.log("V1 vs V2 COMPARISON TEST")
    logger.log(f"{'='*70}")
    
    question = "Điều 50 Luật Hàng hải quy định gì?"
    
    # Test V1
    logger.log("\n📡 Testing V1 (/chat/stream)...")
    v1_start = time.time()
    v1_first_token = None
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream(
                "POST",
                f"{BASE_URL}/api/v1/chat/stream",
                json={"user_id": "test-v1", "message": question, "role": "student"},
                headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
                timeout=120
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("event: answer") and v1_first_token is None:
                        v1_first_token = time.time() - v1_start
        except Exception as e:
            logger.log(f"   V1 Error: {e}")
    
    v1_total = time.time() - v1_start
    
    # Test V2
    logger.log("📡 Testing V2 (/chat/stream/v2)...")
    v2_start = time.time()
    v2_first_token = None
    
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream(
                "POST",
                f"{BASE_URL}/api/v1/chat/stream/v2",
                json={"user_id": "test-v2", "message": question, "role": "student"},
                headers={"Content-Type": "application/json", "X-API-Key": API_KEY},
                timeout=120
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("event: answer") and v2_first_token is None:
                        v2_first_token = time.time() - v2_start
        except Exception as e:
            logger.log(f"   V2 Error: {e}")
    
    v2_total = time.time() - v2_start
    
    logger.log(f"\n{'='*70}")
    logger.log("COMPARISON RESULTS")
    logger.log(f"{'='*70}")
    logger.log(f"| Metric        | V1 (old)     | V2 (new)     | Improvement |")
    logger.log(f"|---------------|--------------|--------------|-------------|")
    
    v1_ft = f"{v1_first_token:.2f}s" if v1_first_token else "N/A"
    v2_ft = f"{v2_first_token:.2f}s" if v2_first_token else "N/A"
    
    if v1_first_token and v2_first_token:
        improvement = f"{(v1_first_token / v2_first_token):.1f}x faster"
    else:
        improvement = "N/A"
    
    logger.log(f"| First token   | {v1_ft:12} | {v2_ft:12} | {improvement:11} |")
    logger.log(f"| Total time    | {v1_total:.2f}s        | {v2_total:.2f}s        | -           |")
    
    return {
        "v1_first_token": v1_first_token,
        "v2_first_token": v2_first_token,
        "v1_total": v1_total,
        "v2_total": v2_total
    }


async def main():
    logger = TestLogger(OUTPUT_FILE)
    
    logger.log("=" * 70)
    logger.log("P3 SOTA STREAMING VERIFICATION")
    logger.log(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.log(f"Target: {BASE_URL}")
    logger.log("=" * 70)
    
    # Run streaming tests
    results = await test_streaming_v2(logger)
    
    # Run comparison
    # comparison = await compare_v1_v2(logger)  # Uncomment to run comparison
    
    # Summary
    logger.log(f"\n{'='*70}")
    logger.log("FINAL SUMMARY")
    logger.log(f"{'='*70}")
    
    success_count = sum(1 for r in results if r.get("success"))
    total_count = len(results)
    
    logger.log(f"   Tests passed:    {success_count}/{total_count}")
    
    avg_first_token = sum(r.get("first_token_time", 0) or 0 for r in results) / max(len(results), 1)
    logger.log(f"   Avg first token: {avg_first_token:.2f}s")
    logger.log(f"   Target:          <30s")
    
    if success_count == total_count:
        logger.log(f"\n✅ ALL TESTS PASSED")
        status = 0
    else:
        logger.log(f"\n❌ SOME TESTS FAILED")
        for r in results:
            if not r.get("success"):
                logger.log(f"   - {r.get('question', 'Unknown')[:40]}: {r.get('error', 'Unknown error')}")
        status = 1
    
    logger.log(f"\n{'='*70}")
    
    # Save results
    logger.save()
    
    return status


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
