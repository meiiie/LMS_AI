from __future__ import annotations

import logging
from typing import Any

from app.engine.multi_agent.direct_node_response_cleanup import (
    apply_source_backed_empty_response_fallback,
    clean_direct_node_llm_response,
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
