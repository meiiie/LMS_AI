"""Runtime helpers for course generation API endpoints."""

from __future__ import annotations

import os
import tempfile
from typing import Any, Callable, Optional
from uuid import uuid4

from fastapi import HTTPException, UploadFile

SAFE_DOC_TO_COURSE_CONTRACT = "host_action_preview_apply"
LEGACY_DIRECT_EXPAND_CONTRACT = "legacy_course_generation_expand"
LEGACY_EXPAND_CONFIRMATION_REQUIRED = {
    "code": "legacy_lms_mutation_confirmation_required",
    "message": (
        "POST /course-generation/{generation_id}/expand is a legacy direct LMS "
        "mutation path. Product LMS doc-to-course must use preview -> teacher "
        "confirm -> apply instead."
    ),
    "required_field": "legacy_lms_mutation_confirmed",
    "safe_contract": SAFE_DOC_TO_COURSE_CONTRACT,
    "issue": "meiiie/wiii#285",
}


def _source_pages(value: Any) -> list[Any]:
    if not isinstance(value, list):
        return []
    return [page for page in value if page is not None]


def build_outline_source_references(outline: Any) -> list[dict[str, Any]]:
    if not isinstance(outline, dict):
        return []

    chapters = outline.get("chapters")
    if not isinstance(chapters, list):
        return []

    references: list[dict[str, Any]] = []
    for chapter_index, chapter in enumerate(chapters):
        if not isinstance(chapter, dict):
            continue

        chapter_title = chapter.get("title")
        chapter_pages = _source_pages(chapter.get("sourcePages"))
        if chapter_pages:
            references.append(
                {
                    "kind": "chapter",
                    "chapter_index": chapter_index,
                    "title": chapter_title,
                    "source_pages": chapter_pages,
                }
            )

        lessons = chapter.get("lessons")
        if not isinstance(lessons, list):
            continue

        for lesson_index, lesson in enumerate(lessons):
            if not isinstance(lesson, dict):
                continue
            lesson_pages = _source_pages(lesson.get("sourcePages"))
            if not lesson_pages:
                continue
            references.append(
                {
                    "kind": "lesson",
                    "chapter_index": chapter_index,
                    "lesson_index": lesson_index,
                    "chapter_title": chapter_title,
                    "title": lesson.get("title"),
                    "source_pages": lesson_pages,
                }
            )
    return references


async def list_generation_jobs_impl(
    *,
    limit: int,
    teacher_id: Optional[str],
    auth,
    get_course_gen_repo_fn: Callable[[], Any],
    is_platform_admin_fn: Callable[[Any], bool],
    build_generation_job_summary_fn: Callable[[dict], Any],
):
    repo = get_course_gen_repo_fn()

    effective_teacher_id = teacher_id
    if not is_platform_admin_fn(auth):
        effective_teacher_id = auth.user_id
    elif effective_teacher_id:
        effective_teacher_id = effective_teacher_id.strip() or None

    jobs = await repo.list_jobs(
        teacher_id=effective_teacher_id,
        organization_id=None if is_platform_admin_fn(auth) else auth.organization_id,
        limit=limit,
    )
    return [build_generation_job_summary_fn(job) for job in jobs]


async def generate_outline_impl(
    *,
    file: UploadFile,
    teacher_id: str,
    teacher_prompt: str,
    language: str,
    target_chapters: Optional[int],
    auth,
    ensure_teacher_matches_auth_fn: Callable[[str, Any], None],
    ensure_docling_available_fn: Callable[[str], None],
    derive_generation_thread_id_fn: Callable[[Any], Optional[str]],
    get_course_gen_repo_fn: Callable[[], Any],
    dispatch_course_generation_task_fn: Callable[..., Any],
    run_outline_phase_fn: Callable[..., Any],
    max_file_size: int,
    allowed_extensions: set[str],
):
    ensure_teacher_matches_auth_fn(teacher_id, auth)

    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(400, f"Unsupported file type: {ext}. Supported: {allowed_extensions}")
    if ext != ".pdf":
        ensure_docling_available_fn(ext)

    content = await file.read()
    if len(content) > max_file_size:
        raise HTTPException(400, f"File too large ({len(content)} bytes). Max: {max_file_size}")

    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    generation_id = str(uuid4())
    thread_id = derive_generation_thread_id_fn(auth)

    repo = get_course_gen_repo_fn()
    await repo.create_job(
        generation_id=generation_id,
        teacher_id=teacher_id,
        file_path=tmp_path,
        language=language,
        teacher_prompt=teacher_prompt,
        target_chapters=target_chapters,
        organization_id=auth.organization_id,
        session_id=auth.session_id,
        thread_id=thread_id,
        status_message="Đã xếp hàng tạo outline khóa học",
    )

    dispatch_course_generation_task_fn(
        run_outline_phase_fn(
            generation_id,
            tmp_path,
            teacher_id,
            teacher_prompt,
            language,
            target_chapters,
        ),
        label=f"course-gen:outline:{generation_id}",
        generation_id=generation_id,
    )

    return {
        "generation_id": generation_id,
        "phase": "CONVERTING",
        "progress_percent": 0,
        "thread_id": thread_id,
    }


