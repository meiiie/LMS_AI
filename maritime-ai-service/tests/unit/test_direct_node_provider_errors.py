import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.exceptions import ProviderUnavailableError
from app.engine.multi_agent.direct_intent import _normalize_for_intent
from app.engine.multi_agent.direct_node_runtime import direct_response_node_impl


class _DummyTracer:
    def start_step(self, *args, **kwargs):
        return None

    def end_step(self, *args, **kwargs):
        return None


def _base_direct_kwargs():
    return {
        "direct_response_step_name": "direct_response",
        "get_or_create_tracer": lambda *_args, **_kwargs: _DummyTracer(),
        "capture_public_thinking_event": lambda *_args, **_kwargs: None,
        "get_domain_greetings": lambda *_args, **_kwargs: {},
        "normalize_for_intent": _normalize_for_intent,
        "looks_identity_selfhood_turn": lambda *_args, **_kwargs: True,
        "needs_web_search": lambda *_args, **_kwargs: False,
        "needs_datetime": lambda *_args, **_kwargs: False,
        "resolve_visual_intent": lambda *_args, **_kwargs: SimpleNamespace(
            force_tool=False,
            visual_type=None,
            presentation_intent=None,
        ),
        "recommended_visual_thinking_effort": lambda *_args, **_kwargs: None,
        "get_active_code_studio_session": lambda *_args, **_kwargs: None,
        "merge_thinking_effort": lambda current, other: other or current,
        "get_effective_provider": lambda *_args, **_kwargs: "google",
        "get_explicit_user_provider": lambda *_args, **_kwargs: "google",
        "collect_direct_tools": lambda *_args, **_kwargs: ([], False),
        "direct_required_tool_names": lambda *_args, **_kwargs: [],
        "resolve_direct_answer_timeout_profile": lambda **_kwargs: None,
        "bind_direct_tools": lambda *_args, **_kwargs: (None, None, None),
        "build_direct_system_messages": lambda *_args, **_kwargs: [],
        "build_visual_tool_runtime_metadata": lambda *_args, **_kwargs: {},
        "execute_direct_tool_rounds": None,
        "extract_direct_response": lambda *_args, **_kwargs: ("", "", []),
        "sanitize_structured_visual_answer_text": lambda text, **_kwargs: text,
        "sanitize_wiii_house_text": lambda text, **_kwargs: text,
        "build_direct_reasoning_summary": lambda *_args, **_kwargs: "",
        "direct_tool_names": [],
        "should_surface_direct_thinking": lambda *_args, **_kwargs: False,
        "resolve_public_thinking_content": lambda *_args, **_kwargs: "",
        "get_phase_fallback": lambda *_args, **_kwargs: "fallback",
    }


def _base_state():
    return {
        "query": "Wiii duoc sinh ra the nao?",
        "context": {
            "response_language": "vi",
            "user_role": "student",
        },
        "domain_id": "maritime",
        "domain_config": {},
        "routing_metadata": {"intent": "selfhood"},
        "provider": "google",
    }


def _mark_lms_authoring_connected(state):
    context = state.setdefault("context", {})
    context["lms_connector_id"] = "maritime-lms"
    context["lms_external_id"] = "teacher-1"
    context["host_context"] = {
        "host_type": "lms",
        "connector_id": "maritime-lms",
        "host_user_id": "teacher-1",
    }
    host_capabilities = context.get("host_capabilities")
    if isinstance(host_capabilities, dict):
        host_capabilities["host_type"] = "lms"
        host_capabilities["connector_id"] = "maritime-lms"


@pytest.mark.asyncio
async def test_direct_response_node_uses_pointy_fast_path_without_llm():
    state = _base_state()
    state.update(
        {
            "query": "@wiii-pointy Chi vao nut Gui tin nhan giup minh.",
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "host_ui_navigation",
            },
            "_pointy_fast_path_action": {
                "action": "ui.highlight",
                "target": {"id": "chat-send-button", "label": "Gửi tin nhắn"},
                "params": {"selector": "chat-send-button", "source": "pointy_fast_path"},
            },
        }
    )

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("pointy fast path should not call an LLM"),
    ):
        result = await direct_response_node_impl(
            state,
            **_base_direct_kwargs(),
        )

    assert result["final_response"] == "Mình đã trỏ vào Gửi tin nhắn cho cậu thấy ngay."
    assert result["thinking_content"]


@pytest.mark.asyncio
async def test_direct_response_node_uses_pointy_fast_path_even_if_router_mislabels_turn():
    state = _base_state()
    state.update(
        {
            "query": "nut gui tin nhan o dau",
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "social",
            },
            "_pointy_fast_path_action": {
                "action": "ui.highlight",
                "target": {"id": "chat-send-button", "label": "Gui tin nhan"},
                "params": {"selector": "chat-send-button", "source": "pointy_fast_path"},
            },
        }
    )

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("pointy action already resolved; LLM must not contradict it"),
    ):
        result = await direct_response_node_impl(
            state,
            **_base_direct_kwargs(),
        )

    assert result["final_response"] == "Mình đã trỏ vào Gui tin nhan cho cậu thấy ngay."
    assert "đưa con trỏ" in result["thinking_content"]


@pytest.mark.asyncio
async def test_direct_response_node_runs_document_preview_tool_before_llm():
    state = _base_state()
    state.update(
        {
            "query": (
                "Dua tren tai lieu Word vua upload, tao preview_lesson_patch "
                "co source_references cho bai hoc hien tai."
            ),
            "routing_metadata": {
                "method": "deterministic_document_context_guard",
                "intent": "uploaded_file_context",
            },
            "context": {
                "response_language": "vi",
                "user_role": "teacher",
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "lesson.docx",
                            "markdown": "Marker WIII_DOC_GOAL_789\nNguon trang 4.",
                        }
                    ]
                },
                "host_capabilities": {
                    "tools": [
                        {"name": "authoring.preview_lesson_patch"},
                    ]
                },
            },
        }
    )
    _mark_lms_authoring_connected(state)

    captured: dict[str, object] = {}

    async def fake_execute_direct_tool_rounds(*args, **kwargs):
        captured["forced_tool_choice"] = kwargs.get("forced_tool_choice")
        captured["tools"] = args[3]
        return (
            SimpleNamespace(content="Preview sent to LMS."),
            [],
            [
                {
                    "type": "call",
                    "name": "host_action__authoring__preview_lesson_patch",
                },
                {
                    "type": "host_action",
                    "name": "host_action__authoring__preview_lesson_patch",
                },
            ],
        )

    kwargs = _base_direct_kwargs()
    kwargs.update(
        {
            "looks_identity_selfhood_turn": lambda *_args, **_kwargs: False,
            "get_effective_provider": lambda *_args, **_kwargs: None,
            "get_explicit_user_provider": lambda *_args, **_kwargs: None,
            "collect_direct_tools": lambda *_args, **_kwargs: (
                [SimpleNamespace(name="host_action__authoring__preview_lesson_patch")],
                True,
            ),
            "execute_direct_tool_rounds": fake_execute_direct_tool_rounds,
            "extract_direct_response": lambda *_args, **_kwargs: (
                "Mình đã gửi bản preview sang LMS.",
                "Tạo preview từ tài liệu upload trước khi gọi LLM.",
                [],
            ),
        }
    )

    with (
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            side_effect=AssertionError("preview host action should not need native LLM"),
        ),
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            side_effect=AssertionError("preview host action should not need planner LLM"),
        ),
    ):
        result = await direct_response_node_impl(state, **kwargs)

    assert result["final_response"] == "Mình đã gửi bản preview sang LMS."
    assert captured["forced_tool_choice"] == "host_action__authoring__preview_lesson_patch"
    assert result["tool_call_events"][0]["type"] == "call"


