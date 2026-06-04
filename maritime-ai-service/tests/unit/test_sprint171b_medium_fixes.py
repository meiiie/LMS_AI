"""
Sprint 171b: MEDIUM Severity Fixes Tests.

Tests verify 5 MEDIUM fixes:
1. Upload size/content-type validation (4 tests)
2. Upload timeout handling (2 tests)
3. INTERVAL parameterization — no SQL injection (4 tests)
4. Living Agent org isolation (6 tests)
5. WebSocket org_id tracking (6 tests)

22 tests across 5 groups.
"""

import asyncio
import inspect
import json
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ============================================================================
# Group 1: Upload Validation (4 tests)
# ============================================================================


class TestUploadValidation:
    """Verify upload size and content-type validation."""

    @pytest.mark.asyncio
    async def test_rejects_oversized_upload(self):
        """Upload larger than MAX_UPLOAD_SIZE returns error."""
        from app.services.object_storage import ObjectStorageClient

        client = ObjectStorageClient(endpoint="t.co:9000", access_key="k", secret_key="s", bucket="b")
        # Create data larger than 10MB
        huge_data = b"x" * (client.MAX_UPLOAD_SIZE + 1)

        with patch("app.services.object_storage._cb", None):
            result = await client.upload_image(huge_data, "doc1", 1)

        assert result.success is False
        assert "too large" in result.error.lower()

    @pytest.mark.asyncio
    async def test_accepts_valid_size(self):
        """Upload within MAX_UPLOAD_SIZE proceeds to upload logic."""
        from app.services.object_storage import ObjectStorageClient

        client = ObjectStorageClient(endpoint="t.co:9000", access_key="k", secret_key="s", bucket="b")
        mock_minio = MagicMock()
        mock_minio.put_object.return_value = None
        mock_minio.presigned_get_object.return_value = "http://t.co:9000/b/doc1/page_1.jpg?token=abc"
        client._client = mock_minio

        small_data = b"x" * 1024  # 1KB

        with patch("app.services.object_storage._cb", None):
            result = await client.upload_image(small_data, "doc1", 1)

        assert result.success is True
        mock_minio.put_object.assert_called_once()

    @pytest.mark.asyncio
    async def test_rejects_invalid_content_type(self):
        """Upload with unsupported content type returns error."""
        from app.services.object_storage import ObjectStorageClient

        client = ObjectStorageClient(endpoint="t.co:9000", access_key="k", secret_key="s", bucket="b")

        with patch("app.services.object_storage._cb", None):
            result = await client.upload_image(
                b"data", "doc1", 1, content_type="application/pdf"
            )

        assert result.success is False
        assert "unsupported content type" in result.error.lower()

    @pytest.mark.asyncio
    async def test_accepts_valid_content_types(self):
        """All allowed content types pass validation."""
        from app.services.object_storage import ObjectStorageClient

        client = ObjectStorageClient(endpoint="t.co:9000", access_key="k", secret_key="s", bucket="b")

        for ct in client.ALLOWED_CONTENT_TYPES:
            mock_minio = MagicMock()
            mock_minio.put_object.return_value = None
            mock_minio.presigned_get_object.return_value = "http://t.co:9000/b/doc1/page_1.jpg"
            client._client = mock_minio

            with patch("app.services.object_storage._cb", None):
                result = await client.upload_image(b"data", "doc1", 1, content_type=ct)
            # Should not fail on content type
            if not result.success:
                assert "content type" not in (result.error or "").lower()


# ============================================================================
# Group 2: Upload Timeout (2 tests)
# ============================================================================


class TestUploadTimeout:
    """Verify upload timeout handling."""

    def test_upload_timeout_constant_exists(self):
        """ObjectStorageClient has UPLOAD_TIMEOUT."""
        from app.services.object_storage import ObjectStorageClient

        assert hasattr(ObjectStorageClient, "UPLOAD_TIMEOUT")
        assert ObjectStorageClient.UPLOAD_TIMEOUT > 0

    def test_upload_uses_wait_for(self):
        """upload_image source code uses asyncio.wait_for for timeout."""
        from app.services.object_storage import ObjectStorageClient

        source = inspect.getsource(ObjectStorageClient.upload_image)
        assert "wait_for" in source
        assert "UPLOAD_TIMEOUT" in source or "timeout" in source


