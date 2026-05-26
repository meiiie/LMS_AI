"""
Utility Tools - General-purpose tools for AI agents.

SOTA 2026: Agents need basic utilities beyond domain-specific tools.
These tools provide calculation, datetime, and unit conversion capabilities.
"""

import ast
import asyncio
import logging
import math
import operator
import re
import threading
from datetime import datetime, timezone, timedelta

from app.engine.tools.native_tool import tool

from app.engine.tools.registry import (
    ToolCategory,
    ToolAccess,
    get_tool_registry,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Safe Math Evaluator (no eval/exec — AST-based)
# =============================================================================

# Allowed math operators
_SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}

# Allowed math functions
_SAFE_FUNCTIONS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "log": math.log,
    "log10": math.log10,
    "ceil": math.ceil,
    "floor": math.floor,
    "pi": math.pi,
    "e": math.e,
    # Nautical/domain-useful
    "radians": math.radians,
    "degrees": math.degrees,
}


def _safe_eval(node):
    """Safely evaluate an AST node (no arbitrary code execution)."""
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    elif isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"Unsupported constant: {node.value}")
    elif isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"Unsupported operator: {op_type.__name__}")
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        # Guard against huge exponents
        if op_type == ast.Pow and isinstance(right, (int, float)) and abs(right) > 1000:
            raise ValueError("Exponent too large")
        return _SAFE_OPERATORS[op_type](left, right)
    elif isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _SAFE_OPERATORS:
            raise ValueError(f"Unsupported unary operator: {op_type.__name__}")
        return _SAFE_OPERATORS[op_type](_safe_eval(node.operand))
    elif isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in _SAFE_FUNCTIONS:
            func = _SAFE_FUNCTIONS[node.func.id]
            args = [_safe_eval(arg) for arg in node.args]
            if callable(func):
                return func(*args)
            return func  # Constants like pi, e
        raise ValueError(f"Unsupported function: {getattr(node.func, 'id', '?')}")
    elif isinstance(node, ast.Name):
        if node.id in _SAFE_FUNCTIONS:
            val = _SAFE_FUNCTIONS[node.id]
            if not callable(val):
                return val  # Constants like pi, e
        raise ValueError(f"Unknown variable: {node.id}")
    else:
        raise ValueError(f"Unsupported expression: {type(node).__name__}")


@tool(description="Tính toán biểu thức toán học. Hỗ trợ: +, -, *, /, **, sqrt, sin, cos, log, pi. Ví dụ: '15 * 1.852' (hải lý sang km), 'sqrt(3**2 + 4**2)'")
def tool_calculator(expression: str) -> str:
    """Calculate a math expression safely."""
    try:
        # Parse the expression into AST
        tree = ast.parse(expression.strip(), mode="eval")
        result = _safe_eval(tree)

        # Format result
        if isinstance(result, float):
            if result == int(result) and abs(result) < 1e15:
                formatted = str(int(result))
            else:
                formatted = f"{result:.6g}"
        else:
            formatted = str(result)

        logger.info("[CALC] %s = %s", expression, formatted)
        return f"{expression} = {formatted}"

    except ZeroDivisionError:
        return "Lỗi: Chia cho 0"
    except (ValueError, TypeError, SyntaxError) as e:
        return f"Lỗi biểu thức: {e}"
    except Exception as e:
        logger.warning("Calculator error: %s", e)
        return f"Không thể tính: {e}"


_VN_DAY_NAMES = [
    "Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm",
    "Thứ Sáu", "Thứ Bảy", "Chủ Nhật",
]


def _vn_time_of_day(hour: int) -> str:
    """Return Vietnamese time-of-day label."""
    if 6 <= hour < 12:
        return "buổi sáng"
    elif 12 <= hour < 14:
        return "buổi trưa"
    elif 14 <= hour < 18:
        return "buổi chiều"
    elif 18 <= hour < 22:
        return "buổi tối"
    elif 22 <= hour or hour < 2:
        return "khuya"
    return "rất khuya"


