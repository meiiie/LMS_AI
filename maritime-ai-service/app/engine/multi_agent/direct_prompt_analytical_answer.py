"""Late answer contracts for analytical direct turns."""

from __future__ import annotations

from app.engine.multi_agent.direct_prompt_evidence import _join_direct_hint_list
from app.engine.multi_agent.direct_reasoning import (
    _build_direct_analytical_axes,
    _build_direct_evidence_plan,
    _infer_direct_thinking_mode,
    _is_temporal_market_query,
    _should_default_market_to_vietnam,
)
from app.engine.multi_agent.state import AgentState


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
