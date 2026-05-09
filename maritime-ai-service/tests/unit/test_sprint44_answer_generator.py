"""
Tests for Sprint 44: AnswerGenerator coverage.

Tests LLM-based answer generation including:
- generate_response with/without nodes
- generate_response with/without LLM
- extract_content_from_chunk (streaming)
- Helper functions (_get_role_rules, _build_user_prompt)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


class TestExtractiveStreamingFallback:
    """Regression tests for source-safe extractive fallback."""

    def _make_node(self, title: str, content: str):
        node = MagicMock()
        node.title = title
        node.content = content
        return node

    def test_colreg_query_does_not_cite_irrelevant_rag_sources(self):
        from app.engine.agentic_rag.answer_generator import _build_extractive_streaming_fallback

        answer = _build_extractive_streaming_fallback(
            "COLREG là gì? Trả lời 2 câu, nêu nguồn nếu có.",
            [
                self._make_node(
                    "Thiết kế giao diện LMS hàng hải",
                    "Tài liệu này mô tả quy trình soạn thảo khóa học và kiểm thử tải.",
                )
            ],
            ["- Thiết kế giao diện LMS hàng hải (doc-1)"],
        )

        assert "COLREG" in answer
        assert "Quy tắc quốc tế phòng ngừa đâm va" in answer
        assert "Nguồn tham khảo" not in answer
        assert "Thiết kế giao diện" not in answer

    def test_relevant_colreg_source_is_still_cited(self):
        from app.engine.agentic_rag.answer_generator import _build_extractive_streaming_fallback

        answer = _build_extractive_streaming_fallback(
            "COLREG Rule 5 nói gì?",
            [
                self._make_node(
                    "COLREG Rule 5",
                    "COLREG Rule 5 requires every vessel to maintain a proper look-out by sight and hearing.",
                )
            ],
            ["- COLREG Rule 5 (doc-2)"],
        )

        assert "Mình tóm tắt trực tiếp" in answer
        assert "proper look-out" in answer
        assert "COLREG Rule 5 (doc-2)" in answer

    def test_colreg_rule15_fallback_is_specific_without_fake_citation(self):
        from app.engine.agentic_rag.answer_generator import _build_extractive_streaming_fallback

        answer = _build_extractive_streaming_fallback(
            "Giải thích ngắn Quy tắc 15 COLREGs về tình huống tàu cắt hướng",
            [],
            [],
        )

        assert "Rule 15" in answer
        assert "mạn phải" in answer
        assert "tránh cắt qua trước mũi" in answer
        assert "Nguồn tham khảo" not in answer


# ============================================================================
# generate_response - no nodes
# ============================================================================


class TestGenerateResponseNoNodes:
    """Test generate_response when no nodes are provided."""

    def test_no_nodes_returns_fallback(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        answer, thinking = AnswerGenerator.generate_response(
            llm=MagicMock(),
            prompt_loader=MagicMock(),
            question="What is Rule 15?",
            nodes=[]
        )
        assert "couldn't find" in answer.lower()
        assert thinking is None

    def test_empty_nodes_list(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        answer, thinking = AnswerGenerator.generate_response(
            llm=MagicMock(),
            prompt_loader=MagicMock(),
            question="Test",
            nodes=[]
        )
        assert thinking is None


# ============================================================================
# generate_response - no LLM
# ============================================================================


class TestGenerateResponseNoLLM:
    """Test generate_response when no LLM is available."""

    def _make_node(self, title="Rule 15", content="Crossing situation", source="COLREGs"):
        node = MagicMock()
        node.title = title
        node.content = content
        node.source = source
        return node

    def test_no_llm_returns_raw_context(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        nodes = [self._make_node()]
        answer, thinking = AnswerGenerator.generate_response(
            llm=None,
            prompt_loader=MagicMock(),
            question="What is Rule 15?",
            nodes=nodes
        )
        assert "Rule 15" in answer
        assert "Crossing situation" in answer
        assert thinking is None

    def test_no_llm_includes_sources(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        nodes = [self._make_node()]
        answer, _ = AnswerGenerator.generate_response(
            llm=None,
            prompt_loader=MagicMock(),
            question="Test",
            nodes=nodes
        )
        assert "COLREGs" in answer

    def test_no_llm_includes_entity_context(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        nodes = [self._make_node()]
        answer, _ = AnswerGenerator.generate_response(
            llm=None,
            prompt_loader=MagicMock(),
            question="Test",
            nodes=nodes,
            entity_context="Related to SOLAS Chapter II"
        )
        assert "SOLAS" in answer

    def test_no_llm_no_source(self):
        """Node with no source doesn't add source line."""
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        node = self._make_node(source=None)
        answer, _ = AnswerGenerator.generate_response(
            llm=None,
            prompt_loader=MagicMock(),
            question="Test",
            nodes=[node]
        )
        assert "tham kh" not in answer.lower()