async def expand_chapters_impl(
    *,
    generation_id: str,
    req,
    auth,
    get_course_gen_repo_fn: Callable[[], Any],
    require_generation_job_access_fn: Callable[[dict, Any], None],
    ensure_teacher_matches_auth_fn: Callable[[str, Any], None],
    normalize_approved_chapters_fn: Callable[[list[int], int], list[int]],
    dispatch_course_generation_task_fn: Callable[..., Any],
    run_expand_phase_fn: Callable[..., Any],
):
    repo = get_course_gen_repo_fn()
    job = await repo.get_job(generation_id)
    if not job:
        raise HTTPException(404, "Generation job not found")
    require_generation_job_access_fn(job, auth)
    if job["phase"] != "OUTLINE_READY":
        raise HTTPException(400, f"Cannot expand: phase is '{job['phase']}', expected 'OUTLINE_READY'")
    ensure_teacher_matches_auth_fn(req.teacher_id, auth)
    if not req.legacy_lms_mutation_confirmed:
        raise HTTPException(
            409,
            {
                **LEGACY_EXPAND_CONFIRMATION_REQUIRED,
                "generation_id": generation_id,
            },
        )

    outline = job.get("outline") or {}
    chapters = outline.get("chapters") or []
    approved_chapters = normalize_approved_chapters_fn(req.approved_chapters, len(chapters))
    req = req.model_copy(update={"approved_chapters": approved_chapters})

    await repo.update_phase(
        generation_id,
        "EXPANDING",
        expand_request=req.model_dump(),
        progress_percent=max(job.get("progress_percent", 40), 45),
        status_message="Đã xếp hàng mở rộng nội dung khóa học",
        error=None,
        cancel_requested=False,
        cancelled_at=None,
        completed_at=None,
    )

    dispatch_course_generation_task_fn(
        run_expand_phase_fn(generation_id, req),
        label=f"course-gen:expand:{generation_id}",
        generation_id=generation_id,
    )

    return {
        "generation_id": generation_id,
        "phase": "EXPANDING",
        "progress_percent": max(job.get("progress_percent", 40), 45),
        "mutation_contract": LEGACY_DIRECT_EXPAND_CONTRACT,
        "safe_product_contract": SAFE_DOC_TO_COURSE_CONTRACT,
    }


async def retry_failed_chapter_impl(
    *,
    generation_id: str,
    chapter_index: int,
    auth,
    get_course_gen_repo_fn: Callable[[], Any],
    require_generation_job_access_fn: Callable[[dict, Any], None],
    dispatch_course_generation_task_fn: Callable[..., Any],
    run_retry_chapter_fn: Callable[..., Any],
):
    repo = get_course_gen_repo_fn()
    job = await repo.get_job(generation_id)
    if not job:
        raise HTTPException(404, "Generation job not found")
    require_generation_job_access_fn(job, auth)

    if job["phase"] not in ("COMPLETED", "EXPANDING"):
        raise HTTPException(400, f"Cannot retry: phase is '{job['phase']}'")

    failed_ch = None
    for ch in job.get("failed_chapters", []):
        if ch.get("index") == chapter_index:
            failed_ch = ch
            break

    if not failed_ch:
        raise HTTPException(404, f"Chapter {chapter_index} not found in failed list")

    dispatch_course_generation_task_fn(
        run_retry_chapter_fn(generation_id, chapter_index),
        label=f"course-gen:retry:{generation_id}:{chapter_index}",
        generation_id=generation_id,
    )

    return {
        "generation_id": generation_id,
        "chapter_index": chapter_index,
        "retry_type": "PUSH_RETRY" if failed_ch.get("content_cache") else "FULL_RETRY",
    }


async def cancel_generation_job_impl(
    *,
    generation_id: str,
    auth,
    get_course_gen_repo_fn: Callable[[], Any],
    require_generation_job_access_fn: Callable[[dict, Any], None],
    cancel_active_generation_tasks_fn: Callable[[str], int],
    utcnow_fn: Callable[[], Any],
    terminal_generation_phases: set[str],
):
    repo = get_course_gen_repo_fn()
    job = await repo.get_job(generation_id)
    if not job:
        raise HTTPException(404, "Generation job not found")
    require_generation_job_access_fn(job, auth)

    phase = job.get("phase", "")
    if phase in terminal_generation_phases:
        return {
            "generation_id": generation_id,
            "phase": phase,
            "cancel_requested": job.get("cancel_requested", False),
        }

    if phase == "OUTLINE_READY":
        await repo.update_phase(
            generation_id,
            "CANCELLED",
            cancel_requested=True,
            cancelled_at=utcnow_fn(),
            completed_at=None,
            status_message="Đã hủy tác vụ tạo khóa học",
        )
    else:
        await repo.request_cancel(
            generation_id,
            status_message="Đã ghi nhận yêu cầu hủy, đang dừng tác vụ nền",
        )
        cancel_active_generation_tasks_fn(generation_id)

    latest = await repo.get_job(generation_id) or job
    return {
        "generation_id": generation_id,
        "phase": latest.get("phase"),
        "cancel_requested": latest.get("cancel_requested", False),
        "status_message": latest.get("status_message"),
    }


