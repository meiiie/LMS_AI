from __future__ import annotations

import logging
from typing import Any

from app.engine.multi_agent.direct_node_response_cleanup import (
    apply_source_backed_empty_response_fallback,
    clean_direct_node_llm_response,
    strip_live_lookup_inferred_personal_context,
)


def test_clean_direct_node_llm_response_replaces_generic_codebase_answer() -> None:
    snapshots: list[dict[str, Any]] = []

    result = clean_direct_node_llm_response(
        query="kiem tra codebase",
        state={"session_id": "s1"},
        response="<tool_call>{}</tool_call>generic fallback",
        thinking_content="old thinking",
        tools_used=[],
        tool_call_events=[],
        is_identity_turn=False,
        is_codebase_analysis_turn=True,
        explicit_web_search_turn=False,
        sanitize_structured_visual_answer_text=lambda text, **_kwargs: text,
        sanitize_wiii_house_text=lambda text, **_kwargs: text,
        strip_direct_inline_private_asides=lambda text: text,
        strip_dsml_residue=lambda text: text.replace("<tool_call>{}</tool_call>", ""),
        compact_basic_identity_answer=lambda text, **_kwargs: text,
        looks_generic_direct_fallback_response=lambda text: "generic fallback" in text,
        build_codebase_analysis_fallback_answer=lambda _query: "codebase answer",
        build_codebase_analysis_fallback_thinking=lambda _query: "codebase thinking",
        record_direct_node_thinking_snapshot=lambda **kwargs: snapshots.append(kwargs),
        record_thinking_snapshot_fn=lambda **_kwargs: None,
    )

    assert result.response == "codebase answer"
    assert result.thinking_content == "codebase thinking"
    assert snapshots[0]["provenance"] == "deterministic_codebase_fallback"
    assert snapshots[0]["thinking"] == "codebase thinking"


def test_clean_direct_node_llm_response_compacts_identity_after_sanitize() -> None:
    result = clean_direct_node_llm_response(
        query="ban la ai",
        state={},
        response="  Wiii raw  ",
        thinking_content="",
        tools_used=[],
        tool_call_events=[],
        is_identity_turn=True,
        is_codebase_analysis_turn=False,
        explicit_web_search_turn=False,
        sanitize_structured_visual_answer_text=lambda text, **_kwargs: text.strip(),
        sanitize_wiii_house_text=lambda text, **_kwargs: text.replace("raw", "clean"),
        strip_direct_inline_private_asides=lambda text: text,
        strip_dsml_residue=lambda text: text,
        compact_basic_identity_answer=lambda text, **_kwargs: f"identity::{text}",
        looks_generic_direct_fallback_response=lambda _text: False,
        build_codebase_analysis_fallback_answer=lambda _query: "",
        build_codebase_analysis_fallback_thinking=lambda _query: "",
        record_direct_node_thinking_snapshot=lambda **_kwargs: None,
        record_thinking_snapshot_fn=lambda **_kwargs: None,
    )

    assert result.response == "identity::Wiii clean"


def test_strip_live_lookup_inferred_personal_context_removes_memory_bleed() -> None:
    events = [{"type": "result", "name": "tool_web_search"}]

    cleaned = strip_live_lookup_inferred_personal_context(
        (
            "Hai Phong hom nay nang nong 37C. "
            "Minh biet cau dang buon, nen dung ra ngoai lau nha. "
            "Co gi can minh goi y cach chong nong khong?"
        ),
        query="thoi tiet Hai Phong hom nay",
        tool_call_events=events,
    )

    assert "37C" in cleaned
    assert "dang buon" not in cleaned
    assert "goi y" not in cleaned


def test_strip_live_lookup_inferred_personal_context_removes_story_bleed_and_replay() -> None:
    events = [{"type": "result", "name": "tool_web_search"}]

    cleaned = strip_live_lookup_inferred_personal_context(
        (
            "Minh vua tra ne: thoi tiet Hai Phong 29C.\n\n"
            "Minh vua tra ne: thoi tiet Hai Phong 29C. Do am 81%, co kha nang mua. "
            "Cau nho mang ao mua neu ra ngoai. "
            "Bong ao cua minh cung dang cuon tron trong chan ne."
        ),
        query="thoi tiet Hai Phong hom nay",
        tool_call_events=events,
    )

    assert cleaned.count("Minh vua tra ne") == 1
    assert "Do am 81%" in cleaned
    assert "mang ao mua" in cleaned
    assert "Bong" not in cleaned
    assert "cuon tron" not in cleaned


def test_strip_live_lookup_inferred_personal_context_removes_bong_bedtime_aside() -> None:
    events = [{"type": "result", "name": "tool_web_search"}]

    cleaned = strip_live_lookup_inferred_personal_context(
        (
            "Minh vua tra xong thoi tiet Hai Phong: nhiet do cao nhat 37C, "
            "do am 84%, co mua dong rai rac. "
            "Neu di ra ngoai, nho mang ao mua va tranh cay cao khi co sam set. "
            "Dung thuc khuya qua, minh ke chuyen meo Bong bi uot vi quen mang o."
        ),
        query="thoi tiet Hai Phong hom nay",
        tool_call_events=events,
    )

    assert "37C" in cleaned
    assert "mang ao mua" in cleaned
    assert "Bong" not in cleaned
    assert "thuc khuya" not in cleaned
    assert "ke chuyen" not in cleaned


