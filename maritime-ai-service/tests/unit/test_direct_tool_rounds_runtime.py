import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def test_build_direct_final_synthesis_instruction_is_mode_aware_for_market_turn():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_direct_final_synthesis_instruction,
    )

    instruction = _build_direct_final_synthesis_instruction(
        "phan tich gia dau",
        {},
        ["tool_web_search"],
    ).lower()

    assert "khong goi them cong cu" in instruction
    assert "mot cau thesis ve mat bang thi truong hien tai" in instruction
    assert "khong dung heading markdown nhu #, ##, ###" in instruction
    assert "khong dung bullet/bold kieu ban tin tong hop" in instruction
    assert "opec+" in instruction or "ton kho" in instruction


def test_explicit_web_search_returns_template_after_fetch_evidence():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _prefer_official_query_for_known_docs,
        _should_return_search_template_after_tool_round,
        _should_use_search_template_for_empty_response,
    )

    events = [
        {
            "type": "result",
            "name": "tool_web_search",
            "result": "**OpenAI Responses API**\nURL: https://developers.openai.com/api/reference/responses",
            "id": "search_1",
        },
        {
            "type": "result",
            "name": "tool_fetch_url",
            "result": "The Responses API exposes POST /v1/responses.",
            "id": "fetch_1",
        },
    ]

    assert _should_return_search_template_after_tool_round(
        query="Tìm trên web giúp mình: OpenAI Responses API endpoint nào?",
        state={"routing_metadata": {"intent": "unknown"}},
        tool_call_events=events,
        tool_round=1,
    ) is True
    assert _should_return_search_template_after_tool_round(
        query="Phân tích nội bộ từ dữ liệu đã có",
        state={"routing_metadata": {"intent": "general"}},
        tool_call_events=events,
        tool_round=1,
    ) is False
    assert _should_return_search_template_after_tool_round(
        query="Tìm trên web giúp mình: OpenAI Responses API endpoint nào?",
        state={"routing_metadata": {"intent": "unknown"}},
        tool_call_events=events[:1],
        tool_round=0,
    ) is False
    rich_search_events = [
        {
            "type": "result",
            "name": "tool_web_search",
            "result": (
                "**OpenAI Responses API**\n"
                "URL: https://developers.openai.com/api/reference/responses/overview\n"
                "POST /v1/responses creates a model response. "
                "GET /v1/responses/{response_id} retrieves a response. "
            )
            * 35,
            "id": "search_1",
        },
    ]
    assert _should_return_search_template_after_tool_round(
        query="Tìm trên web giúp mình: OpenAI Responses API endpoint nào?",
        state={"routing_metadata": {"intent": "unknown"}},
        tool_call_events=rich_search_events,
        tool_round=0,
    ) is True
    assert _prefer_official_query_for_known_docs(
        {"query": "OpenAI Responses API endpoints 2025"},
        "Tìm trên web giúp mình: OpenAI Responses API hiện tại có endpoint nào?",
    ) == {
        "query": "OpenAI API Reference Responses POST /v1/responses platform.openai.com"
    }
    assert _should_use_search_template_for_empty_response(
        query="Tìm web từ nguồn chính thức OpenAI: Responses API endpoint là gì?",
        state={"routing_metadata": {"intent": "web_search"}},
        tool_call_events=events[:1],
    ) is True
    assert _should_use_search_template_for_empty_response(
        query="Không dùng web, chỉ nhắc lại trong phiên.",
        state={"routing_metadata": {"intent": "personal"}},
        tool_call_events=events[:1],
    ) is False


def test_direct_public_thinking_dedupe_detects_identical_blocks():
    from app.engine.multi_agent.direct_public_thinking_runtime import (
        remember_direct_public_thinking_chunks,
        should_emit_direct_public_thinking_chunks,
    )

    state = {}
    opening_chunks = [
        "Cau nay can mot nhip dap cham va that hon la mot loi giai thich voi.",
        "Minh muon mo loi vua du diu de neu ban muon ke tiep thi van con cho cho nhip do di ra.",
    ]
    remember_direct_public_thinking_chunks(state, opening_chunks)

    assert should_emit_direct_public_thinking_chunks(state, list(opening_chunks)) is False


def test_direct_public_thinking_dedupe_allows_changed_blocks():
    from app.engine.multi_agent.direct_public_thinking_runtime import (
        remember_direct_public_thinking_chunks,
        should_emit_direct_public_thinking_chunks,
    )

    state = {}
    remember_direct_public_thinking_chunks(
        state,
        [
            "Cau nay can mot nhip dap cham va that hon la mot loi giai thich voi.",
            "Minh muon mo loi vua du diu de neu ban muon ke tiep thi van con cho cho nhip do di ra.",
        ],
    )

    assert should_emit_direct_public_thinking_chunks(
        state,
        [
            "Gio minh da co them du kien nen co the noi cu the hon.",
            "Minh se giu nhip diu nhung neo cau tra loi vao dieu vua kiem chung.",
        ],
    ) is True


def test_build_direct_final_synthesis_instruction_is_mode_aware_for_math_turn():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_direct_final_synthesis_instruction,
    )

    instruction = _build_direct_final_synthesis_instruction(
        "Phan tich ve toan hoc con lac don",
        {},
        [],
    ).lower()

    assert "khong goi them cong cu" in instruction
    assert "mot cau thesis ve mo hinh dang dung" in instruction
    assert "mo hinh/gia dinh -> phuong trinh hoac suy dan -> y nghia vat ly" in instruction
    assert "khong dung heading markdown nhu #, ##, ###" in instruction


