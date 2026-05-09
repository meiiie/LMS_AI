import base64
import time
from unittest.mock import AsyncMock

import pytest


def _fake_image_b64() -> str:
    return base64.b64encode(b"fake-image-bytes").decode("utf-8")


def test_resolve_provider_order_prefers_explicit_provider(monkeypatch):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "vision_provider", "auto", raising=False)
    monkeypatch.setattr(vr.settings, "vision_failover_chain", ["google", "openai"], raising=False)
    monkeypatch.setattr(vr.settings, "llm_failover_chain", ["ollama"], raising=False)

    order = vr._resolve_provider_order(
        capability=vr.VisionCapability.VISUAL_DESCRIBE,
        preferred_provider="openai",
    )

    assert order[0] == "openai"
    assert "google" in order
    assert "ollama" in order


def test_resolve_provider_order_infers_zhipu_for_ocr_specialist(monkeypatch):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "vision_provider", "auto", raising=False)
    monkeypatch.setattr(vr.settings, "vision_failover_chain", ["google", "openai"], raising=False)
    monkeypatch.setattr(vr.settings, "llm_failover_chain", ["ollama"], raising=False)
    monkeypatch.setattr(vr.settings, "vision_ocr_provider", "auto", raising=False)
    monkeypatch.setattr(vr.settings, "vision_ocr_model", "glm-ocr", raising=False)
    vr.reset_vision_runtime_caches()
    monkeypatch.setattr(vr, "_load_recent_audit_demoted_providers", lambda capability: set())

    order = vr._resolve_provider_order(
        capability=vr.VisionCapability.OCR_EXTRACT,
        preferred_provider=None,
    )

    assert order[0] == "zhipu"
    assert "google" in order


def test_resolve_provider_order_demotes_recent_runtime_failure_for_zhipu_ocr(monkeypatch):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "vision_provider", "auto", raising=False)
    monkeypatch.setattr(vr.settings, "vision_failover_chain", ["ollama", "google"], raising=False)
    monkeypatch.setattr(vr.settings, "llm_failover_chain", [], raising=False)
    monkeypatch.setattr(vr.settings, "vision_ocr_provider", "auto", raising=False)
    monkeypatch.setattr(vr.settings, "vision_ocr_model", "glm-ocr", raising=False)
    vr.reset_vision_runtime_caches()
    monkeypatch.setattr(vr, "_load_recent_audit_demoted_providers", lambda capability: set())

    vr._record_recent_vision_failure(
        "zhipu",
        vr.VisionCapability.OCR_EXTRACT,
        reason_code="provider_unavailable",
    )
    order = vr._resolve_provider_order(
        capability=vr.VisionCapability.OCR_EXTRACT,
        preferred_provider=None,
    )

    assert order[0] == "ollama"
    assert order[-1] == "zhipu"


def test_provider_status_marks_zhipu_ocr_as_specialist(monkeypatch):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "zhipu_api_key", "zhipu-key", raising=False)
    monkeypatch.setattr(
        vr.settings,
        "zhipu_base_url",
        "https://open.bigmodel.cn/api/paas/v4",
        raising=False,
    )

    status = vr._provider_status(
        "zhipu",
        vr.VisionCapability.OCR_EXTRACT,
        model_name="glm-ocr",
    )

    assert status.available is True
    assert status.lane_fit == "specialist"
    assert status.lane_fit_label == "OCR specialist"


def test_openai_vision_generation_kwargs_use_current_token_param_for_gpt5():
    from app.engine import vision_runtime as vr

    kwargs = vr._openai_vision_generation_kwargs(
        provider="openai",
        model_name="gpt-5.4-mini",
        max_output_tokens=512,
        temperature=0.2,
    )

    assert kwargs == {"max_completion_tokens": 512}


