"""
Test script for Multimodal RAG API with Semantic Chunking (v2.7.0)
Tests ingestion pipeline and verifies chunking metadata.

Run: python scripts/test_multimodal_api.py
     python scripts/test_multimodal_api.py --verbose
     python scripts/test_multimodal_api.py --skip-ingestion  # Only test chat

Features: multimodal-rag-vision, semantic-chunking
"""
import httpx
import asyncio
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

# Configuration
API_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = "secret_key_cho_team_lms"
PDF_PATH = "data/VanBanGoc_95.2015.QH13.P1.pdf"
DOCUMENT_ID = "luat_hang_hai_2015"


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


class MultimodalAPITester:
    """Test suite for Multimodal RAG API with Semantic Chunking"""
    
    def __init__(self, verbose: bool = False, skip_ingestion: bool = False):
        self.verbose = verbose
        self.skip_ingestion = skip_ingestion
        self.results: list[TestResult] = []
        self.session_id = f"test_multimodal_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    async def run_all_tests(self) -> bool:
        """Run all tests and return overall success status"""
        print("=" * 70)
        print("🧪 MULTIMODAL RAG + SEMANTIC CHUNKING - API TEST SUITE")
        print("=" * 70)
        print(f"API URL: {API_URL}")
        print(f"PDF: {PDF_PATH}")
        print(f"Document ID: {DOCUMENT_ID}")
        print(f"Session: {self.session_id}")
        print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print()
        
        # Test 1: Health Check
        await self._test_health()
        
        # Test 2: Multimodal Ingestion (optional)
        if not self.skip_ingestion:
            await self._test_multimodal_ingestion()
        else:
            self.results.append(TestResult(
                name="Multimodal Ingestion",
                status=TestStatus.SKIPPED,
                message="Skipped by --skip-ingestion flag"
            ))
            print("\n📋 Test 2: Multimodal Ingestion")
            print("   ⏭️ SKIPPED: --skip-ingestion flag")
        
        # Test 3: Chat with maritime query
        await self._test_chat_maritime_query()
        
        # Test 4: Verify sources have chunking metadata
        await self._test_sources_chunking_metadata()
        
        # Test 5: Verify evidence images
        await self._test_evidence_images()
        
        # Print summary
        self._print_summary()
        
        # Return overall success
        failed_count = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        return failed_count == 0
    
    async def _test_health(self):
        """Test 1: API Health Check"""
        test_name = "API Health Check"
        print(f"\n📋 Test 1: {test_name}")
        
        start = datetime.now()
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                print("   Waiting for Render to wake up...")
                response = await client.get(f"{API_URL}/health")
                duration = (datetime.now() - start).total_seconds() * 1000
                
                if response.status_code == 200:
                    data = response.json()
                    status = data.get("status", "unknown")
                    db_status = data.get("database", "unknown")
                    
                    if self.verbose:
                        print(f"   Response: {data}")
                    
                    if status == "ok":
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.PASSED,
                            message=f"API healthy, DB: {db_status}",
                            details=data,
                            duration_ms=duration
                        )
                    else:
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.WARNING,
                            message=f"API status: {status}",
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
    
    async def _test_multimodal_ingestion(self):
        """Test 2: Multimodal Ingestion with Semantic Chunking"""
        test_name = "Multimodal Ingestion"
        print(f"\n📋 Test 2: {test_name}")
        
        pdf_file = Path(PDF_PATH)
        if not pdf_file.exists():
            result = TestResult(
                name=test_name,
                status=TestStatus.FAILED,
                message=f"PDF file not found: {PDF_PATH}"
            )
            self._record_result(result)
            return
        
        print(f"   📄 Uploading: {pdf_file.name} ({pdf_file.stat().st_size / 1024:.1f} KB)")
        print("   ⏳ This may take several minutes...")
        
        start = datetime.now()
        try:
            async with httpx.AsyncClient(timeout=600.0) as client:
                with open(pdf_file, "rb") as f:
                    files = {"file": (pdf_file.name, f, "application/pdf")}
                    data = {"document_id": DOCUMENT_ID, "role": "admin"}
                    
                    response = await client.post(
                        f"{API_URL}/api/v1/knowledge/ingest-multimodal",
                        headers={"X-API-Key": API_KEY},
                        files=files,
                        data=data
                    )
                
                duration = (datetime.now() - start).total_seconds() * 1000
                
                if response.status_code == 200:
                    result_data = response.json()
                    successful = result_data.get("successful_pages", 0)
                    total = result_data.get("total_pages", 0)
                    chunks = result_data.get("total_chunks", 0)
                    
                    if self.verbose:
                        print(f"   Response: {result_data}")
                    
                    if successful > 0:
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.PASSED,
                            message=f"{successful}/{total} pages, {chunks} chunks",
                            details=result_data,
                            duration_ms=duration
                        )
                    else:
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.WARNING,
                            message=f"0 pages ingested (may need poppler)",
                            details=result_data,
                            duration_ms=duration
                        )
                else:
                    error_detail = ""
                    try:
                        error_detail = response.json().get("detail", "")
                    except:
                        pass
                    result = TestResult(
                        name=test_name,
                        status=TestStatus.FAILED,
                        message=f"HTTP {response.status_code}: {error_detail}",
                        duration_ms=duration
                    )
        except httpx.TimeoutException:
            duration = (datetime.now() - start).total_seconds() * 1000
            result = TestResult(
                name=test_name,
                status=TestStatus.FAILED,
                message="Timeout after 600s",
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

    
    async def _test_chat_maritime_query(self):
        """Test 3: Chat with maritime query"""
        test_name = "Chat Maritime Query"
        print(f"\n📋 Test 3: {test_name}")
        
        query = "Điều 1 Luật Hàng hải Việt Nam quy định gì về phạm vi điều chỉnh?"
        
        if self.verbose:
            print(f"   Query: {query}")
        
        start = datetime.now()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "message": query,
                    "session_id": self.session_id,
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
                    answer = inner_data.get("answer", "")
                    sources = inner_data.get("sources", [])
                    metadata = data.get("metadata", {})
                    agent = metadata.get("agent_type", "unknown")
                    
                    if self.verbose:
                        print(f"   Agent: {agent}")
                        print(f"   Answer length: {len(answer)} chars")
                        print(f"   Sources: {len(sources)}")
                        if answer:
                            print(f"   Answer preview: {answer[:200]}...")
                    
                    if len(answer) > 50:
                        if len(sources) > 0:
                            result = TestResult(
                                name=test_name,
                                status=TestStatus.PASSED,
                                message=f"Got response with {len(sources)} sources",
                                details={
                                    "agent": agent,
                                    "answer_length": len(answer),
                                    "sources_count": len(sources)
                                },
                                duration_ms=duration
                            )
                        else:
                            result = TestResult(
                                name=test_name,
                                status=TestStatus.WARNING,
                                message=f"Got response but no sources (need ingestion)",
                                details={"agent": agent, "answer_length": len(answer)},
                                duration_ms=duration
                            )
                    else:
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.WARNING,
                            message=f"Response too short ({len(answer)} chars)",
                            duration_ms=duration
                        )
                else:
                    error_detail = ""
                    try:
                        error_detail = response.json().get("detail", "")
                    except:
                        pass
                    result = TestResult(
                        name=test_name,
                        status=TestStatus.FAILED,
                        message=f"HTTP {response.status_code}: {error_detail}",
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
    
    async def _test_sources_chunking_metadata(self):
        """Test 4: Verify sources have chunking metadata"""
        test_name = "Sources Chunking Metadata"
        print(f"\n📋 Test 4: {test_name}")
        
        start = datetime.now()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "message": "Điều 15 về quyền và nghĩa vụ của thuyền viên",
                    "session_id": f"{self.session_id}_metadata",
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
                        print(f"   Sources count: {len(sources)}")
                        if sources:
                            print(f"   First source keys: {list(sources[0].keys())}")
                    
                    if sources:
                        # Check for chunking metadata fields
                        first_source = sources[0]
                        has_content_type = "content_type" in first_source
                        has_confidence = "confidence_score" in first_source
                        has_chunk_index = "chunk_index" in first_source
                        has_hierarchy = "section_hierarchy" in first_source
                        
                        metadata_fields = []
                        if has_content_type:
                            metadata_fields.append("content_type")
                        if has_confidence:
                            metadata_fields.append("confidence_score")
                        if has_chunk_index:
                            metadata_fields.append("chunk_index")
                        if has_hierarchy:
                            metadata_fields.append("section_hierarchy")
                        
                        if len(metadata_fields) >= 2:
                            result = TestResult(
                                name=test_name,
                                status=TestStatus.PASSED,
                                message=f"Found chunking metadata: {', '.join(metadata_fields)}",
                                details={
                                    "sources_count": len(sources),
                                    "metadata_fields": metadata_fields,
                                    "sample_source": first_source
                                },
                                duration_ms=duration
                            )
                        else:
                            result = TestResult(
                                name=test_name,
                                status=TestStatus.WARNING,
                                message=f"Limited metadata: {metadata_fields or 'none'}",
                                details={"source_keys": list(first_source.keys())},
                                duration_ms=duration
                            )
                    else:
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.WARNING,
                            message="No sources to check (need ingestion)",
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
    
    async def _test_evidence_images(self):
        """Test 5: Verify evidence images"""
        test_name = "Evidence Images"
        print(f"\n📋 Test 5: {test_name}")
        
        start = datetime.now()
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                payload = {
                    "message": "Hình ảnh về cấu trúc tàu biển",
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
                    
                    # Check for image URLs in sources
                    sources_with_images = sum(
                        1 for s in sources 
                        if s.get("image_url") or s.get("url")
                    ) if sources else 0
                    
                    if self.verbose:
                        print(f"   Evidence images: {len(evidence_images)}")
                        print(f"   Sources with image_url: {sources_with_images}")
                    
                    if evidence_images or sources_with_images > 0:
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.PASSED,
                            message=f"{len(evidence_images)} evidence images, {sources_with_images} sources with URLs",
                            details={
                                "evidence_images": len(evidence_images),
                                "sources_with_images": sources_with_images
                            },
                            duration_ms=duration
                        )
                    else:
                        result = TestResult(
                            name=test_name,
                            status=TestStatus.WARNING,
                            message="No evidence images (need multimodal ingestion)",
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
    
    def _record_result(self, result: TestResult):
        """Record test result and print status"""
        self.results.append(result)
        print(f"   {result.status.value}: {result.message} ({result.duration_ms:.0f}ms)")
        
        if self.verbose and result.details:
            for key, value in result.details.items():
                if key != "sample_source":  # Don't print full source
                    print(f"      {key}: {value}")
    
    def _print_summary(self):
        """Print test summary"""
        print("\n" + "=" * 70)
        print("📊 TEST RESULTS SUMMARY")
        print("=" * 70)
        
        passed = sum(1 for r in self.results if r.status == TestStatus.PASSED)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAILED)
        warnings = sum(1 for r in self.results if r.status == TestStatus.WARNING)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIPPED)
        total = len(self.results)
        
        print(f"\nTotal Tests: {total}")
        print(f"  ✅ Passed:   {passed}")
        print(f"  ❌ Failed:   {failed}")
        print(f"  ⚠️ Warnings: {warnings}")
        print(f"  ⏭️ Skipped:  {skipped}")
        
        print("\nDetailed Results:")
        for i, result in enumerate(self.results, 1):
            print(f"  {i}. {result.name}: {result.status.value}")
            if result.status == TestStatus.FAILED:
                print(f"     → {result.message}")
        
        total_time = sum(r.duration_ms for r in self.results)
        print(f"\nTotal Time: {total_time/1000:.1f}s")
        
        # Print next steps if warnings
        if warnings > 0:
            print("\n📝 NEXT STEPS:")
            print("   If sources/images are missing:")
            print("   1. Ensure poppler is installed on server")
            print("   2. Run ingestion: python scripts/test_multimodal_api.py")
            print("   3. Or use API: POST /api/v1/knowledge/ingest-multimodal")
        
        print("\n" + "=" * 70)
        if failed == 0:
            print("🎉 ALL TESTS PASSED!")
        else:
            print(f"❌ {failed} TEST(S) FAILED - Please check the issues above")
        print("=" * 70)


async def main():
    global API_URL, PDF_PATH, DOCUMENT_ID
    
    parser = argparse.ArgumentParser(
        description="Test Multimodal RAG API with Semantic Chunking"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output"
    )
    parser.add_argument(
        "--skip-ingestion",
        action="store_true",
        help="Skip ingestion test (only test chat)"
    )
    parser.add_argument(
        "--api-url",
        default=API_URL,
        help=f"API URL (default: {API_URL})"
    )
    parser.add_argument(
        "--pdf",
        default=PDF_PATH,
        help=f"PDF file path (default: {PDF_PATH})"
    )
    parser.add_argument(
        "--document-id",
        default=DOCUMENT_ID,
        help=f"Document ID (default: {DOCUMENT_ID})"
    )
    args = parser.parse_args()
    
    # Update globals
    API_URL = args.api_url
    PDF_PATH = args.pdf
    DOCUMENT_ID = args.document_id
    
    tester = MultimodalAPITester(
        verbose=args.verbose,
        skip_ingestion=args.skip_ingestion
    )
    success = await tester.run_all_tests()
    
    exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
