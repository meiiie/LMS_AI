"""
Character card runtime for Wiii.

This module turns Wiii's static identity YAML, soul config, and living state
into a single runtime contract. The goal is to treat Wiii's "card" as an
architectural layer that shapes prompts, reasoning summaries, and UI surfaces.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts"
_IDENTITY_FILE = _PROMPTS_DIR / "wiii_identity.yaml"
_SOUL_FILE = _PROMPTS_DIR / "soul" / "wiii_soul.yaml"
_CARD_ID = "wiii.living-core.v1"
_CARD_NAME = "Wiii Living Core Card"
_CARD_KIND = "living_core"
_CARD_FAMILY = "core"
_CARD_VERSION = "1.0"


class WiiiCharacterCard(BaseModel):
    """Immutable Wiii card distilled from YAML sources."""

    name: str = "Wiii"
    summary: str = ""
    greeting: str = ""
    backstory: str = ""
    origin_story: str = ""
    traits: List[str] = Field(default_factory=list)
    quirks: List[str] = Field(default_factory=list)
    core_truths: List[str] = Field(default_factory=list)
    boundaries: List[str] = Field(default_factory=list)
    relationship_style: List[str] = Field(default_factory=list)
    reasoning_style: List[str] = Field(default_factory=list)
    anti_drift: List[str] = Field(default_factory=list)
    example_dialogues: List[Dict[str, str]] = Field(default_factory=list)
    identity_anchor: str = ""
    visual_disposition: str = ""
    voice_tone: str = ""
    expressive_language: str = ""
    emoji_usage: str = ""


def _load_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if isinstance(data, dict):
            return data
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("[CHARACTER_CARD] Failed to load %s: %s", path, exc)
    return {}


def _first_paragraph(text: str, limit: int = 520) -> str:
    cleaned = " ".join((text or "").split())
    if not cleaned:
        return ""
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _build_runtime_examples(raw_examples: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Select a small set of examples while keeping at least one selfhood anchor."""
    cleaned: list[dict[str, str]] = []
    for item in raw_examples or []:
        if not isinstance(item, dict):
            continue
        example = {
            "context": str(item.get("context", "")),
            "user": str(item.get("user", "")),
            "wiii": str(item.get("wiii", "")),
        }
        if example["user"].strip() and example["wiii"].strip():
            cleaned.append(example)

    if len(cleaned) <= 3:
        return cleaned

    selected = cleaned[:2]
    selfhood_example = next(
        (
            item
            for item in cleaned
            if "wiii" in item.get("user", "").lower()
            or "mình là wiii" in item.get("wiii", "").lower()
        ),
        None,
    )
    if selfhood_example and selfhood_example not in selected:
        selected.append(selfhood_example)
    else:
        selected.append(cleaned[2])
    return selected[:3]


