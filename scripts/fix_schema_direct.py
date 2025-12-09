#!/usr/bin/env python3
"""
Direct database schema fix for Maritime AI Service.
Runs ALTER TABLE statements directly without DO blocks.
"""
import os
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import psycopg2
from dotenv import load_dotenv

load_dotenv(project_root / ".env")


def get_database_url():
    """Get database URL from environment and convert to psycopg2 format."""
    url = os.getenv("DATABASE_URL") or os.getenv("NEON_DATABASE_URL")
    if not url:
        print("❌ DATABASE_URL or NEON_DATABASE_URL not set")
        sys.exit(1)
    
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    
    if "?" in url:
        base_url = url.split("?")[0]
        url = f"{base_url}?sslmode=require"
    else:
        url = f"{url}?sslmode=require"
    
    return url


def column_exists(cursor, table, column):
    """Check if a column exists in a table."""
    cursor.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns 
            WHERE table_name = %s AND column_name = %s
        )
    """, (table, column))
    return cursor.fetchone()[0]


def run_fix():
    """Run the schema fix."""
    database_url = get_database_url()
    
    print("🔧 Maritime AI Service - Direct Schema Fix")
    print("=" * 50)
    
    try:
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("📡 Connected to database")
        print()
        
        # =====================================================================
        # 1. Fix chat_messages table
        # =====================================================================
        print("📋 Fixing chat_messages table...")
        
        if not column_exists(cursor, 'chat_messages', 'is_blocked'):
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN is_blocked BOOLEAN DEFAULT FALSE")
            print("   ✓ Added is_blocked column")
        else:
            print("   ⚠ is_blocked already exists")
        
        if not column_exists(cursor, 'chat_messages', 'block_reason'):
            cursor.execute("ALTER TABLE chat_messages ADD COLUMN block_reason TEXT")
            print("   ✓ Added block_reason column")
        else:
            print("   ⚠ block_reason already exists")
        
        # Create index if not exists
        try:
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_chat_messages_is_blocked ON chat_messages(is_blocked)")
            print("   ✓ Created index on is_blocked")
        except Exception as e:
            print(f"   ⚠ Index: {e}")
        
        # =====================================================================
        # 2. Fix learning_profile table
        # =====================================================================
        print("\n📋 Fixing learning_profile table...")
        
        columns_to_add = [
            ("attributes", "JSONB DEFAULT '{}'"),
            ("weak_areas", "JSONB DEFAULT '[]'"),
            ("strong_areas", "JSONB DEFAULT '[]'"),
            ("total_sessions", "INTEGER DEFAULT 0"),
            ("total_messages", "INTEGER DEFAULT 0"),
        ]
        
        for col_name, col_type in columns_to_add:
            if not column_exists(cursor, 'learning_profile', col_name):
                cursor.execute(f"ALTER TABLE learning_profile ADD COLUMN {col_name} {col_type}")
                print(f"   ✓ Added {col_name} column")
            else:
                print(f"   ⚠ {col_name} already exists")
        
        # =====================================================================
        # 3. Check user_id type
        # =====================================================================
        print("\n📋 Checking learning_profile.user_id type...")
        
        cursor.execute("""
            SELECT data_type FROM information_schema.columns 
            WHERE table_name = 'learning_profile' AND column_name = 'user_id'
        """)
        row = cursor.fetchone()
        if row:
            current_type = row[0]
            print(f"   Current type: {current_type}")
            
            if current_type == 'uuid':
                print("   ⚠ user_id is UUID - needs manual migration to TEXT")
                print("   💡 For now, the code will handle UUID conversion")
        
        # =====================================================================
        # 4. Verify schema
        # =====================================================================
        print("\n" + "=" * 50)
        print("📊 Final schema verification:")
        print("-" * 50)
        
        for table in ['chat_messages', 'learning_profile']:
            cursor.execute("""
                SELECT column_name, data_type 
                FROM information_schema.columns 
                WHERE table_name = %s
                ORDER BY column_name
            """, (table,))
            
            print(f"\n📋 {table}:")
            for row in cursor.fetchall():
                print(f"   - {row[0]}: {row[1]}")
        
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 50)
        print("✅ Schema fix completed!")
        print("\n💡 Next steps:")
        print("   1. Redeploy the application on Render")
        print("   2. Test the chat API")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    run_fix()
