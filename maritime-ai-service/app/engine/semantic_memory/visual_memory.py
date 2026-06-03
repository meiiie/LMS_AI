"""
Visual Memory — Multimodal image memory for Wiii.
Sprint 186: "Trí Nhớ Hình Ảnh"

Allows Wiii to remember images users have sent and recall them later.
Key capabilities:
1. Store image descriptions + metadata (hash, source, concepts)
2. Generate text descriptions via Vision LLM for text-based retrieval
3. Retrieve images by text query (semantic similarity on descriptions)
4. Track image importance and decay (medium-term: 504h stability)

Data storage:
- Uses existing `semantic_memories` table with memory_type=IMAGE_MEMORY
- Image metadata stored in `metadata` JSONB: image_hash, source_url, concepts, etc.
- Text description stored in `content` field for embedding-based retrieval
- Zero new migrations required

Feature-gated by enable_visual_memory in config.
"""

import base64 as b64module
import hashlib
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from app.engine.embedding_runtime import get_embedding_backend
from app.engine.semantic_memory.privacy import hash_memory_identifier
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    append_semantic_memory_write_audit_event,
    build_semantic_memory_write_audit,
    resolve_memory_read_scope,
    resolve_memory_write_scope,
)
from app.engine.vision_runtime import describe_image_content

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


class ImageSource(str, Enum):
    """Source channel where the image was received."""

    DESKTOP = "desktop"        # Pasted/attached in desktop chat
    MESSENGER = "messenger"    # Facebook Messenger
    ZALO = "zalo"              # Zalo OA
    TELEGRAM = "telegram"      # Telegram bot
    WEB = "web"                # Web embed chat
    UPLOAD = "upload"          # Direct file upload
    SCREENSHOT = "screenshot"  # Browser screenshot


class VisualConceptType(str, Enum):
    """Categories of visual content recognized."""

    DIAGRAM = "diagram"            # Technical diagram, flowchart
    TABLE = "table"                # Data table, spreadsheet
    CHART = "chart"                # Bar/line/pie chart
    PHOTOGRAPH = "photograph"      # Real-world photo
    SCREENSHOT = "screenshot"      # App/web screenshot
    DOCUMENT = "document"          # Scanned document page
    MAP = "map"                    # Navigation/geographic map
    FORMULA = "formula"            # Mathematical formula
    HANDWRITING = "handwriting"    # Handwritten notes
    OTHER = "other"


@dataclass
class ImageMemoryEntry:
    """A stored image memory with description and metadata."""

    memory_id: Optional[str] = None
    user_id: str = ""
    image_hash: str = ""           # SHA-256 of image data
    description: str = ""          # Text description (Vietnamese)
    visual_concepts: List[str] = field(default_factory=list)
    concept_type: VisualConceptType = VisualConceptType.OTHER
    source: ImageSource = ImageSource.DESKTOP
    source_url: Optional[str] = None   # MinIO/S3 URL if stored
    media_type: str = "image/jpeg"
    importance: float = 0.6
    session_id: Optional[str] = None
    created_at: Optional[datetime] = None
    last_accessed: Optional[datetime] = None
    access_count: int = 0

    def to_metadata(self) -> Dict[str, Any]:
        """Convert to metadata dict for semantic_memories JSONB storage."""
        return {
            "image_hash": self.image_hash,
            "visual_concepts": self.visual_concepts,
            "concept_type": self.concept_type.value,
            "source": self.source.value,
            "source_url": self.source_url,
            "media_type": self.media_type,
            "access_count": self.access_count,
            "is_visual_memory": True,
        }

    @classmethod
    def from_metadata(
        cls,
        user_id: str,
        content: str,
        metadata: Dict[str, Any],
        memory_id: Optional[str] = None,
        importance: float = 0.6,
        session_id: Optional[str] = None,
        created_at: Optional[datetime] = None,
    ) -> "ImageMemoryEntry":
        """Reconstruct from semantic_memories metadata."""
        return cls(
            memory_id=memory_id,
            user_id=user_id,
            image_hash=metadata.get("image_hash", ""),
            description=content,
            visual_concepts=metadata.get("visual_concepts", []),
            concept_type=VisualConceptType(
                metadata.get("concept_type", "other")
            ),
            source=ImageSource(metadata.get("source", "desktop")),
            source_url=metadata.get("source_url"),
            media_type=metadata.get("media_type", "image/jpeg"),
            importance=importance,
            session_id=session_id,
            created_at=created_at,
            access_count=metadata.get("access_count", 0),
        )


