"""
Multimodal Re-ingestion Script

CHỈ THỊ KỸ THUẬT SỐ 26: Multimodal RAG Pipeline
Re-ingests PDF documents using Vision-based extraction.

Usage:
    python scripts/reingest_multimodal.py --pdf <path> --document-id <id>

Example:
    python scripts/reingest_multimodal.py --pdf data/COLREGs.pdf --document-id colregs_2024

**Feature: multimodal-rag-vision**
**Validates: Requirements 2.1, 7.1, 7.4**
"""
import asyncio
import argparse
import logging
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def main():
    parser = argparse.ArgumentParser(description="Multimodal PDF Re-ingestion")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--document-id", required=True, help="Document identifier")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from last page")
    parser.add_argument("--no-resume", action="store_true", help="Start from beginning")
    args = parser.parse_args()
    
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"❌ PDF file not found: {pdf_path}")
        sys.exit(1)
    
    print("=" * 60)
    print("CHỈ THỊ 26: Multimodal RAG Re-ingestion")
    print("=" * 60)
    print(f"\n📄 PDF: {pdf_path}")
    print(f"🆔 Document ID: {args.document_id}")
    print(f"🔄 Resume: {not args.no_resume}")
    
    # Import service
    from app.services.multimodal_ingestion_service import get_ingestion_service
    
    service = get_ingestion_service()
    
    print("\n🚀 Starting ingestion pipeline...")
    print("   1. PDF → Images (pdf2image)")
    print("   2. Images → Supabase Storage")
    print("   3. Images → Gemini Vision (text extraction)")
    print("   4. Text + Embeddings → Neon Database")
    print()
    
    # Run ingestion
    result = await service.ingest_pdf(
        pdf_path=str(pdf_path),
        document_id=args.document_id,
        resume=not args.no_resume
    )
    
    # Print results
    print("\n" + "=" * 60)
    print("📊 INGESTION RESULTS")
    print("=" * 60)
    print(f"Document ID:      {result.document_id}")
    print(f"Total Pages:      {result.total_pages}")
    print(f"Successful:       {result.successful_pages}")
    print(f"Failed:           {result.failed_pages}")
    print(f"Success Rate:     {result.success_rate:.1f}%")
    
    if result.errors:
        print(f"\n⚠️  Errors ({len(result.errors)}):")
        for error in result.errors[:5]:  # Show first 5 errors
            print(f"   - {error}")
        if len(result.errors) > 5:
            print(f"   ... and {len(result.errors) - 5} more")
    
    if result.failed_pages == 0:
        print("\n✅ Ingestion completed successfully!")
    else:
        print(f"\n⚠️  Ingestion completed with {result.failed_pages} failures")
        print("   Run with --resume to retry failed pages")
    
    print("\n📝 Next steps:")
    print("   1. Verify data in Neon: SELECT COUNT(*) FROM knowledge_embeddings WHERE document_id = '<id>'")
    print("   2. Test search: curl -X POST /api/v1/chat -d '{\"message\": \"Rule 15\", ...}'")
    print("   3. Check evidence images in response")


if __name__ == "__main__":
    asyncio.run(main())
