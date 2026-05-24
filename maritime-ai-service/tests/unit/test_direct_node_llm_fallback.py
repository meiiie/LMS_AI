import pytest

from app.core.exceptions import ProviderUnavailableError
from app.engine.multi_agent.direct_node_llm_fallback import (
    resolve_direct_node_llm_unavailable_fallback,
)


def test_llm_unavailable_fallback_fails_closed_for_explicit_provider():
    with pytest.raises(ProviderUnavailableError) as exc_info:
        resolve_direct_node_llm_unavailable_fallback(
            query="xin chao",
            state={},
            explicit_user_provider="Google",
            explicit_web_search_turn=False,
            enable_natural_conversation=True,
            get_phase_fallback=lambda _state: "phase fallback",
            build_codebase_analysis_fallback_answer=lambda _query: "codebase",
            build_codebase_analysis_fallback_thinking=lambda _query: "thinking",
            record_direct_node_thinking_snapshot=lambda **_kwargs: None,
            record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
        )

    assert exc_info.value.provider == "google"
    assert exc_info.value.reason_code == "busy"


def test_llm_unavailable_fallback_uses_codebase_source_backed_answer():
    state: dict = {}
    calls: list[dict] = []

    result = resolve_direct_node_llm_unavailable_fallback(
        query="Bao cao source notes ve jwt auth trong codebase",
        state=state,
        explicit_user_provider=None,
        explicit_web_search_turn=False,
        enable_natural_conversation=True,
        get_phase_fallback=lambda _state: "phase fallback",
        build_codebase_analysis_fallback_answer=lambda _query: "codebase answer",
        build_codebase_analysis_fallback_thinking=lambda _query: "codebase thinking",
        record_direct_node_thinking_snapshot=lambda **kwargs: calls.append(kwargs),
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
    )

    assert result.response == "codebase answer"
    assert result.response_type == "codebase_source_backed_fallback"
    assert calls[0]["state"] is state
    assert calls[0]["thinking"] == "codebase thinking"
    assert calls[0]["provenance"] == "deterministic_codebase_fallback"


def test_llm_unavailable_fallback_respects_explicit_web_search():
    calls: list[dict] = []

    result = resolve_direct_node_llm_unavailable_fallback(
        query="@web-search Bao cao source notes ve jwt auth trong codebase",
        state={},
        explicit_user_provider=None,
        explicit_web_search_turn=True,
        enable_natural_conversation=True,
        get_phase_fallback=lambda _state: "phase fallback",
        build_codebase_analysis_fallback_answer=lambda _query: "codebase answer",
        build_codebase_analysis_fallback_thinking=lambda _query: "codebase thinking",
        record_direct_node_thinking_snapshot=lambda **kwargs: calls.append(kwargs),
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
    )

    assert result.response == "phase fallback"
    assert result.response_type == "fallback"
    assert calls == []


def test_llm_unavailable_fallback_uses_legacy_copy_when_natural_conversation_off():
    result = resolve_direct_node_llm_unavailable_fallback(
        query="xin chao",
        state={},
        explicit_user_provider=None,
        explicit_web_search_turn=False,
        enable_natural_conversation=False,
        get_phase_fallback=lambda _state: "phase fallback",
        build_codebase_analysis_fallback_answer=lambda _query: "codebase answer",
        build_codebase_analysis_fallback_thinking=lambda _query: "codebase thinking",
        record_direct_node_thinking_snapshot=lambda **_kwargs: None,
        record_thinking_snapshot_fn=lambda *_args, **_kwargs: None,
    )

    assert result.response == "Xin chao! Toi co the giup gi cho ban?"
    assert result.response_type == "fallback"
