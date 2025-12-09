"""
Semantic Chunking Re-ingestion Script

Feature: semantic-chunking
Re-ingests PDF documents using Vision-based extraction with semantic chunking.

Usage:
    python scripts/reingest_with_chunking.py --pdf <path> --document-id <id>
    python scripts/reingest_with_chunking.py --truncate-first --pdf <path> --document-id <id>

Example:
    python scripts/reingest_with_chunking.py --pdf data/COLREGs.pdf --document-id colregs_2024
    python scripts/reingest_with_chunking.py --truncate-first --pdf data/maritime_law.pdf --document-id law_2024

**Feature: semantic-chunking**
**Validates: Requirements 7.1, 7.2**
"""
import asyncio
import argparse
import logging
import sys
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def truncate_document(document_id: str) -> int:
    """
    Truncate all chunks for a document (backup recommended first).
    
    Returns number of deleted rows.
    """
    from app.core.database import get_shared_session_factory
    from sqlalchemy import text as sql_text
    
    session_factory = get_shared_session_factory()
    
    with session_factory() as session:
        result = session.execute(
            sql_text("DELETE FROM knowledge_embeddings WHERE document_id = :doc_id"),
            {"doc_id": document_id}
        )
        deleted = result.rowcount
        session.commit()
    
    return deleted


async def get_document_stats(document_id: str) -> dict:
    """Get statistics for a document."""
    from app.core.database import get_shared_session_factory
    from sqlalchemy import text as sql_text
    
    session_factory = get_shared_session_factory()
    
    with session_factory() as session:
        # Total chunks
        result = session.execute(
            sql_text("""
                SELECT 
                    COUNT(*) as total_chunks,
                    COUNT(DISTINCT page_number) as total_pages,
                    AVG(confidence_score) as avg_confidence
                FROM knowledge_embeddings 
                WHERE document_id = :doc_id
            """),
            {"doc_id": document_id}
        ).fetchone()
        
        # Content type distribution
        type_result = session.execute(
            sql_text("""
                SELECT content_type, COUNT(*) as count
                FROM knowledge_embeddings 
                WHERE document_id = :doc_id
                GROUP BY content_type
            """),
            {"doc_id": document_id}
        ).fetchall()
        
        content_types = {row[0]: row[1] for row in type_result}
        
        return {
            "total_chunks": result[0] or 0,
            "total_pages": result[1] or 0,
            "avg_confidence": round(result[2] or 0, 2),
            "content_types": content_types
        }


async def main():
    parser = argparse.ArgumentParser(description="Semantic Chunking PDF Re-ingestion")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--document-id", required=True, help="Document identifier")
    parser.add_argument("--truncate-first", action="store_true", help="Delete existing data before ingestion")
    parser.add_argument("--resume", action="store_true", default=True, help="Resume from last page")
    parser.add_argument("--no-resume", action="store_true", help="Start from beginning")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without executing")
    args = parser.parse_args()
    
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"❌ PDF file not found: {pdf_path}")
        sys.exit(1)
    
    print("=" * 70)
    print("🔄 SEMANTIC CHUNKING RE-INGESTION")
    print("=" * 70)
    print(f"\n📄 PDF: {pdf_path}")
    print(f"🆔 Document ID: {args.document_id}")
    print(f"🗑️  Truncate first: {args.truncate_first}")
    print(f"🔄 Resume: {not args.no_resume}")
    print(f"📅 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if args.dry_run:
        print("\n⚠️  DRY RUN MODE - No changes will be made")
        sys.exit(0)
    
    # Check existing data
    print("\n📊 Checking existing data...")
    existing_stats = await get_document_stats(args.document_id)
    if existing_stats["total_chunks"] > 0:
        print(f"   Found {existing_stats['total_chunks']} existing chunks")
        print(f"   Pages: {existing_stats['total_pages']}")
        print(f"   Avg confidence: {existing_stats['avg_confidence']}")
        print(f"   Content types: {existing_stats['content_types']}")
    else:
        print("   No existing data found")
    
    # Truncate if requested
    if args.truncate_first and existing_stats["total_chunks"] > 0:
        print(f"\n🗑️  Truncating {existing_stats['total_chunks']} existing chunks...")
        deleted = await truncate_document(args.document_id)
        print(f"   Deleted {deleted} rows")
    
    # Import service
    from app.services.multimodal_ingestion_service import get_ingestion_service
    
    service = get_ingestion_service()
    
    print("\n🚀 Starting semantic chunking pipeline...")
    print("   1. PDF → Images (PyMuPDF - no external deps)")
    print("   2. Images → Supabase Storage")
    print("   3. Images → Gemini Vision (text extraction)")
    print("   4. Text → Semantic Chunking (maritime patterns)")
    print("   5. Chunks + Embeddings → Neon Database")
    print()
    
    # Run ingestion
    start_time = datetime.now()
    result = await service.ingest_pdf(
        pdf_path=str(pdf_path),
        document_id=args.document_id,
        resume=not args.no_resume
    )
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    
    # Get final stats
    final_stats = await get_document_stats(args.document_id)
    
    # Print results
    print("\n" + "=" * 70)
    print("📊 INGESTION RESULTS")
    print("=" * 70)
    print(f"Document ID:        {result.document_id}")
    print(f"Total Pages:        {result.total_pages}")
    print(f"Successful Pages:   {result.successful_pages}")
    print(f"Failed Pages:       {result.failed_pages}")
    print(f"Success Rate:       {result.success_rate:.1f}%")
    print(f"Duration:           {duration:.1f} seconds")
    print(f"Avg Time/Page:      {duration/max(result.total_pages, 1):.1f} seconds")
    
    print("\n📈 CHUNKING STATISTICS")
    print("-" * 40)
    print(f"Total Chunks:       {final_stats['total_chunks']}")
    print(f"Avg Chunks/Page:    {final_stats['total_chunks']/max(final_stats['total_pages'], 1):.1f}")
    print(f"Avg Confidence:     {final_stats['avg_confidence']}")
    print(f"Content Types:")
    for ctype, count in final_stats['content_types'].items():
        print(f"   - {ctype}: {count}")
    
    if result.errors:
        print(f"\n⚠️  Errors ({len(result.errors)}):")
        for error in result.errors[:5]:
            print(f"   - {error}")
        if len(result.errors) > 5:
            print(f"   ... and {len(result.errors) - 5} more")
    
    if result.failed_pages == 0:
        print("\n✅ Ingestion completed successfully!")
    else:
        print(f"\n⚠️  Ingestion completed with {result.failed_pages} failures")
        print("   Run with --resume to retry failed pages")
    
    print("\n📝 Next steps:")
    print("   1. Verify chunks: SELECT content_type, COUNT(*) FROM knowledge_embeddings WHERE document_id = '<id>' GROUP BY content_type")
    print("   2. Test search: curl -X POST /api/v1/chat -d '{\"message\": \"Điều 15\", ...}'")
    print("   3. Check document hierarchy in search results")


if __name__ == "__main__":
    asyncio.run(main())
