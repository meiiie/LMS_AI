"""
Scheduler Tools — LangChain tools for proactive agent scheduling

Sprint 19: Virtual Agent-per-User Architecture
The agent can schedule reminders, quizzes, and proactive actions for users.

Tools:
- schedule_reminder: Schedule a future task/reminder
- list_scheduled_tasks: List user's active scheduled tasks
- cancel_scheduled_task: Cancel a specific scheduled task

Feature-gated: Requires `enable_scheduler=True` in config.
"""

import contextvars
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.engine.tools.native_tool import tool

logger = logging.getLogger(__name__)

# Sprint 26: contextvars for per-request isolation


@dataclass
class SchedulerToolState:
    """Per-request state for scheduler tools."""
    user_id: Optional[str] = None
    domain_id: str = "maritime"
    identity_key: Optional[str] = None


_scheduler_tool_state: contextvars.ContextVar[Optional[SchedulerToolState]] = contextvars.ContextVar(
    '_scheduler_tool_state', default=None
)


def _tool_identity(
    user_id: Optional[str] = None,
    domain_id: str = "maritime",
) -> tuple[str, Optional[str], str, bool]:
    """Resolve the current scheduler tool identity for state isolation."""
    runtime_user_id = None
    runtime_org_id = ""
    runtime_session_id = ""
    identity_available = bool(user_id)

    try:
        from app.engine.tools.runtime_context import get_current_tool_runtime_context

        runtime = get_current_tool_runtime_context()
        if runtime:
            runtime_user_id = runtime.user_id
            runtime_org_id = str(runtime.organization_id or "").strip()
            runtime_session_id = str(runtime.session_id or "").strip()
            identity_available = identity_available or bool(
                runtime_user_id or runtime_org_id or runtime_session_id
            )
    except Exception:
        pass

    if not runtime_org_id:
        try:
            from app.core.org_context import get_current_org_id

            runtime_org_id = str(get_current_org_id() or "").strip()
            identity_available = identity_available or bool(runtime_org_id)
        except Exception:
            pass

    resolved_user_id = (
        str(user_id or runtime_user_id).strip()
        if user_id or runtime_user_id
        else None
    )
    resolved_domain_id = str(domain_id or "maritime").strip() or "maritime"
    identity_key = (
        f"user={resolved_user_id or ''}|org={runtime_org_id}|"
        f"session={runtime_session_id}|domain={resolved_domain_id}"
    )
    return identity_key, resolved_user_id, resolved_domain_id, identity_available


def _new_scheduler_state(
    user_id: Optional[str] = None,
    domain_id: str = "maritime",
) -> SchedulerToolState:
    identity_key, resolved_user_id, resolved_domain_id, _ = _tool_identity(
        user_id,
        domain_id,
    )
    return SchedulerToolState(
        user_id=resolved_user_id,
        domain_id=resolved_domain_id,
        identity_key=identity_key,
    )


def _get_scheduler_state(
    user_id: Optional[str] = None,
    domain_id: str = "maritime",
) -> SchedulerToolState:
    """Get or create identity-scoped scheduler tool state."""
    identity_key, resolved_user_id, resolved_domain_id, identity_available = (
        _tool_identity(user_id, domain_id)
    )
    state = _scheduler_tool_state.get(None)
    if state is None:
        state = _new_scheduler_state(user_id, domain_id)
        _scheduler_tool_state.set(state)
    elif identity_available and state.identity_key != identity_key:
        state = _new_scheduler_state(user_id, domain_id)
        _scheduler_tool_state.set(state)
    elif state.identity_key is None:
        state.identity_key = identity_key
        if resolved_user_id:
            state.user_id = resolved_user_id
        state.domain_id = resolved_domain_id
    return state


def set_scheduler_user(user_id: str, domain_id: str = "maritime") -> None:
    """Set current user context for scheduler tools (per-request)."""
    _get_scheduler_state(user_id, domain_id)