def test_openai_vision_generation_kwargs_keep_compat_shape_for_openrouter():
    from app.engine import vision_runtime as vr

    kwargs = vr._openai_vision_generation_kwargs(
        provider="openrouter",
        model_name="openai/gpt-5.4-mini",
        max_output_tokens=512,
        temperature=0.2,
    )

    assert kwargs == {"max_tokens": 512, "temperature": 0.2}


def test_provider_status_marks_ollama_ocr_as_fallback(monkeypatch):
    from app.engine import vision_runtime as vr

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"models":[{"name":"gemma3:4b","model":"gemma3:4b"}]}'

    monkeypatch.setattr(vr.settings, "ollama_base_url", "http://localhost:11434", raising=False)
    monkeypatch.setattr(vr, "urlopen", lambda request, timeout=2.0: _FakeResponse())
    vr.reset_vision_runtime_caches()

    status = vr._provider_status(
        "ollama",
        vr.VisionCapability.OCR_EXTRACT,
        model_name="gemma3:4b",
    )

    assert status.available is True
    assert status.lane_fit == "fallback"
    assert status.lane_fit_label == "OCR fallback"


def test_resolve_provider_order_keeps_explicit_provider_even_when_demoted(monkeypatch):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "vision_provider", "auto", raising=False)
    monkeypatch.setattr(vr.settings, "vision_failover_chain", ["ollama", "google"], raising=False)
    monkeypatch.setattr(vr.settings, "llm_failover_chain", [], raising=False)
    monkeypatch.setattr(vr.settings, "vision_ocr_provider", "auto", raising=False)
    monkeypatch.setattr(vr.settings, "vision_ocr_model", "glm-ocr", raising=False)
    vr.reset_vision_runtime_caches()
    monkeypatch.setattr(vr, "_load_recent_audit_demoted_providers", lambda capability: {"zhipu"})

    vr._record_recent_vision_failure(
        "zhipu",
        vr.VisionCapability.OCR_EXTRACT,
        reason_code="timeout",
    )
    order = vr._resolve_provider_order(
        capability=vr.VisionCapability.OCR_EXTRACT,
        preferred_provider="zhipu",
    )

    assert order[0] == "zhipu"


def test_recent_audit_demoted_providers_only_applies_to_ocr(monkeypatch):
    from app.engine import vision_runtime as vr

    vr.reset_vision_runtime_caches()
    monkeypatch.setattr(
        vr,
        "_vision_audit_demotion_cache",
        (
            time.monotonic(),
            {
                ("zhipu", vr.VisionCapability.OCR_EXTRACT.value): "Provider tam thoi khong kha dung.",
                ("ollama", vr.VisionCapability.VISUAL_DESCRIBE.value): "Provider phan hoi qua lau va da bi timeout.",
            },
        ),
    )

    assert vr._load_recent_audit_demoted_providers(vr.VisionCapability.OCR_EXTRACT) == {"zhipu"}
    assert vr._load_recent_audit_demoted_providers(vr.VisionCapability.VISUAL_DESCRIBE) == set()


def test_recent_audit_demoted_providers_skips_provider_after_runtime_recovery(monkeypatch):
    from types import SimpleNamespace

    from app.engine import vision_runtime as vr

    vr.reset_vision_runtime_caches()
    monkeypatch.setattr(vr, "_vision_audit_demotion_cache", None)
    monkeypatch.setattr(
        "app.services.vision_runtime_audit_service.get_persisted_vision_runtime_audit",
        lambda: SimpleNamespace(
            payload={
                "providers": {
                    "zhipu": {
                        "capabilities": {
                            "ocr_extract": {
                                "last_probe_attempt_at": "2026-04-04T01:00:00+00:00",
                                "last_probe_success_at": None,
                                "last_probe_error": "Provider tam thoi khong kha dung.",
                                "last_runtime_success_at": "2026-04-04T01:00:10+00:00",
                            }
                        }
                    }
                }
            }
        ),
    )

    assert vr._load_recent_audit_demoted_providers(vr.VisionCapability.OCR_EXTRACT) == set()