@pytest.mark.asyncio
async def test_execute_direct_tool_rounds_does_not_emit_authored_public_thinking_for_tool_rounds():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    class FakeTool:
        name = "tool_demo"

        async def ainvoke(self, args):
            return f"ket qua cho {args['query']}"

    events = []

    async def push_event(event):
        events.append(event)

    async def fake_ainvoke_with_fallback(_llm, _messages, **kwargs):
        call_index = fake_ainvoke_with_fallback.calls
        fake_ainvoke_with_fallback.calls += 1
        if call_index == 0:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {"id": "call_1", "name": "tool_demo", "args": {"query": "abc"}}
                ],
            )
        return SimpleNamespace(content="Day la cau tra loi cuoi.", tool_calls=[])

    fake_ainvoke_with_fallback.calls = 0

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("No-tool streaming path should not be used in this test")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(push_event, node, content, subtype):
        await push_event(
            {
                "type": "status",
                "content": content,
                "node": node,
                "subtype": subtype,
            }
        )

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, _messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeTool()],
            push_event=push_event,
            query="Tim giup minh mot du kien roi tra loi ngan gon.",
            state={},
            forced_tool_choice="tool_demo",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert llm_response.content == "Day la cau tra loi cuoi."
    assert [event["type"] for event in tool_call_events] == ["call", "result"]
    event_types = [event["type"] for event in events]
    assert "tool_call" in event_types
    assert "tool_result" in event_types
    assert "thinking_start" not in event_types
    assert "thinking_delta" not in event_types
    assert "action_text" not in event_types


@pytest.mark.asyncio
async def test_forced_web_search_runs_tool_without_planner_or_synthesis_llm():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    class FakeTool:
        name = "tool_web_search"

        def invoke(self, args):
            return (
                "**Introducing GPT-5.5 - OpenAI**\n"
                "Apr 23, 2026 · OpenAI is releasing GPT-5.5.\n"
                "URL: https://openai.com/index/introducing-gpt-5-5/"
            )

        async def ainvoke(self, args):
            return (
                "**Introducing GPT-5.5 - OpenAI**\n"
                "Apr 23, 2026 · OpenAI is releasing GPT-5.5.\n"
                "URL: https://openai.com/index/introducing-gpt-5-5/"
            )

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(_llm, _messages, **_kwargs):
        fake_ainvoke_with_fallback.calls += 1
        raise AssertionError("forced @web-search should not depend on planner LLM")

    fake_ainvoke_with_fallback.calls = 0

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("tool-bound turn should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, _messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeTool()],
            push_event=push_event,
            query="OpenAI latest model announcement 2026",
            state={"context": {"force_skills": ["web-search"]}},
            forced_tool_choice="tool_web_search",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert fake_ainvoke_with_fallback.calls == 0
    assert "Introducing GPT-5.5" in llm_response.content
    assert "https://openai.com/index/introducing-gpt-5-5/" in llm_response.content
    assert [event["type"] for event in tool_call_events] == ["call", "result"]
    assert tool_call_events[0]["args"]["query"] == "OpenAI latest model announcement 2026"


@pytest.mark.asyncio
async def test_uploaded_document_preview_runs_host_action_without_planner_llm():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    captured: dict[str, object] = {}

    class FakeHostPreviewTool:
        name = "host_action__authoring__preview_lesson_patch"

        def invoke(self, args):
            captured["args"] = dict(args)
            return json.dumps(
                {
                    "status": "action_requested",
                    "request_id": "host-preview-1",
                    "action": "authoring.preview_lesson_patch",
                    "params": args,
                },
                ensure_ascii=False,
            )

        async def ainvoke(self, args):
            return self.invoke(args)

    events: list[dict] = []

    async def push_event(event):
        events.append(event)

    async def fake_ainvoke_with_fallback(_llm, _messages, **_kwargs):
        raise AssertionError("uploaded document preview should not depend on planner LLM")

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("document preview should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    markdown = (
        "Sổ tay trực ca buồng lái\n"
        "Marker kiểm thử: WIII_DOC_GOAL_123\n"
        "Mục tiêu học tập 1: giải thích quy trình trực ca khi tầm nhìn hạn chế.\n"
        "Checklist nguồn trang 4: xác nhận người trực ca, kiểm tra thiết bị định vị.\n"
        "Checklist nguồn trang 5: báo thuyền trưởng, giảm tốc an toàn, ghi nhật ký.\n"
    )
    state = {
        "context": {
            "document_context": {
                "attachments": [
                    {
                        "file_name": "so-tay-truc-ca.docx",
                        "markdown": markdown,
                    }
                ]
            },
            "page_context": {"lesson_id": "lesson-from-url"},
        }
    }

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, _messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeHostPreviewTool()],
            push_event=push_event,
            query=(
                "Dua tren tai lieu Word vua upload, tao preview_lesson_patch "
                "co source_references page 4-5 va marker WIII_DOC_GOAL_123."
            ),
            state=state,
            forced_tool_choice="host_action__authoring__preview_lesson_patch",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    preview_args = captured["args"]
    assert preview_args["lesson_id"] == "lesson-from-url"
    assert preview_args["title"].startswith("Bản nháp:")
    assert "# Bản nháp bài học từ tài liệu:" in preview_args["content"]
    assert "## Mục tiêu học tập" in preview_args["content"]
    assert "## Hoạt động thảo luận" in preview_args["content"]
    assert "Marker kiểm thử: WIII_DOC_GOAL_123" in preview_args["content"]
    assert "Ban nhap" not in preview_args["content"]
    assert "Muc tieu hoc tap" not in preview_args["content"]
    assert "WIII_DOC_GOAL_123" in preview_args["content"]
    assert preview_args["source_references"][0]["page_start"] == 4
    assert preview_args["source_references"][0]["page_end"] == 5
    assert [event["type"] for event in tool_call_events] == ["call", "host_action", "result"]
    assert any(event.get("type") == "host_action" for event in events)
    assert "preview" in llm_response.content.lower()


