"""
Tests for Sprint 50: UserGraphRepository coverage.

Tests Neo4j graph repository including:
- __init__ (driver init, unavailable)
- is_available
- ensure_user_node (success, unavailable, error)
- get_user_node (success, not found, unavailable, error)
- ensure_module_node (success, unavailable, error)
- ensure_topic_node (success, unavailable, error)
- mark_studied / mark_completed / mark_weak_at (success, unavailable, error)
- add_prerequisite (success, unavailable, error)
- get_learning_path / get_knowledge_gaps / get_prerequisites (success, unavailable, error, empty)
- close
- Singleton
"""

from unittest.mock import MagicMock, patch

from app.repositories.user_graph_repository import UserGraphRepository


# ============================================================================
# Helpers
# ============================================================================


def _make_repo(available=True):
    """Create UserGraphRepository with mocked Neo4j driver.

    Patches neo4j.GraphDatabase at the source module level so
    _init_driver() gets our mock instead of a real Neo4j connection.
    """
    mock_driver = MagicMock()

    if not available:
        mock_driver.verify_connectivity.side_effect = Exception("Connection refused")

    mock_gdb = MagicMock()
    mock_gdb.driver.return_value = mock_driver

    with patch("neo4j.GraphDatabase", mock_gdb):
        repo = UserGraphRepository()

    if available:
        # Constructor should have set _available=True via mock
        repo._driver = mock_driver
        repo._available = True
    return repo


