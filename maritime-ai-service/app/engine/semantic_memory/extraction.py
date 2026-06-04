"""
Fact Extraction Module for Semantic Memory
CHỈ THỊ KỸ THUẬT SỐ 25 - Project Restructure

Handles fact extraction from conversations and storage.
Extracted from semantic_memory.py for better modularity.

Requirements: 4.1, 4.2, 4.3
"""
import json
import logging
import re
import unicodedata
from datetime import datetime
from typing import List, Optional

from app.core.config import settings
from app.engine.embedding_runtime import EmbeddingBackendProtocol
from app.engine.llm_pool import get_llm_light
from app.engine.semantic_memory.privacy import (
    hash_memory_identifier,
    memory_log_reference,
)
from app.engine.semantic_memory.write_audit import (
    MemoryWriteScope,
    append_semantic_memory_write_audit_event,
    build_semantic_memory_write_audit,
    resolve_memory_write_scope,
)
from app.services.output_processor import extract_thinking_from_response
from app.models.semantic_memory import (
    ALLOWED_FACT_TYPES,
    FACT_TYPE_MAPPING,
    IGNORED_FACT_TYPES,
    FactType,
    MemoryType,
    SemanticMemoryCreate,
    UserFact,
    UserFactExtraction,
)
from app.repositories.semantic_memory_repository import SemanticMemoryRepository

logger = logging.getLogger(__name__)


def _strip_diacritics(text: str) -> str:
    """Strip Vietnamese diacritics for fuzzy matching."""
    text = text.replace("đ", "d").replace("Đ", "D")
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


# Vietnamese pronouns that are commonly confused with names when diacritics are
# missing. Maps diacritics-stripped lowercase form → canonical diacriticized form.
_VIETNAMESE_PRONOUNS = {
    "minh": "mình", "to": "tớ", "toi": "tôi",
    "em": "em", "anh": "anh", "chi": "chị",
    "ban": "bạn", "cau": "cậu",
}

_EXPLICIT_MEMORY_MARKERS = (
    "ghi nho",
    "hay nho",
    "luu lai",
    "nho rang",
    "remember that",
    "please remember",
    "keep in mind",
)

_SESSION_MEMORY_MARKERS = (
    "for this conversation",
    "for this session",
    "in this conversation",
    "in this session",
    "phien hien tai",
    "trong cuoc tro chuyen nay",
    "trong phien nay",
    "trong session nay",
)

_MEMORY_RECALL_QUESTION_MARKERS = (
    "vua nho ban ghi nho",
    "nho ban ghi nho",
    "ban ghi nho la gi",
    "ban nho la gi",
    "da bao ban nho",
    "minh da nho ban",
    "minh vua nho ban",
    "nho gi",
    "ghi nho gi",
    "what did i ask you to remember",
    "what did you remember",
)

_REPLY_DIRECTIVE_RE = re.compile(
    r"\b(?:trả\s+lời|tra\s+loi|answer\s+only|reply\s+only|respond\s+only)\b",
    flags=re.IGNORECASE,
)

_EXPLICIT_MEMORY_SPLIT_RE = re.compile(
    r"\b(?:hãy\s+ghi\s+nhớ\s+lâu\s+dài\s+rằng|hay\s+ghi\s+nho\s+lau\s+dai\s+rang|"
    r"hãy\s+ghi\s+nhớ\s+rằng|hay\s+ghi\s+nho\s+rang|hãy\s+nhớ\s+rằng|hay\s+nho\s+rang|"
    r"hãy\s+nhớ|hay\s+nho|ghi\s+nhớ|ghi\s+nho|nhớ\s+rằng|nho\s+rang|"
    r"lưu\s+lại|luu\s+lai|remember\s+that|please\s+remember|keep\s+in\s+mind)\b",
    flags=re.IGNORECASE,
)


def _detect_pronoun_as_name(message: str) -> Optional[str]:
    """
    Detect if the message's sentence-initial word is a Vietnamese pronoun
    being used as a self-reference (which LLM might confuse with a name).

    Returns the diacritics-stripped pronoun if detected, else None.

    Common patterns:
      "Minh que Hai Phong"  → "minh" is pronoun "mình"
      "Minh la Hung"        → "minh" is pronoun "mình", "Hung" is the name
      "Toi la sinh vien"    → "toi" is pronoun "tôi"
    """
    stripped = _strip_diacritics(message).lower().split()
    if not stripped:
        return None

    first_word = stripped[0]
    if first_word in _VIETNAMESE_PRONOUNS:
        # Check context: pronoun + verb/location marker = self-reference
        # "Minh que ..." / "Minh la ..." / "Minh cung ..." / "Minh thich ..."
        context_words = {"la", "que", "o", "hoc", "lam", "thich", "cung",
                         "dang", "muon", "can", "co", "khong", "da", "se",
                         "ten", "nam", "nu", "sinh", "hien"}
        if len(stripped) >= 2 and stripped[1] in context_words:
            return first_word
    return None


