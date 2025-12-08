"""
Truncate Old Knowledge Data Script

CHỈ THỊ KỸ THUẬT SỐ 26: Data Migration
Removes old pypdf-extracted data before re-ingesting with Multimodal pipeline.

Usage:
    python scripts/truncate_old_knowledge.py [--backup] [--force]

Options:
    --backup    Create backup before truncating (recommended)
    --force     Skip confirmation prompt

**Feature: multimodal-rag-vision**
**Validates: Requirements 5.3**
"""
import asyncio
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.config import settings

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def get_db_pool():
    """Get database connection pool"""
    import asyncpg
    
    database_url = settings.database_url
    if not database_url:
        raise ValueError("DATABASE_URL not configured")
    
    # Convert to asyncpg format
    if database_url.startswith("postgresql+asyncpg://"):
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    return await asyncpg.create_pool(database_url, min_size=1, max_size=5)


async def backup_data(pool) -> str:
    """
    Create backup of knowledge_embeddings data.
    
    Returns backup filename.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = f"backup_knowledge_embeddings_{timestamp}.sql"
    
    async with pool.acquire() as conn:
        # Get row count
        count = await conn.fetchval("SELECT COUNT(*) FROM knowledge_embeddings")
        logger.info(f"Found {count} rows to backup")
        
        if count == 0:
            logger.info("No data to backup")
            return None
        
        # Export data as INSERT statements
        rows = await conn.fetch(
            "SELECT node_id, content, embedding::text FROM knowledge_embeddings"
        )
        
        with open(backup_file, 'w', encoding='utf-8') as f:
            f.write("-- Backup of knowledge_embeddings\n")
            f.write(f"-- Created: {datetime.now().isoformat()}\n")
            f.write(f"-- Rows: {count}\n\n")
            
            for row in rows:
                node_id = row['node_id'].replace("'", "''")
                content = row['content'].replace("'", "''") if row['content'] else ''
                embedding = row['embedding'] if row['embedding'] else 'NULL'
                
                f.write(
                    f"INSERT INTO knowledge_embeddings (node_id, content, embedding) "
                    f"VALUES ('{node_id}', '{content}', '{embedding}'::vector);\n"
                )
        
        logger.info(f"Backup created: {backup_file}")
        return backup_file


async def truncate_data(pool):
    """
    Truncate knowledge_embeddings table.
    
    **Validates: Requirements 5.3**
    """
    async with pool.acquire() as conn:
        # Get current count
        count_before = await conn.fetchval("SELECT COUNT(*) FROM knowledge_embeddings")
        logger.info(f"Current row count: {count_before}")
        
        # Truncate table
        await conn.execute("TRUNCATE TABLE knowledge_embeddings")
        
        # Verify
        count_after = await conn.fetchval("SELECT COUNT(*) FROM knowledge_embeddings")
        logger.info(f"After truncate: {count_after} rows")
        
        return count_before


async def main():
    parser = argparse.ArgumentParser(description="Truncate old knowledge data")
    parser.add_argument("--backup", action="store_true", help="Create backup before truncating")
    parser.add_argument("--force", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()
    
    print("=" * 60)
    print("CHỈ THỊ 26: Truncate Old Knowledge Data")
    print("=" * 60)
    
    # Confirmation
    if not args.force:
        response = input("\n⚠️  This will DELETE all data in knowledge_embeddings. Continue? [y/N]: ")
        if response.lower() != 'y':
            print("Aborted.")
            return
    
    pool = await get_db_pool()
    
    try:
        # Backup if requested
        if args.backup:
            print("\n📦 Creating backup...")
            backup_file = await backup_data(pool)
            if backup_file:
                print(f"✅ Backup saved to: {backup_file}")
        
        # Truncate
        print("\n🗑️  Truncating knowledge_embeddings...")
        rows_deleted = await truncate_data(pool)
        
        print(f"\n✅ Successfully truncated {rows_deleted} rows")
        print("\nNext step: Run multimodal re-ingestion with:")
        print("  python scripts/reingest_multimodal.py --pdf data/COLREGs.pdf --document-id colregs_2024")
        
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
