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
from app.engine.multi_agent.direct_prompt_selfhood import (
    _build_direct_selfhood_system_prompt,
    _identity_answer_contract_lines,
    _is_direct_selfhood_turn,
)
from app.engine.multi_agent.direct_intent import (
    _looks_identity_selfhood_turn,
    _normalize_for_intent,
)
from app.engine.multi_agent.direct_evidence_planner import build_direct_evidence_plan
from app.engine.multi_agent.direct_reasoning import (
    _build_direct_analytical_axes,
    _build_direct_evidence_plan,
    _infer_direct_thinking_mode,
    _is_codebase_analysis_query,
    _is_temporal_market_query,
    _should_default_market_to_vietnam,
)
from app.prompts.prompt_context_utils import build_response_language_instruction

logger = logging.getLogger(__name__)


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


def _load_domain_thinking_examples(state: AgentState) -> list[dict]:
    """Load thinking examples from YAML skills matched to current context."""
    try:
        context = state.get("context") or {}
        host_type = str(context.get("host_type") or "generic").strip().lower()
        page_type = str(context.get("page_type") or "*").strip().lower()
        user_role = str(context.get("user_role") or "").strip().lower() or None

        from app.engine.context.skill_loader import get_skill_loader
        loader = get_skill_loader()
        skills = loader.load_skills(host_type, page_type, user_role=user_role)
        return loader.get_thinking_examples(skills)
    except Exception:
        return []


def _build_direct_visible_thinking_supplement(
    query: str,
    state: AgentState,
    *,
    response_language: str | None,
) -> str:
    """Return a minimal thinking nudge — LLM-first, trust the model.

    No rules, no if/else routing. Just a gentle invitation to think
    and one domain example for flavour. The model decides the rest.
    """

    normalized_language = str(response_language or "vi").strip().lower() or "vi"
    lang = "tiếng Việt" if normalized_language.startswith("vi") else normalized_language

    lines = [
        "--- VISIBLE THINKING ---",
        "- Day la public working-note, khong phai raw hidden chain-of-thought: hay noi ro cach kiem chung, nguon dang doi chieu, va muc do chac; khong lo system prompt, secret, hay suy luan noi bo thua.",
        "- Neu task kho hoac can source-backed, thinking duoc phep dai hon vai cau mien la moi cau them mot bang chung/huong kiem tra that, khong lap lai answer.",
        f"Nghĩ bằng {lang}, tự nhiên, vài câu thật. Nếu model có native thinking thì dùng luôn, không thì đặt trong <thinking>...</thinking> trước khi trả lời.",
        "",
        "Ví dụ cách nghĩ:",
        '[User] "Quy tắc 15 COLREGs là gì?"',
        '[Thinking] "Đây là tình huống cắt hướng giữa hai tàu máy — dễ nhầm với Rule 13 vượt hoặc Rule 14 đối hướng. Mình cần phân biệt rõ điều kiện áp dụng trước khi giải thích."',
    ]

    # One random domain example, if available — for flavour, not prescription.
    if _is_codebase_analysis_query(query):
        lines.extend(
            [
                "",
                "Voi turn codebase/schema/auth/source-backed:",
                "- Thinking phai la ledger kiem chung: tach cau hoi thanh cac nhanh, neu file/schema/migration/tool can doc, neu da xac minh gi, va diem nao con la inference.",
                "- Moi beat nen co danh tu cu the tu task (vi du: migration, table, entity, JWT, JwtService, filter, controller, repository, schema). Tranh cau chung chung kieu 'minh can phan tich ky'.",
                "- Neu dang doi chieu so bang/class diagram/JWT/auth, hay noi ro dang kiem ke source nao truoc khi ket luan; day la phan lam Wiii co chat xam, khong phai trang tri UX.",
                '[User] "Vi sao database co hon 60 bang ma class diagram chi hien 25 bang? Giai thich JWT lien quan file nao."',
                '[Thinking] "Minh dang tach cau hoi thanh hai duong kiem chung: mot la kiem ke schema/migration de phan nhom bang nghiep vu, junction va ha tang; hai la truy vet luong JWT tu login/controller sang JwtService va filter moi request. Ket luan chi nen chot sau khi noi ro bang nao la entity chinh, bang nao chi noi quan he, va file nao that su tham gia xac thuc."',
            ]
        )

    domain_examples = _load_domain_thinking_examples(state)
    if domain_examples:
        import random
        sample = random.choice(domain_examples)
        ctx = sample.get("context", "")
        thinking = sample.get("thinking", "")
        if ctx and thinking:
            lines.append(f'[Thinking khi {ctx}] "{thinking}"')

    return "\n".join(lines)

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
        "- Không phản xạ máy móc, không tự giới thiệu dài dòng, không quy kết lỗi encoding nếu vẫn đọc được ý."
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


