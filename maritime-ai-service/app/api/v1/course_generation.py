"""
Course Generation API Endpoints.

Provides endpoints for teachers to generate LMS courses from uploaded documents.
Job state persisted in PostgreSQL (crash-recoverable).

Feature: ai-course-generation
Design spec v2.0 (2026-03-22), expert-reviewed.

Endpoints:
  POST /course-generation/outline          — upload doc, generate outline
  POST /course-generation/{id}/expand      — legacy direct LMS expansion
  POST /course-generation/{id}/retry/{idx} — retry a failed chapter
  GET  /course-generation/{id}             — poll job status
"""

import asyncio
import logging
from datetime import datetime
from typing import Awaitable, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from app.api.v1.course_generation_parsers import (
    BasicPdfParser,
    ensure_docling_available as _ensure_docling_available_impl,
    get_parser as _get_parser_impl,
    try_build_docling_parser as _try_build_docling_parser_impl,
)
from app.api.v1.course_generation_endpoint_runtime import (
    cancel_generation_job_impl,
    expand_chapters_impl,
    generate_outline_impl,
    get_generation_status_impl,
    list_generation_jobs_impl,
    resume_generation_job_impl,
    retry_failed_chapter_impl,
)
from app.api.v1.course_generation_runtime import (
    build_outline_status_message as _build_outline_status_message_impl,
    cancel_active_generation_tasks as _cancel_active_generation_tasks_impl,
    dispatch_course_generation_task as _dispatch_course_generation_task_impl,
    generation_heartbeat_loop as _generation_heartbeat_loop_impl,
    heartbeat_interval_seconds as _heartbeat_interval_seconds_impl,
    raise_if_generation_cancelled as _raise_if_generation_cancelled_impl,
    recover_course_generation_jobs_impl,
    run_expand_phase_impl,
    run_outline_phase_impl,
    run_retry_chapter_impl,
    start_generation_heartbeat as _start_generation_heartbeat_impl,
    stop_generation_heartbeat as _stop_generation_heartbeat_impl,
)
from app.api.v1.course_generation_support import (
    build_partial_failure_summary_impl,
    cleanup_outline_source_file_impl,
    compute_expand_progress_impl,
    dedupe_failed_chapters_impl,
    derive_generation_thread_id_impl,
    ensure_teacher_matches_auth_impl,
    merge_completed_chapters_impl,
    normalize_approved_chapters_impl,
    require_generation_job_access_impl,
    upsert_failed_chapter_impl,
    utcnow_impl,
    without_failed_chapter_impl,
    without_failed_chapters_impl,
)
from app.api.v1.course_generation_schemas import (
    ExpandRequest,
    GenerationJobSummaryResponse,
    GenerationStatusResponse,
)
from app.core.config import settings
from app.core.security import AuthenticatedUser, is_platform_admin, require_auth
from app.repositories.course_generation_repository import get_course_gen_repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/course-generation", tags=["Course Generation"])

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx"}
RECOVERABLE_PHASES = (
    "CONVERTING",
    "EXPANDING",
    "RECOVERING_OUTLINE",
    "RECOVERING_EXPANDING",
)
_active_course_generation_tasks: set[asyncio.Task] = set()
_active_course_generation_tasks_by_job: dict[str, set[asyncio.Task]] = {}
ACTIVE_GENERATION_PHASES = {
    "CONVERTING",
    "RECOVERING_OUTLINE",
    "EXPANDING",
    "RECOVERING_EXPANDING",
}
TERMINAL_GENERATION_PHASES = {"COMPLETED", "FAILED", "CANCELLED"}


class CourseGenerationCancelledError(Exception):
    """Raised when a background generation job has been cancelled."""


# ── Response Models ──



# ── Endpoints ──

@router.get("")
async def list_generation_jobs(
    limit: int = Query(20, ge=1, le=100),
    teacher_id: Optional[str] = Query(None),
    auth: AuthenticatedUser = Depends(require_auth),
):
    """List recent generation jobs for the current teacher or admin scope."""
    return await list_generation_jobs_impl(
        limit=limit,
        teacher_id=teacher_id,
        auth=auth,
        get_course_gen_repo_fn=get_course_gen_repo,
        is_platform_admin_fn=is_platform_admin,
        build_generation_job_summary_fn=_build_generation_job_summary,
    )


