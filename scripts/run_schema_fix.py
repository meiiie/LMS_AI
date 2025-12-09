#!/usr/bin/env python3
"""
Run database schema fix for Maritime AI Service.

This script connects to Neon PostgreSQL and runs the schema fix SQL.

Usage:
    python scripts/run_schema_fix.py
    
Or with custom database URL:
    DATABASE_URL="postgresql://..." python scripts/run_schema_fix.py
"""
import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import psycopg2
from dotenv import load_dotenv

# Load environment variables
load_dotenv(project_root / ".env")


def get_database_url():
    """Get database URL from environment and convert to psycopg2 format."""
    url = os.getenv("DATABASE_URL") or os.getenv("NEON_DATABASE_URL")
    if not url:
        print("❌ DATABASE_URL or NEON_DATABASE_URL not set")
        sys.exit(1)
    
    # Convert SQLAlchemy URL to psycopg2 format
    # postgresql+asyncpg:// -> postgresql://
    # Also handle sslmode parameter
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    
    # Remove query parameters that psycopg2 doesn't understand
    if "?" in url:
        base_url = url.split("?")[0]
        # Add sslmode=require for Neon
        url = f"{base_url}?sslmode=require"
    else:
        url = f"{url}?sslmode=require"
    
    return url


def run_schema_fix():
    """Run the schema fix SQL script."""
    database_url = get_database_url()
    
    # Read SQL script
    sql_file = project_root / "scripts" / "fix_database_schema.sql"
    if not sql_file.exists():
        print(f"❌ SQL file not found: {sql_file}")
        sys.exit(1)
    
    sql_content = sql_file.read_text()
    
    print("🔧 Maritime AI Service - Database Schema Fix")
    print("=" * 50)
    print(f"📁 SQL file: {sql_file}")
    print(f"🔗 Database: {database_url[:50]}...")
    print()
    
    try:
        # Connect to database
        print("📡 Connecting to database...")
        conn = psycopg2.connect(database_url)
        conn.autocommit = True
        cursor = conn.cursor()
        
        print("🚀 Running schema fix...")
        
        # Execute each statement separately
        # Split by semicolon but be careful with DO blocks
        statements = []
        current_stmt = []
        in_do_block = False
        
        for line in sql_content.split('\n'):
            stripped = line.strip()
            
            # Skip comments and empty lines for statement detection
            if stripped.startswith('--') or not stripped:
                current_stmt.append(line)
                continue
            
            # Track DO blocks
            if stripped.upper().startswith('DO $$') or stripped.upper().startswith('DO $'):
                in_do_block = True
            if in_do_block and stripped.endswith('$$;'):
                in_do_block = False
                current_stmt.append(line)
                statements.append('\n'.join(current_stmt))
                current_stmt = []
                continue
            
            current_stmt.append(line)
            
            # End of statement (not in DO block)
            if not in_do_block and stripped.endswith(';'):
                stmt = '\n'.join(current_stmt).strip()
                if stmt and not stmt.startswith('--'):
                    statements.append(stmt)
                current_stmt = []
        
        # Execute each statement
        for i, stmt in enumerate(statements):
            if not stmt.strip() or stmt.strip().startswith('--'):
                continue
            # Skip SELECT statements (verification queries)
            if stmt.strip().upper().startswith('SELECT'):
                continue
            try:
                cursor.execute(stmt)
                print(f"   ✓ Statement {i+1} executed")
            except Exception as e:
                # Some errors are expected (e.g., table already exists)
                if "already exists" in str(e).lower():
                    print(f"   ⚠ Statement {i+1}: Already exists (OK)")
                elif "does not exist" in str(e).lower() and "DROP" in stmt.upper():
                    print(f"   ⚠ Statement {i+1}: Nothing to drop (OK)")
                else:
                    print(f"   ⚠ Statement {i+1}: {e}")
        
        # Fetch results from the verification query
        print("\n📊 Schema verification:")
        print("-" * 50)
        
        # Run verification query separately
        cursor.execute("""
            SELECT 'chat_sessions' as table_name, column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'chat_sessions'
            UNION ALL
            SELECT 'chat_messages' as table_name, column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'chat_messages'
            UNION ALL
            SELECT 'learning_profile' as table_name, column_name, data_type 
            FROM information_schema.columns 
            WHERE table_name = 'learning_profile'
            ORDER BY table_name, column_name;
        """)
        
        rows = cursor.fetchall()
        current_table = None
        for row in rows:
            table, column, dtype = row
            if table != current_table:
                print(f"\n📋 {table}:")
                current_table = table
            print(f"   - {column}: {dtype}")
        
        cursor.close()
        conn.close()
        
        print("\n" + "=" * 50)
        print("✅ Schema fix completed successfully!")
        print("\n💡 Next steps:")
        print("   1. Redeploy the application on Render")
        print("   2. Test the chat API")
        
    except psycopg2.Error as e:
        print(f"\n❌ Database error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_schema_fix()
