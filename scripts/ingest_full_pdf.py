"""
Full PDF Ingestion Script with Batch Processing.

Handles Render Free Tier worker timeout (~30s) by processing PDF in small batches.
Each batch processes 10 pages to stay within timeout limits.

Feature: hybrid-text-vision
Usage:
    python scripts/ingest_full_pdf.py
    python scripts/ingest_full_pdf.py --local  # Use local server
"""
import os
import sys
import time
import argparse
import requests

# Configuration
RENDER_URL = os.getenv("RENDER_URL", "https://maritime-ai-chatbot.onrender.com")
LOCAL_URL = "http://localhost:8000"

# PDF to ingest
PDF_PATH = "data/VanBanGoc_95.2015.QH13.P1.pdf"
DOCUMENT_ID = "luat-hang-hai-2015-p1"

# Batch settings - 10 pages per batch for Render Free Tier (~30s timeout)
BATCH_SIZE = 10
MAX_RETRIES = 3  # Retries per batch
RETRY_DELAY = 5  # Seconds between retries
BATCH_DELAY = 3  # Seconds between batches


def get_api_urls(use_local: bool = False):
    """Get API URLs based on environment"""
    base_url = LOCAL_URL if use_local else RENDER_URL
    return {
        'ingest': f"{base_url}/api/v1/knowledge/ingest-multimodal",
        'health': f"{base_url}/api/v1/health",
        'stats': f"{base_url}/api/v1/knowledge/stats"
    }


def check_health(urls: dict) -> bool:
    """Check server health"""
    try:
        response = requests.get(urls['health'], timeout=30)
        return response.status_code == 200
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False


def get_total_pages(pdf_path: str) -> int:
    """Get total pages in PDF using PyMuPDF"""
    try:
        import fitz
        doc = fitz.open(pdf_path)
        total = len(doc)
        doc.close()
        return total
    except Exception as e:
        print(f"❌ Cannot read PDF: {e}")
        return 0