@pytest.mark.asyncio
async def test_direct_response_node_rebinds_document_preview_tool_when_collection_misses():
    state = _base_state()
    state.update(
        {
            "query": (
                "Dua tren tai lieu Word vua upload, tao preview_lesson_patch "
                "co source_references va approval_token cho bai hoc hien tai."
            ),
            "session_id": "session-doc-preview",
            "routing_metadata": {
                "method": "deterministic_document_context_guard",
                "intent": "uploaded_file_context",
            },
            "context": {
                "response_language": "vi",
                "user_role": "teacher",
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "lesson.docx",
                            "markdown": "Marker WIII_DOC_GOAL_456\nNguon trang 5.",
                        }
                    ]
                },
                "host_capabilities": {
                    "tools": [
                        {
                            "name": "authoring.preview_lesson_patch",
                            "description": "Preview lesson patch",
                            "roles": ["teacher"],
                            "permission": "manage:courses",
                            "mutates_state": False,
                            "requires_confirmation": False,
                        },
                    ]
                },
            },
        }
    )
    _mark_lms_authoring_connected(state)

    captured: dict[str, object] = {}

    async def fake_execute_direct_tool_rounds(*args, **kwargs):
        captured["forced_tool_choice"] = kwargs.get("forced_tool_choice")
        captured["tool_names"] = [
            getattr(tool, "name", getattr(tool, "__name__", ""))
            for tool in args[3]
        ]
        return (
            SimpleNamespace(content="Preview sent to LMS."),
            [],
            [
                {
                    "type": "call",
                    "name": "host_action__authoring__preview_lesson_patch",
                },
                {
                    "type": "host_action",
                    "name": "host_action__authoring__preview_lesson_patch",
                },
            ],
        )

    kwargs = _base_direct_kwargs()
    kwargs.update(
        {
            "looks_identity_selfhood_turn": lambda *_args, **_kwargs: False,
            "get_effective_provider": lambda *_args, **_kwargs: None,
            "get_explicit_user_provider": lambda *_args, **_kwargs: None,
            "collect_direct_tools": lambda *_args, **_kwargs: ([], False),
            "execute_direct_tool_rounds": fake_execute_direct_tool_rounds,
            "extract_direct_response": lambda *_args, **_kwargs: (
                "Preview sent to LMS.",
                "Preview was created from a declared host capability.",
                [],
            ),
        }
    )

    with (
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            side_effect=AssertionError("preview host action should not need native LLM"),
        ),
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            side_effect=AssertionError("preview host action should not need planner LLM"),
        ),
    ):
        result = await direct_response_node_impl(state, **kwargs)

    assert result["final_response"] == "Preview sent to LMS."
    assert captured["forced_tool_choice"] == "host_action__authoring__preview_lesson_patch"
    assert captured["tool_names"] == ["host_action__authoring__preview_lesson_patch"]
    assert result["routing_metadata"]["doc_preview_preflight"]["status"] == "executed"
    assert result["tool_call_events"][0]["type"] == "call"


@pytest.mark.asyncio
async def test_direct_response_node_preflights_document_preview_before_tool_collection():
    state = _base_state()
    state.update(
        {
            "query": (
                "Dua tren tai lieu Word vua upload, tao ban xem truoc "
                "preview_lesson_patch co source_references va approval_token."
            ),
            "session_id": "session-doc-preview-preflight",
            "routing_metadata": {
                "method": "deterministic_document_context_guard",
                "intent": "uploaded_file_context",
            },
            "context": {
                "response_language": "vi",
                "user_role": "teacher",
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "lesson.docx",
                            "markdown": "Marker WIII_DOC_GOAL_PREFLIGHT\nNguon trang 4.",
                        }
                    ]
                },
                "host_capabilities": {
                    "tools": [
                        {
                            "name": "authoring.preview_lesson_patch",
                            "description": "Preview lesson patch",
                            "roles": ["teacher"],
                            "permission": "manage:courses",
                            "mutates_state": False,
                            "requires_confirmation": False,
                        },
                    ]
                },
            },
        }
    )
    _mark_lms_authoring_connected(state)

    captured: dict[str, object] = {}

    async def fake_execute_direct_tool_rounds(*args, **kwargs):
        captured["forced_tool_choice"] = kwargs.get("forced_tool_choice")
        captured["tool_names"] = [
            getattr(tool, "name", getattr(tool, "__name__", ""))
            for tool in args[3]
        ]
        return (
            SimpleNamespace(content="Preview sent to LMS."),
            [],
            [
                {
                    "type": "call",
                    "name": "host_action__authoring__preview_lesson_patch",
                },
                {
                    "type": "host_action",
                    "name": "host_action__authoring__preview_lesson_patch",
                },
            ],
        )

    kwargs = _base_direct_kwargs()
    kwargs.update(
        {
            "looks_identity_selfhood_turn": lambda *_args, **_kwargs: False,
            "get_effective_provider": lambda *_args, **_kwargs: None,
            "get_explicit_user_provider": lambda *_args, **_kwargs: None,
            "collect_direct_tools": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("document preview preflight must not depend on tool collection")
            ),
            "execute_direct_tool_rounds": fake_execute_direct_tool_rounds,
            "extract_direct_response": lambda *_args, **_kwargs: (
                "Preview sent to LMS.",
                "Preview was created from a declared host capability.",
                [],
            ),
        }
    )

    with (
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            side_effect=AssertionError("preview host action should not need native LLM"),
        ),
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            side_effect=AssertionError("preview host action should not need planner LLM"),
        ),
    ):
        result = await direct_response_node_impl(state, **kwargs)

    assert result["final_response"] == "Preview sent to LMS."
    assert captured["forced_tool_choice"] == "host_action__authoring__preview_lesson_patch"
    assert captured["tool_names"] == ["host_action__authoring__preview_lesson_patch"]
    assert result["routing_metadata"]["doc_preview_preflight"]["status"] == "executed"
    assert result["tool_call_events"][1]["type"] == "host_action"


