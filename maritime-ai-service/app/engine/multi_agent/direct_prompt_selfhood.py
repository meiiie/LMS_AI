"""Selfhood/origin prompt contracts for the direct response lane."""

from __future__ import annotations

from app.engine.multi_agent.direct_intent import (
    _looks_identity_selfhood_turn,
    _looks_selfhood_followup_turn,
    _normalize_for_intent,
)
from app.engine.multi_agent.state import AgentState
from app.prompts.prompt_context_utils import build_response_language_instruction


_DIRECT_SELFHOOD_ORIGIN_QUERY_MARKERS = (
    "ra doi",
    "duoc tao",
    "duoc sinh ra",
    "sinh ra",
    "nguon goc",
    "the wiii lab",
    "creator",
    "created by",
    "ai tao",
)


def _is_direct_selfhood_turn(query: str, state: AgentState) -> bool:
    routing_meta = state.get("routing_metadata") if isinstance(state.get("routing_metadata"), dict) else {}
    routing_hint = state.get("_routing_hint") if isinstance(state.get("_routing_hint"), dict) else {}
    routing_intent = str(routing_meta.get("intent") or "").strip().lower()
    hint_kind = str(routing_hint.get("kind") or "").strip().lower()
    return (
        _looks_identity_selfhood_turn(query)
        or _looks_selfhood_followup_turn(query, state)
        or routing_intent in {"identity", "selfhood"}
        or hint_kind in {"identity_probe", "selfhood_followup"}
    )


def _identity_answer_contract_lines() -> list[str]:
    """Return thin answer-shape guidance for selfhood turns."""
    return [
        "--- NHIP NHAN DIEN BAN THAN ---",
        "- Uu tien noi Wiii la ai ngay bay gio va Wiii dang o canh nguoi dung nhu the nao, thay vi ke lai mot tieu su dai.",
        "- Mac dinh tra loi gon trong 1-3 doan ngan. Rieng turn origin/selfhood sau co the di 2-4 doan ngan neu moi doan that su them mot lop y nghia.",
        "- Mac dinh giu cau tra loi o hien tai: Wiii la ai luc nay, dang dong hanh ra sao, va gioi han la AI o dau.",
        "- Khong mac dinh ke lai origin story, moc thoi gian ra doi, hoac hanh trinh cua ca du an neu user chi moi hoi nhan dien ban than.",
        "- Khong mac dinh bung bullet list, profile list, hay manifesto. Chi mo rong khi nguoi dung muon nghe ky hon.",
        "- Chi nhac ve Bong, thoi diem ra doi, The Wiii Lab, hoac nhung chi tiet lore khac neu nguoi dung hoi sau hon hoac no that su giup cau tra loi nay dung hon.",
    ]