async def resume_generation_job_impl(
    *,
    generation_id: str,
    auth,
    expand_request_cls,
    get_course_gen_repo_fn: Callable[[], Any],
    require_generation_job_access_fn: Callable[[dict, Any], None],
    dispatch_course_generation_task_fn: Callable[..., Any],
    run_outline_phase_fn: Callable[..., Any],
    run_expand_phase_fn: Callable[..., Any],
    active_generation_phases: set[str],
):
    repo = get_course_gen_repo_fn()
    job = await repo.get_job(generation_id)
    if not job:
        raise HTTPException(404, "Generation job not found")
    require_generation_job_access_fn(job, auth)

    if job.get("phase") in active_generation_phases:
        raise HTTPException(400, "Generation job is already running")

    if job.get("phase") == "OUTLINE_READY":
        raise HTTPException(400, "Outline is already ready. Use /expand to continue.")

    await repo.clear_cancel_request(generation_id)

    outline = job.get("outline")
    file_path = job.get("file_path")
    expand_request = job.get("expand_request")

    if not outline:
        if not file_path or not os.path.exists(file_path):
            raise HTTPException(400, "Cannot resume outline: source document is no longer available")
        await repo.update_phase(
            generation_id,
            "CONVERTING",
            progress_percent=min(job.get("progress_percent", 0), 10),
            status_message="Đã xếp hàng tiếp tục tạo outline",
            error=None,
            cancelled_at=None,
            completed_at=None,
        )
        dispatch_course_generation_task_fn(
            run_outline_phase_fn(
                generation_id,
                file_path,
                job["teacher_id"],
                job.get("teacher_prompt", ""),
                job.get("language", "vi"),
                job.get("target_chapters"),
            ),
            label=f"course-gen:resume:outline:{generation_id}",
            generation_id=generation_id,
        )
        return {"generation_id": generation_id, "phase": "CONVERTING"}

    if not expand_request:
        await repo.update_phase(
            generation_id,
            "OUTLINE_READY",
            progress_percent=max(job.get("progress_percent", 0), 40),
            status_message="Outline đã sẵn sàng để duyệt lại",
            error=None,
            cancelled_at=None,
            completed_at=None,
        )
        return {
            "generation_id": generation_id,
            "phase": "OUTLINE_READY",
            "progress_percent": max(job.get("progress_percent", 0), 40),
        }

    req = expand_request_cls(**expand_request)
    await repo.update_phase(
        generation_id,
        "EXPANDING",
        expand_request=req.model_dump(),
        progress_percent=max(job.get("progress_percent", 40), 45),
        status_message="Đã xếp hàng tiếp tục mở rộng khóa học",
        error=None,
        cancelled_at=None,
        completed_at=None,
    )
    dispatch_course_generation_task_fn(
        run_expand_phase_fn(generation_id, req),
        label=f"course-gen:resume:expand:{generation_id}",
        generation_id=generation_id,
    )
    return {
        "generation_id": generation_id,
        "phase": "EXPANDING",
        "progress_percent": max(job.get("progress_percent", 40), 45),
    }


async def get_generation_status_impl(
    *,
    generation_id: str,
    auth,
    generation_status_response_cls,
    get_course_gen_repo_fn: Callable[[], Any],
    require_generation_job_access_fn: Callable[[dict, Any], None],
):
    repo = get_course_gen_repo_fn()
    job = await repo.get_job(generation_id)
    if not job:
        raise HTTPException(404, "Generation job not found")
    require_generation_job_access_fn(job, auth)

    return generation_status_response_cls(
        generation_id=job["id"],
        phase=job["phase"],
        outline=job.get("outline"),
        source_references=build_outline_source_references(job.get("outline")),
        course_id=job.get("course_id"),
        completed_chapters=job.get("completed_chapters", []),
        failed_chapters=job.get("failed_chapters", []),
        progress_percent=job.get("progress_percent", 0),
        status_message=job.get("status_message"),
        cancel_requested=job.get("cancel_requested", False),
        session_id=job.get("session_id"),
        thread_id=job.get("thread_id"),
        created_at=job.get("created_at"),
        updated_at=job.get("updated_at"),
        heartbeat_at=job.get("heartbeat_at"),
        started_at=job.get("started_at"),
        completed_at=job.get("completed_at"),
        cancelled_at=job.get("cancelled_at"),
        error=job.get("error"),
    )