@pytest.mark.asyncio
async def test_uploaded_document_course_plan_runs_host_action_without_planner_llm():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    captured: dict[str, object] = {}

    class FakeHostCourseTool:
        name = "host_action__authoring__generate_course_from_document"

        def invoke(self, args):
            captured["args"] = dict(args)
            return json.dumps(
                {
                    "status": "action_requested",
                    "request_id": "host-course-1",
                    "action": "authoring.generate_course_from_document",
                    "params": args,
                },
                ensure_ascii=False,
            )

        async def ainvoke(self, args):
            return self.invoke(args)

    events: list[dict] = []

    async def push_event(event):
        events.append(event)

    async def fake_ainvoke_with_fallback(_llm, _messages, **_kwargs):
        raise AssertionError("uploaded document course plan should not depend on planner LLM")

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("document course plan should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    markdown = (
        "# Hướng Dẫn Sử Dụng HoLiLiHu LMS\n"
        "Nguồn section: 1. Tổng Quan (trang 1-2)\n"
        "# 3. Hướng Dẫn Cho Học Viên\n"
        "Nguồn section: 3. Hướng Dẫn Cho Học Viên (trang 12-20)\n"
        "# 4. Hướng Dẫn Cho Giảng Viên\n"
        "Nguồn section: 4. Hướng Dẫn Cho Giảng Viên (trang 21-34)\n"
        "## 4.2. Tạo khóa học mới\n"
        "Nguồn section: 4.2. Tạo khóa học mới (trang 23-25)\n"
        "## 4.5. Thêm video, tài liệu và quiz\n"
        "Nguồn section: 4.5. Thêm video, tài liệu và quiz (trang 29-31)\n"
        "# 5. Hướng Dẫn Cho Quản Lý\n"
        "Nguồn section: 5. Hướng Dẫn Cho Quản Lý (trang 35-42)\n"
    )
    state = {
        "context": {
            "document_context": {
                "attachments": [
                    {
                        "file_name": "Huong_dan_su_dung_HoLiLiHu_LMS.docx",
                        "markdown": markdown,
                    }
                ]
            },
            "page_context": {"course_id": "course-from-url"},
        }
    }

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, _messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeHostCourseTool()],
            push_event=push_event,
            query="Dựa trên tài liệu Word vừa upload, hãy tạo toàn bộ khóa học theo chương/bài có citation.",
            state=state,
            forced_tool_choice="host_action__authoring__generate_course_from_document",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    course_args = captured["args"]
    course_plan = course_args["course_plan"]
    assert course_args["course_id"] == "course-from-url"
    assert course_args["action"] == "preview_course_plan_from_document"
    assert course_plan["title"] == "Khai thác HoLiLiHu LMS từ tài liệu hướng dẫn"
    assert len(course_plan["chapters"]) == 5
    assert sum(len(chapter["lessons"]) for chapter in course_plan["chapters"]) >= 15
    assert "Tác nghiệp giảng viên" in course_plan["chapters"][2]["title"]
    assert "source_references" in course_plan["chapters"][2]["lessons"][0]
    assert any(ref.get("page_start") == 23 for ref in course_args["source_references"])
    assert [event["type"] for event in tool_call_events] == ["call", "host_action", "result"]
    assert any(event.get("type") == "host_action" for event in events)
    assert "khóa học" in llm_response.content.lower()


def test_uploaded_doc_course_plan_builder_creates_full_lms_architecture():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_course_params,
    )

    markdown = (
        "# Hướng Dẫn Sử Dụng HoLiLiHu LMS\n"
        "Nguồn section: 1. Tổng Quan (trang 1-2)\n"
        "# 3. Hướng Dẫn Cho Học Viên\n"
        "Nguồn section: 3. Hướng Dẫn Cho Học Viên (trang 12-20)\n"
        "# 4. Hướng Dẫn Cho Giảng Viên\n"
        "Nguồn section: 4. Hướng Dẫn Cho Giảng Viên (trang 21-34)\n"
        "## 4.2. Tạo khóa học mới\n"
        "Nguồn section: 4.2. Tạo khóa học mới (trang 23-25)\n"
        "## 4.5. Thêm video, tài liệu và quiz\n"
        "Nguồn section: 4.5. Thêm video, tài liệu và quiz (trang 29-31)\n"
        "# 5. Hướng Dẫn Cho Quản Lý\n"
        "Nguồn section: 5. Hướng Dẫn Cho Quản Lý (trang 35-42)\n"
    )
    params = _build_uploaded_doc_course_params(
        "Tạo khóa học đầy đủ từ tài liệu Word này, chia chương/bài có source_references.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "Huong_dan_su_dung_HoLiLiHu_LMS.docx",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-1"},
            }
        },
    )

    plan = params["course_plan"]
    assert params["course_id"] == "course-1"
    assert params["changed_fields"] == ["course_structure"]
    assert params["summary"].endswith("tài liệu upload.")
    assert "trích dẫn" not in params["summary"]
    assert "LMS" not in params["summary"]
    assert len(plan["chapters"]) == 5
    titles = [chapter["title"] for chapter in plan["chapters"]]
    assert any("Hành trình học viên" in title for title in titles)
    assert any("Tác nghiệp giảng viên" in title for title in titles)
    assert any("Quản lý" in title for title in titles)
    assert plan["chapters"][2]["lessons"][0]["source_references"][0]["page_start"] == 23
    assert f"{sum(len(chapter['lessons']) for chapter in plan['chapters'])} bài" in plan["duration"]
    assert "không publish tự động" in " ".join(plan["implementation_checklist"])


def test_uploaded_doc_course_plan_builder_keeps_maritime_research_out_of_lms_manual():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_course_params,
        _normalize_doc_preview_text,
    )

    markdown = (
        "# NGHIEN CUU XAY DUNG HE THONG QUAN LY VAN HANH VA HO SO TAU THUY\n"
        "Nguon section: GIOI THIEU (trang 1-4)\n"
        "# GIOI THIEU\n"
        "Gioi thieu bai toan xay dung he thong quan ly van hanh va ho so tau thuy.\n"
        "Nguon section: Gioi thieu bai toan xay dung he thong quan ly van hanh va ho so tau thuy (trang 5-8)\n"
        "# KHAO SAT BAI TOAN VAN HANH VA HO SO TAU THUY\n"
        "Nguon section: Khao sat bai toan van hanh va ho so tau thuy (trang 9-20)\n"
        "## Nghiep vu quan ly van hanh va ho so tau thuy\n"
        "Nguon section: Nghiep vu quan ly van hanh va ho so tau thuy (trang 18-28)\n"
        "# PHAN TICH VA THIET KE HE THONG\n"
        "Nguon section: Phan tich va thiet ke he thong (trang 29-40)\n"
        "## Phan tich chuc nang cua he thong tau\n"
        "Nguon section: Phan tich chuc nang cua he thong tau (trang 41-50)\n"
        "## So do luong du lieu muc ngu canh\n"
        "Nguon section: So do luong du lieu muc ngu canh (trang 51-60)\n"
        "## Thiet ke co so du lieu tau\n"
        "Nguon section: Thiet ke co so du lieu tau (trang 61-80)\n"
        "## Cac bang du lieu\n"
        "Nguon section: Cac bang du lieu (trang 81-95)\n"
        "## Phan tich chuc nang cua he thong bo\n"
        "Nguon section: Phan tich chuc nang cua he thong bo (trang 96-110)\n"
        "# KET LUAN VA HUONG PHAT TRIEN\n"
        "Nguon section: Ket luan va huong phat trien (trang 111-120)\n"
    )
    params = _build_uploaded_doc_course_params(
        (
            "Lap chuong trinh dao tao cho giao vien tu tai lieu Word nay. "
            "Khong bien thanh huong dan HoLiLiHu LMS; hay bam vao van hanh, "
            "ho so tau thuy va doanh nghiep van tai bien."
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "40 - GV.25-26.01.31 - Nghien cuu he thong quan ly van hanh va ho so tau thuy.docx",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-vessel"},
            }
        },
    )

    plan = params["course_plan"]
    normalized_plan = _normalize_doc_preview_text(json.dumps(plan, ensure_ascii=False))
    assert params["course_id"] == "course-vessel"
    assert len(plan["chapters"]) == 6
    assert sum(len(chapter["lessons"]) for chapter in plan["chapters"]) == 18
    assert "holilihu" not in normalized_plan
    assert "dang nhap" not in normalized_plan
    assert "video tuong tac" not in normalized_plan
    assert "ho so tau" in normalized_plan
    assert "van tai bien" in normalized_plan
    assert "co so du lieu" in normalized_plan or "du lieu" in normalized_plan
    assert all(
        lesson.get("source_references")
        for chapter in plan["chapters"]
        for lesson in chapter["lessons"]
    )