# ============================================================================
# Group 3: INTERVAL Parameterization (4 tests)
# ============================================================================


class TestIntervalParameterization:
    """Verify INTERVAL values use parameterized queries, not f-strings."""

    def test_emotional_repo_get_history_parameterized(self):
        """get_history uses parameterized INTERVAL, not f-string."""
        from app.repositories.emotional_state_repository import EmotionalStateRepository

        source = inspect.getsource(EmotionalStateRepository.get_history)
        # Should NOT have f-string INTERVAL
        assert "INTERVAL '{hours}" not in source
        # Should have parameterized form
        assert ":hours" in source

    def test_emotional_repo_cleanup_parameterized(self):
        """cleanup_old_snapshots uses parameterized INTERVAL."""
        from app.repositories.emotional_state_repository import EmotionalStateRepository

        source = inspect.getsource(EmotionalStateRepository.cleanup_old_snapshots)
        assert "INTERVAL '{keep_days}" not in source
        assert ":keep_days" in source

    def test_journal_get_recent_parameterized(self):
        """get_recent_entries uses parameterized INTERVAL."""
        from app.engine.living_agent.journal import JournalWriter

        source = inspect.getsource(JournalWriter.get_recent_entries)
        assert "INTERVAL '{days}" not in source
        assert ":days" in source

    def test_skill_builder_count_safe(self):
        """_count_recent_discoveries uses literal constant (not user input)."""
        from app.engine.living_agent.skill_builder import SkillBuilder

        source = inspect.getsource(SkillBuilder._count_recent_discoveries)
        # This uses a literal '7 days' — safe, no f-string interpolation
        assert "INTERVAL '7 days'" in source
        # Should NOT have f-string interpolation
        assert "INTERVAL '{" not in source


# ============================================================================
# Group 4: Living Agent Org Isolation (6 tests)
# ============================================================================


class TestLivingAgentOrgIsolation:
    """Verify Living Agent methods use org_id filtering."""

    def test_skill_find_by_name_uses_org_filter(self):
        """_find_by_name source includes explicit org scoping."""
        from app.engine.living_agent.skill_builder import SkillBuilder

        source = inspect.getsource(SkillBuilder._find_by_name)
        assert "_resolve_skill_scope" in source
        assert "AND organization_id = :org_id" in source

    def test_skill_query_skills_uses_org_filter(self):
        """_query_skills source includes explicit org scoping."""
        from app.engine.living_agent.skill_builder import SkillBuilder

        source = inspect.getsource(SkillBuilder._query_skills)
        assert "_resolve_skill_scope" in source
        assert "organization_id = :org_id" in source

    def test_skill_count_recent_uses_org_filter(self):
        """_count_recent_discoveries source includes explicit org scoping."""
        from app.engine.living_agent.skill_builder import SkillBuilder

        source = inspect.getsource(SkillBuilder._count_recent_discoveries)
        assert "_resolve_skill_scope" in source
        assert "organization_id = :org_id" in source

    def test_heartbeat_queue_pending_includes_org_id(self):
        """queue_pending_actions_impl resolves write scope and inserts org_id."""
        from app.engine.living_agent.heartbeat_runtime_support import queue_pending_actions_impl

        source = inspect.getsource(queue_pending_actions_impl)
        assert "organization_id" in source
        assert "resolve_memory_write_scope" in source

    def test_heartbeat_load_pending_filters_by_org(self):
        """load_pending_action_impl uses explicit org filtering."""
        from app.engine.living_agent.heartbeat_runtime_support import load_pending_action_impl

        source = inspect.getsource(load_pending_action_impl)
        assert "resolve_memory_read_scope" in source
        assert "AND organization_id = :org_id" in source

    def test_heartbeat_audit_includes_org_id(self):
        """save_heartbeat_audit_impl resolves write scope and inserts org_id."""
        from app.engine.living_agent.heartbeat_runtime_support import save_heartbeat_audit_impl

        source = inspect.getsource(save_heartbeat_audit_impl)
        assert "organization_id" in source
        assert "resolve_memory_write_scope" in source


