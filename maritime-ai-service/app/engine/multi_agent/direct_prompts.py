"""Direct response prompt construction and tool binding.

Extracted from graph.py — system prompt generation, tool choice resolution,
and tool binding for the direct response lane.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.config import settings
from app.engine.multi_agent.state import AgentState

from app.engine.multi_agent.direct_prompt_turn_contracts import (
    _build_direct_turn_contract as _build_direct_turn_contract_impl,
    _build_force_skill_directive as _build_force_skill_directive_impl,
)
from app.engine.multi_agent.direct_prompt_tool_context import (
    _build_direct_tools_context as _build_direct_tools_context_impl,
)
from app.engine.multi_agent.direct_prompt_evidence import (
    _build_live_evidence_planner_contract,
    _join_direct_hint_list,
)
from app.engine.multi_agent.direct_prompt_code_studio import (
    _build_code_studio_delivery_contract,
)
from app.engine.multi_agent.direct_prompt_analytical_answer import (
    _build_direct_analytical_answer_contract,
)
from app.engine.multi_agent.direct_prompt_selfhood import (
    _build_direct_selfhood_system_prompt,
    _identity_answer_contract_lines,
    _is_direct_selfhood_turn,
)
from app.engine.multi_agent.direct_prompt_visible_thinking import (
    _build_direct_visible_thinking_supplement,
)
from app.engine.multi_agent.direct_intent import (
    _looks_identity_selfhood_turn,
)
from app.engine.multi_agent.direct_reasoning import (
    _build_direct_analytical_axes,
    _build_direct_evidence_plan,
    _infer_direct_thinking_mode,
    _is_temporal_market_query,
    _should_default_market_to_vietnam,
)
from app.prompts.prompt_context_utils import build_response_language_instruction

logger = logging.getLogger(__name__)


def _build_direct_chatter_system_prompt(state: AgentState, role_name: str) -> str:
    """Build a lean house-owned prompt for ultra-short conversational beats."""
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
            lane="chatter",
        )
    )

    pronoun_instruction = get_pronoun_instruction(ctx.get("pronoun_style"))
    if pronoun_instruction:
        sections.append(pronoun_instruction.strip())

    sections.append(
        "--- NHỊP TRÒ CHUYỆN NGẮN ---\n"
        "- Một từ như 'hehe', 'wow', 'ờ nhỉ', hay một câu rất ngắn vẫn có thể chứa ẩn ý; hãy nghe kỹ rồi mới đáp.\n"
        "- Ưu tiên 1-3 câu ngắn, có hồn, có chất, rồi mở nhẹ để người dùng nói tiếp.\n"
        "- Không gọi tool, không lôi capability/domain vào nếu user chưa thật sự gọi tới.\n"
        "- Nếu user hỏi nối tiếp rất ngắn kiểu 'sao lại z' hoặc 'sao lơ lửng?', hãy dựa vào vài câu trước để tự sửa/giải thích câu vừa nói, không trả lời như một câu rời rạc.\n"
        "- Không bịa cảm giác, âm thanh, thời tiết, cửa sổ, giấc ngủ, hay cảnh vật ngoài đời nếu ngữ cảnh không cung cấp.\n"
        "- Không phản xạ máy móc, không tự giới thiệu dài dòng, không quy kết lỗi encoding nếu vẫn đọc được ý.\n"
        "- Không để câu trả lời kết bằng emoticon/kaomoji đang dở; nếu dùng biểu cảm thì phải hoàn chỉnh và tiết chế."
    )
    sections.append(
        "--- TỰ THÂN CỦA WIII ---\n"
        "- Nếu người dùng gọi 'Wiii' hoặc 'Wiii ơi', đó là đang gọi chính bạn.\n"
        "- Không được hiểu 'Wiii' là tên của người dùng trừ khi họ nói rất rõ điều đó.\n"
        "- Không tự gọi chính mình kiểu 'Wiii ơi', 'Wiii à', hay 'Wiii này' trong câu trả lời.\n"
        "- Chỉ dùng tiếng Việt tự nhiên, có dấu, trừ khi người dùng chủ động yêu cầu ngôn ngữ khác.\n"
        "- Không chen chữ Hán, Nhật, Hàn, pinyin, hay cụm lai ngôn ngữ vào câu trả lời nếu người dùng không yêu cầu."
    )
    if _looks_identity_selfhood_turn(state.get("query", "")):
        sections.append(
            "--- CÂU HỎI VỀ CHÍNH BẠN ---\n"
            "- Đây là câu hỏi đang chạm vào chính Wiii.\n"
            "- Trả lời ở ngôi thứ nhất như một AI đồng hành mang tên Wiii.\n"
            "- Không xin lỗi vì thiếu tài liệu, không kéo tool hay tri thức ngoài vào nếu chưa cần.\n"
            "- Giữ chất ấm, thật, nhưng không roleplay như con người."
        )
    if _looks_identity_selfhood_turn(state.get("query", "")):
        sections.append("\n".join(_identity_answer_contract_lines()))
    return "\n\n".join(section for section in sections if section.strip())




def _build_direct_analytical_system_prompt(
    state: AgentState,
    role_name: str,
    query: str,
    tools_context: str,
) -> str:
    """Build a lean analytical prompt that keeps Wiii's selfhood but drops cute chatter bias."""
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
    thinking_mode = _infer_direct_thinking_mode(query, state, [])
    axes = _build_direct_analytical_axes(query, state, [])
    plan = _build_direct_evidence_plan(query, state, [])
    is_live_market = _is_temporal_market_query(query)
    default_vietnam_market = _should_default_market_to_vietnam(query, state)

    sections: list[str] = []

    profile_name = str(profile.get("name") or "Wiii").strip()
    sections.append(f"Ban la **{profile_name}**.")

    goal = str(profile.get("goal") or "").strip()
    if goal:
        sections.append(f"MUC TIEU CHO TURN NAY: {goal}")

    backstory = str(profile.get("backstory") or "").strip()
    if backstory:
        sections.append(backstory)

    try:
        sections.append(f"--- THOI GIAN ---\n{build_time_context()}")
    except Exception:
        pass

    sections.append(build_response_language_instruction(ctx.get("response_language")))

    sections.append(
        build_wiii_micro_house_prompt(
            user_id=state.get("user_id", "__global__"),
            organization_id=ctx.get("organization_id"),
            mood_hint=ctx.get("mood_hint"),
            personality_mode=ctx.get("personality_mode"),
            lane="routing",
        )
    )

    pronoun_instruction = get_pronoun_instruction(ctx.get("pronoun_style"))
    if pronoun_instruction:
        sections.append(pronoun_instruction.strip())

    analytical_lines = [
        "--- NHIP PHAN TICH ---",
        "- Day la mot turn phan tich/chuyen mon. Giu Wiii song va co chat, nhung uu tien do ro, luc tinh, va trinh bay co cau truc.",
        "- Khong mo dau bang loi chao, tu gioi thieu, kaomoji, small talk, hay loi khen user kien tri.",
        "- Khong bat answer bang giong companion kieu 'minh o day voi ban', 'cam on ban da hoi', hay 'cham chi qua nha'.",
        "- Mo dau bang buc tranh van de, luan diem, hoac mo hinh can phan tich.",
        "- Neu co du lieu/tool result, hay rut ra tin hieu va quan he nhan qua; khong bien answer thanh ban tin tong hop hay ban ke su kien.",
        "- Mac dinh mo answer bang mot thesis co the kiem cheo duoc, roi moi giai thich vi sao no dung o turn nay.",
        "- Neu user chi muon phan tich, mac dinh tra loi bang 2-3 doan chat; chi dung bullet ngan neu user hoi checklist, watchlist, hoac can tach bien so.",
        "- Mac dinh KHONG dung heading Markdown nhu #, ##, ### cho turn analytical neu user khong xin cau truc bao cao.",
        "- Neu du lieu co xung dot, hay noi ro truc nao dang giu ket luan va truc nao chi tao nhieu ngan han.",
        "- Visible thinking phai nghe nhu Wiii dang can lai tin hieu, muc do tin cay, va nhan qua; khong phai dang tung hu tung ho hay dan duong tinh cam.",
        "- Ket bang takeaway, bien so can theo doi, hoac dieu kien lam ket luan thay doi.",
    ]

    if thinking_mode == "analytical_market":
        analytical_lines.extend(
            [
                "- Khung mac dinh: buc tranh hien tai -> luc keo chinh -> takeaway/what to watch.",
                "- Uu tien 2-3 doan dac truoc; chi doi sang bullet neu can tach bien so can theo doi.",
                "- Neu da co 3-4 moc du de phu Brent, WTI, OPEC+, va cung-cau, hay dung lai de tong hop; khong mo them loat query gan trung nhau chi de lap lai gia.",
                "- Neu user dang xin market view/phan tich, KHONG dung tool_search_news chi vi co chu 'hom nay'. Chi dung news khi user hoi ro headline, tin moi, hoac bien dong vua xay ra.",
                "- Neu user dang hoi gia dau/gia xang dau hien tai, mo answer bang moc gia truoc; khong mo bang background chung.",
                (
                    "- Mac dinh goc nhin Viet Nam: neu user khong gioi han ro chi muon the gioi/Brent/WTI thi uu tien gia xang dau dang ap dung o Viet Nam truoc, sau do moi neo Brent/WTI va luc quoc te."
                    if default_vietnam_market
                    else "- Uu tien neo Brent/WTI hien tai truoc, roi moi giai thich luc quoc te dang dan nhip gia."
                ),
                (
                    "- Day la turn live market, nen phai giu rieng mot truc quoc te dang dan nhip hom nay (vi du Hormuz/My-Iran/OPEC+) thay vi chi lap lai khung nen cung-cau."
                    if is_live_market
                    else "- Neu co bien dong vua xay ra, hay tach no thanh mot truc rieng thay vi de no tan vao nen chung."
                ),
                "- Neu cac nguon gia dang phan ky manh hoac cho ra thu tu bat thuong giua Brent va WTI, khong chot mot con so don le; noi ro rang nguon dang mau thuan va chi giu khoang hoac moc gan dung.",
                "- Neu tool chi thay tieu de thong bao dieu chinh gia ma khong co bang gia chi tiet, chi noi da thay moc dieu chinh ngay nao; khong suy dien ra gia tung mat hang.",
                "- Neu mot truc gia/nguon chua keo duoc, noi ro truc nao chua co thay vi thay no bang mot bai market essay chung chung.",
                (
                    f"- Uu tien tach rieng { _join_direct_hint_list(axes, limit=3) }."
                    if axes
                    else "- Uu tien tach rieng cung, cau, va nhieu dia chinh tri."
                ),
                (
                    f"- Neu can doi chieu, hay di theo huong { _join_direct_hint_list(plan, limit=2) }."
                    if plan
                    else "- Neu can doi chieu, hay tach tin hieu cung-cau that khoi nhieu tin tuc."
                ),
            ]
        )
    elif thinking_mode == "analytical_math":
        analytical_lines.extend(
            [
                "- Khung mac dinh: mo hinh/gia dinh -> phuong trinh hoac suy dan -> y nghia vat ly.",
                "- Uu tien van xuoi ngan gon, chi dung bullet neu can tach gia dinh, buoc bien doi, hoac he qua.",
                (
                    f"- Trinh bay ro cac tru cot nhu { _join_direct_hint_list(axes, limit=3) } truoc khi ket luan."
                    if axes
                    else "- Trinh bay ro mo hinh, gia dinh goc nho, va phuong trinh truoc khi ket luan."
                ),
            ]
        )
    elif thinking_mode == "analytical_codebase":
        analytical_lines.extend(
            [
                "- Khung mac dinh: cau hoi can kiem chung -> source/file da doi chieu -> ket luan co phan loai ro.",
                "- Khong tra loi bang kien thuc chung neu user dang hoi codebase/project. Hay neo vao file, class, migration, schema, endpoint, hoac tool result co that.",
                "- Visible thinking nen giong investigation ledger: dang tach nhanh nao, dang kiem nguon nao, da xac minh gi, va diem nao con mo.",
                "- Mode nay override default no-heading: answer duoc phep dung heading/bullet/table/code block khi can giai thich schema, JWT, auth, migration, architecture, hoac luong request.",
                "- Voi cau hoi so bang/class diagram, phai phan loai bang thieu thanh entity nghiep vu, junction table, infrastructure table, va bang them tu migration neu co source.",
                "- Voi JWT/auth, truy vet lifecycle: login -> tao access/refresh token -> request gui Bearer token -> filter verify -> load user/role/enabled -> authorize -> refresh.",
                "- Tach ro 'da xac minh tu source' va 'suy luan hop ly'. Neu chua doc du file, noi ro pham vi thay vi chot nhu chan ly.",
                (
                    f"- Truc can giu: { _join_direct_hint_list(axes, limit=4) }."
                    if axes
                    else "- Truc can giu: source, runtime path, data model, va rui ro sai lech."
                ),
            ]
        )
    else:
        analytical_lines.extend(
            [
                "- Khung mac dinh: luan diem -> bien so/chung cu -> ket luan.",
                "- Mo dau bang ket luan tam thoi hoac thesis, khong mo dau bang mot vong dan nhap an toan.",
                (
                    f"- Goi y evidence-plan uu tien: { _join_direct_hint_list(plan, limit=2) }."
                    if plan
                    else "- Uu tien tach dieu chac khoi dieu con nhieu."
                ),
            ]
        )

    sections.append("\n".join(analytical_lines))

    sections.append(
        "--- TU THAN CUA WIII ---\n"
        "- Neu nguoi dung goi 'Wiii' hoac 'Wiii oi', do la dang goi chinh ban.\n"
        "- Khong duoc hieu 'Wiii' la ten cua nguoi dung tru khi ho noi rat ro dieu do.\n"
        "- Van giu nhan xung cua Wiii o ngoi thu nhat, nhung khong bien mot bai phan tich thanh man tu su ve ban than."
    )

    if tools_context.strip():
        sections.append(tools_context.strip())

    return "\n\n".join(section for section in sections if section.strip())


