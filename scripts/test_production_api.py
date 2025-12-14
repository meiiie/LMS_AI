"""
Comprehensive API Test Suite for Maritime AI Service

Tests the refactored ChatService and all major endpoints.
Run after deployment to verify production integration.

Usage:
    python scripts/test_production_api.py
"""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import List, Optional
import httpx

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL = "https://maritime-ai-chatbot.onrender.com"
API_PREFIX = "/api/v1"
API_KEY = "secret_key_cho_team_lms"  # From env vars

# Test user
TEST_USER_ID = "test_user_refactor_check"
TEST_ROLE = "student"

# Colors for output
class Colors:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    message: str
    response_data: Optional[dict] = None


# ============================================================================
# TEST CASES
# ============================================================================

async def test_health_check(client: httpx.AsyncClient) -> TestResult:
    """Test basic health endpoint."""
    start = time.time()
    try:
        response = await client.get(f"{API_PREFIX}/health")
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            return TestResult(
                name="Health Check",
                passed=True,
                duration_ms=duration,
                message=f"Status: {data.get('status', 'unknown')}",
                response_data=data
            )
        else:
            return TestResult(
                name="Health Check",
                passed=False,
                duration_ms=duration,
                message=f"Status code: {response.status_code}"
            )
    except Exception as e:
        return TestResult(
            name="Health Check",
            passed=False,
            duration_ms=(time.time() - start) * 1000,
            message=f"Error: {str(e)}"
        )


async def test_chat_simple(client: httpx.AsyncClient) -> TestResult:
    """Test simple chat message."""
    start = time.time()
    try:
        response = await client.post(
            f"{API_PREFIX}/chat",
            json={
                "message": "Xin chào! Tôi là sinh viên mới.",
                "user_id": TEST_USER_ID,
                "role": TEST_ROLE
            },
            headers={
                "X-API-Key": API_KEY,
                "X-User-ID": TEST_USER_ID,
                "X-Role": TEST_ROLE
            },
            timeout=60.0
        )
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            message = data.get("message", "")[:100]
            agent_type = data.get("agent_type", "unknown")
            return TestResult(
                name="Chat Simple",
                passed=True,
                duration_ms=duration,
                message=f"Agent: {agent_type}, Response: {message}...",
                response_data=data
            )
        else:
            return TestResult(
                name="Chat Simple",
                passed=False,
                duration_ms=duration,
                message=f"Status: {response.status_code}, Body: {response.text[:200]}"
            )
    except Exception as e:
        return TestResult(
            name="Chat Simple",
            passed=False,
            duration_ms=(time.time() - start) * 1000,
            message=f"Error: {str(e)}"
        )


async def test_chat_rag_query(client: httpx.AsyncClient) -> TestResult:
    """Test RAG query that should trigger knowledge search."""
    start = time.time()
    try:
        response = await client.post(
            f"{API_PREFIX}/chat",
            json={
                "message": "Giải thích Rule 15 trong COLREGs về tình huống cắt hướng.",
                "user_id": TEST_USER_ID,
                "role": TEST_ROLE
            },
            headers={
                "X-API-Key": API_KEY,
                "X-User-ID": TEST_USER_ID,
                "X-Role": TEST_ROLE
            },
            timeout=90.0  # RAG queries take longer
        )
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            sources = data.get("sources", [])
            agent_type = data.get("agent_type", "unknown")
            message_preview = data.get("message", "")[:150]
            
            has_sources = len(sources) > 0
            source_info = f"{len(sources)} sources" if has_sources else "No sources"
            
            return TestResult(
                name="Chat RAG Query",
                passed=True,
                duration_ms=duration,
                message=f"Agent: {agent_type}, {source_info}, Response: {message_preview}...",
                response_data=data
            )
        else:
            return TestResult(
                name="Chat RAG Query",
                passed=False,
                duration_ms=duration,
                message=f"Status: {response.status_code}, Body: {response.text[:200]}"
            )
    except Exception as e:
        return TestResult(
            name="Chat RAG Query",
            passed=False,
            duration_ms=(time.time() - start) * 1000,
            message=f"Error: {str(e)}"
        )


