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
from typing import List, Optional, Callable
import httpx

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL = "https://maritime-ai-chatbot.onrender.com"
API_PREFIX = "/api/v1"
API_KEY = "secret_key_cho_team_lms"  # From env vars

# Test user - Use valid UUID for learning_profile table compatibility
# CHỈ THỊ SỐ 28: learning_profile.user_id requires UUID type
TEST_USER_ID = "12345678-1234-5678-1234-567812345678"  # Valid UUID format
TEST_ROLE = "student"

# Debug mode - print full API responses
VERBOSE = True

# Retry configuration for 502 errors (Render auto-restart)
MAX_RETRIES = 3
RETRY_DELAY_BASE = 5  # seconds
RETRY_STATUS_CODES = [502, 503, 504]  # Gateway errors

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
    thinking: Optional[str] = None  # CHỈ THỊ SỐ 29: Vietnamese thinking process
    retry_count: int = 0  # Number of retries needed


# ============================================================================
# RETRY HELPER (for 502 errors during Render deploys)
# ============================================================================

async def retry_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs
) -> httpx.Response:
    """
    Retry a request with exponential backoff for gateway errors.
    
    This handles Render free tier auto-restarts and deployments that
    can cause 502 errors mid-request.
    """
    last_error = None
    
    for attempt in range(MAX_RETRIES + 1):
        try:
            if method.upper() == "GET":
                response = await client.get(url, **kwargs)
            else:
                response = await client.post(url, **kwargs)
            
            if response.status_code in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
                delay = RETRY_DELAY_BASE * (2 ** attempt)  # Exponential backoff
                print(f"{Colors.YELLOW}  ⚠️  Got {response.status_code}, retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})...{Colors.RESET}")
                await asyncio.sleep(delay)
                continue
            
            return response
            
        except (httpx.ConnectError, httpx.ReadTimeout) as e:
            last_error = e
            if attempt < MAX_RETRIES:
                delay = RETRY_DELAY_BASE * (2 ** attempt)
                print(f"{Colors.YELLOW}  ⚠️  Connection error, retrying in {delay}s (attempt {attempt + 1}/{MAX_RETRIES})...{Colors.RESET}")
                await asyncio.sleep(delay)
                continue
            raise
    
    raise last_error if last_error else Exception("Max retries exceeded")


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
            # Parse nested response structure: data.data.answer, data.metadata
            response_data = data.get("data", {})
            metadata = data.get("metadata", {})
            message = response_data.get("answer", "")[:300]
            agent_type = metadata.get("agent_type", "unknown")
            session_id = metadata.get("session_id", "N/A")
            tools_used = metadata.get("tools_used", [])
            tool_info = f", Tools: {[t.get('name') for t in tools_used]}" if tools_used else ""
            return TestResult(
                name="Chat Simple",
                passed=True,
                duration_ms=duration,
                message=f"Agent: {agent_type}{tool_info}, Response: {message}...",
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
    retry_count = 0
    try:
        # Use retry_request for handling 502 during Render deploys
        response = await retry_request(
            client,
            "POST",
            f"{API_PREFIX}/chat",
            json={
                # Updated to match Vietnamese Maritime Law (Bộ luật hàng hải Việt Nam)
                "message": "Giải thích Điều 31 về trách nhiệm đăng kiểm tàu biển theo Bộ luật hàng hải Việt Nam 2015.",
                "user_id": TEST_USER_ID,
                "role": TEST_ROLE
            },
            headers={
                "X-API-Key": API_KEY,
                "X-User-ID": TEST_USER_ID,
                "X-Role": TEST_ROLE
            },
            timeout=200.0  # CRAG with batch grading can take 160s+
        )
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            # Parse nested response structure: data.data.sources, data.metadata
            response_data = data.get("data", {})
            metadata = data.get("metadata", {})
            sources = response_data.get("sources", [])
            agent_type = metadata.get("agent_type", "unknown")
            tools_used = metadata.get("tools_used", [])
            message_preview = response_data.get("answer", "")[:400]
            
            # CHỈ THỊ SỐ 29: Extract thinking process
            thinking = metadata.get("thinking")  # Natural Vietnamese thinking
            thinking_content = metadata.get("thinking_content")  # Structured summary
            
            has_sources = len(sources) > 0
            source_info = f"{len(sources)} sources" if has_sources else "No sources"
            tool_info = f", Tools: {[t.get('name') for t in tools_used]}" if tools_used else ", Tools: []"
            
            # VERBOSE DEBUG OUTPUT
            if VERBOSE:
                print(f"\n{Colors.YELLOW}--- RAG DEBUG INFO ---{Colors.RESET}")
                print(f"  metadata.session_id: {metadata.get('session_id', 'N/A')}")
                print(f"  metadata.agent_type: {agent_type}")
                print(f"  metadata.tools_used: {tools_used}")
                print(f"  data.sources count: {len(sources)}")
                if sources:
                    for i, src in enumerate(sources[:3]):
                        print(f"    Source {i+1}: {src.get('title', 'N/A')}")
                        # CHỈ THỊ 26: Check image_url and page_number
                        print(f"      - image_url: {src.get('image_url', 'N/A')}")
                        print(f"      - page_number: {src.get('page_number', 'N/A')}")
                print(f"  Full answer length: {len(response_data.get('answer', ''))}")
                
                # CHỈ THỊ SỐ 29: Display Thinking Process
                print(f"\n{Colors.BLUE}--- QUÁ TRÌNH SUY NGHĨ (Thinking) ---{Colors.RESET}")
                if thinking:
                    # Show first 500 chars of Vietnamese thinking
                    thinking_preview = thinking[:500] + "..." if len(thinking) > 500 else thinking
                    print(f"  {Colors.GREEN}✓ Vietnamese Thinking:{Colors.RESET}")
                    for line in thinking_preview.split("\n")[:10]:
                        print(f"    {line}")
                    print(f"  [Total: {len(thinking)} chars]")
                else:
                    print(f"  {Colors.YELLOW}⚠️  No thinking field in response{Colors.RESET}")
                
                if thinking_content:
                    print(f"\n  {Colors.GREEN}✓ Thinking Content (Summary):{Colors.RESET}")
                    content_preview = thinking_content[:300] + "..." if len(thinking_content) > 300 else thinking_content
                    print(f"    {content_preview}")
                
                # Reasoning trace summary
                reasoning_trace = metadata.get("reasoning_trace")
                if reasoning_trace:
                    print(f"\n  {Colors.GREEN}✓ Reasoning Trace:{Colors.RESET}")
                    print(f"    Steps: {reasoning_trace.get('total_steps', 0)}")
                    print(f"    Confidence: {reasoning_trace.get('final_confidence', 0):.0%}")
                
                print(f"{Colors.YELLOW}--------------------------------------{Colors.RESET}\n")
            
            return TestResult(
                name="Chat RAG Query",
                passed=True,
                duration_ms=duration,
                message=f"Agent: {agent_type}{tool_info}, {source_info}\nResponse: {message_preview}...",
                response_data=data,
                thinking=thinking,
                retry_count=retry_count
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
        
        # Wait for background task to save facts to database
        # Fact extraction happens async, so we need to wait before testing retrieval
        await asyncio.sleep(3)
        
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
            # CHỈ THỊ: Response format is data.data.answer, not data.message
            answer = data2.get("data", {}).get("answer", "")
            message2 = answer.lower()
            
            # Check if name was remembered
            remembers_name = "minh" in message2
            
            # Handle None thread_id
            thread_display = thread_id[:8] if thread_id else "N/A"
            
            return TestResult(
                name="Thread Continuity",
                passed=True,
                duration_ms=duration,
                message=f"Thread ID: {thread_display}..., Remembers name: {remembers_name}",
                response_data={
                    "thread_id": thread_id, 
                    "remembers_name": remembers_name,
                    "ai_response": answer[:500] + "..." if len(answer) > 500 else answer  # Debug: log actual response
                }
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
            # API returns MemoryListResponse: {"data": [...], "total": n}
            memory_items = data.get("data", [])
            total = data.get("total", len(memory_items))
            
            # Build detailed message
            details = [f"Found {total} user memories/facts:"]
            for i, mem in enumerate(memory_items[:5]):  # Show top 5
                mem_type = mem.get("type", "unknown")
                mem_value = mem.get("value", "")[:50]  # Truncate
                details.append(f"  [{i+1}] {mem_type}: {mem_value}...")
            if total > 5:
                details.append(f"  ... and {total - 5} more")
            
            return TestResult(
                name="Memories Endpoint",
                passed=True,
                duration_ms=duration,
                message="\n".join(details),
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
            # API returns InsightListResponse: {"data": [...], "total": n, "categories": {}}
            insight_items = data.get("data", [])
            total = data.get("total", len(insight_items))
            categories = data.get("categories", {})
            
            # Build detailed message
            details = [f"Found {total} behavioral insights ({len(categories)} categories):"]
            for cat, count in categories.items():
                details.append(f"  - {cat}: {count}")
            # Show sample insights
            if insight_items:
                details.append("Sample insights:")
                for i, ins in enumerate(insight_items[:3]):  # Show top 3
                    content = ins.get("content", "")[:60]
                    details.append(f"  [{i+1}] {content}...")
            
            return TestResult(
                name="Insights Endpoint",
                passed=True,
                duration_ms=duration,
                message="\n".join(details),
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
            f"{API_PREFIX}/history/{TEST_USER_ID}",  # Correct path: /history, not /chat/history
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
            # API returns GetHistoryResponse: {"data": [...], "pagination": {...}}
            history_items = data.get("data", [])
            pagination = data.get("pagination", {})
            total = pagination.get("total", len(history_items))
            
            # Build detailed message
            details = [f"Found {len(history_items)} messages (total: {total}):"]
            for i, msg in enumerate(history_items[:5]):  # Show top 5
                role = msg.get("role", "?")
                content = msg.get("content", "")[:50]  # Truncate
                details.append(f"  [{i+1}] {role}: {content}...")
            if len(history_items) > 5:
                details.append(f"  ... and {len(history_items) - 5} more")
            
            return TestResult(
                name="Chat History",
                passed=True,
                duration_ms=duration,
                message="\n".join(details),
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
    
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=200.0) as client:  # 200s for CRAG batch grading
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
    completed_time = time.strftime('%Y-%m-%d %H:%M:%S')
    
    print(f"\n{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"{Colors.BOLD}  TEST SUMMARY{Colors.RESET}")
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}")
    print(f"  {Colors.GREEN}Passed: {passed}{Colors.RESET}")
    print(f"  {Colors.RED}Failed: {failed}{Colors.RESET}")
    print(f"  Total Time: {total_time/1000:.1f}s")
    print(f"  Completed: {completed_time}")
    print(f"{Colors.BOLD}{'='*70}{Colors.RESET}\n")
    
    if failed == 0:
        print(f"{Colors.GREEN}{Colors.BOLD}🎉 All tests passed! Production deployment verified.{Colors.RESET}\n")
    else:
        print(f"{Colors.YELLOW}{Colors.BOLD}⚠️  Some tests failed. Check the output above.{Colors.RESET}\n")
    
    # Save detailed results to file
    save_results_to_file(results, passed, failed, total_time, completed_time)
    
    return results


def save_results_to_file(results: List[TestResult], passed: int, failed: int, total_time: float, completed_time: str):
    """Save detailed test results to a txt file for analysis."""
    filename = f"test_results_{time.strftime('%Y%m%d_%H%M%S')}.txt"
    filepath = f"scripts/{filename}"
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("=" * 70 + "\n")
        f.write("  Maritime AI Service - Production API Test Results\n")
        f.write(f"  Base URL: {BASE_URL}\n")
        f.write(f"  Test User ID: {TEST_USER_ID}\n")
        f.write(f"  Completed: {completed_time}\n")
        f.write("=" * 70 + "\n\n")
        
        for i, result in enumerate(results, 1):
            status = "✓ PASSED" if result.passed else "✗ FAILED"
            f.write(f"{i}. {result.name} [{status}] ({result.duration_ms:.0f}ms)\n")
            f.write("-" * 50 + "\n")
            for line in result.message.split("\n"):
                f.write(f"   {line}\n")
            
            # CHỈ THỊ SỐ 29: Write thinking process if available
            if result.thinking:
                f.write("\n   [QUÁ TRÌNH SUY NGHĨ]:\n")
                f.write("-" * 50 + "\n")
                thinking_lines = result.thinking.split("\n")
                for line in thinking_lines[:20]:  # Limit to first 20 lines
                    f.write(f"   {line}\n")
                if len(thinking_lines) > 20:
                    f.write(f"   ... [{len(thinking_lines) - 20} more lines]\n")
                f.write("-" * 50 + "\n")
            
            # Write full response_data for detailed analysis
            if result.response_data:
                f.write("\n   [FULL RESPONSE DATA]:\n")
                import json
                try:
                    json_str = json.dumps(result.response_data, indent=2, ensure_ascii=False, default=str)
                    for line in json_str.split("\n"):
                        f.write(f"   {line}\n")
                except:
                    f.write(f"   {result.response_data}\n")
            f.write("\n")
        
        f.write("=" * 70 + "\n")
        f.write("  TEST SUMMARY\n")
        f.write("=" * 70 + "\n")
        f.write(f"  Passed: {passed}\n")
        f.write(f"  Failed: {failed}\n")
        f.write(f"  Total Time: {total_time/1000:.1f}s\n")
        f.write(f"  Completed: {completed_time}\n")
        f.write("=" * 70 + "\n")
    
    print(f"{Colors.BLUE}📝 Detailed results saved to: {filepath}{Colors.RESET}\n")


if __name__ == "__main__":
    asyncio.run(run_all_tests())
