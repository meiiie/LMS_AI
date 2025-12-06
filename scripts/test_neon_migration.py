#!/usr/bin/env python3
"""
Test script for Neon Migration (CHỈ THỊ KỸ THUẬT SỐ 19)

Tests:
1. Database connection to Neon
2. Vector extension enabled
3. Tables created via Alembic
4. Health check endpoints
"""
import asyncio
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text


def test_neon_connection():
    """Test 1: Neon database connection"""
    print("\n" + "="*60)
    print("TEST 1: Neon Database Connection")
    print("="*60)
    
    try:
        from app.core.database import get_shared_engine, test_connection
        
        # Test connection
        result = test_connection()
        if result:
            print("✅ Neon connection: OK")
            
            # Show connection info
            from app.core.config import settings
            url = settings.database_url
            # Mask password
            if url:
                masked = url.replace(url.split(':')[2].split('@')[0], '***')
                print(f"   URL: {masked[:80]}...")
            return True
        else:
            print("❌ Neon connection: FAILED")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_vector_extension():
    """Test 2: Vector extension enabled"""
    print("\n" + "="*60)
    print("TEST 2: Vector Extension")
    print("="*60)
    
    try:
        from app.core.database import get_shared_session_factory
        
        session_factory = get_shared_session_factory()
        with session_factory() as session:
            result = session.execute(text(
                "SELECT extname FROM pg_extension WHERE extname = 'vector'"
            ))
            row = result.fetchone()
            
            if row:
                print("✅ Vector extension: ENABLED")
                return True
            else:
                print("❌ Vector extension: NOT FOUND")
                return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_tables_created():
    """Test 3: Tables created via Alembic"""
    print("\n" + "="*60)
    print("TEST 3: Database Tables")
    print("="*60)
    
    try:
        from app.core.database import get_shared_session_factory
        
        session_factory = get_shared_session_factory()
        with session_factory() as session:
            result = session.execute(text("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """))
            tables = [row[0] for row in result.fetchall()]
            
            print(f"   Found {len(tables)} tables:")
            for table in tables:
                print(f"   - {table}")
            
            # Check required tables
            required = ['chat_sessions', 'chat_messages', 'semantic_memories', 'alembic_version']
            missing = [t for t in required if t not in tables]
            
            if not missing:
                print("✅ All required tables exist")
                return True
            else:
                print(f"❌ Missing tables: {missing}")
                return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_neo4j_connection():
    """Test 4: Neo4j Knowledge Graph connection"""
    print("\n" + "="*60)
    print("TEST 4: Neo4j Knowledge Graph")
    print("="*60)
    
    try:
        from app.engine.tools.rag_tool import get_knowledge_repository
        
        repo = get_knowledge_repository()
        if repo.ping():
            print("✅ Neo4j connection: OK")
            print("   Knowledge Graph ready")
            return True
        else:
            print("❌ Neo4j connection: FAILED")
            return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*60)
    print("CHỈ THỊ KỸ THUẬT SỐ 19: NEON MIGRATION TEST")
    print("="*60)
    
    results = []
    
    # Run tests
    results.append(("Neon Connection", test_neon_connection()))
    results.append(("Vector Extension", test_vector_extension()))
    results.append(("Database Tables", test_tables_created()))
    results.append(("Neo4j Connection", test_neo4j_connection()))
    
    # Summary
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"   {name}: {status}")
    
    print(f"\n   Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 NEON MIGRATION SUCCESSFUL!")
        return 0
    else:
        print("\n⚠️ Some tests failed. Please check the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
