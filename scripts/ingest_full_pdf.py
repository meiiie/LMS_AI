"""
Full PDF Ingestion Script with Server-Side Progress Tracking.

This script handles large PDF ingestion by:
1. Querying server for already-processed pages
2. Only sending pages that haven't been processed
3. Using small batches to avoid timeout/memory issues

Feature: hybrid-text-vision
Usage:
    python scripts/ingest_full_pdf.py
    python scripts/ingest_full_pdf.py --local
    python scripts/ingest_full_pdf.py --batch-size 5
    python scripts/ingest_full_pdf.py --force  # Re-process all pages
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

# Batch settings - 5 pages per batch for Render Free Tier (512MB RAM, ~30s timeout)
BATCH_SIZE = 5
MAX_RETRIES = 2
RETRY_DELAY = 10
BATCH_DELAY = 5


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


def get_processed_pages(document_id: str) -> set:
    """
    Query database to find which pages have already been processed.
    Returns set of page numbers (1-indexed).
    """
    try:
        import asyncpg
        import asyncio
        from dotenv import load_dotenv
        
        load_dotenv()
        db_url = os.getenv("DATABASE_URL", "")
        
        if not db_url:
            print("⚠️ DATABASE_URL not set, cannot check processed pages")
            return set()
        
        # Convert URL format
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
        db_url = db_url.replace("postgres://", "postgresql://")
        
        async def query():
            conn = await asyncpg.connect(db_url)
            try:
                rows = await conn.fetch(
                    """
                    SELECT DISTINCT page_number 
                    FROM knowledge_embeddings 
                    WHERE document_id = $1 AND page_number IS NOT NULL
                    """,
                    document_id
                )
                return {row['page_number'] for row in rows}
            finally:
                await conn.close()
        
        return asyncio.run(query())
    except Exception as e:
        print(f"⚠️ Cannot query processed pages: {e}")
        return set()


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
            'resume': 'false',
            'start_page': str(start_page),
            'end_page': str(end_page),
        }
        
        try:
            response = requests.post(
                urls['ingest'],
                files=files,
                data=data,
                timeout=120  # 2 minutes per batch
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
            print("⚠️ Request timed out (server may still be processing)")
            return None
        except Exception as e:
            print(f"❌ Error: {e}")
            return None


def main():
    """Run full PDF ingestion with server-side progress tracking"""
    parser = argparse.ArgumentParser(description='Ingest PDF with batch processing')
    parser.add_argument('--local', action='store_true', help='Use local server')
    parser.add_argument('--batch-size', type=int, default=BATCH_SIZE, help='Pages per batch')
    parser.add_argument('--start', type=int, default=1, help='Start from page (1-indexed)')
    parser.add_argument('--force', action='store_true', help='Re-process all pages')
    args = parser.parse_args()
    
    urls = get_api_urls(args.local)
    batch_size = args.batch_size
    
    print("=" * 60)
    print("FULL PDF INGESTION WITH PROGRESS TRACKING")
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
    
    # Check which pages are already processed
    if args.force:
        processed_pages = set()
        print("🔄 Force mode: will re-process all pages")
    else:
        print("\n🔍 Checking already processed pages...")
        processed_pages = get_processed_pages(DOCUMENT_ID)
        if processed_pages:
            print(f"✅ Already processed: {len(processed_pages)} pages")
            print(f"   Pages: {sorted(processed_pages)[:10]}{'...' if len(processed_pages) > 10 else ''}")
        else:
            print("📝 No pages processed yet")
    
    # Determine pages to process
    all_pages = set(range(1, total_pages + 1))
    pages_to_process = sorted(all_pages - processed_pages)
    
    if not pages_to_process:
        print("\n✅ All pages already processed!")
        return
    
    print(f"\n📋 Pages to process: {len(pages_to_process)}")
    
    # Group into batches
    batches = []
    i = 0
    while i < len(pages_to_process):
        batch_pages = pages_to_process[i:i + batch_size]
        if batch_pages:
            batches.append((min(batch_pages), max(batch_pages)))
        i += batch_size
    
    print(f"📦 Batches needed: {len(batches)}")
    
    # Track progress
    total_successful = 0
    total_vision = 0
    total_direct = 0
    failed_batches = []
    
    print("\n" + "-" * 60)
    
    # Process each batch
    for batch_num, (start_page, end_page) in enumerate(batches, 1):
        print(f"\n📤 Batch {batch_num}/{len(batches)}: Pages {start_page}-{end_page}")
        
        # Retry logic
        success = False
        for retry in range(MAX_RETRIES):
            result = ingest_batch(urls, start_page, end_page)
            
            if result:
                pages_in_batch = result.get('successful_pages', 0)
                vision = result.get('vision_pages', 0)
                direct = result.get('direct_pages', 0)
                
                total_successful += pages_in_batch
                total_vision += vision
                total_direct += direct
                
                print(f"   ✅ Processed: {pages_in_batch} pages")
                print(f"   📊 Vision: {vision}, Direct: {direct}")
                
                success = True
                break
            else:
                if retry < MAX_RETRIES - 1:
                    print(f"   ⚠️ Retry {retry + 1}/{MAX_RETRIES} in {RETRY_DELAY}s...")
                    time.sleep(RETRY_DELAY)
        
        if not success:
            print(f"   ❌ Batch failed after {MAX_RETRIES} retries")
            failed_batches.append((start_page, end_page))
        
        # Wait between batches
        if batch_num < len(batches):
            print(f"   ⏳ Waiting {BATCH_DELAY}s...")
            time.sleep(BATCH_DELAY)
    
    # Final summary
    print("\n" + "=" * 60)
    print("📊 FINAL RESULTS")
    print("=" * 60)
    print(f"Total Pages: {total_pages}")
    print(f"Previously Processed: {len(processed_pages)}")
    print(f"Newly Processed: {total_successful}")
    print(f"Vision Pages: {total_vision}")
    print(f"Direct Pages: {total_direct}")
    
    if failed_batches:
        print(f"\n⚠️ Failed batches: {len(failed_batches)}")
        for start, end in failed_batches:
            print(f"   - Pages {start}-{end}")
        print("\nRun script again to retry failed batches")
    else:
        print("\n✅ All batches completed successfully!")


if __name__ == "__main__":
    main()