@router.post("/outline")
async def generate_outline(
    file: UploadFile = File(...),
    teacher_id: str = Form(...),
    teacher_prompt: str = Form(""),
    language: str = Form("vi"),
    target_chapters: Optional[int] = Form(None),
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Upload document and generate course outline (Phase 1).

    Runs in background. Poll GET /course-generation/{id} for status.
    """
    return await generate_outline_impl(
        file=file,
        teacher_id=teacher_id,
        teacher_prompt=teacher_prompt,
        language=language,
        target_chapters=target_chapters,
        auth=auth,
        ensure_teacher_matches_auth_fn=_ensure_teacher_matches_auth,
        ensure_docling_available_fn=_ensure_docling_available,
        derive_generation_thread_id_fn=_derive_generation_thread_id,
        get_course_gen_repo_fn=get_course_gen_repo,
        dispatch_course_generation_task_fn=_dispatch_course_generation_task,
        run_outline_phase_fn=_run_outline_phase,
        max_file_size=MAX_FILE_SIZE,
        allowed_extensions=ALLOWED_EXTENSIONS,
    )


@router.post("/{generation_id}/expand")
async def expand_chapters(
    generation_id: str,
    req: ExpandRequest,
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Legacy path: expand approved chapters and push directly to LMS.

    Requires legacy_lms_mutation_confirmed=true because it creates a course
    shell in LMS if no course_id is provided, then pushes expanded chapters.
    Product LMS doc-to-course must use preview -> teacher confirm -> apply.
    """
    return await expand_chapters_impl(
        generation_id=generation_id,
        req=req,
        auth=auth,
        get_course_gen_repo_fn=get_course_gen_repo,
        require_generation_job_access_fn=_require_generation_job_access,
        ensure_teacher_matches_auth_fn=_ensure_teacher_matches_auth,
        normalize_approved_chapters_fn=_normalize_approved_chapters,
        dispatch_course_generation_task_fn=_dispatch_course_generation_task,
        run_expand_phase_fn=_run_expand_phase,
    )


@router.post("/{generation_id}/retry/{chapter_index}")
async def retry_failed_chapter(
    generation_id: str,
    chapter_index: int,
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Retry a failed chapter. Uses cached content for PUSH_FAILED, re-generates for LLM_FAILED."""
    return await retry_failed_chapter_impl(
        generation_id=generation_id,
        chapter_index=chapter_index,
        auth=auth,
        get_course_gen_repo_fn=get_course_gen_repo,
        require_generation_job_access_fn=_require_generation_job_access,
        dispatch_course_generation_task_fn=_dispatch_course_generation_task,
        run_retry_chapter_fn=_run_retry_chapter,
    )


@router.post("/{generation_id}/cancel")
async def cancel_generation_job(
    generation_id: str,
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Request cancellation for an in-flight or resumable generation job."""
    return await cancel_generation_job_impl(
        generation_id=generation_id,
        auth=auth,
        get_course_gen_repo_fn=get_course_gen_repo,
        require_generation_job_access_fn=_require_generation_job_access,
        cancel_active_generation_tasks_fn=_cancel_active_generation_tasks,
        utcnow_fn=_utcnow,
        terminal_generation_phases=TERMINAL_GENERATION_PHASES,
    )


@router.post("/{generation_id}/resume")
async def resume_generation_job(
    generation_id: str,
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Resume a previously failed or cancelled outline/expand workflow."""
    return await resume_generation_job_impl(
        generation_id=generation_id,
        auth=auth,
        expand_request_cls=ExpandRequest,
        get_course_gen_repo_fn=get_course_gen_repo,
        require_generation_job_access_fn=_require_generation_job_access,
        dispatch_course_generation_task_fn=_dispatch_course_generation_task,
        run_outline_phase_fn=_run_outline_phase,
        run_expand_phase_fn=_run_expand_phase,
        active_generation_phases=ACTIVE_GENERATION_PHASES,
    )


@router.get("/{generation_id}")
async def get_generation_status(
    generation_id: str,
    auth: AuthenticatedUser = Depends(require_auth),
):
    """Poll generation job status."""
    return await get_generation_status_impl(
        generation_id=generation_id,
        auth=auth,
        generation_status_response_cls=GenerationStatusResponse,
        get_course_gen_repo_fn=get_course_gen_repo,
        require_generation_job_access_fn=_require_generation_job_access,
    )


async def recover_course_generation_jobs(limit: int = 50) -> int:
    """Re-dispatch unfinished jobs after app restart."""
    return await recover_course_generation_jobs_impl(
        limit=limit,
        get_course_gen_repo_fn=get_course_gen_repo,
        recoverable_phases=RECOVERABLE_PHASES,
        dispatch_task_fn=_dispatch_course_generation_task,
        run_outline_phase_fn=_run_outline_phase,
        run_expand_phase_fn=_run_expand_phase,
        expand_request_cls=ExpandRequest,
        logger=logger,
    )


# ── Background Tasks ──

async def _run_outline_phase(
    generation_id: str,
    file_path: str,
    teacher_id: str,
    teacher_prompt: str,
    language: str,
    target_chapters: Optional[int],
):
    """Background: CONVERT + OUTLINE. Persists result to DB."""
    from app.engine.workflows.course_generation import convert_node, outline_node
    from app.engine.workflows.course_generation_source_preparation import (
        prepare_outline_source,
    )

    await run_outline_phase_impl(
        generation_id,
        file_path,
        teacher_id,
        teacher_prompt,
        language,
        target_chapters,
        get_course_gen_repo_fn=get_course_gen_repo,
        convert_node_fn=convert_node,
        outline_node_fn=outline_node,
        prepare_outline_source_fn=prepare_outline_source,
        get_parser_fn=_get_parser,
        raise_if_generation_cancelled_fn=_raise_if_generation_cancelled,
        build_outline_status_message_fn=_build_outline_status_message,
        start_generation_heartbeat_fn=_start_generation_heartbeat,
        stop_generation_heartbeat_fn=_stop_generation_heartbeat,
        utcnow_fn=_utcnow,
        cleanup_outline_source_file_fn=_cleanup_outline_source_file,
        logger=logger,
        cancelled_error_cls=CourseGenerationCancelledError,
    )


async def _run_expand_phase(generation_id: str, req: ExpandRequest):
    """Background: create course shell → EXPAND chapters → push to LMS."""
    from app.engine.workflows.course_generation import (
        compute_execution_waves,
        expand_single_chapter,
    )
    from app.integrations.lms.push_service import get_push_service

    await run_expand_phase_impl(
        generation_id,
        req,
        get_course_gen_repo_fn=get_course_gen_repo,
        get_push_service_fn=get_push_service,
        raise_if_generation_cancelled_fn=_raise_if_generation_cancelled,
        utcnow_fn=_utcnow,
        normalize_approved_chapters_fn=_normalize_approved_chapters,
        merge_completed_chapters_fn=_merge_completed_chapters,
        dedupe_failed_chapters_fn=_dedupe_failed_chapters,
        without_failed_chapters_fn=_without_failed_chapters,
        compute_expand_progress_fn=_compute_expand_progress,
        settings_obj=settings,
        expand_single_chapter_fn=expand_single_chapter,
        compute_execution_waves_fn=compute_execution_waves,
        start_generation_heartbeat_fn=_start_generation_heartbeat,
        stop_generation_heartbeat_fn=_stop_generation_heartbeat,
        build_partial_failure_summary_fn=_build_partial_failure_summary,
        upsert_failed_chapter_fn=_upsert_failed_chapter,
        logger=logger,
        cancelled_error_cls=CourseGenerationCancelledError,
    )


async def _run_retry_chapter(
    generation_id: str,
    chapter_index: int,
):
    """Background: retry a single failed chapter."""
    from app.engine.workflows.course_generation import expand_single_chapter
    from app.integrations.lms.push_service import get_push_service

    await run_retry_chapter_impl(
        generation_id,
        chapter_index,
        get_course_gen_repo_fn=get_course_gen_repo,
        get_push_service_fn=get_push_service,
        raise_if_generation_cancelled_fn=_raise_if_generation_cancelled,
        merge_completed_chapters_fn=_merge_completed_chapters,
        without_failed_chapter_fn=_without_failed_chapter,
        upsert_failed_chapter_fn=_upsert_failed_chapter,
        build_partial_failure_summary_fn=_build_partial_failure_summary,
        expand_single_chapter_fn=expand_single_chapter,
        utcnow_fn=_utcnow,
        logger=logger,
        cancelled_error_cls=CourseGenerationCancelledError,
    )


# ── Helpers ──

def _get_parser(file_path: str):
    return _get_parser_impl(file_path, settings_obj=settings, logger=logger)


def _dispatch_course_generation_task(
    coroutine: Awaitable[None],
    *,
    label: str,
    generation_id: str,
) -> asyncio.Task:
    return _dispatch_course_generation_task_impl(
        coroutine,
        label=label,
        generation_id=generation_id,
        active_tasks=_active_course_generation_tasks,
        active_tasks_by_job=_active_course_generation_tasks_by_job,
        logger=logger,
        cancelled_error_cls=CourseGenerationCancelledError,
    )


def _cancel_active_generation_tasks(generation_id: str) -> int:
    return _cancel_active_generation_tasks_impl(
        generation_id,
        active_tasks_by_job=_active_course_generation_tasks_by_job,
    )


def _build_outline_status_message(source_mode: str) -> str:
    return _build_outline_status_message_impl(source_mode)


def _heartbeat_interval_seconds() -> float:
    return _heartbeat_interval_seconds_impl(settings)


def _start_generation_heartbeat(
    repo,
    generation_id: str,
    *,
    progress_percent: int,
    status_message: str,
) -> asyncio.Task:
    return _start_generation_heartbeat_impl(
        repo,
        generation_id,
        progress_percent=progress_percent,
        status_message=status_message,
        interval_seconds=_heartbeat_interval_seconds(),
        generation_heartbeat_loop_fn=_generation_heartbeat_loop,
    )


async def _stop_generation_heartbeat(task: Optional[asyncio.Task]) -> None:
    await _stop_generation_heartbeat_impl(task)


async def _generation_heartbeat_loop(
    repo,
    generation_id: str,
    *,
    progress_percent: int,
    status_message: str,
    interval_seconds: float,
) -> None:
    await _generation_heartbeat_loop_impl(
        repo,
        generation_id,
        progress_percent=progress_percent,
        status_message=status_message,
        interval_seconds=interval_seconds,
        terminal_generation_phases=TERMINAL_GENERATION_PHASES,
        utcnow_fn=_utcnow,
    )


async def _raise_if_generation_cancelled(repo, generation_id: str) -> None:
    await _raise_if_generation_cancelled_impl(
        repo,
        generation_id,
        cancelled_error_cls=CourseGenerationCancelledError,
    )


def _utcnow() -> datetime:
    return utcnow_impl()


def _derive_generation_thread_id(auth: AuthenticatedUser) -> Optional[str]:
    return derive_generation_thread_id_impl(auth)


def _compute_expand_progress(total_target: int, completed_count: int) -> int:
    return compute_expand_progress_impl(total_target, completed_count)


def _without_failed_chapters(chapters: list[dict], chapter_indices: list[int]) -> list[dict]:
    return without_failed_chapters_impl(chapters, chapter_indices)


def _cleanup_outline_source_file(file_path: str) -> None:
    cleanup_outline_source_file_impl(file_path)


def _build_generation_job_summary(job: dict) -> GenerationJobSummaryResponse:
    completed = job.get("completed_chapters", []) or []
    failed = job.get("failed_chapters", []) or []
    return GenerationJobSummaryResponse(
        generation_id=job["id"],
        phase=job.get("phase", "UNKNOWN"),
        course_id=job.get("course_id"),
        progress_percent=job.get("progress_percent", 0),
        status_message=job.get("status_message"),
        completed_chapter_count=len(completed),
        failed_chapter_count=len(failed),
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


def _ensure_teacher_matches_auth(teacher_id: str, auth: AuthenticatedUser) -> None:
    ensure_teacher_matches_auth_impl(teacher_id, auth)


def _require_generation_job_access(job: dict, auth: AuthenticatedUser) -> None:
    require_generation_job_access_impl(job, auth)


def _try_build_docling_parser():
    return _try_build_docling_parser_impl(settings_obj=settings, logger=logger)


def _ensure_docling_available(ext: str) -> None:
    try:
        _ensure_docling_available_impl(ext, settings_obj=settings, logger=logger)
    except RuntimeError as exc:
        raise HTTPException(400, str(exc)) from exc


def _normalize_approved_chapters(indices: list[int], chapter_count: int) -> list[int]:
    return normalize_approved_chapters_impl(indices, chapter_count)


def _merge_completed_chapters(chapters: list[dict]) -> list[dict]:
    return merge_completed_chapters_impl(chapters)


def _without_failed_chapter(chapters: list[dict], chapter_index: int) -> list[dict]:
    return without_failed_chapter_impl(chapters, chapter_index)


def _upsert_failed_chapter(chapters: list[dict], failed: dict) -> list[dict]:
    return upsert_failed_chapter_impl(chapters, failed)


def _dedupe_failed_chapters(chapters: list[dict]) -> list[dict]:
    return dedupe_failed_chapters_impl(chapters)


def _build_partial_failure_summary(failed_chapters: list[dict]) -> Optional[str]:
    return build_partial_failure_summary_impl(failed_chapters)


class _BasicPdfParser(BasicPdfParser):
    """Backward-compatible alias for tests and wrappers."""
