"""
Local Full PDF Ingestion Script.

Runs ingestion directly on local machine (bypasses Render timeout).
Connects to production databases (Neon, Supabase).

Feature: hybrid-text-vision
Usage:
    .venv\Scripts\Activate.ps1
    python scripts/ingest_local_full.py
    
Requirements:
    - .env file with production credentials
    - PDF file in data/ directory
"""
import asyncio
import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Load environment variables
from dotenv import load_dotenv
load_dotenv()


async def main():
    """Run full PDF ingestion locally"""
    print("=" * 60)
    print("LOCAL FULL PDF INGESTION")
    print("Feature: hybrid-text-vision")
    print("=" * 60)
    
    # Import after env loaded
    from app.services.multimodal_ingestion_service import get_ingestion_service
    
    # Configuration
    PDF_PATH = "data/VanBanGoc_95.2015.QH13.P1.pdf"
    DOCUMENT_ID = "luat-hang-hai-2015-p1-full"
    
    if not os.path.exists(PDF_PATH):
        print(f"❌ PDF not found: {PDF_PATH}")
        sys.exit(1)
    
    print(f"\n📄 PDF: {PDF_PATH}")
    print(f"📝 Document ID: {DOCUMENT_ID}")
    print(f"🔧 Running locally (no timeout!)\n")
    
    # Get ingestion service
    service = get_ingestion_service()
    
    print("⏳ Starting ingestion (this may take several minutes)...\n")
    
    # Run ingestion
    result = await service.ingest_pdf(
        pdf_path=PDF_PATH,
        document_id=DOCUMENT_ID,
        resume=False,  # Fresh start
        max_pages=None  # Process ALL pages
    )
    
    # Display results
    print("\n" + "=" * 60)
    print("📊 INGESTION RESULTS")
    print("=" * 60)
    
    print(f"\n📄 Document: {result.document_id}")
    print(f"📑 Total Pages: {result.total_pages}")
    print(f"✅ Successful: {result.successful_pages}")
    print(f"❌ Failed: {result.failed_pages}")
    print(f"📈 Success Rate: {result.success_rate:.1f}%")
    
    print(f"\n🔍 Hybrid Detection Stats:")
    print(f"   Vision Pages (Gemini API): {result.vision_pages}")
    print(f"   Direct Pages (PyMuPDF): {result.direct_pages}")
    print(f"   Fallback Pages: {result.fallback_pages}")
    print(f"   API Savings: {result.api_savings_percent:.1f}%")
    
    # Visual bar
    if result.total_pages > 0:
        bar_length = 40
        direct_bar = int((result.direct_pages / result.total_pages) * bar_length)
        vision_bar = bar_length - direct_bar
        print(f"\n   [{'🟢' * direct_bar}{'🔴' * vision_bar}]")
        print(f"   🟢 = Direct (FREE)  🔴 = Vision (PAID)")
    
    # Errors
    if result.errors:
        print(f"\n⚠️ Errors ({len(result.errors)}):")
        for err in result.errors[:5]:
            print(f"   - {err}")
    
    # Summary
    print("\n" + "=" * 60)
    if result.api_savings_percent >= 50:
        print(f"🎉 EXCELLENT! {result.api_savings_percent:.1f}% API cost savings!")
    elif result.api_savings_percent >= 30:
        print(f"✅ GOOD! {result.api_savings_percent:.1f}% API cost savings!")
    else:
        print(f"📊 {result.api_savings_percent:.1f}% API cost savings")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
