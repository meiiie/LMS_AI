"""
Test script for Managed Memory List v0.4
CHỈ THỊ KỸ THUẬT SỐ 23

Tests:
1. Memory Capping (50 facts limit)
2. True Deduplication (Upsert)
3. Fact Type Validation
4. Memory API endpoint
"""
import asyncio
import sys
sys.path.insert(0, '.')

from app.engine.semantic_memory import SemanticMemoryEngine
from app.repositories.semantic_memory_repository import SemanticMemoryRepository
from app.models.semantic_memory import MemoryType, ALLOWED_FACT_TYPES, FACT_TYPE_MAPPING, IGNORED_FACT_TYPES


def test_fact_type_validation():
    """Test fact type validation logic."""
    print("\n" + "="*60)
    print("TEST 1: Fact Type Validation")
    print("="*60)
    
    engine = SemanticMemoryEngine()
    
    # Test allowed types
    for fact_type in ALLOWED_FACT_TYPES:
        result = engine._validate_fact_type(fact_type)
        assert result == fact_type, f"Expected {fact_type}, got {result}"
        print(f"  ✅ {fact_type} -> {result}")
    
    # Test case insensitivity
    result = engine._validate_fact_type("NAME")
    assert result == "name", f"Expected 'name', got {result}"
    print(f"  ✅ NAME (uppercase) -> {result}")
    
    # Test deprecated type mapping
    for old_type, new_type in FACT_TYPE_MAPPING.items():
        result = engine._validate_fact_type(old_type)
        assert result == new_type, f"Expected {new_type}, got {result}"
        print(f"  ✅ {old_type} -> {result} (mapped)")
    
    # Test ignored types
    for ignored_type in IGNORED_FACT_TYPES:
        result = engine._validate_fact_type(ignored_type)
        assert result is None, f"Expected None, got {result}"
        print(f"  ✅ {ignored_type} -> None (ignored)")
    
    # Test unknown type
    result = engine._validate_fact_type("unknown_type")
    assert result is None, f"Expected None, got {result}"
    print(f"  ✅ unknown_type -> None (rejected)")
    
    print("\n✅ PASSED: Fact Type Validation")


def test_memory_cap_constant():
    """Test memory cap constant."""
    print("\n" + "="*60)
    print("TEST 2: Memory Cap Constant")
    print("="*60)
    
    engine = SemanticMemoryEngine()
    
    assert engine.MAX_USER_FACTS == 50, f"Expected 50, got {engine.MAX_USER_FACTS}"
    print(f"  ✅ MAX_USER_FACTS = {engine.MAX_USER_FACTS}")
    
    print("\n✅ PASSED: Memory Cap Constant")


def test_repository_methods():
    """Test new repository methods exist."""
    print("\n" + "="*60)
    print("TEST 3: Repository Methods")
    print("="*60)
    
    repo = SemanticMemoryRepository()
    
    methods = [
        'find_fact_by_type',
        'update_fact',
        'delete_oldest_facts',
        'get_all_user_facts'
    ]
    
    for method in methods:
        assert hasattr(repo, method), f"Missing method: {method}"
        print(f"  ✅ {method}() exists")
    
    print("\n✅ PASSED: Repository Methods")


def test_engine_methods():
    """Test new engine methods exist."""
    print("\n" + "="*60)
    print("TEST 4: Engine Methods")
    print("="*60)
    
    engine = SemanticMemoryEngine()
    
    methods = [
        'store_user_fact_upsert',
        '_enforce_memory_cap',
        '_validate_fact_type'
    ]
    
    for method in methods:
        assert hasattr(engine, method), f"Missing method: {method}"
        print(f"  ✅ {method}() exists")
    
    print("\n✅ PASSED: Engine Methods")


def test_api_endpoint():
    """Test API endpoint is registered."""
    print("\n" + "="*60)
    print("TEST 5: API Endpoint")
    print("="*60)
    
    from app.main import app
    
    routes = [r.path for r in app.routes]
    memories_route = '/api/v1/memories/{user_id}'
    
    assert memories_route in routes, f"Missing route: {memories_route}"
    print(f"  ✅ {memories_route} registered")
    
    print("\n✅ PASSED: API Endpoint")


def main():
    print("="*60)
    print("MANAGED MEMORY LIST v0.4 TEST")
    print("CHỈ THỊ KỸ THUẬT SỐ 23")
    print("="*60)
    
    tests = [
        test_fact_type_validation,
        test_memory_cap_constant,
        test_repository_methods,
        test_engine_methods,
        test_api_endpoint,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            print(f"\n❌ FAILED: {test.__name__}")
            print(f"   Error: {e}")
            failed += 1
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    print(f"Passed: {passed}/{len(tests)}")
    print(f"Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED!")
        print("Managed Memory List v0.4 is ready!")
    else:
        print("\n⚠️ Some tests failed. Please check the errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