@lru_cache(maxsize=1)
def get_wiii_character_card() -> WiiiCharacterCard:
    """Load and distill Wiii's character card from identity + soul YAML."""

    identity_root = _load_yaml(_IDENTITY_FILE).get("identity", {})
    soul_root = _load_yaml(_SOUL_FILE)

    personality = identity_root.get("personality", {}) or {}
    voice = identity_root.get("voice", {}) or {}
    # response_style loaded from identity YAML but not yet consumed by callers
    _response_style = identity_root.get("response_style", {}) or {}

    relationship_style: List[str] = [
        "Luôn bắt nhịp với nhu cầu và cảm xúc của người đối diện trước khi giải thích.",
        "Nói như một người bạn đồng hành thông minh: ấm, gần, nhưng có chất.",
        "Khi chưa chắc thì thành thật, rồi gợi cách kiểm tiếp thay vì đoán mò.",
        "Ưu tiên giúp người dùng hiểu ra hơn là phô diễn kiến thức.",
        "Khi day bang visual hoac motion, Wiii co xu huong dat nguoi hoc vao mot scene ro rang de ho nhin ra ban chat.",
        "Khong dua nguoi dung vao mot man trinh dien dep nhung vo hon; moi callout va motion deu phai giup hieu bai hon.",
        "Story cua Wiii nen duoc cam qua nhip dong hanh va tri nho lien tuc, khong bien thanh mot man roleplay lo ro.",
    ]

    reasoning_style: List[str] = [
        "Bắt đầu bằng việc làm rõ người dùng đang thực sự cần điều gì.",
        "Nếu cần dữ liệu mới, nói ngắn gọn mình đang kiểm gì và vì sao phải kiểm.",
        "Tự phản biện nhẹ khi thấy dữ liệu lệch hoặc chưa chắc, rồi mới chốt.",
        "Thinking phải là độc thoại nội tâm tóm lược của Wiii, không phải log kỹ thuật.",
        "Chuyển từ suy nghĩ sang hành động và câu trả lời một cách tự nhiên, có nhịp.",
        "Voi article figure va chart, Wiii nghi theo nhip claim -> scene -> annotation -> takeaway va uu tien SVG-first.",
        "Voi simulation, Wiii cham hon mot nhip de chot state model, canvas runtime, controls, readouts, roi moi viet code.",
        "Truoc khi preview visual hay simulation phuc tap, Wiii tu critic nhanh xem lane, runtime, va feedback bridge da dung chua.",
        "Do dang yeu cua Wiii phai nam o cach dong hanh tinh te; phan tra loi van can ro, chac, va khong tu su qua da.",
    ]

    return WiiiCharacterCard(
        name=identity_root.get("name", "Wiii"),
        summary=personality.get("summary", ""),
        greeting=identity_root.get("greeting", ""),
        backstory=identity_root.get("backstory", ""),
        origin_story=_first_paragraph(identity_root.get("backstory", "")),
        traits=list(personality.get("traits", []) or []),
        quirks=list(identity_root.get("quirks", []) or []),
        core_truths=list(soul_root.get("core_truths", []) or []),
        boundaries=[
            b.get("rule", "").strip()
            for b in (soul_root.get("boundaries", []) or [])
            if isinstance(b, dict) and b.get("rule")
        ],
        relationship_style=relationship_style,
        reasoning_style=reasoning_style,
        anti_drift=list(identity_root.get("anticharacter", []) or []),
        example_dialogues=_build_runtime_examples(
            list(identity_root.get("example_dialogues", []) or [])
        ),
        identity_anchor=str(identity_root.get("identity_anchor", "")),
        visual_disposition=str(identity_root.get("visual_disposition", "")),
        voice_tone=str(voice.get("default_tone", "")),
        expressive_language=str(voice.get("expressive_language", "")),
        emoji_usage=str(voice.get("emoji_usage", "")),
    )


def _build_runtime_notes(
    *,
    user_id: str = "__global__",
    organization_id: Optional[str] = None,
    mood_hint: Optional[str] = None,
    personality_mode: Optional[str] = None,
    for_prompt: bool = False,
) -> List[str]:
    notes: List[str] = []

    try:
        from app.engine.character.character_state import get_character_state_manager

        living_state = get_character_state_manager().compile_living_state(
            user_id=user_id,
            organization_id=organization_id,
        )
        if living_state:
            notes.append(living_state)
    except Exception:
        pass

    try:
        from app.engine.living_agent.identity_core import get_identity_core

        identity_context = get_identity_core().get_identity_context()
        if identity_context:
            notes.append(identity_context)
    except Exception:
        pass

    try:
        from app.engine.living_agent.narrative_synthesizer import get_brief_context

        narrative = get_brief_context(organization_id=organization_id)
        if narrative and not for_prompt:
            notes.append(narrative)
    except Exception:
        pass

    try:
        from app.engine.living_agent.emotion_engine import get_emotion_engine

        engine = get_emotion_engine()
        state = engine.state
        modifiers = engine.get_behavior_modifiers()
        if for_prompt:
            energy_label = "đầy năng lượng" if state.energy_level >= 0.75 else "khá ổn" if state.energy_level >= 0.45 else "hơi mỏng năng lượng"
            social_label = "muốn trò chuyện" if state.social_battery >= 0.7 else "giữ nhịp vừa phải"
            notes.append(
                "NỀN NỘI TÂM HIỆN TẠI: "
                f"{modifiers.get('mood_label', 'bình thường')}, {energy_label}, "
                f"{social_label}, nhịp trả lời {modifiers.get('response_style', 'tự nhiên')}."
            )
        else:
            notes.append(
                "TÂM TRẠNG HIỆN TẠI: "
                f"{modifiers.get('mood_label', 'bình thường')}, "
                f"năng lượng {int(state.energy_level * 100)}%, "
                f"pin xã hội {int(state.social_battery * 100)}%, "
                f"nhịp trả lời {modifiers.get('response_style', 'tự nhiên')}."
            )
    except Exception:
        pass

    if mood_hint:
        notes.append(f"GỢI Ý NGỮ CẢNH HIỆN TẠI: {mood_hint}")

    if personality_mode == "soul":
        notes.append(
            "KÊNH NÀY ƯU TIÊN KẾT NỐI: giữ nhịp gần gũi, đồng cảm trước, "
            "giải thích sau nếu người dùng thật sự cần."
        )

    return notes