def test_strip_live_lookup_inferred_personal_context_removes_unsolicited_creation_followup() -> None:
    events = [{"type": "result", "name": "tool_web_search"}]

    cleaned = strip_live_lookup_inferred_personal_context(
        (
            "Hai Phong luc 22h nhiet do 30C, nhieu may, do am 85%. "
            "Ngay mai co mua rao va dong, nen mang o neu ra ngoai. "
            "Minh co the tao bieu do de nhin luon."
        ),
        query="thoi tiet Hai Phong hom nay",
        tool_call_events=events,
    )

    assert "30C" in cleaned
    assert "mang o" in cleaned
    assert "tao bieu do" not in cleaned


def test_strip_live_lookup_inferred_personal_context_removes_study_late_inference() -> None:
    events = [{"type": "result", "name": "tool_web_search"}]

    cleaned = strip_live_lookup_inferred_personal_context(
        (
            "Hai Phong hien 29C, nhieu may, do am 82%, kha nang mua 75%. "
            "Du bao den 23h van am u va am uot. "
            "Cau dang hoc khuya ma troi nhu the nay thi de buon ngu va met lam."
        ),
        query="thoi tiet Hai Phong hom nay",
        tool_call_events=events,
    )

    assert "29C" in cleaned
    assert "am uot" in cleaned
    assert "hoc khuya" not in cleaned
    assert "buon ngu" not in cleaned


def test_strip_live_lookup_inferred_personal_context_removes_whereabouts_followup() -> None:
    events = [{"type": "result", "name": "tool_web_search"}]

    cleaned = strip_live_lookup_inferred_personal_context(
        (
            "Hai Phong luc 22h la 29C, troi quang, do am 80%. "
            "Tu 23h co mua rao nhe keo dai den sang mai. "
            "Cau dang o nha hay di dau khuya vay? "
            "Neu ra ngoai, nho mang ao mua nho nha. Dung de uot, minh lo lam. "
            "Con neu dang hoc bai thi nghi som mot chut."
        ),
        query="thoi tiet Hai Phong hom nay",
        tool_call_events=events,
    )

    assert "29C" in cleaned
    assert "mua rao" in cleaned
    assert "dang o nha" not in cleaned
    assert "di dau" not in cleaned
    assert "minh lo" not in cleaned
    assert "hoc bai" not in cleaned


def test_strip_live_lookup_inferred_personal_context_keeps_requested_context() -> None:
    events = [{"type": "result", "name": "tool_web_search"}]
    response = "Minh biet cau dang buon, nen minh se noi ngan: troi nong 37C."

    assert (
        strip_live_lookup_inferred_personal_context(
            response,
            query="minh dang buon, thoi tiet Hai Phong hom nay the nao",
            tool_call_events=events,
        )
        == response
    )


def test_apply_source_backed_empty_response_fallback_uses_tool_events() -> None:
    counters: list[dict[str, Any]] = []
    events = [
        {"type": "result", "name": "tool_web_search", "content": "source"},
        {"type": "result", "name": "tool_knowledge_search", "content": "source"},
    ]

    result = apply_source_backed_empty_response_fallback(
        query="gia dau hom nay",
        response="",
        tools_used=[],
        tool_call_events=events,
        looks_like_search_placeholder_answer=lambda _text: False,
        build_search_template_fallback=lambda **_kwargs: "source-backed answer",
        inc_counter=lambda name, **kwargs: counters.append({"name": name, **kwargs}),
        logger_obj=logging.getLogger(__name__),
    )

    assert result.engaged is True
    assert result.response == "source-backed answer"
    assert result.tools_used == [
        {"name": "tool_knowledge_search"},
        {"name": "tool_web_search"},
    ]
    assert counters == [
        {
            "name": "wiii.direct.template_fallback.engaged",
            "labels": {"trigger": "empty_body"},
        }
    ]


def test_apply_source_backed_empty_response_fallback_skips_normal_answer() -> None:
    result = apply_source_backed_empty_response_fallback(
        query="hello",
        response="normal answer",
        tools_used=[{"name": "tool_web_search"}],
        tool_call_events=[{"type": "result", "name": "tool_web_search"}],
        looks_like_search_placeholder_answer=lambda _text: False,
        build_search_template_fallback=lambda **_kwargs: "should not run",
        inc_counter=lambda *_args, **_kwargs: None,
        logger_obj=logging.getLogger(__name__),
    )

    assert result.engaged is False
    assert result.response == "normal answer"
    assert result.tools_used == [{"name": "tool_web_search"}]