def test_provider_status_accepts_openrouter_qwen_vl(monkeypatch):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "openai_api_key", "openrouter-key", raising=False)
    monkeypatch.setattr(
        vr.settings,
        "openai_base_url",
        "https://openrouter.ai/api/v1",
        raising=False,
    )

    status = vr._provider_status(
        "openrouter",
        vr.VisionCapability.VISUAL_DESCRIBE,
        model_name="qwen/qwen2.5-vl-32b-instruct",
    )

    assert status.available is True
    assert status.model_name == "qwen/qwen2.5-vl-32b-instruct"


def test_provider_status_accepts_nvidia_vlm(monkeypatch):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "nvidia_api_key", "nvapi-test-key", raising=False)
    monkeypatch.setattr(
        vr.settings,
        "nvidia_base_url",
        "https://integrate.api.nvidia.com/v1",
        raising=False,
    )

    status = vr._provider_status(
        "nvidia",
        vr.VisionCapability.VISUAL_DESCRIBE,
        model_name="nvidia/nemotron-nano-12b-v2-vl",
    )

    assert status.available is True
    assert status.model_name == "nvidia/nemotron-nano-12b-v2-vl"
    assert status.resolved_base_url == "https://integrate.api.nvidia.com/v1"


@pytest.mark.parametrize(
    "model_name",
    [
        "meta/llama-3.2-11b-vision-instruct",
        "meta/llama-4-maverick-17b-128e-instruct",
        "google/gemma-4-31b-it",
        "mistralai/ministral-14b-instruct-2512",
        "moonshotai/kimi-k2.6",
    ],
)
def test_provider_status_accepts_nvidia_catalog_multimodal_models(monkeypatch, model_name):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "nvidia_api_key", "nvapi-test-key", raising=False)

    status = vr._provider_status(
        "nvidia",
        vr.VisionCapability.VISUAL_DESCRIBE,
        model_name=model_name,
    )

    assert status.available is True
    assert status.model_name == model_name


def test_provider_status_rejects_nvidia_text_model_for_vision(monkeypatch):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "nvidia_api_key", "nvapi-test-key", raising=False)

    status = vr._provider_status(
        "nvidia",
        vr.VisionCapability.VISUAL_DESCRIBE,
        model_name="deepseek-ai/deepseek-v4-flash",
    )

    assert status.available is False
    assert status.reason_code == "model_unverified"


def test_provider_status_accepts_zhipu_glm_ocr(monkeypatch):
    from app.engine import vision_runtime as vr

    monkeypatch.setattr(vr.settings, "zhipu_api_key", "zhipu-key", raising=False)
    monkeypatch.setattr(
        vr.settings,
        "zhipu_base_url",
        "https://api.z.ai/api/paas/v4",
        raising=False,
    )

    status = vr._provider_status(
        "zhipu",
        vr.VisionCapability.OCR_EXTRACT,
        model_name="glm-ocr",
    )

    assert status.available is True
    assert status.model_name == "glm-ocr"
    assert status.resolved_base_url == "https://api.z.ai/api/paas/v4"


def test_provider_status_accepts_ollama_gemma3(monkeypatch):
    from app.engine import vision_runtime as vr

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"models":[{"name":"gemma3:4b","model":"gemma3:4b"}]}'

    monkeypatch.setattr(vr.settings, "ollama_base_url", "http://localhost:11434", raising=False)
    monkeypatch.setattr(vr, "urlopen", lambda request, timeout=2.0: _FakeResponse())
    vr.reset_vision_runtime_caches()

    status = vr._provider_status(
        "ollama",
        vr.VisionCapability.VISUAL_DESCRIBE,
        model_name="gemma3:4b",
    )

    assert status.available is True
    assert status.model_name == "gemma3:4b"


