"""
Database Audit Script
Queries the Neon database to get current schema and data statistics.
"""
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
from app.core.config import settings


async def audit_database():
    """Audit database tables and data."""
    print("=" * 60)
    print("DATABASE AUDIT - Maritime AI Tutor")
    print("=" * 60)
    print(f"\nConnecting to: {settings.postgres_url[:50]}...")
    
    engine = create_async_engine(settings.postgres_url)
    
    async with engine.connect() as conn:
        # 1. List all tables
        print("\n📋 TABLES IN DATABASE:")
        print("-" * 40)
        result = await conn.execute(text("""
            SELECT table_name 
            FROM information_schema.tables 
            WHERE table_schema = 'public' 
            ORDER BY table_name
        """))
        tables = [row[0] for row in result.fetchall()]
        for t in tables:
            print(f"  ✓ {t}")
        
        # 2. Get row counts
        print("\n📊 ROW COUNTS:")
        print("-" * 40)
        for table in tables:
            try:
                result = await conn.execute(text(f"SELECT COUNT(*) FROM {table}"))
                count = result.scalar()
                print(f"  {table}: {count} rows")
            except Exception as e:
                print(f"  {table}: ERROR - {e}")
        
        # 3. semantic_memories details
        print("\n🔍 SEMANTIC_MEMORIES BREAKDOWN:")
        print("-" * 40)
        result = await conn.execute(text("""
            SELECT memory_type, COUNT(*) as count 
            FROM semantic_memories 
            GROUP BY memory_type 
            ORDER BY count DESC
        """))
        for row in result.fetchall():
            print(f"  {row[0]}: {row[1]} items")
        
        # 4. Check columns of semantic_memories
        print("\n📝 SEMANTIC_MEMORIES SCHEMA:")
        print("-" * 40)
        result = await conn.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'semantic_memories'
            ORDER BY ordinal_position
        """))
        for row in result.fetchall():
            nullable = "NULL" if row[2] == 'YES' else "NOT NULL"
            print(f"  {row[0]}: {row[1]} ({nullable})")
        
        # 5. Sample metadata from user_facts
        print("\n📦 SAMPLE FACT METADATA:")
        print("-" * 40)
        result = await conn.execute(text("""
            SELECT metadata 
            FROM semantic_memories 
            WHERE memory_type = 'user_fact' 
            LIMIT 3
        """))
        for i, row in enumerate(result.fetchall(), 1):
            print(f"  Sample {i}: {row[0]}")
    
    await engine.dispose()
    print("\n" + "=" * 60)
    print("AUDIT COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(audit_database())
