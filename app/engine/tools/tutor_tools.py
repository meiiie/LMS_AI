"""
Tutor Tools - Structured Learning Tools for Maritime AI Tutor

Category: LEARNING (Structured teaching sessions)
Access: Mixed (READ for status, WRITE for session changes)

SOTA 2024: Stateful tools with session persistence in ReAct agents.
These tools expose the TutorAgent's state machine via the ToolRegistry,
allowing UnifiedAgent to provide structured learning experiences.

Phases: INTRODUCTION → EXPLANATION → ASSESSMENT → COMPLETED
"""

import logging
from typing import Optional

from langchain_core.tools import tool

from app.engine.tools.registry import (
    ToolCategory, ToolAccess, get_tool_registry
)

logger = logging.getLogger(__name__)


# =============================================================================
# Module-level state (TutorAgent instance + session tracking)
# =============================================================================

_tutor_agent = None
_current_session_id: Optional[str] = None
_current_user_id: Optional[str] = None


def init_tutor_tools(user_id: Optional[str] = None):
    """
    Initialize tutor tools with user context.
    
    Called by UnifiedAgent when processing a request.
    """
    global _tutor_agent, _current_user_id
    
    if _tutor_agent is None:
        try:
            from app.engine.tutor.tutor_agent import TutorAgent
            _tutor_agent = TutorAgent()
            logger.info("TutorAgent initialized for tutor tools")
        except ImportError as e:
            logger.error(f"Failed to import TutorAgent: {e}")
            return
    
    _current_user_id = user_id
    logger.info(f"Tutor tools initialized for user: {user_id}")


def set_tutor_user(user_id: str):
    """Set the current user ID for tutor operations."""
    global _current_user_id
    _current_user_id = user_id


def get_current_session_id() -> Optional[str]:
    """Get the current active session ID."""
    return _current_session_id


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
    global _tutor_agent, _current_session_id, _current_user_id
    
    if not _tutor_agent:
        init_tutor_tools(_current_user_id)
        if not _tutor_agent:
            return "Lỗi: TutorAgent không khả dụng."
    
    try:
        user_id = _current_user_id or "current_user"
        logger.info(f"[TOOL] Starting lesson on '{topic}' for user {user_id}")
        
        response = _tutor_agent.start_session(topic, user_id)
        _current_session_id = response.state.session_id
        
        result = f"🎓 **Buổi học: {topic.upper()}**\n\n"
        result += response.content
        result += f"\n\n📊 Phase: {response.phase.value}"
        
        logger.info(f"[TOOL] Lesson started, session_id={_current_session_id}")
        return result
        
    except Exception as e:
        logger.error(f"Start lesson error: {e}")
        return f"Lỗi khi bắt đầu buổi học: {str(e)}"


@tool(description="""
Tiếp tục buổi học hiện tại hoặc trả lời câu hỏi quiz.
Gọi khi user đang trong buổi học và nói: "ready", "tiếp tục", "continue", hoặc trả lời câu hỏi.
Nếu đang ở phase ASSESSMENT, input sẽ được xem là câu trả lời cho quiz.
""")
async def tool_continue_lesson(user_input: str) -> str:
    """Continue the current lesson or answer a quiz question."""
    global _tutor_agent, _current_session_id
    
    if not _tutor_agent:
        return "Lỗi: Chưa có buổi học nào được bắt đầu. Hãy dùng 'Dạy tôi về...' trước."
    
    if not _current_session_id:
        return "Lỗi: Không có buổi học đang hoạt động. Hãy bắt đầu buổi học mới."
    
    try:
        logger.info(f"[TOOL] Continuing lesson, input: '{user_input[:50]}...'")
        
        response = _tutor_agent.process_response(user_input, _current_session_id)
        
        result = response.content
        
        # Add status info
        if response.phase.value == "ASSESSMENT":
            state = response.state
            result += f"\n\n📊 Score: {state.correct_answers}/{state.questions_asked} ({state.score:.0f}%)"
        
        if response.assessment_complete:
            result += "\n\n✅ Buổi học đã hoàn thành!"
            if response.mastery_achieved:
                result += " 🌟 **Bạn đã đạt Mastery!**"
            _current_session_id = None  # Clear session
        
        return result
        
    except Exception as e:
        logger.error(f"Continue lesson error: {e}")
        return f"Lỗi: {str(e)}"


@tool(description="""
Xem trạng thái buổi học hiện tại.
Gọi khi user hỏi: "đang học gì", "tiến độ", "score", "status".
""")
async def tool_lesson_status() -> str:
    """Get the current lesson status and score."""
    global _tutor_agent, _current_session_id
    
    if not _current_session_id:
        return "Không có buổi học nào đang hoạt động. Hãy nói 'Dạy tôi về [chủ đề]' để bắt đầu."
    
    try:
        state = _tutor_agent.get_session(_current_session_id)
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
        logger.error(f"Lesson status error: {e}")
        return f"Lỗi: {str(e)}"


@tool(description="""
Kết thúc buổi học hiện tại và xem kết quả.
Gọi khi user nói: "kết thúc buổi học", "end lesson", "thoát học", "stop".
""")
async def tool_end_lesson() -> str:
    """End the current lesson and show final results."""
    global _tutor_agent, _current_session_id
    
    if not _current_session_id:
        return "Không có buổi học nào đang hoạt động."
    
    try:
        state = _tutor_agent.get_session(_current_session_id)
        if not state:
            _current_session_id = None
            return "Buổi học đã kết thúc."
        
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
        _current_session_id = None
        logger.info(f"[TOOL] Lesson ended for topic: {state.topic}")
        
        return result
        
    except Exception as e:
        logger.error(f"End lesson error: {e}")
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
