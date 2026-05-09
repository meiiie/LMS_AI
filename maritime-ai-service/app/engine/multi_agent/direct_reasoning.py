"""Shared direct-lane reasoning cues and reflections."""

from __future__ import annotations

from typing import Any
import re
import unicodedata

from app.engine.multi_agent.direct_intent import (
    _needs_datetime,
    _needs_legal_search,
    _needs_lms_query,
    _needs_news_search,
    _needs_web_search,
)
from app.engine.multi_agent.state import AgentState
from app.engine.multi_agent.visual_intent_resolver import resolve_visual_intent

_DIRECT_TIME_TOOLS = {"tool_current_datetime"}
_DIRECT_NEWS_TOOLS = {"tool_search_news"}
_DIRECT_LEGAL_TOOLS = {"tool_search_legal"}
_DIRECT_WEB_TOOLS = {
    "tool_web_search",
    "tool_search_maritime",
    "tool_knowledge_search",
}
_DIRECT_MEMORY_TOOLS = {"tool_character_read", "tool_character_note"}
_DIRECT_BROWSER_TOOLS = {"tool_browser_snapshot_url"}
_DIRECT_ANALYSIS_PREFIXES = ("tool_execute_python", "tool_chart_", "tool_plot_")
_DIRECT_LMS_PREFIX = "tool_lms_"
_DIRECT_HOST_ACTION_PREFIX = "host_action__"
_MARKET_ANALYSIS_KEYWORDS = (
    "gia dau",
    "gia xang",
    "gia gas",
    "brent",
    "wti",
    "opec",
    "opec+",
    "ton kho",
    "eia",
    "sàn ice",
    "ice brent",
    "nang luong",
    "thi truong dau",
    "gia nang luong",
)
_MATH_ANALYSIS_KEYWORDS = (
    "toan hoc",
    "phuong trinh",
    "dao ham",
    "tich phan",
    "dao dong",
    "con lac don",
    "con lắc đơn",
    "goc nho",
    "góc nhỏ",
    "chu ky",
    "chu kỳ",
    "hilbert",
    "self-adjoint",
    "self adjoint",
    "tự liên hợp",
    "tu lien hop",
    "spectral theorem",
    "stone theorem",
    "compact resolvent",
    "deficiency indices",
    "deficiency index",
)
_ANALYTICAL_QUERY_KEYWORDS = (
    "phan tich",
    "phân tích",
    "danh gia",
    "đánh giá",
    "xu huong",
    "xu hướng",
    "tac dong",
    "tác động",
    "vi sao",
    "tai sao",
    "mo hinh",
    "mô hình",
)
_CODEBASE_ANALYSIS_KEYWORDS = (
    "agent",
    "alembic",
    "api",
    "auth",
    "authentication",
    "backend",
    "bang",
    "class diagram",
    "codebase",
    "controller",
    "database",
    "diagram",
    "entity",
    "filter",
    "flyway",
    "github",
    "jwt",
    "migration",
    "repository",
    "repo",
    "schema",
    "security",
    "service",
    "source",
    "table",
    "uml",
    "xac thuc",
)
_CODEBASE_STRONG_KEYWORDS = (
    "class diagram",
    "database",
    "jwt",
    "migration",
    "schema",
    "source",
    "xac thuc",
)


def _extract_math_topic_hint(query: str) -> str:
    folded = _fold_reasoning_text(query)
    if "con lac don" in folded:
        return "con lắc đơn"
    if any(
        token in folded
        for token in (
            "hilbert",
            "self adjoint",
            "selfadjoint",
            "tu lien hop",
            "tự liên hợp",
            "compact resolvent",
            "spectral theorem",
            "stone theorem",
            "deficiency indice",
            "deficiency index",
        )
    ):
        return "bài toán toán tử trên không gian Hilbert"
    return "bài toán toán học này"


def _normalize_reasoning_text(text: str) -> str:
    return " ".join((text or "").lower().split())


def _fold_reasoning_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text or "")
    stripped = "".join(char for char in normalized if not unicodedata.combining(char))
    lowered = stripped.replace("đ", "d").replace("Đ", "D").lower()
    lowered = re.sub(r"[^0-9a-z+]+", " ", lowered)
    return " ".join(lowered.split())


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    normalized = _fold_reasoning_text(text)
    return any(_fold_reasoning_text(keyword) in normalized for keyword in keywords)