def test_provider_status_accepts_ollama_qwen25vl(monkeypatch):
    from app.engine import vision_runtime as vr

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"models":[{"name":"qwen2.5vl:3b","model":"qwen2.5vl:3b"}]}'

    monkeypatch.setattr(vr.settings, "ollama_base_url", "http://localhost:11434", raising=False)
    monkeypatch.setattr(vr, "urlopen", lambda request, timeout=2.0: _FakeResponse())
    vr.reset_vision_runtime_caches()

    status = vr._provider_status(
        "ollama",
        vr.VisionCapability.VISUAL_DESCRIBE,
        model_name="qwen2.5vl:3b",
    )

    assert status.available is True
    assert status.model_name == "qwen2.5vl:3b"


def test_build_image_data_url_wraps_raw_base64():
    from app.engine import vision_runtime as vr

    data_url = vr._build_image_data_url(
        image_base64="YWJjMTIz",
        media_type="image/png",
    )

    assert data_url == "data:image/png;base64,YWJjMTIz"


def test_build_image_data_url_keeps_existing_data_url():
    from app.engine import vision_runtime as vr

    original = "data:image/png;base64,YWJjMTIz"

    assert (
        vr._build_image_data_url(
            image_base64=original,
            media_type="image/png",
        )
        == original
    )


def test_image_analysis_prompt_prioritizes_exact_marker_text():
    from app.engine import vision_runtime as vr

    prompt = vr._build_image_analysis_prompt("Đọc marker trong ảnh")

    assert "copy the exact visible text verbatim" in prompt
    assert "only visible evidence" in prompt
    assert "Final answer must be in Vietnamese" in prompt
    assert "background color" in prompt
    assert "Answer every explicit part" in prompt


def test_compact_repeated_vision_text_removes_exact_sentence_loops():
    from app.engine import vision_runtime as vr

    compacted = vr._compact_repeated_vision_text(
        "Marker là WIII. Nền màu xanh. Nền màu xanh. Nền màu xanh."
    )

    assert compacted == "Marker là WIII. Nền màu xanh."


def test_compact_repeated_vision_text_strips_answer_label():
    from app.engine import vision_runtime as vr

    compacted = vr._compact_repeated_vision_text('**Answer:** * "WIII BLUE 729".\n* Nen xanh.')

    assert compacted == '"WIII BLUE 729". Nen xanh.'


def test_provider_status_autoselects_local_vision_model_for_ollama(monkeypatch):
    from app.engine import vision_runtime as vr

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"models":[{"name":"embeddinggemma:latest"},{"name":"gemma3:4b"},{"name":"qwen3:4b-instruct"}]}'

    monkeypatch.setattr(vr.settings, "ollama_base_url", "http://localhost:11434", raising=False)
    monkeypatch.setattr(vr.settings, "ollama_model", "qwen3:4b-instruct", raising=False)
    monkeypatch.setattr(vr, "urlopen", lambda request, timeout=2.0: _FakeResponse())
    vr.reset_vision_runtime_caches()

    status = vr._provider_status(
        "ollama",
        vr.VisionCapability.VISUAL_DESCRIBE,
    )

    assert status.available is True
    assert status.model_name == "gemma3:4b"


def test_provider_status_autoselect_does_not_upgrade_qwen3b_to_family_stem(monkeypatch):
    from app.engine import vision_runtime as vr

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def read(self):
            return b'{"models":[{"name":"qwen2.5vl:3b"},{"name":"gemma3:4b"}]}'

    monkeypatch.setattr(vr.settings, "ollama_base_url", "http://localhost:11434", raising=False)
    monkeypatch.setattr(vr.settings, "ollama_model", "qwen3:4b-instruct", raising=False)
    monkeypatch.setattr(vr, "urlopen", lambda request, timeout=2.0: _FakeResponse())
    vr.reset_vision_runtime_caches()

    status = vr._provider_status(
        "ollama",
        vr.VisionCapability.VISUAL_DESCRIBE,
    )

    assert status.available is True
    assert status.model_name == "gemma3:4b"