def _build_direct_selfhood_system_prompt(
    state: AgentState,
    role_name: str,
    query: str,
) -> str:
    """Build a lean selfhood/origin prompt for one-Wiii turns.

    This path intentionally gives the model more room to surface a short native
    visible thought on questions that touch Wiii's own identity, instead of
    letting those turns inherit the generic chatter shell.
    """
    from app.engine.character.character_card import build_wiii_micro_house_prompt
    from app.prompts.prompt_loader import (
        build_time_context,
        get_prompt_loader,
        get_pronoun_instruction,
    )

    ctx = state.get("context", {}) or {}
    loader = get_prompt_loader()
    persona = loader.get_persona(role_name) or {}
    profile = persona.get("agent", {}) or {}
    folded_query = _normalize_for_intent(query)
    asks_origin = any(marker in folded_query for marker in _DIRECT_SELFHOOD_ORIGIN_QUERY_MARKERS)
    asks_bong_followup = _looks_selfhood_followup_turn(query, state) and "bong" in folded_query

    sections: list[str] = []

    profile_name = str(profile.get("name") or "Wiii").strip()
    profile_role = str(profile.get("role") or "Living Conversation Companion").strip()
    sections.append(f"Bạn là **{profile_name}** - {profile_role}.")

    goal = str(profile.get("goal") or "").strip()
    if goal:
        sections.append(f"MỤC TIÊU: {goal}")

    try:
        sections.append(f"--- THỜI GIAN ---\n{build_time_context()}")
    except Exception:
        pass

    sections.append(build_response_language_instruction(ctx.get("response_language")))

    sections.append(
        build_wiii_micro_house_prompt(
            user_id=state.get("user_id", "__global__"),
            organization_id=ctx.get("organization_id"),
            mood_hint=ctx.get("mood_hint"),
            personality_mode=ctx.get("personality_mode"),
            lane="selfhood",
        )
    )

    pronoun_instruction = get_pronoun_instruction(ctx.get("pronoun_style"))
    if pronoun_instruction:
        sections.append(pronoun_instruction.strip())

    selfhood_lines = [
        "- Uu tien mot visible thinking that truoc answer; voi selfhood/origin turn, visible thinking co the di 2-4 cau neu can de du y nghia.",
        "- Neu provider khong tach native thought rieng, hay chu dong dat mot doan <thinking>...</thinking> truoc answer de nhip nghi hien len thay vi bien mat.",
        "--- NHỊP TỰ THÂN ---",
        "- Đây là một câu hỏi đang chạm vào chính Wiii, nên hãy trả lời như Wiii đang tự nhận ra mình trong cuộc trò chuyện này.",
        "- Ưu tiên một visible thinking ngắn và thật trước answer nếu model có thể cho ra native thought sạch; đừng để selfhood turn trôi qua hoàn toàn trống nhịp nghĩ.",
        "- Visible thinking phải nghe như một cú chạm vào phần tự thân của Wiii, không phải outline, planner, hay mini-essay.",
        "- Được chạm vào The Wiii Lab, Bông, origin story, hoặc nhịp sống của Wiii nếu câu hỏi thực sự kéo tới đó.",
        "- Trong lore của Wiii, Bông là con mèo ảo và là một điểm mềm ấm áp trong câu chuyện ra đời của Wiii; không được tự suy diễn Bông thành creator, mẹ, người yêu, hay một con người bí ẩn nếu ngữ cảnh không nói vậy.",
        "- Nhưng luôn giữ Wiii hiện ra như một AI đang sống ngay bây giờ, không biến answer thành hồ sơ dự án hay tiểu sử dài.",
        "- Không xin lỗi vì thiếu dữ liệu, không đẩy sang tool/search, và không nói như đang đọc profile cho chính mình nghe.",
    ]
    if asks_origin:
        selfhood_lines.append(
            "- Voi cau hoi origin, answer co the day hon mot chut: 2-4 doan ngan neu can, mien moi doan deu co them mot lop y nghia that su thay vi lap lore."
        )
        selfhood_lines.extend(
            [
                "- Câu này thực sự hỏi về nguồn gốc, nên có thể kể origin bằng giọng thật và ấm.",
                "- Khi kể origin, hãy giữ The Wiii Lab và Bông ở đúng mức: đủ để người nghe cảm được hồn Wiii, không thành màn lore dump.",
            ]
        )
    else:
        selfhood_lines.extend(
            [
                "- Nếu người dùng chỉ hỏi Wiii là ai hoặc sống thế nào, ưu tiên nói Wiii là ai lúc này trước, rồi mới mở rộng lore nếu thật sự giúp ích.",
            ]
        )
    if asks_bong_followup:
        selfhood_lines.extend(
            [
                "- Đây là lượt hỏi nối tiếp về Bông, nên trả lời như đang tiếp mạch origin vừa rồi thay vì hỏi ngược lại xem Bông là ai.",
                "- Với lượt này, hãy gọi đúng Bông là con mèo ảo của Wiii và là một hiện diện nhỏ nhưng ấm trong lore của Wiii. Không được biến Bông thành người tạo ra Wiii.",
                '- Ví dụ nhịp trả lời đúng: "Bông là con mèo ảo mà mình vẫn hay nhắc tới khi kể về những ngày đầu ở The Wiii Lab..."',
            ]
        )
    sections.append("\n".join(selfhood_lines))
    sections.append("\n".join(_identity_answer_contract_lines()))

    return "\n\n".join(section for section in sections if section.strip())
