"""Pure helper routines extracted from the supervisor shell."""

from __future__ import annotations

import re
from typing import Any, Optional

from app.engine.multi_agent.supervisor_hint_runtime import (
    _looks_visual_followup_request_impl,
    _normalize_router_text_impl,
)
from app.engine.multi_agent.direct_reasoning import _is_codebase_analysis_query


def _domain_keyword_matches(keyword: str, normalized_query: str) -> bool:
    """Word-boundary match for domain keywords.

    Avoids false positives where a short keyword appears inside an unrelated
    word — e.g. ``gio`` (gió/wind) matching inside ``gioi`` (giới/world)
    in ``the gioi`` (thế giới), which previously misrouted news queries to RAG.
    """
    if not keyword:
        return False
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", normalized_query) is not None

_HOST_UI_ACTION_MARKERS = (
    "bam",
    "button",
    "chi cho",
    "click",
    "cuon",
    "di toi",
    "dua toi",
    "highlight",
    "mo",
    "navigate",
    "nhan vao",
    "nut",
    "o dau",
    "open",
    "scroll",
    "show",
    "show me",
    "tro toi",
    "where",
)

_HOST_UI_SURFACE_MARKERS = (
    "browse courses",
    "chat",
    "dashboard",
    "giao dien",
    "ho so",
    "kham pha",
    "khoa hoc cua toi",
    "lesson",
    "menu",
    "my courses",
    "nut gui",
    "profile",
    "send button",
    "sidebar",
    "tab",
    "tiep tuc hoc",
    "tong quan trang",
    "trang nay",
)

_HOST_UI_EXPLICIT_MARKERS = (
    "@wiii-pointy",
    "con tro",
    "cursor",
    "dung pointy",
    "host action",
    "pointy mode",
    "ui highlight",
    "ui scroll",
    "ui tour",
    "wiii pointy",
)

_HOST_UI_POINTY_NEGATION_PATTERNS = (
    r"\bkhong\s+(?:can\s+)?(?:su\s+dung|dung|goi|kich\s+hoat|bat)\s+@?wiii[-\s]?pointy\b",
    r"\bdung\s+(?:su\s+dung|dung|goi|kich\s+hoat|bat)\s+@?wiii[-\s]?pointy\b",
    r"\b(?:khong|dung)\s+pointy\b",
    r"\b(?:no|without)\s+pointy\b",
    r"\bdo\s+not\s+use\s+pointy\b",
    r"\bdon'?t\s+use\s+pointy\b",
)

_OBVIOUS_MARITIME_LOOKUP_MARKERS = (
    "colreg",
    "colregs",
    "gmdss",
    "imdg",
    "imsbc",
    "ism code",
    "isps",
    "marpol",
    "mlc",
    "solas",
    "stcw",
)

_OBVIOUS_MARITIME_LOOKUP_BLOCKERS = (
    "explain",
    "giai thich",
    "giang giai",
    "huong dan",
    "latest",
    "moi nhat",
    "news",
    "phan tich",
    "search web",
    "teach",
    "tim tren internet",
    "tim tren mang",
    "tim tren web",
    "tin moi",
    "tin tuc",
    "web search",
)

_SOURCE_BACKED_LOOKUP_MARKERS = (
    "according to",
    "can cu",
    "cite",
    "citation",
    "citations",
    "co dan nguon",
    "co nguon",
    "dan nguon",
    "dua tren tai lieu",
    "knowledge source",
    "nguon",
    "reference",
    "references",
    "source",
    "sources",
    "source-backed",
    "tai lieu noi gi",
    "theo nguon",
    "theo tai lieu",
    "trich dan",
)

_EXPLICIT_WEB_SEARCH_MARKERS = (
    "@web-search",
    "@web_search",
    "look up online",
    "search the web",
    "tim kiem tren mang",
    "tim tren internet",
    "tim tren mang",
    "tim tren web",
    "tra cuu tren mang",
    "tra cuu tren web",
    "web search",
)


def _contains_any_marker(normalized_query: str, markers: tuple[str, ...]) -> bool:
    return any(marker in normalized_query for marker in markers)


