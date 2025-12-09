"""
Apply bounding_boxes migration directly to Neon PostgreSQL.

Feature: source-highlight-citation
Validates: Requirements 3.1, 3.2, 3.3

Usage:
    .venv\Scripts\python scripts/apply_bounding_boxes_migration.py
"""
import os
import asyncio
import asyncpg
from dotenv import load_dotenv

load_dotenv()


async def apply_migration():
    """Apply bounding_boxes column migration."""
    database_url = os.getenv("DATABASE_URL")
    
    if not database_url:
        print("❌ DATABASE_URL not found in environment")
        return False
    
    # Convert SQLAlchemy URL to asyncpg format
    if "postgresql+asyncpg://" in database_url:
        database_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    
    print("🔄 Connecting to Neon PostgreSQL...")
    
    try:
        conn = await asyncpg.connect(database_url)
        
        # Check if column already exists
        check_query = """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'knowledge_embeddings' 
        AND column_name = 'bounding_boxes'
        """
        existing = await conn.fetchval(check_query)
        
        if existing:
            print("✅ Column 'bounding_boxes' already exists")
        else:
            # Add bounding_boxes column
            print("📝 Adding 'bounding_boxes' column...")
            await conn.execute("""
                ALTER TABLE knowledge_embeddings 
                ADD COLUMN bounding_boxes JSONB DEFAULT NULL
            """)
            print("✅ Column 'bounding_boxes' added successfully")
        
        # Check if index exists
        index_check = """
        SELECT indexname 
        FROM pg_indexes 
        WHERE tablename = 'knowledge_embeddings' 
        AND indexname = 'idx_knowledge_bounding_boxes'
        """
        index_exists = await conn.fetchval(index_check)
        
        if index_exists:
            print("✅ Index 'idx_knowledge_bounding_boxes' already exists")
        else:
            # Create GIN index
            print("📝 Creating GIN index for bounding_boxes...")
            await conn.execute("""
                CREATE INDEX idx_knowledge_bounding_boxes 
                ON knowledge_embeddings USING GIN(bounding_boxes)
            """)
            print("✅ Index 'idx_knowledge_bounding_boxes' created successfully")
        
        # Verify
        print("\n📊 Verification:")
        columns = await conn.fetch("""
            SELECT column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'knowledge_embeddings' 
            AND column_name = 'bounding_boxes'
        """)
        for col in columns:
            print(f"   Column: {col['column_name']}, Type: {col['data_type']}")
        
        await conn.close()
        print("\n✅ Migration completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Migration failed: {e}")
        return False


if __name__ == "__main__":
    asyncio.run(apply_migration())