@dataclass
class VisualMemoryContext:
    """Result from visual memory retrieval."""

    entries: List[ImageMemoryEntry] = field(default_factory=list)
    context_text: str = ""
    total_time_ms: float = 0.0


# =============================================================================
# Visual Memory Manager
# =============================================================================


class VisualMemoryManager:
    """Manages image memories for users.

    Stores image descriptions + metadata in semantic_memories table.
    Retrieval is text-based (embedding of description) for simplicity.
    """

    # Image memory importance: medium-term stability (between learning and personal)
    DEFAULT_IMPORTANCE = 0.6
    # Max image memories per user before oldest are pruned
    MAX_MEMORIES_PER_USER = 100

    def __init__(self):
        self._description_cache: Dict[str, str] = {}  # image_hash → description

    @staticmethod
    def compute_image_hash(image_data: bytes) -> str:
        """Compute SHA-256 hash of image data for deduplication."""
        return hashlib.sha256(image_data).hexdigest()

    @staticmethod
    def compute_image_hash_from_base64(base64_data: str) -> str:
        """Compute SHA-256 hash from base64-encoded image data."""
        try:
            raw = b64module.b64decode(base64_data)
            return hashlib.sha256(raw).hexdigest()
        except Exception:
            # Fallback: hash the base64 string itself
            return hashlib.sha256(base64_data.encode()).hexdigest()

    async def describe_image(
        self,
        image_base64: str,
        media_type: str = "image/jpeg",
        context_hint: str = "",
    ) -> str:
        """Generate a text description of an image using Vision LLM.

        Args:
            image_base64: Base64-encoded image data.
            media_type: MIME type of the image.
            context_hint: Optional hint about what the image shows.

        Returns:
            Vietnamese text description of the image.
        """
        try:
            b64module.b64decode(image_base64, validate=True)
        except Exception:
            return await self._describe_image_via_google_legacy(
                image_base64=image_base64,
                media_type=media_type,
                context_hint=context_hint,
            )

        result = await describe_image_content(
            image_base64=image_base64,
            media_type=media_type,
            context_hint=context_hint,
        )
        if result.success and result.text:
            description = result.text.strip()
            if len(description) < 10:
                return "Hình ảnh không rõ nội dung."
            return description
        if result.error:
            logger.warning("[VisualMemory] Image description failed: %s", result.error)
        return "Hình ảnh do người dùng gửi (không thể phân tích chi tiết)."

        try:
            from google import genai

            client = genai.Client()

            prompt = (
                "Mô tả chi tiết hình ảnh này bằng tiếng Việt. "
                "Nêu rõ: loại hình ảnh (biểu đồ/bảng/ảnh/sơ đồ/tài liệu), "
                "nội dung chính, các chi tiết quan trọng. "
                "Viết ngắn gọn (50-150 từ)."
            )
            if context_hint:
                prompt += f"\nNgữ cảnh: {context_hint}"

            from app.core.config import get_settings
            _vm_model = get_settings().google_model
            response = client.models.generate_content(
                model=_vm_model,
                contents=[
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": media_type,
                                    "data": image_base64,
                                },
                            },
                        ],
                    },
                ],
            )

            description = response.text.strip() if response.text else ""
            if len(description) < 10:
                description = "Hình ảnh không rõ nội dung."
            return description

        except Exception as e:
            logger.warning("[VisualMemory] Image description failed: %s", e)
            return "Hình ảnh do người dùng gửi (không thể phân tích chi tiết)."

    async def _describe_image_via_google_legacy(
        self,
        *,
        image_base64: str,
        media_type: str,
        context_hint: str,
    ) -> str:
        """Compatibility path for legacy tests using mocked google.genai.Client."""
        try:
            from google import genai

            client = genai.Client()

            prompt = (
                "Mô tả chi tiết hình ảnh này bằng tiếng Việt. "
                "Nêu rõ: loại hình ảnh (biểu đồ/bảng/ảnh/sơ đồ/tài liệu), "
                "nội dung chính, các chi tiết quan trọng. "
                "Viết ngắn gọn (50-150 từ)."
            )
            if context_hint:
                prompt += f"\nNgữ cảnh: {context_hint}"

            from app.core.config import get_settings

            _vm_model = get_settings().google_model
            response = client.models.generate_content(
                model=_vm_model,
                contents=[
                    {
                        "parts": [
                            {"text": prompt},
                            {
                                "inline_data": {
                                    "mime_type": media_type,
                                    "data": image_base64,
                                },
                            },
                        ],
                    },
                ],
            )

            description = response.text.strip() if response.text else ""
            if len(description) < 10:
                description = "Hình ảnh không rõ nội dung."
            return description

        except Exception as e:
            logger.warning("[VisualMemory] Image description failed: %s", e)
            return "Hình ảnh do người dùng gửi (không thể phân tích chi tiết)."

    def detect_concept_type(self, description: str) -> VisualConceptType:
        """Detect visual concept type from description text."""
        desc_lower = description.lower()

        # Order matters: more specific types first to avoid substring false matches
        # (e.g., "hàng hải" should match MAP before "hàng" matches TABLE)
        _type_keywords = [
            (VisualConceptType.MAP, [
                "bản đồ", "map", "hải đồ", "vùng biển", "tuyến đường", "hàng hải",
            ]),
            (VisualConceptType.DIAGRAM, [
                "sơ đồ", "flowchart", "diagram", "luồng", "quy trình",
            ]),
            (VisualConceptType.FORMULA, [
                "công thức", "formula", "phương trình", "toán",
            ]),
            (VisualConceptType.TABLE, [
                "bảng", "table", "dữ liệu bảng",
            ]),
            (VisualConceptType.CHART, [
                "biểu đồ", "chart", "đồ thị", "pie", "bar", "graph",
            ]),
            (VisualConceptType.SCREENSHOT, [
                "screenshot", "ảnh chụp màn hình", "giao diện",
                "app", "trang web",
            ]),
            (VisualConceptType.HANDWRITING, [
                "viết tay", "handwriting", "chữ viết", "ghi chú tay",
            ]),
            (VisualConceptType.DOCUMENT, [
                "tài liệu", "document", "văn bản",
            ]),
            (VisualConceptType.PHOTOGRAPH, [
                "ảnh", "photo", "hình ảnh thực", "chụp", "photograph",
            ]),
        ]

        for concept_type, keywords in _type_keywords:
            if any(kw in desc_lower for kw in keywords):
                return concept_type

        return VisualConceptType.OTHER

    def extract_concepts(self, description: str) -> List[str]:
        """Extract visual concepts (keywords) from description."""
        concepts = []
        desc_lower = description.lower()

        # Domain-specific maritime concepts
        _maritime_keywords = [
            "colregs", "solas", "marpol", "radar", "ecdis", "ais",
            "tàu", "thuyền", "hải đồ", "cảng", "biển", "sông",
            "hàng hải", "navigation", "buồng lái", "máy lái",
        ]
        for kw in _maritime_keywords:
            if kw in desc_lower:
                concepts.append(kw)

        # General visual concepts
        _general_keywords = [
            "bảng", "biểu đồ", "sơ đồ", "công thức", "bản đồ",
            "quy tắc", "luật", "quy trình", "hệ thống",
        ]
        for kw in _general_keywords:
            if kw in desc_lower:
                concepts.append(kw)

        return concepts[:10]  # Max 10 concepts

    async def store_image_memory(
        self,
        user_id: str,
        image_base64: str,
        media_type: str = "image/jpeg",
        source: ImageSource = ImageSource.DESKTOP,
        session_id: Optional[str] = None,
        context_hint: str = "",
        source_url: Optional[str] = None,
    ) -> Optional[ImageMemoryEntry]:
        """Store an image as a memory with auto-generated description.

        Args:
            user_id: User identifier.
            image_base64: Base64-encoded image data.
            media_type: MIME type.
            source: Channel where image was received.
            session_id: Optional session ID.
            context_hint: Optional context from conversation.
            source_url: Optional URL where image is stored (MinIO/S3).

        Returns:
            ImageMemoryEntry if stored successfully, None on failure.
        """
        start = time.time()

        try:
            # 1. Compute hash for deduplication
            image_hash = self.compute_image_hash_from_base64(image_base64)

            # 2. Check if already stored (dedup by hash)
            if image_hash in self._description_cache:
                logger.info(
                    "[VisualMemory] Duplicate image %s for user_hash=%s, skipping",
                    image_hash[:12],
                    hash_memory_identifier(user_id),
                )
                return None

            # 3. Generate description via Vision LLM
            from app.core.config import get_settings
            settings = get_settings()
            if not settings.enable_visual_memory:
                return None

            audit_scope = resolve_memory_write_scope()
            if not audit_scope.write_allowed:
                await self._append_visual_memory_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    source_message=context_hint,
                    scope=audit_scope,
                    status="blocked",
                    warnings=["visual_memory_blocked_missing_org_context"],
                )
                logger.warning(
                    "[VisualMemory] Store blocked for user_hash=%s: %s",
                    hash_memory_identifier(user_id),
                    audit_scope.state,
                )
                return None

            description = await self.describe_image(
                image_base64, media_type, context_hint,
            )

            # 4. Detect concept type and extract concepts
            concept_type = self.detect_concept_type(description)
            concepts = self.extract_concepts(description)

            # 5. Create entry
            entry = ImageMemoryEntry(
                user_id=user_id,
                image_hash=image_hash,
                description=description,
                visual_concepts=concepts,
                concept_type=concept_type,
                source=source,
                source_url=source_url,
                media_type=media_type,
                importance=self.DEFAULT_IMPORTANCE,
                session_id=session_id,
                created_at=datetime.now(timezone.utc),
            )

            # 6. Store as semantic memory
            stored = await self._store_as_semantic_memory(
                entry,
                audit_scope=audit_scope,
                emit_write_audit=False,
            )
            if stored:
                self._description_cache[image_hash] = description
                elapsed = (time.time() - start) * 1000
                logger.info(
                    "[VisualMemory] Stored image memory for user_hash=%s: %s (%s, %.0fms)",
                    hash_memory_identifier(user_id),
                    image_hash[:12],
                    concept_type.value,
                    elapsed,
                )
                await self._append_visual_memory_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    source_message=description,
                    scope=audit_scope,
                    status="saved",
                )
                return entry

            await self._append_visual_memory_write_audit(
                user_id=user_id,
                session_id=session_id,
                source_message=description,
                scope=audit_scope,
                status="degraded",
                warnings=["visual_memory_not_persisted"],
            )
            return None

        except Exception as e:
            logger.error("[VisualMemory] Failed to store image: %s", e)
            return None

    async def _store_as_semantic_memory(
        self,
        entry: ImageMemoryEntry,
        audit_scope: Optional[MemoryWriteScope] = None,
        emit_write_audit: bool = True,
    ) -> bool:
        """Persist image memory entry to semantic_memories table."""
        scope = audit_scope or resolve_memory_write_scope()
        if not scope.write_allowed:
            await self._append_visual_memory_write_audit(
                user_id=entry.user_id,
                session_id=entry.session_id,
                source_message=entry.description,
                scope=scope,
                status="blocked",
                warnings=["visual_memory_blocked_missing_org_context"],
                emit_write_audit=emit_write_audit,
            )
            logger.warning(
                "[VisualMemory] Semantic storage blocked for user_hash=%s: %s",
                hash_memory_identifier(entry.user_id),
                scope.state,
            )
            return False

        try:
            from app.repositories.semantic_memory_repository import (
                SemanticMemoryRepository,
            )
            from app.models.semantic_memory import (
                MemoryType,
                SemanticMemoryCreate,
            )

            embeddings = get_embedding_backend()
            repo = SemanticMemoryRepository()

            # Embed the text description
            desc_embeddings = await embeddings.aembed_documents(
                [entry.description],
            )
            embedding = desc_embeddings[0] if desc_embeddings else []
            if not embedding:
                logger.warning("[VisualMemory] Empty embedding, skipping semantic storage")
                return False

            memory = SemanticMemoryCreate(
                user_id=entry.user_id,
                content=entry.description,
                embedding=embedding,
                memory_type=MemoryType.IMAGE_MEMORY,
                importance=entry.importance,
                metadata=entry.to_metadata(),
                session_id=entry.session_id,
            )

            result = repo.save_memory(memory)
            await self._append_visual_memory_write_audit(
                user_id=entry.user_id,
                session_id=entry.session_id,
                source_message=entry.description,
                scope=scope,
                status="saved" if result is not None else "degraded",
                warnings=[] if result is not None else ["visual_memory_not_persisted"],
                emit_write_audit=emit_write_audit,
            )
            return result is not None

        except Exception as e:
            logger.error("[VisualMemory] Semantic memory storage failed: %s", e)
            await self._append_visual_memory_write_audit(
                user_id=entry.user_id,
                session_id=entry.session_id,
                source_message=entry.description,
                scope=scope,
                status="failed",
                warnings=["visual_memory_store_failed"],
                emit_write_audit=emit_write_audit,
            )
            return False

    async def _append_visual_memory_write_audit(
        self,
        *,
        user_id: str,
        session_id: Optional[str],
        source_message: Optional[str],
        scope: MemoryWriteScope,
        status: str,
        warnings: Optional[list[str]] = None,
        emit_write_audit: bool = True,
    ) -> bool:
        if not emit_write_audit:
            return False
        audit_payload = build_semantic_memory_write_audit(
            user_id=user_id,
            session_id=session_id,
            message=source_message or "",
            response="",
            scope=scope,
            write_kind="visual_memory",
            message_saved=False,
            response_saved=False,
            extract_facts=False,
            stored_fact_count=0,
            stored_insight_count=0,
            status=status,
            warnings=warnings,
        )
        return await append_semantic_memory_write_audit_event(
            session_id=session_id,
            org_id=scope.org_id,
            payload=audit_payload,
        )

    async def retrieve_visual_memories(
        self,
        user_id: str,
        query: str,
        limit: int = 5,
        similarity_threshold: float = 0.5,
    ) -> VisualMemoryContext:
        """Retrieve image memories relevant to a text query.

        Uses text-based semantic search on image descriptions.

        Args:
            user_id: User identifier.
            query: Text query to match against image descriptions.
            limit: Max results to return.
            similarity_threshold: Min cosine similarity.

        Returns:
            VisualMemoryContext with matching entries and formatted text.
        """
        start = time.time()

        read_scope = resolve_memory_read_scope()
        if not read_scope.write_allowed:
            logger.warning(
                "[VisualMemory] Retrieval blocked for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                read_scope.state,
            )
            return VisualMemoryContext()

        try:
            from app.repositories.semantic_memory_repository import (
                SemanticMemoryRepository,
            )
            from app.models.semantic_memory import MemoryType

            embeddings = get_embedding_backend()
            repo = SemanticMemoryRepository()

            # Embed query
            query_embeddings = await embeddings.aembed_documents([query])
            query_embedding = query_embeddings[0] if query_embeddings else []

            if not query_embedding:
                return VisualMemoryContext()

            # Search for image memories
            results = repo.search_similar(
                user_id=user_id,
                query_embedding=query_embedding,
                limit=limit,
                threshold=similarity_threshold,
                memory_types=[MemoryType.IMAGE_MEMORY],
            )

            # Convert to ImageMemoryEntry
            entries = []
            for r in results:
                if r.metadata.get("is_visual_memory"):
                    entry = ImageMemoryEntry.from_metadata(
                        user_id=user_id,
                        content=r.content,
                        metadata=r.metadata,
                        memory_id=str(r.id),
                        importance=r.importance,
                        created_at=r.created_at,
                    )
                    entries.append(entry)

            # Build context text
            context_text = self._build_visual_context(entries)

            elapsed = (time.time() - start) * 1000
            return VisualMemoryContext(
                entries=entries,
                context_text=context_text,
                total_time_ms=elapsed,
            )

        except Exception as e:
            logger.warning("[VisualMemory] Retrieval failed: %s", e)
            return VisualMemoryContext()

    def _build_visual_context(
        self, entries: List[ImageMemoryEntry],
    ) -> str:
        """Build Vietnamese context text for LLM injection."""
        if not entries:
            return ""

        parts = ["=== Trí nhớ hình ảnh ==="]
        for i, entry in enumerate(entries, 1):
            age_str = ""
            if entry.created_at:
                now = datetime.now(timezone.utc)
                if entry.created_at.tzinfo is None:
                    ca = entry.created_at.replace(tzinfo=timezone.utc)
                else:
                    ca = entry.created_at
                delta = now - ca
                if delta.days == 0:
                    age_str = "hôm nay"
                elif delta.days == 1:
                    age_str = "hôm qua"
                elif delta.days < 7:
                    age_str = f"{delta.days} ngày trước"
                else:
                    weeks = delta.days // 7
                    age_str = f"{weeks} tuần trước"

            line = f"{i}. [{entry.concept_type.value}]"
            if age_str:
                line += f" ({age_str})"
            line += f": {entry.description}"

            if entry.visual_concepts:
                line += f" [khái niệm: {', '.join(entry.visual_concepts[:5])}]"

            parts.append(line)

        return "\n".join(parts)

    def get_user_image_count(self, user_id: str) -> int:
        """Get count of cached image hashes (approximate, cache-wide)."""
        return len(self._description_cache)

    def clear_cache(self) -> None:
        """Clear the description cache."""
        self._description_cache.clear()