def _is_codebase_analysis_query(text: str) -> bool:
    normalized = _fold_reasoning_text(text)
    if not any(
        _fold_reasoning_text(keyword) in normalized
        for keyword in _CODEBASE_ANALYSIS_KEYWORDS
    ):
        return False
    if any(
        _fold_reasoning_text(keyword) in normalized
        for keyword in _CODEBASE_STRONG_KEYWORDS
    ):
        return True
    return any(
        _fold_reasoning_text(keyword) in normalized
        for keyword in _ANALYTICAL_QUERY_KEYWORDS
    )


def _has_prefixed_tool(tool_names: list[str], prefixes: tuple[str, ...]) -> bool:
    """Check whether any tool starts with one of the provided prefixes."""
    return any(name.startswith(prefix) for name in tool_names for prefix in prefixes)


def _uses_lms_tool(tool_names: list[str]) -> bool:
    """Check whether direct reasoning involved LMS tools."""
    return any(name.startswith(_DIRECT_LMS_PREFIX) for name in tool_names)


def _uses_host_action_tool(tool_names: list[str]) -> bool:
    """Check whether direct reasoning involved host action tools."""
    return any(name.startswith(_DIRECT_HOST_ACTION_PREFIX) for name in tool_names)


def _infer_direct_reasoning_cue(
    query: str,
    state: AgentState,
    tool_names: list[str] | None = None,
) -> str:
    """Map the current direct path into a stable reasoning cue."""
    tool_names = tool_names or []
    tool_set = set(tool_names)
    routing_meta = state.get("routing_metadata") or {}
    intent = str(routing_meta.get("intent", "")).strip().lower()
    context = state.get("context") or {}

    categories = 0
    categories += int(bool(tool_set & _DIRECT_TIME_TOOLS))
    categories += int(bool(tool_set & _DIRECT_NEWS_TOOLS))
    categories += int(bool(tool_set & _DIRECT_LEGAL_TOOLS))
    categories += int(bool(tool_set & _DIRECT_WEB_TOOLS))
    categories += int(_uses_lms_tool(tool_names))
    categories += int(_uses_host_action_tool(tool_names))
    categories += int(bool(tool_set & _DIRECT_MEMORY_TOOLS))
    categories += int(bool(tool_set & _DIRECT_BROWSER_TOOLS))
    categories += int(_has_prefixed_tool(tool_names, _DIRECT_ANALYSIS_PREFIXES))
    if categories > 1:
        return "multi_source"

    if context.get("images"):
        return "visual"
    if "tool_current_datetime" in tool_set or _needs_datetime(query):
        return "datetime"
    if tool_set & _DIRECT_NEWS_TOOLS or _needs_news_search(query):
        return "news"
    if tool_set & _DIRECT_LEGAL_TOOLS or _needs_legal_search(query):
        return "legal"
    if tool_set & _DIRECT_WEB_TOOLS or _needs_web_search(query):
        return "web"
    if _uses_host_action_tool(tool_names):
        return "operator"
    if _uses_lms_tool(tool_names) or _needs_lms_query(query):
        return "lms"
    if tool_set & _DIRECT_MEMORY_TOOLS:
        return "memory"
    if tool_set & _DIRECT_BROWSER_TOOLS:
        return "browser"
    if _has_prefixed_tool(tool_names, _DIRECT_ANALYSIS_PREFIXES):
        return "analysis"
    if intent == "personal":
        return "personal"
    if intent == "social":
        return "social"
    if intent == "off_topic":
        return "off_topic"
    return "general"


def _infer_direct_topic_hint(
    query: str,
    state: AgentState,
    tool_names: list[str] | None = None,
) -> str:
    del state, tool_names
    normalized = _normalize_reasoning_text(query)
    if _is_codebase_analysis_query(normalized):
        folded = _fold_reasoning_text(query)
        if "jwt" in folded or "auth" in folded or "xac thuc" in folded:
            return "JWT/auth trong codebase"
        if "schema" in folded or "database" in folded or "table" in folded or "bang" in folded:
            return "schema/database trong codebase"
        return "codebase/source-backed analysis"
    if _contains_any(normalized, _MARKET_ANALYSIS_KEYWORDS):
        return "giá dầu"
    if _contains_any(normalized, _MATH_ANALYSIS_KEYWORDS):
        return _extract_math_topic_hint(query)
    return ""


def _infer_direct_thinking_mode(
    query: str,
    state: AgentState,
    tool_names: list[str] | None = None,
) -> str:
    tool_names = tool_names or []
    cue = _infer_direct_reasoning_cue(query, state, tool_names)
    normalized = _normalize_reasoning_text(query)

    if _contains_any(normalized, _MARKET_ANALYSIS_KEYWORDS):
        return "analytical_market"
    if _contains_any(normalized, _MATH_ANALYSIS_KEYWORDS):
        return "analytical_math"
    if _is_codebase_analysis_query(normalized):
        return "analytical_codebase"
    if cue in {"visual", "browser"}:
        return "visual_editorial"
    if cue in {"news", "web"} and _contains_any(normalized, _ANALYTICAL_QUERY_KEYWORDS):
        return "analytical_general"
    if cue == "analysis":
        return "analytical_general"
    if cue in {"datetime", "memory", "personal", "social", "off_topic", "general"}:
        return ""
    return ""