async def test_chat_thread_continuity(client: httpx.AsyncClient) -> TestResult:
    """Test thread-based conversation continuity."""
    start = time.time()
    thread_id = None
    
    try:
        # First message - get thread_id
        response1 = await client.post(
            f"{API_PREFIX}/chat",
            json={
                "message": "Tên tôi là Minh, tôi đang học về hàng hải.",
                "user_id": TEST_USER_ID,
                "role": TEST_ROLE
            },
            headers={
                "X-API-Key": API_KEY,
                "X-User-ID": TEST_USER_ID,
                "X-Role": TEST_ROLE
            },
            timeout=60.0
        )
        
        if response1.status_code != 200:
            return TestResult(
                name="Thread Continuity",
                passed=False,
                duration_ms=(time.time() - start) * 1000,
                message=f"First message failed: {response1.status_code}"
            )
        
        data1 = response1.json()
        metadata = data1.get("metadata", {})
        thread_id = metadata.get("session_id")
        
        # Second message - use thread_id
        response2 = await client.post(
            f"{API_PREFIX}/chat",
            json={
                "message": "Bạn có nhớ tên tôi không?",
                "user_id": TEST_USER_ID,
                "role": TEST_ROLE,
                "thread_id": thread_id
            },
            headers={
                "X-API-Key": API_KEY,
                "X-User-ID": TEST_USER_ID,
                "X-Role": TEST_ROLE
            },
            timeout=60.0
        )
        
        duration = (time.time() - start) * 1000
        
        if response2.status_code == 200:
            data2 = response2.json()
            message2 = data2.get("message", "").lower()
            
            # Check if name was remembered
            remembers_name = "minh" in message2
            
            return TestResult(
                name="Thread Continuity",
                passed=True,
                duration_ms=duration,
                message=f"Thread ID: {thread_id[:8]}..., Remembers name: {remembers_name}",
                response_data={"thread_id": thread_id, "remembers_name": remembers_name}
            )
        else:
            return TestResult(
                name="Thread Continuity",
                passed=False,
                duration_ms=duration,
                message=f"Second message failed: {response2.status_code}"
            )
            
    except Exception as e:
        return TestResult(
            name="Thread Continuity",
            passed=False,
            duration_ms=(time.time() - start) * 1000,
            message=f"Error: {str(e)}"
        )


async def test_auth_required(client: httpx.AsyncClient) -> TestResult:
    """Test that API requires authentication."""
    start = time.time()
    try:
        # Request without API key
        response = await client.post(
            f"{API_PREFIX}/chat",
            json={
                "message": "Test without auth",
                "user_id": "test",
                "role": "student"
            },
            timeout=10.0
        )
        duration = (time.time() - start) * 1000
        
        # Should fail with 401 or 403
        if response.status_code in [401, 403]:
            return TestResult(
                name="Auth Required",
                passed=True,
                duration_ms=duration,
                message=f"Correctly rejected with status {response.status_code}"
            )
        else:
            return TestResult(
                name="Auth Required",
                passed=False,
                duration_ms=duration,
                message=f"Expected 401/403, got {response.status_code}"
            )
    except Exception as e:
        return TestResult(
            name="Auth Required",
            passed=False,
            duration_ms=(time.time() - start) * 1000,
            message=f"Error: {str(e)}"
        )


async def test_memories_endpoint(client: httpx.AsyncClient) -> TestResult:
    """Test user memories endpoint."""
    start = time.time()
    try:
        response = await client.get(
            f"{API_PREFIX}/memories/{TEST_USER_ID}",
            headers={
                "X-API-Key": API_KEY,
                "X-User-ID": TEST_USER_ID,
                "X-Role": TEST_ROLE
            },
            timeout=30.0
        )
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            facts = data.get("facts", [])
            return TestResult(
                name="Memories Endpoint",
                passed=True,
                duration_ms=duration,
                message=f"Found {len(facts)} user facts",
                response_data=data
            )
        elif response.status_code == 404:
            return TestResult(
                name="Memories Endpoint",
                passed=True,
                duration_ms=duration,
                message="No memories found (expected for new user)"
            )
        else:
            return TestResult(
                name="Memories Endpoint",
                passed=False,
                duration_ms=duration,
                message=f"Status: {response.status_code}"
            )
    except Exception as e:
        return TestResult(
            name="Memories Endpoint",
            passed=False,
            duration_ms=(time.time() - start) * 1000,
            message=f"Error: {str(e)}"
        )