def _setup_session(repo, result_records=None):
    """Setup mock session that returns records."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    if result_records is not None:
        mock_result.single.return_value = result_records[0] if result_records else None
        mock_result.__iter__ = lambda self: iter(result_records or [])
    else:
        mock_result.single.return_value = None
        mock_result.__iter__ = lambda self: iter([])
    mock_session.run.return_value = mock_result
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)
    repo._driver.session.return_value = mock_session
    return mock_session


# ============================================================================
# __init__
# ============================================================================


class TestInit:
    """Test initialization."""

    def test_available(self):
        repo = _make_repo(available=True)
        assert repo.is_available() is True

    def test_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.is_available() is False


# ============================================================================
# ensure_user_node
# ============================================================================


class TestEnsureUserNode:
    """Test user node creation."""

    def test_success(self):
        repo = _make_repo()
        session = _setup_session(repo)
        assert repo.ensure_user_node("user1", "Minh") is True
        session.run.assert_called_once()

    def test_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.ensure_user_node("user1") is False

    def test_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.ensure_user_node("user1") is False


# ============================================================================
# get_user_node
# ============================================================================


class TestGetUserNode:
    """Test user node retrieval."""

    def test_found(self):
        repo = _make_repo()
        record = {"id": "user1", "display_name": "Minh", "last_seen": "2026-01-01"}
        _setup_session(repo, [record])
        result = repo.get_user_node("user1")
        assert result["id"] == "user1"

    def test_not_found(self):
        repo = _make_repo()
        _setup_session(repo, [])
        result = repo.get_user_node("nonexistent")
        assert result is None

    def test_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.get_user_node("user1") is None

    def test_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.get_user_node("user1") is None


# ============================================================================
# ensure_module_node
# ============================================================================


class TestEnsureModuleNode:
    """Test module node creation."""

    def test_success(self):
        repo = _make_repo()
        _setup_session(repo)
        assert repo.ensure_module_node("mod1", "COLREGs Basics") is True

    def test_with_document_id(self):
        repo = _make_repo()
        _setup_session(repo)
        assert repo.ensure_module_node("mod1", "Title", document_id="doc1") is True

    def test_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.ensure_module_node("mod1", "Title") is False

    def test_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.ensure_module_node("mod1", "Title") is False


# ============================================================================
# ensure_topic_node
# ============================================================================


class TestEnsureTopicNode:
    """Test topic node creation."""

    def test_success(self):
        repo = _make_repo()
        _setup_session(repo)
        assert repo.ensure_topic_node("rule_15", "Rule 15") is True

    def test_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.ensure_topic_node("t1", "Topic") is False

    def test_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.ensure_topic_node("t1", "Topic") is False


# ============================================================================
# mark_studied / mark_completed / mark_weak_at
# ============================================================================


class TestRelationships:
    """Test relationship operations."""

    def test_mark_studied_success(self):
        repo = _make_repo()
        _setup_session(repo)
        assert repo.mark_studied("u1", "mod1", progress=0.5) is True

    def test_mark_studied_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.mark_studied("u1", "mod1") is False

    def test_mark_studied_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.mark_studied("u1", "mod1") is False

    def test_mark_completed_success(self):
        repo = _make_repo()
        _setup_session(repo)
        assert repo.mark_completed("u1", "mod1") is True

    def test_mark_completed_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.mark_completed("u1", "mod1") is False

    def test_mark_completed_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.mark_completed("u1", "mod1") is False

    def test_mark_weak_at_success(self):
        repo = _make_repo()
        _setup_session(repo)
        assert repo.mark_weak_at("u1", "t1", confidence=0.7) is True

    def test_mark_weak_at_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.mark_weak_at("u1", "t1") is False

    def test_mark_weak_at_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.mark_weak_at("u1", "t1") is False


# ============================================================================
# add_prerequisite
# ============================================================================


class TestAddPrerequisite:
    """Test prerequisite creation."""

    def test_success(self):
        repo = _make_repo()
        _setup_session(repo)
        assert repo.add_prerequisite("mod2", "mod1") is True

    def test_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.add_prerequisite("mod2", "mod1") is False

    def test_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.add_prerequisite("mod2", "mod1") is False


# ============================================================================
# Query operations
# ============================================================================


class TestQueryOperations:
    """Test query methods."""

    def test_get_learning_path_success(self):
        repo = _make_repo()
        records = [
            {"module_id": "mod1", "title": "Basics", "progress": 0.5, "status": "STUDIED"},
            {"module_id": "mod2", "title": "Advanced", "progress": 1.0, "status": "COMPLETED"},
        ]
        _setup_session(repo, records)
        result = repo.get_learning_path("u1")
        assert len(result) == 2

    def test_get_learning_path_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.get_learning_path("u1") == []

    def test_get_learning_path_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.get_learning_path("u1") == []

    def test_get_knowledge_gaps_success(self):
        repo = _make_repo()
        records = [
            {"topic_id": "t1", "topic_name": "Rule 15", "confidence": 0.3},
        ]
        _setup_session(repo, records)
        result = repo.get_knowledge_gaps("u1")
        assert len(result) == 1

    def test_get_knowledge_gaps_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.get_knowledge_gaps("u1") == []

    def test_get_knowledge_gaps_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.get_knowledge_gaps("u1") == []

    def test_get_prerequisites_success(self):
        repo = _make_repo()
        records = [{"module_id": "mod1", "title": "Basics"}]
        _setup_session(repo, records)
        result = repo.get_prerequisites("mod2")
        assert len(result) == 1

    def test_get_prerequisites_unavailable(self):
        repo = _make_repo(available=False)
        assert repo.get_prerequisites("mod2") == []

    def test_get_prerequisites_error(self):
        repo = _make_repo()
        session = _setup_session(repo)
        session.run.side_effect = Exception("DB error")
        assert repo.get_prerequisites("mod2") == []


# ============================================================================
# Organization scope
# ============================================================================


class TestOrgScope:
    """Test organization-aware Neo4j graph boundaries."""

    def test_single_tenant_keeps_legacy_user_merge(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "enable_multi_tenant", False)
        repo = _make_repo()
        session = _setup_session(repo)

        assert repo.ensure_user_node("u1", "Minh") is True

        query = session.run.call_args.args[0]
        params = session.run.call_args.kwargs
        assert "MERGE (u:User {id: $user_id})" in query
        assert "organization_id" not in params

    def test_user_node_uses_current_org_context(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-A")
        try:
            repo = _make_repo()
            session = _setup_session(repo)

            assert repo.ensure_user_node("u1", "Minh") is True
        finally:
            current_org_id.reset(token)

        query = session.run.call_args.args[0]
        params = session.run.call_args.kwargs
        assert "MERGE (u:User {id: $user_id, organization_id: $organization_id})" in query
        assert params["organization_id"] == "org-A"

    def test_relationships_scope_user_and_target_nodes(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-B")
        try:
            repo = _make_repo()
            session = _setup_session(repo)

            assert repo.mark_studied("u1", "mod1", progress=0.5) is True
        finally:
            current_org_id.reset(token)

        query = session.run.call_args.args[0]
        params = session.run.call_args.kwargs
        assert "User {id: $user_id, organization_id: $organization_id}" in query
        assert "Module {id: $module_id, organization_id: $organization_id}" in query
        assert params["organization_id"] == "org-B"

    def test_query_scopes_knowledge_gaps_by_org(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set("org-C")
        try:
            repo = _make_repo()
            session = _setup_session(repo, [])

            assert repo.get_knowledge_gaps("u1") == []
        finally:
            current_org_id.reset(token)

        query = session.run.call_args.args[0]
        params = session.run.call_args.kwargs
        assert "User {id: $user_id, organization_id: $organization_id}" in query
        assert "Topic {organization_id: $organization_id}" in query
        assert params["organization_id"] == "org-C"

    def test_write_blocks_missing_org_context_before_neo4j(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            repo = _make_repo()

            assert repo.ensure_user_node("raw-user", "Private") is False
        finally:
            current_org_id.reset(token)

        repo._driver.session.assert_not_called()

    def test_read_blocks_missing_org_context_before_neo4j(self, monkeypatch):
        from app.core.config import settings
        from app.core.org_context import current_org_id

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")

        token = current_org_id.set(None)
        try:
            repo = _make_repo()

            assert repo.get_learning_path("raw-user") == []
        finally:
            current_org_id.reset(token)

        repo._driver.session.assert_not_called()


# ============================================================================
# close
# ============================================================================


class TestClose:
    """Test driver close."""

    def test_close_with_driver(self):
        repo = _make_repo()
        repo.close()
        repo._driver.close.assert_called_once()

    def test_close_without_driver(self):
        repo = _make_repo(available=False)
        repo._driver = None
        repo.close()  # Should not raise


# ============================================================================
# Singleton
# ============================================================================


class TestSingleton:
    """Test singleton pattern."""

    def test_get_user_graph_repository(self):
        import app.repositories.user_graph_repository as mod
        mod._user_graph_repo = None

        mock_gdb = MagicMock()
        mock_gdb.driver.return_value = MagicMock()

        with patch("neo4j.GraphDatabase", mock_gdb):
            r1 = mod.get_user_graph_repository()
            r2 = mod.get_user_graph_repository()
            assert r1 is r2

        mod._user_graph_repo = None  # Cleanup