def _build_direct_analytical_axes(
    query: str,
    state: AgentState,
    tool_names: list[str] | None = None,
) -> list[str]:
    del state, tool_names
    normalized = _normalize_reasoning_text(query)
    if _contains_any(normalized, _MARKET_ANALYSIS_KEYWORDS):
        return [
            "OPEC+ và sản lượng",
            "tồn kho và nhịp cung cầu",
            "địa chính trị",
            "Brent/WTI",
        ]
    if _contains_any(normalized, _MATH_ANALYSIS_KEYWORDS):
        if "con lắc đơn" in _extract_math_topic_hint(query):
            return [
                "mô hình lý tưởng",
                "giả định góc nhỏ",
                "phương trình dao động",
                "chu kỳ và năng lượng",
            ]
        return [
            "đối tượng và giả thiết",
            "điều kiện áp dụng định lý",
            "bước suy ra then chốt",
            "hệ quả cần kết luận",
        ]
    if _is_codebase_analysis_query(normalized):
        folded = _fold_reasoning_text(query)
        if "jwt" in folded or "auth" in folded or "xac thuc" in folded:
            return [
                "entrypoint dang nhap va tao token",
                "JwtService/JwtAuthenticationFilter",
                "User/Role/Organization state",
                "request lifecycle va refresh path",
            ]
        if "database" in folded or "schema" in folded or "table" in folded or "bang" in folded:
            return [
                "source schema/migration",
                "entity nghiep vu cot loi",
                "junction/infrastructure tables",
                "khoang cach giua class diagram va database",
            ]
        return [
            "claim cua user",
            "file/source can kiem",
            "runtime path lien quan",
            "ket luan va diem con mo",
        ]
    if _contains_any(normalized, _ANALYTICAL_QUERY_KEYWORDS):
        return [
            "biến số chính",
            "quan hệ nhân quả",
            "giả định nền",
        ]
    return []


def _build_direct_evidence_plan(
    query: str,
    state: AgentState,
    tool_names: list[str] | None = None,
) -> list[str]:
    del state
    normalized = _normalize_reasoning_text(query)
    tool_names = tool_names or []
    if _is_codebase_analysis_query(normalized):
        folded = _fold_reasoning_text(query)
        if "jwt" in folded or "auth" in folded or "xac thuc" in folded:
            return [
                "truy tu login/controller sang service tao token",
                "kiem JwtAuthenticationFilter doc Bearer token moi request",
                "doi chieu user/role/enabled tu database voi payload token",
                "tach dieu verified tu inference neu chua doc du file",
            ]
        if "database" in folded or "schema" in folded or "table" in folded or "bang" in folded:
            return [
                "kiem ke bang tu schema/migration thay vi doan theo so luong",
                "phan nhom entity chinh, junction table, va infrastructure table",
                "doi chieu class diagram voi bang thuc te",
                "ghi ro bang nao thieu va vi sao thieu",
            ]
        return [
            "mo bang cau hoi can kiem chung",
            "neu nguon/file nao da doc truoc khi ket luan",
            "noi ro muc do chac va diem con mo neu thieu source",
        ]
    if _contains_any(normalized, _MARKET_ANALYSIS_KEYWORDS):
        plan = [
            "đối chiếu Brent và WTI",
            "tách OPEC+ khỏi yếu tố nhu cầu",
            "kiểm chéo tín hiệu tồn kho hoặc nguồn năng lượng cập nhật",
        ]
        if "tool_search_news" in tool_names:
            plan.append("giữ riêng phần nhiễu địa chính trị từ tin mới")
        return plan
    if _contains_any(normalized, _MATH_ANALYSIS_KEYWORDS):
        if "con lắc đơn" in _extract_math_topic_hint(query):
            return [
                "chốt mô hình con lắc lý tưởng",
                "tách trường hợp góc nhỏ",
                "neo công thức chu kỳ và ý nghĩa vật lý",
            ]
        return [
            "chốt đối tượng và giả thiết",
            "tách điều kiện áp dụng khỏi hệ quả",
            "kiểm lại từng bước suy ra",
        ]
    if _contains_any(normalized, _ANALYTICAL_QUERY_KEYWORDS):
        return [
            "neo vài biến số chính",
            "tách điều chắc khỏi điều còn nhiễu",
        ]
    return []