@tool
def tool_schedule_reminder(description: str, when: str) -> str:
    """
    Lên lịch nhắc nhở hoặc tác vụ cho người dùng.

    Sử dụng tool này khi người dùng muốn được nhắc nhở về một chủ đề,
    ôn tập kiến thức, hoặc làm quiz sau một khoảng thời gian.

    Args:
        description: Mô tả tác vụ bằng tiếng Việt (ví dụ: "Nhắc ôn tập Quy tắc 13-15 COLREGs")
        when: Thời điểm thực hiện, định dạng ISO 8601 (ví dụ: "2026-02-10T09:00:00+07:00")

    Returns:
        Kết quả tạo lịch nhắc nhở
    """
    _sched_state = _get_scheduler_state()
    _current_user_id = _sched_state.user_id
    _current_domain_id = _sched_state.domain_id
    if not _current_user_id:
        return "Không thể lên lịch: chưa xác định user_id"

    try:
        # Validate datetime
        run_time = datetime.fromisoformat(when)
        if run_time <= datetime.now(timezone.utc):
            return "Không thể lên lịch: thời điểm phải ở tương lai"

        from app.repositories.scheduler_repository import get_scheduler_repository
        repo = get_scheduler_repository()

        task_id = repo.create_task(
            user_id=_current_user_id,
            description=description,
            schedule_type="once",
            schedule_expr=when,
            next_run=run_time,
            domain_id=_current_domain_id,
        )

        if task_id:
            return (
                f"Đã lên lịch thành công!\n"
                f"- Nội dung: {description}\n"
                f"- Thời điểm: {when}\n"
                f"- ID: {task_id}"
            )
        return "Không thể tạo lịch nhắc nhở. Vui lòng thử lại."

    except ValueError:
        return f"Định dạng thời gian không hợp lệ: {when}. Sử dụng ISO 8601 (ví dụ: 2026-02-10T09:00:00+07:00)"
    except Exception as e:
        logger.warning("Schedule reminder failed: %s", e)
        return f"Lỗi khi lên lịch: {e}"


@tool
def tool_list_scheduled_tasks() -> str:
    """
    Liệt kê các tác vụ đã lên lịch của người dùng hiện tại.

    Returns:
        Danh sách các tác vụ đã lên lịch (hoặc thông báo trống)
    """
    _sched_state = _get_scheduler_state()
    _current_user_id = _sched_state.user_id
    _current_domain_id = _sched_state.domain_id
    if not _current_user_id:
        return "Không thể liệt kê: chưa xác định user_id"

    try:
        from app.repositories.scheduler_repository import get_scheduler_repository
        repo = get_scheduler_repository()

        tasks = repo.list_tasks(user_id=_current_user_id)
        if not tasks:
            return "Bạn chưa có tác vụ nào được lên lịch."

        parts = [f"Bạn có {len(tasks)} tác vụ đã lên lịch:"]
        for t in tasks:
            parts.append(
                f"- [{t['id'][:8]}] {t['description']} "
                f"(lần chạy tiếp: {t['next_run'] or 'N/A'}, "
                f"loại: {t['schedule_type']})"
            )

        return "\n".join(parts)

    except Exception as e:
        logger.warning("List scheduled tasks failed: %s", e)
        return f"Lỗi khi liệt kê: {e}"


@tool
def tool_cancel_scheduled_task(task_id: str) -> str:
    """
    Hủy một tác vụ đã lên lịch.

    Args:
        task_id: ID của tác vụ cần hủy (UUID hoặc 8 ký tự đầu)

    Returns:
        Kết quả hủy tác vụ
    """
    _sched_state = _get_scheduler_state()
    _current_user_id = _sched_state.user_id
    _current_domain_id = _sched_state.domain_id
    if not _current_user_id:
        return "Không thể hủy: chưa xác định user_id"

    try:
        from app.repositories.scheduler_repository import get_scheduler_repository
        repo = get_scheduler_repository()

        # Support short ID (first 8 chars)
        if len(task_id) < 36:
            tasks = repo.list_tasks(user_id=_current_user_id)
            matched = [t for t in tasks if t["id"].startswith(task_id)]
            if len(matched) == 1:
                task_id = matched[0]["id"]
            elif len(matched) > 1:
                return f"Có {len(matched)} tác vụ khớp với ID '{task_id}'. Vui lòng cung cấp ID đầy đủ."
            else:
                return f"Không tìm thấy tác vụ với ID '{task_id}'"

        success = repo.cancel_task(task_id=task_id, user_id=_current_user_id)
        if success:
            return f"Đã hủy tác vụ {task_id[:8]}..."
        return "Không thể hủy: tác vụ không tồn tại hoặc đã hủy trước đó"

    except Exception as e:
        logger.warning("Cancel scheduled task failed: %s", e)
        return f"Lỗi khi hủy: {e}"


def get_scheduler_tools() -> list:
    """Get all scheduler tools for registration."""
    return [tool_schedule_reminder, tool_list_scheduled_tasks, tool_cancel_scheduled_task]


def init_scheduler_tools(user_id: str, domain_id: str = "maritime") -> None:
    """Initialize scheduler tools with current user context (per-request)."""
    set_scheduler_user(user_id, domain_id)
