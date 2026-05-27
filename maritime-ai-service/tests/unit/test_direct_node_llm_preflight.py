from __future__ import annotations

from typing import Any

from app.engine.multi_agent.direct_node_llm_preflight import (
    DirectNodeLlmSelection,
    apply_direct_node_natural_conversation_penalties,
    maybe_build_uploaded_visual_guard,
    prepare_direct_node_llm_preflight,
    select_direct_node_llm,
)


class _Llm:
    def __init__(
        self,
        *,
        provider: str = "qwen",
        model: str = "qwen3-next",
        native: bool = False,
    ) -> None:
        self._wiii_provider_name = provider
        self._wiii_model_name = model
        if native:
            self._wiii_native_route = True
        self.bind_kwargs: dict[str, Any] | None = None

    def bind(self, **kwargs: Any) -> "_Llm":
        self.bind_kwargs = kwargs
        return _Llm(provider=self._wiii_provider_name, model=self._wiii_model_name)


def test_select_direct_node_llm_uses_supported_native_route() -> None:
    native_llm = _Llm(provider="qwen", native=True)
    standard_llm = _Llm(provider="fallback")
    calls: list[str] = []

    result = select_direct_node_llm(
        is_identity_turn=False,
        ctx={},
        is_short_house_chatter=False,
        is_emotional_support_turn=False,
        use_house_voice_direct=False,
        is_codebase_source_turn=False,
        response_present=False,
        thinking_effort="medium",
        direct_provider_override="qwen",
        requested_model="qwen3-next",
        get_native_llm=lambda *_args, **_kwargs: calls.append("native") or native_llm,
        get_llm=lambda *_args, **_kwargs: calls.append("standard") or standard_llm,
        supports_native_answer_streaming=lambda provider: provider == "qwen",
    )

    assert result.direct_node_id == "direct"
    assert result.native_direct_possible is True
    assert result.llm is native_llm
    assert calls == ["native"]


def test_select_direct_node_llm_falls_back_when_native_provider_unsupported() -> None:
    native_llm = _Llm(provider="legacy-provider", native=True)
    standard_llm = _Llm(provider="qwen")
    calls: list[str] = []

    result = select_direct_node_llm(
        is_identity_turn=False,
        ctx={},
        is_short_house_chatter=False,
        is_emotional_support_turn=False,
        use_house_voice_direct=False,
        is_codebase_source_turn=False,
        response_present=False,
        thinking_effort=None,
        direct_provider_override=None,
        requested_model=None,
        get_native_llm=lambda *_args, **_kwargs: calls.append("native") or native_llm,
        get_llm=lambda *_args, **_kwargs: calls.append("standard") or standard_llm,
        supports_native_answer_streaming=lambda _provider: False,
    )

    assert result.llm is standard_llm
    assert calls == ["native", "standard"]


def test_select_direct_node_llm_uses_chatter_node_for_short_house_chatter() -> None:
    standard_llm = _Llm(provider="qwen")
    calls: list[tuple[str, str]] = []

    result = select_direct_node_llm(
        is_identity_turn=False,
        ctx={},
        is_short_house_chatter=True,
        is_emotional_support_turn=False,
        use_house_voice_direct=True,
        is_codebase_source_turn=False,
        response_present=False,
        thinking_effort="low",
        direct_provider_override="nvidia",
        requested_model=None,
        get_native_llm=lambda *args, **_kwargs: calls.append(("native", args[0])),
        get_llm=lambda *args, **_kwargs: calls.append(("standard", args[0])) or standard_llm,
        supports_native_answer_streaming=lambda _provider: True,
    )

    assert result.direct_node_id == "direct_chatter"
    assert result.native_direct_possible is False
    assert result.llm is standard_llm
    assert calls == [("standard", "direct_chatter")]


def test_maybe_build_uploaded_visual_guard_clears_images_for_text_only_provider() -> None:
    ctx = {"images": [{"url": "frame.png"}]}

    result = maybe_build_uploaded_visual_guard(
        llm=_Llm(provider="text-only", model="text-model"),
        query="anh trong video noi gi",
        state={"model": "state-model"},
        ctx_for_preflight=ctx,
        has_uploaded_document_context=True,
        direct_provider_override=None,
        preferred_provider="qwen",
        looks_uploaded_file_visual_inspection_query=lambda _query: True,
        provider_likely_supports_image_blocks=lambda _provider, _model: False,
        build_uploaded_document_visual_guard_answer=lambda _query, _ctx: "need vision",
    )

    assert result is not None
    assert result.response == "need vision"
    assert result.provider == "text-only"
    assert result.model == "text-model"
    assert ctx["images"] == []


