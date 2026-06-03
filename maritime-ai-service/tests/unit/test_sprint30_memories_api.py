"""
Tests for Sprint 30: Memories API endpoint coverage.

Covers:
- GET /{user_id}: list user memories, ownership check, admin access
- DELETE /{user_id}/{memory_id}: delete single memory, 404, ownership
- DELETE /{user_id}: clear all memories, ownership
- Error handling: 500 responses don't leak internal details
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone
from uuid import uuid4


# =============================================================================
# Helpers
# =============================================================================

def _make_request():
    """Create a real starlette Request for rate-limited endpoints."""
    from starlette.requests import Request
    scope = {
        "type": "http", "method": "GET", "path": "/api/v1/memories/user-1",
        "headers": [], "query_string": b"", "root_path": "",
        "client": ("127.0.0.1", 12345),
    }
    return Request(scope)


def _make_auth(user_id="user-1", role="student"):
    """Create a mock auth object."""
    auth = MagicMock()
    auth.user_id = user_id
    auth.role = role
    return auth


def _make_fact(fact_id=None, content="fact_type: some_value", fact_type="user_preference"):
    """Create a mock fact/memory object."""
    fact = MagicMock()
    fact.id = fact_id or uuid4()
    fact.content = content
    fact.metadata = {"fact_type": fact_type}
    fact.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
    return fact


# =============================================================================
# GET /{user_id} — List memories
# =============================================================================


class TestGetUserMemories:
    """Test get_user_memories endpoint."""

    @pytest.mark.asyncio
    async def test_returns_empty_list(self):
        from app.api.v1.memories import get_user_memories

        mock_repo = MagicMock()
        mock_repo.get_all_user_facts.return_value = []

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_memories(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert result.total == 0
        assert result.data == []
        assert result.summary.total == 0
        assert result.summary.type_counts == {}
        assert result.summary.provenance.source_kinds == {}
        assert result.summary.privacy.raw_content_included is False

    @pytest.mark.asyncio
    async def test_returns_facts(self):
        from app.api.v1.memories import get_user_memories

        facts = [
            _make_fact(content="learning_style: visual", fact_type="learning_style"),
            _make_fact(content="name: John", fact_type="user_info"),
        ]
        mock_repo = MagicMock()
        mock_repo.get_all_user_facts.return_value = facts

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_memories(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert result.total == 2
        assert result.data[0].type == "learning_style"
        assert result.data[0].value == "visual"
        assert result.data[1].value == "John"
        assert result.summary.total == 2
        assert result.summary.type_counts == {
            "learning_style": 1,
            "user_info": 1,
        }
        assert result.summary.latest_created_at == facts[0].created_at
        assert result.summary.provenance.source_kinds == {"semantic_fact": 2}
        assert result.summary.provenance.raw_content_included is False
        assert result.summary.privacy.identifier_strategy == "hash_or_count_only"
        assert result.summary.controls.can_delete_one is True
        assert result.summary.controls.can_clear_all is True

    @pytest.mark.asyncio
    async def test_extracts_value_from_content(self):
        """Content format is 'type: value' — extracts after ': '."""
        from app.api.v1.memories import get_user_memories

        facts = [_make_fact(content="preference: dark mode")]
        mock_repo = MagicMock()
        mock_repo.get_all_user_facts.return_value = facts

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_memories(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert result.data[0].value == "dark mode"

    @pytest.mark.asyncio
    async def test_content_without_separator(self):
        """Content without ': ' returns full content as value."""
        from app.api.v1.memories import get_user_memories

        facts = [_make_fact(content="just plain text")]
        mock_repo = MagicMock()
        mock_repo.get_all_user_facts.return_value = facts

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_memories(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert result.data[0].value == "just plain text"

    @pytest.mark.asyncio
    async def test_ownership_check_forbids_other_users(self):
        from app.api.v1.memories import get_user_memories
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await get_user_memories(request=_make_request(), user_id="user-2", auth=_make_auth("user-1", "student"))

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_access_other_users(self):
        from app.api.v1.memories import get_user_memories

        mock_repo = MagicMock()
        mock_repo.get_all_user_facts.return_value = []

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await get_user_memories(request=_make_request(), user_id="user-2", auth=_make_auth("admin-1", "admin"))

        assert result.total == 0

    @pytest.mark.asyncio
    async def test_repository_error_returns_500(self):
        from app.api.v1.memories import get_user_memories
        from fastapi import HTTPException

        mock_repo = MagicMock()
        mock_repo.get_all_user_facts.side_effect = RuntimeError("DB down")

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            with pytest.raises(HTTPException) as exc_info:
                await get_user_memories(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert exc_info.value.status_code == 500
        assert "Internal server error" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_blocks_missing_org_context_before_read(
        self,
        monkeypatch,
    ):
        from app.api.v1.memories import get_user_memories
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from fastapi import HTTPException

        mock_repo = MagicMock()
        repo_factory = MagicMock(return_value=mock_repo)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        token = current_org_id.set(None)
        try:
            with patch(
                "app.api.v1.memories.SemanticMemoryRepository",
                repo_factory,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await get_user_memories(
                        request=_make_request(),
                        user_id="user-private-123",
                        auth=_make_auth("user-private-123"),
                    )
        finally:
            current_org_id.reset(token)

        assert exc_info.value.status_code == 403
        assert "Organization context required for memory access" in exc_info.value.detail
        repo_factory.assert_not_called()
        mock_repo.get_all_user_facts.assert_not_called()


# =============================================================================
# DELETE /{user_id}/{memory_id} — Delete single memory
# =============================================================================


class TestDeleteUserMemory:
    """Test delete_user_memory endpoint."""

    @pytest.mark.asyncio
    async def test_successful_delete(self):
        from app.api.v1.memories import delete_user_memory

        mock_repo = MagicMock()
        mock_repo.delete_memory.return_value = True

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await delete_user_memory(request=_make_request(), user_id="user-1", memory_id="mem-123", auth=_make_auth("user-1"))

        assert result.success is True
        mock_repo.delete_memory.assert_called_once_with("user-1", "mem-123")

    @pytest.mark.asyncio
    async def test_not_found_returns_404(self):
        from app.api.v1.memories import delete_user_memory
        from fastapi import HTTPException

        mock_repo = MagicMock()
        mock_repo.delete_memory.return_value = False

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            with pytest.raises(HTTPException) as exc_info:
                await delete_user_memory(request=_make_request(), user_id="user-1", memory_id="nonexistent", auth=_make_auth("user-1"))

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_ownership_check(self):
        from app.api.v1.memories import delete_user_memory
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await delete_user_memory(request=_make_request(), user_id="user-2", memory_id="mem-1", auth=_make_auth("user-1", "student"))

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_delete_others(self):
        from app.api.v1.memories import delete_user_memory

        mock_repo = MagicMock()
        mock_repo.delete_memory.return_value = True

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await delete_user_memory(request=_make_request(), user_id="user-2", memory_id="mem-1", auth=_make_auth("admin-1", "admin"))

        assert result.success is True

    @pytest.mark.asyncio
    async def test_error_returns_500(self):
        from app.api.v1.memories import delete_user_memory
        from fastapi import HTTPException

        mock_repo = MagicMock()
        mock_repo.delete_memory.side_effect = RuntimeError("DB fail")

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            with pytest.raises(HTTPException) as exc_info:
                await delete_user_memory(request=_make_request(), user_id="user-1", memory_id="m1", auth=_make_auth("user-1"))

        assert exc_info.value.status_code == 500
        assert "DB fail" not in exc_info.value.detail  # No leak

    @pytest.mark.asyncio
    async def test_blocks_missing_org_context_before_delete(
        self,
        monkeypatch,
    ):
        from app.api.v1.memories import delete_user_memory
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from fastapi import HTTPException

        mock_repo = MagicMock()
        repo_factory = MagicMock(return_value=mock_repo)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        token = current_org_id.set(None)
        try:
            with patch(
                "app.api.v1.memories.SemanticMemoryRepository",
                repo_factory,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await delete_user_memory(
                        request=_make_request(),
                        user_id="user-private-123",
                        memory_id="memory-private-123",
                        auth=_make_auth("user-private-123"),
                    )
        finally:
            current_org_id.reset(token)

        assert exc_info.value.status_code == 403
        assert "Organization context required for memory mutation" in exc_info.value.detail
        repo_factory.assert_not_called()
        mock_repo.delete_memory.assert_not_called()


# =============================================================================
# DELETE /{user_id} — Clear all memories
# =============================================================================


class TestClearUserMemories:
    """Test clear_user_memories endpoint."""

    @pytest.mark.asyncio
    async def test_successful_clear(self):
        from app.api.v1.memories import clear_user_memories

        mock_repo = MagicMock()
        mock_repo.delete_all_user_memories.return_value = 5

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await clear_user_memories(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert result.success is True
        assert result.deleted_count == 5

    @pytest.mark.asyncio
    async def test_clear_empty(self):
        from app.api.v1.memories import clear_user_memories

        mock_repo = MagicMock()
        mock_repo.delete_all_user_memories.return_value = 0

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await clear_user_memories(request=_make_request(), user_id="user-1", auth=_make_auth("user-1"))

        assert result.success is True
        assert result.deleted_count == 0

    @pytest.mark.asyncio
    async def test_ownership_check(self):
        from app.api.v1.memories import clear_user_memories
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await clear_user_memories(request=_make_request(), user_id="user-2", auth=_make_auth("user-1", "student"))

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_can_clear_others(self):
        from app.api.v1.memories import clear_user_memories

        mock_repo = MagicMock()
        mock_repo.delete_all_user_memories.return_value = 3

        with patch("app.api.v1.memories.SemanticMemoryRepository", return_value=mock_repo):
            result = await clear_user_memories(request=_make_request(), user_id="user-2", auth=_make_auth("admin", "admin"))

        assert result.success is True
        assert result.deleted_count == 3

    @pytest.mark.asyncio
    async def test_blocks_missing_org_context_before_clear(
        self,
        monkeypatch,
    ):
        from app.api.v1.memories import clear_user_memories
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from fastapi import HTTPException

        mock_repo = MagicMock()
        repo_factory = MagicMock(return_value=mock_repo)
        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        token = current_org_id.set(None)
        try:
            with patch(
                "app.api.v1.memories.SemanticMemoryRepository",
                repo_factory,
            ):
                with pytest.raises(HTTPException) as exc_info:
                    await clear_user_memories(
                        request=_make_request(),
                        user_id="user-private-123",
                        auth=_make_auth("user-private-123"),
                    )
        finally:
            current_org_id.reset(token)

        assert exc_info.value.status_code == 403
        assert "Organization context required for memory mutation" in exc_info.value.detail
        repo_factory.assert_not_called()
        mock_repo.delete_all_user_memories.assert_not_called()
