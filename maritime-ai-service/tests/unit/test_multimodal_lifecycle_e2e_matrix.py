from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.engine.semantic_memory.visual_memory import (
    ImageMemoryEntry,
    VisualConceptType,
    VisualMemoryContext,
)
from app.engine.vision_extractor import VisionExtractor
from app.engine.vision_runtime import VisionCapability, VisionProviderStatus, VisionResult
from app.services.input_processor import ChatContext
from app.services.input_processor_context_runtime import build_context_impl


def _fake_image_b64() -> str:
    return base64.b64encode(b"fake-image-bytes").decode("utf-8")


OCR_RUNTIME_CASES = [
    {
        "id": "ocr_specialist_success",
        "zhipu_side_effect": "# Rule 15\n| Cot | Gia tri |\n| --- | --- |\n| A | B |",
        "ollama_side_effect": "# Fallback should not run",
        "expected_provider": "zhipu",
        "expected_attempts": ["zhipu"],
    },
    {
        "id": "ocr_fallback_success",
        "zhipu_side_effect": TimeoutError(),
        "ollama_side_effect": "# Rule 15\n| Cot | Gia tri |\n| --- | --- |\n| A | B |",
        "expected_provider": "ollama",
        "expected_attempts": ["zhipu", "ollama"],
    },
]


@pytest.mark.asyncio
@pytest.mark.parametrize("case", OCR_RUNTIME_CASES, ids=[case["id"] for case in OCR_RUNTIME_CASES])
async def test_ocr_runtime_lifecycle_matrix(case, monkeypatch):
    from app.engine import vision_runtime as vr

    def _status(provider: str, capability: VisionCapability, model_name: str | None = None):
        if provider == "zhipu":
            return VisionProviderStatus(
                provider="zhipu",
                available=True,
                model_name="glm-ocr",
                lane_fit="specialist",
                lane_fit_label="OCR specialist",
                resolved_base_url="https://api.z.ai/api/paas/v4",
            )
        if provider == "ollama":
            return VisionProviderStatus(
                provider="ollama",
                available=True,
                model_name="gemma3:4b",
                lane_fit="fallback",
                lane_fit_label="OCR fallback",
                resolved_base_url="http://localhost:11434",
            )
        return VisionProviderStatus(provider=provider, available=False)

    async def _mock_zhipu(**_kwargs):
        payload = case["zhipu_side_effect"]
        if isinstance(payload, Exception):
            raise payload
        return payload

    async def _mock_openai_compatible(**_kwargs):
        payload = case["ollama_side_effect"]
        if isinstance(payload, Exception):
            raise payload
        return payload

    monkeypatch.setattr(vr, "_provider_status", _status)
    monkeypatch.setattr(vr, "_run_zhipu_layout_parsing_request", _mock_zhipu)
    monkeypatch.setattr(vr, "_run_openai_compatible_vision_request", _mock_openai_compatible)
    monkeypatch.setattr(vr.settings, "vision_failover_chain", ["zhipu", "ollama"], raising=False)
    monkeypatch.setattr(vr.settings, "llm_failover_chain", [], raising=False)
    monkeypatch.setattr(vr, "_record_vision_runtime_observation", lambda **_kwargs: None)

    result = await vr.extract_document_markdown(
        image_base64=_fake_image_b64(),
        prompt="extract",
    )

    assert result.success is True
    assert result.provider == case["expected_provider"]
    assert [attempt["provider"] for attempt in result.attempted_providers] == case["expected_attempts"]
    if case["expected_provider"] == "ollama":
        assert result.attempted_providers[0]["reason_code"] == "timeout"


@pytest.mark.asyncio
async def test_vision_extractor_runtime_surface_matrix():
    image = Image.new("RGB", (8, 8), color="white")
    runtime_result = VisionResult(
        text="## Rule 15\n| Cot | Gia tri |\n| --- | --- |\n| A | B |\n",
        success=True,
        provider="zhipu",
        model_name="glm-ocr",
        capability=VisionCapability.OCR_EXTRACT,
    )

    with patch(
        "app.engine.vision_extractor.extract_document_markdown",
        new=AsyncMock(return_value=runtime_result),
    ) as mock_extract:
        extractor = VisionExtractor()
        result = await extractor.extract_from_image(image)

    assert result.success is True
    assert result.has_tables is True
    assert "Rule 15" in result.headings_found
    mock_extract.assert_awaited_once()