def _normalize_memory_text(text: str) -> str:
    return " ".join(_strip_diacritics(text).lower().replace("đ", "d").split())


def _has_explicit_memory_marker(normalized_text: str) -> bool:
    return any(marker in normalized_text for marker in _EXPLICIT_MEMORY_MARKERS)


def _is_session_scoped_explicit_memory_request(message: str) -> bool:
    normalized = _normalize_memory_text(message)
    return _has_explicit_memory_marker(normalized) and any(
        marker in normalized for marker in _SESSION_MEMORY_MARKERS
    )


def _is_memory_recall_question(message: str) -> bool:
    normalized = _normalize_memory_text(message)
    if not normalized:
        return False
    has_question_shape = "?" in str(message or "") or " la gi" in normalized or normalized.endswith(" gi")
    if not has_question_shape:
        return False
    if any(marker in normalized for marker in _MEMORY_RECALL_QUESTION_MARKERS):
        return True
    return ("nho" in normalized or "ghi nho" in normalized) and (
        " la gi" in normalized or " gi" in normalized
    )


def _extract_explicit_memory_segment(message: str) -> str:
    before_reply_directive = _REPLY_DIRECTIVE_RE.split(str(message or ""), maxsplit=1)[0].strip()
    if not before_reply_directive:
        return ""
    marker_split = _EXPLICIT_MEMORY_SPLIT_RE.split(before_reply_directive, maxsplit=1)
    if len(marker_split) < 2:
        return ""
    segment = marker_split[-1].strip(" :：.。")
    return re.sub(r"\s+", " ", segment).strip()


def _rule_based_explicit_user_facts(message: str) -> list[UserFact]:
    """Deterministic path for explicit durable-memory writes."""
    normalized = _normalize_memory_text(message)
    if not normalized:
        return []
    if _is_memory_recall_question(message):
        return []
    if _is_session_scoped_explicit_memory_request(message):
        return []
    if not _has_explicit_memory_marker(normalized):
        return []

    segment = _extract_explicit_memory_segment(message)
    if not segment or len(segment) < 4 or len(segment) > 260:
        return []
    if any(marker in segment.lower() for marker in ("```", "<script", "</")):
        return []

    normalized_segment = _normalize_memory_text(segment)
    fact_type = FactType.PREFERENCE
    if any(marker in normalized_segment for marker in ("muc tieu", "goal", "can dat", "muon hoc")):
        fact_type = FactType.GOAL
    elif any(marker in normalized_segment for marker in ("so thich", "thich", "prefer")):
        fact_type = FactType.PREFERENCE
    elif any(marker in normalized_segment for marker in ("quan tam", "interest")):
        fact_type = FactType.INTEREST

    return [
        UserFact(
            fact_type=fact_type,
            value=segment,
            confidence=0.92,
            source_message=message,
        )
    ]


