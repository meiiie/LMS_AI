from unittest.mock import MagicMock, patch

import pytest

from app.engine.multi_agent.direct_reasoning import (
    _build_direct_analytical_axes,
    _build_direct_evidence_plan,
    _infer_direct_thinking_mode,
    _infer_direct_topic_hint,
)
from app.engine.multi_agent.direct_response_runtime import (
    _derive_analytical_thinking_from_answer,
)


def test_direct_reasoning_infers_codebase_mode_for_schema_count_query():
    query = "Vi sao database co hon 60 bang ma class diagram chi hien 25 bang?"

    mode = _infer_direct_thinking_mode(query, {}, [])
    topic = _infer_direct_topic_hint(query, {}, [])
    axes = _build_direct_analytical_axes(query, {}, [])
    plan = _build_direct_evidence_plan(query, {}, [])

    assert mode == "analytical_codebase"
    assert topic == "schema/database trong codebase"
    assert any("junction" in axis for axis in axes)
    assert any("migration" in step for step in plan)


def test_direct_reasoning_infers_codebase_mode_for_jwt_auth_query():
    query = "Giai thich JWT xac thuc lien quan controller, service va filter nao"

    mode = _infer_direct_thinking_mode(query, {}, [])
    topic = _infer_direct_topic_hint(query, {}, [])
    axes = _build_direct_analytical_axes(query, {}, [])
    plan = _build_direct_evidence_plan(query, {}, [])

    assert mode == "analytical_codebase"
    assert topic == "JWT/auth trong codebase"
    assert any("JwtService" in axis for axis in axes)
    assert any("JwtAuthenticationFilter" in step for step in plan)


def test_direct_prompt_adds_source_backed_codebase_contract():
    from app.engine.multi_agent.direct_prompts import _build_direct_system_messages

    loader = MagicMock()
    loader.build_system_prompt.return_value = "BASE SYSTEM PROMPT"
    loader.get_thinking_instruction.return_value = ""
    loader.get_persona.return_value = {
        "agent": {
            "name": "Wiii",
            "goal": "Tra loi co chat",
            "backstory": "Vai tro: tro ly hoi thoai da linh vuc.",
        }
    }
    state = {
        "context": {"response_language": "vi"},
        "user_id": "user-1",
    }

    with patch("app.prompts.prompt_loader.get_prompt_loader", return_value=loader):
        messages = _build_direct_system_messages(
            state,
            "Vi sao database co hon 60 bang ma class diagram chi hien 25 bang? Giai thich JWT xac thuc.",
            "Maritime",
            tools_context_override="",
        )

    system_prompt = messages[0]["content"].lower()
    assert "analytical_codebase" not in system_prompt
    assert "source-backed" in system_prompt
    assert "ledger kiem chung" in system_prompt
    assert "mode nay override default no-heading" in system_prompt
    assert "login -> tao access/refresh token" in system_prompt
    assert "junction table" in system_prompt


def test_codebase_fallback_thinking_is_public_evidence_ledger_not_answer_copy():
    answer = (
        "Class diagram khong phai database diagram. No chi chon entity nghiep vu chinh, "
        "con cac bang junction va infrastructure chi phuc vu quan he hoac van hanh. "
        "JWT xac thuc thi di qua controller, token service va filter moi request."
    )

    thinking = _derive_analytical_thinking_from_answer(
        query="Vi sao class diagram chi hien 25 bang va JWT xac thuc lien quan file nao?",
        answer=answer,
        tools_used_names=set(),
    )

    assert "source-backed" in thinking
    assert "junction table" in thinking
    assert "JWT/auth" in thinking
    assert thinking != answer


def test_image_input_thinking_is_evidence_led_for_ocr_and_color_questions():
    from app.engine.multi_agent.direct_node_operational_fast_paths import (
        _build_image_input_thinking,
    )

    thinking = _build_image_input_thinking("Doc chu va mau nen trong anh nay")

    assert "vision co bang chung" in thinking
    assert "doc chu/marker" in thinking
    assert "doi chieu mau nen" in thinking
    assert "khong keo sang RAG" in thinking