@pytest.mark.asyncio
async def test_run_vision_prompt_returns_image_missing_without_payload():
    from app.engine import vision_runtime as vr

    result = await vr.run_vision_prompt(
        prompt="describe",
        capability=vr.VisionCapability.VISUAL_DESCRIBE,
    )

    assert result.success is False
    assert result.reason_code == "image_missing"


@pytest.mark.asyncio
async def test_run_vision_prompt_google_success(monkeypatch):
    from app.engine import vision_runtime as vr

    async def _mock_google(**kwargs):
        return "Bảng so sánh COLREGs Rule 15"

    monkeypatch.setattr(
        vr,
        "_provider_status",
        lambda provider, capability, model_name=None: vr.VisionProviderStatus(
            provider=provider,
            available=(provider == "google"),
            model_name="gemini-3.1-flash-lite-preview" if provider == "google" else None,
            lane_fit="general" if provider == "google" else None,
            lane_fit_label="General vision" if provider == "google" else None,
        ),
    )
    monkeypatch.setattr(vr, "_run_google_vision_request", _mock_google)
    observation_calls = []
    monkeypatch.setattr(
        vr,
        "_record_vision_runtime_observation",
        lambda **kwargs: observation_calls.append(kwargs),
    )

    result = await vr.run_vision_prompt(
        prompt="describe",
        capability=vr.VisionCapability.VISUAL_DESCRIBE,
        image_base64=_fake_image_b64(),
    )

    assert result.success is True
    assert result.provider == "google"
    assert "COLREGs" in result.text
    assert observation_calls
    assert observation_calls[0]["success"] is True
    assert observation_calls[0]["provider"] == "google"


@pytest.mark.asyncio
async def test_run_zhipu_layout_parsing_wraps_base64_as_data_url(monkeypatch):
    import httpx

    from app.engine import vision_runtime as vr

    captured: dict[str, object] = {}

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"md_results": "# OCR\nRule 15"}

    class _Client:
        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.get("timeout")
            captured["timeout"] = self.timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, endpoint, headers=None, json=None):
            captured["endpoint"] = endpoint
            captured["headers"] = headers
            captured["json"] = json
            return _Response()

    monkeypatch.setattr(vr.settings, "zhipu_api_key", "zhipu-key", raising=False)
    monkeypatch.setattr(
        vr.settings,
        "zhipu_base_url",
        "https://open.bigmodel.cn/api/paas/v4",
        raising=False,
    )
    monkeypatch.setattr(httpx, "AsyncClient", _Client)

    text = await vr._run_zhipu_layout_parsing_request(
        model_name="glm-ocr",
        image_base64="YWJjMTIz",
        media_type="image/png",
        timeout_seconds=30.0,
    )

    assert text == "# OCR\nRule 15"
    assert captured["endpoint"] == "https://open.bigmodel.cn/api/paas/v4/layout_parsing"
    assert captured["json"]["file"] == "data:image/png;base64,YWJjMTIz"
    assert captured["headers"]["Authorization"] == "Bearer zhipu-key"
    assert isinstance(captured["timeout"], httpx.Timeout)
    assert captured["timeout"].connect == 8.0


@pytest.mark.asyncio
async def test_run_vision_prompt_fails_over_to_openai(monkeypatch):
    from app.engine import vision_runtime as vr

    async def _mock_google(**kwargs):
        raise RuntimeError("quota exceeded")

    async def _mock_openai(**kwargs):
        return "Mô tả hình ảnh qua OpenAI"

    def _status(provider, capability, model_name=None):
        if provider == "google":
            return vr.VisionProviderStatus(
                provider=provider,
                available=True,
                model_name="gemini-3.1-flash-lite-preview",
            )
        if provider == "openai":
            return vr.VisionProviderStatus(
                provider=provider,
                available=True,
                model_name="gpt-4.1",
                resolved_base_url="https://api.openai.com/v1",
            )
        return vr.VisionProviderStatus(provider=provider, available=False)

    monkeypatch.setattr(vr, "_provider_status", _status)
    monkeypatch.setattr(vr, "_run_google_vision_request", _mock_google)
    monkeypatch.setattr(vr, "_run_openai_compatible_vision_request", _mock_openai)
    monkeypatch.setattr(vr.settings, "vision_failover_chain", ["google", "openai"], raising=False)
    monkeypatch.setattr(vr.settings, "llm_failover_chain", [], raising=False)

    result = await vr.run_vision_prompt(
        prompt="describe",
        capability=vr.VisionCapability.GROUNDED_VISUAL_ANSWER,
        image_base64=_fake_image_b64(),
    )

    assert result.success is True
    assert result.provider == "openai"
    assert len(result.attempted_providers) >= 2
    assert result.attempted_providers[0]["provider"] == "google"
    assert result.attempted_providers[1]["provider"] == "openai"


