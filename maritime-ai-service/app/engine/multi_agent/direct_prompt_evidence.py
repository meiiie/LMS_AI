"""Live-evidence prompt contracts for the direct response lane."""

from __future__ import annotations

from app.engine.multi_agent.direct_evidence_planner import build_direct_evidence_plan
from app.engine.multi_agent.state import AgentState


def _build_live_evidence_planner_contract(query: str, state: AgentState) -> str:
    plan = build_direct_evidence_plan(query, state, [])
    if plan.family in {"none", "product_search_handoff"}:
        return ""

    lines = [
        "## LIVE EVIDENCE PLANNER:",
        f"- Query family: {plan.family}",
        f"- Topic cluster: {plan.topic_cluster or 'general'}",
        f"- Locality policy: {plan.locality}",
        f"- Answer mode: {plan.answer_mode}",
    ]
    if plan.needs_time_anchor:
        lines.append("- Bat buoc chot moc thoi gian hien tai truoc khi tong hop.")
    if plan.requires_current_sources:
        lines.append("- Bat buoc dua tren nguon hien tai/nguon co moc thoi gian ro.")
    if plan.axes:
        lines.append(f"- Evidence axes: {_join_direct_hint_list(list(plan.axes), limit=4)}.")
    if plan.source_plan:
        lines.append(f"- Source plan: {_join_direct_hint_list(list(plan.source_plan), limit=3)}.")
    if plan.source_policy:
        lines.append(f"- Source policy: {_join_direct_hint_list(list(plan.source_policy), limit=3)}.")
    if plan.family == "live_weather":
        lines.extend(
            [
                "- Mo answer bang dia diem + tinh hinh thoi tiet hien tai truoc, roi moi den du bao/canh bao neu can.",
                "- Neu dia diem user noi mo ho, noi ro dia diem dang duoc gia dinh thay vi gia vo user da chi ro.",
            ]
        )
    elif plan.family in {"live_news_lookup", "live_current_lookup"}:
        lines.extend(
            [
                "- Uu tien fact snapshot co moc ngay gio ro, roi moi them boi canh ngan.",
                "- Neu nguon chua du chac de chot cung, noi muc do chac va diem con mo.",
            ]
        )
    elif plan.family in {"live_market_price", "market_analysis"}:
        lines.extend(
            [
                "- Neu gia/quote cac nguon lech nhau, tra khoang hoac noi ro nguon dang phan ky.",
                "- Khong bien answer thanh market essay chung chung neu user dang hoi moc gia hien tai.",
            ]
        )
    return "\n".join(lines)


def _join_direct_hint_list(items: list[str], *, limit: int = 3) -> str:
    chosen = [str(item or "").strip() for item in items if str(item or "").strip()][:limit]
    if not chosen:
        return ""
    if len(chosen) == 1:
        return chosen[0]
    if len(chosen) == 2:
        return f"{chosen[0]} va {chosen[1]}"
    return ", ".join(chosen[:-1]) + f", va {chosen[-1]}"
