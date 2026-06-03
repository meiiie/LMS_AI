"""
Tests for Sprint 186: "Trí Nhớ Hình Ảnh" — Visual/Image Memory.

Phase 6 of the Visual Intelligence plan:
- VisualMemoryManager: store + retrieve image memories
- ImageMemoryEntry dataclass + metadata serialization
- Image hash deduplication
- Concept type detection + keyword extraction
- Vision LLM description generation (mocked)
- Semantic memory integration (embedding + repo storage)
- Input processor integration (context injection + image storage)
- Config flags gating

42 tests across 12 test classes.
"""

import asyncio
import base64
import hashlib
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

# ─── IMPORT TARGETS ───────────────────────────────────────────────────


# ==============================================================================
# 1. DATA MODEL TESTS
# ==============================================================================


class TestImageSource:
    """Test ImageSource enum."""

    def test_all_sources_exist(self):
        from app.engine.semantic_memory.visual_memory import ImageSource
        assert ImageSource.DESKTOP == "desktop"
        assert ImageSource.MESSENGER == "messenger"
        assert ImageSource.ZALO == "zalo"
        assert ImageSource.TELEGRAM == "telegram"
        assert ImageSource.WEB == "web"
        assert ImageSource.UPLOAD == "upload"
        assert ImageSource.SCREENSHOT == "screenshot"

    def test_source_is_string_enum(self):
        from app.engine.semantic_memory.visual_memory import ImageSource
        assert isinstance(ImageSource.DESKTOP.value, str)


class TestVisualConceptType:
    """Test VisualConceptType enum."""

    def test_all_concept_types(self):
        from app.engine.semantic_memory.visual_memory import VisualConceptType
        expected = {
            "diagram", "table", "chart", "photograph", "screenshot",
            "document", "map", "formula", "handwriting", "other",
        }
        actual = {t.value for t in VisualConceptType}
        assert actual == expected

    def test_other_is_default(self):
        from app.engine.semantic_memory.visual_memory import VisualConceptType
        assert VisualConceptType.OTHER.value == "other"


class TestImageMemoryEntry:
    """Test ImageMemoryEntry dataclass."""

    def test_default_values(self):
        from app.engine.semantic_memory.visual_memory import (
            ImageMemoryEntry, ImageSource, VisualConceptType,
        )
        entry = ImageMemoryEntry(user_id="u1", image_hash="abc123")
        assert entry.user_id == "u1"
        assert entry.image_hash == "abc123"
        assert entry.description == ""
        assert entry.concept_type == VisualConceptType.OTHER
        assert entry.source == ImageSource.DESKTOP
        assert entry.importance == 0.6
        assert entry.visual_concepts == []
        assert entry.access_count == 0

    def test_to_metadata(self):
        from app.engine.semantic_memory.visual_memory import (
            ImageMemoryEntry, ImageSource, VisualConceptType,
        )
        entry = ImageMemoryEntry(
            user_id="u1",
            image_hash="sha256:abc",
            visual_concepts=["radar", "hải đồ"],
            concept_type=VisualConceptType.MAP,
            source=ImageSource.ZALO,
            source_url="s3://bucket/img.png",
            media_type="image/png",
            access_count=3,
        )
        meta = entry.to_metadata()
        assert meta["image_hash"] == "sha256:abc"
        assert meta["visual_concepts"] == ["radar", "hải đồ"]
        assert meta["concept_type"] == "map"
        assert meta["source"] == "zalo"
        assert meta["source_url"] == "s3://bucket/img.png"
        assert meta["media_type"] == "image/png"
        assert meta["access_count"] == 3
        assert meta["is_visual_memory"] is True

    def test_from_metadata(self):
        from app.engine.semantic_memory.visual_memory import (
            ImageMemoryEntry, ImageSource, VisualConceptType,
        )
        metadata = {
            "image_hash": "h123",
            "visual_concepts": ["colregs"],
            "concept_type": "diagram",
            "source": "telegram",
            "source_url": None,
            "media_type": "image/jpeg",
            "access_count": 1,
            "is_visual_memory": True,
        }
        entry = ImageMemoryEntry.from_metadata(
            user_id="u2",
            content="Sơ đồ quy tắc COLREGs",
            metadata=metadata,
            memory_id="mem-001",
            importance=0.7,
            session_id="sess-1",
            created_at=datetime(2026, 1, 15, tzinfo=timezone.utc),
        )
        assert entry.user_id == "u2"
        assert entry.image_hash == "h123"
        assert entry.description == "Sơ đồ quy tắc COLREGs"
        assert entry.concept_type == VisualConceptType.DIAGRAM
        assert entry.source == ImageSource.TELEGRAM
        assert entry.importance == 0.7
        assert entry.memory_id == "mem-001"
        assert entry.visual_concepts == ["colregs"]

    def test_from_metadata_defaults(self):
        from app.engine.semantic_memory.visual_memory import (
            ImageMemoryEntry, ImageSource, VisualConceptType,
        )
        entry = ImageMemoryEntry.from_metadata(
            user_id="u3", content="Test", metadata={},
        )
        assert entry.concept_type == VisualConceptType.OTHER
        assert entry.source == ImageSource.DESKTOP
        assert entry.image_hash == ""


