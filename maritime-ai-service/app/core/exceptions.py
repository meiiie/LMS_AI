"""
Wiii Exception Hierarchy

Typed exceptions for consistent error handling across the platform.
Each exception maps to an HTTP status code and error code for API responses.
"""

from typing import Optional


class WiiiException(Exception):
    """Base exception for all Wiii platform errors."""

    http_status: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str = "", details: Optional[str] = None):
        self.message = message
        self.details = details
        super().__init__(message)


class ChatServiceError(WiiiException):
    """Chat processing pipeline failure (500)."""

    http_status = 500
    error_code = "CHAT_SERVICE_ERROR"


class RetrievalError(WiiiException):
    """Knowledge retrieval or grading failure (503)."""

    http_status = 503
    error_code = "RETRIEVAL_FAILED"


class LLMError(WiiiException):
    """LLM provider call failure (502)."""

    http_status = 502
    error_code = "LLM_ERROR"


class RepositoryError(WiiiException):
    """Database or storage unavailable (503)."""

    http_status = 503
    error_code = "REPOSITORY_ERROR"


class DomainError(WiiiException):
    """Domain not found or misconfigured (404)."""

    http_status = 404
    error_code = "DOMAIN_NOT_FOUND"


class ValidationError(WiiiException):
    """Input validation failure (400)."""

    http_status = 400
    error_code = "VALIDATION_ERROR"


class ProviderUnavailableError(WiiiException):
    """Requested runtime provider is not currently selectable (503)."""

    http_status = 503
    error_code = "PROVIDER_UNAVAILABLE"

    def __init__(
        self,
        *,
        provider: str,
        reason_code: str,
        message: str = "Provider currently unavailable.",
        details: Optional[str] = None,
    ):
        super().__init__(message=message, details=details)
        self.provider = provider
        self.reason_code = reason_code


class ProviderStreamInterruptedError(LLMError):
    """Provider stream ended before a complete assistant answer was received."""

    error_code = "PROVIDER_STREAM_INTERRUPTED"

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        partial_chars: int = 0,
        message: str = (
            "Luồng phản hồi từ model bị ngắt giữa chừng. "
            "Wiii chưa chốt câu trả lời này; bạn thử gửi lại hoặc đổi provider."
        ),
        details: Optional[str] = None,
    ):
        super().__init__(message=message, details=details)
        self.provider = provider
        self.model = model
        self.partial_chars = max(0, int(partial_chars or 0))
        self.reason_code = "provider_stream_interrupted"