def test_uploaded_doc_course_plan_builder_keeps_maritime_lms_research_out_of_holilihu_manual():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_course_params,
        _normalize_doc_preview_text,
    )

    markdown = (
        "CONG TRINH\n\n"
        "**NGHIEN CUU XAY DUNG HE THONG LMS NANG CAO NGHIEP VU CHUYEN MON CHO CAC THUY THU**\n"
        "# GIOI THIEU\n"
        "Tai lieu phan tich nhu cau boi duong nghiep vu chuyen mon cho thuy thu bang he thong LMS.\n"
        "Nguon section: Gioi thieu nhu cau dao tao thuy thu (trang 1-5)\n"
        "# CO SO LY LUAN VA THUC TIEN\n"
        "Trinh bay co so e-learning, quan ly hoc tap va dac thu dao tao hang hai.\n"
        "Nguon section: Co so ly luan va thuc tien (trang 6-18)\n"
        "# PHAN TICH VA THIET KE HE THONG LMS\n"
        "Mo ta cac chuc nang quan ly khoa hoc, nguoi hoc, bai giang va danh gia nang luc.\n"
        "Nguon section: Phan tich va thiet ke he thong LMS (trang 19-36)\n"
        "# THU NGHIEM VA DANH GIA\n"
        "Danh gia kha nang ung dung he thong trong dao tao nghiep vu chuyen mon cho thuy thu.\n"
        "Nguon section: Thu nghiem va danh gia (trang 37-48)\n"
    )

    params = _build_uploaded_doc_course_params(
        "Tao bai giang di.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "SV25-26.43_KH-KT.docx",
                            "title": "tmpg98c_ocp",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-maritime-lms"},
            }
        },
    )

    plan = params["course_plan"]
    normalized_plan = _normalize_doc_preview_text(json.dumps(plan, ensure_ascii=False))
    assert params["course_id"] == "course-maritime-lms"
    assert plan["document_domain"]["id"] != "holilihu_lms_manual"
    assert "holilihu" not in normalized_plan
    assert "khai thac holilihu lms" not in normalized_plan
    assert "nghien cuu xay dung he thong lms" in _normalize_doc_preview_text(
        plan["source_document_title"]
    )
    assert "nghiep vu" in normalized_plan
    assert "thuy thu" in normalized_plan


def test_generic_uploaded_doc_course_clusters_full_long_document_map():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_course_params,
        _normalize_doc_preview_text,
    )

    sections = []
    for index in range(1, 25):
        sections.append(
            "\n".join(
                [
                    f"# Section {index}: Operational capability {index}",
                    f"This section explains capability {index}, constraints, evidence, and practical decisions.",
                    f"Nguon section: Section {index}: Operational capability {index} (trang {index}-{index})",
                ]
            )
        )
    markdown = "# Complex operations handbook\n" + "\n\n".join(sections)

    params = _build_uploaded_doc_course_params(
        "Turn this uploaded handbook into a complete course plan with citations.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "complex-operations-handbook.docx",
                            "title": "Complex operations handbook",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"course_id": "course-generic"},
            }
        },
    )

    plan = params["course_plan"]
    normalized_plan = _normalize_doc_preview_text(json.dumps(plan, ensure_ascii=False))

    assert params["course_id"] == "course-generic"
    assert plan["document_domain"]["id"] == "generic_document_course"
    assert len(plan["chapters"]) == 6
    assert sum(len(chapter["lessons"]) for chapter in plan["chapters"]) == 18
    assert plan["document_map_summary"]["strategy"] == "cluster_full_document_map"
    assert plan["document_map_summary"]["candidate_section_count"] >= 24
    assert params["quality_report"]["status"] == "pass"
    assert params["quality_report"]["source_reference_count"] >= 24
    assert "section 24" in normalized_plan
    assert "section 1" in normalized_plan
    assert all(
        lesson.get("source_references")
        for chapter in plan["chapters"]
        for lesson in chapter["lessons"]
    )


def test_uploaded_doc_course_parses_unicode_vietnamese_source_lines():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_course_params,
    )

    markdown = (
        "# Báo cáo vận hành\n"
        "Nguồn section: Tổng quan vận hành (trang 7-9)\n"
        "# Quy trình kiểm tra\n"
        "Nguồn section: Quy trình kiểm tra (trang 12)\n"
        "# Đánh giá sau triển khai\n"
        "Nguồn section: Đánh giá sau triển khai (trang 18-20)\n"
    )

    params = _build_uploaded_doc_course_params(
        "Tạo khóa học từ báo cáo này với citation.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "bao-cao-van-hanh.docx",
                            "title": "Báo cáo vận hành",
                            "markdown": markdown,
                        }
                    ]
                },
            }
        },
    )

    assert params["quality_report"]["source_reference_count"] == 3
    assert params["source_references"][0]["page_start"] == 7
    assert params["source_references"][0]["page_end"] == 9