async def _build_direct_reasoning_summary(
    query: str,
    state: AgentState,
    tool_names: list[str] | None,
    *,
    render_reasoning_fast,
) -> str:
    """Build safe, human-readable direct reasoning without exposing raw CoT."""
    cue = _infer_direct_reasoning_cue(query, state, tool_names)
    thinking_mode = _infer_direct_thinking_mode(query, state, tool_names)
    topic_hint = _infer_direct_topic_hint(query, state, tool_names)
    analytical_axes = _build_direct_analytical_axes(query, state, tool_names)
    evidence_plan = _build_direct_evidence_plan(query, state, tool_names)
    opening = await render_reasoning_fast(
        state=state,
        node="direct",
        phase="attune",
        cue=cue,
        tool_names=tool_names,
        thinking_mode=thinking_mode,
        topic_hint=topic_hint,
        analytical_axes=analytical_axes,
        evidence_plan=evidence_plan,
        style_tags=["direct", "summary"],
    )
    closing = await render_reasoning_fast(
        state=state,
        node="direct",
        phase="synthesize",
        cue=cue,
        tool_names=tool_names,
        thinking_mode=thinking_mode,
        topic_hint=topic_hint,
        analytical_axes=analytical_axes,
        evidence_plan=evidence_plan,
        style_tags=["direct", "summary"],
    )
    if closing.summary and closing.summary != opening.summary:
        return f"{opening.summary}\n\n{closing.summary}"
    return opening.summary


async def _build_direct_tool_reflection(
    state: AgentState,
    tool_name: str,
    result: object,
) -> str:
    """Return a small user-safe progress beat for direct-tool execution."""
    del result
    query = str(state.get("query") or "").strip()
    visual_decision = resolve_visual_intent(query)
    normalized_tool = str(tool_name or "").strip().lower()

    if normalized_tool in {"tool_web_search", "tool_search_news", "tool_search_legal", "tool_search_maritime", "tool_knowledge_search", "tool_fetch_url"}:
        if _is_codebase_analysis_query(query):
            return "Minh vua co them nguon de doi chieu claim voi file/schema that; buoc tiep theo la tach dieu da xac minh khoi suy luan."
        if visual_decision.presentation_intent == "chart_runtime":
            return "Mình đã có thêm vài mảnh dữ liệu để dựng thành một hình nhìn ra xu hướng rõ hơn."
        return "Mình đã có thêm vài mảnh dữ liệu để gạn lại cho câu trả lời chắc hơn."
    if normalized_tool == "tool_current_datetime":
        return "Mốc thời gian đã rõ, nên câu trả lời giờ có thể bám đúng hiện tại hơn."
    if normalized_tool == "tool_generate_visual":
        return "Khung trực quan đã lên rồi; giờ mình chỉ cần khâu lời dẫn cho gọn và đúng nhịp."
    if normalized_tool.startswith("tool_chart_") or normalized_tool.startswith("tool_plot_"):
        return "Phần trực quan đã có khung chính; giờ mình gạn lại để bạn nhìn là hiểu ngay."
    return "Mình đang lồng kết quả vừa có vào câu trả lời để nó vừa chắc vừa tự nhiên hơn."


# ── Market temporal + locality helpers (shared with direct_evidence_planner) ──

_TEMPORAL_MARKERS = (
    "hom nay", "hien tai", "bay gio", "moi nhat", "gan day",
    "latest", "today", "current", "now",
)

_VIETNAM_LOCALITY_MARKERS = (
    "viet nam", "vietnam", "trong nuoc", "xang ron", "petrolimex", "pvoil",
    "gia xang", "gia dau",
)


def _is_temporal_market_query(query: str) -> bool:
    """Check if the query asks about current/live market data."""
    normalized = _normalize_reasoning_text(query)
    is_market = any(kw in normalized for kw in _MARKET_ANALYSIS_KEYWORDS)
    is_temporal = any(kw in normalized for kw in _TEMPORAL_MARKERS)
    return is_market and is_temporal


def _should_default_market_to_vietnam(query: str, state: AgentState) -> bool:
    """Check if the market query should default to a Vietnam-first perspective."""
    del state
    normalized = _normalize_reasoning_text(query)
    global_markers = ("the gioi", "quoc te", "global", "brent", "wti", "usd", "index")
    has_global = any(kw in normalized for kw in global_markers)
    if has_global:
        return False
    return any(kw in normalized for kw in _VIETNAM_LOCALITY_MARKERS)