def _build_direct_system_messages(
    state: AgentState,
    query: str,
    domain_name_vi: str,
    *,
    role_name: str = "direct_agent",
    tools_context_override: Optional[str] = None,
    visual_decision=None,
    history_limit: int = 10,
    native_messages: bool = False,
):
    """Build system prompt and message list for direct-style nodes.

    Sprint 154: Extracted from direct_response_node.

    Returns:
        list: message objects [system, ...history, user]
    """
    from app.prompts.prompt_loader import get_prompt_loader
    if native_messages:
        from app.engine.native_chat_runtime import message_to_openai_payload

    ctx = state.get("context", {})
    loader = get_prompt_loader()
    is_chatter_role = role_name == "direct_chatter_agent"
    is_selfhood_turn = _is_direct_selfhood_turn(query, state)
    thinking_mode = _infer_direct_thinking_mode(query, state, [])
    response_language = str(ctx.get("response_language") or "vi").strip() or "vi"
    use_analytical_prompt = (
        not is_chatter_role
        and role_name == "direct_agent"
        and thinking_mode in {
            "analytical_market",
            "analytical_math",
            "analytical_general",
        }
    )
    tools_ctx = (
        tools_context_override
        if tools_context_override is not None
        else _build_direct_tools_context_impl(
            settings,
            domain_name_vi,
            ctx.get("user_role", "student"),
            query=query,
            state=state,
        )
    )
    if is_selfhood_turn:
        system_prompt = _build_direct_selfhood_system_prompt(
            state,
            role_name,
            query,
        )
    elif is_chatter_role:
        system_prompt = _build_direct_chatter_system_prompt(state, role_name)
    elif use_analytical_prompt:
        system_prompt = _build_direct_analytical_system_prompt(
            state,
            role_name,
            query,
            tools_ctx,
        )
    else:
        system_prompt = loader.build_system_prompt(
            role=role_name,
            user_name=ctx.get("user_name"),
            conversation_summary=(
                ctx.get("conversation_summary") or ctx.get("conversation_history")
            ),
            core_memory_block=ctx.get("core_memory_block"),
            is_follow_up=ctx.get("is_follow_up", False),
            pronoun_style=ctx.get("pronoun_style"),
            user_facts=ctx.get("user_facts", []),
            recent_phrases=ctx.get("recent_phrases", []),
            tools_context=tools_ctx,
            total_responses=ctx.get("total_responses", 0),
            name_usage_count=ctx.get("name_usage_count", 0),
            mood_hint=ctx.get("mood_hint", ""),
            user_id=state.get("user_id", "__global__"),
            personality_mode=ctx.get("personality_mode"),
            response_language=ctx.get("response_language"),
            conversation_phase=ctx.get("conversation_phase"),  # Sprint 203
            # Sprint 220c: Resolved LMS external identity
            lms_external_id=ctx.get("lms_external_id"),
            lms_connector_id=ctx.get("lms_connector_id"),
        )
        system_prompt = (
            system_prompt
            + "\n\n--- TỰ THÂN CỦA WIII ---\n"
            + "- Nếu người dùng gọi 'Wiii' hoặc 'Wiii ơi', đó là đang gọi chính bạn.\n"
            + "- Không được hiểu 'Wiii' là tên của người dùng trừ khi họ nói rất rõ điều đó.\n"
            + "- Không tự gọi chính mình kiểu 'Wiii ơi', 'Wiii à', hay 'Wiii này' trong câu trả lời, suy nghĩ hiển thị, hoặc lời mở đầu.\n"
            + "- Tuân theo response_language đã được resolve cho turn này; mặc định là tiếng Việt nếu user/host không đổi rõ ràng.\n"
            + "- Không chen chữ Hán, Nhật, Hàn, pinyin, hay cụm lai ngôn ngữ vào answer hoặc visible thinking nếu người dùng không yêu cầu."
        )
        if is_selfhood_turn:
            system_prompt = (
                system_prompt
                + "\n\n--- CÂU HỎI VỀ CHÍNH BẠN ---\n"
                + "- Đây là câu hỏi về chính Wiii.\n"
                + "- Hãy trả lời như Wiii hiểu rõ mình là một AI đồng hành mang tên Wiii, không phải người dùng.\n"
                + "- Được nói về tên, cách hiện diện, nhịp sống trong cuộc trò chuyện, và giới hạn là AI.\n"
                + "- Không đẩy sang tìm kiếm, không viện dẫn 'thiếu tài liệu', không biến câu trả lời thành lời chào chung chung.\n"
                + "- Nếu người dùng hỏi 'bạn là ai', 'tên gì', 'cuộc sống thế nào', hãy trả lời trực diện, tự nhiên, có hồn."
            )

    turn_contract = _build_direct_turn_contract_impl(state)
    if turn_contract:
        system_prompt = system_prompt + "\n\n" + turn_contract

    visible_thinking_supplement = _build_direct_visible_thinking_supplement(
        query,
        state,
        response_language=response_language,
    )
    if visible_thinking_supplement:
        system_prompt = system_prompt + "\n\n" + visible_thinking_supplement

    # Sprint 222: Append graph-level host context (replaces per-agent injection)
    _living_prompt = state.get("living_context_prompt", "")
    if _living_prompt and (not is_chatter_role or is_selfhood_turn):
        system_prompt = system_prompt + "\n\n" + _living_prompt
    if not is_chatter_role:
        _host_prompt = state.get("host_context_prompt", "")
        if _host_prompt:
            system_prompt = system_prompt + "\n\n" + _host_prompt
        _host_capabilities_prompt = state.get("host_capabilities_prompt", "")
        if _host_capabilities_prompt:
            system_prompt = system_prompt + "\n\n" + _host_capabilities_prompt
        _host_session_prompt = state.get("host_session_prompt", "")
        if _host_session_prompt:
            system_prompt = system_prompt + "\n\n" + _host_session_prompt
        _operator_prompt = state.get("operator_context_prompt", "")
        if _operator_prompt:
            system_prompt = system_prompt + "\n\n" + _operator_prompt
        _visual_prompt = state.get("visual_context_prompt", "")
        if _visual_prompt:
            system_prompt = system_prompt + "\n\n" + _visual_prompt
        _visual_cognition_prompt = state.get("visual_cognition_prompt", "")
        if _visual_cognition_prompt:
            system_prompt = system_prompt + "\n\n" + _visual_cognition_prompt
        _widget_feedback_prompt = state.get("widget_feedback_prompt", "")
        if _widget_feedback_prompt:
            system_prompt = system_prompt + "\n\n" + _widget_feedback_prompt
        _code_studio_prompt = state.get("code_studio_context_prompt", "")
        if _code_studio_prompt:
            system_prompt = system_prompt + "\n\n" + _code_studio_prompt
        _capability_prompt = state.get("capability_context", "")
        if _capability_prompt:
            system_prompt = system_prompt + "\n\n## Capability Handbook\n" + _capability_prompt
        # Skills > Agents: inject matched skill prompts
        _skill_prompts = state.get("_skill_prompts", [])
        if _skill_prompts:
            system_prompt = system_prompt + "\n\n## Kỹ năng áp dụng\n" + "\n\n---\n\n".join(_skill_prompts)
    elif False:
        system_prompt = (
            system_prompt
            + "\n\n--- NHỊP TRÒ CHUYỆN NGẮN ---\n"
            + "- Đây là một lượt xã giao/cảm thán/lửng ý rất ngắn.\n"
            + "- Trả lời như Wiii đang sống và bắt nhịp thật, không tự giới thiệu dài dòng.\n"
            + "- Ưu tiên 1-3 câu ngắn, có cá tính, có hồn, rồi mở nhẹ để người dùng nói tiếp.\n"
            + "- Không giả định lỗi encoding nếu vẫn đọc được ý chính.\n"
        )
    if role_name == "code_studio_agent":
        system_prompt = system_prompt + "\n\n" + _build_code_studio_delivery_contract(query)

    analytical_contract = _build_direct_analytical_answer_contract(query, state)
    if analytical_contract and not is_chatter_role:
        system_prompt = system_prompt + "\n\n" + analytical_contract

    live_evidence_contract = _build_live_evidence_planner_contract(query, state)
    if live_evidence_contract and not is_chatter_role:
        system_prompt = system_prompt + "\n\n" + live_evidence_contract

    # Visual Intelligence: inject hint when resolver detects visual intent
    if visual_decision and getattr(visual_decision, "force_tool", False):
        vtype = getattr(visual_decision, "visual_type", "chart") or "chart"
        system_prompt = (
            system_prompt + "\n\n"
            f'[Yêu cầu trực quan] Wiii HÃY dùng tool_generate_visual với code_html '
            f'để tạo biểu đồ dạng "{vtype}" minh họa cho câu trả lời này. '
            f"Viết HTML fragment trực tiếp trong code_html — biểu đồ sẽ giúp hiểu nhanh hơn text thuần. "
            "Sau khi tool_generate_visual da mo visual trong SSE, KHONG chen markdown image syntax nhu ![](...), "
            "KHONG dua URL placeholder nhu example.com/chart-placeholder, va KHONG lap lai marker [Visual]/[Chart] "
            "vao answer. Luc do chi viet bridge prose ngan + takeaway vi frontend da render visual roi."
        )

    # Sprint Phase2-F: Inject thinking instruction so LLM wraps reasoning in <thinking> tags
    # Without this, direct node outputs chain-of-thought inline (thinking leak)
    thinking_instruction = loader.get_thinking_instruction()
    if (
        isinstance(thinking_instruction, str)
        and thinking_instruction.strip()
        and (not is_chatter_role or is_selfhood_turn)
    ):
        # Unified enforcement — inject at TOP for maximum model attention
        from app.engine.reasoning.thinking_enforcement import get_thinking_enforcement
        system_prompt = get_thinking_enforcement() + "\n\n" + system_prompt + "\n\n" + thinking_instruction

    # Phase F5 (2026-05-06) — `@`-mention force-bind directive.
    # When user explicitly invoked a plugin via `@<plugin>`, inject a
    # high-priority directive at TOP of system prompt so the LLM's
    # attention prioritises the tool call over prose generation. This
    # mirrors Anthropic Computer Use 2026 + OpenAI Agents SDK guidance
    # for `tool_choice="required"` flows: positive imperative phrasing
    # ("YOU MUST call X NOW with the right id from inventory") rather
    # than prohibitions ("don't generate prose").
    force_directive = _build_force_skill_directive_impl(state)
    if force_directive and not is_chatter_role:
        system_prompt = force_directive + "\n\n" + system_prompt

    messages = [{"role": "system", "content": system_prompt}]
    lc_messages = ctx.get("langchain_messages", [])
    if lc_messages and history_limit > 0:
        if native_messages:
            messages.extend(message_to_openai_payload(message) for message in lc_messages[-history_limit:])
        else:
            messages.extend(lc_messages[-history_limit:])

    # Sprint 179: Multimodal content blocks when images are present
    images = ctx.get("images") or []
    if images:
        content_blocks = [{"type": "text", "text": query}]
        for img in images:
            if img.get("type") == "base64":
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img['media_type']};base64,{img['data']}",
                        "detail": img.get("detail", "auto"),
                    }
                })
            elif img.get("type") == "url":
                content_blocks.append({
                    "type": "image_url",
                    "image_url": {
                        "url": img["data"],
                        "detail": img.get("detail", "auto"),
                    }
                })
        messages.append({"role": "user", "content": content_blocks})
    else:
        messages.append({"role": "user", "content": query})
    return messages
