import logging

from app.core import logging_config
from app.core.logging_config import setup_logging


class _StrictCp1252Stream:
    encoding = "cp1252"

    def __init__(self) -> None:
        self.writes: list[str] = []
        self.flush_count = 0

    def write(self, text: str) -> int:
        text.encode(self.encoding)
        self.writes.append(text)
        return len(text)

    def flush(self) -> None:
        self.flush_count += 1


class _ReconfigurableCp1252Stream(_StrictCp1252Stream):
    def __init__(self) -> None:
        super().__init__()
        self.reconfigure_calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs: str) -> None:
        self.reconfigure_calls.append(dict(kwargs))


def test_setup_logging_silences_openai_sdk_request_logs():
    setup_logging(json_output=False, log_level="INFO")

    assert logging.getLogger("openai").level == logging.WARNING
    assert logging.getLogger("openai._base_client").level == logging.WARNING


def test_setup_logging_reconfigures_stdout_for_utf8(monkeypatch):
    stream = _ReconfigurableCp1252Stream()
    monkeypatch.setattr(logging_config.sys, "stdout", stream)

    setup_logging(json_output=False, log_level="INFO")

    assert stream.reconfigure_calls
    assert stream.reconfigure_calls[0]["encoding"] == "utf-8"
    assert stream.reconfigure_calls[0]["errors"] == "backslashreplace"


def test_logging_handler_survives_vietnamese_on_cp1252_stream(monkeypatch):
    stream = _StrictCp1252Stream()
    monkeypatch.setattr(logging_config.sys, "stdout", stream)

    setup_logging(json_output=False, log_level="INFO")
    logger = logging.getLogger("wiii.test.logging")
    logger.info("đăng thử bài thơ lên facebook đi")

    joined = "".join(stream.writes)
    assert "\\u0111" in joined
    assert "facebook" in joined


def test_settings_repr_hides_provider_secrets():
    from app.core.config import Settings
    from app.core.config.llm import LLMConfig

    flat_settings = Settings(
        nvidia_api_key="nvapi-super-secret",
        openai_api_key="sk-super-secret",
    )
    nested_settings = LLMConfig(nvidia_api_key="nvapi-super-secret")

    assert "nvapi-super-secret" not in repr(flat_settings)
    assert "sk-super-secret" not in repr(flat_settings)
    assert "nvapi-super-secret" not in repr(nested_settings)
