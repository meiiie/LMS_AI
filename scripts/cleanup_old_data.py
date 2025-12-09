"""
Cleanup Old Data Script

Xóa data cũ không có image_url để tránh trả về sources không có evidence images.

Usage:
    python scripts/cleanup_old_data.py --dry-run  # Preview only
    python scripts/cleanup_old_data.py --execute  # Actually delete
"""
import os
import asyncio
import argparse
from dotenv import load_dotenv

load_dotenv()

async def analyze_old_data():
    """Analyze which documents have incomplete image_url coverage"""
    import asyncpg
    
    db_url = os.getenv("DATABASE_URL", "")
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    db_url = db_url.replace("postgres://", "postgresql://")
    
    conn = await asyncpg.connect(db_url)
    try:
        print("📊 Analyzing documents with incomplete image coverage...")
        print("="*60)
        
        rows = await conn.fetch(
            """
            SELECT 
                document_id,
                COUNT(*) as total,
                COUNT(CASE WHEN image_url IS NOT NULL AND image_url != '' THEN 1 END) as with_image,
                ROUND(100.0 * COUNT(CASE WHEN image_url IS NOT NULL AND image_url != '' THEN 1 END) / COUNT(*), 1) as coverage_pct
            FROM knowledge_embeddings
            GROUP BY document_id
            ORDER BY coverage_pct ASC, total DESC
            """
        )
        
        incomplete_docs = []
        complete_docs = []
        
        for row in rows:
            doc_info = {
                'document_id': row['document_id'],
                'total': row['total'],
                'with_image': row['with_image'],
                'coverage': float(row['coverage_pct'])
            }
            
            if doc_info['coverage'] < 100:
                incomplete_docs.append(doc_info)
            else:
                complete_docs.append(doc_info)
        
        print("\n❌ Documents with INCOMPLETE image coverage (candidates for cleanup):")
        for doc in incomplete_docs:
            print(f"  - {doc['document_id']}: {doc['with_image']}/{doc['total']} ({doc['coverage']}%)")
        
        print("\n✅ Documents with COMPLETE image coverage:")
        for doc in complete_docs:
            print(f"  - {doc['document_id']}: {doc['with_image']}/{doc['total']} ({doc['coverage']}%)")
        
        return incomplete_docs
        
    finally:
        await conn.close()


async def cleanup_document(document_id: str, dry_run: bool = True):
    """Delete all chunks for a specific document"""
    import asyncpg
    
    db_url = os.getenv("DATABASE_URL", "")
    db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")
    db_url = db_url.replace("postgres://", "postgresql://")
    
    conn = await asyncpg.connect(db_url)
    try:
        # Count first
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM knowledge_embeddings WHERE document_id = $1",
            document_id
        )
        
        if dry_run:
            print(f"  [DRY RUN] Would delete {count} chunks from '{document_id}'")
        else:
            await conn.execute(
                "DELETE FROM knowledge_embeddings WHERE document_id = $1",
                document_id
            )
            print(f"  ✅ Deleted {count} chunks from '{document_id}'")
        
        return count
        
    finally:
        await conn.close()


async def main():
    parser = argparse.ArgumentParser(description='Cleanup old data without image_url')
    parser.add_argument('--dry-run', action='store_true', help='Preview only, no deletion')
    parser.add_argument('--execute', action='store_true', help='Actually delete data')
    parser.add_argument('--document', type=str, help='Specific document to delete')
    args = parser.parse_args()
    
    if not args.dry_run and not args.execute:
        print("Please specify --dry-run or --execute")
        return
    
    dry_run = not args.execute
    
    if args.document:
        # Delete specific document
        print(f"\n{'[DRY RUN] ' if dry_run else ''}Cleaning up document: {args.document}")
        await cleanup_document(args.document, dry_run)
    else:
        # Analyze and suggest
        incomplete_docs = await analyze_old_data()
        
        if incomplete_docs:
            print("\n" + "="*60)
            print("RECOMMENDED ACTIONS:")
            print("="*60)
            
            for doc in incomplete_docs:
                if doc['coverage'] < 50:
                    print(f"\n🗑️ DELETE '{doc['document_id']}' ({doc['coverage']}% coverage)")
                    print(f"   Command: python scripts/cleanup_old_data.py --execute --document {doc['document_id']}")
                else:
                    print(f"\n⚠️ REVIEW '{doc['document_id']}' ({doc['coverage']}% coverage)")
            
            print("\n💡 After cleanup, re-ingest with Multimodal pipeline:")
            print("   python scripts/ingest_full_pdf.py --force")


if __name__ == "__main__":
    asyncio.run(main())
