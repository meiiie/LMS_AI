"""Check insights in database."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

def check():
    from app.core.database import get_shared_session_factory
    from sqlalchemy import text
    
    session_factory = get_shared_session_factory()
    with session_factory() as session:
        # Check for v0.5 insights specifically
        print("="*60)
        print("CHECKING FOR v0.5 INSIGHTS (insight_category)")
        print("="*60)
        
        result = session.execute(text("""
            SELECT COUNT(*) FROM semantic_memories 
            WHERE insight_category IS NOT NULL;
        """))
        insight_count = result.scalar()
        print(f"\nInsights with insight_category column: {insight_count}")
        
        # Check memory types distribution
        print("\n" + "="*60)
        print("MEMORY TYPE DISTRIBUTION")
        print("="*60)
        
        result = session.execute(text("""
            SELECT memory_type, COUNT(*) as cnt 
            FROM semantic_memories 
            GROUP BY memory_type 
            ORDER BY cnt DESC;
        """))
        
        for row in result.fetchall():
            print(f"  {row[0]}: {row[1]}")
        
        # Check recent user_facts (v0.4 style)
        print("\n" + "="*60)
        print("RECENT USER_FACTS (v0.4 style)")
        print("="*60)
        
        result = session.execute(text("""
            SELECT user_id, content, metadata 
            FROM semantic_memories 
            WHERE memory_type = 'user_fact'
            ORDER BY created_at DESC 
            LIMIT 10;
        """))
        
        for row in result.fetchall():
            meta = row[2] or {}
            fact_type = meta.get("fact_type", "unknown")
            print(f"\n  User: {row[0]}")
            print(f"  Type: {fact_type}")
            print(f"  Content: {row[1][:80]}...")
        
        # Check if any memory has insight_category in metadata
        print("\n" + "="*60)
        print("CHECKING METADATA FOR insight_category")
        print("="*60)
        
        result = session.execute(text("""
            SELECT user_id, content, metadata 
            FROM semantic_memories 
            WHERE metadata::text LIKE '%insight_category%'
            LIMIT 5;
        """))
        
        rows = result.fetchall()
        if rows:
            print(f"\nFound {len(rows)} with insight_category in metadata:")
            for row in rows:
                print(f"  {row[0]}: {row[1][:60]}...")
        else:
            print("\n⚠️ No memories with insight_category in metadata")
            print("   This means v0.5 Insight Engine is NOT storing insights yet")
            print("   Possible causes:")
            print("   1. Code not deployed to production")
            print("   2. extract_and_store_insights() not being called")
            print("   3. InsightExtractor returning empty results")

if __name__ == "__main__":
    check()