@pytest.mark.asyncio
async def test_visual_rag_enrichment_lifecycle_matrix():
    from app.engine.agentic_rag.visual_rag import enrich_documents_with_visual_context

    docs = [
        {
            "node_id": "visual-1",
            "content": "Noi dung bang goc",
            "title": "Rule 15 table",
            "score": 0.9,
            "image_url": "https://example.com/rule15-table.jpg",
            "page_number": 3,
            "document_id": "doc-rule15",
            "content_type": "table",
            "bounding_boxes": [{"x": 0.1, "y": 0.2}],
        },
        {
            "node_id": "plain-1",
            "content": "Doan van ban thuong",
            "title": "Rule 15 prose",
            "score": 0.7,
            "image_url": None,
            "page_number": 4,
            "document_id": "doc-rule15",
            "content_type": "text",
        },
    ]

    with patch(
        "app.engine.agentic_rag.visual_rag._fetch_image_as_base64",
        new=AsyncMock(return_value=_fake_image_b64()),
    ), patch(
        "app.engine.agentic_rag.visual_rag._analyze_image_with_vision",
        new=AsyncMock(return_value="Bang nay cho thay tau o man phai phai nhuong duong."),
    ):
        result = await enrich_documents_with_visual_context(
            docs,
            "Quy tac 15 COLREGs la gi?",
        )

    assert result.total_images_analyzed == 1
    assert result.enriched_documents[0]["visual_description"].startswith("Bang nay")
    assert "[Mô tả hình ảnh trang 3]" in result.enriched_documents[0]["content"]
    assert result.enriched_documents[1]["content"] == "Doan van ban thuong"


@pytest.mark.asyncio
async def test_input_processor_visual_memory_lifecycle_matrix():
    request = SimpleNamespace(
        user_id="student-visual",
        message="Ban con nho hinh radar hom truoc khong?",
        role="student",
        user_context=None,
        images=[
            SimpleNamespace(
                type="base64",
                data=_fake_image_b64(),
                media_type="image/png",
            )
        ],
    )
    settings_obj = SimpleNamespace(
        enable_cross_platform_memory=False,
        enable_visual_memory=True,
        visual_memory_context_max_items=3,
        enable_vision=True,
        enable_emotional_state=False,
    )
    logger_obj = MagicMock()
    visual_entry = ImageMemoryEntry(
        user_id="student-visual",
        image_hash="hash-radar",
        description="Bang radar va vi tri tau trong tinh huong cat huong.",
        concept_type=VisualConceptType.TABLE,
    )
    visual_context = VisualMemoryContext(
        entries=[visual_entry],
        context_text="=== Tri nho hinh anh ===\n1. [table]: Bang radar va vi tri tau trong tinh huong cat huong.",
    )
    vm = MagicMock()
    vm.retrieve_visual_memories = AsyncMock(return_value=visual_context)
    vm.store_image_memory = AsyncMock(return_value=None)
    scheduled: list[object] = []

    def _fake_create_task(coro):
        scheduled.append(coro)
        coro.close()
        return MagicMock()

    with patch(
        "app.engine.semantic_memory.visual_memory.get_visual_memory_manager",
        return_value=vm,
    ), patch(
        "app.services.input_processor_context_runtime._apply_budgeted_history",
        new=AsyncMock(return_value=None),
    ), patch(
        "app.services.input_processor_context_runtime.asyncio.create_task",
        side_effect=_fake_create_task,
    ):
        context = await build_context_impl(
            request=request,
            session_id="session-visual",
            user_name=None,
            recent_history_fallback=None,
            chat_context_cls=ChatContext,
            semantic_memory=None,
            chat_history=None,
            learning_graph=None,
            memory_summarizer=None,
            conversation_analyzer=None,
            settings_obj=settings_obj,
            logger_obj=logger_obj,
        )

    assert "Tri nho hinh anh" in context.semantic_context
    assert context.images == request.images
    vm.retrieve_visual_memories.assert_awaited_once()
    assert vm.store_image_memory.call_count == 1
    assert len(scheduled) == 1


@pytest.mark.asyncio
async def test_input_processor_marks_image_input_when_vision_disabled():
    request = SimpleNamespace(
        user_id="student-visual-disabled",
        message="Nhin anh nay giup minh",
        role="student",
        user_context=None,
        images=[
            SimpleNamespace(
                type="base64",
                data=_fake_image_b64(),
                media_type="image/png",
            )
        ],
    )
    settings_obj = SimpleNamespace(
        enable_cross_platform_memory=False,
        enable_visual_memory=True,
        visual_memory_context_max_items=3,
        enable_vision=False,
        enable_emotional_state=False,
    )

    with patch(
        "app.services.input_processor_context_runtime._apply_budgeted_history",
        new=AsyncMock(return_value=None),
    ):
        context = await build_context_impl(
            request=request,
            session_id="session-visual-disabled",
            user_name=None,
            recent_history_fallback=None,
            chat_context_cls=ChatContext,
            semantic_memory=None,
            chat_history=None,
            learning_graph=None,
            memory_summarizer=None,
            conversation_analyzer=None,
            settings_obj=settings_obj,
            logger_obj=MagicMock(),
        )

    assert context.images is None
    assert context.image_input_error == "vision_disabled"
    assert "enable_vision dang tat" in context.semantic_context