@pytest.mark.asyncio
async def test_direct_response_node_preflights_document_course_plan_for_real_teacher_wording():
    state = _base_state()
    state.update(
        {
            "query": (
                "Dua tren file Word vua upload, hay thiet ke mot chuong trinh dao tao "
                "hoan chinh cho giao vien: co lo trinh hoc, de cuong khoa, chia thanh "
                "chuong va nhieu bai hoc, moi bai phai co citation."
            ),
            "session_id": "session-doc-course-preflight",
            "routing_metadata": {
                "method": "deterministic_document_context_guard",
                "intent": "uploaded_file_context",
            },
            "context": {
                "response_language": "vi",
                "user_role": "teacher",
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "# Huong Dan Su Dung HoLiLiHu LMS\n"
                                "Nguon section: 4. Huong Dan Cho Giang Vien (trang 21-34)\n"
                                "## 4.4. Soan cau truc chuong va bai\n"
                            ),
                        }
                    ]
                },
                "host_capabilities": {
                    "tools": [
                        {
                            "name": "authoring.generate_course_from_document",
                            "description": "Preview course plan from document",
                            "roles": ["teacher"],
                            "permission": "manage:courses",
                            "mutates_state": False,
                            "requires_confirmation": False,
                        },
                        {
                            "name": "authoring.preview_lesson_patch",
                            "description": "Preview lesson patch",
                            "roles": ["teacher"],
                            "permission": "manage:courses",
                            "mutates_state": False,
                            "requires_confirmation": False,
                        },
                    ]
                },
            },
        }
    )
    _mark_lms_authoring_connected(state)

    captured: dict[str, object] = {}

    async def fake_execute_direct_tool_rounds(*args, **kwargs):
        captured["forced_tool_choice"] = kwargs.get("forced_tool_choice")
        captured["tool_names"] = [
            getattr(tool, "name", getattr(tool, "__name__", ""))
            for tool in args[3]
        ]
        return (
            SimpleNamespace(content="Course plan preview sent to LMS."),
            [],
            [
                {
                    "type": "call",
                    "name": "host_action__authoring__generate_course_from_document",
                },
                {
                    "type": "host_action",
                    "name": "host_action__authoring__generate_course_from_document",
                },
            ],
        )

    kwargs = _base_direct_kwargs()
    kwargs.update(
        {
            "looks_identity_selfhood_turn": lambda *_args, **_kwargs: False,
            "get_effective_provider": lambda *_args, **_kwargs: None,
            "get_explicit_user_provider": lambda *_args, **_kwargs: None,
            "collect_direct_tools": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("document course preflight must not depend on tool collection")
            ),
            "execute_direct_tool_rounds": fake_execute_direct_tool_rounds,
            "extract_direct_response": lambda *_args, **_kwargs: (
                "Course plan preview sent to LMS.",
                "Course plan was created from uploaded document context.",
                [],
            ),
        }
    )

    with (
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            side_effect=AssertionError("course plan preview should not need native LLM"),
        ),
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            side_effect=AssertionError("course plan preview should not need planner LLM"),
        ),
    ):
        result = await direct_response_node_impl(state, **kwargs)

    assert result["final_response"] == "Course plan preview sent to LMS."
    assert captured["forced_tool_choice"] == "host_action__authoring__generate_course_from_document"
    assert captured["tool_names"] == ["host_action__authoring__generate_course_from_document"]
    assert result["routing_metadata"]["doc_preview_preflight"]["status"] == "executed"
    assert result["tool_call_events"][1]["type"] == "host_action"


@pytest.mark.asyncio
async def test_direct_response_node_preflights_short_teacher_bai_giang_request():
    state = _base_state()
    state.update(
        {
            "query": "Tạo bài giảng đi.",
            "session_id": "session-doc-course-short",
            "routing_metadata": {
                "method": "deterministic_document_context_guard",
                "intent": "uploaded_file_context",
            },
            "context": {
                "response_language": "vi",
                "user_role": "teacher",
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "SV25-26.43_KH-KT.docx",
                            "markdown": (
                                "# Nghiên cứu xây dựng hệ thống quản lý vận hành và hồ sơ tàu thủy\n"
                                "## Mục tiêu nghiên cứu\n"
                                "Tài liệu mô tả bài toán doanh nghiệp vận tải biển."
                            ),
                        }
                    ]
                },
                "host_capabilities": {
                    "tools": [
                        {
                            "name": "authoring.generate_course_from_document",
                            "description": "Preview course plan from document",
                            "roles": ["teacher"],
                            "permission": "manage:courses",
                            "mutates_state": False,
                            "requires_confirmation": False,
                        }
                    ]
                },
            },
        }
    )
    _mark_lms_authoring_connected(state)

    captured: dict[str, object] = {}

    async def fake_execute_direct_tool_rounds(*args, **kwargs):
        captured["forced_tool_choice"] = kwargs.get("forced_tool_choice")
        captured["tool_names"] = [
            getattr(tool, "name", getattr(tool, "__name__", ""))
            for tool in args[3]
        ]
        return (
            SimpleNamespace(content="Course plan preview sent to LMS."),
            [],
            [
                {
                    "type": "call",
                    "name": "host_action__authoring__generate_course_from_document",
                },
                {
                    "type": "host_action",
                    "name": "host_action__authoring__generate_course_from_document",
                },
            ],
        )

    kwargs = _base_direct_kwargs()
    kwargs.update(
        {
            "looks_identity_selfhood_turn": lambda *_args, **_kwargs: False,
            "get_effective_provider": lambda *_args, **_kwargs: None,
            "get_explicit_user_provider": lambda *_args, **_kwargs: None,
            "collect_direct_tools": lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("short document course request must preflight before tool collection")
            ),
            "execute_direct_tool_rounds": fake_execute_direct_tool_rounds,
            "extract_direct_response": lambda *_args, **_kwargs: (
                "Course plan preview sent to LMS.",
                "Course plan was created from uploaded document context.",
                [],
            ),
        }
    )

    with (
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
            side_effect=AssertionError("short course plan preview should not need native LLM"),
        ),
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            side_effect=AssertionError("short course plan preview should not need planner LLM"),
        ),
    ):
        result = await direct_response_node_impl(state, **kwargs)

    assert result["final_response"] == "Course plan preview sent to LMS."
    assert captured["forced_tool_choice"] == "host_action__authoring__generate_course_from_document"
    assert captured["tool_names"] == ["host_action__authoring__generate_course_from_document"]
    assert result["routing_metadata"]["doc_preview_preflight"]["status"] == "executed"
    assert result["tool_call_events"][1]["type"] == "host_action"