def ingest_batch(urls: dict, start_page: int, end_page: int) -> dict:
    """
    Ingest a batch of pages.
    
    Args:
        urls: API URLs
        start_page: Start page (1-indexed)
        end_page: End page (1-indexed, inclusive)
        
    Returns:
        dict: API response or None on error
    """
    if not os.path.exists(PDF_PATH):
        print(f"❌ PDF not found: {PDF_PATH}")
        return None
    
    with open(PDF_PATH, 'rb') as f:
        files = {'file': (os.path.basename(PDF_PATH), f, 'application/pdf')}
        data = {
            'document_id': DOCUMENT_ID,
            'role': 'admin',
            'resume': 'false',  # Don't use resume, we control pages explicitly
            'start_page': str(start_page),
            'end_page': str(end_page),
        }
        
        try:
            response = requests.post(
                urls['ingest'],
                files=files,
                data=data,
                timeout=60  # 60 seconds per batch
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                print(f"❌ API Error: {response.status_code}")
                try:
                    print(f"   Detail: {response.json().get('detail', 'Unknown')}")
                except:
                    pass
                return None
                
        except requests.exceptions.Timeout:
            print("⚠️ Request timed out")
            return None
        except Exception as e:
            print(f"❌ Error: {e}")
            return None


def main():
    """Run full PDF ingestion with batch processing"""
    parser = argparse.ArgumentParser(description='Ingest PDF with batch processing')
    parser.add_argument('--local', action='store_true', help='Use local server')
    parser.add_argument('--batch-size', type=int, default=BATCH_SIZE, help='Pages per batch')
    parser.add_argument('--start', type=int, default=1, help='Start from page (1-indexed)')
    args = parser.parse_args()
    
    urls = get_api_urls(args.local)
    batch_size = args.batch_size
    
    print("=" * 60)
    print("FULL PDF INGESTION WITH BATCH PROCESSING")
    print(f"Document: {DOCUMENT_ID}")
    print(f"PDF: {PDF_PATH}")
    print(f"Server: {'LOCAL' if args.local else 'RENDER'}")
    print(f"Batch Size: {batch_size} pages")
    print("=" * 60)
    
    # Check server
    print("\n🔍 Checking server health...")
    if not check_health(urls):
        print("❌ Server not available")
        sys.exit(1)
    print("✅ Server is healthy")
    
    # Get total pages
    total_pages = get_total_pages(PDF_PATH)
    if total_pages == 0:
        print("❌ Cannot determine PDF page count")
        sys.exit(1)
    print(f"📄 Total pages: {total_pages}")
    
    # Calculate batches
    start_page = args.start
    num_batches = (total_pages - start_page + 1 + batch_size - 1) // batch_size
    print(f"📦 Batches needed: {num_batches}")
    
    # Track progress
    total_successful = 0
    total_vision = 0
    total_direct = 0
    total_fallback = 0
    failed_batches = []
    
    print("\n" + "-" * 60)
    
    # Process each batch
    current_page = start_page
    batch_num = 0
    
    while current_page <= total_pages:
        batch_num += 1
        end_page = min(current_page + batch_size - 1, total_pages)
        
        print(f"\n📤 Batch {batch_num}/{num_batches}: Pages {current_page}-{end_page}")
        
        # Retry logic for each batch
        success = False
        for retry in range(MAX_RETRIES):
            result = ingest_batch(urls, current_page, end_page)
            
            if result:
                pages_in_batch = result.get('successful_pages', 0)
                vision = result.get('vision_pages', 0)
                direct = result.get('direct_pages', 0)
                fallback = result.get('fallback_pages', 0)
                
                total_successful += pages_in_batch
                total_vision += vision
                total_direct += direct
                total_fallback += fallback
                
                print(f"   ✅ Processed: {pages_in_batch} pages")
                print(f"   📊 Vision: {vision}, Direct: {direct}, Fallback: {fallback}")
                
                success = True
                break
            else:
                if retry < MAX_RETRIES - 1:
                    print(f"   ⚠️ Retry {retry + 1}/{MAX_RETRIES}...")
                    time.sleep(RETRY_DELAY)
        
        if not success:
            print(f"   ❌ Batch failed after {MAX_RETRIES} retries")
            failed_batches.append((current_page, end_page))
        
        # Move to next batch
        current_page = end_page + 1
        
        # Wait between batches to avoid overwhelming server
        if current_page <= total_pages:
            print(f"   ⏳ Waiting {BATCH_DELAY}s before next batch...")
            time.sleep(BATCH_DELAY)
    
    # Final summary
    print("\n" + "=" * 60)
    print("📊 FINAL RESULTS")
    print("=" * 60)
    print(f"Total Pages: {total_pages}")
    print(f"Successful: {total_successful}")
    print(f"Vision Pages: {total_vision} (Gemini API - PAID)")
    print(f"Direct Pages: {total_direct} (PyMuPDF - FREE)")
    print(f"Fallback Pages: {total_fallback}")
    
    if total_successful > 0:
        savings = (total_direct / total_successful) * 100
        print(f"API Savings: {savings:.1f}%")
    
    if failed_batches:
        print(f"\n⚠️ Failed batches: {len(failed_batches)}")
        for start, end in failed_batches:
            print(f"   - Pages {start}-{end}")
        print("\nTo retry failed batches, run:")
        for start, end in failed_batches:
            print(f"   python scripts/ingest_full_pdf.py --start {start} --batch-size {end - start + 1}")
    else:
        print("\n✅ All batches completed successfully!")
    
    # Visual representation
    print("\n" + "-" * 60)
    print("📈 Extraction Method Distribution:")
    bar = ""
    for i in range(total_successful):
        if i < total_direct:
            bar += "🟢"
        else:
            bar += "🔴"
    print(bar[:50])  # Limit display
    if total_successful > 50:
        print(f"   ... ({total_successful} total)")
    print("🟢 = Direct (FREE)  🔴 = Vision (PAID)")


if __name__ == "__main__":
    main()