def test_uploaded_doc_course_request_matches_real_teacher_curriculum_wording():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _looks_uploaded_doc_course_request,
    )

    assert _looks_uploaded_doc_course_request("Tạo bài giảng đi.")
    assert _looks_uploaded_doc_course_request("Soạn giáo án từ tài liệu vừa upload.")
    assert _looks_uploaded_doc_course_request(
        "Tu file Word vua upload, lap chuong trinh dao tao hoan chinh, "
        "de cuong khoa, lo trinh hoc va chia thanh chuong/bai co citation."
    )
    assert _looks_uploaded_doc_course_request(
        "Hay bien tai lieu nay thanh curriculum/syllabus gom nhieu chuong "
        "va nhieu bai hoc cho giao vien."
    )


def test_uploaded_doc_preview_skips_logo_data_uri_and_focuses_teacher_manual():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    markdown = (
        "![Logo Trường Đại học Hàng hải Việt Nam](data:image/png;base64...)\n\n"
        "**HƯỚNG DẪN SỬ DỤNG\n"
        "HOLILIHU ONLINE LMS**\n\n"
        "| **Vai trò** | **Nên đọc trước** | **Mục tiêu sau khi đọc** |\n"
        "| --- | --- | --- |\n"
        "| **Giảng viên** | Phần 4 và 5 | Biết tạo khóa, soạn nội dung và xuất bản. |\n\n"
        "# 4. Hướng Dẫn Cho Giảng Viên\n"
        "Mục tiêu học tập: giảng viên biết tạo khóa học, soạn bài học và kiểm tra trước khi xuất bản.\n"
        "Quy trình thao tác: mở trang quản lý khóa học, cập nhật bài học, thêm tài liệu và kiểm tra quiz.\n"
        "Checklist triển khai: xác nhận tiêu đề, nội dung, tài liệu đính kèm, trạng thái xuất bản và quyền truy cập học viên.\n"
    )
    params = _build_uploaded_doc_preview_params(
        (
            'Dựa trên tài liệu Word, tạo preview cho giáo viên. '
            'Trong preview gửi source_references title là "Hướng dẫn sử dụng HoLiLiHu LMS". '
            'Marker WIII_DOC_GOAL_REAL_MANUAL.'
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "Huong_dan_su_dung_HoLiLiHu_LMS_Chi_tiet_2026-05-10.docx",
                            "markdown": markdown,
                        }
                    ]
                },
                "page_context": {"lesson_id": "lesson-manual"},
            }
        },
    )

    content = params["content"]
    assert params["title"] == "Bản nháp: Hướng dẫn sử dụng HoLiLiHu LMS"
    assert params["lesson_id"] == "lesson-manual"
    assert params["source_references"][0]["title"] == "Hướng dẫn sử dụng HoLiLiHu LMS"
    assert "Logo Trường Đại học Hàng hải" not in params["title"]
    assert "data:image" not in content
    assert "| **Vai trò**" not in content
    assert "## Checklist thao tác / nội dung cần nắm" in content
    assert "giảng viên biết tạo khóa học" in content
    assert "trực ca" not in content.lower()
    assert "WIII_DOC_GOAL_REAL_MANUAL" in content


def test_uploaded_doc_preview_preserves_general_wiii_marker_from_query():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    marker = "WIII_PRODUCT_E2E_20260512024500"
    params = _build_uploaded_doc_preview_params(
        (
            "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload. "
            f"Noi dung bai hoc moi phai chua marker kiem thu chinh xac: {marker}."
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Muc tieu hoc tap: giao vien tao khoa hoc va kiem tra noi dung.\n"
                                "Quy trinh thao tac: mo khoa hoc, cap nhat bai hoc, kiem tra quiz.\n"
                            ),
                        }
                    ]
                },
                "page_context": {"lesson_id": "lesson-e2e"},
            }
        },
    )

    assert params["lesson_id"] == "lesson-e2e"
    assert marker in params["content"]


def test_uploaded_doc_preview_preserves_labelled_non_wiii_marker_from_query():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    marker = "COURSE_PATCH_MARKER_42"
    params = _build_uploaded_doc_preview_params(
        (
            "Create a safe LMS preview from the uploaded document. "
            f"Exact marker: {marker}."
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Bridge resource management guide\n"
                                "Learning objective: verify the checklist before saving.\n"
                                "Checklist: title, lesson content, source references, preview approval.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    assert marker in params["content"]


def test_uploaded_doc_preview_prefers_explicit_query_title_over_parser_metadata():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        (
            'Tao preview_lesson_patch cho giao vien. '
            'Trong preview gui source_references title la "Huong dan su dung HoLiLiHu LMS".'
        ),
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "title": "Parser provenance",
                            "markdown": (
                                "Parser provenance\n"
                                "Muc tieu hoc tap: giao vien cap nhat bai hoc trong LMS.\n"
                                "Checklist: kiem tra tieu de, noi dung va nguon truoc khi luu.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    assert params["title"] == "Bản nháp: Hướng dẫn sử dụng HoLiLiHu LMS"
    assert params["source_references"][0]["title"] == "Hướng dẫn sử dụng HoLiLiHu LMS"
    assert "# Bản nháp bài học từ tài liệu: Hướng dẫn sử dụng HoLiLiHu LMS" in params["content"]
    assert "Parser provenance" not in params["title"]


def test_uploaded_doc_preview_prefers_real_teacher_heading_over_smart_excerpt_outline():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    markdown = (
        "# Tai lieu upload: manual.docx\n\n"
        "## Muc luc phat hien\n"
        "- 3. Huong Dan Cho Hoc Vien\n"
        "- 4. Huong Dan Cho Giang Vien\n"
        "- 4.2. Tao khoa hoc moi\n\n"
        "## Trich doan dau tai lieu\n"
        "Vai tro: Hoc vien, Giang vien, Quan ly.\n\n"
        "## Trich doan uu tien theo vai tro/chu de\n"
        "### 4. Huong Dan Cho Giang Vien\n"
        "# 4. Huong Dan Cho Giang Vien\n"
        "Phan nay tap trung vao tac vu tao va van hanh khoa hoc.\n\n"
        "## 4.2. Tao khoa hoc moi\n"
        "**Giang vien**\n\n"
        "| **Muc tieu** | Nhap thong tin khoa theo cach du dung cho duyet va cho hoc vien hieu. |\n"
        "| --- | --- |\n"
        "| **Buoc** | **Thao tac** | **Ket qua dung** |\n"
        "| **1** | Bam Tao khoa hoc. | Form co cac nhom thong tin tach ro. |\n"
        "| **2** | Nhap tieu de ro rang. | Truong bat buoc bao loi neu thieu. |\n"
        "Checklist trien khai: tieu de, noi dung, video tuong tac, cau hoi va trang thai xuat ban.\n"
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien voi source_references tu tai lieu LMS nay.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": markdown,
                        }
                    ]
                }
            }
        },
    )

    content = params["content"]
    assert "Tai lieu upload" not in content
    assert "Muc luc phat hien" not in content
    assert "- 4. Huong Dan Cho Giang Vien" not in content
    assert "Nhap thong tin khoa" in content
    assert "Checklist trien khai" in content
    assert "HoLiLiHu LMS" in params["description"]
    assert "OOW" not in params["description"]