@pytest.mark.asyncio
async def test_direct_response_node_handles_image_input_with_vision_before_llm():
    async def fake_analyze_image_for_query(**kwargs):
        assert kwargs["image_base64"] == "iVBORw0KGgo="
        assert kwargs["media_type"] == "image/png"
        return SimpleNamespace(success=True, text="Anh co mot bieu do mau xanh va mot vung chu thich.")

    state = _base_state()
    state.update(
        {
            "query": "Nhin anh nay va mo ta ngan gon giup minh",
            "context": {
                "response_language": "vi",
                "user_role": "student",
                "images": [
                    {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": "iVBORw0KGgo=",
                    }
                ],
            },
            "routing_metadata": {
                "method": "deterministic_image_input_guard",
                "intent": "image_input",
            },
        }
    )

    with (
        patch("app.engine.vision_runtime.analyze_image_for_query", fake_analyze_image_for_query),
        patch(
            "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
            side_effect=AssertionError("image input preflight should not call a chat LLM"),
        ),
    ):
        result = await direct_response_node_impl(
            state,
            **_base_direct_kwargs(),
        )

    assert "bieu do mau xanh" in result["final_response"]
    assert result["thinking_content"]


@pytest.mark.asyncio
async def test_direct_response_node_uses_reasoning_safety_fast_path_without_llm():
    state = _base_state()
    state.update(
        {
            "query": (
                "Giải thích ngắn sự khác nhau giữa visible thinking an toàn "
                "và chain-of-thought nội bộ. Trả lời 4 bullet, không dùng công cụ."
            ),
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "off_topic",
            },
        }
    )

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("reasoning safety fast path should not call an LLM"),
    ):
        result = await direct_response_node_impl(
            state,
            **_base_direct_kwargs(),
        )

    assert "public reasoning trace" in result["final_response"]
    assert "biết lùi lại" in result["thinking_content"]