def test_apply_natural_conversation_penalties_binds_non_native_llm() -> None:
    llm = _Llm(provider="qwen", model="qwen3-next")

    result = apply_direct_node_natural_conversation_penalties(
        llm,
        response_present=False,
        enable_natural_conversation=True,
        presence_penalty=0.2,
        frequency_penalty=0.1,
    )

    assert result is not llm
    assert llm.bind_kwargs == {"presence_penalty": 0.2, "frequency_penalty": 0.1}
    assert getattr(result, "_wiii_provider_name") == "qwen"
    assert getattr(result, "_wiii_model_name") == "qwen3-next"


def test_apply_natural_conversation_penalties_skips_native_llm() -> None:
    llm = _Llm(provider="qwen", native=True)

    result = apply_direct_node_natural_conversation_penalties(
        llm,
        response_present=False,
        enable_natural_conversation=True,
        presence_penalty=0.2,
        frequency_penalty=0.1,
    )

    assert result is llm
    assert llm.bind_kwargs is None


def test_prepare_direct_node_llm_preflight_applies_uploaded_visual_guard_before_penalties():
    llm = _Llm(provider="text-only", model="text-model")
    ctx_for_preflight = {"images": [{"url": "frame.png"}]}
    tracer_calls: list[dict[str, Any]] = []

    class _Tracer:
        def end_step(self, **kwargs: Any) -> None:
            tracer_calls.append(kwargs)

    penalty_calls: list[dict[str, Any]] = []

    def apply_penalties_fn(candidate_llm: Any, **kwargs: Any) -> Any:
        penalty_calls.append(kwargs)
        return candidate_llm

    result = prepare_direct_node_llm_preflight(
        query="anh trong video noi gi",
        state={"model": "state-model"},
        ctx={},
        ctx_for_preflight=ctx_for_preflight,
        has_uploaded_document_context=True,
        response="",
        is_identity_turn=False,
        is_short_house_chatter=False,
        is_emotional_support_turn=False,
        use_house_voice_direct=False,
        is_codebase_source_turn=False,
        thinking_effort="medium",
        direct_provider_override=None,
        preferred_provider="qwen",
        requested_model="qwen3-next",
        enable_natural_conversation=True,
        presence_penalty=0.2,
        frequency_penalty=0.1,
        get_native_llm=lambda *_args, **_kwargs: None,
        get_llm=lambda *_args, **_kwargs: llm,
        supports_native_answer_streaming=lambda _provider: False,
        looks_uploaded_file_visual_inspection_query=lambda _query: True,
        provider_likely_supports_image_blocks=lambda _provider, _model: False,
        build_uploaded_document_visual_guard_answer=lambda _query, _ctx: "need vision",
        tracer=_Tracer(),
        logger_obj=type("_Logger", (), {"info": lambda *_args, **_kwargs: None})(),
        apply_penalties_fn=apply_penalties_fn,
    )

    assert result.llm is llm
    assert result.response == "need vision"
    assert result.visual_guard is not None
    assert result.visual_guard.provider == "text-only"
    assert ctx_for_preflight["images"] == []
    assert penalty_calls == [
        {
            "response_present": True,
            "enable_natural_conversation": True,
            "presence_penalty": 0.2,
            "frequency_penalty": 0.1,
        }
    ]
    assert tracer_calls == [
        {
            "result": "Uploaded-file visual guard fallback (text-only provider)",
            "confidence": 0.7,
            "details": {
                "response_type": "uploaded_file_visual_guard_fallback",
                "provider": "text-only",
                "model": "text-model",
            },
        }
    ]


def test_prepare_direct_node_llm_preflight_allows_selection_injection():
    selected_llm = _Llm(provider="qwen")
    selection = DirectNodeLlmSelection(
        direct_node_id="direct",
        native_direct_possible=True,
        llm=selected_llm,
    )

    result = prepare_direct_node_llm_preflight(
        query="xin chao",
        state={},
        ctx={},
        ctx_for_preflight={},
        has_uploaded_document_context=False,
        response="",
        is_identity_turn=False,
        is_short_house_chatter=False,
        is_emotional_support_turn=False,
        use_house_voice_direct=False,
        is_codebase_source_turn=False,
        thinking_effort=None,
        direct_provider_override=None,
        preferred_provider=None,
        requested_model=None,
        enable_natural_conversation=False,
        presence_penalty=0.0,
        frequency_penalty=0.0,
        get_native_llm=lambda *_args, **_kwargs: None,
        get_llm=lambda *_args, **_kwargs: None,
        supports_native_answer_streaming=lambda _provider: False,
        looks_uploaded_file_visual_inspection_query=lambda _query: False,
        provider_likely_supports_image_blocks=lambda _provider, _model: True,
        build_uploaded_document_visual_guard_answer=lambda _query, _ctx: "",
        tracer=type("_Tracer", (), {"end_step": lambda *_args, **_kwargs: None})(),
        logger_obj=type("_Logger", (), {"info": lambda *_args, **_kwargs: None})(),
        select_llm_fn=lambda **_kwargs: selection,
    )

    assert result.selection is selection
    assert result.llm is selected_llm
    assert result.response == ""
    assert result.visual_guard is None