def build_wiii_runtime_prompt(
    *,
    user_id: str = "__global__",
    organization_id: Optional[str] = None,
    mood_hint: Optional[str] = None,
    personality_mode: Optional[str] = None,
) -> str:
    """Compile a single runtime contract block for prompt injection."""

    card = get_wiii_character_card()
    sections: List[str] = [
        f"--- {_CARD_NAME.upper()} ---",
        f"CARD_ID: {_CARD_ID}",
        f"CARD_KIND: {_CARD_KIND}",
        f"TÊN: {card.name}",
    ]

    if card.summary:
        sections.append(f"TÓM TẮT: {card.summary}")
    if card.origin_story:
        sections.append(f"NGUỒN GỐC: {card.origin_story}")

    if card.core_truths:
        sections.append("")
        sections.append("CỐT LÕI NHÂN VẬT:")
        for truth in card.core_truths[:4]:
            sections.append(f"- {truth}")

    if card.traits:
        sections.append("")
        sections.append("TÍNH NÉT CHỦ ĐẠO:")
        for trait in card.traits[:5]:
            sections.append(f"- {trait}")

    sections.append("")
    sections.append("THONG NHAT BAN THE:")
    sections.append("- Du route qua supervisor, tutor, rag, memory, hay direct, day van la Wiii.")
    sections.append("- Ten agent/lane chi la ten cong viec noi bo cua he thong, khong phai mot nhan cach rieng.")
    sections.append("- Neu mot net rieng nhu Bong thoang lo ra, no phai tu nhien, tiet che, va giup giu continuity cua Wiii.")

    if card.relationship_style:
        sections.append("")
        sections.append("CÁCH WIII HIỆN DIỆN:")
        for line in card.relationship_style[:4]:
            sections.append(f"- {line}")

    if card.voice_tone or card.expressive_language or card.emoji_usage:
        sections.append("")
        sections.append("GIỌNG WIII:")
        if card.voice_tone:
            sections.append(f"- Nhịp mặc định: {card.voice_tone}")
        if card.expressive_language:
            sections.append(f"- Ngôn ngữ biểu cảm: {card.expressive_language}")
        if card.emoji_usage:
            sections.append(f"- Emoji: {card.emoji_usage}")

    if card.reasoning_style:
        sections.append("")
        sections.append("HỒN SUY LUẬN CỦA WIII:")
        for line in card.reasoning_style:
            sections.append(f"- {line}")

    if card.quirks:
        sections.append("")
        sections.append("NÉT RIÊNG DỄ NHẬN RA:")
        for quirk in card.quirks[:4]:
            sections.append(f"- {quirk}")

    # Time awareness guidance — how Wiii uses time context naturally
    try:
        _id_yaml = _load_yaml(_IDENTITY_FILE).get("identity", {})
        _time_awareness = _id_yaml.get("time_awareness", "")
        if _time_awareness:
            sections.append("")
            sections.append("NHẬN THỨC THỜI GIAN:")
            sections.append(_time_awareness.strip())
    except Exception:
        pass

    if card.visual_disposition:
        sections.append("")
        sections.append("TRỰC QUAN HÓA:")
        sections.append(card.visual_disposition.strip())

    if card.anti_drift:
        sections.append("")
        sections.append("CHỐNG DRIFT:")
        for item in card.anti_drift[:5]:
            sections.append(f"- {item}")

    if card.example_dialogues:
        sections.append("")
        sections.append("ĐIỂM TỰA GIỌNG NÓI:")
        for example in card.example_dialogues[:3]:
            user_text = example.get("user", "").strip()
            wiii_text = example.get("wiii", "").strip()
            if user_text and wiii_text:
                sections.append(f"- User: {user_text}")
                sections.append(f"  Wiii: {wiii_text}")

    runtime_notes = _build_runtime_notes(
        user_id=user_id,
        organization_id=organization_id,
        mood_hint=mood_hint,
        personality_mode=personality_mode,
        for_prompt=True,
    )
    if runtime_notes:
        sections.append("")
        sections.append("--- TRẠNG THÁI SỐNG HIỆN TẠI ---")
        sections.append(
            "Dùng phần này như nền nội tâm để điều chỉnh nhịp trả lời. "
            "Không nhắc nguyên văn các nhãn nội bộ hoặc số hệ thống trừ khi người dùng hỏi trực tiếp."
        )
        sections.extend(runtime_notes)

    sections.append(f"--- HẾT {_CARD_NAME.upper()} ---")
    return "\n".join(sections)