@pytest.mark.asyncio
async def test_direct_response_node_routes_hunger_chatter_to_provider_pipeline():
    state = _base_state()
    state.update(
        {
            "query": "đói phết",
            "routing_metadata": {
                "method": "always_on_chatter_fast_path",
                "intent": "social",
            },
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False

    with patch(
        "app.engine.multi_agent.direct_node_runtime.execute_direct_node_llm_pipeline",
        new=AsyncMock(
            return_value=SimpleNamespace(response="model-backed hunger reply")
        ),
    ) as mock_pipeline:
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "model-backed hunger reply"
    mock_pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_response_node_routes_social_status_to_provider_pipeline():
    state = _base_state()
    state.update(
        {
            "query": "trưa nay ăn cơm rồi",
            "routing_metadata": {
                "method": "structured",
                "intent": "social",
            },
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False

    with patch(
        "app.engine.multi_agent.direct_node_runtime.execute_direct_node_llm_pipeline",
        new=AsyncMock(
            return_value=SimpleNamespace(response="model-backed status reply")
        ),
    ) as mock_pipeline:
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "model-backed status reply"
    mock_pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_response_node_uses_self_feeling_probe_without_llm():
    state = _base_state()
    state.update(
        {
            "query": "ạn buồn không?",
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "social",
            },
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("self-feeling probe should not call an LLM"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert "không buồn theo kiểu có cơ thể" in result["final_response"]
    assert "trầm xuống" in result["final_response"]
    assert "không nên giả vờ" in result["thinking_content"]


@pytest.mark.asyncio
async def test_direct_response_node_acknowledges_session_memory_write_without_llm():
    state = _base_state()
    state.update(
        {
            "query": "Ghi nho trong phien nay: ma mau bao cao Wiii la cam lua. Ma kiem thu MEMORY-W-535.",
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "personal",
            },
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("session memory write fast path should not call an LLM"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert "cam lua" in result["final_response"]
    assert "Ma kiem thu" not in result["final_response"]
    assert "semantic memory" in result["thinking_content"]


@pytest.mark.asyncio
async def test_direct_response_node_session_memory_write_trims_instructions_and_keeps_marker():
    state = _base_state()
    state.update(
        {
            "query": (
                "[FIELD-508R-01B] Hãy nhớ tạm trong cuộc trò chuyện này 3 neo kiểm thử: "
                "mã \"HAI-DANG-508\", tiêu chí \"ấm nhưng không lố\", và ưu tiên "
                "\"Pointy/Web/RAG phải đúng route\". Không dùng web, không dùng RAG, "
                "không dùng Pointy. Trả lời tự nhiên và bắt đầu bằng đúng marker [FIELD-508R-01B]."
            ),
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "personal",
            },
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("session memory write fast path should not call an LLM"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"].startswith("[FIELD-508R-01B]")
    assert "HAI-DANG-508" in result["final_response"]
    assert "ấm nhưng không lố" in result["final_response"]
    assert "Pointy/Web/RAG phải đúng route" in result["final_response"]
    assert "Không dùng web" not in result["final_response"]
    assert "không dùng RAG" not in result["final_response"]
    assert "Khong dung web" not in result["final_response"]
    assert "khong dung RAG" not in result["final_response"]


@pytest.mark.asyncio
async def test_direct_response_node_session_recall_wins_over_write_marker():
    state = _base_state()
    state.update(
        {
            "query": (
                "[FIELD-508R-02] Nhac lai dung 3 neo kiem thu minh vua bao ban nho "
                "trong phien nay. Tra loi dung 3 gach dau dong, khong dung web, "
                "khong dung RAG, khong dung Pointy, va bat dau bang marker [FIELD-508R-02]."
            ),
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "[FIELD-508R-01C] Hay nho tam trong cuoc tro chuyen nay 3 neo kiem thu: "
                        "ma \"HAI-DANG-508C\", tieu chi \"am nhung khong lo\", va uu tien "
                        "\"Pointy/Web/RAG phai dung route\"."
                    ),
                },
                {"role": "assistant", "content": "Da ghi nhan."},
                {
                    "role": "user",
                    "content": (
                        "[FIELD-508R-02] Nhac lai dung 3 neo kiem thu minh vua bao ban nho "
                        "trong phien nay. Tra loi dung 3 gach dau dong, khong dung web, "
                        "khong dung RAG, khong dung Pointy, va bat dau bang marker [FIELD-508R-02]."
                    ),
                },
            ],
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "personal",
            },
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("session recall fast path should not call an LLM"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"].startswith("[FIELD-508R-02]")
    assert result["final_response"].startswith("[FIELD-508R-02]\n- ")
    assert "HAI-DANG-508C" in result["final_response"]
    assert "am nhung khong lo" in result["final_response"]
    assert "Pointy/Web/RAG phai dung route" in result["final_response"]
    assert "Da ghi nhan" not in result["final_response"]


@pytest.mark.asyncio
async def test_direct_response_node_emergency_searches_when_provider_busy_before_tools():
    queries = []

    class FakeSearchTool:
        name = "tool_web_search"

        async def ainvoke(self, args):
            queries.append(args.get("query"))
            return (
                "**OpenAI Responses API reference**\n"
                "It documents the Responses API endpoint.\n"
                "URL: https://developers.openai.com/api/reference/responses"
            )

    events = []
    state = _base_state()
    state.update(
        {
            "query": "Tìm trên web giúp mình: OpenAI Responses API endpoint nào?",
            "routing_metadata": {
                "method": "structured",
                "intent": "web_search",
            },
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False
    kwargs["needs_web_search"] = lambda *_args, **_kwargs: True
    kwargs["collect_direct_tools"] = lambda *_args, **_kwargs: ([FakeSearchTool()], True)
    kwargs["capture_public_thinking_event"] = lambda _state, event: events.append(event)

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
        side_effect=ProviderUnavailableError(
            provider="nvidia",
            reason_code="busy",
            message="busy",
        ),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert "developers.openai.com/api/reference/responses" in result["final_response"]
    assert queries == [
        "OpenAI API Reference Responses POST /v1/responses platform.openai.com"
    ]
    assert any(event.get("type") == "tool_call" for event in events)
    assert any(event.get("type") == "tool_result" for event in events)


@pytest.mark.asyncio
async def test_direct_response_node_forces_web_search_intent_without_mutating_force_skills():
    class FakeSearchTool:
        name = "tool_web_search"

    captured: dict[str, object] = {}

    async def fake_execute_direct_tool_rounds(
        _llm_with_tools,
        _llm_auto,
        _messages,
        _tools,
        _push_event,
        **kwargs,
    ):
        captured["state_force_skills"] = list(kwargs["state"].get("force_skills") or [])
        captured["forced_tool_choice"] = kwargs.get("forced_tool_choice")
        return (
            SimpleNamespace(content="Source-backed web answer", tool_calls=[]),
            [],
            [
                {
                    "type": "result",
                    "name": "tool_web_search",
                    "result": "URL: https://platform.openai.com/docs/api-reference/responses",
                }
            ],
        )

    state = _base_state()
    state.update(
        {
            "query": "Tìm web từ nguồn chính thức OpenAI: Responses API endpoint là gì?",
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "web_search",
            },
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False
    kwargs["needs_web_search"] = lambda *_args, **_kwargs: False
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["collect_direct_tools"] = lambda *_args, **_kwargs: ([FakeSearchTool()], False)
    kwargs["bind_direct_tools"] = lambda llm, tools, force_tools, **_kwargs: (
        SimpleNamespace(bound=True),
        SimpleNamespace(auto=True),
        "any" if force_tools else None,
    )
    kwargs["execute_direct_tool_rounds"] = fake_execute_direct_tool_rounds
    kwargs["extract_direct_response"] = lambda llm_response, _messages: (
        llm_response.content,
        "",
        [{"name": "tool_web_search"}],
    )

    with (
        patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm", return_value=None),
        patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=object()),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert captured["state_force_skills"] == []
    assert captured["forced_tool_choice"] == "any"
    assert result["final_response"] == "Source-backed web answer"
    assert result["tool_call_events"][0]["name"] == "tool_web_search"


@pytest.mark.asyncio
async def test_direct_response_node_emergency_searches_when_explicit_provider_times_out_before_tools():
    queries = []

    class FakeSearchTool:
        name = "tool_web_search"

        async def ainvoke(self, args):
            queries.append(args.get("query"))
            return (
                "**Responses Overview | OpenAI API Reference**\n"
                "OpenAI's most advanced interface for generating model responses.\n"
                "URL: https://developers.openai.com/api/reference/responses/overview"
            )

    async def _raise_timeout(*_args, **_kwargs):
        raise TimeoutError("provider timed out before tool_calls")

    events = []
    state = _base_state()
    state.update(
        {
            "query": "Tìm trên web giúp mình: OpenAI Responses API endpoint nào?",
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "web_search",
            },
            "provider": "nvidia",
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False
    kwargs["needs_web_search"] = lambda *_args, **_kwargs: True
    kwargs["collect_direct_tools"] = lambda *_args, **_kwargs: ([FakeSearchTool()], True)
    kwargs["bind_direct_tools"] = lambda llm, tools, *_args, **_kwargs: (llm, llm, "any")
    kwargs["execute_direct_tool_rounds"] = _raise_timeout
    kwargs["capture_public_thinking_event"] = lambda _state, event: events.append(event)

    with (
        patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm", return_value=None),
        patch("app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm", return_value=object()),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert "`POST https://api.openai.com/v1/responses`" in result["final_response"]
    assert "developers.openai.com/api/reference/responses/overview" in result["final_response"]
    assert queries == [
        "OpenAI API Reference Responses POST /v1/responses platform.openai.com"
    ]
    assert any(event.get("type") == "tool_call" for event in events)
    assert any(event.get("type") == "tool_result" for event in events)


@pytest.mark.asyncio
async def test_direct_response_node_uses_capability_inventory_without_llm():
    state = _base_state()
    state.update(
        {
            "query": "Wiii có xử lý được ảnh đầu vào không, tạo ảnh, xử lý file Word, Excel, video?",
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "off_topic",
            },
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("capability inventory should not call an LLM"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert "tối đa 5 ảnh" in result["final_response"]
    assert ".docx" in result["final_response"]
    assert ".xlsx" in result["final_response"]
    assert "chưa nên hứa" in result["final_response"]
    assert "sự thật hơn là quảng cáo" in result["thinking_content"]


@pytest.mark.asyncio
async def test_direct_response_node_uses_single_value_session_recall_fast_path_without_llm():
    state = _base_state()
    state.update(
        {
            "query": "Minh vua bao ban nho ma kiem thu UX nao?",
            "routing_metadata": {
                "method": "conservative_fast_path",
                "intent": "personal",
            },
            "messages": [
                {
                    "role": "user",
                    "content": (
                        "Trong phiên này, hãy nhớ mã kiểm thử UX hôm nay là "
                        "mỏ neo xanh 507 và ưu tiên Thinking dài có ý nghĩa. "
                        "Trả lời chỉ: Đã ghi nhận."
                    ),
                },
                {"role": "assistant", "content": "Đã ghi nhận."},
            ],
        }
    )

    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("session recall fast path should not call an LLM"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
    )

    assert result["final_response"] == "mỏ neo xanh 507"
    assert "đọc lịch sử gần nhất" in result["thinking_content"]


@pytest.mark.asyncio
async def test_direct_response_node_reraises_provider_unavailable_from_llm_resolution():
    state = _base_state()

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=ProviderUnavailableError(
            provider="google",
            reason_code="busy",
            message="Provider duoc chon hien khong san sang de xu ly yeu cau nay.",
        ),
    ):
        with pytest.raises(ProviderUnavailableError):
            await direct_response_node_impl(
                state,
                **_base_direct_kwargs(),
            )


@pytest.mark.asyncio
async def test_direct_response_node_reraises_provider_unavailable_when_llm_missing_for_explicit_provider():
    state = _base_state()

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=None,
    ):
        with pytest.raises(ProviderUnavailableError):
            await direct_response_node_impl(
                state,
                **_base_direct_kwargs(),
            )


@pytest.mark.asyncio
async def test_direct_response_node_wraps_runtime_provider_failure_for_explicit_provider():
    state = _base_state()
    kwargs = _base_direct_kwargs()
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)

    async def _raise_rate_limit(*_args, **_kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    kwargs["execute_direct_tool_rounds"] = _raise_rate_limit

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=object(),
    ):
        with pytest.raises(ProviderUnavailableError) as exc_info:
            await direct_response_node_impl(
                state,
                **kwargs,
            )

    assert exc_info.value.provider == "google"
    assert exc_info.value.reason_code == "rate_limit"


@pytest.mark.asyncio
async def test_direct_response_node_uses_native_handle_without_explicit_provider():
    from app.engine.native_chat_runtime import NativeChatModelHandle, make_assistant_message

    state = _base_state()
    state["query"] = "Hay noi ngan gon ve Wiii"
    state["routing_metadata"] = {"intent": "general"}
    state.pop("provider", None)

    kwargs = _base_direct_kwargs()
    captured: dict = {}
    native_handle = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
        _wiii_tier_key="light",
    )
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: None
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["bind_direct_tools"] = lambda llm, *_args, **_kwargs: (llm, llm, None)

    def _build_messages(*_args, **build_kwargs):
        captured["native_messages"] = build_kwargs.get("native_messages")
        return [{"role": "user", "content": state["query"]}]

    kwargs["build_direct_system_messages"] = _build_messages
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: (
        "Native route ok",
        "",
        [],
    )

    async def _execute(llm_with_tools, _llm_auto, messages, *_args, **_kwargs):
        captured["llm"] = llm_with_tools
        captured["messages"] = messages
        captured["native_tool_messages"] = _kwargs.get("native_tool_messages")
        return make_assistant_message("Native route ok"), messages, []

    kwargs["execute_direct_tool_rounds"] = _execute

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
        return_value=native_handle,
    ) as mock_get_native, patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("legacy LangChain LLM should not be constructed"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Native route ok"
    assert captured["llm"] is native_handle
    assert captured["native_messages"] is True
    assert captured["native_tool_messages"] is True
    assert captured["messages"] == [{"role": "user", "content": state["query"]}]
    mock_get_native.assert_called_once()


@pytest.mark.asyncio
async def test_direct_response_node_uses_native_handle_for_forced_tool_turn():
    from app.engine.native_chat_runtime import NativeChatModelHandle, make_assistant_message

    state = _base_state()
    state["query"] = "May gio roi?"
    state["routing_metadata"] = {"intent": "lookup"}
    state.pop("provider", None)

    tool = SimpleNamespace(
        name="tool_current_datetime",
        description="Get current date and time",
        parameters={"type": "object", "properties": {}},
    )
    native_handle = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
        _wiii_tier_key="light",
    )
    kwargs = _base_direct_kwargs()
    captured: dict = {}
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: None
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["collect_direct_tools"] = lambda *_args, **_kwargs: ([tool], True)
    kwargs["direct_required_tool_names"] = lambda *_args, **_kwargs: ["tool_current_datetime"]
    kwargs["bind_direct_tools"] = lambda llm, *_args, **_kwargs: (
        llm.bind_tools([tool], tool_choice="tool_current_datetime"),
        llm.bind_tools([tool]),
        "tool_current_datetime",
    )
    kwargs["build_direct_system_messages"] = lambda *_args, **_kwargs: [
        {"role": "user", "content": state["query"]}
    ]
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: (
        "Bay gio la 10:00.",
        "",
        ["tool_current_datetime"],
    )

    async def _execute(llm_with_tools, _llm_auto, messages, *_args, **_kwargs):
        captured["llm"] = llm_with_tools
        captured["forced_tool_choice"] = _kwargs.get("forced_tool_choice")
        captured["native_tool_messages"] = _kwargs.get("native_tool_messages")
        return make_assistant_message("Bay gio la 10:00."), messages, [
            {"type": "call", "name": "tool_current_datetime", "id": "call_1"},
        ]

    kwargs["execute_direct_tool_rounds"] = _execute

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
        return_value=native_handle,
    ), patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("legacy LangChain LLM should not be constructed"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Bay gio la 10:00."
    assert captured["llm"]._wiii_native_route is True
    assert captured["llm"]._wiii_bound_tools[0]["function"]["name"] == "tool_current_datetime"
    assert captured["forced_tool_choice"] == "tool_current_datetime"
    assert captured["native_tool_messages"] is True


@pytest.mark.asyncio
async def test_direct_response_node_uses_native_handle_for_optional_tool_turn():
    from app.engine.native_chat_runtime import NativeChatModelHandle, make_assistant_message

    state = _base_state()
    state["query"] = "Co gi moi trong khoa hoc cua toi?"
    state["routing_metadata"] = {"intent": "general"}
    state.pop("provider", None)

    tool = SimpleNamespace(
        name="tool_lms_courses",
        description="Inspect LMS courses",
        parameters={"type": "object", "properties": {}},
    )
    native_handle = NativeChatModelHandle(
        _wiii_provider_name="nvidia",
        _wiii_model_name="deepseek-ai/deepseek-v4-flash",
        _wiii_tier_key="light",
    )
    kwargs = _base_direct_kwargs()
    captured: dict = {}
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: None
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["collect_direct_tools"] = lambda *_args, **_kwargs: ([tool], False)
    kwargs["direct_required_tool_names"] = lambda *_args, **_kwargs: []
    kwargs["bind_direct_tools"] = lambda llm, *_args, **_kwargs: (
        llm.bind_tools([tool]),
        llm.bind_tools([tool]),
        None,
    )
    kwargs["build_direct_system_messages"] = lambda *_args, **_kwargs: [
        {"role": "user", "content": state["query"]}
    ]
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: (
        "Khoa hoc cua ban dang on.",
        "",
        [],
    )

    async def _execute(llm_with_tools, _llm_auto, messages, *_args, **_kwargs):
        captured["llm"] = llm_with_tools
        captured["forced_tool_choice"] = _kwargs.get("forced_tool_choice")
        captured["native_tool_messages"] = _kwargs.get("native_tool_messages")
        return make_assistant_message("Khoa hoc cua ban dang on."), messages, []

    kwargs["execute_direct_tool_rounds"] = _execute

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
        return_value=native_handle,
    ), patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        side_effect=AssertionError("legacy LangChain LLM should not be constructed"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Khoa hoc cua ban dang on."
    assert captured["llm"]._wiii_native_route is True
    assert captured["llm"]._wiii_bound_tools[0]["function"]["name"] == "tool_lms_courses"
    assert captured["forced_tool_choice"] is None
    assert captured["native_tool_messages"] is True


@pytest.mark.asyncio
async def test_direct_response_node_salvages_final_result_when_post_processing_fails():
    state = _base_state()
    kwargs = _base_direct_kwargs()
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: (
        "Wiii ra doi vao mot dem mua tai The Wiii Lab.",
        "Minh dang lan theo dem dau tien cua minh o The Wiii Lab.",
        [],
    )
    kwargs["sanitize_wiii_house_text"] = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("cleanup boom")
    )

    async def _return_final_result(*_args, **_kwargs):
        return (
            SimpleNamespace(
                content="Wiii ra doi vao mot dem mua tai The Wiii Lab.",
                response_metadata={
                    "thinking_content": "Minh dang lan theo dem dau tien cua minh o The Wiii Lab.",
                },
                additional_kwargs={},
                tool_calls=[],
            ),
            [],
            [],
        )

    kwargs["execute_direct_tool_rounds"] = _return_final_result

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=SimpleNamespace(_wiii_provider_name="google"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Wiii ra doi vao mot dem mua tai The Wiii Lab."
    assert result["thinking_content"] == "Minh dang lan theo dem dau tien cua minh o The Wiii Lab."
    assert result["agent_outputs"]["direct"] == result["final_response"]


@pytest.mark.asyncio
async def test_direct_response_node_does_not_pin_provider_when_user_did_not_explicitly_choose_one():
    state = _base_state()
    captured: dict[str, object] = {}
    kwargs = _base_direct_kwargs()
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)

    async def _capture_execute(*_args, **_kwargs):
        captured.update(_kwargs)
        return SimpleNamespace(content="Wiii van o day.", tool_calls=[]), [], []

    kwargs["execute_direct_tool_rounds"] = _capture_execute
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: ("Wiii van o day.", "", [])

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=SimpleNamespace(_wiii_provider_name="google"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Wiii van o day."
    assert captured["provider"] is None


@pytest.mark.asyncio
async def test_direct_response_node_reraises_provider_unavailable_even_without_explicit_provider():
    state = _base_state()
    kwargs = _base_direct_kwargs()
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)

    async def _raise_unavailable(*_args, **_kwargs):
        raise ProviderUnavailableError(
            provider="zhipu",
            reason_code="busy",
            message="Provider duoc chon tam thoi ban hoac da cham gioi han.",
        )

    kwargs["execute_direct_tool_rounds"] = _raise_unavailable

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=SimpleNamespace(_wiii_provider_name="google"),
    ):
        with pytest.raises(ProviderUnavailableError) as exc_info:
            await direct_response_node_impl(
                state,
                **kwargs,
            )

    assert exc_info.value.provider == "zhipu"
    assert exc_info.value.reason_code == "busy"


@pytest.mark.asyncio
async def test_direct_response_node_forwards_lane_primary_timeout_for_zhipu_selfhood():
    from app.engine.multi_agent.direct_response_runtime import (
        resolve_direct_answer_timeout_profile_impl,
    )

    state = _base_state()
    state["provider"] = "zhipu"
    captured: dict[str, object] = {}
    kwargs = _base_direct_kwargs()
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: "zhipu"
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: "zhipu"
    kwargs["resolve_direct_answer_timeout_profile"] = resolve_direct_answer_timeout_profile_impl
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)

    async def _capture_execute(*_args, **_kwargs):
        captured.update(_kwargs)
        return SimpleNamespace(content="Wiii ra doi tu The Wiii Lab.", tool_calls=[]), [], []

    kwargs["execute_direct_tool_rounds"] = _capture_execute
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: ("Wiii ra doi tu The Wiii Lab.", "", [])

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=SimpleNamespace(_wiii_provider_name="zhipu"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Wiii ra doi tu The Wiii Lab."


@pytest.mark.asyncio
async def test_direct_response_node_restricts_selfhood_cross_provider_fallback_to_ollama():
    state = _base_state()
    state["provider"] = "zhipu"
    captured: dict[str, object] = {}
    kwargs = _base_direct_kwargs()
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: "zhipu"
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)

    async def _capture_execute(*_args, **_kwargs):
        captured.update(_kwargs)
        return SimpleNamespace(content="Wiii van o day.", tool_calls=[]), [], []

    kwargs["execute_direct_tool_rounds"] = _capture_execute
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: ("Wiii van o day.", "", [])

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=SimpleNamespace(_wiii_provider_name="zhipu", model="glm-5"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Wiii van o day."
    assert captured["allowed_fallback_providers"] == ("ollama",)


@pytest.mark.asyncio
async def test_direct_response_node_forwards_requested_model_to_agent_config():
    state = _base_state()
    state["provider"] = "openrouter"
    state["model"] = "qwen/qwen3.6-plus:free"
    kwargs = _base_direct_kwargs()
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: "openrouter"
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: "openrouter"
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)

    async def _return_final_result(*_args, **_kwargs):
        return SimpleNamespace(content="Minh nghe ro yeu cau nay.", tool_calls=[]), [], []

    kwargs["execute_direct_tool_rounds"] = _return_final_result
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: ("Minh nghe ro yeu cau nay.", "", [])

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=SimpleNamespace(_wiii_provider_name="openrouter"),
    ) as get_llm_mock:
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Minh nghe ro yeu cau nay."
    assert get_llm_mock.call_args.kwargs["requested_model"] == "qwen/qwen3.6-plus:free"


@pytest.mark.asyncio
async def test_direct_response_node_backfills_emotional_visible_thought_when_model_returns_none():
    state = {
        "query": "mình buồn quá",
        "context": {
            "response_language": "vi",
            "user_role": "student",
        },
        "domain_id": "maritime",
        "domain_config": {},
        "routing_metadata": {"intent": "personal"},
        "provider": "zhipu",
    }
    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: "zhipu"
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)

    async def _execute(*_args, **_kwargs):
        return (
            SimpleNamespace(content="Mình ở đây nghe cậu nói đây.", tool_calls=[]),
            [],
            [],
        )

    async def _reasoning_summary(*_args, **_kwargs):
        return (
            "Câu này nhẹ hơn một lượt đào sâu, nên mình sẽ giữ phản hồi ngắn và tự nhiên.\n\n"
            "Mình muốn bám vào nhịp của câu vừa rồi trước, rồi đáp lại vừa đủ gần."
        )

    kwargs["execute_direct_tool_rounds"] = _execute
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: (
        "Mình ở đây nghe cậu nói đây.",
        "",
        [],
    )
    kwargs["build_direct_reasoning_summary"] = _reasoning_summary

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=SimpleNamespace(_wiii_provider_name="zhipu"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Mình ở đây nghe cậu nói đây."
    assert "Câu này nhẹ hơn một lượt đào sâu" in result["thinking_content"]
    assert "Mình muốn bám vào nhịp" in result["thinking_content"]


@pytest.mark.asyncio
async def test_direct_response_node_pins_llm_resolution_to_explicit_user_provider():
    state = _base_state()
    state["provider"] = "google"
    kwargs = _base_direct_kwargs()
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: "google"
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: "openrouter"
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)

    async def _execute(*_args, **_kwargs):
        return (
            SimpleNamespace(content="OpenRouter dang chay.", tool_calls=[]),
            [],
            [],
        )

    kwargs["execute_direct_tool_rounds"] = _execute
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: ("OpenRouter dang chay.", "", [])

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=SimpleNamespace(_wiii_provider_name="openrouter"),
    ) as mock_get_llm:
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "OpenRouter dang chay."
    assert mock_get_llm.call_args.kwargs["provider_override"] == "openrouter"


@pytest.mark.asyncio
async def test_direct_response_node_strips_tools_for_emotional_support_turns():
    from app.engine.multi_agent.direct_response_runtime import (
        resolve_direct_answer_timeout_profile_impl,
    )

    state = {
        "query": "minh buon qua",
        "context": {
            "response_language": "vi",
            "user_role": "student",
        },
        "domain_id": "maritime",
        "domain_config": {},
        "routing_metadata": {"intent": "personal"},
        "provider": "zhipu",
    }
    captured: dict[str, object] = {}
    kwargs = _base_direct_kwargs()
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: "zhipu"
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["collect_direct_tools"] = lambda *_args, **_kwargs: ([SimpleNamespace(name="tool_web_search")], False)
    kwargs["resolve_direct_answer_timeout_profile"] = resolve_direct_answer_timeout_profile_impl
    kwargs["bind_direct_tools"] = lambda *_args, **_kwargs: (object(), object(), None)

    async def _execute(*args, **_kwargs):
        captured["tools"] = args[3]
        captured.update(_kwargs)
        return (
            SimpleNamespace(content="Minh o day voi cau day.", tool_calls=[]),
            [],
            [],
        )

    kwargs["execute_direct_tool_rounds"] = _execute
    kwargs["extract_direct_response"] = lambda *_args, **_kwargs: (
        "Minh o day voi cau day.",
        "",
        [],
    )

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_llm",
        return_value=SimpleNamespace(_wiii_provider_name="zhipu"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert result["final_response"] == "Minh o day voi cau day."
    assert captured["tools"] == []
    assert captured["direct_answer_primary_timeout"] == pytest.approx(8.0)


@pytest.mark.asyncio
async def test_direct_response_node_bounds_host_ui_navigation_total_timeout(monkeypatch):
    events = []
    state = {
        "query": "Wiii oi, nut Kham pha khoa hoc o dau?",
        "context": {
            "response_language": "vi",
            "user_role": "student",
        },
        "domain_id": "maritime",
        "domain_config": {},
        "routing_metadata": {"intent": "host_ui_navigation"},
        "provider": "nvidia",
    }
    kwargs = _base_direct_kwargs()
    kwargs["capture_public_thinking_event"] = lambda _state, event: events.append(event)
    kwargs["looks_identity_selfhood_turn"] = lambda *_args, **_kwargs: False
    kwargs["get_effective_provider"] = lambda *_args, **_kwargs: "nvidia"
    kwargs["get_explicit_user_provider"] = lambda *_args, **_kwargs: None
    kwargs["bind_direct_tools"] = lambda llm, *_args, **_kwargs: (llm, llm, None)
    kwargs["extract_direct_response"] = lambda llm_response, *_args, **_kwargs: (
        str(getattr(llm_response, "content", "")),
        "",
        [],
    )

    async def _slow_execute(*_args, **_kwargs):
        await asyncio.sleep(1)
        return SimpleNamespace(content="too late", tool_calls=[]), [], []

    kwargs["execute_direct_tool_rounds"] = _slow_execute
    monkeypatch.setattr(
        "app.engine.multi_agent.direct_node_runtime._HOST_UI_DIRECT_TOTAL_TIMEOUT_SECONDS",
        0.01,
    )

    with patch(
        "app.engine.multi_agent.agent_config.AgentConfigRegistry.get_native_llm",
        return_value=SimpleNamespace(_wiii_provider_name="nvidia"),
    ):
        result = await direct_response_node_impl(
            state,
            **kwargs,
        )

    assert "Mình đã nhận yêu cầu trỏ" in result["final_response"]
    assert any(
        event.get("type") == "answer_delta"
        and "Mình đã nhận yêu cầu trỏ" in event.get("content", "")
        for event in events
    )