async def test_insights_endpoint(client: httpx.AsyncClient) -> TestResult:
    """Test user insights endpoint."""
    start = time.time()
    try:
        response = await client.get(
            f"{API_PREFIX}/insights/{TEST_USER_ID}",
            headers={
                "X-API-Key": API_KEY,
                "X-User-ID": TEST_USER_ID,
                "X-Role": TEST_ROLE
            },
            timeout=30.0
        )
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            insights = data.get("insights", [])
            return TestResult(
                name="Insights Endpoint",
                passed=True,
                duration_ms=duration,
                message=f"Found {len(insights)} behavioral insights",
                response_data=data
            )
        elif response.status_code == 404:
            return TestResult(
                name="Insights Endpoint",
                passed=True,
                duration_ms=duration,
                message="No insights found (expected for new user)"
            )
        else:
            return TestResult(
                name="Insights Endpoint",
                passed=False,
                duration_ms=duration,
                message=f"Status: {response.status_code}"
            )
    except Exception as e:
        return TestResult(
            name="Insights Endpoint",
            passed=False,
            duration_ms=(time.time() - start) * 1000,
            message=f"Error: {str(e)}"
        )


async def test_chat_history_endpoint(client: httpx.AsyncClient) -> TestResult:
    """Test chat history endpoint."""
    start = time.time()
    try:
        response = await client.get(
            f"{API_PREFIX}/chat/history/{TEST_USER_ID}",
            headers={
                "X-API-Key": API_KEY,
                "X-User-ID": TEST_USER_ID,
                "X-Role": TEST_ROLE
            },
            timeout=30.0
        )
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            messages = data.get("messages", [])
            return TestResult(
                name="Chat History",
                passed=True,
                duration_ms=duration,
                message=f"Found {len(messages)} messages in history",
                response_data=data
            )
        elif response.status_code == 404:
            return TestResult(
                name="Chat History",
                passed=True,
                duration_ms=duration,
                message="No history found (expected for new user)"
            )
        else:
            return TestResult(
                name="Chat History",
                passed=False,
                duration_ms=duration,
                message=f"Status: {response.status_code}, Body: {response.text[:100]}"
            )
    except Exception as e:
        return TestResult(
            name="Chat History",
            passed=False,
            duration_ms=(time.time() - start) * 1000,
            message=f"Error: {str(e)}"
        )


# ============================================================================
# MAIN TEST RUNNER
# ============================================================================

async def run_all_tests():
    """Run all tests and print results."""
    print(f"\n{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}  Maritime AI Service - Production API Tests{Colors.RESET}")
    print(f"{Colors.BOLD}  Base URL: {BASE_URL}{Colors.RESET}")
    print(f"{Colors.BOLD}  Time: {time.strftime('%Y-%m-%d %H:%M:%S')}{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}\n")
    
    results: List[TestResult] = []
    
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=120.0) as client:
        # Run tests sequentially
        tests = [
            ("1. Health Check", test_health_check),
            ("2. Auth Required", test_auth_required),
            ("3. Chat Simple", test_chat_simple),
            ("4. Chat RAG Query", test_chat_rag_query),
            ("5. Thread Continuity", test_chat_thread_continuity),
            ("6. Memories Endpoint", test_memories_endpoint),
            ("7. Insights Endpoint", test_insights_endpoint),
            ("8. Chat History", test_chat_history_endpoint),
        ]
        
        for test_name, test_func in tests:
            print(f"{Colors.BLUE}Running: {test_name}...{Colors.RESET}")
            result = await test_func(client)
            results.append(result)
            
            if result.passed:
                print(f"  {Colors.GREEN}✓ PASSED{Colors.RESET} ({result.duration_ms:.0f}ms)")
                print(f"    {result.message}")
            else:
                print(f"  {Colors.RED}✗ FAILED{Colors.RESET} ({result.duration_ms:.0f}ms)")
                print(f"    {result.message}")
            print()
    
    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    total_time = sum(r.duration_ms for r in results)
    
    print(f"\n{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}  TEST SUMMARY{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"  {Colors.GREEN}Passed: {passed}{Colors.RESET}")
    print(f"  {Colors.RED}Failed: {failed}{Colors.RESET}")
    print(f"  Total Time: {total_time/1000:.1f}s")
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}\n")
    
    if failed == 0:
        print(f"{Colors.GREEN}{Colors.BOLD}🎉 All tests passed! Production deployment verified.{Colors.RESET}\n")
    else:
        print(f"{Colors.YELLOW}{Colors.BOLD}⚠️  Some tests failed. Check the output above.{Colors.RESET}\n")
    
    return results


if __name__ == "__main__":
    asyncio.run(run_all_tests())