def test_doc_preview_clean_line_drops_checkbox_table_markers():
    from app.engine.multi_agent.direct_tool_rounds_runtime import _clean_doc_preview_line

    assert _clean_doc_preview_line(
        "| **□** | Thong tin khoa hoan chinh. | Co tieu de va muc tieu hoc tap. |"
    ) == "Thong tin khoa hoan chinh. - Co tieu de va muc tieu hoc tap."


def test_uploaded_doc_preview_filters_bare_table_labels_from_goals():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "| **Muc tieu** |\n"
                                "| **Muc tieu hoc tap** |\n"
                                "| **Buoc** | **Thao tac** | **Ket qua dung** |\n"
                                "Muc tieu hoc tap: giao vien cap nhat bai hoc va kiem tra nguon truoc khi luu.\n"
                                "Checklist: xac nhan tieu de, noi dung, nguon va trang thai xuat ban.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    content = params["content"]
    assert "- Muc tieu\n" not in content
    assert "- Muc tieu hoc tap\n" not in content
    assert "- Buoc" not in content
    assert "- Thao tac" not in content
    assert "giao vien cap nhat bai hoc" in content
    assert "xac nhan tieu de" in content


def test_uploaded_doc_preview_keeps_ordered_actions_out_of_learning_goals():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Muc tieu hoc tap: giao vien hieu cach chuan bi bai hoc truoc khi luu.\n"
                                "| **Buoc** | **Thao tac** | **Ket qua dung** |\n"
                                "| **3** | Them anh dai dien va nhap muc tieu bai hoc khi soan bai. |"
                                "Noi dung duoc hien thi dung cho hoc vien. |\n"
                                "Checklist: xac nhan source references va preview approval.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    content = params["content"]
    objectives_section = content.split("## Checklist", 1)[0]
    checklist_section = content.split("## Checklist", 1)[1]
    assert "giao vien hieu cach chuan bi bai hoc" in objectives_section
    assert "Them anh dai dien" not in objectives_section
    assert "- 3 - Them anh" not in content
    assert "Them anh dai dien va nhap muc tieu bai hoc" in checklist_section


def test_uploaded_doc_preview_excludes_admonitions_from_learning_goals():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Khong nen dan van ban qua dai mot doan. "
                                "Chia thanh muc tieu, doi tuong, yeu cau dau vao.\n"
                                "Luu y: giao vien kiem tra citation truoc khi luu.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    content = params["content"]
    objectives_section = content.split("## Checklist", 1)[0]
    assert "Khong nen dan van ban qua dai" not in objectives_section
    assert "Luu y: giao vien kiem tra citation" not in objectives_section
    assert "Giáo viên xác định đúng thao tác cần làm trong LMS" in objectives_section


def test_uploaded_doc_preview_shapes_descriptive_excerpt_into_learning_goal():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Phan nay tap trung vao tac vu tao va van hanh khoa hoc: "
                                "lap khoa, soan noi dung, tao cau hoi va cau hinh video.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    objectives_section = params["content"].split("## Checklist", 1)[0]
    assert "Phan nay tap trung vao" not in objectives_section
    assert (
        "Giáo viên thực hiện được tac vu tao va van hanh khoa hoc"
        in objectives_section
    )


def test_uploaded_doc_preview_repairs_truncated_publish_word_in_learning_goal():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Phan nay tap trung vao tac vu tao va van hanh khoa hoc: "
                                "lap khoa, soan noi dung, tao cau hoi, cau hinh video, "
                                "kiem tra roi xuat ba\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    objectives_section = params["content"].split("## Checklist", 1)[0]
    assert "xuat ba trong LMS" not in objectives_section
    assert "xuất bản trong LMS" in objectives_section


def test_uploaded_doc_preview_supplements_sparse_lms_learning_goals():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _build_uploaded_doc_preview_params,
    )

    params = _build_uploaded_doc_preview_params(
        "Tao preview_lesson_patch cho giao vien tu tai lieu vua upload.",
        {
            "context": {
                "document_context": {
                    "attachments": [
                        {
                            "file_name": "manual.docx",
                            "markdown": (
                                "Huong dan su dung HoLiLiHu LMS\n"
                                "Muc tieu hoc tap: giao vien tao khoa hoc dung quy trinh.\n"
                            ),
                        }
                    ]
                }
            }
        },
    )

    objectives_section = params["content"].split("## Checklist", 1)[0]
    objective_lines = [
        line for line in objectives_section.splitlines() if line.startswith("- ")
    ]
    assert len(objective_lines) >= 3
    assert "giao vien tao khoa hoc dung quy trinh" in objectives_section
    assert "phần so sánh thay đổi và nguồn trích dẫn" in objectives_section
    assert "diff, citation" not in objectives_section
    assert "bấm Apply" not in objectives_section
    assert "trạng thái nháp" in objectives_section


