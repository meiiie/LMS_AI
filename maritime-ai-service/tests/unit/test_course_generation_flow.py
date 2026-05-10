import asyncio

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from unittest.mock import MagicMock

from app.api.v1.course_generation import (
    ExpandRequest,
    _generation_heartbeat_loop,
    cancel_generation_job,
    _ensure_teacher_matches_auth,
    _normalize_approved_chapters,
    _require_generation_job_access,
    list_generation_jobs,
    recover_course_generation_jobs,
    resume_generation_job,
    _run_expand_phase,
    _run_outline_phase,
    _run_retry_chapter,
)
from app.api.v1.course_generation_endpoint_runtime import (
    expand_chapters_impl,
    get_generation_status_impl,
)
from app.api.v1.course_generation_schemas import GenerationStatusResponse
from app.models.course_generation import ChapterContentSchema, CourseOutlineSchema
from app.engine.context.adapters.lms import LMSHostAdapter
from app.engine.context.host_context import from_legacy_page_context
from app.core.security import AuthenticatedUser


class _FakeRepo:
    def __init__(self, jobs):
        self._jobs = list(jobs)
        self._source_jobs = [dict(job) for job in jobs]
        self._job_map = {
            job.get("id", f"job-{idx}"): dict(job)
            for idx, job in enumerate(jobs)
            if isinstance(job, dict)
        }
        self.phase_updates = []
        self.chapter_updates = []
        self.claimed_phases = None
        self.progress_updates = []
        self.cancel_requests = []
        self.clear_cancel_requests = []
        self.list_calls = []

    async def update_phase(self, generation_id, phase, **kwargs):
        self.phase_updates.append((generation_id, phase, kwargs))
        current = self._job_map.setdefault(generation_id, {"id": generation_id})
        current["phase"] = phase
        current.update(kwargs)

    async def update_chapters(self, generation_id, completed_chapters, failed_chapters):
        self.chapter_updates.append(
            (
                generation_id,
                list(completed_chapters),
                list(failed_chapters),
            )
        )
        current = self._job_map.setdefault(generation_id, {"id": generation_id})
        current["completed_chapters"] = list(completed_chapters)
        current["failed_chapters"] = list(failed_chapters)

    async def update_progress(self, generation_id, progress_percent, **kwargs):
        self.progress_updates.append((generation_id, progress_percent, kwargs))
        current = self._job_map.setdefault(generation_id, {"id": generation_id})
        current["progress_percent"] = progress_percent
        if "status_message" in kwargs and kwargs["status_message"] is not None:
            current["status_message"] = kwargs["status_message"]
        if "heartbeat_at" in kwargs and kwargs["heartbeat_at"] is not None:
            current["heartbeat_at"] = kwargs["heartbeat_at"]

    async def get_job(self, generation_id):
        if len(self._jobs) > 1:
            job = self._jobs.pop(0)
            self._job_map[generation_id] = dict(job)
            return job
        if self._jobs:
            job = self._jobs[0]
            self._job_map[generation_id] = dict(job)
            return job
        return self._job_map.get(generation_id)

    async def list_jobs(self, *, teacher_id=None, organization_id=None, limit=20):
        self.list_calls.append(
            {
                "teacher_id": teacher_id,
                "organization_id": organization_id,
                "limit": limit,
            }
        )
        jobs = list(self._source_jobs)
        if teacher_id:
            jobs = [job for job in jobs if job.get("teacher_id") == teacher_id]
        if organization_id:
            jobs = [job for job in jobs if job.get("organization_id") == organization_id]
        return jobs[:limit]

    async def request_cancel(self, generation_id, **kwargs):
        self.cancel_requests.append((generation_id, kwargs))
        current = self._job_map.setdefault(generation_id, {"id": generation_id})
        current["cancel_requested"] = True
        current.update(kwargs)

    async def clear_cancel_request(self, generation_id):
        self.clear_cancel_requests.append(generation_id)
        current = self._job_map.setdefault(generation_id, {"id": generation_id})
        current["cancel_requested"] = False

    async def claim_jobs_for_recovery(self, phases, limit=100):
        self.claimed_phases = (list(phases), limit)
        return list(self._jobs)

    async def get_failed_chapter(self, generation_id, chapter_index):
        if len(self._jobs) > 1:
            failed = self._jobs[0].get("failed_chapters", [])
        elif self._jobs:
            failed = self._jobs[0].get("failed_chapters", [])
        else:
            failed = (self._job_map.get(generation_id) or {}).get("failed_chapters", [])
        for chapter in failed:
            if chapter.get("index") == chapter_index:
                return chapter
        return None