@pytest.mark.asyncio
async def test_extract_document_markdown_uses_pil_image(monkeypatch):
    from PIL import Image

    from app.engine import vision_runtime as vr

    mock_run = AsyncMock(
        return_value=vr.VisionResult(
            text="## Điều 15",
            success=True,
            provider="google",
            model_name="gemini-3.1-flash-lite-preview",
        )
    )
    monkeypatch.setattr(vr, "run_vision_prompt", mock_run)

    image = Image.new("RGB", (8, 8), color="white")
    result = await vr.extract_document_markdown(
        image=image,
        prompt="extract",
    )

    assert result.success is True
    assert result.text.startswith("##")
    assert mock_run.await_count == 1
    assert mock_run.await_args.kwargs["image_base64"]


@pytest.mark.asyncio
async def test_run_vision_prompt_uses_zhipu_layout_parsing_for_ocr(monkeypatch):
    from app.engine import vision_runtime as vr

    async def _mock_zhipu_ocr(**kwargs):
        return "# OCR\nRule 15"

    monkeypatch.setattr(
        vr,
        "_provider_status",
        lambda provider, capability, model_name=None: vr.VisionProviderStatus(
            provider=provider,
            available=(provider == "zhipu"),
            model_name="glm-ocr" if provider == "zhipu" else None,
            resolved_base_url="https://api.z.ai/api/paas/v4" if provider == "zhipu" else None,
        ),
    )
    monkeypatch.setattr(vr, "_run_zhipu_layout_parsing_request", _mock_zhipu_ocr)
    monkeypatch.setattr(vr.settings, "vision_failover_chain", ["zhipu", "google"], raising=False)
    monkeypatch.setattr(vr.settings, "llm_failover_chain", [], raising=False)

    result = await vr.run_vision_prompt(
        prompt="extract",
        capability=vr.VisionCapability.OCR_EXTRACT,
        image_base64=_fake_image_b64(),
    )

    assert result.success is True
    assert result.provider == "zhipu"
    assert result.model_name == "glm-ocr"
    assert "Rule 15" in result.text


@pytest.mark.asyncio
async def test_run_vision_prompt_prefers_actionable_timeout_reason(monkeypatch):
    from app.engine import vision_runtime as vr

    async def _mock_ollama(**kwargs):
        raise TimeoutError()

    monkeypatch.setattr(
        vr,
        "_provider_status",
        lambda provider, capability, model_name=None: vr.VisionProviderStatus(
            provider=provider,
            available=(provider == "ollama"),
            model_name="qwen2.5vl:3b" if provider == "ollama" else None,
        ),
    )
    monkeypatch.setattr(vr, "_run_openai_compatible_vision_request", _mock_ollama)
    monkeypatch.setattr(vr.settings, "vision_failover_chain", ["ollama", "google"], raising=False)
    monkeypatch.setattr(vr.settings, "llm_failover_chain", [], raising=False)

    result = await vr.run_vision_prompt(
        prompt="describe",
        capability=vr.VisionCapability.VISUAL_DESCRIBE,
        image_base64=_fake_image_b64(),
        preferred_provider="ollama",
        timeout_seconds=0.01,
    )

    assert result.success is False
    assert result.reason_code == "timeout"