class FactExtractor:
    """
    Handles fact extraction and storage operations.

    Responsibilities:
    - Extract user facts from messages using LLM
    - Store facts with upsert logic
    - Enforce memory caps

    Requirements: 4.1, 4.2, 4.3
    """

    # Sprint 122 (Bug F6): MAX_USER_FACTS now reads from settings
    @property
    def MAX_USER_FACTS(self) -> int:
        """Memory cap — configurable via settings.max_user_facts."""
        return settings.max_user_facts
    
    def __init__(
        self,
        embeddings: EmbeddingBackendProtocol,
        repository: SemanticMemoryRepository,
        llm=None
    ):
        """
        Initialize FactExtractor.
        
        Args:
            embeddings: Semantic embedding backend instance
            repository: SemanticMemoryRepository instance
            llm: Optional LLM for fact extraction
        """
        self._embeddings = embeddings
        self._repository = repository
        self._llm = llm
        logger.debug("FactExtractor initialized")
    
    def _ensure_llm(self):
        """Lazy initialization of LLM for fact extraction."""
        if self._llm is None:
            try:
                # CHỈ THỊ SỐ 28: Use MINIMAL tier (512 tokens) for structured extraction
                self._llm = get_llm_light()
                logger.info("LLM initialized for fact extraction (LIGHT tier - shared pool)")
            except Exception as e:
                logger.warning("Failed to initialize LLM: %s", e)
    
    async def extract_and_store_facts(
        self,
        user_id: str,
        message: str,
        session_id: Optional[str] = None,
        existing_facts: Optional[dict] = None,
        emit_write_audit: bool = True,
    ) -> List[UserFact]:
        """
        Extract user facts from a message using LLM.

        Sprint 73 Enhancement:
        - Passes existing facts to prompt to avoid re-extraction
        - Uses MemoryUpdater for ADD/UPDATE/DELETE/NOOP classification
        - Tracks revisions in metadata
        - Invalidates CoreMemoryBlock cache on changes

        Args:
            user_id: User ID
            message: Message to extract facts from
            session_id: Optional session ID
            existing_facts: Pre-fetched existing facts dict
            emit_write_audit: Whether to emit a fact-extraction write audit

        Returns:
            List of extracted UserFact objects

        Requirements: 4.1, 4.2, 4.3
        """
        audit_scope = resolve_memory_write_scope()
        if not audit_scope.write_allowed:
            await self._append_fact_write_audit(
                user_id=user_id,
                session_id=session_id,
                source_message=message,
                scope=audit_scope,
                write_kind="fact_extraction",
                extract_facts=True,
                stored_fact_count=0,
                status="blocked",
                warnings=["fact_write_blocked_missing_org_context"],
                emit_write_audit=emit_write_audit,
            )
            logger.warning(
                "Fact extraction write blocked for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                audit_scope.state,
            )
            return []

        try:
            extraction = await self.extract_user_facts(
                user_id, message, existing_facts=existing_facts,
            )

            if not extraction.has_facts:
                await self._append_fact_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    source_message=message,
                    scope=audit_scope,
                    write_kind="fact_extraction",
                    extract_facts=True,
                    stored_fact_count=0,
                    status="skipped",
                    emit_write_audit=emit_write_audit,
                )
                return []

            # Store each fact using upsert logic (v0.4)
            stored_facts = []
            for fact in extraction.facts:
                fact_content = fact.to_content()

                # Use upsert method which handles validation, dedup, and capping
                # Sprint 123 (P3): Pass source message for provenance tracking
                success = await self.store_user_fact_upsert(
                    user_id=user_id,
                    fact_content=fact_content,
                    fact_type=fact.fact_type.value,
                    confidence=fact.confidence,
                    session_id=session_id,
                    source_message=message,
                    emit_write_audit=False,
                )

                if success:
                    stored_facts.append(fact)

            if stored_facts:
                # Sprint 73: Invalidate core memory cache on changes
                try:
                    from app.engine.semantic_memory.core_memory_block import get_core_memory_block
                    get_core_memory_block().invalidate(user_id)
                except Exception as _e:
                    logger.debug("CoreMemoryBlock cache invalidation skipped: %s", _e)

                logger.info(
                    "Extracted and stored %d facts for user_hash=%s",
                    len(stored_facts),
                    hash_memory_identifier(user_id),
                )
            await self._append_fact_write_audit(
                user_id=user_id,
                session_id=session_id,
                source_message=message,
                scope=audit_scope,
                write_kind="fact_extraction",
                extract_facts=True,
                stored_fact_count=len(stored_facts),
                status="saved" if stored_facts else "degraded",
                warnings=[] if stored_facts else ["fact_extraction_stored_no_facts"],
                emit_write_audit=emit_write_audit,
            )
            return stored_facts

        except RuntimeError as e:
            # Handle "Event loop is closed" gracefully
            if "Event loop is closed" in str(e):
                logger.warning("Fact extraction skipped (event loop closed): %s", e)
            else:
                logger.error("Fact extraction runtime error: %s", e)
            await self._append_fact_write_audit(
                user_id=user_id,
                session_id=session_id,
                source_message=message,
                scope=audit_scope,
                write_kind="fact_extraction",
                extract_facts=True,
                stored_fact_count=0,
                status="failed",
                warnings=["fact_extraction_failed"],
                emit_write_audit=emit_write_audit,
            )
            return []
        except Exception as e:
            logger.error("Failed to extract facts: %s", e)
            await self._append_fact_write_audit(
                user_id=user_id,
                session_id=session_id,
                source_message=message,
                scope=audit_scope,
                write_kind="fact_extraction",
                extract_facts=True,
                stored_fact_count=0,
                status="failed",
                warnings=["fact_extraction_failed"],
                emit_write_audit=emit_write_audit,
            )
            return []
    
    async def extract_user_facts(
        self,
        user_id: str,
        message: str,
        existing_facts: Optional[dict] = None,
    ) -> UserFactExtraction:
        """
        Use LLM to extract user facts from a message.

        Args:
            user_id: User ID
            message: Message to analyze
            existing_facts: Pre-fetched existing facts dict (Sprint 73)

        Returns:
            UserFactExtraction with extracted facts

        Requirements: 4.1, 4.2
        """
        rule_facts = _rule_based_explicit_user_facts(message)
        if (
            rule_facts
            or _is_session_scoped_explicit_memory_request(message)
            or _is_memory_recall_question(message)
        ):
            return UserFactExtraction(
                facts=rule_facts,
                raw_message=message,
            )

        self._ensure_llm()

        if not self._llm:
            return UserFactExtraction(
                facts=[],
                raw_message=message,
            )

        try:
            prompt = self._build_fact_extraction_prompt(message, existing_facts)
            response = await self._llm.ainvoke(prompt)

            # SOTA FIX: Handle Gemini 2.5 Flash content block format
            text_content, _ = extract_thinking_from_response(response.content)

            # Parse JSON response
            facts = self._parse_fact_extraction_response(text_content, message)
            if not facts:
                facts = rule_facts

            return UserFactExtraction(
                facts=facts,
                raw_message=message
            )

        except Exception as e:
            logger.error("Fact extraction failed: %s", e)
            return UserFactExtraction(
                facts=rule_facts,
                raw_message=message,
            )
    
    async def store_user_fact_upsert(
        self,
        user_id: str,
        fact_content: str,
        fact_type: str = "name",
        confidence: float = 0.9,
        session_id: Optional[str] = None,
        source_message: Optional[str] = None,
        emit_write_audit: bool = True,
    ) -> bool:
        """
        Store or update a user fact using upsert logic.

        v0.4 (CHỈ THỊ 23):
        1. Validate fact_type is in ALLOWED_FACT_TYPES
        2. Check if fact of same type exists
        3. If exists: Update content, embedding, updated_at
        4. If not: Insert new fact
        5. Enforce memory cap (importance-aware eviction, Sprint 122)

        Sprint 123 (P3): Captures source_quote in metadata for provenance.

        Args:
            user_id: User ID
            fact_content: The fact content (e.g., "User's name is Minh")
            fact_type: Type of fact (name, role, level, goal, preference, weakness)
            confidence: Confidence score (0.0 - 1.0)
            session_id: Optional session ID
            source_message: Original user message for provenance tracking
            emit_write_audit: Whether to emit a fact-upsert write audit

        Returns:
            True if storage successful

        **Validates: Requirements 2.1, 2.2, 2.3, 2.4**
        """
        audit_scope = resolve_memory_write_scope()
        if not audit_scope.write_allowed:
            await self._append_fact_write_audit(
                user_id=user_id,
                session_id=session_id,
                source_message=source_message,
                scope=audit_scope,
                write_kind="fact_upsert",
                extract_facts=False,
                stored_fact_count=0,
                status="blocked",
                warnings=["fact_upsert_blocked_missing_org_context"],
                emit_write_audit=emit_write_audit,
            )
            logger.warning(
                "Fact upsert blocked for user_hash=%s: %s",
                hash_memory_identifier(user_id),
                audit_scope.state,
            )
            return False

        try:
            # Step 1: Validate and normalize fact_type
            validated_type = self._validate_fact_type(fact_type)
            if validated_type is None:
                logger.debug("Fact type '%s' is invalid/ignored, skipping storage", fact_type)
                await self._append_fact_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    source_message=source_message,
                    scope=audit_scope,
                    write_kind="fact_upsert",
                    extract_facts=False,
                    stored_fact_count=0,
                    status="skipped",
                    warnings=["fact_type_ignored"],
                    emit_write_audit=emit_write_audit,
                )
                return False

            # Step 2: Generate embedding for the fact when available.
            fact_embedding = []
            try:
                fact_embeddings = await self._embeddings.aembed_documents([fact_content])
                if fact_embeddings and fact_embeddings[0]:
                    fact_embedding = fact_embeddings[0]
            except Exception as exc:
                logger.warning(
                    "Fact embedding unavailable for user_hash=%s; "
                    "continuing without vector: %s",
                    hash_memory_identifier(user_id),
                    exc,
                )

            # Step 3: SOTA - Check for semantic duplicate first
            # Find existing fact with high embedding similarity
            semantic_duplicate = None
            if fact_embedding:
                semantic_duplicate = self._repository.find_similar_fact_by_embedding(
                    user_id=user_id,
                    embedding=fact_embedding,
                    similarity_threshold=settings.fact_similarity_threshold,  # Configurable
                    memory_type=MemoryType.USER_FACT
                )

            metadata = {
                "fact_type": validated_type,
                "confidence": confidence,
                "source": "explicit_save",
            }
            # Sprint 123 (P3): Source quote for provenance
            if source_message:
                metadata["source_quote"] = source_message[:200]
                metadata["extracted_at"] = datetime.utcnow().isoformat()
            
            if semantic_duplicate:
                # SOTA: Update semantically similar fact
                logger.info("Found semantic duplicate for %s, updating...", validated_type)
                if fact_embedding:
                    success = self._repository.update_fact(
                        fact_id=semantic_duplicate.id,
                        content=fact_content,
                        embedding=fact_embedding,
                        metadata=metadata,
                        user_id=user_id,  # Sprint 121 RC-7: defense-in-depth
                    )
                else:
                    success = self._repository.update_fact_preserve_embedding(
                        fact_id=semantic_duplicate.id,
                        content=fact_content,
                        metadata=metadata,
                        user_id=user_id,
                    )
                if success:
                    logger.info(
                        "Updated similar fact for user_hash=%s: type=%s content_ref=%s",
                        hash_memory_identifier(user_id),
                        validated_type,
                        memory_log_reference(fact_content),
                    )
                await self._append_fact_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    source_message=source_message,
                    scope=audit_scope,
                    write_kind="fact_upsert",
                    extract_facts=False,
                    stored_fact_count=1 if success else 0,
                    status="saved" if success else "degraded",
                    warnings=[] if success else ["fact_upsert_not_persisted"],
                    emit_write_audit=emit_write_audit,
                )
                return success
            
            # Step 4: Fallback - Check if fact of same type exists
            existing_fact = self._repository.find_fact_by_type(user_id, validated_type)
            
            if existing_fact:
                # Step 4a: Update existing fact (UPSERT - Update)
                if fact_embedding:
                    success = self._repository.update_fact(
                        fact_id=existing_fact.id,
                        content=fact_content,
                        embedding=fact_embedding,
                        metadata=metadata,
                        user_id=user_id,  # Sprint 121 RC-7: defense-in-depth
                    )
                else:
                    success = self._repository.update_fact_preserve_embedding(
                        fact_id=existing_fact.id,
                        content=fact_content,
                        metadata=metadata,
                        user_id=user_id,
                    )
                if success:
                    logger.info(
                        "Updated user fact for user_hash=%s: type=%s content_ref=%s",
                        hash_memory_identifier(user_id),
                        validated_type,
                        memory_log_reference(fact_content),
                    )
                await self._append_fact_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    source_message=source_message,
                    scope=audit_scope,
                    write_kind="fact_upsert",
                    extract_facts=False,
                    stored_fact_count=1 if success else 0,
                    status="saved" if success else "degraded",
                    warnings=[] if success else ["fact_upsert_not_persisted"],
                    emit_write_audit=emit_write_audit,
                )
                return success
            else:
                # Step 4b: Insert new fact (UPSERT - Insert)
                fact_memory = SemanticMemoryCreate(
                    user_id=user_id,
                    content=fact_content,
                    embedding=fact_embedding,
                    memory_type=MemoryType.USER_FACT,
                    importance=confidence,
                    metadata=metadata,
                    session_id=session_id
                )

                saved_memory = self._repository.save_memory(fact_memory)
                if saved_memory is None:
                    logger.warning(
                        "Failed to persist new fact for user_hash=%s type=%s",
                        hash_memory_identifier(user_id),
                        validated_type,
                    )
                    await self._append_fact_write_audit(
                        user_id=user_id,
                        session_id=session_id,
                        source_message=source_message,
                        scope=audit_scope,
                        write_kind="fact_upsert",
                        extract_facts=False,
                        stored_fact_count=0,
                        status="degraded",
                        warnings=["fact_upsert_not_persisted"],
                        emit_write_audit=emit_write_audit,
                    )
                    return False
                logger.info(
                    "Stored new user fact for user_hash=%s: type=%s content_ref=%s",
                    hash_memory_identifier(user_id),
                    validated_type,
                    memory_log_reference(fact_content),
                )
                
                # Step 5: Enforce memory cap after insert
                await self._enforce_memory_cap(user_id)
                
                await self._append_fact_write_audit(
                    user_id=user_id,
                    session_id=session_id,
                    source_message=source_message,
                    scope=audit_scope,
                    write_kind="fact_upsert",
                    extract_facts=False,
                    stored_fact_count=1,
                    status="saved",
                    emit_write_audit=emit_write_audit,
                )
                return True
            
        except Exception as e:
            logger.error("Failed to store/update user fact: %s", e)
            await self._append_fact_write_audit(
                user_id=user_id,
                session_id=session_id,
                source_message=source_message,
                scope=audit_scope,
                write_kind="fact_upsert",
                extract_facts=False,
                stored_fact_count=0,
                status="failed",
                warnings=["fact_upsert_failed"],
                emit_write_audit=emit_write_audit,
            )
            return False

    async def _append_fact_write_audit(
        self,
        *,
        user_id: str,
        session_id: Optional[str],
        source_message: Optional[str],
        scope: MemoryWriteScope,
        write_kind: str,
        extract_facts: bool,
        stored_fact_count: int,
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
            write_kind=write_kind,
            message_saved=False,
            response_saved=False,
            extract_facts=extract_facts,
            stored_fact_count=stored_fact_count,
            status=status,
            warnings=warnings,
        )
        return await append_semantic_memory_write_audit_event(
            session_id=session_id,
            org_id=scope.org_id,
            payload=audit_payload,
        )
    
    def _validate_fact_type(self, fact_type: str) -> Optional[str]:
        """
        Validate and normalize fact_type.
        
        Args:
            fact_type: Raw fact type string
            
        Returns:
            Normalized fact type or None if invalid/ignored
        """
        # Normalize to lowercase
        normalized = fact_type.lower().strip()
        
        # Check if in ignored types
        if normalized in IGNORED_FACT_TYPES:
            return None
        
        # Check if in allowed types
        if normalized in ALLOWED_FACT_TYPES:
            return normalized
        
        # Check mapping
        if normalized in FACT_TYPE_MAPPING:
            return FACT_TYPE_MAPPING[normalized]
        
        # Default to None (invalid)
        logger.debug("Unknown fact type: %s", fact_type)
        return None
    
    async def _enforce_memory_cap(self, user_id: str) -> int:
        """
        Enforce memory cap using importance-aware eviction.

        Sprint 122 (Bug F5): Replaces FIFO eviction with importance-based.
        Identity facts (name, age) are protected; volatile/low-importance facts
        are evicted first using the Ebbinghaus decay formula.

        Args:
            user_id: User ID

        Returns:
            Number of facts deleted

        **Validates: Requirements 1.1, 1.2, 1.3, 1.4**
        """
        try:
            from app.engine.semantic_memory.importance_decay import (
                calculate_effective_importance_from_timestamps,
            )

            # Get all facts (no dedup, no decay — we need raw data for scoring)
            all_facts = self._repository.get_all_user_facts(user_id)
            current_count = len(all_facts)

            if current_count <= self.MAX_USER_FACTS:
                return 0

            excess = current_count - self.MAX_USER_FACTS

            # Score each fact by effective importance
            scored_facts = []
            for fact in all_facts:
                fact_type = (fact.metadata or {}).get("fact_type", "unknown")
                access_count = (fact.metadata or {}).get("access_count", 0)
                effective = calculate_effective_importance_from_timestamps(
                    base_importance=fact.importance,
                    fact_type=fact_type,
                    last_accessed=(fact.metadata or {}).get("last_accessed"),
                    created_at=fact.created_at,
                    access_count=access_count,
                )
                scored_facts.append((fact, effective))

            # Sort by effective importance ASC (lowest importance first = evict first)
            scored_facts.sort(key=lambda x: x[1])

            # Delete the N lowest-importance facts
            deleted = 0
            for fact, importance in scored_facts[:excess]:
                fact_type = (fact.metadata or {}).get("fact_type", "unknown")
                success = self._repository.delete_memory(user_id, str(fact.id))
                if success:
                    deleted += 1
                    logger.info(
                        "Evicted low-importance fact for user_hash=%s: type=%s, "
                        "effective_importance=%.3f, content_ref=%s",
                        hash_memory_identifier(user_id),
                        fact_type,
                        importance,
                        memory_log_reference(fact.content),
                    )

            if deleted > 0:
                logger.info(
                    "Memory cap enforced for user_hash=%s: evicted %d facts by importance "
                    "(was %d, now %d)",
                    hash_memory_identifier(user_id),
                    deleted,
                    current_count,
                    current_count - deleted,
                )

            return deleted

        except Exception as e:
            logger.error("Failed to enforce memory cap: %s", e)
            return 0
    
    def _build_fact_extraction_prompt(
        self, message: str, existing_facts: Optional[dict] = None,
    ) -> str:
        """
        Build prompt for fact extraction.

        Sprint 73: Enhanced Mem0-style prompt with 15 categories and
        existing facts context to avoid re-extraction and detect changes.
        """
        if settings.enable_enhanced_extraction:
            return self._build_enhanced_prompt(message, existing_facts)

        # Legacy 6-type prompt (fallback)
        return self._build_legacy_prompt(message)

    def _build_legacy_prompt(self, message: str) -> str:
        """Legacy 6-type extraction prompt (pre-Sprint 73)."""
        pronoun_warning = ""
        detected = _detect_pronoun_as_name(message)
        if detected:
            canonical = _VIETNAMESE_PRONOUNS[detected]
            pronoun_warning = (
                f'\nWARNING: "{detected}" at sentence start is Vietnamese pronoun '
                f'"{canonical}" (= "I/me"), NOT a person\'s name. Do NOT extract as name.\n'
            )

        return f"""Analyze the following message and extract any personal facts about the user.
Return a JSON array of facts. Each fact should have:
- fact_type: one of [name, preference, goal, background, weak_area, strong_area, interest, learning_style]
- value: the actual fact
- confidence: confidence score from 0.0 to 1.0

If no facts are found, return an empty array: []

Message: "{message}"
{pronoun_warning}
IMPORTANT: Vietnamese pronouns are NOT names:
  "mình/minh", "tớ/to", "tôi/toi", "em", "anh", "chị/chi" = "I/me"
  Only extract name when pattern is: "tên là X", "mình là X", "tôi là X"

Examples of facts to extract:
- User's name ONLY with explicit pattern: "Tên mình là Hùng" -> name: "Hùng", "Tôi là Lan" -> name: "Lan"
- "Minh que Hai Phong" -> background: "quê Hải Phòng" (⚠️ "Minh" = pronoun "mình", NOT a name!)
- Learning goals ("Tôi muốn học về COLREGs" -> goal: "học về COLREGs")
- Professional background ("Tôi là thuyền trưởng" -> background: "thuyền trưởng")
- Conversational questions ("mình vừa hỏi gì?" / "bạn nhớ gì về tôi?") -> [] (NO facts to extract)
- Interests ("Tôi quan tâm đến an toàn hàng hải" -> interest: "an toàn hàng hải")

Return ONLY valid JSON, no explanation:"""

    def _build_enhanced_prompt(
        self, message: str, existing_facts: Optional[dict] = None,
    ) -> str:
        """
        Sprint 73: Enhanced Mem0-style extraction prompt.

        15 categories across 6 groups. Passes existing facts to LLM
        so it avoids re-extracting known info and detects contradictions.
        """
        existing_block = ""
        if existing_facts:
            lines = [f"  - {k}: {v}" for k, v in existing_facts.items() if v]
            if lines:
                existing_block = (
                    "Thông tin ĐÃ BIẾT về user (KHÔNG trích xuất lại nếu giống hệt):\n"
                    + "\n".join(lines) + "\n\n"
                )

        # Detect Vietnamese pronoun that might be confused with a name
        pronoun_warning = ""
        detected = _detect_pronoun_as_name(message)
        if detected:
            canonical = _VIETNAMESE_PRONOUNS[detected]
            pronoun_warning = (
                f'\nCẢNH BÁO: Từ "{detected}" ở đầu câu là ĐẠI TỪ NHÂN XƯNG '
                f'tiếng Việt "{canonical}" (nghĩa là "tôi/I"), KHÔNG PHẢI tên người. '
                f"KHÔNG trích xuất nó làm name.\n"
            )

        return f"""Bạn là Personal Information Organizer. Phân tích tin nhắn và trích xuất thông tin cá nhân.

{existing_block}Tin nhắn: "{message}"
{pronoun_warning}
Trả về JSON array. Mỗi fact có:
- fact_type: MỘT trong [name, age, hometown, role, level, location, organization, goal, preference, weakness, strength, learning_style, hobby, interest, emotion, recent_topic]
- value: giá trị cụ thể, đầy đủ (VD: "Hải Phòng" chứ không phải "HP")
- confidence: 0.0-1.0

QUY TẮC:
1. CHỈ trích xuất thông tin ĐƯỢC NÊU RÕ RÀNG trong tin nhắn
2. KHÔNG suy luận hoặc đoán
3. Nếu thông tin đã biết VÀ GIỐNG HỆT → không trích xuất lại
4. Nếu thông tin đã biết NHƯNG KHÁC → trích xuất giá trị MỚI (sẽ cập nhật)
5. confidence >= 0.8 cho thông tin rõ ràng, 0.5-0.7 cho thông tin ngầm hiểu
6. Câu có NHIỀU thông tin → trích xuất TỪNG fact RIÊNG BIỆT.
   VD: "Mình quê Hải Phòng, có con mèo tên Bông" → 2 facts: location + hobby
7. ĐẠI TỪ NHÂN XƯNG tiếng Việt KHÔNG PHẢI tên người:
   "mình/minh", "tớ/to", "tôi/toi", "em", "anh", "chị/chi", "bạn/ban", "cậu/cau"
   VD: "Minh que Hai Phong" → "Minh" = đại từ "mình", KHÔNG phải name.
   Chỉ trích xuất name khi có cấu trúc rõ ràng: "tên là X", "mình là X", "tôi là X"

6 NHÓM:
  Danh tính: name (tên), age (tuổi), hometown (quê quán — cố định, VD: "Hải Phòng")
  Nghề nghiệp: role (vai trò), level (cấp bậc), location (nơi ở/làm việc HIỆN TẠI — VD: "đang ở Cát Lái"), organization (tổ chức/trường)
  Học tập: goal (mục tiêu), preference (sở thích học), weakness (điểm yếu), strength (điểm mạnh), learning_style (phong cách)
  Cá nhân: hobby (sở thích, thú cưng, VD: "nuôi mèo tên Bông"), interest (quan tâm: thể thao, âm nhạc, chuyên môn, VD: "MU", "guitar")
  Cảm xúc: emotion (tâm trạng hiện tại)
  Ngữ cảnh: recent_topic (chủ đề đang thảo luận)

VÍ DỤ:
  "Tên mình là Hùng, 25 tuổi, kỹ sư ở SG" → [name:Hùng, age:25, role:kỹ sư, location:Sài Gòn]
  "Tôi là Lan" → [name:Lan]
  "Minh que Hai Phong" → [hometown:Hải Phòng] (⚠️ "Minh" = đại từ "mình", KHÔNG trích xuất name!)
  "Minh cung thich choi bong da" → [hobby:bóng đá] (⚠️ "Minh" = đại từ "mình", KHÔNG trích xuất name!)
  "Mình quê Hải Phòng, đang neo tàu ở Cát Lái" → [hometown:Hải Phòng, location:Cát Lái] (KHÔNG có name!)
  "Mình quê Hải Phòng, có con mèo tên Bông" → [hometown:Hải Phòng, hobby:nuôi mèo tên Bông] (KHÔNG có name!)
  "Mình thích đọc sách về AI" → [hobby:đọc sách về AI]
  "Hôm nay mình hơi buồn vì thi trượt" → [emotion:buồn, weakness:thi trượt]
  "Em là sinh viên năm 3 trường Hàng hải, muốn thi Đại phó" → [role:sinh viên năm 3, organization:trường Hàng hải, goal:thi Đại phó]
  "mình vừa hỏi gì?" → [] (câu hỏi hội thoại, KHÔNG có thông tin cá nhân)
  "bạn nhớ tên tôi không?" → [] (câu hỏi, KHÔNG trích xuất gì)

Nếu không có thông tin mới, trả về: []
{self._build_adaptive_preference_block()}
Return ONLY valid JSON:"""
    
    def _build_adaptive_preference_block(self) -> str:
        """
        Sprint 219: Build behavioral inference rules block for adaptive preference learning.

        When enable_adaptive_preferences=True, adds rules that instruct the LLM to infer
        learning preferences from conversation behavior patterns (not just explicit statements).
        """
        if not settings.enable_adaptive_preferences:
            return ""

        return """
SUY LUẬN HÀNH VI (tự động nhận biết từ cách user tương tác):
- Nếu user hay xin ví dụ/tương tự → fact_type="learning_style", value="trực quan/ví dụ minh họa"
- Nếu user yêu cầu từng bước → fact_type="learning_style", value="có cấu trúc/tuần tự"
- Nếu user hỏi "tại sao" sâu → fact_type="learning_style", value="khái niệm/chuyên sâu"
- Nếu user gặp khó khăn với chủ đề → fact_type="weakness", value="{chủ đề}"
- Nếu user trả lời nhanh/đúng về chủ đề → fact_type="strength", value="{chủ đề}"
- Nếu user thích câu trả lời ngắn gọn → fact_type="preference", value="trả lời ngắn gọn"
- Nếu user thích giải thích chi tiết → fact_type="preference", value="giải thích chi tiết"
- Nếu user hay hỏi lại/nhờ giải thích lại → fact_type="preference", value="cần giải thích nhiều lần"
- Nếu user thích so sánh/đối chiếu → fact_type="learning_style", value="so sánh/đối chiếu"
Lưu ý: Chỉ suy luận khi HÀNH VI RÕ RÀNG trong tin nhắn, confidence 0.5-0.7 cho suy luận hành vi.
"""

    def _parse_fact_extraction_response(
        self,
        response: str,
        original_message: str
    ) -> List[UserFact]:
        """Parse LLM response into UserFact objects."""
        try:
            # Clean response - extract JSON
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
            
            # Parse JSON
            facts_data = json.loads(response)
            
            if not isinstance(facts_data, list):
                return []
            
            facts = []
            for item in facts_data:
                try:
                    fact_type = FactType(item.get("fact_type", "").lower())
                    value = item.get("value", "")
                    confidence = float(item.get("confidence", 0.8))
                    
                    if value:
                        facts.append(UserFact(
                            fact_type=fact_type,
                            value=value,
                            confidence=min(max(confidence, 0.0), 1.0),
                            source_message=original_message
                        ))
                except (ValueError, KeyError) as e:
                    logger.debug("Skipping invalid fact: %s", e)
                    continue
            
            return facts
            
        except json.JSONDecodeError as e:
            logger.warning("Failed to parse fact extraction response: %s", e)
            return []