# ============================================================================
# generate_response - with LLM
# ============================================================================


class TestGenerateResponseWithLLM:
    """Test generate_response with mocked LLM."""

    def _make_node(self, title="Rule 15", content="Crossing situation", source="COLREGs"):
        node = MagicMock()
        node.title = title
        node.content = content
        node.source = source
        return node

    def test_llm_generates_response(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="LLM generated answer about Rule 15")

        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "System prompt"
        mock_loader.get_thinking_instruction.return_value = "Think step by step"

        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=("LLM generated answer about Rule 15", None)):
            answer, thinking = AnswerGenerator.generate_response(
                llm=mock_llm,
                prompt_loader=mock_loader,
                question="What is Rule 15?",
                nodes=[self._make_node()]
            )
            assert "Rule 15" in answer
            assert thinking is None

    def test_llm_with_native_thinking(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="content")

        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "System"
        mock_loader.get_thinking_instruction.return_value = "Think"

        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=("Answer text", "Native thinking content")):
            answer, thinking = AnswerGenerator.generate_response(
                llm=mock_llm,
                prompt_loader=mock_loader,
                question="Test",
                nodes=[self._make_node()]
            )
            assert thinking == "Native thinking content"

    def test_llm_failure_returns_raw(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator

        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = Exception("LLM error")

        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "System"
        mock_loader.get_thinking_instruction.return_value = "Think"

        answer, thinking = AnswerGenerator.generate_response(
            llm=mock_llm,
            prompt_loader=mock_loader,
            question="Test",
            nodes=[self._make_node()]
        )
        # Falls back to raw content
        assert "Rule 15" in answer or "Crossing" in answer
        assert thinking is None

    def test_student_vs_teacher_role(self):
        """Different roles produce different prompts."""
        from app.engine.agentic_rag.answer_generator import AnswerGenerator

        mock_llm = MagicMock()
        mock_llm.invoke.return_value = MagicMock(content="Answer")

        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "System"
        mock_loader.get_thinking_instruction.return_value = "Think"

        with patch("app.services.output_processor.extract_thinking_from_response",
                    return_value=("Answer", None)):
            # Student
            AnswerGenerator.generate_response(
                llm=mock_llm, prompt_loader=mock_loader,
                question="Test", nodes=[self._make_node()],
                user_role="student"
            )
            student_call = mock_llm.invoke.call_args[0][0]

            # Teacher
            AnswerGenerator.generate_response(
                llm=mock_llm, prompt_loader=mock_loader,
                question="Test", nodes=[self._make_node()],
                user_role="teacher"
            )
            teacher_call = mock_llm.invoke.call_args[0][0]

            # System prompts should differ
            assert student_call[0].content != teacher_call[0].content or \
                   len(student_call[0].content) != len(teacher_call[0].content)


# ============================================================================
# extract_content_from_chunk
# ============================================================================


class TestExtractContentFromChunk:
    """Test streaming chunk content extraction."""

    def test_string_chunk(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        assert AnswerGenerator.extract_content_from_chunk("hello") == "hello"

    def test_chunk_with_string_content(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        chunk = MagicMock()
        chunk.content = "token text"
        assert AnswerGenerator.extract_content_from_chunk(chunk) == "token text"

    def test_chunk_with_list_content(self):
        """Gemini thinking mode returns list of blocks."""
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        chunk = MagicMock()
        chunk.content = [
            {"type": "thinking", "thinking": "internal thought"},
            {"type": "text", "text": "visible answer"},
        ]
        result = AnswerGenerator.extract_content_from_chunk(chunk)
        assert "visible answer" in result
        assert "internal thought" not in result

    def test_chunk_with_string_blocks(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        chunk = MagicMock()
        chunk.content = ["part1", "part2"]
        result = AnswerGenerator.extract_content_from_chunk(chunk)
        assert "part1" in result
        assert "part2" in result

    def test_chunk_no_content_attr(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        chunk = 42  # No content attribute
        assert AnswerGenerator.extract_content_from_chunk(chunk) == ""

    def test_chunk_empty_list(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        chunk = MagicMock()
        chunk.content = []
        assert AnswerGenerator.extract_content_from_chunk(chunk) == ""


# ============================================================================
# Helper functions
# ============================================================================


class TestHelperFunctions:
    """Test private helper functions."""

    def test_get_role_rules_student(self):
        from app.engine.agentic_rag.answer_generator import _get_role_rules
        rules = _get_role_rules("student")
        assert "VARIATION" in rules
        assert "starboard" in rules

    def test_get_role_rules_teacher(self):
        from app.engine.agentic_rag.answer_generator import _get_role_rules
        rules = _get_role_rules("teacher")
        assert "chuy\u00ean nghi\u1ec7p" in rules.lower() or "VARIATION" not in rules

    def test_get_role_rules_admin(self):
        from app.engine.agentic_rag.answer_generator import _get_role_rules
        rules = _get_role_rules("admin")
        # Admin uses same as teacher
        assert "VARIATION" not in rules

    def test_build_user_prompt_basic(self):
        from app.engine.agentic_rag.answer_generator import _build_user_prompt
        prompt = _build_user_prompt("context text", "What is Rule 15?")
        assert "context text" in prompt
        assert "Rule 15" in prompt

    def test_build_user_prompt_with_history(self):
        from app.engine.agentic_rag.answer_generator import _build_user_prompt
        prompt = _build_user_prompt("context", "question", conversation_history="User asked about SOLAS")
        assert "SOLAS" in prompt

    def test_build_user_prompt_with_entity_context(self):
        from app.engine.agentic_rag.answer_generator import _build_user_prompt
        prompt = _build_user_prompt("context", "question", entity_context="Related entities: COLREG Rule 15")
        assert "COLREG" in prompt
        assert "GraphRAG" in prompt

    def test_streaming_rules_student(self):
        from app.engine.agentic_rag.answer_generator import _get_streaming_student_rules
        rules = _get_streaming_student_rules()
        assert len(rules) > 0

    def test_streaming_rules_other(self):
        from app.engine.agentic_rag.answer_generator import _get_streaming_other_rules
        rules = _get_streaming_other_rules()
        assert len(rules) > 0


# ============================================================================
# Streaming generation
# ============================================================================


class TestStreamingGeneration:
    """Test generate_response_streaming."""

    def _make_node(self, title="Rule 15", content="Crossing", source="COLREGs"):
        node = MagicMock()
        node.title = title
        node.content = content
        node.source = source
        return node

    @pytest.mark.asyncio
    async def test_no_nodes_yields_fallback(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        chunks = []
        async for chunk in AnswerGenerator.generate_response_streaming(
            llm=MagicMock(),
            prompt_loader=MagicMock(),
            question="Test",
            nodes=[]
        ):
            chunks.append(chunk)
        assert len(chunks) == 1
        assert "th\u00f4ng tin" in chunks[0].lower() or "kh\u00f4ng" in chunks[0].lower()

    @pytest.mark.asyncio
    async def test_no_llm_yields_raw(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        chunks = []
        async for chunk in AnswerGenerator.generate_response_streaming(
            llm=None,
            prompt_loader=MagicMock(),
            question="Test",
            nodes=[self._make_node()]
        ):
            chunks.append(chunk)
        assert any("Rule 15" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_streaming_uses_buffered_failover_when_native_stream_dies(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator

        class FakeLLM:
            async def astream(self, _messages):
                raise RuntimeError("403 PERMISSION_DENIED")
                yield  # pragma: no cover

        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "System"
        mock_loader.get_thinking_instruction.return_value = "Think"

        recovered = MagicMock(content="Recovered answer from fallback")
        chunks = []
        with patch(
            "app.engine.agentic_rag.answer_generator.ainvoke_agentic_rag_llm",
            AsyncMock(return_value=recovered),
        ), patch(
            "app.services.output_processor.extract_thinking_from_response",
            return_value=("Recovered answer from fallback", None),
        ):
            async for chunk in AnswerGenerator.generate_response_streaming(
                llm=FakeLLM(),
                prompt_loader=mock_loader,
                question="What is Rule 16?",
                nodes=[self._make_node(title="Rule 16", content="Take early and substantial action")],
            ):
                chunks.append(chunk)

        combined = "".join(chunks)
        assert "Recovered answer from fallback" in combined
        assert "Internal processing error" not in combined

    @pytest.mark.asyncio
    async def test_streaming_llm_failure_yields_source_backed_fallback(self):
        from app.engine.agentic_rag.answer_generator import AnswerGenerator

        class FakeLLM:
            async def astream(self, _messages):
                raise RuntimeError("provider exploded")
                yield  # pragma: no cover

        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "System"
        mock_loader.get_thinking_instruction.return_value = "Think"

        chunks = []
        async for chunk in AnswerGenerator.generate_response_streaming(
            llm=FakeLLM(),
            prompt_loader=mock_loader,
            question="What is Rule 5?",
            nodes=[
                self._make_node(
                    title="COLREG Rule 5",
                    content="Every vessel shall maintain a proper look-out by sight and hearing.",
                )
            ],
        ):
            chunks.append(chunk)

        combined = "".join(chunks)
        assert "Internal processing error" not in combined
        assert "model tổng hợp" not in combined
        assert "COLREG Rule 5" in combined
        assert "proper look-out" in combined
