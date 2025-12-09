"""
Bounding Box Re-ingestion Script

Feature: source-highlight-citation
Validates: Requirements 4.1, 4.2, 4.3

Updates existing chunks with bounding_boxes coordinates for PDF highlighting.
Preserves embeddings (vector data) - only updates bounding_boxes field.

Usage:
    python scripts/reingest_bounding_boxes.py --pdf <path> --document-id <id>
    python scripts/reingest_bounding_boxes.py --pdf data/COLREGs.pdf --document-id colregs_2024

Options:
    --pdf           Path to PDF file
    --document-id   Document identifier to update
    --dry-run       Preview changes without updating database
    --batch-size    Number of chunks to process per batch (default: 50)
    --verbose       Show detailed progress

**Feature: source-highlight-citation**
**Validates: Requirements 4.1, 4.2, 4.3**
"""
import asyncio
import argparse
import json
import logging
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ReingestionStats:
    """Statistics for re-ingestion process."""
    total_chunks: int = 0
    processed: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    already_has_boxes: int = 0
    
    @property
    def success_rate(self) -> float:
        if self.processed == 0:
            return 0.0
        return (self.updated / self.processed) * 100


async def get_chunks_for_document(document_id: str) -> list[dict]:
    """
    Get all chunks for a document from database.
    
    Returns list of chunks with node_id, content, page_number.
    """
    from app.core.database import get_shared_pool
    
    pool = await get_shared_pool()
    if pool is None:
        raise RuntimeError("Database pool not available")
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT 
                node_id,
                content,
                page_number,
                bounding_boxes
            FROM knowledge_embeddings
            WHERE document_id = $1
            ORDER BY page_number, chunk_index
            """,
            document_id
        )
        
        return [
            {
                "node_id": row["node_id"],
                "content": row["content"],
                "page_number": row["page_number"],
                "bounding_boxes": row["bounding_boxes"]
            }
            for row in rows
        ]


async def update_chunk_bounding_boxes(
    node_id: str,
    bounding_boxes: list[dict]
) -> bool:
    """
    Update bounding_boxes for a single chunk.
    
    Preserves all other fields including embeddings.
    
    **Validates: Requirements 4.1, 4.2**
    """
    from app.core.database import get_shared_pool
    
    pool = await get_shared_pool()
    if pool is None:
        return False
    
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE knowledge_embeddings
                SET bounding_boxes = $2::jsonb
                WHERE node_id = $1
                """,
                node_id,
                json.dumps(bounding_boxes)
            )
            return True
    except Exception as e:
        logger.error(f"Failed to update {node_id}: {e}")
        return False


async def extract_bounding_boxes_for_chunk(
    pdf_path: str,
    page_number: int,
    content: str
) -> Optional[list[dict]]:
    """
    Extract bounding boxes for a chunk from PDF page.
    
    Returns list of bounding box dicts or None if extraction fails.
    """
    import fitz  # PyMuPDF
    from app.engine.bounding_box_extractor import get_bounding_box_extractor
    
    try:
        doc = fitz.open(pdf_path)
        
        # Page numbers are 1-indexed in our system, 0-indexed in PyMuPDF
        page_idx = page_number - 1 if page_number else 0
        
        if page_idx < 0 or page_idx >= len(doc):
            logger.warning(f"Invalid page number: {page_number}")
            doc.close()
            return None
        
        page = doc[page_idx]
        extractor = get_bounding_box_extractor()
        
        boxes = extractor.extract_text_with_boxes(page, content)
        doc.close()
        
        if boxes:
            return [box.to_dict() for box in boxes]
        return None
        
    except Exception as e:
        logger.warning(f"Extraction failed for page {page_number}: {e}")
        return None