def test_codebase_fallback_answer_replaces_generic_phase_greeting():
    from app.engine.multi_agent.direct_node_operational_fast_paths import (
        _build_codebase_analysis_fallback_answer,
        _build_codebase_analysis_fallback_thinking,
        _looks_generic_direct_fallback_response,
    )

    query = (
        "Vi sao database co hon 60 bang ma class diagram chi hien 25 entity? "
        "Noi them co che JWT xac thuc."
    )

    assert _looks_generic_direct_fallback_response("Minh la Wiii! Ban muon tim hieu gi hom nay?")
    answer = _build_codebase_analysis_fallback_answer(query)
    thinking = _build_codebase_analysis_fallback_thinking(query)

    assert "class diagram" in answer
    assert "junction table" in answer
    assert "JwtService" in answer
    assert "JwtAuthenticationFilter" in answer
    assert "stateless" in answer
    assert "ledger kiểm chứng" in thinking


def test_codebase_source_notes_use_deterministic_fast_answer():
    from app.engine.multi_agent.direct_node_operational_fast_paths import (
        _build_codebase_analysis_fallback_answer,
        _should_use_codebase_source_note_fast_answer,
    )

    query = (
        "Context: report rehearsal. Source notes: course_publications, "
        "video_assets, JwtService.java, JwtAuthenticationFilter.java. "
        "Vi sao database co hon 60 bang nhung class diagram chi hien 25 entity? "
        "Giai thich JWT stateless."
    )

    assert _should_use_codebase_source_note_fast_answer(query) is True
    answer = _build_codebase_analysis_fallback_answer(query)
    folded = answer.lower()
    assert "course_publications" in answer
    assert "snapshot" in folded
    assert "join giữa" not in folded


@pytest.mark.asyncio
async def test_guardian_fast_passes_codebase_analysis_without_llm():
    from app.engine.multi_agent.guardian_runtime import guardian_node_impl

    def fail_guardian():
        raise AssertionError("guardian LLM should not be called")

    state = {
        "query": "Vi sao database co hon 60 bang nhung class diagram chi hien 25 entity? Giai thich JWT.",
        "context": {},
    }

    result = await guardian_node_impl(state, get_guardian=fail_guardian)

    assert result["guardian_passed"] is True
    assert result["_guardian_fast_path"] == "codebase_source_backed_analysis"


@pytest.mark.asyncio
async def test_guardian_fast_passes_safe_image_inspection_without_llm():
    from app.engine.multi_agent.guardian_runtime import guardian_node_impl

    def fail_guardian():
        raise AssertionError("guardian LLM should not be called")

    state = {
        "query": "Hay doc marker va mau nen trong anh nay.",
        "context": {"images": [{"type": "base64", "data": "abc"}]},
    }

    result = await guardian_node_impl(state, get_guardian=fail_guardian)

    assert result["guardian_passed"] is True
    assert result["_guardian_fast_path"] == "safe_image_inspection"


def test_hunger_chatter_unicode_fast_path_matches_vietnamese() -> None:
    from app.engine.multi_agent.direct_intent import _normalize_for_intent
    from app.engine.multi_agent.direct_node_chatter_runtime import (
        _looks_hunger_chatter_turn,
    )

    query = "\u0111\u00f3i ph\u1ebft"

    assert _looks_hunger_chatter_turn(_normalize_for_intent(query))


def test_pointy_missing_inventory_fails_soft_without_llm() -> None:
    from app.engine.multi_agent.direct_node_operational_fast_paths import (
        _build_pointy_missing_inventory_answer,
        _pointy_requested_without_inventory,
    )

    state = {
        "force_skills": ["wiii-pointy"],
        "context": {"force_skills": ["wiii-pointy"]},
    }

    assert _pointy_requested_without_inventory(state)
    assert "host_context" in _build_pointy_missing_inventory_answer("show send button")