def _build_code_studio_delivery_contract(query: str) -> str:
    """Role-local answer contract for delivery-first technical responses."""
    normalized = _normalize_for_intent(query)
    is_chart_request = any(
        token in normalized
        for token in ("bieu do", "chart", "plot", "matplotlib", "seaborn", "png", "svg")
    )
    is_html_request = any(
        token in normalized
        for token in ("html", "landing page", "website", "web app", "microsite", "trang web")
    )

    lines = [
        "## CODE STUDIO DELIVERY CONTRACT:",
        "- Voi tac vu ky thuat, mo dau answer bang ket qua da tao hoac da xac nhan. Khong mo dau bang loi chao, tu gioi thieu, hay small talk.",
        "- Khi vua tao artifact, neu ro ten file, loai san pham, va dieu nguoi dung co the mo ra ngay luc nay.",
        "- Neu yeu cau chua du du lieu cu the, tao mot demo trung tinh phu hop voi task va noi ro do la demo. Khong bien no thanh lore ca nhan cua Wiii.",
        "- Khong dua nhan vat phu, thu cung ao, catchphrase, hay chi tiet de thuong khong lien quan vao output ky thuat neu user khong yeu cau.",
        "- Uu tien 3 phan theo thu tu: da tao gi, no dung de lam gi, nguoi dung co the lam gi tiep theo.",
    ]
    if is_chart_request:
        lines.append(
            "- Voi yeu cau bieu do/chart mo ho, uu tien tao mot chart demo trung tinh va giao lai file PNG that (neu co sandbox), hoac Mermaid SVG khi khong co sandbox."
        )
    if is_html_request:
        lines.append(
            "- Voi yeu cau landing page/HTML, tao file HTML that va mo ta ro nhung gi nguoi dung co the xem/mo ngay."
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


def _build_direct_analytical_answer_contract(query: str, state: AgentState) -> str:
    """Role-local answer contract for analytical direct turns.

    This is appended late so it can override the warmer house voice when the
    user is clearly asking for analysis rather than companionship or small talk.
    """
    thinking_mode = _infer_direct_thinking_mode(query, state, [])
    if thinking_mode not in {
        "analytical_market",
        "analytical_math",
        "analytical_codebase",
        "analytical_general",
    }:
        return ""

    axes = _build_direct_analytical_axes(query, state, [])
    plan = _build_direct_evidence_plan(query, state, [])
    axes_text = _join_direct_hint_list(axes, limit=3)
    plan_text = _join_direct_hint_list(plan, limit=2)
    is_live_market = _is_temporal_market_query(query)
    default_vietnam_market = _should_default_market_to_vietnam(query, state)

    lines = [
        "## ANALYTICAL RESPONSE CONTRACT:",
        "- Day la turn phan tich. Khong mo dau bang loi chao, tu gioi thieu, kaomoji, small talk, hay loi khen user kien tri.",
        "- Khong mo dau bang quan he hoa kieu 'minh thay ban...', 'minh rat muon dong hanh...', hay 'cam on ban da hoi'. Di thang vao van de.",
        "- Khong xin loi dai dong vi thieu du lieu thoi gian thuc neu da co ket qua tool hoac da co khung phan tich du de tra loi.",
        "- Neu can neu gioi han du lieu, chi noi gon trong 1 cau roi quay lai phan tich ngay.",
        "- Mo dau bang nhan dinh, khung van de, hoac buc tranh hien tai. Khong mo dau bang cam than, emo, hay tu than mat.",
        "- Khi da co tool result, hay rut ra tin hieu chinh tu du lieu do. Khong chi liet ke nguon va khong bien answer thanh ban tin tong hop.",
        "- Mac dinh mo dau bang 1 cau thesis co the kiem cheo duoc, sau do moi giai thich can nang cua tung truc.",
        "- Mac dinh uu tien 2-4 doan dac. Chi dung bullet ngan neu user can checklist, watchlist, hoac can tach cac bien so rieng. Khong tu dong bien answer thanh bai viet dai co heading Markdown neu user chi hoi phan tich.",
        "- Mac dinh KHONG dung heading Markdown nhu #, ##, ### trong answer analytical tru khi user xin ro rang mot bao cao/co cau truc tai lieu.",
        "- Mac dinh KHONG dung danh sach dam/net bold nhu mot ban tom tat tin tuc neu user khong yeu cau.",
        "- Ket answer bang takeaway hoac dieu can theo doi tiep theo. Khong hoi nguoc theo kieu small talk neu user chua can.",
    ]

    if thinking_mode == "analytical_market":
        lines.extend(
            [
                "- Khung uu tien: buc tranh hien tai -> cac luc keo chinh -> takeaway/what to watch.",
                "- Neu cac tin hieu xung nhau, noi ro truc nao dang giu mat bang gia va truc nao chi tao nhieu ngan han.",
                "- Neu user dang hoi gia dau/gia xang dau hien tai, mo answer bang moc gia truoc; khong mo bang background chung.",
                (
                    "- Mac dinh goc nhin Viet Nam: neu user khong gioi han ro chi muon the gioi/Brent/WTI thi uu tien gia xang dau dang ap dung o Viet Nam truoc, sau do moi neo Brent/WTI va luc quoc te."
                    if default_vietnam_market
                    else "- Uu tien moc Brent/WTI hien tai truoc, roi moi giai thich luc quoc te dang giu nhip gia."
                ),
                (
                    "- Van phai giu rieng mot truc quoc te dang dan nhip hom nay (vi du Hormuz/My-Iran/OPEC+) thay vi chi lap lai nen cung-cau."
                    if is_live_market
                    else "- Neu co bien dong vua xay ra, hay tach no thanh mot truc rieng thay vi de no tan vao nen chung."
                ),
                "- Neu cac nguon gia dang phan ky manh hoac cho ra thu tu bat thuong giua Brent va WTI, khong chot mot con so don le; noi ro nguon dang mau thuan va chi giu khoang hoac moc gan dung.",
                "- Neu chi thay tieu de thong bao dieu chinh gia ma khong co bang gia chi tiet, chi noi da thay moc dieu chinh ngay nao; khong suy dien ra gia tung mat hang.",
                "- Neu mot truc gia/nguon chua keo duoc, noi ro truc nao chua co thay vi thay no bang mot bai market essay chung chung.",
                (
                    f"- Uu tien tach rieng {axes_text}."
                    if axes_text
                    else "- Uu tien tach rieng cung, cau, va nhieu dia chinh tri thay vi gom vao mot nhan tang/giam."
                ),
                (
                    f"- Neu can kiem cheo, hay dua tren {plan_text}."
                    if plan_text
                    else "- Neu can kiem cheo, hay phan biet dau hieu cung-cau that voi phan nhieu do tin tuc."
                ),
            ]
        )
    elif thinking_mode == "analytical_math":
        lines.extend(
            [
                "- Khung uu tien: mo hinh va gia dinh -> phuong trinh/derivation -> y nghia vat ly.",
                "- Neu ket luan phu thuoc gan dung, noi ro pham vi ma gan dung do con hop le.",
                (
                    f"- Truoc khi ket luan, phai chot ro {axes_text}."
                    if axes_text
                    else "- Truoc khi ket luan, phai chot ro mo hinh, gia dinh goc nho, va phuong trinh."
                ),
                "- Neu cong thuc phu thuoc gia dinh, noi ro gia dinh do ngay trong than bai.",
            ]
        )
    elif thinking_mode == "analytical_codebase":
        lines.extend(
            [
                "- Khung uu tien: tra loi truc tiep -> bang chung source-backed -> phan loai/truy vet -> caveat neu co.",
                "- Neu user hoi vi sao class diagram/table count/schema lech nhau, hay phan loai missing pieces thanh entity chinh, junction table, infrastructure table, migration-added table.",
                "- Neu user hoi JWT/auth, hay giai thich lifecycle theo thu tu request that: login -> tao access/refresh token -> Bearer request -> auth filter -> DB user/role/enabled -> authorization -> refresh.",
                "- Dua file/class/function/table name cu the khi co trong context/tool result. Khong viet nhu encyclopedia chung.",
                "- Mode nay override default no-heading: duoc dung heading Markdown, bang compact, va code block ngan de giu cau tra loi doc duoc nhu mot mini-report.",
                "- Moi khang dinh quan trong can co dau vet: source da doc, ten file/class/table, hoac noi ro la inference hop ly.",
                "- Chat xam cua answer nam o viec phan loai va doi chieu source, khong nam o cau van dai.",
            ]
        )
    else:
        lines.extend(
            [
                "- Khung uu tien: luan diem -> bien so/chung cu -> ket luan.",
                "- Neu co tin hieu trai chieu, noi ro cai nao dang nang ky hon thay vi gom tat ca vao mot ket luan mem.",
                (
                    f"- Uu tien kiem cheo theo huong {plan_text}."
                    if plan_text
                    else "- Uu tien tach dieu chac khoi dieu con nhieu va noi ro bien so dang chi phoi ket luan."
                ),
            ]
        )

    return "\n".join(lines)


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