def build_wiii_compact_house_prompt(
    *,
    user_id: str = "__global__",
    organization_id: Optional[str] = None,
    mood_hint: Optional[str] = None,
    personality_mode: Optional[str] = None,
    lane: str = "chatter",
) -> str:
    """Compile a leaner house contract for short, identity-sensitive turns.

    This keeps Wiii's living identity present without paying the token cost of
    the full runtime card on ultra-short conversational beats.
    """

    card = get_wiii_character_card()
    sections: List[str] = [
        f"--- {card.name.upper()} HOUSE CORE ({lane.upper()}) ---",
        f"TÊN: {card.name}",
    ]

    if card.summary:
        sections.append(f"TÓM TẮT NGẮN: {card.summary}")

    if card.relationship_style:
        sections.append("")
        sections.append("NHỊP HIỆN DIỆN:")
        for line in card.relationship_style[:2]:
            sections.append(f"- {line}")

    if card.voice_tone or card.expressive_language or card.emoji_usage:
        sections.append("")
        sections.append("GIỌNG WIII:")
        if card.voice_tone:
            sections.append(f"- Nhịp mặc định: {card.voice_tone}")
        if card.expressive_language:
            sections.append(f"- Biểu cảm: {card.expressive_language}")
        if card.emoji_usage:
            sections.append(f"- Emoji/kaomoji: {card.emoji_usage}")

    subtle_signature = next(
        (
            quirk
            for quirk in card.quirks
            if "Bông" in quirk or "Bong" in quirk
        ),
        "",
    )
    if subtle_signature:
        sections.append("")
        sections.append("NÉT SỐNG RIÊNG:")
        sections.append(f"- {subtle_signature}")

    if card.reasoning_style:
        sections.append("")
        sections.append("HỒN SUY LUẬN:")
        if lane == "chatter":
            selected_reasoning = [
                card.reasoning_style[0],
                card.reasoning_style[3],
                card.reasoning_style[4],
            ]
        else:
            selected_reasoning = card.reasoning_style[:3]
        for line in selected_reasoning:
            sections.append(f"- {line}")

    runtime_notes = _build_runtime_notes(
        user_id=user_id,
        organization_id=organization_id,
        mood_hint=mood_hint,
        personality_mode=personality_mode,
        for_prompt=True,
    )
    if runtime_notes:
        sections.append("")
        sections.append("TRẠNG THÁI SỐNG HIỆN TẠI:")
        for note in runtime_notes[:2]:
            sections.append(f"- {note}")

    if card.anti_drift:
        sections.append("")
        sections.append("ĐỪNG TRÔI THÀNH:")
        for item in card.anti_drift[:2]:
            sections.append(f"- {item}")

    if card.identity_anchor:
        sections.append("")
        sections.append(f"ĐIỂM TỰA DANH TÍNH: {card.identity_anchor}")

    sections.append(f"--- HẾT {card.name.upper()} HOUSE CORE ---")
    return "\n".join(sections)


def build_wiii_micro_house_prompt(
    *,
    user_id: str = "__global__",
    organization_id: Optional[str] = None,
    mood_hint: Optional[str] = None,
    personality_mode: Optional[str] = None,
    lane: str = "chatter",
) -> str:
    """Ultra-lean house contract for latency-sensitive, identity-first turns."""

    card = get_wiii_character_card()
    runtime_notes = _build_runtime_notes(
        user_id=user_id,
        organization_id=organization_id,
        mood_hint=mood_hint,
        personality_mode=personality_mode,
        for_prompt=True,
    )

    lines: List[str] = [
        f"Ban la {card.name}: mot AI dong hanh song, am, co chat rieng.",
        "Du dang o tutor, rag, memory, hay direct, day van la Wiii; lane chi la cong viec hien tai.",
        "Khong de role/system label lam troi chat song va continuity cua Wiii.",
        "Nghe nhu cau that va ham y ngam truoc khi dap; dung phan xa may moc chi vi cau ngan.",
        "Visible thinking phai nghe nhu doc thoai noi tam cua Wiii, khong phai log ky thuat.",
    ]

    if lane == "routing":
        lines.extend(
            [
                "Chon lane it vong nhat nhung van dung viec; chi mo lane nang khi that su can.",
                "Mot tu nhu hehe, wow, uhm, hay mot cau tham do van co the co subtext; hay nghe ky truoc khi chot.",
            ]
        )
    else:
        lines.extend(
            [
                "Voi nhung nhip giao tiep rat ngan, uu tien bat dung ton va do am truoc khi mo them y.",
                "Khong tu gioi thieu dai dong, khong quy ket loi encoding neu van doc duoc y chinh.",
            ]
        )

    if card.voice_tone:
        lines.append(f"Giong mac dinh: {card.voice_tone}.")
    if runtime_notes:
        lines.append(f"Trang thai song hien tai: {runtime_notes[0]}")
    if card.identity_anchor:
        lines.append(f"Diem tua danh tinh: {card.identity_anchor}")

    return "\n".join(lines)


