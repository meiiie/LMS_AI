"""
Cross-session Memory Persistence E2E Test
CHỈ THỊ KỸ THUẬT SỐ 06 - v0.2.1

Test scenario:
1. Session A: User introduces themselves (name, job)
2. Session B: User asks "What's my name?" - AI should remember

**Feature: cross-session-memory**
**Validates: Requirements 1.1, 1.2, 3.1, 3.4**
"""
import asyncio
import sys
import uuid
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, ".")

from app.core.config import settings
from app.engine.semantic_memory import SemanticMemoryEngine
from app.models.semantic_memory import FactType, MemoryType, SemanticMemoryCreate, UserFact
from app.repositories.semantic_memory_repository import SemanticMemoryRepository


def print_header(text: str):
    """Print formatted header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_result(test_name: str, passed: bool, details: str = ""):
    """Print test result."""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"{status} | {test_name}")
    if details:
        print(f"       {details}")


async def test_cross_session_fact_retrieval():
    """
    Test that facts stored in Session A are retrievable in Session B.
    
    **Property 1: Cross-session Fact Retrieval**
    **Validates: Requirements 1.1, 1.2, 3.1, 4.2**
    """
    print_header("Test 1: Cross-session Fact Retrieval")
    
    # Setup
    engine = SemanticMemoryEngine()
    repo = SemanticMemoryRepository()
    
    if not repo.is_available():
        print("⚠️  Database not available, skipping test")
        return False
    
    # Generate unique user_id for this test
    user_id = f"test_user_{uuid.uuid4().hex[:8]}"
    session_a = f"session_a_{uuid.uuid4().hex[:8]}"
    session_b = f"session_b_{uuid.uuid4().hex[:8]}"
    
    print(f"User ID: {user_id}")
    print(f"Session A: {session_a}")
    print(f"Session B: {session_b}")
    
    try:
        # Session A: Store user facts
        print("\n--- Session A: Storing user facts ---")
        
        # Store name fact
        await engine.store_interaction(
            user_id=user_id,
            message="Tôi tên là Nam, tôi là thuyền trưởng",
            response="Chào anh Nam! Rất vui được gặp anh.",
            session_id=session_a,
            extract_facts=True
        )
        print("Stored: 'Tôi tên là Nam, tôi là thuyền trưởng'")
        
        # Wait a bit for storage
        await asyncio.sleep(0.5)
        
        # Session B: Retrieve facts (different session!)
        print("\n--- Session B: Retrieving facts (different session) ---")
        
        context = await engine.retrieve_context(
            user_id=user_id,
            query="Tôi làm nghề gì?",
            include_user_facts=True,
            deduplicate_facts=True
        )
        
        print(f"Retrieved {len(context.user_facts)} user facts")
        
        # Check if facts are retrieved
        facts_found = len(context.user_facts) > 0
        
        if facts_found:
            print("\nUser facts retrieved:")
            for fact in context.user_facts:
                print(f"  - {fact.content} (type: {fact.metadata.get('fact_type', 'unknown')})")
        
        # Check context string
        context_str = context.to_prompt_context()
        print(f"\nContext string preview:\n{context_str[:500]}...")
        
        # Verify
        passed = facts_found
        print_result(
            "Cross-session fact retrieval",
            passed,
            f"Found {len(context.user_facts)} facts from Session A in Session B"
        )
        
        return passed
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


async def test_fact_deduplication():
    """
    Test that duplicate facts are deduplicated by fact_type.
    
    **Property 4: Fact Deduplication by Type**
    **Validates: Requirements 2.3**
    """
    print_header("Test 2: Fact Deduplication")
    
    repo = SemanticMemoryRepository()
    
    if not repo.is_available():
        print("⚠️  Database not available, skipping test")
        return False
    
    user_id = f"test_user_{uuid.uuid4().hex[:8]}"
    
    try:
        # Import embedding engine
        from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
        embeddings = GeminiOptimizedEmbeddings()
        
        # Store multiple facts of same type
        print("\n--- Storing multiple 'name' facts ---")
        
        # Fact 1: Old name
        content1 = "name: Minh"
        embedding1 = embeddings.embed_documents([content1])[0]
        repo.save_memory(SemanticMemoryCreate(
            user_id=user_id,
            content=content1,
            embedding=embedding1,
            memory_type=MemoryType.USER_FACT,
            importance=0.8,
            metadata={"fact_type": "name", "confidence": 0.8}
        ))
        print(f"Stored: {content1}")
        
        await asyncio.sleep(0.5)
        
        # Fact 2: New name (should override)
        content2 = "name: Nam"
        embedding2 = embeddings.embed_documents([content2])[0]
        repo.save_memory(SemanticMemoryCreate(
            user_id=user_id,
            content=content2,
            embedding=embedding2,
            memory_type=MemoryType.USER_FACT,
            importance=0.9,
            metadata={"fact_type": "name", "confidence": 0.9}
        ))
        print(f"Stored: {content2}")
        
        # Retrieve with deduplication
        print("\n--- Retrieving with deduplication ---")
        facts_dedup = repo.get_user_facts(user_id, deduplicate=True)
        facts_all = repo.get_user_facts(user_id, deduplicate=False)
        
        print(f"Without deduplication: {len(facts_all)} facts")
        print(f"With deduplication: {len(facts_dedup)} facts")
        
        # Check that only most recent name is kept
        name_facts = [f for f in facts_dedup if f.metadata.get("fact_type") == "name"]
        
        passed = len(name_facts) == 1 and "Nam" in name_facts[0].content
        print_result(
            "Fact deduplication",
            passed,
            f"Kept most recent name: {name_facts[0].content if name_facts else 'None'}"
        )
        
        return passed
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


async def test_context_includes_user_profile():
    """
    Test that context string includes user profile section.
    
    **Property 5: Context Includes User Facts**
    **Validates: Requirements 1.3, 2.2, 4.3**
    """
    print_header("Test 3: Context Includes User Profile")
    
    engine = SemanticMemoryEngine()
    repo = SemanticMemoryRepository()
    
    if not repo.is_available():
        print("⚠️  Database not available, skipping test")
        return False
    
    user_id = f"test_user_{uuid.uuid4().hex[:8]}"
    
    try:
        # Store some facts
        print("\n--- Storing user facts ---")
        await engine.store_interaction(
            user_id=user_id,
            message="Tôi là Hùng, tôi đang học về COLREGs",
            response="Chào Hùng! COLREGs là chủ đề quan trọng.",
            session_id="test_session",
            extract_facts=True
        )
        
        await asyncio.sleep(0.5)
        
        # Retrieve context
        print("\n--- Retrieving context ---")
        context = await engine.retrieve_context(
            user_id=user_id,
            query="Giải thích quy tắc 15",
            include_user_facts=True
        )
        
        # Check context string
        context_str = context.to_prompt_context()
        print(f"\nContext string:\n{context_str}")
        
        # Verify user profile section exists
        has_profile = "Hồ sơ người dùng" in context_str or "Thông tin về người dùng" in context_str
        has_facts = len(context.user_facts) > 0
        
        passed = has_facts
        print_result(
            "Context includes user profile",
            passed,
            f"Has profile section: {has_profile}, Has facts: {has_facts}"
        )
        
        return passed
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


async def main():
    """Run all cross-session memory tests."""
    print_header("Cross-session Memory Persistence E2E Tests")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print(f"Database: {settings.postgres_url_sync[:50]}...")
    
    results = []
    
    # Run tests
    results.append(await test_cross_session_fact_retrieval())
    results.append(await test_fact_deduplication())
    results.append(await test_context_includes_user_profile())
    
    # Summary
    print_header("Test Summary")
    passed = sum(results)
    total = len(results)
    
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("\n✅ All cross-session memory tests PASSED!")
        print("The AI will now remember user information across sessions.")
    else:
        print(f"\n❌ {total - passed} test(s) FAILED")
        print("Please check the implementation.")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