class _FakePushService:
    def __init__(self, shell_response=None, chapter_response=None):
        self.shell_response = shell_response or {"courseId": "course-shell-1"}
        self.chapter_response = chapter_response or {"chapterId": "chapter-1"}
        self.shell_calls = []
        self.chapter_calls = []

    async def push_course_shell_async(self, **kwargs):
        self.shell_calls.append(kwargs)
        return self.shell_response

    async def push_chapter_content_async(self, course_id, payload):
        self.chapter_calls.append((course_id, payload))
        return self.chapter_response


def test_expand_request_deduplicates_indices():
    req = ExpandRequest(
        teacher_id="teacher-1",
        category_id="category-1",
        course_title="Khoa hoc",
        approved_chapters=[0, 2, 2, 1, 0],
    )
    assert req.approved_chapters == [0, 2, 1]


def test_expand_request_rejects_negative_indices():
    with pytest.raises(ValidationError):
        ExpandRequest(
            teacher_id="teacher-1",
            category_id="category-1",
            course_title="Khoa hoc",
            approved_chapters=[0, -1],
        )


def test_normalize_approved_chapters_rejects_out_of_range():
    with pytest.raises(HTTPException) as exc:
        _normalize_approved_chapters([0, 3], 3)
    assert exc.value.status_code == 400
    assert "invalid index 3" in exc.value.detail


def test_ensure_teacher_matches_auth_rejects_mismatch():
    auth = AuthenticatedUser(user_id="teacher-2", auth_method="jwt", role="teacher")
    with pytest.raises(HTTPException) as exc:
        _ensure_teacher_matches_auth("teacher-1", auth)
    assert exc.value.status_code == 403


def test_require_generation_job_access_rejects_cross_org_teacher():
    auth = AuthenticatedUser(
        user_id="teacher-1",
        auth_method="jwt",
        role="teacher",
        organization_id="org-b",
    )
    with pytest.raises(HTTPException) as exc:
        _require_generation_job_access(
            {"teacher_id": "teacher-1", "organization_id": "org-a"},
            auth,
        )
    assert exc.value.status_code == 403


def test_require_generation_job_access_allows_admin_bypass():
    auth = AuthenticatedUser(user_id="admin-1", auth_method="jwt", role="admin")
    _require_generation_job_access(
        {"teacher_id": "teacher-1", "organization_id": "org-a"},
        auth,
    )