@pytest.mark.asyncio
async def test_execute_direct_tool_rounds_forwards_runtime_tier_to_failover_helper():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    class FakeTool:
        name = "tool_demo"

        async def ainvoke(self, args):
            return f"ket qua cho {args['query']}"

    captured: dict[str, object] = {}

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(_llm, _messages, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content="final", tool_calls=[])

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("tool-bound turn should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    llm = SimpleNamespace(_wiii_tier_key="deep", _wiii_provider_name="google")

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        await execute_direct_tool_rounds_impl(
            llm_with_tools=llm,
            llm_auto=llm,
            messages=[],
            tools=[FakeTool()],
            push_event=push_event,
            query="Hay giai thich spectral theorem va self-adjoint operator",
            state={},
            llm_base=llm,
            forced_tool_choice="tool_demo",
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert captured["tier"] == "deep"


@pytest.mark.asyncio
async def test_execute_direct_tool_rounds_can_use_native_tool_messages():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )
    from app.engine.native_chat_runtime import NativeToolMessage, NativeUserMessage

    class FakeTool:
        name = "tool_demo"

        def invoke(self, args):
            return f"ket qua cho {args['query']}"

    captured_messages: list[list[object]] = []

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(_llm, messages, **_kwargs):
        captured_messages.append(list(messages))
        call_index = fake_ainvoke_with_fallback.calls
        fake_ainvoke_with_fallback.calls += 1
        if call_index == 0:
            return SimpleNamespace(
                content="",
                tool_calls=[
                    {"id": "call_1", "name": "tool_demo", "args": {"query": "abc"}}
                ],
            )
        if call_index == 1:
            return SimpleNamespace(content="", tool_calls=[])
        return SimpleNamespace(content="Day la cau tra loi cuoi.", tool_calls=[])

    fake_ainvoke_with_fallback.calls = 0

    async def fake_stream_direct_answer_with_fallback(*args, **kwargs):
        raise AssertionError("tool-bound turn should not use no-tool streaming path")

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    with patch(
        "app.engine.multi_agent.graph._ainvoke_with_fallback",
        new=fake_ainvoke_with_fallback,
    ), patch(
        "app.engine.multi_agent.graph._stream_direct_wait_heartbeats",
        new=fake_stream_direct_wait_heartbeats,
    ):
        llm_response, messages, tool_call_events = await execute_direct_tool_rounds_impl(
            llm_with_tools=object(),
            llm_auto=object(),
            messages=[],
            tools=[FakeTool()],
            push_event=push_event,
            query="Tim du kien roi tong hop lai",
            state={},
            forced_tool_choice="tool_demo",
            native_tool_messages=True,
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert llm_response.content == "Day la cau tra loi cuoi."
    assert [event["type"] for event in tool_call_events] == ["call", "result"]
    assert any(isinstance(message, NativeToolMessage) for message in captured_messages[1])
    assert isinstance(captured_messages[2][-1], NativeUserMessage)
    assert messages == captured_messages[2]


@pytest.mark.asyncio
async def test_execute_direct_tool_rounds_forwards_primary_timeout_to_stream_path():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        execute_direct_tool_rounds_impl,
    )

    captured: dict[str, object] = {}

    async def push_event(_event):
        return None

    async def fake_ainvoke_with_fallback(*args, **kwargs):
        raise AssertionError("no-tool turn should use streaming helper first")

    async def fake_stream_direct_answer_with_fallback(_llm, _messages, _push_event, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(content="xin chao", tool_calls=[]), True

    async def fake_stream_direct_wait_heartbeats(*args, **kwargs):
        stop_signal = kwargs.get("stop_signal")
        if stop_signal is not None:
            await stop_signal.wait()
            return
        await asyncio.Future()

    async def push_status_only_progress(*args, **kwargs):
        return None

    llm = SimpleNamespace(_wiii_tier_key="deep", _wiii_provider_name="zhipu")

    with patch(
        "app.engine.multi_agent.graph._stream_direct_answer_with_fallback",
        new=fake_stream_direct_answer_with_fallback,
    ):
        await execute_direct_tool_rounds_impl(
            llm_with_tools=llm,
            llm_auto=llm,
            messages=[],
            tools=[],
            push_event=push_event,
            query="Wiii duoc sinh ra nhu the nao?",
            state={},
            llm_base=llm,
            direct_answer_timeout_profile="structured",
            direct_answer_primary_timeout=6.0,
            ainvoke_with_fallback=fake_ainvoke_with_fallback,
            stream_direct_answer_with_fallback=fake_stream_direct_answer_with_fallback,
            stream_direct_wait_heartbeats=fake_stream_direct_wait_heartbeats,
            push_status_only_progress=push_status_only_progress,
        )

    assert captured["primary_timeout"] == pytest.approx(6.0)
    assert captured["timeout_profile"] == "structured"


# ─────────────────────────────────────────────────────────────────────────
# Wiii Pointy v3.0 — server-side selector validator (anti-hallucination).
# ─────────────────────────────────────────────────────────────────────────


def _state_with_targets(*ids: str) -> SimpleNamespace:
    """Build minimal state.host_context.page.metadata.available_targets."""
    return SimpleNamespace(
        host_context={
            "page": {
                "metadata": {
                    "available_targets": [{"id": i} for i in ids],
                }
            }
        }
    )


def test_pointy_validator_accepts_bare_id_in_inventory():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button", "settings-link")
    assert _validate_pointy_selector("chat-send-button", state) is None


def test_pointy_validator_accepts_auto_id_in_inventory():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("auto:button:gui-tin-nhan", "settings-link")
    assert _validate_pointy_selector("auto:button:gui-tin-nhan", state) is None


def test_pointy_validator_accepts_data_wiii_id_verbose_form():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    assert (
        _validate_pointy_selector('[data-wiii-id="chat-send-button"]', state)
        is None
    )


def test_pointy_validator_rejects_compound_css_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector(
        'button[type="submit"], .send-button, [aria-label="Gửi"], button:has(svg)',
        state,
    )
    assert err is not None
    assert "ERROR" in err
    assert "NOT a valid Wiii Pointy id" in err
    assert "chat-send-button" in err  # available ids surfaced for self-correction


def test_pointy_validator_rejects_class_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector(".send-button", state)
    assert err is not None
    assert "DO NOT generate CSS selectors" in err


def test_pointy_validator_rejects_aria_label_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector('[aria-label="Gửi"]', state)
    assert err is not None
    assert "ERROR" in err


def test_pointy_validator_rejects_pseudo_class_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector("button:has(svg)", state)
    assert err is not None


def test_pointy_validator_rejects_id_with_hash_prefix():
    """The `#chat-send-button` form is a CSS id selector, not a bare id."""
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector("#chat-send-button", state)
    assert err is not None


def test_pointy_validator_rejects_empty_selector():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button")
    err = _validate_pointy_selector("", state)
    assert err is not None
    assert "Empty selector" in err


def test_pointy_validator_rejects_unknown_bare_id_with_inventory_hint():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("chat-send-button", "settings-link")
    err = _validate_pointy_selector("nonexistent-button", state)
    assert err is not None
    assert "không có trong available_targets" in err
    assert "chat-send-button" in err


def test_pointy_validator_rejects_unknown_auto_id_with_inventory_hint():
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = _state_with_targets("auto:button:gui-tin-nhan")
    err = _validate_pointy_selector("auto:button:cai-dat", state)
    assert err is not None
    assert "available_targets" in err
    assert "auto:button:gui-tin-nhan" in err


def test_pointy_validator_passes_bare_id_when_inventory_empty():
    """Without inventory we can't verify — fall through to permissive."""
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = SimpleNamespace(host_context=None)
    assert _validate_pointy_selector("chat-send-button", state) is None


def test_pointy_validator_passes_auto_id_when_inventory_empty():
    """Without inventory, allow Wiii synthetic id syntax and let frontend resolve."""
    from app.engine.multi_agent.direct_tool_rounds_runtime import (
        _validate_pointy_selector,
    )

    state = SimpleNamespace(host_context=None)
    assert _validate_pointy_selector("auto:button:gui-tin-nhan", state) is None



def test_build_force_skill_directive_pointy_inlines_inventory():
    """v3.0 F5: when @-mention force-binds wiii-pointy, system prompt
    directive must inline the available_targets so LLM picks right id
    without round-tripping tool_pointy_inventory."""
    from app.engine.multi_agent.direct_prompts import _build_force_skill_directive

    state = {
        'context': {
            'force_skills': ['wiii-pointy'],
            'host_context': {
                'page': {
                    'metadata': {
                        'available_targets': [
                            {'id': 'chat-send-button', 'role': 'button', 'label': 'Gửi tin nhắn'},
                            {'id': 'auto:button:dinh-kem-file', 'role': 'button', 'label': 'Đính kèm file'},
                            {'id': 'settings-link', 'role': 'link', 'label': 'Cài đặt'},
                        ]
                    }
                }
            }
        }
    }
    result = _build_force_skill_directive(state)
    # Imperative phrasing — Anthropic Computer Use 2026.
    assert 'PHẢI gọi' in result
    assert 'tool_pointy_show' in result
    # Inventory inline với prescriptive directive.
    assert 'chat-send-button' in result
    assert 'Gửi tin nhắn' in result
    # Anti-hallucination — exact inventory id contract, including auto ids.
    assert 'auto:button:dinh-kem-file' in result
    assert 'Synthetic ids' in result
    assert 'KHÔNG generate CSS' in result


def test_build_force_skill_directive_empty_when_no_force_skills():
    from app.engine.multi_agent.direct_prompts import _build_force_skill_directive

    assert _build_force_skill_directive({'context': {}}) == ''
    assert _build_force_skill_directive({}) == ''


def test_build_force_skill_directive_web_search_branch():
    from app.engine.multi_agent.direct_prompts import _build_force_skill_directive

    state = {'context': {'force_skills': ['web-search']}}
    result = _build_force_skill_directive(state)
    assert 'web-search' in result.lower() or 'tool_web_search' in result
    assert 'PHẢI gọi' in result



def test_make_pointy_show_with_enum_constrains_selector():
    """v9.0 F18: enum-bound tool's selector must accept inventory ids only.

    SeeAct (ICML'24) Textual Choices grounding pattern — JSON schema
    enum constraint at OpenAI tool-call layer.
    """
    from app.engine.tools.pointy_tools import make_pointy_show_with_enum

    inventory = ["chat-send-button", "auto:button:dinh-kem-file", "domain-selector"]
    enum_tool = make_pointy_show_with_enum(inventory)
    schema = enum_tool.input_model.model_json_schema()
    selector_field = schema.get("properties", {}).get("selector", {})
    # Pydantic produces enum constraint via Literal[...].
    enum_values = selector_field.get("enum")
    assert enum_values is not None
    assert set(enum_values) == set(inventory)


def test_make_pointy_show_with_enum_empty_falls_back_to_static():
    from app.engine.tools.pointy_tools import (
        make_pointy_show_with_enum,
        tool_pointy_show,
    )

    enum_tool = make_pointy_show_with_enum([])
    # No inventory → return static unchanged.
    assert enum_tool is tool_pointy_show


def test_make_pointy_show_with_enum_caps_at_64_for_token_budget():
    from app.engine.tools.pointy_tools import make_pointy_show_with_enum

    huge_inventory = [f"item-{i:03d}" for i in range(200)]
    enum_tool = make_pointy_show_with_enum(huge_inventory)
    schema = enum_tool.input_model.model_json_schema()
    enum_values = schema["properties"]["selector"].get("enum", [])
    # Cap to 64 to avoid prompt bloat.
    assert len(enum_values) == 64
    assert enum_values[0] == "item-000"


def test_validate_pointy_target_accepts_inventory_id():
    from app.engine.tools.pointy_tools import validate_pointy_target

    inv = ["chat-send-button", "attach-file-button"]
    assert validate_pointy_target("chat-send-button", inv) is None
    err = validate_pointy_target("nonexistent", inv)
    assert err is not None
    assert "not in current inventory" in err
    err = validate_pointy_target("", inv)
    assert err is not None


def test_extract_inventory_ids_from_state_dict_form():
    from app.engine.tools.pointy_tools import extract_inventory_ids_from_state

    state = {
        "host_context": {
            "page": {
                "metadata": {
                    "available_targets": [
                        {"id": "btn-a"},
                        {"id": "btn-b"},
                        {"id": ""},  # filtered
                    ]
                }
            }
        }
    }
    ids = extract_inventory_ids_from_state(state)
    assert ids == ["btn-a", "btn-b"]


def test_extract_inventory_ids_from_state_nested_context():
    from app.engine.tools.pointy_tools import extract_inventory_ids_from_state

    # Some flows set host_context inside state["context"] not top-level.
    state = {
        "context": {
            "host_context": {
                "page": {
                    "metadata": {
                        "available_targets": [{"id": "btn-x"}]
                    }
                }
            }
        }
    }
    ids = extract_inventory_ids_from_state(state)
    assert ids == ["btn-x"]