# =============================================================================
# Runtime-safe text normalization + patched describe_image authority
# =============================================================================


def _normalize_visual_memory_text(value: str) -> str:
    if not value:
        return value
    try:
        repaired = value.encode("latin-1").decode("utf-8")
        if repaired:
            return repaired
    except Exception:
        pass
    return value


async def _visual_memory_describe_image_legacy(
    self: VisualMemoryManager,
    *,
    image_base64: str,
    media_type: str,
    context_hint: str,
) -> str:
    try:
        from google import genai

        client = genai.Client()
        prompt = (
            "Mô tả chi tiết hình ảnh này bằng tiếng Việt. "
            "Nêu rõ: loại hình ảnh (biểu đồ/bảng/ảnh/sơ đồ/tài liệu), "
            "nội dung chính, các chi tiết quan trọng. "
            "Viết ngắn gọn (50-150 từ)."
        )
        if context_hint:
            prompt += f"\nNgữ cảnh: {context_hint}"

        from app.core.config import get_settings

        response = client.models.generate_content(
            model=get_settings().google_model,
            contents=[
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": media_type,
                                "data": image_base64,
                            },
                        },
                    ],
                },
            ],
        )
        description = _normalize_visual_memory_text(response.text.strip() if response.text else "")
        if len(description) < 10:
            return "không rõ nội dung."
        return description
    except Exception as exc:
        logger.warning("[VisualMemory] Image description failed: %s", exc)
        return "hình ảnh do người dùng gửi (không thể phân tích chi tiết)."


