"""
Run database migration for Contextual RAG feature

Usage: python -m scripts.run_migration
"""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.core.database import get_shared_session_factory


def run_contextual_content_migration():
    """Add contextual_content column to knowledge_embeddings table"""
    print("=" * 60)
    print("Running Contextual RAG Migration")
    print("=" * 60)
    
    migration_sql = """
    DO $$
    BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = 'knowledge_embeddings' 
            AND column_name = 'contextual_content'
        ) THEN
            ALTER TABLE knowledge_embeddings 
            ADD COLUMN contextual_content TEXT DEFAULT NULL;
            
            RAISE NOTICE 'Added contextual_content column to knowledge_embeddings';
        ELSE
            RAISE NOTICE 'Column contextual_content already exists';
        END IF;
    END $$;
    """
    
    try:
        session_factory = get_shared_session_factory()
        
        with session_factory() as session:
            print("\n🔄 Connecting to database...")
            
            # Run migration
            print("🔄 Running migration...")
            session.execute(text(migration_sql))
            session.commit()
            
            # Verify column exists
            result = session.execute(text("""
                SELECT column_name, data_type, is_nullable 
                FROM information_schema.columns 
                WHERE table_name = 'knowledge_embeddings' 
                AND column_name = 'contextual_content'
            """)).fetchone()
            
            if result:
                print(f"\n✅ Migration successful!")
                print(f"   Column: {result[0]}")
                print(f"   Type: {result[1]}")
                print(f"   Nullable: {result[2]}")
            else:
                print("\n⚠️  Column may not have been created. Check logs.")
                
    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    print("\n" + "=" * 60)
    print("Migration Complete!")
    print("=" * 60)
    return True


if __name__ == "__main__":
    run_contextual_content_migration()