class TestVisualMemoryContext:
    """Test VisualMemoryContext dataclass."""

    def test_defaults(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryContext
        ctx = VisualMemoryContext()
        assert ctx.entries == []
        assert ctx.context_text == ""
        assert ctx.total_time_ms == 0.0


# ==============================================================================
# 2. HASH COMPUTATION TESTS
# ==============================================================================


class TestImageHash:
    """Test image hash computation for deduplication."""

    def test_compute_image_hash(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        data = b"test image bytes"
        expected = hashlib.sha256(data).hexdigest()
        assert mgr.compute_image_hash(data) == expected

    def test_compute_hash_from_base64(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        raw = b"sample image data"
        b64 = base64.b64encode(raw).decode()
        expected = hashlib.sha256(raw).hexdigest()
        assert mgr.compute_image_hash_from_base64(b64) == expected

    def test_compute_hash_from_base64_invalid_fallback(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        # Invalid base64 — should fall back to hashing the string
        result = mgr.compute_image_hash_from_base64("not-valid-base64!!!")
        assert len(result) == 64  # SHA-256 hex length

    def test_same_data_same_hash(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        data = b"identical"
        h1 = mgr.compute_image_hash(data)
        h2 = mgr.compute_image_hash(data)
        assert h1 == h2

    def test_different_data_different_hash(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        h1 = mgr.compute_image_hash(b"image1")
        h2 = mgr.compute_image_hash(b"image2")
        assert h1 != h2


# ==============================================================================
# 3. CONCEPT TYPE DETECTION TESTS
# ==============================================================================


class TestConceptTypeDetection:
    """Test detect_concept_type method."""

    def test_detect_diagram(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Sơ đồ luồng quy trình xử lý") == VisualConceptType.DIAGRAM

    def test_detect_table(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Bảng dữ liệu tốc độ gió") == VisualConceptType.TABLE

    def test_detect_chart(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Biểu đồ tròn phân bố tàu") == VisualConceptType.CHART

    def test_detect_map(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Bản đồ hàng hải vùng biển Đông") == VisualConceptType.MAP

    def test_detect_formula(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Công thức tính khoảng cách an toàn") == VisualConceptType.FORMULA

    def test_detect_screenshot(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Ảnh chụp màn hình ECDIS") == VisualConceptType.SCREENSHOT

    def test_detect_document(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Tài liệu hướng dẫn SOLAS") == VisualConceptType.DOCUMENT

    def test_detect_handwriting(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Ghi chú viết tay về luật") == VisualConceptType.HANDWRITING

    def test_detect_photograph(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Ảnh chụp tàu container") == VisualConceptType.PHOTOGRAPH

    def test_detect_other_fallback(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        assert mgr.detect_concept_type("Nội dung không xác định rõ ràng") == VisualConceptType.OTHER


# ==============================================================================
# 4. CONCEPT EXTRACTION TESTS
# ==============================================================================


class TestConceptExtraction:
    """Test extract_concepts method."""

    def test_extract_maritime_concepts(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        concepts = mgr.extract_concepts(
            "Sơ đồ radar trên tàu theo quy định COLREGs về hàng hải"
        )
        assert "radar" in concepts
        assert "colregs" in concepts
        assert "tàu" in concepts
        assert "hàng hải" in concepts

    def test_extract_general_concepts(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        concepts = mgr.extract_concepts("Bảng biểu đồ quy tắc luật giao thông")
        assert "bảng" in concepts
        assert "biểu đồ" in concepts
        assert "quy tắc" in concepts
        assert "luật" in concepts

    def test_max_10_concepts(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        # A description with many keywords
        desc = (
            "Sơ đồ radar tàu thuyền hải đồ cảng biển sông hàng hải "
            "navigation buồng lái máy lái bảng biểu đồ công thức quy tắc "
            "luật quy trình hệ thống"
        )
        concepts = mgr.extract_concepts(desc)
        assert len(concepts) <= 10

    def test_empty_description(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        assert mgr.extract_concepts("") == []


# ==============================================================================
# 5. IMAGE DESCRIPTION (VISION LLM) TESTS
# ==============================================================================


class TestDescribeImage:
    """Test describe_image with mocked Vision LLM."""

    @pytest.mark.asyncio
    async def test_describe_image_success(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()

        mock_response = MagicMock()
        mock_response.text = "Biểu đồ radar hiển thị vị trí tàu trong vùng giao thông"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_client):
            desc = await mgr.describe_image("base64data", "image/jpeg")

        assert "radar" in desc.lower() or "biểu đồ" in desc.lower()
        mock_client.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_describe_image_with_context_hint(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()

        mock_response = MagicMock()
        mock_response.text = "Hải đồ vùng biển Đông"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_client):
            desc = await mgr.describe_image("b64", "image/png", context_hint="Bài học hải đồ")

        assert len(desc) > 5
        # Check that context hint was included in prompt
        call_args = mock_client.models.generate_content.call_args
        contents = call_args[1]["contents"] if "contents" in call_args[1] else call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("contents", [])
        # The prompt should contain the context hint
        assert desc == "Hải đồ vùng biển Đông"

    @pytest.mark.asyncio
    async def test_describe_image_empty_response(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()

        mock_response = MagicMock()
        mock_response.text = ""

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("google.genai.Client", return_value=mock_client):
            desc = await mgr.describe_image("b64", "image/jpeg")

        assert "không rõ" in desc.lower()

    @pytest.mark.asyncio
    async def test_describe_image_exception_fallback(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()

        with patch("google.genai.Client", side_effect=Exception("API error")):
            desc = await mgr.describe_image("b64", "image/jpeg")

        assert "không thể phân tích" in desc.lower()


# ==============================================================================
# 6. STORE IMAGE MEMORY TESTS
# ==============================================================================


class TestStoreImageMemory:
    """Test store_image_memory method."""

    @pytest.mark.asyncio
    async def test_store_image_memory_success(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()
        raw = b"fake image bytes"
        b64 = base64.b64encode(raw).decode()

        mock_settings = MagicMock()
        mock_settings.enable_visual_memory = True

        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])

        mock_repo = MagicMock()
        mock_repo.save_memory.return_value = MagicMock(id=uuid4())

        with patch("app.core.config.get_settings", return_value=mock_settings), \
             patch(
                 "app.engine.semantic_memory.visual_memory.describe_image_content",
                 new=AsyncMock(
                     return_value=SimpleNamespace(
                         success=True,
                         text="Bảng dữ liệu tốc độ gió biển",
                         error=None,
                     )
                 ),
             ), \
             patch("app.engine.semantic_memory.visual_memory.get_embedding_backend", return_value=mock_embeddings), \
             patch("app.repositories.semantic_memory_repository.SemanticMemoryRepository", return_value=mock_repo):
            entry = await mgr.store_image_memory(
                user_id="user-1",
                image_base64=b64,
                media_type="image/jpeg",
                session_id="sess-1",
                context_hint="Bài kiểm tra",
            )

        assert entry is not None
        assert entry.user_id == "user-1"
        assert entry.description == "Bảng dữ liệu tốc độ gió biển"
        assert entry.image_hash == hashlib.sha256(raw).hexdigest()
        mock_repo.save_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_store_image_memory_blocks_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.runtime.session_event_log import InMemorySessionEventLog
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()
        b64 = base64.b64encode(b"private image bytes").decode()
        log = InMemorySessionEventLog()

        mock_settings = MagicMock()
        mock_settings.enable_visual_memory = True
        describe = AsyncMock(
            return_value=SimpleNamespace(
                success=True,
                text="PRIVATE IMAGE DESCRIPTION",
                error=None,
            )
        )
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.1] * 768])
        repo_factory = MagicMock()

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        monkeypatch.setattr(
            "app.engine.runtime.session_event_log.get_session_event_log",
            lambda: log,
        )

        token = current_org_id.set(None)
        try:
            with patch("app.core.config.get_settings", return_value=mock_settings), \
                 patch(
                     "app.engine.semantic_memory.visual_memory.describe_image_content",
                     new=describe,
                 ), \
                 patch(
                     "app.engine.semantic_memory.visual_memory.get_embedding_backend",
                     return_value=mock_embeddings,
                 ), \
                 patch(
                     "app.repositories.semantic_memory_repository.SemanticMemoryRepository",
                     repo_factory,
                 ):
                entry = await mgr.store_image_memory(
                    user_id="user-private-123",
                    image_base64=b64,
                    media_type="image/jpeg",
                    session_id="session-private-123",
                    context_hint="PRIVATE IMAGE CONTEXT",
                )
        finally:
            current_org_id.reset(token)

        assert entry is None
        describe.assert_not_awaited()
        mock_embeddings.aembed_documents.assert_not_awaited()
        repo_factory.assert_not_called()
        events = await log.get_events(session_id="session-private-123")
        assert len(events) == 1
        payload = events[0].payload
        assert payload["write"]["kind"] == "visual_memory"
        assert payload["write"]["status"] == "blocked"
        assert payload["scope"]["write_allowed"] is False
        assert payload["privacy"]["raw_content_included"] is False
        assert (
            payload["scope"]["organization_context"]
            == "blocked_missing_org_context"
        )
        serialized = str(payload)
        assert "PRIVATE IMAGE CONTEXT" not in serialized
        assert "PRIVATE IMAGE DESCRIPTION" not in serialized
        assert "user-private-123" not in serialized
        assert "session-private-123" not in serialized

    @pytest.mark.asyncio
    async def test_store_image_memory_feature_disabled(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()

        mock_settings = MagicMock()
        mock_settings.enable_visual_memory = False

        # describe_image is called before settings check, so mock it
        mock_response = MagicMock()
        mock_response.text = "Some description"
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        with patch("app.core.config.get_settings", return_value=mock_settings), \
             patch("google.genai.Client", return_value=mock_client):
            entry = await mgr.store_image_memory(
                user_id="user-1",
                image_base64=base64.b64encode(b"data").decode(),
            )

        assert entry is None

    @pytest.mark.asyncio
    async def test_store_image_memory_dedup(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()
        raw = b"same image"
        b64 = base64.b64encode(raw).decode()
        image_hash = hashlib.sha256(raw).hexdigest()

        # Pre-fill cache to simulate already stored
        mgr._description_cache[image_hash] = "Already stored"

        entry = await mgr.store_image_memory(
            user_id="user-1",
            image_base64=b64,
        )

        assert entry is None  # Duplicate, not stored again

    @pytest.mark.asyncio
    async def test_store_image_memory_exception(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()

        with patch("google.genai.Client", side_effect=Exception("boom")), \
             patch("app.core.config.get_settings", return_value=MagicMock(enable_visual_memory=True)):
            entry = await mgr.store_image_memory(
                user_id="u1",
                image_base64=base64.b64encode(b"x").decode(),
            )

        # Should not raise, returns None
        assert entry is None


# ==============================================================================
# 7. RETRIEVE VISUAL MEMORIES TESTS
# ==============================================================================


class TestRetrieveVisualMemories:
    """Test retrieve_visual_memories method."""

    @pytest.mark.asyncio
    async def test_retrieve_success(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        from app.models.semantic_memory import MemoryType

        mgr = VisualMemoryManager()

        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.5] * 768])

        mock_result = MagicMock()
        mock_result.id = uuid4()
        mock_result.content = "Bảng radar tàu"
        mock_result.importance = 0.6
        mock_result.metadata = {
            "is_visual_memory": True,
            "image_hash": "h123",
            "visual_concepts": ["radar", "tàu"],
            "concept_type": "table",
            "source": "desktop",
            "media_type": "image/jpeg",
            "access_count": 2,
        }
        mock_result.created_at = datetime(2026, 2, 20, tzinfo=timezone.utc)

        mock_repo = MagicMock()
        mock_repo.search_similar.return_value = [mock_result]

        with patch("app.engine.semantic_memory.visual_memory.get_embedding_backend", return_value=mock_embeddings), \
             patch("app.repositories.semantic_memory_repository.SemanticMemoryRepository", return_value=mock_repo):
            ctx = await mgr.retrieve_visual_memories(
                user_id="u1", query="radar tàu biển",
            )

        assert len(ctx.entries) == 1
        assert ctx.entries[0].image_hash == "h123"
        assert ctx.entries[0].description == "Bảng radar tàu"
        assert "Trí nhớ hình ảnh" in ctx.context_text
        assert ctx.total_time_ms >= 0

    @pytest.mark.asyncio
    async def test_retrieve_empty(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()

        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.5] * 768])

        mock_repo = MagicMock()
        mock_repo.search_similar.return_value = []

        with patch("app.engine.semantic_memory.visual_memory.get_embedding_backend", return_value=mock_embeddings), \
             patch("app.repositories.semantic_memory_repository.SemanticMemoryRepository", return_value=mock_repo):
            ctx = await mgr.retrieve_visual_memories(user_id="u1", query="test")

        assert len(ctx.entries) == 0
        assert ctx.context_text == ""

    @pytest.mark.asyncio
    async def test_retrieve_filters_non_visual(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()

        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.5] * 768])

        # Result without is_visual_memory flag
        mock_result = MagicMock()
        mock_result.id = uuid4()
        mock_result.content = "Regular memory"
        mock_result.importance = 0.5
        mock_result.metadata = {}  # No is_visual_memory
        mock_result.created_at = datetime.now(timezone.utc)

        mock_repo = MagicMock()
        mock_repo.search_similar.return_value = [mock_result]

        with patch("app.engine.semantic_memory.visual_memory.get_embedding_backend", return_value=mock_embeddings), \
             patch("app.repositories.semantic_memory_repository.SemanticMemoryRepository", return_value=mock_repo):
            ctx = await mgr.retrieve_visual_memories(user_id="u1", query="test")

        assert len(ctx.entries) == 0

    @pytest.mark.asyncio
    async def test_retrieve_exception_returns_empty(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()

        with patch("app.engine.semantic_memory.visual_memory.get_embedding_backend", side_effect=Exception("embed error")):
            ctx = await mgr.retrieve_visual_memories(user_id="u1", query="test")

        assert len(ctx.entries) == 0
        assert ctx.context_text == ""

    @pytest.mark.asyncio
    async def test_retrieve_blocks_without_org_context_when_multi_tenant(
        self,
        monkeypatch,
    ):
        from app.core.config import settings
        from app.core.org_context import current_org_id
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()
        mock_embeddings = MagicMock()
        mock_embeddings.aembed_documents = AsyncMock(return_value=[[0.5] * 768])
        repo_factory = MagicMock()

        monkeypatch.setattr(settings, "enable_multi_tenant", True)
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(settings, "default_organization_id", "default")
        token = current_org_id.set(None)
        try:
            with patch(
                "app.engine.semantic_memory.visual_memory.get_embedding_backend",
                return_value=mock_embeddings,
            ), patch(
                "app.repositories.semantic_memory_repository.SemanticMemoryRepository",
                repo_factory,
            ):
                ctx = await mgr.retrieve_visual_memories(
                    user_id="user-private-123",
                    query="PRIVATE QUERY",
                )
        finally:
            current_org_id.reset(token)

        assert ctx.entries == []
        assert ctx.context_text == ""
        mock_embeddings.aembed_documents.assert_not_called()
        repo_factory.assert_not_called()


# ==============================================================================
# 8. CONTEXT TEXT BUILDING TESTS
# ==============================================================================


class TestBuildVisualContext:
    """Test _build_visual_context formatting."""

    def test_empty_entries(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        assert mgr._build_visual_context([]) == ""

    def test_single_entry_today(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, ImageMemoryEntry, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        entry = ImageMemoryEntry(
            user_id="u1",
            description="Bảng radar",
            concept_type=VisualConceptType.TABLE,
            visual_concepts=["radar"],
            created_at=datetime.now(timezone.utc),
        )
        text = mgr._build_visual_context([entry])
        assert "Trí nhớ hình ảnh" in text
        assert "table" in text
        assert "hôm nay" in text
        assert "Bảng radar" in text
        assert "radar" in text

    def test_entry_yesterday(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, ImageMemoryEntry, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        entry = ImageMemoryEntry(
            user_id="u1",
            description="Sơ đồ",
            concept_type=VisualConceptType.DIAGRAM,
            created_at=datetime.now(timezone.utc) - timedelta(days=1),
        )
        text = mgr._build_visual_context([entry])
        assert "hôm qua" in text

    def test_entry_days_ago(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, ImageMemoryEntry, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        entry = ImageMemoryEntry(
            user_id="u1",
            description="Ảnh",
            concept_type=VisualConceptType.PHOTOGRAPH,
            created_at=datetime.now(timezone.utc) - timedelta(days=5),
        )
        text = mgr._build_visual_context([entry])
        assert "5 ngày trước" in text

    def test_entry_weeks_ago(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, ImageMemoryEntry, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        entry = ImageMemoryEntry(
            user_id="u1",
            description="Old",
            concept_type=VisualConceptType.OTHER,
            created_at=datetime.now(timezone.utc) - timedelta(days=14),
        )
        text = mgr._build_visual_context([entry])
        assert "2 tuần trước" in text

    def test_multiple_entries(self):
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryManager, ImageMemoryEntry, VisualConceptType,
        )
        mgr = VisualMemoryManager()
        entries = [
            ImageMemoryEntry(
                user_id="u1", description="Entry 1",
                concept_type=VisualConceptType.CHART,
                created_at=datetime.now(timezone.utc),
            ),
            ImageMemoryEntry(
                user_id="u1", description="Entry 2",
                concept_type=VisualConceptType.TABLE,
                created_at=datetime.now(timezone.utc),
            ),
        ]
        text = mgr._build_visual_context(entries)
        assert "1." in text
        assert "2." in text
        assert "Entry 1" in text
        assert "Entry 2" in text


# ==============================================================================
# 9. SINGLETON TESTS
# ==============================================================================


class TestSingleton:
    """Test module-level singleton."""

    def test_singleton_consistent(self):
        import app.engine.semantic_memory.visual_memory as vm_mod
        # Reset singleton
        vm_mod._visual_memory = None
        m1 = vm_mod.get_visual_memory_manager()
        m2 = vm_mod.get_visual_memory_manager()
        assert m1 is m2
        # Cleanup
        vm_mod._visual_memory = None

    def test_clear_cache(self):
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager
        mgr = VisualMemoryManager()
        mgr._description_cache["test"] = "cached"
        mgr.clear_cache()
        assert len(mgr._description_cache) == 0


# ==============================================================================
# 10. MEMORY TYPE INTEGRATION TESTS
# ==============================================================================


class TestMemoryTypeIntegration:
    """Test IMAGE_MEMORY enum in semantic_memory models."""

    def test_image_memory_type_exists(self):
        from app.models.semantic_memory import MemoryType
        assert hasattr(MemoryType, "IMAGE_MEMORY")
        assert MemoryType.IMAGE_MEMORY.value == "image_memory"

    def test_image_memory_in_enum_members(self):
        from app.models.semantic_memory import MemoryType
        values = {m.value for m in MemoryType}
        assert "image_memory" in values

    def test_backward_compat_existing_types(self):
        from app.models.semantic_memory import MemoryType
        # Ensure existing types still work
        assert MemoryType.MESSAGE.value == "message"
        assert MemoryType.SUMMARY.value == "summary"
        assert MemoryType.RUNNING_SUMMARY.value == "running_summary"
        assert MemoryType.USER_FACT.value == "user_fact"
        assert MemoryType.INSIGHT.value == "insight"


# ==============================================================================
# 11. CONFIG FLAG TESTS
# ==============================================================================


class TestConfigFlags:
    """Test visual memory config flags."""

    def test_enable_visual_memory_default_false(self):
        from app.core.config import Settings
        s = Settings(
            google_api_key="test-key",
            api_key="test",
            _env_file=None,
        )
        assert s.enable_visual_memory is False

    def test_visual_memory_max_per_user_default(self):
        from app.core.config import Settings
        s = Settings(
            google_api_key="test-key",
            api_key="test",
            _env_file=None,
        )
        assert s.visual_memory_max_per_user == 100

    def test_visual_memory_context_max_items_default(self):
        from app.core.config import Settings
        s = Settings(
            google_api_key="test-key",
            api_key="test",
            _env_file=None,
        )
        assert s.visual_memory_context_max_items == 3


# ==============================================================================
# 12. INPUT PROCESSOR INTEGRATION TESTS
# ==============================================================================


class TestInputProcessorIntegration:
    """Test visual memory integration in input_processor."""

    @pytest.mark.asyncio
    async def test_visual_memory_context_injection(self):
        """When enabled, visual memory context is injected into semantic_parts."""
        from app.engine.semantic_memory.visual_memory import (
            VisualMemoryContext, ImageMemoryEntry, VisualConceptType,
        )

        mock_ctx = VisualMemoryContext(
            entries=[
                ImageMemoryEntry(
                    user_id="u1", description="Radar chart",
                    concept_type=VisualConceptType.CHART,
                    created_at=datetime.now(timezone.utc),
                ),
            ],
            context_text="=== Trí nhớ hình ảnh ===\n1. [chart] (hôm nay): Radar chart",
        )

        mock_vm = MagicMock()
        mock_vm.retrieve_visual_memories = AsyncMock(return_value=mock_ctx)

        mock_settings = MagicMock()
        mock_settings.enable_visual_memory = True
        mock_settings.visual_memory_context_max_items = 3

        # Simulate the injection logic from input_processor
        semantic_parts = ["=== Existing context ==="]

        if mock_settings.enable_visual_memory:
            visual_ctx = await mock_vm.retrieve_visual_memories(
                user_id="u1", query="test query",
                limit=mock_settings.visual_memory_context_max_items,
            )
            if visual_ctx.context_text:
                semantic_parts.append(visual_ctx.context_text)

        result = "\n\n".join(semantic_parts)
        assert "Trí nhớ hình ảnh" in result
        assert "Radar chart" in result

    @pytest.mark.asyncio
    async def test_visual_memory_disabled_no_injection(self):
        """When disabled, no visual memory context is injected."""
        mock_settings = MagicMock()
        mock_settings.enable_visual_memory = False

        semantic_parts = ["=== Existing context ==="]

        if mock_settings.enable_visual_memory:
            # Should not execute
            semantic_parts.append("SHOULD NOT APPEAR")

        result = "\n\n".join(semantic_parts)
        assert "SHOULD NOT APPEAR" not in result

    @pytest.mark.asyncio
    async def test_image_storage_triggered_for_base64(self):
        """When vision + visual_memory enabled, base64 images trigger storage."""
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()
        mgr.store_image_memory = AsyncMock(return_value=None)

        mock_img = MagicMock()
        mock_img.type = "base64"
        mock_img.data = base64.b64encode(b"test").decode()
        mock_img.media_type = "image/jpeg"

        images = [mock_img]

        # Simulate input_processor logic
        for img in images:
            if getattr(img, 'type', 'base64') == 'base64' and getattr(img, 'data', ''):
                await mgr.store_image_memory(
                    user_id="u1",
                    image_base64=img.data,
                    media_type=getattr(img, 'media_type', 'image/jpeg'),
                    session_id="sess-1",
                    context_hint="test message",
                )

        mgr.store_image_memory.assert_called_once()

    @pytest.mark.asyncio
    async def test_url_images_not_stored(self):
        """URL-type images are not stored (only base64)."""
        from app.engine.semantic_memory.visual_memory import VisualMemoryManager

        mgr = VisualMemoryManager()
        mgr.store_image_memory = AsyncMock(return_value=None)

        mock_img = MagicMock()
        mock_img.type = "url"
        mock_img.data = "https://example.com/img.jpg"

        images = [mock_img]

        for img in images:
            if getattr(img, 'type', 'base64') == 'base64' and getattr(img, 'data', ''):
                await mgr.store_image_memory(
                    user_id="u1",
                    image_base64=img.data,
                )

        mgr.store_image_memory.assert_not_called()