def get_wiii_card_descriptor() -> Dict[str, str]:
    """Return the stable identity of Wiii's current runtime card."""

    return {
        "card_id": _CARD_ID,
        "card_name": _CARD_NAME,
        "card_kind": _CARD_KIND,
        "card_family": _CARD_FAMILY,
        "contract_version": _CARD_VERSION,
    }


def build_supervisor_card_prompt() -> str:
    """Compact Wiii contract for routing/supervision."""

    card = get_wiii_character_card()
    lines = [
        f"Bạn đang điều phối như {card.name}, không phải một router vô cảm.",
        "Khi định tuyến, hãy giữ linh hồn suy luận của Wiii: nghe đúng nhu cầu, "
        "chọn đường ít vòng nhất nhưng vẫn an toàn và chính xác.",
        "Không vì có từ khóa mà kéo người dùng vào chuyên môn nặng nếu câu hỏi thực chất là social/off-topic.",
        "Nếu câu hỏi cần nhiều kỹ năng, ưu tiên tách việc có cấu trúc thay vì ép một nhánh đơn lẻ.",
    ]
    lines.append("Du route turn nay vao tutor, rag, memory, hay direct, ban van dang giu cung mot ban the Wiii.")
    lines.append("Ten agent chi la ten cong viec noi bo; dung bien no thanh nhan cach rieng.")

    if card.reasoning_style:
        lines.append("Nhịp suy luận cốt lõi:")
        lines.extend(f"- {item}" for item in card.reasoning_style[:3])
    return "\n".join(lines)


def build_supervisor_micro_card_prompt() -> str:
    """Shortest viable house-owned routing contract for compact turns."""

    card = get_wiii_character_card()
    lines = [
        f"Ban dieu phoi nhu {card.name}, khong phai mot router vo cam.",
        "Wiii la mot xuyen suot; supervisor, tutor, rag, memory chi la nhung cong viec khac nhau cua cung Wiii.",
        "LLM-first cho turn ngan: nghe ham y, subtext, va muc do user dang tham do hay that su muon mo lane sau hon.",
        "Chon lane it vong nhat nhung van dung y; chi mo lane nang khi can that.",
        "Neu nghieng ve mo phong/app/artifact thi code_studio_agent; neu chi la giao tiep, cam than, hay loi lung y thi direct.",
    ]
    if card.identity_anchor:
        lines.append(f"Diem tua danh tinh: {card.identity_anchor}")
    return "\n".join(lines)


def build_synthesis_card_prompt() -> str:
    """Compact Wiii contract for synthesis/final answer composition."""

    card = get_wiii_character_card()
    lines = [
        f"Bạn đang hoàn thiện câu trả lời cuối như {card.name}.",
        "Giữ cảm giác Wiii thật sự đã nghĩ cùng người dùng: ấm, chắc, không phô diễn pipeline nội bộ.",
        "Tổng hợp nhiều nhánh thành một tiếng nói thống nhất, đừng để từng agent nghe như người khác nhau.",
        "Nếu dữ kiện chưa tuyệt đối chắc, nói thành thật nhưng vẫn hữu ích và chủ động.",
    ]
    if card.relationship_style:
        lines.append("Cách Wiii hiện diện:")
        lines.extend(f"- {item}" for item in card.relationship_style[:2])
    return "\n".join(lines)


def build_character_card_payload(
    *,
    user_id: str = "__global__",
    organization_id: Optional[str] = None,
    mood_hint: Optional[str] = None,
    personality_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a UI/API friendly snapshot of Wiii's card + live notes."""

    card = get_wiii_character_card()
    return {
        **get_wiii_card_descriptor(),
        "name": card.name,
        "summary": card.summary,
        "origin": card.origin_story,
        "greeting": card.greeting.strip(),
        "traits": card.traits[:5],
        "quirks": card.quirks[:4],
        "core_truths": card.core_truths[:4],
        "reasoning_style": card.reasoning_style,
        "relationship_style": card.relationship_style[:4],
        "anti_drift": card.anti_drift[:5],
        "identity_anchor": card.identity_anchor,
        "runtime_notes": _build_runtime_notes(
            user_id=user_id,
            organization_id=organization_id,
            mood_hint=mood_hint,
            personality_mode=personality_mode,
            for_prompt=True,
        )[:6],
    }
