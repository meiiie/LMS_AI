"""
Test Hybrid Text/Vision Detection via Production API.

Feature: hybrid-text-vision
Tests the full ingestion pipeline with hybrid detection on deployed server.

Usage:
    python scripts/test_hybrid_api.py
    
Requirements:
    - Server deployed at RENDER_URL
    - PDF file in data/ directory
"""
import os
import sys
import requests
from pathlib import Path

# Configuration
RENDER_URL = os.getenv("RENDER_URL", "https://maritime-ai-chatbot.onrender.com")
API_ENDPOINT = f"{RENDER_URL}/api/v1/knowledge/ingest-multimodal"
HEALTH_ENDPOINT = f"{RENDER_URL}/api/v1/health"  # Shallow health check (no DB)

# Test PDF - use VanBanGoc for text-heavy content (should have high savings)
TEST_PDF = "data/VanBanGoc_95.2015.QH13.P1.pdf"
TEST_DOCUMENT_ID = "hybrid-test-vanban-25"
MAX_PAGES = 25  # Limit to 25 pages to avoid Render worker timeout


def check_server_health():
    """Check if server is running"""
    print(f"\n🔍 Checking server health: {HEALTH_ENDPOINT}")
    try:
        response = requests.get(HEALTH_ENDPOINT, timeout=30)
        if response.status_code == 200:
            print("✅ Server is healthy")
            return True
        else:
            print(f"❌ Server returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Server connection failed: {e}")
        return False


def test_hybrid_ingestion():
    """Test hybrid detection via API"""
    print(f"\n📄 Testing Hybrid Ingestion API")
    print(f"   Endpoint: {API_ENDPOINT}")
    print(f"   PDF: {TEST_PDF}")
    print(f"   Max Pages: {MAX_PAGES}")
    
    # Check if PDF exists
    if not os.path.exists(TEST_PDF):
        print(f"❌ PDF not found: {TEST_PDF}")
        return None
    
    # Prepare request
    with open(TEST_PDF, 'rb') as f:
        files = {'file': (os.path.basename(TEST_PDF), f, 'application/pdf')}
        data = {
            'document_id': TEST_DOCUMENT_ID,
            'role': 'admin',
            'resume': 'false',  # Fresh ingestion
        }
        # Only add max_pages if specified
        if MAX_PAGES is not None:
            data['max_pages'] = str(MAX_PAGES)
        
        print(f"\n⏳ Uploading and processing (this may take a few minutes)...")
        
        try:
            response = requests.post(
                API_ENDPOINT,
                files=files,
                data=data,
                timeout=300  # 5 minutes timeout
            )
            
            if response.status_code == 200:
                result = response.json()
                print("\n✅ Ingestion completed!")
                return result
            else:
                print(f"\n❌ API Error: {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return None
                
        except requests.exceptions.Timeout:
            print("\n⚠️ Request timed out (server may still be processing)")
            return None
        except Exception as e:
            print(f"\n❌ Request failed: {e}")
            return None


def analyze_results(result: dict):
    """Analyze and display hybrid detection results"""
    print("\n" + "=" * 60)
    print("📊 HYBRID TEXT/VISION DETECTION RESULTS")
    print("=" * 60)
    
    # Basic stats
    print(f"\n📄 Document: {result.get('document_id', 'N/A')}")
    print(f"   Status: {result.get('status', 'N/A')}")
    print(f"   Message: {result.get('message', 'N/A')}")
    
    # Page counts
    total = result.get('total_pages', 0)
    successful = result.get('successful_pages', 0)
    failed = result.get('failed_pages', 0)
    success_rate = result.get('success_rate', 0)
    
    print(f"\n📑 Page Processing:")
    print(f"   Total Pages: {total}")
    print(f"   Successful: {successful}")
    print(f"   Failed: {failed}")
    print(f"   Success Rate: {success_rate:.1f}%")
    
    # Hybrid detection stats (Feature: hybrid-text-vision)
    vision_pages = result.get('vision_pages', 0)
    direct_pages = result.get('direct_pages', 0)
    fallback_pages = result.get('fallback_pages', 0)
    api_savings = result.get('api_savings_percent', 0)
    
    print(f"\n🔍 Hybrid Detection Stats:")
    print(f"   Vision Pages (Gemini API): {vision_pages}")
    print(f"   Direct Pages (PyMuPDF): {direct_pages}")
    print(f"   Fallback Pages: {fallback_pages}")
    print(f"   API Savings: {api_savings:.1f}%")
    
    # Visual bar for savings
    if total > 0:
        bar_length = 30
        direct_bar = int((direct_pages / total) * bar_length)
        vision_bar = bar_length - direct_bar
        print(f"\n   [{'🟢' * direct_bar}{'🔴' * vision_bar}]")
        print(f"   🟢 = Direct (FREE)  🔴 = Vision (PAID)")
    
    # Errors
    errors = result.get('errors', [])
    if errors:
        print(f"\n⚠️ Errors ({len(errors)}):")
        for err in errors[:5]:  # Show first 5
            print(f"   - {err}")
    
    # Summary
    print("\n" + "=" * 60)
    if api_savings >= 50:
        print(f"🎉 EXCELLENT! {api_savings:.1f}% API cost savings achieved!")
    elif api_savings >= 30:
        print(f"✅ GOOD! {api_savings:.1f}% API cost savings achieved!")
    elif api_savings > 0:
        print(f"📊 {api_savings:.1f}% API cost savings (PDF may have visual content)")
    else:
        print("📊 0% savings - PDF requires Vision for all pages")
    print("=" * 60)
    
    return api_savings


def main():
    """Run hybrid detection API test"""
    print("=" * 60)
    print("HYBRID TEXT/VISION DETECTION - API TEST")
    print("Feature: hybrid-text-vision")
    print("=" * 60)
    
    # Check server health
    if not check_server_health():
        print("\n❌ Server not available. Please check deployment.")
        sys.exit(1)
    
    # Run ingestion test
    result = test_hybrid_ingestion()
    
    if result:
        savings = analyze_results(result)
        
        # Return exit code based on success
        if result.get('status') == 'completed':
            print("\n✅ Test PASSED!")
            sys.exit(0)
        else:
            print("\n⚠️ Test completed with warnings")
            sys.exit(0)
    else:
        print("\n❌ Test FAILED!")
        sys.exit(1)


if __name__ == "__main__":
    main()
