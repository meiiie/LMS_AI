"""
Wiii Structured Logging — SOTA 2026

Configures structlog for JSON output (production) or colored console (development).
Integrates with stdlib logging so all existing `logging.getLogger()` calls
automatically emit structured output.

Usage:
    from app.core.logging_config import setup_logging
    setup_logging()  # Call once at app startup
"""

import logging
import sys
from typing import Any, BinaryIO

import structlog


def _stream_candidates(stream: Any) -> list[Any]:
    """Return plausible wrapped text streams without depending on colorama internals."""

    candidates: list[Any] = []
    seen: set[int] = set()
    pending = [stream]
    while pending:
        current = pending.pop(0)
        if current is None:
            continue
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        candidates.append(current)
        for attr in ("wrapped", "stream", "_stream", "_StreamWrapper__wrapped"):
            wrapped = getattr(current, attr, None)
            if wrapped is not None:
                pending.append(wrapped)
    return candidates


def _reconfigure_stdio_stream(stream: Any) -> None:
    """Prefer UTF-8 console/file logging even when Windows defaults to cp1252."""

    for candidate in _stream_candidates(stream):
        reconfigure = getattr(candidate, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="backslashreplace")
                return
            except (TypeError, ValueError, OSError):
                continue


def _stream_binary_buffer(stream: Any) -> BinaryIO | None:
    for candidate in _stream_candidates(stream):
        buffer = getattr(candidate, "buffer", None)
        if buffer is not None and hasattr(buffer, "write"):
            return buffer
    return None


class UnicodeSafeStreamHandler(logging.StreamHandler):
    """Stream handler that never lets console encoding break app logging."""

    def emit(self, record: logging.LogRecord) -> None:
        msg = ""
        try:
            msg = self.format(record)
            self.stream.write(msg + self.terminator)
            self.flush()
        except UnicodeEncodeError:
            self._emit_unicode_fallback(msg)
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)

    def _emit_unicode_fallback(self, msg: str) -> None:
        try:
            payload = (msg + self.terminator).encode("utf-8", "backslashreplace")
            buffer = _stream_binary_buffer(self.stream)
            if buffer is not None:
                buffer.write(payload)
                self.flush()
                return

            encoding = getattr(self.stream, "encoding", None) or "utf-8"
            safe_msg = (msg + self.terminator).encode(
                encoding,
                "backslashreplace",
            ).decode(encoding, "replace")
            self.stream.write(safe_msg)
            self.flush()
        except RecursionError:
            raise
        except Exception:
            self.handleError(record)


def setup_logging(*, json_output: bool = False, log_level: str = "INFO") -> None:
    """
    Configure structured logging for the application.

    Args:
        json_output: True for JSON lines (production), False for colored console (dev).
        log_level: Root log level string (DEBUG, INFO, WARNING, ERROR).
    """
    _reconfigure_stdio_stream(sys.stdout)
    _reconfigure_stdio_stream(sys.stderr)

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_output:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = UnicodeSafeStreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # Silence noisy third-party loggers. OpenAI-compatible SDKs can log full
    # request payloads/URLs at INFO, which is too risky for production logs.
    for noisy in (
        "httpcore",
        "httpx",
        "openai",
        "openai._base_client",
        "urllib3",
        "asyncio",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Local dev: keep MCP dependency chatter out of startup logs.
    if not json_output:
        for noisy in (
            "fastapi_mcp.server",
            "mcp.server.lowlevel.server",
            "mcp.server.lowlevel.experimental",
        ):
            logging.getLogger(noisy).setLevel(logging.WARNING)
