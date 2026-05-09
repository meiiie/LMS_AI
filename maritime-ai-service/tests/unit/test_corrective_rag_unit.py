"""
Unit tests for Corrective RAG pipeline components.

Tests CorrectiveRAGResult, confidence logic, and component contracts.
All LLM/DB calls are mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass

from app.engine.agentic_rag.corrective_rag import CorrectiveRAG, CorrectiveRAGResult
from app.engine.agentic_rag.corrective_rag_stream_runtime import process_streaming_impl
from app.engine.reasoning_tracer import StepNames


class TestCorrectiveRAGResult:
    """Test the CorrectiveRAGResult dataclass."""

    def test_basic_creation(self):
        result = CorrectiveRAGResult(
            answer="Rule 15 covers crossing situations.",
            sources=[{"title": "COLREGs", "content": "Rule 15..."}],
        )
        assert result.answer == "Rule 15 covers crossing situations."
        assert len(result.sources) == 1

    def test_default_values(self):
        result = CorrectiveRAGResult(answer="test", sources=[])
        assert result.query_analysis is None
        assert result.grading_result is None
        assert result.verification_result is None
        assert result.was_rewritten is False
        assert result.rewritten_query is None
        assert result.iterations == 1
        assert result.confidence == 80.0  # 0-100 scale (Sprint 83 fix)
        assert result.reasoning_trace is None
        assert result.thinking_content is None
        assert result.thinking is None

    def test_has_warning_no_verification_high_confidence(self):
        # has_warning threshold is confidence < 70 (not 0.7)
        result = CorrectiveRAGResult(answer="test", sources=[], confidence=80)
        assert result.has_warning is False

    def test_has_warning_low_confidence(self):
        result = CorrectiveRAGResult(answer="test", sources=[], confidence=50)
        assert result.has_warning is True

    def test_has_warning_with_verification(self):
        mock_verification = MagicMock()
        mock_verification.needs_warning = True
        result = CorrectiveRAGResult(
            answer="test", sources=[], verification_result=mock_verification
        )
        assert result.has_warning is True

    def test_has_warning_verification_ok(self):
        mock_verification = MagicMock()
        mock_verification.needs_warning = False
        result = CorrectiveRAGResult(
            answer="test", sources=[], verification_result=mock_verification
        )
        assert result.has_warning is False

    def test_rewritten_query_tracking(self):
        result = CorrectiveRAGResult(
            answer="test",
            sources=[],
            was_rewritten=True,
            rewritten_query="maritime COLREGs Rule 15 crossing",
        )
        assert result.was_rewritten is True
        assert "COLREGs" in result.rewritten_query

    def test_multiple_iterations(self):
        result = CorrectiveRAGResult(answer="test", sources=[], iterations=3)
        assert result.iterations == 3

    def test_thinking_content(self):
        result = CorrectiveRAGResult(
            answer="test",
            sources=[],
            thinking="Tôi cần tìm thông tin về Rule 15...",
        )
        assert result.thinking is not None
        assert "Rule 15" in result.thinking

    def test_final_result_drops_sources_when_answer_declines_rag_citations(self):
        from app.engine.agentic_rag.corrective_rag_runtime_support import build_final_result_impl

        result = build_final_result_impl(
            result_cls=CorrectiveRAGResult,
            answer=(
                "Mình chưa thấy nguồn nội bộ thật sự khớp với COLREG trong lượt truy xuất này, "
                "nên mình không gắn citation RAG cho câu trả lời."
            ),
            sources=[{"title": "irrelevant", "document_id": "doc-1"}],
            analysis=None,
            grading_result=None,
            verification_result=None,
            was_rewritten=False,
            rewritten_query=None,
            iterations=1,
            confidence=50,
            reasoning_trace=None,
            thinking_content=None,
            thinking=None,
            evidence_images=[{"url": "https://example.invalid/image.png"}],
        )

        assert result.sources == []
        assert result.evidence_images == []

    def test_final_result_keeps_sources_when_answer_uses_rag_citations(self):
        from app.engine.agentic_rag.corrective_rag_runtime_support import build_final_result_impl

        result = build_final_result_impl(
            result_cls=CorrectiveRAGResult,
            answer="Mình tóm tắt trực tiếp từ nguồn RAG đã tìm được: COLREG Rule 5...",
            sources=[{"title": "COLREG Rule 5", "document_id": "doc-2"}],
            analysis=None,
            grading_result=None,
            verification_result=None,
            was_rewritten=False,
            rewritten_query=None,
            iterations=1,
            confidence=80,
            reasoning_trace=None,
            thinking_content=None,
            thinking=None,
            evidence_images=[{"url": "https://example.invalid/image.png"}],
        )

        assert len(result.sources) == 1
        assert len(result.evidence_images) == 1


class TestConfidenceCalculation:
    """Test confidence scoring patterns used in the platform."""

    def test_confidence_base_with_sources(self):
        """Confidence formula: min(BASE + count * PER_SOURCE, MAX)."""
        from app.core.constants import CONFIDENCE_BASE, CONFIDENCE_PER_SOURCE, CONFIDENCE_MAX

        sources = [{"title": f"doc_{i}"} for i in range(3)]
        score = min(CONFIDENCE_BASE + len(sources) * CONFIDENCE_PER_SOURCE, CONFIDENCE_MAX)
        assert score == pytest.approx(0.8)

    def test_confidence_caps_at_max(self):
        from app.core.constants import CONFIDENCE_BASE, CONFIDENCE_PER_SOURCE, CONFIDENCE_MAX

        sources = [{"title": f"doc_{i}"} for i in range(20)]
        score = min(CONFIDENCE_BASE + len(sources) * CONFIDENCE_PER_SOURCE, CONFIDENCE_MAX)
        assert score == CONFIDENCE_MAX

    def test_confidence_zero_sources(self):
        from app.core.constants import CONFIDENCE_BASE, CONFIDENCE_PER_SOURCE, CONFIDENCE_MAX

        score = min(CONFIDENCE_BASE + 0 * CONFIDENCE_PER_SOURCE, CONFIDENCE_MAX)
        assert score == CONFIDENCE_BASE


class TestContentTruncation:
    """Test that content truncation constants work correctly."""

    def test_snippet_truncation(self):
        from app.core.constants import MAX_CONTENT_SNIPPET_LENGTH

        long_content = "A" * 500
        truncated = long_content[:MAX_CONTENT_SNIPPET_LENGTH]
        assert len(truncated) == MAX_CONTENT_SNIPPET_LENGTH

    def test_document_preview_truncation(self):
        from app.core.constants import MAX_DOCUMENT_PREVIEW_LENGTH

        long_content = "B" * 2000
        truncated = long_content[:MAX_DOCUMENT_PREVIEW_LENGTH]
        assert len(truncated) == MAX_DOCUMENT_PREVIEW_LENGTH

    def test_short_content_not_truncated(self):
        from app.core.constants import MAX_CONTENT_SNIPPET_LENGTH

        short = "Hello world"
        truncated = short[:MAX_CONTENT_SNIPPET_LENGTH]
        assert truncated == short


class TestVisibleCRAGSurface:
    """Regression tests for user-visible CRAG no-doc surfaces."""

    @pytest.mark.asyncio
    async def test_process_streaming_no_docs_uses_generic_surface_text(self):
        mock_settings = MagicMock()
        mock_settings.rag_max_iterations = 1
        mock_settings.rag_confidence_high = 0.8
        mock_settings.enable_answer_verification = False
        mock_settings.semantic_cache_enabled = False
        mock_settings.enable_adaptive_rag = False
        mock_settings.enable_visual_rag = False
        mock_settings.enable_graph_rag = False
        mock_settings.enable_natural_conversation = True
        mock_settings.app_name = "Wiii"

        analyzer = MagicMock()
        analyzer.analyze = AsyncMock(
            return_value=MagicMock(
                complexity=MagicMock(value="simple"),
                is_domain_related=False,
                detected_topics=[],
                requires_multi_step=False,
                confidence=0.9,
            )
        )
        grader = MagicMock()
        grader.grade_documents = AsyncMock(return_value=MagicMock(avg_score=0.0, relevant_count=0))
        rewriter = MagicMock()
        rewriter.rewrite = AsyncMock(return_value=MagicMock(rewritten_query=""))
        verifier = MagicMock()
        tracer = MagicMock()
        tracer.start_step = MagicMock()
        tracer.end_step = MagicMock()
        tracer.build_trace = MagicMock(return_value=MagicMock())
        tracer.build_thinking_summary = MagicMock(return_value="")

        with patch("app.engine.agentic_rag.corrective_rag.settings", mock_settings), \
             patch("app.engine.agentic_rag.corrective_rag.get_query_analyzer", return_value=analyzer), \
             patch("app.engine.agentic_rag.corrective_rag.get_retrieval_grader", return_value=grader), \
             patch("app.engine.agentic_rag.corrective_rag.get_query_rewriter", return_value=rewriter), \
             patch("app.engine.agentic_rag.corrective_rag.get_answer_verifier", return_value=verifier), \
             patch("app.engine.agentic_rag.corrective_rag.get_reasoning_tracer", return_value=tracer):
            crag = CorrectiveRAG(rag_agent=MagicMock())
            crag._cache_enabled = False
            crag._cache = None
            crag._retrieve = AsyncMock(return_value=[])
            crag._generate_fallback = AsyncMock(return_value="")

            events = []
            async for event in crag.process_streaming("có thể uống rượu thưởng trăng không ?", {}):
                events.append(event)

        surface_texts = [str(event.get("content", "")) for event in events if event.get("type") in {"thinking", "answer"}]
        joined = "\n".join(surface_texts)
        assert "Tìm thấy 0 tài liệu liên quan" not in joined
        assert "Xin lỗi, mình chưa có thông tin" not in joined
        assert any("chuyển sang cách đáp trực tiếp" in text.lower() for text in surface_texts)

    @pytest.mark.asyncio
    async def test_process_streaming_accepts_string_rewrite_result(self):
        analyzer = MagicMock()
        analyzer.analyze = AsyncMock(
            return_value=MagicMock(
                complexity=MagicMock(value="moderate"),
                is_domain_related=True,
                detected_topics=["COLREGs"],
                requires_multi_step=False,
                confidence=0.9,
            )
        )

        grading_result = MagicMock(avg_score=1.0, relevant_count=0, feedback="Need better keywords")
        grader = MagicMock()
        grader.grade_documents = AsyncMock(return_value=grading_result)

        rewriter = MagicMock()
        rewriter.rewrite = AsyncMock(return_value="COLREGs Rule 15 crossing situation")

        tracer = MagicMock()
        tracer.start_step = MagicMock()
        tracer.end_step = MagicMock()
        tracer.build_trace = MagicMock(return_value=None)
        tracer.build_thinking_summary = MagicMock(return_value="rewrite summary")

        first_docs = [{"node_id": "doc-old", "title": "Old Doc", "content": "weak result", "document_id": "old", "score": 0.9}]
        rewritten_docs = [{"node_id": "doc-new", "title": "Rule 15", "content": "crossing rule", "document_id": "new", "score": 0.9}]

        async def _stream_answer(**kwargs):
            assert kwargs["question"] == "COLREGs Rule 15 crossing situation"
            yield "Câu trả lời đã sửa."

        owner = MagicMock()
        owner._analyzer = analyzer
        owner._grader = grader
        owner._rewriter = rewriter
        owner._rag = MagicMock()
        owner._rag._generate_response_streaming = _stream_answer
        owner._retrieve = AsyncMock(side_effect=[first_docs, rewritten_docs])
        owner._calculate_confidence = MagicMock(return_value=82.0)
        owner._grade_threshold = 6.0
        owner._retrieval_score_threshold = 0.3

        settings_obj = MagicMock()
        settings_obj.enable_adaptive_rag = False
        settings_obj.enable_visual_rag = False
        settings_obj.enable_graph_rag = False
        settings_obj.rag_model_version = "test-rag"

        events = []
        async for event in process_streaming_impl(
            owner,
            "crossing rule?",
            {"user_role": "student", "conversation_history": ""},
            result_cls=CorrectiveRAGResult,
            get_reasoning_tracer_fn=lambda: tracer,
            settings_obj=settings_obj,
            step_names_cls=StepNames,
            build_retrieval_surface_text_fn=lambda count: f"{count} docs",
            build_house_fallback_reply_fn=lambda: "fallback",
            is_no_doc_retrieval_text_fn=lambda text: False,
            normalize_visible_text_fn=lambda text: str(text),
            max_content_snippet_length=200,
        ):
            events.append(event)

        result_event = next(event for event in events if event["type"] == "result")
        result = result_event["data"]
        assert result.was_rewritten is True
        assert result.rewritten_query == "COLREGs Rule 15 crossing situation"
        assert "Câu trả lời đã sửa." in result.answer

    @pytest.mark.asyncio
    async def test_colreg_rule5_exact_query_uses_fast_regulation_answer(self):
        analyzer = MagicMock()
        analyzer.analyze = AsyncMock(
            return_value=MagicMock(
                complexity=MagicMock(value="simple"),
                is_domain_related=True,
                detected_topics=["COLREGs"],
                requires_multi_step=False,
                confidence=0.9,
            )
        )

        grader = MagicMock()
        grader.grade_documents = AsyncMock(
            side_effect=AssertionError("mismatched docs should be dropped before grading")
        )

        tracer = MagicMock()
        tracer.start_step = MagicMock()
        tracer.end_step = MagicMock()
        tracer.build_trace = MagicMock(return_value=None)
        tracer.build_thinking_summary = MagicMock(return_value="")

        owner = MagicMock()
        owner._analyzer = analyzer
        owner._grader = grader
        owner._rewriter = None
        owner._rag = MagicMock()
        owner._retrieve = AsyncMock(
            return_value=[
                {
                    "node_id": "lms-perf",
                    "title": "3-5 MB",
                    "content": "Nen tang co 295 diem cuoi API va ket qua tai video.",
                    "document_id": "lms",
                    "score": 0.92,
                }
            ]
        )
        owner._generate_fallback = AsyncMock(return_value=("", ""))
        owner._calculate_confidence = MagicMock(return_value=40.0)
        owner._grade_threshold = 6.0
        owner._retrieval_score_threshold = 0.3

        settings_obj = MagicMock()
        settings_obj.enable_adaptive_rag = False
        settings_obj.enable_visual_rag = False
        settings_obj.enable_graph_rag = False
        settings_obj.rag_model_version = "test-rag"

        events = []
        async for event in process_streaming_impl(
            owner,
            "Theo COLREG Rule 5, người trực ca phải duy trì lookout như thế nào?",
            {"user_role": "student", "conversation_history": ""},
            result_cls=CorrectiveRAGResult,
            get_reasoning_tracer_fn=lambda: tracer,
            settings_obj=settings_obj,
            step_names_cls=StepNames,
            build_retrieval_surface_text_fn=lambda count: f"{count} docs",
            build_house_fallback_reply_fn=lambda: "fallback",
            is_no_doc_retrieval_text_fn=lambda text: False,
            normalize_visible_text_fn=lambda text: str(text),
            max_content_snippet_length=200,
        ):
            events.append(event)

        joined = "\n".join(str(event.get("content", "")) for event in events)
        result = next(event["data"] for event in events if event["type"] == "result")

        assert "COLREG Rule 5" in joined
        assert "3-5 MB" not in result.answer
        assert result.sources[0]["title"] == "COLREG 1972 - Rule 5 (Look-out)"
        owner._retrieve.assert_not_awaited()
        grader.grade_documents.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_colreg_rule15_crossing_query_uses_fast_no_internal_source_answer(self):
        grader = MagicMock()
        grader.grade_documents = AsyncMock(
            side_effect=AssertionError("Rule 15 fast path should not grade unrelated docs")
        )

        tracer = MagicMock()
        tracer.start_step = MagicMock()
        tracer.end_step = MagicMock()
        tracer.build_trace = MagicMock(return_value=None)
        tracer.build_thinking_summary = MagicMock(return_value="")

        owner = MagicMock()
        owner._analyzer = MagicMock()
        owner._grader = grader
        owner._rewriter = None
        owner._rag = MagicMock()
        owner._retrieve = AsyncMock(side_effect=AssertionError("Rule 15 fast path should not retrieve"))
        owner._generate_fallback = AsyncMock(return_value=("", ""))
        owner._calculate_confidence = MagicMock(return_value=40.0)
        owner._grade_threshold = 6.0
        owner._retrieval_score_threshold = 0.3

        settings_obj = MagicMock()
        settings_obj.enable_adaptive_rag = False
        settings_obj.enable_visual_rag = False
        settings_obj.enable_graph_rag = False
        settings_obj.rag_model_version = "test-rag"

        events = []
        async for event in process_streaming_impl(
            owner,
            "Giải thích ngắn Quy tắc 15 COLREGs về tình huống tàu cắt hướng",
            {"user_role": "student", "conversation_history": ""},
            result_cls=CorrectiveRAGResult,
            get_reasoning_tracer_fn=lambda: tracer,
            settings_obj=settings_obj,
            step_names_cls=StepNames,
            build_retrieval_surface_text_fn=lambda count: f"{count} docs",
            build_house_fallback_reply_fn=lambda: "fallback",
            is_no_doc_retrieval_text_fn=lambda text: False,
            normalize_visible_text_fn=lambda text: str(text),
            max_content_snippet_length=200,
        ):
            events.append(event)

        joined = "\n".join(str(event.get("content", "")) for event in events)
        result = next(event["data"] for event in events if event["type"] == "result")

        assert "Rule 15" in joined
        assert joined.count("\n- ") >= 4
        assert "citation RAG" in joined
        assert "Rule 13" in joined
        assert "Rule 14" in joined
        assert "mạn phải" in joined
        assert "tránh cắt qua trước mũi" in joined
        assert result.sources == []
        owner._retrieve.assert_not_awaited()
        grader.grade_documents.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_low_score_docs_continue_kb_path_when_web_corrective_missing(self):
        analyzer = MagicMock()
        analyzer.analyze = AsyncMock(
            return_value=MagicMock(
                complexity=MagicMock(value="simple"),
                is_domain_related=True,
                detected_topics=["COLREGs"],
                requires_multi_step=False,
                confidence=0.9,
            )
        )

        grading_result = MagicMock(avg_score=8.0, relevant_count=1, feedback="")
        grader = MagicMock()
        grader.grade_documents = AsyncMock(return_value=grading_result)

        tracer = MagicMock()
        tracer.start_step = MagicMock()
        tracer.end_step = MagicMock()
        tracer.build_trace = MagicMock(return_value=None)
        tracer.build_thinking_summary = MagicMock(return_value="kb summary")

        docs = [
            {
                "node_id": "rule-5",
                "title": "COLREG Rule 5",
                "content": "Every vessel shall maintain a proper look-out by sight and hearing.",
                "document_id": "colregs",
                "score": 0.01,
            }
        ]

        async def _stream_answer(**kwargs):
            assert kwargs["nodes"][0].title == "COLREG Rule 5"
            yield "Rule 5 answer from KB."

        owner = MagicMock()
        owner._analyzer = analyzer
        owner._grader = grader
        owner._rewriter = None
        owner._rag = MagicMock()
        owner._rag._generate_response_streaming = _stream_answer
        owner._retrieve = AsyncMock(return_value=docs)
        owner._calculate_confidence = MagicMock(return_value=82.0)
        owner._grade_threshold = 6.0
        owner._retrieval_score_threshold = 0.3

        settings_obj = MagicMock()
        settings_obj.enable_adaptive_rag = False
        settings_obj.enable_visual_rag = False
        settings_obj.enable_graph_rag = False
        settings_obj.rag_model_version = "test-rag"

        events = []
        with patch.dict("sys.modules", {"app.engine.agentic_rag.crag_web_corrective": None}):
            async for event in process_streaming_impl(
                owner,
                "Theo COLREG, nguồn nội bộ này nói gì?",
                {"user_role": "student", "conversation_history": ""},
                result_cls=CorrectiveRAGResult,
                get_reasoning_tracer_fn=lambda: tracer,
                settings_obj=settings_obj,
                step_names_cls=StepNames,
                build_retrieval_surface_text_fn=lambda count: f"{count} docs",
                build_house_fallback_reply_fn=lambda: "fallback",
                is_no_doc_retrieval_text_fn=lambda text: False,
                normalize_visible_text_fn=lambda text: str(text),
                max_content_snippet_length=200,
            ):
                events.append(event)

        joined = "\n".join(str(event.get("content", "")) for event in events)
        result = next(event["data"] for event in events if event["type"] == "result")
        answer_texts = [
            str(event.get("content", ""))
            for event in events
            if event.get("type") == "answer"
        ]

        assert "Tiếp tục dùng tài liệu nội bộ" in joined
        assert "Chuyển sang cách đáp trực tiếp" not in joined
        assert not any("tài liệu liên quan" in text for text in answer_texts)
        assert result.sources[0]["title"] == "COLREG Rule 5"
        assert "Rule 5 answer from KB." in result.answer
        grader.grade_documents.assert_awaited_once()


class TestVerificationSkipOnEmptySources:
    """Sprint 103: Verification is skipped when 0 sources (fallback answer from LLM).

    When KB is empty, RAG uses _generate_fallback() → sources=[].
    Verifying against 0 sources always gives confidence=50 + warning.
    Fix: skip verification when len(sources) == 0.
    """

    def test_should_verify_false_when_no_sources(self):
        """Verification condition requires len(sources) > 0."""
        from app.core.config import settings

        sources = []
        enable_verification = True
        requires_verification = True
        grading_confidence = 0.3  # LOW — normally would trigger verification
        reflection_is_high = False

        should_verify = (
            enable_verification and
            requires_verification and
            len(sources) > 0 and  # Sprint 103: this blocks verification
            grading_confidence < settings.rag_confidence_medium and
            not reflection_is_high
        )
        assert should_verify is False

    def test_should_verify_true_when_sources_present(self):
        """Verification condition passes when sources exist."""
        from app.core.config import settings

        sources = [{"content": "COLREGs Rule 13..."}]
        enable_verification = True
        requires_verification = True
        grading_confidence = 0.3  # LOW
        reflection_is_high = False

        should_verify = (
            enable_verification and
            requires_verification and
            len(sources) > 0 and
            grading_confidence < settings.rag_confidence_medium and
            not reflection_is_high
        )
        assert should_verify is True

    @pytest.mark.asyncio
    async def test_verifier_always_warns_on_empty_sources(self):
        """Verify that answer_verifier returns warning when sources is empty."""
        from app.engine.agentic_rag.answer_verifier import AnswerVerifier

        with patch("app.engine.agentic_rag.answer_verifier.get_llm_moderate", return_value=MagicMock()):
            verifier = AnswerVerifier()
        result = await verifier.verify("Some LLM answer about MARPOL", [])
        assert result.warning is not None
        assert "thiếu nguồn tham khảo" in result.warning
        assert result.confidence == 50