@tool(description="Lấy ngày giờ hiện tại (UTC+7 Việt Nam). Hữu ích khi cần biết thời gian hiện tại, ngày hết hạn, thời hạn.")
def tool_current_datetime() -> str:
    """Get current date and time in Vietnam timezone (UTC+7)."""
    vn_tz = timezone(timedelta(hours=7))
    now = datetime.now(vn_tz)

    day_name = _VN_DAY_NAMES[now.weekday()]
    time_label = _vn_time_of_day(now.hour)

    return (
        f"Ngày giờ hiện tại (UTC+7): {now.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Ngày: {now.strftime('%d/%m/%Y')}\n"
        f"Thứ: {day_name}\n"
        f"Giờ: {now.strftime('%H:%M')}\n"
        f"Buổi: {time_label}"
    )


_WEATHER_CITY_NOISE_MARKERS = (
    "thoi tiet",
    "nhiet do",
    "bao do",
    "may do",
    "hom nay",
    "nay",
    "bay gio",
    "hien tai",
    "weather",
    "forecast",
)


def _fold_weather_text(value: str) -> str:
    import unicodedata

    normalized = unicodedata.normalize("NFKD", str(value or "").lower())
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return " ".join(stripped.replace("đ", "d").split())


def _clean_weather_city(city: str) -> str:
    text = str(city or "").strip()
    text = re.sub(
        r"(?i)^\s*(?:ý\s+là|y\s+la|ý\s+mình\s+là|y\s+minh\s+la|tức\s+là|tuc\s+la)\s+",
        "",
        text,
    ).strip(" .,:;!?-")
    folded = _fold_weather_text(text)
    if not text or len(text) > 80 or "?" in text:
        return ""
    if any(marker in folded for marker in _WEATHER_CITY_NOISE_MARKERS):
        return ""
    return text


def _run_weather_async(factory):
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    result: dict[str, object] = {}

    def runner() -> None:
        try:
            result["value"] = asyncio.run(factory())
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc

    thread = threading.Thread(target=runner, name="weather_tool", daemon=True)
    thread.start()
    thread.join()
    error = result.get("error")
    if isinstance(error, BaseException):
        raise error
    return result.get("value")


@tool(description=(
    "Lấy thời tiết hiện tại từ provider thời tiết đã cấu hình. "
    "Chỉ truyền city khi người dùng nêu rõ địa điểm; nếu không, "
    "dùng thành phố mặc định."
))
def tool_current_weather(city: str = "") -> str:
    """Get current weather for the configured/default city."""
    from app.core.config import settings
    from app.engine.living_agent.weather_service import get_weather_service

    resolved_city = _clean_weather_city(city) or settings.living_agent_weather_city
    if not resolved_city:
        return "Bạn muốn xem nhiệt độ ở thành phố nào?"

    if (
        not settings.living_agent_enable_weather
        or not settings.living_agent_weather_api_key
    ):
        return (
            "Wiii chưa có kết nối thời tiết trực tiếp, nên không nên đoán nhiệt độ. "
            f"Thành phố mặc định hiện đang cấu hình là {resolved_city}. "
            "Hãy bật cấu hình thời tiết hoặc cho mình địa điểm để mình xử lý "
            "qua kênh dữ liệu phù hợp."
        )

    service = get_weather_service()
    try:
        weather = _run_weather_async(lambda: service.get_current(resolved_city))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[WEATHER] Current weather tool failed: %s", exc)
        return (
            f"Mình chưa lấy được thời tiết hiện tại cho {resolved_city}. "
            "Bạn thử lại sau một chút nhé."
        )

    if not weather:
        return (
            f"Mình chưa lấy được thời tiết hiện tại cho {resolved_city}. "
            "Không có dữ liệu đủ chắc để chốt nhiệt độ."
        )

    now = datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M UTC+7")
    return f"Cập nhật {now}: {service.format_current_vi(weather)}"


# =============================================================================
# Initialization
# =============================================================================

def init_utility_tools():
    """Register utility tools with the global registry."""
    registry = get_tool_registry()

    registry.register(
        tool_calculator,
        category=ToolCategory.UTILITY,
        access=ToolAccess.READ,
        description="Safe math calculator"
    )

    registry.register(
        tool_current_datetime,
        category=ToolCategory.UTILITY,
        access=ToolAccess.READ,
        description="Current date/time in Vietnam"
    )

    registry.register(
        tool_current_weather,
        category=ToolCategory.UTILITY,
        access=ToolAccess.READ,
        description="Current weather from configured weather provider"
    )

    logger.info("Utility tools registered: calculator, current_datetime, current_weather")