async def reingest_document(
    pdf_path: str,
    document_id: str,
    dry_run: bool = False,
    batch_size: int = 50,
    verbose: bool = False
) -> ReingestionStats:
    """
    Re-ingest bounding boxes for all chunks in a document.
    
    **Feature: source-highlight-citation**
    **Validates: Requirements 4.1, 4.2, 4.3**
    """
    stats = ReingestionStats()
    
    # Get all chunks for document
    print(f"\n📥 Fetching chunks for document: {document_id}")
    chunks = await get_chunks_for_document(document_id)
    stats.total_chunks = len(chunks)
    
    if stats.total_chunks == 0:
        print(f"❌ No chunks found for document_id: {document_id}")
        return stats
    
    print(f"   Found {stats.total_chunks} chunks")
    
    # Process in batches
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        
        print(f"\n📦 Processing batch {batch_num}/{total_batches} ({len(batch)} chunks)")
        
        for chunk in batch:
            stats.processed += 1
            node_id = chunk["node_id"]
            content = chunk["content"]
            page_number = chunk["page_number"]
            existing_boxes = chunk["bounding_boxes"]
            
            # Skip if already has bounding boxes
            if existing_boxes:
                stats.already_has_boxes += 1
                stats.skipped += 1
                if verbose:
                    print(f"   ⏭️  {node_id}: Already has bounding boxes")
                continue
            
            # Skip if no page number
            if not page_number:
                stats.skipped += 1
                if verbose:
                    print(f"   ⏭️  {node_id}: No page number")
                continue
            
            # Extract bounding boxes
            boxes = await extract_bounding_boxes_for_chunk(
                pdf_path, page_number, content or ""
            )
            
            if boxes:
                if dry_run:
                    stats.updated += 1
                    if verbose:
                        print(f"   ✅ {node_id}: Would update with {len(boxes)} boxes")
                else:
                    success = await update_chunk_bounding_boxes(node_id, boxes)
                    if success:
                        stats.updated += 1
                        if verbose:
                            print(f"   ✅ {node_id}: Updated with {len(boxes)} boxes")
                    else:
                        stats.failed += 1
                        if verbose:
                            print(f"   ❌ {node_id}: Update failed")
            else:
                stats.failed += 1
                if verbose:
                    print(f"   ⚠️  {node_id}: No boxes extracted")
        
        # Progress update
        progress = (stats.processed / stats.total_chunks) * 100
        print(f"   Progress: {stats.processed}/{stats.total_chunks} ({progress:.1f}%)")
    
    return stats


async def main():
    parser = argparse.ArgumentParser(
        description="Re-ingest bounding boxes for PDF highlighting"
    )
    parser.add_argument(
        "--pdf", 
        required=True, 
        help="Path to PDF file"
    )
    parser.add_argument(
        "--document-id", 
        required=True, 
        help="Document identifier to update"
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Preview changes without updating database"
    )
    parser.add_argument(
        "--batch-size", 
        type=int, 
        default=50, 
        help="Chunks per batch (default: 50)"
    )
    parser.add_argument(
        "--verbose", 
        action="store_true", 
        help="Show detailed progress"
    )
    args = parser.parse_args()
    
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"❌ PDF file not found: {pdf_path}")
        sys.exit(1)
    
    print("=" * 60)
    print("Feature: source-highlight-citation")
    print("Bounding Box Re-ingestion Script")
    print("=" * 60)
    print(f"\n📄 PDF: {pdf_path}")
    print(f"🆔 Document ID: {args.document_id}")
    print(f"🔢 Batch Size: {args.batch_size}")
    if args.dry_run:
        print("⚠️  DRY RUN MODE - No changes will be made")
    
    print("\n🚀 Starting bounding box extraction...")
    print("   - Preserves existing embeddings (vector data)")
    print("   - Only updates bounding_boxes field")
    print("   - Skips chunks that already have bounding boxes")
    
    # Run re-ingestion
    stats = await reingest_document(
        pdf_path=str(pdf_path),
        document_id=args.document_id,
        dry_run=args.dry_run,
        batch_size=args.batch_size,
        verbose=args.verbose
    )
    
    # Print results
    print("\n" + "=" * 60)
    print("📊 RE-INGESTION RESULTS")
    print("=" * 60)
    print(f"Total Chunks:        {stats.total_chunks}")
    print(f"Processed:           {stats.processed}")
    print(f"Updated:             {stats.updated}")
    print(f"Skipped:             {stats.skipped}")
    print(f"  - Already had boxes: {stats.already_has_boxes}")
    print(f"Failed:              {stats.failed}")
    print(f"Success Rate:        {stats.success_rate:.1f}%")
    
    if args.dry_run:
        print("\n⚠️  DRY RUN - No changes were made")
        print("   Run without --dry-run to apply changes")
    elif stats.failed == 0 and stats.updated > 0:
        print("\n✅ Re-ingestion completed successfully!")
    elif stats.updated == 0 and stats.already_has_boxes == stats.total_chunks:
        print("\n✅ All chunks already have bounding boxes!")
    else:
        print(f"\n⚠️  Re-ingestion completed with {stats.failed} failures")
    
    print("\n📝 Verification:")
    print(f"   SELECT COUNT(*) FROM knowledge_embeddings")
    print(f"   WHERE document_id = '{args.document_id}'")
    print(f"   AND bounding_boxes IS NOT NULL;")


if __name__ == "__main__":
    asyncio.run(main())