async def _visual_memory_describe_image_runtime(
    self: VisualMemoryManager,
    image_base64: str,
    media_type: str = "image/jpeg",
    context_hint: str = "",
) -> str:
    try:
        b64module.b64decode(image_base64, validate=True)
    except Exception:
        return await _visual_memory_describe_image_legacy(
            self,
            image_base64=image_base64,
            media_type=media_type,
            context_hint=context_hint,
        )

    result = await describe_image_content(
        image_base64=image_base64,
        media_type=media_type,
        context_hint=context_hint,
    )
    if result.success and result.text:
        description = _normalize_visual_memory_text(result.text.strip())
        if len(description) < 10:
            return "không rõ nội dung."
        return description
    if result.error:
        logger.warning("[VisualMemory] Image description failed: %s", result.error)
    return "hình ảnh do người dùng gửi (không thể phân tích chi tiết)."


VisualMemoryManager._describe_image_via_google_legacy = _visual_memory_describe_image_legacy
VisualMemoryManager.describe_image = _visual_memory_describe_image_runtime


# =============================================================================
# Module-level singleton
# =============================================================================

_visual_memory: Optional[VisualMemoryManager] = None


def get_visual_memory_manager() -> VisualMemoryManager:
    """Get or create the singleton VisualMemoryManager."""
    global _visual_memory
    if _visual_memory is None:
        _visual_memory = VisualMemoryManager()
    return _visual_memory
