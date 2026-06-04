"""
Character State Manager — Compiles Wiii's living state into prompt text.

Sprint 93: Loads character blocks from DB and compiles them into a section
that gets injected into the system prompt alongside the static identity YAML.

Sprint 124: Per-user isolation — each user has their own character blocks.
Cache is now keyed by user_id. All methods accept user_id parameter.

Architecture:
    1. Load all CharacterBlocks from DB (per-user)
    2. Compile into formatted text section
    3. PromptLoader calls compile_living_state(user_id) during build_system_prompt()
    4. Character tools update blocks → next prompt gets updated state

Caching: Blocks are cached in-memory with TTL to avoid DB queries on every request.
"""

import logging
import time
from typing import Dict, Optional, Set

from app.engine.character.models import (
    BLOCK_CHAR_LIMITS,
    BlockLabel,
    CharacterBlock,
    CharacterBlockCreate,
    CharacterBlockUpdate,
)

logger = logging.getLogger(__name__)

# Cache TTL in seconds — how long to reuse cached blocks before re-querying DB
_CACHE_TTL_SECONDS = 60


class CharacterStateManager:
    """Manages Wiii's living character state (per-user).

    Sprint 124: All caches and methods are now user-scoped.

    Responsibilities:
    - Load character blocks from DB (with per-user caching)
    - Compile blocks into prompt text
    - Initialize default blocks on first run per user
    - Provide read/write API for character tools
    """

    def __init__(self):
        # Sprint 124: Per-user cache {user_id: {label: block}}
        self._cache: Dict[str, Dict[str, CharacterBlock]] = {}
        self._cache_timestamp: Dict[str, float] = {}
        self._initialized_defaults: Set[str] = set()

    def _get_repo(self):
        """Lazy import to avoid circular deps."""
        from app.engine.character.character_repository import get_character_repository
        return get_character_repository()

    def _cache_key(
        self,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> str:
        """Build the in-memory cache key for a user within an org scope."""
        if isinstance(organization_id, str) and organization_id.strip():
            return f"{organization_id.strip()}::{user_id}"

        multi_tenant_enabled = False
        try:
            from app.core.config import settings

            multi_tenant_enabled = bool(getattr(settings, "enable_multi_tenant", False))
            if not multi_tenant_enabled:
                return user_id

            from app.engine.semantic_memory.write_audit import resolve_memory_read_scope

            scope = resolve_memory_read_scope()
            return f"{scope.org_id or scope.state}::{user_id}"
        except Exception:
            if multi_tenant_enabled:
                return f"unknown::{user_id}"
            return user_id

    def _is_cache_fresh(
        self,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> bool:
        """Check if cached blocks are still fresh for a user."""
        cache_key = self._cache_key(user_id=user_id, organization_id=organization_id)
        ts = self._cache_timestamp.get(cache_key, 0.0)
        return (time.time() - ts) < _CACHE_TTL_SECONDS

    def _refresh_cache(
        self,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> None:
        """Load all blocks from DB into cache for a specific user."""
        cache_key = self._cache_key(user_id=user_id, organization_id=organization_id)
        try:
            repo = self._get_repo()
            blocks = repo.get_all_blocks(user_id=user_id, organization_id=organization_id)
            self._cache[cache_key] = {b.label: b for b in blocks}
            self._cache_timestamp[cache_key] = time.time()
        except Exception as e:
            logger.warning("Failed to refresh character state cache for user '%s': %s", user_id, e)

    def _ensure_defaults(
        self,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> None:
        """Create default blocks if they don't exist yet for a user.

        Called on first compile — seeds the DB with empty blocks
        matching the living_state config in wiii_identity.yaml.
        """
        cache_key = self._cache_key(user_id=user_id, organization_id=organization_id)
        if cache_key in self._initialized_defaults:
            return

        try:
            repo = self._get_repo()
            existing = repo.get_all_blocks(user_id=user_id, organization_id=organization_id)
            if hasattr(repo, "is_available") and not repo.is_available():
                logger.debug(
                    "Skipping default character block seed for user '%s': repository unavailable",
                    user_id,
                )
                return
            existing_labels = {b.label for b in existing}

            for label_enum in BlockLabel:
                label = label_enum.value
                if label not in existing_labels:
                    char_limit = BLOCK_CHAR_LIMITS.get(label, 1000)
                    created = repo.create_block(
                        CharacterBlockCreate(
                            label=label,
                            content="",
                            char_limit=char_limit,
                        ),
                        user_id=user_id,
                        organization_id=organization_id,
                    )
                    if created:
                        logger.info("Created default character block '%s' for user '%s'", label, user_id)
                    elif hasattr(repo, "is_available") and not repo.is_available():
                        return

            self._initialized_defaults.add(cache_key)
        except Exception as e:
            logger.warning("Could not seed default character blocks for user '%s': %s", user_id, e)

    def get_blocks(
        self,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> Dict[str, CharacterBlock]:
        """Get all character blocks for a user (from cache or DB)."""
        cache_key = self._cache_key(user_id=user_id, organization_id=organization_id)
        if not self._is_cache_fresh(user_id=user_id, organization_id=organization_id):
            self._refresh_cache(user_id=user_id, organization_id=organization_id)
        return self._cache.get(cache_key, {}).copy()

    def get_block(
        self,
        label: str,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> Optional[CharacterBlock]:
        """Get a specific block for a user."""
        blocks = self.get_blocks(user_id=user_id, organization_id=organization_id)
        return blocks.get(label)

    def update_block(
        self,
        label: str,
        content: Optional[str] = None,
        append: Optional[str] = None,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> Optional[CharacterBlock]:
        """Update a character block (replace or append) for a specific user.

        Returns the updated block, or None on failure.
        """
        repo = self._get_repo()
        update = CharacterBlockUpdate(content=content, append=append)
        result = repo.update_block(
            label,
            update,
            user_id=user_id,
            organization_id=organization_id,
        )
        if result:
            # Update per-user cache
            cache_key = self._cache_key(user_id=user_id, organization_id=organization_id)
            if cache_key not in self._cache:
                self._cache[cache_key] = {}
            self._cache[cache_key][label] = result
            self._cache_timestamp[cache_key] = time.time()
        return result

    # ─── Sprint 118: Block Consolidation (Letta pattern) ───────────────

    CONSOLIDATION_THRESHOLD = 0.80  # Trigger at 80% full
    CONSOLIDATION_TARGET = 0.60     # Target 60% after consolidation

    def needs_consolidation(
        self,
        label: str,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> bool:
        """Check if a block needs consolidation (>80% full)."""
        block = self.get_block(label, user_id=user_id, organization_id=organization_id)
        if not block or block.char_limit <= 0:
            return False
        return len(block.content) / block.char_limit >= self.CONSOLIDATION_THRESHOLD

    async def consolidate_full_blocks(
        self,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> int:
        """Check all blocks for a user and consolidate any that are >80% full.

        Uses LIGHT tier LLM to summarize/deduplicate content.
        Fail-safe: errors in one block don't affect others.

        Returns:
            Number of blocks consolidated.
        """
        blocks = self.get_blocks(user_id=user_id, organization_id=organization_id)
        consolidated_count = 0

        for label, block in blocks.items():
            if not block.content.strip() or block.char_limit <= 0:
                continue
            usage = len(block.content) / block.char_limit
            if usage < self.CONSOLIDATION_THRESHOLD:
                continue

            try:
                new_content = await self._consolidate_block_content(block)
                if new_content and len(new_content) < len(block.content):
                    self.update_block(
                        label=label,
                        content=new_content,
                        user_id=user_id,
                        organization_id=organization_id,
                    )
                    consolidated_count += 1
                    logger.info(
                        "[CONSOLIDATE] Block '%s' user '%s': %d -> %d chars (%.0f%% reduction)",
                        label,
                        user_id,
                        len(block.content),
                        len(new_content),
                        (1 - len(new_content) / len(block.content)) * 100,
                    )
            except Exception as e:
                logger.debug(
                    "[CONSOLIDATE] Failed for '%s' user '%s' (non-blocking): %s",
                    label, user_id, e,
                )

        return consolidated_count

    async def _consolidate_block_content(
        self, block: CharacterBlock
    ) -> Optional[str]:
        """Use LLM to consolidate block content — deduplicate and summarize.

        Target: reduce to ~60% of char_limit while keeping important info.
        Uses LIGHT tier LLM for speed.

        Returns:
            Consolidated text, or None on failure.
        """
        from app.engine.llm_pool import get_llm_light
        from app.engine.messages import Message
        from app.engine.messages_adapters import to_openai_dict

        target_chars = int(block.char_limit * self.CONSOLIDATION_TARGET)
        llm = get_llm_light()

        prompt = (
            "Tom tat va hop nhat cac ghi chu sau thanh mot ban ngan gon hon.\n\n"
            "QUY TAC:\n"
            "- Giu tat ca thong tin QUAN TRONG va CU THE\n"
            "- Loai bo trung lap, gop y tuong tu\n"
            "- Giu nguyen dinh dang bullet (- moi y mot dong)\n"
            f"- Toi da {target_chars} ky tu\n"
            "- Tra loi TRUC TIEP noi dung da tom tat (KHONG giai thich)\n\n"
            f"Ghi chu hien tai ({len(block.content)} ky tu):\n"
            f"{block.content}"
        )

        result = await llm.ainvoke([to_openai_dict(Message(role="user", content=prompt))])
        text = result.content.strip()

        # Sanity check: result should be shorter and non-empty
        if not text or len(text) >= len(block.content):
            return None

        return text

    def compile_living_state(
        self,
        user_id: str = "__global__",
        organization_id: Optional[str] = None,
    ) -> str:
        """Compile all living character blocks into prompt text for a user.

        Sprint 124: Now per-user. Each user sees only their own blocks.

        Returns a formatted section ready to inject into system prompt.
        Empty blocks are skipped (no noise in prompt).

        Example output:
            --- TRAI NGHIEM CUA WIII (Living State) ---
            Bai hoc rut ra:
            - User hay hoi ve Rule 15, nen minh giai thich ky hon...

            Chu de yeu thich:
            - COLREGs, dac biet phan tranh va...
        """
        # Ensure default blocks exist for this user
        self._ensure_defaults(user_id=user_id, organization_id=organization_id)

        blocks = self.get_blocks(user_id=user_id, organization_id=organization_id)

        # Only include non-empty blocks
        non_empty = {k: v for k, v in blocks.items() if v.content.strip()}
        if not non_empty:
            return ""

        sections = [
            "--- TRẢI NGHIỆM CỦA WIII (Living State) ---"
        ]

        block_headers = {
            BlockLabel.LEARNED_LESSONS: "📝 Bài học rút ra:",
            BlockLabel.FAVORITE_TOPICS: "🎯 Chủ đề yêu thích:",
            BlockLabel.SELF_NOTES: "💭 Ghi chú cá nhân:",
        }

        # Sprint 121 RC-5: Exclude USER_PATTERNS from prompt — it's global,
        # not per-user, and causes cross-user hallucination.
        # USER_PATTERNS still stored in DB for analytics, just not injected.
        _EXCLUDED_FROM_PROMPT = {BlockLabel.USER_PATTERNS}

        for label_enum in BlockLabel:
            if label_enum in _EXCLUDED_FROM_PROMPT:
                continue
            label = label_enum.value
            if label in non_empty:
                header = block_headers.get(label_enum, f"📌 {label}:")
                sections.append(f"\n{header}")
                sections.append(non_empty[label].content.strip())

        return "\n".join(sections)

    def invalidate_cache(
        self,
        user_id: Optional[str] = None,
        organization_id: Optional[str] = None,
    ) -> None:
        """Force cache invalidation.

        Args:
            user_id: If provided, invalidate only that user's cache.
                     If None, invalidate ALL users' caches.
        """
        if user_id is not None:
            cache_key = self._cache_key(user_id=user_id, organization_id=organization_id)
            self._cache.pop(cache_key, None)
            self._cache_timestamp.pop(cache_key, None)
        else:
            self._cache = {}
            self._cache_timestamp = {}


# =============================================================================
# Singleton
# =============================================================================

_state_manager: Optional[CharacterStateManager] = None


def get_character_state_manager() -> CharacterStateManager:
    """Get or create CharacterStateManager singleton."""
    global _state_manager
    if _state_manager is None:
        _state_manager = CharacterStateManager()
    return _state_manager