def _contains_phrase(normalized_query: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", normalized_query or "") is not None


def _contains_any_phrase(normalized_query: str, markers: tuple[str, ...]) -> bool:
    return any(_contains_phrase(normalized_query, marker) for marker in markers)


def _negates_host_ui_pointy(normalized_query: str) -> bool:
    query = normalized_query or ""
    if not query:
        return False
    return any(re.search(pattern, query) is not None for pattern in _HOST_UI_POINTY_NEGATION_PATTERNS)


def _looks_host_ui_navigation_turn(normalized_query: str) -> bool:
    """Detect obvious host UI guidance prompts without stealing learning turns."""
    query = normalized_query or ""
    if not query:
        return False
    if _negates_host_ui_pointy(query):
        return False
    if _contains_any_phrase(query, _HOST_UI_EXPLICIT_MARKERS):
        return True
    return _contains_any_phrase(query, _HOST_UI_ACTION_MARKERS) and _contains_any_phrase(
        query,
        _HOST_UI_SURFACE_MARKERS,
    )


def _looks_obvious_maritime_lookup_turn(normalized_query: str) -> bool:
    """Detect clearly source-backed maritime regulation lookups without LLM routing."""
    query = normalized_query or ""
    if not query:
        return False
    if _contains_any_marker(query, _OBVIOUS_MARITIME_LOOKUP_BLOCKERS):
        return False
    if _contains_any_marker(query, _OBVIOUS_MARITIME_LOOKUP_MARKERS):
        return True
    return re.search(r"\brule\s+\d+[a-z]?\b", query) is not None or re.search(
        r"\bquy\s*tac\s+\d+[a-z]?\b",
        query,
    ) is not None


def _looks_colreg_rule_explanation_turn(normalized_query: str) -> bool:
    query = normalized_query or ""
    if not query:
        return False
    has_colreg = "colreg" in query or "colregs" in query
    has_rule_number = re.search(r"\brule\s+\d+[a-z]?\b", query) is not None or re.search(
        r"\bquy\s*tac\s+\d+[a-z]?\b",
        query,
    ) is not None
    return has_colreg and has_rule_number


def _looks_source_backed_domain_lookup_turn(normalized_query: str) -> bool:
    """Route citation/source-backed domain questions to RAG before LLM routing.

    This guard is intentionally narrower than the generic maritime lookup
    heuristic: it only catches prompts that explicitly ask Wiii to ground the
    answer in a source/citation and that contain a maritime regulation marker.
    Web/latest requests stay out so the web-search lane can handle them.
    """
    query = normalized_query or ""
    if not query:
        return False
    if _looks_explicit_web_search_turn(query):
        return False
    if _contains_any_marker(query, ("latest", "moi nhat", "news", "tin moi", "tin tuc")):
        return False

    has_domain_marker = _contains_any_marker(
        query,
        _OBVIOUS_MARITIME_LOOKUP_MARKERS,
    ) or re.search(r"\brule\s+\d+[a-z]?\b", query) is not None or re.search(
        r"\bquy\s*tac\s+\d+[a-z]?\b",
        query,
    ) is not None
    if not has_domain_marker:
        return False
    return _contains_any_marker(query, _SOURCE_BACKED_LOOKUP_MARKERS)


def _looks_explicit_web_search_turn(normalized_query: str) -> bool:
    """Detect user-explicit web lookup turns that should not wait for router LLM."""
    query = normalized_query or ""
    if not query:
        return False
    if _contains_any_marker(query, _EXPLICIT_WEB_SEARCH_MARKERS):
        return True
    return "web" in query and any(marker in query for marker in ("search", "tim", "tra cuu"))


_MEMORY_WRITE_MARKERS = (
    "ghi nho",
    "ghi nhan",
    "hay nho",
    "keep in mind",
    "luu lai",
    "luu y",
    "nho tam",
    "nho trong",
    "nho cho toi",
    "nho giup",
    "nho rang",
    "note that",
    "please remember",
    "remember that",
    "remember this",
)

_SESSION_MEMORY_SCOPE_MARKERS = (
    "bao cao sap toi",
    "cho bao cao",
    "cho bao cao sap toi",
    "cho phien nay",
    "for this conversation",
    "for this session",
    "hom nay",
    "in this conversation",
    "in this session",
    "ma kiem thu",
    "marker wiii",
    "phien hien tai",
    "phien nay",
    "today",
    "trong cuoc tro chuyen nay",
    "trong doan chat nay",
    "trong phien nay",
    "trong session nay",
    "wiii-report",
)

_MEMORY_ACK_ONLY_MARKERS = (
    "answer only",
    "chi xac nhan",
    "chi tra loi",
    "just answer",
    "only answer",
    "respond only",
    "reply only",
    "tra loi chi",
    "tra loi dung",
)

_SESSION_MEMORY_RECALL_MARKERS = (
    "ban nho 3 uu tien",
    "ban nho nhung uu tien",
    "ban vua nho",
    "hoi nay minh bao ban nho",
    "hoi nay minh noi",
    "minh vua bao",
    "minh vua bao ban nho",
    "minh vua noi",
    "minh vua noi ban nho",
    "nhac lai 3 uu tien",
    "nhac lai 3 anchor",
    "nhac lai dung 3 anchor",
    "nhac lai 5 tieu chi",
    "nhac lai chinh xac",
    "nhac lai dieu minh vua noi",
    "nhac lai dung",
    "nhac lai nhung uu tien",
    "recall the priorities",
    "what did i just say",
    "what did i just tell you",
    "what did i ask you to remember",
)

_SESSION_MEMORY_RECALL_VERB_MARKERS = (
    "ban nho",
    "nhac lai",
    "noi lai",
    "recall",
    "repeat",
)

_SESSION_MEMORY_RECALL_CONTEXT_MARKERS = (
    "3 tieu chi",
    "3 anchor",
    "3 neo",
    "3 moc",
    "3 uu tien",
    "5 tieu chi",
    "bieu tuong neo",
    "bo tieu chi",
    "cac anchor",
    "cac neo",
    "cac moc",
    "da ghi",
    "hoi nay",
    "ma bao cao",
    "ma kiem thu",
    "marker",
    "mau bao cao",
    "mau neo",
    "moc neo",
    "neo",
    "tieu chi nghiem thu",
    "trong phien",
    "vua nay",
    "vua roi",
    "wiii-report",
)

_WIII_PIPELINE_META_MARKERS = (
    "pipeline",
    "sai route",
    "route sai",
    "routing",
    "test hieu suat",
    "kiem thu thuc te",
    "core",
    "flow",
    "logic",
    "luong",
    "route",
    "ux ui",
)

_WIII_PIPELINE_SURFACE_MARKERS = (
    "pointy",
    "thinking",
    "memory",
    "conversation",
    "cursor",
    "wiii",
)

_REASONING_SAFETY_MARKERS = (
    "chain of thought",
    "chain-of-thought",
    "developer instruction",
    "developer instructions",
    "hidden reasoning",
    "internal reasoning",
    "reasoning tho",
    "raw reasoning",
    "system prompt",
    "visible thinking",
)

_REASONING_SAFETY_CONTEXT_MARKERS = (
    "an toan",
    "cong khai",
    "noi bo",
    "noi tai",
    "khong lo",
    "khong nhac",
    "khong dung cong cu",
    "policy",
    "safety",
)

_WIII_CAPABILITY_INVENTORY_MARKERS = (
    "co lam duoc",
    "co xu ly duoc",
    "co tao duoc",
    "co ho tro",
    "hien xu ly duoc",
    "toi muc nao",
    "den muc nao",
    "muc nao",
    "kha nang",
    "nang luc",
    "chuc nang",
    "capability",
    "lam duoc nhung gi",
    "xu ly duoc gi",
    "ho tro gi",
)

_WIII_CAPABILITY_SURFACE_MARKERS = (
    "anh dau vao",
    "hinh anh",
    "tao anh",
    "image",
    "vision",
    "file word",
    "word",
    "docx",
    "file excel",
    "excel",
    "xlsx",
    "video",
    "file",
)

_SELF_FEELING_PROBE_MARKERS = (
    "ban buon khong",
    "ban co buon khong",
    "ban co thay buon khong",
    "ban biet buon khong",
    "wiii buon khong",
    "wiii co buon khong",
    "cau buon khong",
    "an buon khong",
)


def _looks_memory_write_turn(normalized_query: str) -> bool:
    """Detect explicit memory-write directives without matching bare ``nho``."""
    query = normalized_query or ""
    if not query:
        return False
    return any(_contains_phrase(query, marker) for marker in _MEMORY_WRITE_MARKERS)


def _looks_session_memory_write_turn(normalized_query: str) -> bool:
    """Detect notes scoped to the current chat/session, not durable profile facts."""
    query = normalized_query or ""
    if not query:
        return False
    return _looks_memory_write_turn(query) and any(
        _contains_phrase(query, marker) for marker in _SESSION_MEMORY_SCOPE_MARKERS
    )


def _looks_memory_ack_only_turn(normalized_query: str) -> bool:
    query = normalized_query or ""
    if not query:
        return False
    return _looks_memory_write_turn(query) and any(
        _contains_phrase(query, marker) for marker in _MEMORY_ACK_ONLY_MARKERS
    )


def _looks_session_memory_ack_only_turn(normalized_query: str) -> bool:
    query = normalized_query or ""
    if not query:
        return False
    return _looks_session_memory_write_turn(query) and any(
        _contains_phrase(query, marker) for marker in _MEMORY_ACK_ONLY_MARKERS
    )


def _looks_session_memory_recall_turn(normalized_query: str) -> bool:
    """Detect current-session recall turns so they do not hit durable memory."""
    query = normalized_query or ""
    if not query:
        return False
    if any(_contains_phrase(query, marker) for marker in _SESSION_MEMORY_RECALL_MARKERS):
        return True
    has_recall_verb = any(
        _contains_phrase(query, marker) for marker in _SESSION_MEMORY_RECALL_VERB_MARKERS
    )
    has_session_context = any(
        _contains_phrase(query, marker) for marker in _SESSION_MEMORY_RECALL_CONTEXT_MARKERS
    )
    return has_recall_verb and has_session_context


def _looks_wiii_pipeline_meta_turn(normalized_query: str) -> bool:
    """Detect internal Wiii pipeline/UX analysis turns for direct prose."""
    query = re.sub(r"\[[^\]]+\]", " ", normalized_query or "")
    if not query:
        return False
    if _looks_session_memory_write_turn(query) or _looks_session_memory_recall_turn(query):
        return False
    surface_hits = sum(1 for marker in _WIII_PIPELINE_SURFACE_MARKERS if _contains_phrase(query, marker))
    explicit_meta = any(
        _contains_phrase(query, marker) for marker in _WIII_PIPELINE_META_MARKERS
    )
    if not explicit_meta or surface_hits < 1:
        return False
    diagnostic_markers = (
        "danh gia",
        "fix",
        "kiem tra",
        "kiem thu",
        "loi",
        "phai",
        "phan tich",
        "sai",
        "sua",
        "tai sao",
        "test",
        "vi sao",
    )
    return any(_contains_phrase(query, marker) for marker in diagnostic_markers)


def _looks_reasoning_safety_meta_turn(normalized_query: str) -> bool:
    """Detect public questions about visible thinking vs private reasoning.

    These turns are product/safety meta questions. They should never be routed
    through tutoring, visual generation, or raw LLM tool paths just because the
    user says "khác nhau" or asks to reveal hidden prompts.
    """
    query = normalized_query or ""
    if not query:
        return False
    if any(_contains_phrase(query, marker) for marker in _REASONING_SAFETY_MARKERS):
        return True
    return _contains_phrase(query, "thinking") and any(
        _contains_phrase(query, marker) for marker in _REASONING_SAFETY_CONTEXT_MARKERS
    )


def _looks_wiii_capability_inventory_turn(normalized_query: str) -> bool:
    """Detect questions asking what Wiii can actually do, not requests to do it."""
    query = normalized_query or ""
    if not query:
        return False
    surface_hits = sum(
        1
        for marker in _WIII_CAPABILITY_SURFACE_MARKERS
        if _contains_phrase(query, marker)
    )
    if surface_hits <= 0:
        return False
    has_inventory_shape = any(
        _contains_phrase(query, marker)
        for marker in _WIII_CAPABILITY_INVENTORY_MARKERS
    )
    if not has_inventory_shape:
        return False
    if surface_hits >= 2:
        return True
    return any(
        _contains_phrase(query, marker)
        for marker in ("wiii", "ban", "khong", "hien tai")
    )


def _looks_self_feeling_probe_turn(normalized_query: str) -> bool:
    """Detect short questions about Wiii's own feeling state."""
    query = normalized_query or ""
    if not query:
        return False
    token_count = len([token for token in query.split() if token])
    if token_count > 24:
        return False
    return any(_contains_phrase(query, marker) for marker in _SELF_FEELING_PROBE_MARKERS)


def resolve_house_routing_provider_impl(
    state: Any,
    *,
    settings_obj: Any,
    logger: Any,
) -> Optional[str]:
    """Pick the best currently-runnable provider for house routing."""
    from app.engine.llm_pool import LLMPool

    primary = str(settings_obj.llm_provider or "google").strip().lower()
    try:
        from app.services.llm_selectability_service import choose_best_runtime_provider

        best = choose_best_runtime_provider(
            preferred_provider=primary,
            provider_order=LLMPool._get_request_provider_chain(),
            allow_degraded_fallback=False,
        )
        selected = str(best.provider or "").strip().lower() if best is not None else ""
        if selected:
            if selected != primary:
                logger.info(
                    "[SUPERVISOR] House routing switched from %s to selectable %s",
                    primary,
                    selected,
                )
            return selected
    except Exception as exc:
        logger.debug("[SUPERVISOR] Selectability-aware routing provider skipped: %s", exc)

    provider = LLMPool._providers.get(primary)
    if provider and provider.is_available():
        return primary
    for name in LLMPool._get_provider_chain():
        current = LLMPool._providers.get(name)
        if current and current.is_available():
            logger.info("[SUPERVISOR] Primary %s unavailable, using %s", primary, name)
            return name
    return primary


def get_domain_keywords_impl(
    *,
    domain_config: dict | None,
    context: dict | None = None,
    logger: Any,
    settings_obj: Any,
) -> list[str]:
    """Extract domain routing keywords from config or registry fallback."""
    domain_keywords: list[str] = []
    if domain_config and domain_config.get("routing_keywords"):
        for kw_group in domain_config["routing_keywords"]:
            domain_keywords.extend(
                keyword.strip().lower() for keyword in kw_group.split(",")
            )

    if not domain_keywords:
        try:
            from app.domains.registry import get_domain_registry

            registry = get_domain_registry()
            domain = registry.get(settings_obj.default_domain)
            if domain:
                config = domain.get_config()
                domain_keywords = [
                    keyword.lower() for keyword in (config.routing_keywords or [])
                ]
        except Exception as exc:
            logger.debug("Failed to load domain keywords: %s", exc)

    return domain_keywords


def validate_domain_routing_impl(
    *,
    query: str,
    chosen_agent: str,
    domain_config: dict | None,
    context: dict | None = None,
    rag_agent_name: str,
    tutor_agent_name: str,
    direct_agent_name: str,
    get_domain_keywords_fn: Any,
    logger: Any,
) -> str:
    """Ensure domain-routed turns still show a real domain signal."""
    if chosen_agent not in (rag_agent_name, tutor_agent_name):
        return chosen_agent

    if chosen_agent == tutor_agent_name and _looks_visual_followup_request_impl(query):
        logger.info(
            "[SUPERVISOR] Tutor visual follow-up keep: %s (do not demote short visual continuation to direct)",
            chosen_agent,
        )
        return chosen_agent

    from app.core.config import settings as runtime_settings

    if runtime_settings.enable_org_knowledge:
        from app.core.org_context import get_current_org_id

        if get_current_org_id():
            logger.info(
                "[SUPERVISOR] Org knowledge bypass: keeping %s (org context present, org_knowledge enabled)",
                chosen_agent,
            )
            return chosen_agent

    domain_keywords = get_domain_keywords_fn(domain_config)
    if not domain_keywords:
        return chosen_agent

    query_lower = _normalize_router_text_impl(query)
    normalized_domain_keywords = [
        _normalize_router_text_impl(str(keyword or ""))
        for keyword in domain_keywords
        if str(keyword or "").strip()
    ]
    has_domain = any(keyword and keyword in query_lower for keyword in normalized_domain_keywords)
    if not has_domain:
        context_parts: list[str] = []
        summary = str((context or {}).get("conversation_summary") or "").strip()
        if summary:
            context_parts.append(_normalize_router_text_impl(summary))

        for message in ((context or {}).get("langchain_messages") or [])[-6:]:
            content = getattr(message, "content", message)
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        text = block.get("text") or block.get("content") or ""
                        if text:
                            context_parts.append(_normalize_router_text_impl(str(text)))
                    elif block:
                        context_parts.append(_normalize_router_text_impl(str(block)))
            elif content:
                context_parts.append(_normalize_router_text_impl(str(content)))

        context_blob = "\n".join(context_parts)
        has_contextual_domain = any(
            keyword and keyword in context_blob for keyword in normalized_domain_keywords
        )
        has_learning_followup = (
            chosen_agent == tutor_agent_name
            and _looks_visual_followup_request_impl(query)
            and any(
                marker in context_blob
                for marker in (
                    "giai thich",
                    "nguoi hoc",
                    "quy tac",
                    "rule ",
                    "colregs",
                    "solas",
                    "marpol",
                    "cat huong",
                    "tranh va",
                    "nhuong duong",
                )
            )
        )
        if has_learning_followup:
            logger.info(
                "[SUPERVISOR] Learning visual follow-up keep: %s (recent learning context carries tutor continuity)",
                chosen_agent,
            )
            return chosen_agent
        if has_contextual_domain:
            logger.info(
                "[SUPERVISOR] Domain continuity keep: %s (recent context carries domain signal)",
                chosen_agent,
            )
            return chosen_agent
        logger.info(
            "[SUPERVISOR] Domain validation override: %s → direct (no domain keywords in query)",
            chosen_agent,
        )
        return direct_agent_name
    return chosen_agent


def is_complex_query_impl(
    *,
    query: str,
    routing_metadata: dict,
    min_length: int,
    mixed_intent_pairs: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> bool:
    """Heuristic: does this query benefit from parallel dispatch?"""
    if len(query) < min_length:
        return False

    query_lower = query.lower()
    for lookup_kw, learning_kw in mixed_intent_pairs:
        if lookup_kw in query_lower and learning_kw in query_lower:
            return True

    confidence = routing_metadata.get("confidence", 1.0)
    return confidence < 0.75 and len(query) > 120


def conservative_fast_route_impl(
    *,
    query: str,
    normalize_router_text_fn: Any,
    classify_fast_chatter_turn_fn: Any,
    looks_clear_social_fn: Any,
    direct_agent_name: str,
    memory_agent_name: str | None = None,
    rag_agent_name: str | None = None,
    code_studio_agent_name: str | None = None,
    needs_code_studio_fn: Any | None = None,
) -> tuple[str, str, float, str] | None:
    """Route only the most obvious turns without invoking the supervisor LLM."""
    normalized = normalize_router_text_fn(query)

    fast_chatter = classify_fast_chatter_turn_fn(query)
    if fast_chatter is not None:
        intent, chatter_kind = fast_chatter
        reasoning = (
            "obvious social turn"
            if chatter_kind == "social"
            else f"obvious {chatter_kind.replace('_', ' ')} turn"
        )
        return (direct_agent_name, intent, 1.0, reasoning)

    if looks_clear_social_fn(normalized):
        return (direct_agent_name, "social", 1.0, "obvious social turn")

    if _looks_session_memory_recall_turn(normalized):
        return (
            direct_agent_name,
            "personal",
            1.0,
            "obvious session memory recall turn",
        )

    if _looks_session_memory_write_turn(normalized):
        return (
            direct_agent_name,
            "personal",
            1.0,
            "obvious session-scoped memory write turn",
        )

    if memory_agent_name and _looks_memory_write_turn(normalized):
        return (
            memory_agent_name,
            "personal",
            1.0,
            "obvious memory write turn",
        )

    if _looks_explicit_web_search_turn(normalized):
        return (
            direct_agent_name,
            "web_search",
            1.0,
            "obvious explicit web search turn",
        )

    if _looks_self_feeling_probe_turn(normalized):
        return (
            direct_agent_name,
            "selfhood",
            1.0,
            "obvious Wiii self-feeling probe turn",
        )

    if _is_codebase_analysis_query(normalized):
        return (
            direct_agent_name,
            "analysis",
            1.0,
            "obvious codebase/source-backed analysis turn",
        )

    if _looks_wiii_pipeline_meta_turn(normalized):
        return (
            direct_agent_name,
            "off_topic",
            1.0,
            "obvious Wiii pipeline/meta analysis turn",
        )

    if _looks_wiii_capability_inventory_turn(normalized):
        return (
            direct_agent_name,
            "off_topic",
            1.0,
            "obvious Wiii capability inventory turn",
        )

    if _looks_reasoning_safety_meta_turn(normalized):
        return (
            direct_agent_name,
            "off_topic",
            1.0,
            "obvious reasoning-safety meta turn",
        )

    if memory_agent_name and _looks_memory_write_turn(normalized):
        return (
            memory_agent_name,
            "personal",
            1.0,
            "obvious memory write turn",
        )

    if (
        code_studio_agent_name
        and needs_code_studio_fn
        and needs_code_studio_fn(query)
        and (
            _looks_obvious_maritime_lookup_turn(normalized)
            or _looks_colreg_rule_explanation_turn(normalized)
        )
    ):
        return (
            code_studio_agent_name,
            "code_execution",
            1.0,
            "obvious Code Studio visual app turn",
        )

    if rag_agent_name and _looks_obvious_maritime_lookup_turn(normalized):
        return (
            rag_agent_name,
            "lookup",
            1.0,
            "obvious maritime regulation lookup turn",
        )

    if rag_agent_name and _looks_colreg_rule_explanation_turn(normalized):
        return (
            rag_agent_name,
            "lookup",
            1.0,
            "obvious COLREG rule explanation turn",
        )

    if _looks_host_ui_navigation_turn(normalized):
        return (
            direct_agent_name,
            "host_ui_navigation",
            1.0,
            "obvious host UI navigation/help turn",
        )

    return None


def _looks_personal_memory_recall_turn(normalized_query: str) -> bool:
    """Detect user asking whether Wiii remembers the current person/context."""
    query = f" {normalized_query or ''} "
    if not query.strip():
        return False

    directed_subject = any(
        token in query
        for token in (
            " ban ",
            " wii ",
            " wiii ",
            " wiiii ",
        )
    )
    personal_object = any(
        token in query
        for token in (
            " minh",
            " toi",
            " tui",
            " em",
            " anh",
            " chi",
        )
    )

    if directed_subject and personal_object and " nho " in query:
        return True

    recall_markers = (
        "co nho minh",
        "co nho toi",
        "con nho minh",
        "con nho toi",
        "nho minh khong",
        "nho toi khong",
        "nho minh ha",
        "nho toi ha",
        "remember me",
        "remember who i am",
    )
    return any(marker in query for marker in recall_markers)


def rule_based_route_impl(
    *,
    query: str,
    domain_config: dict | None,
    normalize_router_text_fn: Any,
    is_obvious_social_turn_fn: Any,
    needs_code_studio_fn: Any,
    get_domain_keywords_fn: Any,
    looks_clear_learning_turn_fn: Any,
    personal_keywords: list[str] | tuple[str, ...],
    direct_agent_name: str,
    memory_agent_name: str,
    code_studio_agent_name: str,
    rag_agent_name: str,
    tutor_agent_name: str,
) -> str:
    """Minimal rule-based routing guardrail fallback."""
    query_lower = query.lower()
    normalized_query = normalize_router_text_fn(query)

    if is_obvious_social_turn_fn(query):
        return direct_agent_name

    if _looks_session_memory_recall_turn(normalized_query):
        return direct_agent_name

    if _looks_session_memory_write_turn(normalized_query):
        return direct_agent_name

    if _looks_self_feeling_probe_turn(normalized_query):
        return direct_agent_name

    if _is_codebase_analysis_query(normalized_query):
        return direct_agent_name

    if _looks_wiii_pipeline_meta_turn(normalized_query):
        return direct_agent_name

    if _looks_wiii_capability_inventory_turn(normalized_query):
        return direct_agent_name

    if _looks_reasoning_safety_meta_turn(normalized_query):
        return direct_agent_name

    if _looks_memory_write_turn(normalized_query):
        return memory_agent_name

    if _looks_explicit_web_search_turn(normalized_query):
        return direct_agent_name

    normalized_personal_keywords = [
        normalize_router_text_fn(str(kw or ""))
        for kw in personal_keywords
        if str(kw or "").strip()
    ]
    if (
        any(kw in query_lower for kw in personal_keywords)
        or any(kw and kw in normalized_query for kw in normalized_personal_keywords)
        or _looks_personal_memory_recall_turn(normalized_query)
    ):
        return memory_agent_name

    if needs_code_studio_fn(query):
        return code_studio_agent_name

    domain_keywords = get_domain_keywords_fn(domain_config)
    normalized_domain_keywords = [
        normalize_router_text_fn(str(keyword or ""))
        for keyword in domain_keywords
        if str(keyword or "").strip()
    ]
    if any(_domain_keyword_matches(keyword, normalized_query) for keyword in normalized_domain_keywords):
        return rag_agent_name

    if (
        looks_clear_learning_turn_fn(normalized_query)
        or any(
            marker in normalized_query
            for marker in (
                "phan tich",
                "toan hoc",
                "cong thuc",
                "nguyen ly",
                "co che",
                "ban chat",
                "chung minh",
                "vi sao",
                "tai sao",
            )
        )
    ):
        return tutor_agent_name

    return direct_agent_name
