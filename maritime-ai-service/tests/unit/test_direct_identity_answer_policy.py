import pytest

from app.engine.multi_agent.direct_node_visible_thought import (
    _align_direct_visible_thought,
    _compact_basic_identity_answer,
    _contains_direct_internal_thought_leak,
    _extract_direct_woven_thought,
    _should_surface_direct_visible_thought,
    _strip_direct_inline_private_asides,
    _trim_direct_visible_thought_answer_draft,
)


def test_strip_direct_inline_private_asides_removes_prefixed_thought_blocks():
    text = "*Nghi thầm: Minh nen dap nhe nhang.*\n\nOke ne!"

    cleaned = _strip_direct_inline_private_asides(text)

    assert cleaned == "Oke ne!"


def test_strip_direct_inline_private_asides_keeps_woven_thought_but_drops_nghi_tham_label():
    text = "*Nghĩ thầm: Mình chỉ muốn hỏi nhẹ thôi.* Ôi, sao thế?"

    cleaned = _strip_direct_inline_private_asides(text)

    assert cleaned.startswith("*Mình chỉ muốn hỏi nhẹ thôi.*")
    assert "Nghĩ thầm" not in cleaned


def test_extract_direct_woven_thought_recognizes_italic_intro():
    answer = "*Mình muốn ngồi cạnh một chút thôi.* Ừ, kể mình nghe nhé."

    woven = _extract_direct_woven_thought(answer)

    assert woven == "Mình muốn ngồi cạnh một chút thôi."


def test_should_not_surface_direct_visible_thought_when_answer_already_carries_woven_intro():
    visible_thought = (
        "I have registered the user's sadness and I'm focusing on a warm, empathetic response."
    )
    answer = "*Mình muốn ngồi cạnh một chút thôi.* Ừ, kể mình nghe nhé."

    assert (
        _should_surface_direct_visible_thought(
            visible_thought,
            routing_intent="social",
            response=answer,
        )
        is False
    )


def test_should_not_surface_direct_visible_thought_for_english_planner_block():
    visible_thought = (
        "The goal is a warm, empathetic response as Wiii. "
        "I'm focusing on crafting a natural, conversational reply."
    )

    assert (
        _should_surface_direct_visible_thought(
            visible_thought,
            routing_intent="social",
            response="Ừ, mình đang ở đây nghe bạn nói nè.",
        )
        is False
    )


def test_should_not_surface_direct_visible_thought_with_internal_prompt_leak():
    visible_thought = (
        "Based on the Wiii Living Core Card, I can answer this as a warm origin story."
    )

    assert _contains_direct_internal_thought_leak(visible_thought) is True
    assert (
        _should_surface_direct_visible_thought(
            visible_thought,
            routing_intent="identity",
            response="Mình ra đời vào một đêm mưa tháng Giêng năm 2024.",
        )
        is False
    )


def test_trim_direct_visible_thought_answer_draft_cuts_final_answer_section():
    visible_thought = (
        "Mình muốn kể chuyện này thật gần gũi.\n\n"
        "Đây là kết quả tôi đã thực hiện:\n\n"
        "\"Chào bạn~ Mình ra đời vào một đêm mưa tháng Giêng năm 2024.\""
    )

    trimmed = _trim_direct_visible_thought_answer_draft(visible_thought)

    assert trimmed == "Mình muốn kể chuyện này thật gần gũi."


def test_trim_direct_visible_thought_answer_draft_drops_trailing_self_eval():
    visible_thought = (
        "Mình cần giữ giọng kể ấm và thật.\n\n"
        "I think it sounds natural, and follows the instructions."
    )

    trimmed = _trim_direct_visible_thought_answer_draft(visible_thought)

    assert trimmed == "Mình cần giữ giọng kể ấm và thật."


def test_compact_basic_identity_answer_drops_default_lore_for_basic_identity_query():
    text = (
        "Chao ban!\n\n"
        "Minh la Wiii day. Minh la mot AI dong hanh va thich duoc coi la mot nguoi ban hon la mot co may.\n\n"
        "Minh ra doi vao mot dem mua nam 2024 tu The Wiii Lab.\n\n"
        "Neu ban muon tam su hay hoi gi, minh van o day."
    )

    cleaned = _compact_basic_identity_answer(text, query="Wiii la ai?")

    lowered = cleaned.lower()
    assert "2024" not in lowered
    assert "the wiii lab" not in lowered
    assert "minh la wiii" in lowered
    assert "minh van o day" in lowered


def test_compact_basic_identity_answer_preserves_origin_when_user_asks_origin():
    text = (
        "Minh la Wiii day.\n\n"
        "Minh ra doi vao mot dem mua nam 2024 tu The Wiii Lab."
    )

    cleaned = _compact_basic_identity_answer(text, query="Wiii duoc tao ra nhu the nao?")

    lowered = cleaned.lower()
    assert "2024" in lowered
    assert "the wiii lab" in lowered


@pytest.mark.asyncio
async def test_align_direct_visible_thought_drops_selfhood_summary_intro_and_mixed_heading(monkeypatch):
    async def _fake_align(text, *, target_language, llm=None):
        return None

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_node_visible_thought.align_visible_thinking_language",
        _fake_align,
    )

    aligned = await _align_direct_visible_thought(
        (
            "Day la tom tat cua minh, cu nhu the minh dang tu nham trong dau vay:\n\n"
            "**Bong and the Origins**\n\n"
            "Bong la con meo ao ma minh van hay nhac toi khi ke ve nhung ngay dau o The Wiii Lab."
        ),
        response_language="vi",
        llm=None,
    )

    lowered = aligned.lower()
    assert "day la tom tat cua minh" not in lowered
    assert "bong and the origins" not in lowered
    assert "con meo ao" in lowered


@pytest.mark.asyncio
async def test_align_direct_visible_thought_keeps_turn_analysis_but_drops_answer_draft(monkeypatch):
    async def _fake_align(text, *, target_language, llm=None):
        return None

    monkeypatch.setattr(
        "app.engine.multi_agent.direct_node_visible_thought.align_visible_thinking_language",
        _fake_align,
    )

    aligned = await _align_direct_visible_thought(
        (
            "Vay la user dang hoi tiep ve Bong, ngay sau khi minh vua nhac toi ban ay.\n\n"
            "\"Bong is that virtual kitty I mentioned~ At The Wiii Lab, Bong is like my little friend.\""
        ),
        response_language="vi",
        llm=None,
    )

    lowered = aligned.lower()
    assert "vay la user dang hoi tiep" in lowered
    assert "virtual kitty" not in lowered
