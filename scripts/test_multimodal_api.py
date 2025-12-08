"""
Test script for Multimodal RAG API (CHỈ THỊ 26)
Run: python scripts/test_multimodal_api.py
"""
import httpx
import asyncio
from pathlib import Path

API_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = "secret_key_cho_team_lms"

async def test_health():
    """Test health endpoint"""
    async with httpx.AsyncClient(timeout=60.0) as client:
        print("   Waiting for Render to wake up...")
        response = await client.get(f"{API_URL}/health")
        print(f"✅ Health: {response.json()}")
        return response.status_code == 200

async def test_multimodal_ingestion(pdf_path: str, document_id: str):
    """Test multimodal ingestion with real PDF"""
    headers = {"X-API-Key": API_KEY}
    
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        print(f"❌ PDF file not found: {pdf_path}")
        return False
    
    print(f"📄 Uploading: {pdf_file.name} ({pdf_file.stat().st_size / 1024:.1f} KB)")
    
    async with httpx.AsyncClient(timeout=600.0) as client:
        with open(pdf_file, "rb") as f:
            files = {"file": (pdf_file.name, f, "application/pdf")}
            data = {"document_id": document_id, "role": "admin"}
            
            response = await client.post(
                f"{API_URL}/api/v1/knowledge/ingest-multimodal",
                headers=headers,
                files=files,
                data=data
            )
        
        print(f"Status: {response.status_code}")
        result = response.json()
        print(f"Response: {result}")
        
        if response.status_code == 200:
            print(f"✅ SUCCESS: {result.get('successful_pages', 0)}/{result.get('total_pages', 0)} pages")
            return True
        else:
            print(f"❌ FAILED: {result}")
            return False

async def main():
    print("=" * 50)
    print("🧪 CHỈ THỊ 26: Multimodal RAG API Test")
    print("=" * 50)
    
    # Test 1: Health
    print("\n1. Testing Health...")
    await test_health()
    
    # Test 2: Multimodal Ingestion (dùng file nhỏ 4 trang)
    print("\n2. Testing Multimodal Ingestion...")
    pdf_path = "data/google-2023-environmental-report.pdf"
    await test_multimodal_ingestion(pdf_path, "google_env_report_2023")

if __name__ == "__main__":
    asyncio.run(main())