# ============================================================================
# Group 5: WebSocket Org Tracking (6 tests)
# ============================================================================


class TestWebSocketOrgTracking:
    """Verify WebSocket ConnectionManager tracks org_id."""

    def test_connection_manager_has_session_orgs(self):
        """ConnectionManager tracks org_id per session."""
        from app.api.v1.websocket import ConnectionManager

        mgr = ConnectionManager()
        assert hasattr(mgr, "_session_orgs")
        assert isinstance(mgr._session_orgs, dict)

    def test_register_user_stores_org_id(self):
        """register_user with org_id stores it in _session_orgs."""
        from app.api.v1.websocket import ConnectionManager

        mgr = ConnectionManager()
        mgr.register_user("sess1", "user1", "org-maritime")

        assert mgr._session_orgs["sess1"] == "org-maritime"
        assert "sess1" in mgr._user_sessions["user1"]

    def test_disconnect_cleans_org(self):
        """disconnect removes org_id mapping."""
        from app.api.v1.websocket import ConnectionManager

        mgr = ConnectionManager()
        mgr._connections["sess1"] = MagicMock()
        mgr.register_user("sess1", "user1", "org-A")

        mgr.disconnect("sess1")

        assert "sess1" not in mgr._session_orgs
        assert "sess1" not in mgr._session_users

    @pytest.mark.asyncio
    async def test_send_to_user_filters_by_org(self):
        """send_to_user only sends to sessions in the specified org."""
        from app.api.v1.websocket import ConnectionManager

        mgr = ConnectionManager()

        # Two sessions for same user, different orgs
        ws1 = AsyncMock()
        ws2 = AsyncMock()
        mgr._connections["sess1"] = ws1
        mgr._connections["sess2"] = ws2
        mgr.register_user("sess1", "user1", "org-A")
        mgr.register_user("sess2", "user1", "org-B")

        # Send only to org-A
        sent = await mgr.send_to_user("user1", '{"msg":"hello"}', organization_id="org-A")

        assert sent == 1
        ws1.send_text.assert_called_once_with('{"msg":"hello"}')
        ws2.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_to_user_no_org_sends_all(self):
        """send_to_user without org_id sends to ALL sessions (backward compat)."""
        from app.api.v1.websocket import ConnectionManager

        mgr = ConnectionManager()

        ws1 = AsyncMock()
        ws2 = AsyncMock()
        mgr._connections["sess1"] = ws1
        mgr._connections["sess2"] = ws2
        mgr.register_user("sess1", "user1", "org-A")
        mgr.register_user("sess2", "user1", "org-B")

        sent = await mgr.send_to_user("user1", '{"msg":"hello"}')

        assert sent == 2
        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()

    def test_websocket_endpoint_accepts_org_id_param(self):
        """websocket_chat endpoint has org_id query parameter."""
        from app.api.v1.websocket import websocket_chat

        sig = inspect.signature(websocket_chat)
        assert "organization_id" in sig.parameters

    def test_to_chat_request_passes_org_id(self):
        """to_chat_request includes organization_id from metadata."""
        from app.channels.base import to_chat_request, ChannelMessage

        msg = ChannelMessage(
            text="hello",
            sender_id="user1",
            channel_id="ws:user1",
            channel_type="websocket",
            metadata={"organization_id": "org-maritime"},
        )
        req = to_chat_request(msg)
        assert req.organization_id == "org-maritime"

    def test_get_session_org(self):
        """get_session_org returns org_id for a session."""
        from app.api.v1.websocket import ConnectionManager

        mgr = ConnectionManager()
        mgr.register_user("sess1", "user1", "org-A")

        assert mgr.get_session_org("sess1") == "org-A"
        assert mgr.get_session_org("unknown") == ""
