"""
Tutor Tools - Structured Learning Tools for Wiii

Category: LEARNING (Structured teaching sessions)
Access: Mixed (READ for status, WRITE for session changes)

SOTA 2024: Stateful tools with session persistence in ReAct agents.
These tools expose the TutorAgent's state machine via the ToolRegistry,
allowing multi-agent graph to provide structured learning experiences.

Phases: INTRODUCTION → EXPLANATION → ASSESSMENT → COMPLETED
"""

import contextvars
import logging
from dataclasses import dataclass
from typing import Optional

from app.engine.tools.native_tool import tool

from app.engine.tools.registry import (
    ToolCategory, ToolAccess, get_tool_registry
)

logger = logging.getLogger(__name__)


# =============================================================================
# ASYNC-SAFE STATE (contextvars for per-request isolation)
# Sprint 26: Replaces unsafe module-level globals
# =============================================================================

@dataclass
class TutorToolState:
    """Per-request state for tutor tools."""
    user_id: str = "current_user"
    session_id: Optional[str] = None
    identity_key: Optional[str] = None


_tutor_tool_state: contextvars.ContextVar[Optional[TutorToolState]] = contextvars.ContextVar(
    '_tutor_tool_state', default=None
)

# TutorAgent singleton (shared across requests, stateless) - safe as module-level
_tutor_agent = None


def _tool_identity(user_id: Optional[str] = None) -> tuple[str, str, bool]:
    """Resolve the current tutor-tool identity for state isolation."""
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

    resolved_user_id = str(user_id or runtime_user_id or "current_user").strip() or "current_user"
    identity_key = (
        f"user={resolved_user_id}|org={runtime_org_id}|session={runtime_session_id}"
    )
    return identity_key, resolved_user_id, identity_available


def _new_state(user_id: Optional[str] = None) -> TutorToolState:
    identity_key, resolved_user_id, _ = _tool_identity(user_id)
    return TutorToolState(user_id=resolved_user_id, identity_key=identity_key)


def _get_state(user_id: Optional[str] = None) -> TutorToolState:
    """Get or create identity-scoped tutor tool state."""
    identity_key, resolved_user_id, identity_available = _tool_identity(user_id)
    state = _tutor_tool_state.get(None)
    if state is None:
        state = _new_state(user_id)
        _tutor_tool_state.set(state)
    elif identity_available and state.identity_key != identity_key:
        state = _new_state(user_id)
        _tutor_tool_state.set(state)
    elif state.identity_key is None:
        state.identity_key = identity_key
        state.user_id = resolved_user_id
    return state


def init_tutor_tools(user_id: Optional[str] = None):
    """
    Initialize tutor tools with user context.

    Called by multi-agent graph when processing a request.
    """
    global _tutor_agent

    if _tutor_agent is None:
        try:
            from app.engine.tutor.tutor_agent import TutorAgent
            _tutor_agent = TutorAgent()
            logger.info("TutorAgent initialized for tutor tools")
        except ImportError as e:
            logger.error("Failed to import TutorAgent: %s", e)
            return

    if user_id:
        _get_state(user_id)
    logger.info("Tutor tools initialized for user: %s", user_id)


def set_tutor_user(user_id: str):
    """Set the current user ID for tutor operations (per-request)."""
    _get_state(user_id)


def get_current_session_id() -> Optional[str]:
    """Get the current active session ID (per-request)."""
    return _get_state().session_id


# =============================================================================
# TUTOR TOOLS - Structured Learning
# =============================================================================

@tool(description="""
Bắt đầu một buổi học có cấu trúc về chủ đề hàng hải.
Gọi khi user nói: "dạy tôi về", "học về", "teach me", "start lesson".
Ví dụ: "Dạy tôi về SOLAS" → gọi tool này với topic="solas".
Chủ đề hỗ trợ: solas, colregs, fire_safety.
""")
async def tool_start_lesson(topic: str) -> str:
    """Start a structured learning session on a maritime topic."""
    global _tutor_agent

    state = _get_state()

    if not _tutor_agent:
        init_tutor_tools(state.user_id)
        if not _tutor_agent:
            return "Lỗi: TutorAgent không khả dụng."

    try:
        user_id = state.user_id
        logger.info("[TOOL] Starting lesson on '%s' for user %s", topic, user_id)

        response = _tutor_agent.start_session(topic, user_id)
        state.session_id = response.state.session_id

        result = f"**Buoi hoc: {topic.upper()}**\n\n"
        result += response.content
        result += f"\n\nPhase: {response.phase.value}"

        logger.info("[TOOL] Lesson started, session_id=%s", state.session_id)
        return result

    except Exception as e:
        logger.error("Start lesson error: %s", e)
        return f"Lỗi khi bắt đầu buổi học: {str(e)}"


