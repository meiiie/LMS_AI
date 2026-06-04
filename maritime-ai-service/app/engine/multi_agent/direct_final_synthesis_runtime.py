"""Final synthesis helpers for direct tool-round execution."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.engine.multi_agent.direct_reasoning import (
    _build_direct_analytical_axes,
    _build_direct_evidence_plan,
    _infer_direct_thinking_mode,
)
from app.engine.multi_agent.direct_tool_message_runtime import (
    build_system_instruction_message,
    build_user_instruction_message,
)
from app.engine.multi_agent.state import AgentState

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DirectFinalSynthesisRunResult:
    """Result of forcing one no-tool synthesis pass after tool execution."""

    llm_response: Any
    messages: list[Any]
    resolved_provider: str | None


def extract_direct_visible_text(content: Any) -> str:
    """Return the answer text that would be visible to the user."""
    try:
        from app.services.output_processor import extract_thinking_from_response

        text_content, _thinking_content = extract_thinking_from_response(content)
        return str(text_content or "").strip()
    except Exception:
        return str(content or "").strip()


_LIVE_LOOKUP_TOOL_NAMES = {
    "tool_web_search",
    "web_search",
    "tool_search_news",
    "search_news",
    "tool_search_legal",
    "search_legal",
    "tool_search_maritime",
    "search_maritime",
    "tool_fetch_url",
    "fetch_url",
    "tool_current_datetime",
    "current_datetime",
    "tool_current_weather",
    "current_weather",
}


def _has_live_lookup_tool(tool_names: list[str]) -> bool:
    return any(
        str(name or "").strip().lower() in _LIVE_LOOKUP_TOOL_NAMES
        for name in tool_names
    )


def build_direct_live_lookup_system_guard(tool_names: list[str]) -> str:
    """Return a system-level guard for evidence-only live lookup synthesis."""
    if not _has_live_lookup_tool(tool_names):
        return ""
    return (
        "SYSTEM live lookup guard: answer only from tool evidence collected in "
        "this turn. Do not use stored memory, inferred emotions, relationship "
        "history, occupation, maritime/campus context, or user background unless "
        "the user explicitly asked for that context in the current message. "
        "Do not say the user is sad, worried, interested in ports, or preparing "
        "for something unless the current user message says so. Do not inject "
        "Wiii lore, Bong, pet stories, bedtime advice, kaomoji, or decorative "
        "playful asides into factual lookup answers unless explicitly requested. "
        "Do not ask personal follow-up questions about where the user is, what "
        "they are doing, whether they are studying late, or whether they are at "
        "home. "
        "Keep the answer concise, natural, and professional; the UI already "
        "renders source links."
    )


def build_direct_final_synthesis_instruction(
    query: str,
    state: AgentState,
    tool_names: list[str],
) -> str:
    """Build a mode-aware final synthesis instruction after tool rounds."""
    thinking_mode = _infer_direct_thinking_mode(query, state, tool_names)
    axes = _build_direct_analytical_axes(query, state, tool_names)
    plan = _build_direct_evidence_plan(query, state, tool_names)

    base = (
        "Du lieu da du cho luot nay. Khong goi them cong cu. "
        "Hay tong hop ngay thanh cau tra loi cuoi cung bang tieng Viet, "
        "dua tren cac ket qua cong cu da co."
    )
    if _has_live_lookup_tool(tool_names):
        base += (
            " Voi luot tra cuu web/thoi gian/thoi tiet, chi tra loi tu bang chung "
            "cong cu trong luot nay; khong chen ky uc, cam xuc, moi quan he, "
            "nghe nghiep, hang hai, truong lop, hay suy dien ve nguoi dung neu "
            "user khong hoi truc tiep. Khong chen lore Wiii, Bong, chuyen thu "
            "cung, loi khuyen di ngu, kaomoji, hay aside vui dua vao cau tra "
            "cuu su kien. Khong hoi nguoc chuyen ca nhan nhu user dang o dau, "
            "dang lam gi, co hoc khuya hay dang o nha khong. Uu tien 1-2 doan "
            "gon, tu nhien, chuyen nghiep; khong "
            "can lap lai danh sach link vi UI da co the nguon."
        )

    if thinking_mode == "analytical_market":
        return (
            base
            + " Mo dau bang mot cau thesis ve mat bang thi truong hien tai, sau do tach cac luc keo chinh "
            + "(cung-cau, OPEC+, ton kho, dia chinh tri) thay vi liet ke tin tuc. "
            + "Neu cac tin hieu xung nhau, hay noi ro truc nao dang giu mat bang gia va truc nao chi tao nhieu ngan han. "
            + "Mac dinh uu tien 2-3 doan chat; chi dung bullet ngan neu can tach watchlist. "
            + "KHONG dung heading Markdown nhu #, ##, ###, va KHONG dung bullet/bold kieu ban tin tong hop. "
            + "Ket bang takeaway hoac dieu can theo doi tiep theo."
        )
    if thinking_mode == "analytical_math":
        return (
            base
            + " Mo dau bang mot cau thesis ve mo hinh dang dung, roi trinh bay theo nhip mo hinh/gia dinh -> phuong trinh hoac suy dan -> y nghia vat ly. "
            + "Noi ro cac gia dinh nhu "
            + (", ".join(axes[:3]) if axes else "mo hinh, goc nho, va phuong trinh")
            + ". Neu ket luan phu thuoc gan dung, noi ro pham vi ma gan dung do con hop le. "
            + "Mac dinh uu tien 2-3 doan chat; KHONG dung heading Markdown nhu #, ##, ### neu user khong yeu cau."
        )
    if thinking_mode == "analytical_general":
        plan_hint = (
            ", ".join(plan[:2])
            if plan
            else "cac bien so chinh va chung cu manh nhat"
        )
        return (
            base
            + " Mo dau bang mot cau thesis co the kiem cheo, di thang vao luan diem, tach dieu chac khoi dieu con nhieu, va neo lai "
            + plan_hint
            + ". Neu co tin hieu trai chieu, noi ro cai nao dang nang ky hon. "
            + "Mac dinh uu tien 2-3 doan chat; chi dung bullet ngan khi user can tach checklist/watchlist. "
            + "KHONG dung heading Markdown nhu #, ##, ###."
        )
    return base


async def run_direct_final_synthesis(
    *,
    messages: list[Any],
    query: str,
    state: AgentState,
    tool_call_events: list[dict[str, Any]],
    push_event,
    native_tool_messages: bool,
    llm_base: Any,
    llm_auto: Any,
    llm_with_tools: Any,
    provider: str | None,
    resolved_provider: str | None,
    request_failover_mode: Any,
    allowed_fallback_providers: tuple[str, ...] | list[str] | set[str] | None,
    ainvoke_with_fallback: Callable[..., Any],
    stream_direct_wait_heartbeats: Callable[..., Any],
    remember_execution_target: Callable[..., tuple[str | None, str | None]],
    runtime_tier_for: Callable[..., str],
) -> DirectFinalSynthesisRunResult:
    """Force a final prose answer after tool rounds without exposing tools again."""
    synthesis_tool_names = [
        str(event.get("name", ""))
        for event in tool_call_events
        if event.get("type") == "call"
    ]
    synthesis_messages = list(messages)
    live_lookup_guard = build_direct_live_lookup_system_guard(synthesis_tool_names)
    if live_lookup_guard:
        synthesis_messages.append(
            build_system_instruction_message(
                live_lookup_guard,
                native_tool_messages=native_tool_messages,
            )
        )
    synthesis_messages.append(
        build_user_instruction_message(
            build_direct_final_synthesis_instruction(
                query,
                state,
                synthesis_tool_names,
            ),
            native_tool_messages=native_tool_messages,
        )
    )
    synthesis_llm = llm_base
    if synthesis_llm is None:
        raise RuntimeError(
            "run_direct_final_synthesis requires an unbound LLM for the final no-tool pass"
        )
    synthesis_heartbeat = asyncio.create_task(
        stream_direct_wait_heartbeats(
            push_event,
            query=query,
            phase="synthesize",
            cue="synthesis",
            tool_names=synthesis_tool_names,
        )
    )
    try:
        candidate_provider, _candidate_model = remember_execution_target(
            synthesis_llm,
            fallback_source=llm_base,
        )
        resolved_provider = candidate_provider or resolved_provider
        # Synthesis after a successful tool round needs a longer timeout than
        # tool-bound planning: context is larger and the model must produce
        # grounded prose from already-collected evidence.
        llm_response = await ainvoke_with_fallback(
            synthesis_llm,
            synthesis_messages,
            tier=runtime_tier_for(synthesis_llm, llm_base),
            provider=provider,
            resolved_provider=resolved_provider,
            failover_mode=request_failover_mode,
            push_event=push_event,
            timeout_profile="moderate",
            state=state,
            allowed_fallback_providers=allowed_fallback_providers,
        )
        return DirectFinalSynthesisRunResult(
            llm_response=llm_response,
            messages=synthesis_messages,
            resolved_provider=resolved_provider,
        )
    finally:
        synthesis_heartbeat.cancel()
        try:
            await synthesis_heartbeat
        except asyncio.CancelledError:
            pass
        except Exception as heartbeat_error:
            logger.debug(
                "[DIRECT] Final synthesis heartbeat shutdown skipped: %s",
                heartbeat_error,
            )