@pytest.mark.asyncio
async def test_expand_chapters_impl_requires_legacy_mutation_confirmation():
    repo = _FakeRepo([
        {
            "id": "gen-1",
            "teacher_id": "teacher-1",
            "organization_id": "org-a",
            "phase": "OUTLINE_READY",
            "outline": {"chapters": [{"title": "Chuong 1", "sourcePages": [1]}]},
            "progress_percent": 40,
        }
    ])
    auth = AuthenticatedUser(
        user_id="teacher-1",
        auth_method="jwt",
        role="teacher",
        organization_id="org-a",
    )
    req = ExpandRequest(
        teacher_id="teacher-1",
        category_id="category-1",
        course_title="Khoa hoc",
        approved_chapters=[0],
    )

    with pytest.raises(HTTPException) as exc:
        await expand_chapters_impl(
            generation_id="gen-1",
            req=req,
            auth=auth,
            get_course_gen_repo_fn=lambda: repo,
            require_generation_job_access_fn=_require_generation_job_access,
            ensure_teacher_matches_auth_fn=_ensure_teacher_matches_auth,
            normalize_approved_chapters_fn=_normalize_approved_chapters,
            dispatch_course_generation_task_fn=lambda *args, **kwargs: None,
            run_expand_phase_fn=lambda *args, **kwargs: None,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "legacy_lms_mutation_confirmation_required"
    assert exc.value.detail["required_field"] == "legacy_lms_mutation_confirmed"
    assert repo.phase_updates == []


@pytest.mark.asyncio
async def test_expand_chapters_impl_allows_explicit_legacy_mutation_confirmation():
    repo = _FakeRepo([
        {
            "id": "gen-1",
            "teacher_id": "teacher-1",
            "organization_id": "org-a",
            "phase": "OUTLINE_READY",
            "outline": {"chapters": [{"title": "Chuong 1", "sourcePages": [1]}]},
            "progress_percent": 40,
        }
    ])
    auth = AuthenticatedUser(
        user_id="teacher-1",
        auth_method="jwt",
        role="teacher",
        organization_id="org-a",
    )
    req = ExpandRequest(
        teacher_id="teacher-1",
        category_id="category-1",
        course_title="Khoa hoc",
        approved_chapters=[0],
        legacy_lms_mutation_confirmed=True,
    )
    dispatched: list[tuple[str, str]] = []

    async def fake_run_expand(generation_id, expand_request):
        return None

    def fake_dispatch(coro, *, label, generation_id):
        dispatched.append((label, generation_id))
        coro.close()

    result = await expand_chapters_impl(
        generation_id="gen-1",
        req=req,
        auth=auth,
        get_course_gen_repo_fn=lambda: repo,
        require_generation_job_access_fn=_require_generation_job_access,
        ensure_teacher_matches_auth_fn=_ensure_teacher_matches_auth,
        normalize_approved_chapters_fn=_normalize_approved_chapters,
        dispatch_course_generation_task_fn=fake_dispatch,
        run_expand_phase_fn=fake_run_expand,
    )

    assert result["phase"] == "EXPANDING"
    assert result["mutation_contract"] == "legacy_course_generation_expand"
    assert result["safe_product_contract"] == "host_action_preview_apply"
    assert repo.phase_updates[-1][2]["expand_request"]["legacy_lms_mutation_confirmed"] is True
    assert dispatched == [("course-gen:expand:gen-1", "gen-1")]


@pytest.mark.asyncio
async def test_get_generation_status_includes_outline_source_references():
    repo = _FakeRepo([
        {
            "id": "gen-1",
            "teacher_id": "teacher-1",
            "organization_id": "org-a",
            "phase": "OUTLINE_READY",
            "outline": {
                "chapters": [
                    {
                        "title": "Chuong 1",
                        "sourcePages": [1, 2],
                        "lessons": [
                            {"title": "Bai 1", "sourcePages": [3]},
                            {"title": "Bai 2"},
                        ],
                    }
                ]
            },
        }
    ])
    auth = AuthenticatedUser(
        user_id="teacher-1",
        auth_method="jwt",
        role="teacher",
        organization_id="org-a",
    )

    result = await get_generation_status_impl(
        generation_id="gen-1",
        auth=auth,
        generation_status_response_cls=GenerationStatusResponse,
        get_course_gen_repo_fn=lambda: repo,
        require_generation_job_access_fn=_require_generation_job_access,
    )

    assert result.source_references == [
        {
            "kind": "chapter",
            "chapter_index": 0,
            "title": "Chuong 1",
            "source_pages": [1, 2],
        },
        {
            "kind": "lesson",
            "chapter_index": 0,
            "lesson_index": 0,
            "chapter_title": "Chuong 1",
            "title": "Bai 1",
            "source_pages": [3],
        },
    ]


@pytest.mark.asyncio
async def test_list_generation_jobs_returns_summary_for_authenticated_teacher(monkeypatch):
    import app.api.v1.course_generation as course_gen_api

    repo = _FakeRepo([
        {
            "id": "gen-1",
            "teacher_id": "teacher-1",
            "organization_id": "org-a",
            "phase": "EXPANDING",
            "progress_percent": 72,
            "status_message": "Dang xu ly",
            "completed_chapters": [{"index": 0}, {"index": 1}],
            "failed_chapters": [{"index": 2}],
            "thread_id": "user_teacher-1__session_s-1",
            "session_id": "s-1",
        },
        {
            "id": "gen-2",
            "teacher_id": "teacher-2",
            "organization_id": "org-a",
            "phase": "FAILED",
        },
    ])
    auth = AuthenticatedUser(
        user_id="teacher-1",
        auth_method="jwt",
        role="teacher",
        organization_id="org-a",
    )

    monkeypatch.setattr(course_gen_api, "get_course_gen_repo", lambda: repo)

    result = await list_generation_jobs(limit=10, teacher_id=None, auth=auth)

    assert len(result) == 1
    assert result[0].generation_id == "gen-1"
    assert result[0].completed_chapter_count == 2
    assert result[0].failed_chapter_count == 1
    assert repo.list_calls == [
        {"teacher_id": "teacher-1", "organization_id": "org-a", "limit": 10}
    ]


@pytest.mark.asyncio
async def test_cancel_generation_job_requests_cancel_for_running_job(monkeypatch):
    import app.api.v1.course_generation as course_gen_api

    repo = _FakeRepo([
        {
            "id": "gen-1",
            "teacher_id": "teacher-1",
            "organization_id": "org-a",
            "phase": "EXPANDING",
            "cancel_requested": False,
        }
    ])
    auth = AuthenticatedUser(
        user_id="teacher-1",
        auth_method="jwt",
        role="teacher",
        organization_id="org-a",
    )
    cancelled: list[str] = []

    monkeypatch.setattr(course_gen_api, "get_course_gen_repo", lambda: repo)
    monkeypatch.setattr(course_gen_api, "_cancel_active_generation_tasks", lambda generation_id: cancelled.append(generation_id) or 1)

    result = await cancel_generation_job("gen-1", auth=auth)

    assert result["generation_id"] == "gen-1"
    assert repo.cancel_requests == [
        ("gen-1", {"status_message": "Đã ghi nhận yêu cầu hủy, đang dừng tác vụ nền"})
    ]
    assert cancelled == ["gen-1"]


@pytest.mark.asyncio
async def test_resume_generation_job_restores_outline_ready_without_expand_snapshot(monkeypatch):
    import app.api.v1.course_generation as course_gen_api

    repo = _FakeRepo([
        {
            "id": "gen-1",
            "teacher_id": "teacher-1",
            "organization_id": "org-a",
            "phase": "CANCELLED",
            "outline": {"chapters": [{"orderIndex": 0}]},
            "expand_request": None,
            "progress_percent": 40,
            "cancel_requested": True,
        }
    ])
    auth = AuthenticatedUser(
        user_id="teacher-1",
        auth_method="jwt",
        role="teacher",
        organization_id="org-a",
    )

    monkeypatch.setattr(course_gen_api, "get_course_gen_repo", lambda: repo)

    result = await resume_generation_job("gen-1", auth=auth)

    assert result == {"generation_id": "gen-1", "phase": "OUTLINE_READY", "progress_percent": 40}
    assert repo.clear_cancel_requests == ["gen-1"]
    assert repo.phase_updates[-1][1] == "OUTLINE_READY"


@pytest.mark.asyncio
async def test_run_expand_phase_resumes_only_pending_chapters(monkeypatch):
    import app.api.v1.course_generation as course_gen_api
    import app.engine.workflows.course_generation as workflow_module
    import app.integrations.lms.push_service as push_service_module

    repo = _FakeRepo(
        [
            {
                "id": "gen-1",
                "outline": {
                    "chapters": [
                        {"orderIndex": 0, "title": "Chuong 1"},
                        {"orderIndex": 1, "title": "Chuong 2"},
                        {"orderIndex": 2, "title": "Chuong 3"},
                    ]
                },
                "markdown": "# md",
                "section_map": {},
                "completed_chapters": [{"index": 0, "chapterId": "chapter-0", "status": "COMPLETED"}],
                "failed_chapters": [{"index": 1, "error": "old", "phase": "EXPAND_FAILED", "content_cache": None}],
                "cancel_requested": False,
            }
        ]
    )
    push_service = _FakePushService(shell_response={"courseId": "course-123"})
    called_indices: list[int] = []

    async def fake_expand_single_chapter(state):
        idx = state["current_chapter_idx"]
        called_indices.append(idx)
        return {
            "completed_chapters": [
                {"index": idx, "chapterId": f"chapter-{idx}", "status": "COMPLETED"}
            ],
            "failed_chapters": [],
        }

    monkeypatch.setattr(course_gen_api, "get_course_gen_repo", lambda: repo)
    monkeypatch.setattr(push_service_module, "get_push_service", lambda: push_service)
    monkeypatch.setattr(workflow_module, "compute_execution_waves", lambda approved, deps: [approved])
    monkeypatch.setattr(workflow_module, "expand_single_chapter", fake_expand_single_chapter)

    req = ExpandRequest(
        teacher_id="teacher-1",
        course_id="course-123",
        category_id="category-1",
        course_title="Khoa hoc",
        approved_chapters=[0, 1, 2],
    )

    await _run_expand_phase("gen-1", req)

    assert called_indices == [1, 2]
    _, completed, failed = repo.chapter_updates[-1]
    assert completed == [
        {"index": 0, "chapterId": "chapter-0", "status": "COMPLETED"},
        {"index": 1, "chapterId": "chapter-1", "status": "COMPLETED"},
        {"index": 2, "chapterId": "chapter-2", "status": "COMPLETED"},
    ]
    assert failed == []


def test_from_legacy_page_context_preserves_action_and_extra_metadata():
    ctx = from_legacy_page_context(
        {
            "page_type": "course_editor",
            "page_title": "Editor",
            "course_id": "course-123",
            "action": "generate_lesson",
            "custom_flag": "keep-me",
        }
    )
    assert ctx.page["metadata"]["action"] == "generate_lesson"
    assert ctx.page["metadata"]["custom_flag"] == "keep-me"


def test_lms_adapter_includes_requested_action_instruction():
    adapter = LMSHostAdapter()
    ctx = from_legacy_page_context(
        {
            "page_type": "course_editor",
            "page_title": "Course editor",
            "course_id": "course-123",
            "action": "generate_lesson",
        }
    )
    prompt = adapter.format_context_for_prompt(ctx)
    assert "<requested_action>generate_lesson</requested_action>" in prompt
    assert "tạo bài giảng" in prompt.lower()


@pytest.mark.asyncio
async def test_run_expand_phase_records_partial_failures(monkeypatch):
    import app.api.v1.course_generation as course_gen_api
    import app.engine.workflows.course_generation as workflow_module
    import app.integrations.lms.push_service as push_service_module

    repo = _FakeRepo(
        [
            {
                "outline": {
                    "chapters": [
                        {"orderIndex": 0, "title": "Chuong 1"},
                        {"orderIndex": 1, "title": "Chuong 2"},
                    ]
                },
                "markdown": "# md",
                "section_map": {},
            }
        ]
    )
    push_service = _FakePushService()

    async def fake_expand_single_chapter(state):
        idx = state["current_chapter_idx"]
        if idx == 0:
            return {
                "completed_chapters": [
                    {"index": 0, "chapterId": "chapter-0", "status": "COMPLETED"}
                ],
                "failed_chapters": [],
            }
        return {
            "completed_chapters": [],
            "failed_chapters": [
                {
                    "index": 1,
                    "error": "LLM invalid JSON",
                    "phase": "EXPAND_FAILED",
                    "content_cache": None,
                }
            ],
        }

    monkeypatch.setattr(course_gen_api, "get_course_gen_repo", lambda: repo)
    monkeypatch.setattr(push_service_module, "get_push_service", lambda: push_service)
    monkeypatch.setattr(workflow_module, "compute_execution_waves", lambda approved, deps: [[0, 1]])
    monkeypatch.setattr(workflow_module, "expand_single_chapter", fake_expand_single_chapter)

    req = ExpandRequest(
        teacher_id="teacher-1",
        course_id="course-123",
        category_id="category-1",
        course_title="Khoa hoc",
        approved_chapters=[0, 1],
    )

    await _run_expand_phase("gen-1", req)

    assert repo.chapter_updates
    _, completed, failed = repo.chapter_updates[-1]
    assert completed == [{"index": 0, "chapterId": "chapter-0", "status": "COMPLETED"}]
    assert failed == [
        {
            "index": 1,
            "error": "LLM invalid JSON",
            "phase": "EXPAND_FAILED",
            "content_cache": None,
        }
    ]
    assert repo.phase_updates[-1][0] == "gen-1"
    assert repo.phase_updates[-1][1] == "COMPLETED"
    assert repo.phase_updates[-1][2]["error"] == "1 chapter(s) failed during expansion"
    assert repo.phase_updates[-1][2]["expand_request"] == req.model_dump()
    assert repo.phase_updates[-1][2]["progress_percent"] == 100


@pytest.mark.asyncio
async def test_run_retry_chapter_merges_latest_repo_state(monkeypatch):
    import app.api.v1.course_generation as course_gen_api
    import app.integrations.lms.push_service as push_service_module

    initial_job = {
        "course_id": "course-123",
        "teacher_id": "teacher-1",
        "language": "vi",
        "outline": {"chapters": [{"title": "A"}, {"title": "B"}, {"title": "C"}]},
        "completed_chapters": [{"index": 0, "chapterId": "chapter-0", "status": "COMPLETED"}],
        "failed_chapters": [{"index": 1, "content_cache": {"title": "cached"}, "phase": "PUSH_FAILED"}],
    }
    latest_job = {
        "course_id": "course-123",
        "teacher_id": "teacher-1",
        "language": "vi",
        "outline": {"chapters": [{"title": "A"}, {"title": "B"}, {"title": "C"}]},
        "completed_chapters": [
            {"index": 0, "chapterId": "chapter-0", "status": "COMPLETED"},
            {"index": 2, "chapterId": "chapter-2", "status": "COMPLETED"},
        ],
        "failed_chapters": [{"index": 1, "content_cache": {"title": "cached"}, "phase": "PUSH_FAILED"}],
    }
    repo = _FakeRepo([initial_job, latest_job])
    push_service = _FakePushService(chapter_response={"chapterId": "chapter-1"})

    monkeypatch.setattr(course_gen_api, "get_course_gen_repo", lambda: repo)
    monkeypatch.setattr(push_service_module, "get_push_service", lambda: push_service)

    await _run_retry_chapter("gen-1", 1)

    assert push_service.chapter_calls == [("course-123", {"title": "cached"})]
    assert repo.chapter_updates
    _, completed, failed = repo.chapter_updates[-1]
    assert completed == [
        {"index": 0, "chapterId": "chapter-0", "status": "COMPLETED"},
        {"index": 1, "chapterId": "chapter-1", "status": "COMPLETED"},
        {"index": 2, "chapterId": "chapter-2", "status": "COMPLETED"},
    ]
    assert failed == []


@pytest.mark.asyncio
async def test_recover_course_generation_jobs_marks_missing_outline_file_failed(monkeypatch):
    import app.api.v1.course_generation as course_gen_api

    repo = _FakeRepo([
        {
            "id": "gen-missing",
            "phase": "RECOVERING_OUTLINE",
            "teacher_id": "teacher-1",
            "language": "vi",
            "teacher_prompt": "",
            "target_chapters": None,
            "file_path": "Z:\\does-not-exist.pdf",
        }
    ])
    dispatched: list[str] = []

    def fake_dispatch(coro, *, label, generation_id):
        dispatched.append(label)
        coro.close()
        return None

    monkeypatch.setattr(course_gen_api, "get_course_gen_repo", lambda: repo)
    monkeypatch.setattr(course_gen_api, "_dispatch_course_generation_task", fake_dispatch)

    recovered = await recover_course_generation_jobs(limit=10)

    assert recovered == 0
    assert dispatched == []
    assert repo.claimed_phases == ([*course_gen_api.RECOVERABLE_PHASES], 10)
    assert repo.phase_updates == [
        (
            "gen-missing",
            "FAILED",
            {"error": "Recovery failed: source document is no longer available"},
        )
    ]


@pytest.mark.asyncio
async def test_recover_course_generation_jobs_redispatches_expand_jobs(monkeypatch):
    import app.api.v1.course_generation as course_gen_api

    repo = _FakeRepo([
        {
            "id": "gen-expand",
            "phase": "RECOVERING_EXPANDING",
            "teacher_id": "teacher-1",
            "expand_request": {
                "teacher_id": "teacher-1",
                "course_id": "course-123",
                "category_id": "cat-1",
                "course_title": "Khoa hoc",
                "approved_chapters": [0, 1],
                "language": "vi",
            },
        }
    ])
    dispatched: list[str] = []

    def fake_dispatch(coro, *, label, generation_id):
        dispatched.append(label)
        coro.close()
        return None

    monkeypatch.setattr(course_gen_api, "get_course_gen_repo", lambda: repo)
    monkeypatch.setattr(course_gen_api, "_dispatch_course_generation_task", fake_dispatch)

    recovered = await recover_course_generation_jobs(limit=5)

    assert recovered == 1
    assert dispatched == ["course-gen:recover:expand:gen-expand"]


@pytest.mark.asyncio
async def test_run_outline_phase_prepares_source_before_outline(monkeypatch):
    import app.api.v1.course_generation as course_gen_api
    import app.engine.workflows.course_generation as workflow_module
    import app.engine.workflows.course_generation_source_preparation as prep_module

    repo = _FakeRepo([])
    repo._job_map["gen-1"] = {"id": "gen-1", "phase": "CONVERTING", "cancel_requested": False}
    captured_state: dict[str, object] = {}

    async def fake_convert_node(state, *, parser):
        return {
            **state,
            "markdown": "<!-- page 1 -->\n# Chuong 1\nNoi dung dai " * 80,
            "section_map": {},
        }

    async def fake_outline_node(state):
        captured_state.update(state)
        return {
            **state,
            "outline": {
                "title": "Khoa hoc",
                "description": "Mo ta",
                "chapters": [
                    {"title": "Chuong 1", "description": "Mo ta", "orderIndex": 0, "lessons": [], "sourcePages": [1]}
                ],
            },
            "phase": "OUTLINE_READY",
        }

    class _Prepared:
        mode = "chunk_compact"
        rendered_markdown = "[PREPARED_DOCUMENT_MAP]\n## 1. Chuong 1 (pages 1-1)\nTom tat"
        candidate_providers = ("google", "zhipu")
        original_tokens_estimate = 2000
        prepared_tokens_estimate = 300
        token_budget = 700

        def to_metadata(self):
            return {"mode": self.mode, "token_budget": self.token_budget}

    monkeypatch.setattr(course_gen_api, "get_course_gen_repo", lambda: repo)
    monkeypatch.setattr(course_gen_api, "_get_parser", lambda file_path: object())
    monkeypatch.setattr(course_gen_api, "_cleanup_outline_source_file", lambda file_path: None)
    monkeypatch.setattr(workflow_module, "convert_node", fake_convert_node)
    monkeypatch.setattr(workflow_module, "outline_node", fake_outline_node)
    monkeypatch.setattr(prep_module, "prepare_outline_source", lambda **kwargs: _Prepared())

    await _run_outline_phase(
        "gen-1",
        "C:/tmp/demo.pdf",
        "teacher-1",
        "",
        "vi",
        None,
    )

    assert captured_state["outline_source_mode"] == "chunk_compact"
    assert captured_state["outline_source_markdown"] == _Prepared.rendered_markdown
    assert repo.progress_updates[0][1] == 18
    assert repo.phase_updates[-1][1] == "OUTLINE_READY"


@pytest.mark.asyncio
async def test_outline_node_uses_background_timeout_profile(monkeypatch):
    import app.engine.workflows.course_generation as workflow_module
    import app.services.structured_invoke_service as structured_module

    captured: dict[str, str | None] = {}

    async def fake_ainvoke(**kwargs):
        captured["timeout_profile"] = kwargs.get("timeout_profile")
        return CourseOutlineSchema(
            title="Khoa hoc",
            description="Mo ta",
            chapters=[
                {
                    "title": "Chuong 1",
                    "description": "Mo ta",
                    "orderIndex": 0,
                    "lessons": [{"title": "Bai 1", "description": "Mo ta", "orderIndex": 0}],
                    "sourcePages": [1],
                }
            ],
        )

    monkeypatch.setattr(workflow_module, "get_llm_deep", lambda: MagicMock())
    monkeypatch.setattr(structured_module.StructuredInvokeService, "ainvoke", fake_ainvoke)

    result = await workflow_module.outline_node(
        {
            "generation_id": "gen-1",
            "markdown": "# Noi dung",
            "language": "vi",
            "teacher_prompt": "",
        }
    )

    assert captured["timeout_profile"] == "background"
    assert result["phase"] == "OUTLINE_READY"


@pytest.mark.asyncio
async def test_outline_node_prefers_prepared_source(monkeypatch):
    import app.engine.workflows.course_generation as workflow_module
    import app.services.structured_invoke_service as structured_module

    captured: dict[str, str] = {}

    async def fake_ainvoke(**kwargs):
        payload = kwargs["payload"]
        captured["prompt"] = payload[0]["content"]
        return CourseOutlineSchema(
            title="Khoa hoc",
            description="Mo ta",
            chapters=[
                {
                    "title": "Chuong 1",
                    "description": "Mo ta",
                    "orderIndex": 0,
                    "lessons": [{"title": "Bai 1", "sourcePages": [1]}],
                    "sourcePages": [1],
                }
            ],
        )

    monkeypatch.setattr(workflow_module, "get_llm_deep", lambda: MagicMock())
    monkeypatch.setattr(structured_module.StructuredInvokeService, "ainvoke", fake_ainvoke)

    await workflow_module.outline_node(
        {
            "generation_id": "gen-1",
            "markdown": "# RAW\nNoi dung rat dai",
            "outline_source_markdown": "[PREPARED_DOCUMENT_MAP]\n- 1. Chuong 1 | pages 1-2",
            "outline_source_mode": "heading_index",
            "language": "vi",
            "teacher_prompt": "",
        }
    )

    assert "[PREPARED_DOCUMENT_MAP]" in captured["prompt"]
    assert "# RAW" not in captured["prompt"]


@pytest.mark.asyncio
async def test_generation_heartbeat_loop_updates_active_job():
    repo = _FakeRepo([])
    repo._job_map["gen-1"] = {
        "id": "gen-1",
        "phase": "CONVERTING",
        "cancel_requested": False,
        "progress_percent": 25,
    }

    task = asyncio.create_task(
        _generation_heartbeat_loop(
            repo,
            "gen-1",
            progress_percent=25,
            status_message="Dang tao outline",
            interval_seconds=0.01,
        )
    )

    await asyncio.sleep(0.035)
    repo._job_map["gen-1"]["phase"] = "FAILED"
    await task

    assert repo.progress_updates
    assert repo.progress_updates[0][0] == "gen-1"
    assert repo.progress_updates[0][1] == 25


@pytest.mark.asyncio
async def test_expand_single_chapter_uses_background_timeout_profile(monkeypatch):
    import app.engine.workflows.course_generation as workflow_module
    import app.integrations.lms.push_service as push_service_module
    import app.services.structured_invoke_service as structured_module

    captured: dict[str, str | None] = {}
    push_service = _FakePushService(chapter_response={"chapterId": "chapter-42"})

    async def fake_ainvoke(**kwargs):
        captured["timeout_profile"] = kwargs.get("timeout_profile")
        return ChapterContentSchema(
            title="Chuong 1",
            description="Mo ta",
            orderIndex=0,
            lessons=[
                {
                    "title": "Bai 1",
                    "description": "Mo ta",
                    "orderIndex": 0,
                    "sections": [
                        {
                            "title": "Muc 1",
                            "type": "TEXT",
                            "content": "<p>Hello</p>",
                            "orderIndex": 0,
                        }
                    ],
                }
            ],
        )

    monkeypatch.setattr(workflow_module, "get_llm_light", lambda: MagicMock())
    monkeypatch.setattr(push_service_module, "get_push_service", lambda: push_service)
    monkeypatch.setattr(structured_module.StructuredInvokeService, "ainvoke", fake_ainvoke)

    result = await workflow_module.expand_single_chapter(
        {
            "generation_id": "gen-1",
            "markdown": "# Chuong 1\nNoi dung",
            "section_map": {},
            "language": "vi",
            "teacher_id": "teacher-1",
            "course_id": "course-1",
            "current_chapter_idx": 0,
            "current_chapter": {
                "title": "Chuong 1",
                "orderIndex": 0,
                "sourcePages": [1],
            },
        }
    )

    assert captured["timeout_profile"] == "background"
    assert result["completed_chapters"] == [
        {"index": 0, "chapterId": "chapter-42", "status": "COMPLETED"}
    ]
