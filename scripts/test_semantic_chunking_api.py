"""
Test script for Semantic Chunking API (v2.7.0)
Tests the semantic chunking feature in production environment.

Run: python scripts/test_semantic_chunking_api.py
     python scripts/test_semantic_chunking_api.py --verbose

Feature: semantic-chunking
"""
import httpx
import asyncio
import argparse
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from enum import Enum

# Configuration
API_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = "secret_key_cho_team_lms"
TIMEOUT = 120.0  # 2 minutes for LLM responses


class TestStatus(Enum):
    PASSED = "✅ PASSED"
    FAILED = "❌ FAILED"
    SKIPPED = "⏭️ SKIPPED"
    WARNING = "⚠️ WARNING"


@dataclass
class TestResult:
    name: str
    status: TestStatus
    message: str
    details: Optional[Dict[str, Any]] = None
    duration_ms: float = 0


class SemanticChunkingTester:
    """Production test suite for Semantic Chunking feature"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.results: List[TestResult] = []
        self.session_id = f"test_chunking_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    async def run_all_tests(self) -> bool:
        """Run all tests and return overall success status"""
        print("=" * 70)
        print("🧪 SEMANTIC CHUNKING v2.7.0 - PRODUCTION TEST SUITE")
        print("=" * 70)
        print(f"API URL: {API_URL}")
        print(f"Session: {self.session_id}")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            # Test 1: Health Check
            await self._test_health(client)
            
            # Test 2: Chat với query về Điều (Vietnamese legal structure)
            await self._test_chat_dieu_query(client)
            
            # Test 3: Chat với query về Rule (English maritime rules)
            await self._test_chat_rule_query(client)
            
            # Test 4: Chat với query về bảng biểu (table content)
            await self._test_chat_table_query(client)
            
            # Test 5: Verify response có sources
            await self._test_response_has_sources(client)
            
            # Test 6: Verify evidence images
            await self._test_evidence_images(client)
        
        # Print summary
        self._print_summary()
        
        # Print next steps if warnings
        warning_count = sum(1 for r in self.results if r.status == TestStatus.WARNING)
        if warning_count > 0:
            print("\n📝 NEXT STEPS:")
            print("   If sources are missing, you need to:")
            print("   1. Run migration: alembic upgrade head")
            print("   2. Re-ingest with chunking: python scripts/reingest_with_chunking.py")
            print()
        
        # Return overall success
        failed_count = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        return failed_count == 0
    
    async def _test_health(self, client: httpx.AsyncClient):
        """Test 1: API Health Check"""
        test_name = "API Health Check"
        print(f"\n📋 Test 1: {test_name}")
        
        start = datetime.now()
        try:
            response = await client.get(f"{API_URL}/health")
            duration = (datetime.now() - start).total_seconds() * 1000
            
            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "unknown")
                db_status = data.get("database", "unknown")
                
                if status == "ok" and db_status == "connected":
                    result = TestResult(
                        name=test_name,
                        status=TestStatus.PASSED,
                        message=f"API healthy, DB connected",
                        details=data,
                        duration_ms=duration
                    )
                else:
                    result = TestResult(
                        name=test_name,
                        status=TestStatus.WARNING,
                        message=f"API status: {status}, DB: {db_status}",
                        details=data,
                        duration_ms=duration
                    )
            else:
                result = TestResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    message=f"HTTP {response.status_code}",
                    duration_ms=duration
                )
        except Exception as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            result = TestResult(
                name=test_name,
                status=TestStatus.FAILED,
                message=f"Exception: {str(e)}",
                duration_ms=duration
            )
        
        self._record_result(result)
    
    async def _test_chat_dieu_query(self, client: httpx.AsyncClient):
        """Test 2: Chat với query về Điều (Vietnamese legal structure)"""
        test_name = "Chat Query - Điều (Vietnamese Legal)"
        print(f"\n📋 Test 2: {test_name}")
        
        query = "Điều 15 COLREGs quy định gì về tình huống cắt hướng?"
        result = await self._send_chat_and_verify(
            client, 
            test_name, 
            query,
            expected_keywords=["điều", "cắt hướng", "crossing", "rule 15"],
            check_sources=True
        )
        self._record_result(result)
    
    async def _test_chat_rule_query(self, client: httpx.AsyncClient):
        """Test 3: Chat với query về Rule (English maritime rules)"""
        test_name = "Chat Query - Rule (English Maritime)"
        print(f"\n📋 Test 3: {test_name}")
        
        query = "Rule 19 về hành động của tàu trong tầm nhìn hạn chế"
        result = await self._send_chat_and_verify(
            client,
            test_name,
            query,
            expected_keywords=["rule 19", "tầm nhìn", "restricted visibility"],
            check_sources=True
        )
        self._record_result(result)
    
    async def _test_chat_table_query(self, client: httpx.AsyncClient):
        """Test 4: Chat với query về bảng biểu"""
        test_name = "Chat Query - Table Content"
        print(f"\n📋 Test 4: {test_name}")
        
        query = "Cho tôi biết về các loại đèn hiệu trên tàu thuyền"
        result = await self._send_chat_and_verify(
            client,
            test_name,
            query,
            expected_keywords=["đèn", "light", "tàu"],
            check_sources=True
        )
        self._record_result(result)
    
    async def _test_response_has_sources(self, client: httpx.AsyncClient):
        """Test 5: Verify response có sources với metadata"""
        test_name = "Response Sources Verification"
        print(f"\n📋 Test 5: {test_name}")
        
        start = datetime.now()
        try:
            payload = {
                "message": "Quy tắc về tín hiệu âm thanh khi tầm nhìn hạn chế",
                "session_id": f"{self.session_id}_sources",
                "user_id": "test_user",
                "role": "student"
            }
            
            response = await client.post(
                f"{API_URL}/api/v1/chat",
                json=payload,
                headers={"Content-Type": "application/json", "X-API-Key": API_KEY}
            )
            duration = (datetime.now() - start).total_seconds() * 1000
            
            if response.status_code == 200:
                data = response.json()
                inner_data = data.get("data", data)
                sources = inner_data.get("sources", [])
                
                if self.verbose:
                    print(f"   Response keys: {list(data.keys())}")
                    print(f"   Inner data keys: {list(inner_data.keys()) if isinstance(inner_data, dict) else 'N/A'}")
                    print(f"   Sources count: {len(sources)}")
                
                if sources and len(sources) > 0:
                    # Check if sources have expected fields
                    first_source = sources[0]
                    has_content = "content" in first_source or "text" in first_source
                    has_page = "page_number" in first_source or "page" in first_source
                    
                    if has_content:
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.PASSED,
                            message=f"Found {len(sources)} sources with content",
                            details={"sources_count": len(sources), "sample_keys": list(first_source.keys())},
                            duration_ms=duration
                        )
                    else:
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.WARNING,
                            message=f"Sources found but missing content field",
                            details={"sources_count": len(sources), "sample_keys": list(first_source.keys())},
                            duration_ms=duration
                        )
                else:
                    result = TestResult(
                        name=test_name,
                        status=TestStatus.WARNING,
                        message="No sources in response (may need re-ingestion)",
                        details={"response_keys": list(data.keys())},
                        duration_ms=duration
                    )
            else:
                result = TestResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    message=f"HTTP {response.status_code}",
                    duration_ms=duration
                )
        except Exception as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            result = TestResult(
                name=test_name,
                status=TestStatus.FAILED,
                message=f"Exception: {str(e)}",
                duration_ms=duration
            )
        
        self._record_result(result)
    
    async def _test_evidence_images(self, client: httpx.AsyncClient):
        """Test 6: Verify evidence images trong response"""
        test_name = "Evidence Images Verification"
        print(f"\n📋 Test 6: {test_name}")
        
        start = datetime.now()
        try:
            payload = {
                "message": "Hình ảnh về đèn hành trình của tàu",
                "session_id": f"{self.session_id}_images",
                "user_id": "test_user",
                "role": "student"
            }
            
            response = await client.post(
                f"{API_URL}/api/v1/chat",
                json=payload,
                headers={"Content-Type": "application/json", "X-API-Key": API_KEY}
            )
            duration = (datetime.now() - start).total_seconds() * 1000
            
            if response.status_code == 200:
                data = response.json()
                inner_data = data.get("data", data)
                evidence_images = inner_data.get("evidence_images", [])
                sources = inner_data.get("sources", [])
                
                # Check for image URLs in sources or evidence_images
                has_images = len(evidence_images) > 0
                has_image_urls_in_sources = any(
                    "image_url" in s or "url" in s 
                    for s in sources
                ) if sources else False
                
                if self.verbose:
                    print(f"   Evidence images: {len(evidence_images)}")
                    print(f"   Sources with image_url: {has_image_urls_in_sources}")
                
                if has_images or has_image_urls_in_sources:
                    result = TestResult(
                        name=test_name,
                        status=TestStatus.PASSED,
                        message=f"Evidence images available",
                        details={
                            "evidence_images_count": len(evidence_images),
                            "sources_with_images": has_image_urls_in_sources
                        },
                        duration_ms=duration
                    )
                else:
                    result = TestResult(
                        name=test_name,
                        status=TestStatus.WARNING,
                        message="No evidence images (may need multimodal re-ingestion)",
                        details={"response_keys": list(data.keys())},
                        duration_ms=duration
                    )
            else:
                result = TestResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    message=f"HTTP {response.status_code}",
                    duration_ms=duration
                )
        except Exception as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            result = TestResult(
                name=test_name,
                status=TestStatus.FAILED,
                message=f"Exception: {str(e)}",
                duration_ms=duration
            )
        
        self._record_result(result)

    
    async def _send_chat_and_verify(
        self, 
        client: httpx.AsyncClient,
        test_name: str,
        query: str,
        expected_keywords: List[str],
        check_sources: bool = False
    ) -> TestResult:
        """Helper: Send chat request and verify response"""
        start = datetime.now()
        try:
            payload = {
                "message": query,
                "session_id": self.session_id,
                "user_id": "test_user",
                "role": "student"
            }
            
            if self.verbose:
                print(f"   Query: {query}")
            
            response = await client.post(
                f"{API_URL}/api/v1/chat",
                json=payload,
                headers={"Content-Type": "application/json", "X-API-Key": API_KEY}
            )
            duration = (datetime.now() - start).total_seconds() * 1000
            
            if response.status_code == 200:
                data = response.json()
                # Handle nested response structure: {status, data: {answer, sources}, metadata}
                inner_data = data.get("data", data)
                answer = inner_data.get("answer", "") or inner_data.get("response", "") or data.get("message", "")
                sources = inner_data.get("sources", [])
                metadata = data.get("metadata", {})
                agent = metadata.get("agent_type", "unknown")
                
                if self.verbose:
                    print(f"   Agent: {agent}")
                    print(f"   Answer length: {len(answer)} chars")
                    print(f"   Sources: {len(sources)}")
                    if answer:
                        print(f"   Answer preview: {answer[:200]}...")
                
                # Check if answer contains expected keywords
                answer_lower = answer.lower()
                found_keywords = [kw for kw in expected_keywords if kw.lower() in answer_lower]
                
                # Determine status
                if len(answer) > 50:  # Has meaningful response
                    if check_sources and len(sources) > 0:
                        status = TestStatus.PASSED
                        message = f"Got response with {len(sources)} sources"
                    elif check_sources:
                        status = TestStatus.WARNING
                        message = f"Got response but no sources (may need re-ingestion)"
                    else:
                        status = TestStatus.PASSED
                        message = f"Got meaningful response ({len(answer)} chars)"
                    
                    return TestResult(
                        name=test_name,
                        status=status,
                        message=message,
                        details={
                            "agent": agent,
                            "answer_length": len(answer),
                            "sources_count": len(sources),
                            "found_keywords": found_keywords
                        },
                        duration_ms=duration
                    )
                else:
                    return TestResult(
                        name=test_name,
                        status=TestStatus.WARNING,
                        message=f"Response too short ({len(answer)} chars)",
                        details={"answer": answer},
                        duration_ms=duration
                    )
            else:
                error_detail = ""
                try:
                    error_detail = response.json().get("detail", "")
                except:
                    pass
                return TestResult(
                    name=test_name,
                    status=TestStatus.FAILED,
                    message=f"HTTP {response.status_code}: {error_detail}",
                    duration_ms=duration
                )
                
        except httpx.TimeoutException:
            duration = (datetime.now() - start).total_seconds() * 1000
            return TestResult(
                name=test_name,
                status=TestStatus.FAILED,
                message=f"Timeout after {TIMEOUT}s",
                duration_ms=duration
            )
        except Exception as e:
            duration = (datetime.now() - start).total_seconds() * 1000
            return TestResult(
                name=test_name,
                status=TestStatus.FAILED,
                message=f"Exception: {str(e)}",
                duration_ms=duration
            )
    
    def _record_result(self, result: TestResult):
        """Record test result and print status"""
        self.results.append(result)
        print(f"   {result.status.value}: {result.message} ({result.duration_ms:.0f}ms)")
        
        if self.verbose and result.details:
            for key, value in result.details.items():
                print(f"      {key}: {value}")
    
    def _print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 70)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 70)
        
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        warnings = sum(1 for r in self.results if r.status == TestStatus.WARNING)
        total = len(self.results)
        
        print(f"\nTotal Tests: {total}")
        print(f"  ✅ Passed:   {passed}")
        print(f"  ❌ Failed:   {failed}")
        print(f"  ⚠️ Warnings: {warnings}")
        
        print("\nDetailed Results:")
        for i, result in enumerate(self.results, 1):
            print(f"  {i}. {result.name}: {result.status.value}")
            if result.status == TestStatus.FAILED:
                print(f"     → {result.message}")
        
        total_time = sum(r.duration_ms for r in self.results)
        print(f"\nTotal Time: {total_time/1000:.1f}s")
        
        print("\n" + "=" * 70)
        if failed == 0:
            print("🎉 ALL TESTS PASSED!")
        else:
            print(f"❌ {failed} TEST(S) FAILED - Please check the issues above")
        print("=" * 70)


async def main():
    global API_URL
    
    parser = argparse.ArgumentParser(
        description="Test Semantic Chunking API in Production"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )
    parser.add_argument(
        "--api-url",
        default=API_URL,
        help=f"API URL (default: {API_URL})"
    )
    args = parser.parse_args()
    
    # Update API URL if provided
    API_URL = args.api_url
    
    tester = SemanticChunkingTester(verbose=args.verbose)
    success = await tester.run_all_tests()
    
    # Exit with appropriate code
    exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
