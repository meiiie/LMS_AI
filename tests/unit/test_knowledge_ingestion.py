"""
Test script for Knowledge Ingestion API.

Usage:
    python scripts/test_knowledge_ingestion.py

Feature: knowledge-ingestion
"""

import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
from dotenv import load_dotenv

load_dotenv()

# Configuration
BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("LMS_API_KEY", "test-api-key")


async def test_stats():
    """Test GET /api/v1/knowledge/stats"""
    print("\n=== Testing GET /stats ===")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/api/v1/knowledge/stats",
            headers={"X-API-Key": API_KEY}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200


async def test_list():
    """Test GET /api/v1/knowledge/list"""
    print("\n=== Testing GET /list ===")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/api/v1/knowledge/list",
            headers={"X-API-Key": API_KEY},
            params={"page": 1, "limit": 10}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200


async def test_ingest_non_admin():
    """Test POST /api/v1/knowledge/ingest with non-admin role (should fail)"""
    print("\n=== Testing POST /ingest (non-admin - should fail) ===")
    
    # Create a simple test PDF content
    pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\ntrailer\n<<\n/Root 1 0 R\n>>\n%%EOF"
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/api/v1/knowledge/ingest",
            headers={"X-API-Key": API_KEY},
            files={"file": ("test.pdf", pdf_content, "application/pdf")},
            data={"category": "Test", "role": "student"}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 403


async def test_ingest_admin():
    """Test POST /api/v1/knowledge/ingest with admin role"""
    print("\n=== Testing POST /ingest (admin) ===")
    
    # Check if we have a real PDF to test with
    test_pdf_path = Path(__file__).parent / "test_document.pdf"
    
    if test_pdf_path.exists():
        with open(test_pdf_path, "rb") as f:
            pdf_content = f.read()
        print(f"Using test PDF: {test_pdf_path}")
    else:
        # Create minimal PDF for testing
        pdf_content = b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n>>\nendobj\ntrailer\n<<\n/Root 1 0 R\n>>\n%%EOF"
        print("Using minimal test PDF (no real content)")
    
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{BASE_URL}/api/v1/knowledge/ingest",
            headers={"X-API-Key": API_KEY},
            files={"file": ("test.pdf", pdf_content, "application/pdf")},
            data={"category": "COLREGs", "role": "admin"}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        
        if response.status_code == 200:
            job_id = response.json().get("job_id")
            if job_id:
                # Wait and check job status
                await asyncio.sleep(2)
                await test_job_status(job_id)
        
        return response.status_code == 200


async def test_job_status(job_id: str):
    """Test GET /api/v1/knowledge/jobs/{job_id}"""
    print(f"\n=== Testing GET /jobs/{job_id} ===")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/api/v1/knowledge/jobs/{job_id}",
            headers={"X-API-Key": API_KEY}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 200


async def test_invalid_job():
    """Test GET /api/v1/knowledge/jobs/{invalid_id} (should return 404)"""
    print("\n=== Testing GET /jobs/invalid-id (should fail) ===")
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{BASE_URL}/api/v1/knowledge/jobs/invalid-job-id-12345",
            headers={"X-API-Key": API_KEY}
        )
        print(f"Status: {response.status_code}")
        print(f"Response: {response.json()}")
        return response.status_code == 404


async def main():
    """Run all tests."""
    print("=" * 60)
    print("Knowledge Ingestion API Test Suite")
    print(f"Base URL: {BASE_URL}")
    print("=" * 60)
    
    results = []
    
    # Test stats endpoint
    results.append(("GET /stats", await test_stats()))
    
    # Test list endpoint
    results.append(("GET /list", await test_list()))
    
    # Test non-admin access (should fail)
    results.append(("POST /ingest (non-admin)", await test_ingest_non_admin()))
    
    # Test invalid job ID
    results.append(("GET /jobs/invalid", await test_invalid_job()))
    
    # Test admin upload (optional - requires server running)
    try:
        results.append(("POST /ingest (admin)", await test_ingest_admin()))
    except Exception as e:
        print(f"\nAdmin upload test skipped: {e}")
    
    # Summary
    print("\n" + "=" * 60)
    print("Test Results Summary")
    print("=" * 60)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {name}")
    
    passed_count = sum(1 for _, p in results if p)
    print(f"\nTotal: {passed_count}/{len(results)} tests passed")


if __name__ == "__main__":
    asyncio.run(main())