@tool(description="""
Tiếp tục buổi học hiện tại hoặc trả lời câu hỏi quiz.
Gọi khi user đang trong buổi học và nói: "ready", "tiếp tục", "continue", hoặc trả lời câu hỏi.
Nếu đang ở phase ASSESSMENT, input sẽ được xem là câu trả lời cho quiz.
""")
async def tool_continue_lesson(user_input: str) -> str:
    """Continue the current lesson or answer a quiz question."""
    global _tutor_agent

    state = _get_state()

    if not _tutor_agent:
        return "Lỗi: Chưa có buổi học nào được bắt đầu. Hãy dùng 'Dạy tôi về...' trước."

    if not state.session_id:
        return "Lỗi: Không có buổi học đang hoạt động. Hãy bắt đầu buổi học mới."

    try:
        logger.info("[TOOL] Continuing lesson, input: '%s...'", user_input[:50])

        response = _tutor_agent.process_response(user_input, state.session_id)

        result = response.content

        # Add status info
        if response.phase.value == "ASSESSMENT":
            resp_state = response.state
            result += f"\n\nScore: {resp_state.correct_answers}/{resp_state.questions_asked} ({resp_state.score:.0f}%)"

        if response.assessment_complete:
            result += "\n\nBuoi hoc da hoan thanh!"
            if response.mastery_achieved:
                result += " **Ban da dat Mastery!**"
            state.session_id = None  # Clear session

        return result

    except Exception as e:
        logger.error("Continue lesson error: %s", e)
        return f"Lỗi: {str(e)}"


@tool(description="""
Xem trạng thái buổi học hiện tại.
Gọi khi user hỏi: "đang học gì", "tiến độ", "score", "status".
""")
async def tool_lesson_status() -> str:
    """Get the current lesson status and score."""
    global _tutor_agent

    tool_state = _get_state()

    if not tool_state.session_id:
        return "Không có buổi học nào đang hoạt động. Hãy nói 'Dạy tôi về [chủ đề]' để bắt đầu."

    try:
        state = _tutor_agent.get_session(tool_state.session_id)
        if not state:
            return "Không tìm thấy thông tin buổi học."
        
        status = f"""📊 **Trạng thái buổi học**

- **Chủ đề:** {state.topic}
- **Phase:** {state.current_phase.value}
- **Câu hỏi:** {state.questions_asked} / 5
- **Đúng:** {state.correct_answers}
- **Score:** {state.score:.0f}%
- **Hints đã dùng:** {state.hints_given}
"""
        
        if state.has_mastery():
            status += "\n🌟 **Mastery đạt được!**"
        elif state.is_struggling():
            status += "\n📚 Cần ôn tập thêm"
            
        return status
        
    except Exception as e:
        logger.error("Lesson status error: %s", e)
        return f"Lỗi: {str(e)}"


@tool(description="""
Kết thúc buổi học hiện tại và xem kết quả.
Gọi khi user nói: "kết thúc buổi học", "end lesson", "thoát học", "stop".
""")
async def tool_end_lesson() -> str:
    """End the current lesson and show final results."""
    global _tutor_agent

    tool_state = _get_state()

    if not tool_state.session_id:
        return "Không có buổi học nào đang hoạt động."

    try:
        state = _tutor_agent.get_session(tool_state.session_id)
        if not state:
            tool_state.session_id = None
            return "Buoi hoc da ket thuc."
        
        result = f"""🎓 **Kết quả buổi học: {state.topic.upper()}**

📊 **Thống kê:**
- Câu hỏi: {state.questions_asked}
- Trả lời đúng: {state.correct_answers}
- Điểm số: {state.score:.0f}%
- Hints đã dùng: {state.hints_given}

"""
        
        if state.has_mastery():
            result += "🌟 **Xuất sắc!** Bạn đã thành thạo chủ đề này!"
        elif state.score >= 50:
            result += "👍 **Tốt!** Bạn đã nắm được kiến thức cơ bản."
        else:
            result += "📚 **Cần ôn tập!** Hãy học lại chủ đề này."
        
        # Clear session
        tool_state.session_id = None
        logger.info("[TOOL] Lesson ended for topic: %s", state.topic)
        
        return result
        
    except Exception as e:
        logger.error("End lesson error: %s", e)
        _current_session_id = None
        return f"Lỗi khi kết thúc buổi học: {str(e)}"


# =============================================================================
# REGISTER TOOLS
# =============================================================================

def register_tutor_tools():
    """Register all tutor tools with the registry."""
    registry = get_tool_registry()
    
    # Learning session tools
    registry.register(
        tool=tool_start_lesson,
        category=ToolCategory.LEARNING,
        access=ToolAccess.WRITE,
        description="Start a structured learning session on a maritime topic"
    )
    
    registry.register(
        tool=tool_continue_lesson,
        category=ToolCategory.LEARNING,
        access=ToolAccess.WRITE,
        description="Continue lesson or answer quiz question"
    )
    
    registry.register(
        tool=tool_lesson_status,
        category=ToolCategory.LEARNING,
        access=ToolAccess.READ,
        description="Get current lesson status and score"
    )
    
    registry.register(
        tool=tool_end_lesson,
        category=ToolCategory.LEARNING,
        access=ToolAccess.WRITE,
        description="End lesson and show results"
    )
    
    logger.info("Tutor tools registered (4 tools)")


# Auto-register on import
register_tutor_tools()
