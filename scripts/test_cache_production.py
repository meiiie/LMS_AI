"""
Test Semantic Cache on Production

Tests cache behavior by making 2 identical queries and comparing response times.

Expected:
- Query 1 (cache miss): ~60-120s
- Query 2 (cache hit): <5s

Usage:
    python scripts/test_cache_production.py
"""

import asyncio
import time
import httpx

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL = "https://maritime-ai-chatbot.onrender.com"
API_PREFIX = "/api/v1"
API_KEY = "secret_key_cho_team_lms"

# Test user
TEST_USER_ID = "cache-test-user-001"
TEST_ROLE = "student"

# Test query - same query will be asked twice
TEST_QUERY = "Điều 15 Bộ luật hàng hải Việt Nam quy định gì về trách nhiệm của chủ tàu?"

# Colors
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


# ============================================================================
# TEST FUNCTION
# ============================================================================

async def make_chat_request(client: httpx.AsyncClient, query: str, attempt: int) -> dict:
    """Make a chat request and return timing + response info."""
    print(f"\n{Colors.BLUE}━━━ Query {attempt} ━━━{Colors.RESET}")
    print(f"Question: {query[:60]}...")
    
    start = time.time()
    
    response = await client.post(
        f"{API_PREFIX}/chat",
        json={
            "message": query,
            "user_id": TEST_USER_ID,
            "role": TEST_ROLE
        },
        headers={
            "X-API-Key": API_KEY,
            "X-User-ID": TEST_USER_ID,
            "X-Role": TEST_ROLE
        },
        timeout=180.0  # 3 minutes timeout
    )
    
    duration = time.time() - start
    
    if response.status_code == 200:
        data = response.json()
        response_data = data.get("data", {})
        answer = response_data.get("answer", "")[:200]
        
        # Check for cache indicators in logs
        cache_hit = "cached" in str(data).lower() or duration < 10
        
        return {
            "success": True,
            "duration_s": duration,
            "answer_preview": answer,
            "cache_hit": cache_hit,
            "full_response": data
        }
    else:
        return {
            "success": False,
            "duration_s": duration,
            "error": response.text[:200],
            "status_code": response.status_code
        }


async def test_cache():
    """Test cache by making 2 identical queries."""
    print(f"\n{Colors.BOLD}╔═══════════════════════════════════════════════════════════╗{Colors.RESET}")
    print(f"{Colors.BOLD}║       SEMANTIC CACHE TEST - Production                     ║{Colors.RESET}")
    print(f"{Colors.BOLD}╚═══════════════════════════════════════════════════════════╝{Colors.RESET}")
    print(f"\nTarget: {BASE_URL}")
    print(f"Query: {TEST_QUERY[:50]}...")
    
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        # Query 1: Should be cache MISS (full pipeline)
        print(f"\n{Colors.YELLOW}⏳ Sending Query 1 (expecting cache MISS)...{Colors.RESET}")
        result1 = await make_chat_request(client, TEST_QUERY, 1)
        
        if result1["success"]:
            print(f"{Colors.GREEN}✓ Query 1 completed in {result1['duration_s']:.1f}s{Colors.RESET}")
            print(f"  Answer: {result1['answer_preview']}...")
        else:
            print(f"{Colors.RED}✗ Query 1 failed: {result1.get('error', 'Unknown')}{Colors.RESET}")
            return
        
        # Small delay to ensure cache is written
        print(f"\n{Colors.BLUE}Waiting 2s for cache write...{Colors.RESET}")
        await asyncio.sleep(2)
        
        # Query 2: Should be cache HIT (fast response)
        print(f"\n{Colors.YELLOW}⏳ Sending Query 2 (expecting cache HIT)...{Colors.RESET}")
        result2 = await make_chat_request(client, TEST_QUERY, 2)
        
        if result2["success"]:
            print(f"{Colors.GREEN}✓ Query 2 completed in {result2['duration_s']:.1f}s{Colors.RESET}")
            print(f"  Answer: {result2['answer_preview']}...")
        else:
            print(f"{Colors.RED}✗ Query 2 failed: {result2.get('error', 'Unknown')}{Colors.RESET}")
            return
        
        # Summary
        print(f"\n{Colors.BOLD}╔═══════════════════════════════════════════════════════════╗{Colors.RESET}")
        print(f"{Colors.BOLD}║                       RESULTS                              ║{Colors.RESET}")
        print(f"{Colors.BOLD}╚═══════════════════════════════════════════════════════════╝{Colors.RESET}")
        
        time1 = result1['duration_s']
        time2 = result2['duration_s']
        speedup = time1 / time2 if time2 > 0 else 0
        
        print(f"\n  Query 1 (Cache Miss): {time1:.1f}s")
        print(f"  Query 2 (Cache Hit):  {time2:.1f}s")
        print(f"  Speedup:              {speedup:.1f}x")
        
        # Determine if cache is working
        if time2 < 10 and speedup > 5:
            print(f"\n  {Colors.GREEN}✓ CACHE IS WORKING! ({speedup:.0f}x speedup){Colors.RESET}")
        elif time2 < time1 * 0.5:
            print(f"\n  {Colors.YELLOW}⚠ Partial cache effect detected{Colors.RESET}")
        else:
            print(f"\n  {Colors.RED}✗ Cache may not be working (no significant speedup){Colors.RESET}")
            print(f"  Note: First run after deploy may not have cache populated")


if __name__ == "__main__":
    asyncio.run(test_cache())
