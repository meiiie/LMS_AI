"""
Sprint 89 Tests — RAG Agent Persona Fix + Memory Recall (HOMETOWN)

BUG #1: RAG agent persona reset — user_name never passed through chain
BUG #2: Memory recall 58% — hometown overwritten by location (DISTINCT ON)

Tests verify:
1. user_name flows through entire RAG chain
2. _generate_fallback uses identity YAML
3. Memory agent prompt has personality + emoji
4. HOMETOWN FactType exists and is separate from LOCATION
5. Extraction prompt differentiates hometown from location
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# =========================================================================
# TestRAGPersonaFix — Verify user_name flows through chain
# =========================================================================

class TestRAGPersonaFix:
    """BUG #1: Verify user_name + is_follow_up flow through RAG pipeline."""

    def test_answer_generator_accepts_user_name(self):
        """AnswerGenerator.generate_response() accepts user_name param."""
        from app.engine.agentic_rag.answer_generator import AnswerGenerator

        # Verify signature includes user_name and is_follow_up
        import inspect
        sig = inspect.signature(AnswerGenerator.generate_response)
        params = list(sig.parameters.keys())
        assert "user_name" in params, "generate_response must accept user_name"
        assert "is_follow_up" in params, "generate_response must accept is_follow_up"
        assert "conversation_summary" in params
        assert "core_memory_block" in params

    def test_answer_generator_streaming_accepts_user_name(self):
        """AnswerGenerator.generate_response_streaming() accepts user_name param."""
        from app.engine.agentic_rag.answer_generator import AnswerGenerator

        import inspect
        sig = inspect.signature(AnswerGenerator.generate_response_streaming)
        params = list(sig.parameters.keys())
        assert "user_name" in params
        assert "is_follow_up" in params
        assert "conversation_summary" in params
        assert "core_memory_block" in params

    def test_answer_generator_passes_memory_contract_to_build_prompt(self):
        """AnswerGenerator passes user identity and memory inputs to PromptLoader."""
        from app.engine.agentic_rag.answer_generator import AnswerGenerator
        from app.models.knowledge_graph import KnowledgeNode, NodeType

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "Test response"
        mock_llm.invoke.return_value = mock_response

        mock_loader = MagicMock()
        mock_loader.build_system_prompt.return_value = "System prompt"
        mock_loader.get_thinking_instruction.return_value = ""

        nodes = [KnowledgeNode(
            id="test-1", node_type=NodeType.REGULATION,
            title="Test", content="Test content", source="test"
        )]

        # Lazy import: extract_thinking_from_response imported inside function body
        # Patch at source module (app.services.output_processor)
        with patch(
            "app.services.output_processor.extract_thinking_from_response",
            return_value=("answer text", None),
        ):
            AnswerGenerator.generate_response(
                llm=mock_llm,
                prompt_loader=mock_loader,
                question="test?",
                nodes=nodes,
                user_name="Minh",
                is_follow_up=True,
                conversation_summary="User said Wiii should remember the project.",
                core_memory_block="Name: Minh\nGoal: make Wiii stable",
            )

        # Verify build_system_prompt was called with actual user_name
        mock_loader.build_system_prompt.assert_called_once()
        call_kwargs = mock_loader.build_system_prompt.call_args
        assert call_kwargs.kwargs.get("user_name") == "Minh" or \
            (call_kwargs.args and len(call_kwargs.args) > 1 and call_kwargs.args[1] == "Minh") or \
            call_kwargs[1].get("user_name") == "Minh", \
            f"build_system_prompt not called with user_name='Minh': {call_kwargs}"
        assert call_kwargs.kwargs.get("conversation_summary") == (
            "User said Wiii should remember the project."
        )
        assert call_kwargs.kwargs.get("core_memory_block") == (
            "Name: Minh\nGoal: make Wiii stable"
        )

    def test_rag_agent_generate_from_documents_accepts_user_name(self):
        """RAGAgent.generate_from_documents() accepts user_name param."""
        from app.engine.agentic_rag.rag_agent import RAGAgent

        import inspect
        sig = inspect.signature(RAGAgent.generate_from_documents)
        params = list(sig.parameters.keys())
        assert "user_name" in params
        assert "is_follow_up" in params
        assert "conversation_summary" in params
        assert "core_memory_block" in params

    def test_rag_agent_generate_response_accepts_user_name(self):
        """RAGAgent._generate_response() accepts user_name param."""
        from app.engine.agentic_rag.rag_agent import RAGAgent

        import inspect
        sig = inspect.signature(RAGAgent._generate_response)
        params = list(sig.parameters.keys())
        assert "user_name" in params
        assert "is_follow_up" in params
        assert "conversation_summary" in params
        assert "core_memory_block" in params



# =========================================================================
# TestFallbackIdentity — Verify _generate_fallback uses identity YAML
# =========================================================================



# =========================================================================
# TestMemoryAgentIdentity — Verify prompt updated
# =========================================================================

class TestMemoryAgentIdentity:
    """Verify memory agent prompt has personality + emoji.

    Sprint 90: _MEMORY_RESPONSE_PROMPT replaced by _build_memory_response_prompt().
    Tests now call the builder function instead of importing the old constant.
    """

    def test_memory_prompt_has_emoji(self):
        """Built memory prompt includes emoji."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        prompt = _build_memory_response_prompt()
        assert "emoji" in prompt.lower() or "⚓" in prompt

    def test_memory_prompt_has_dang_yeu(self):
        """Built memory prompt includes 'đáng yêu' personality."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        prompt = _build_memory_response_prompt()
        assert "đáng yêu" in prompt.lower()

    def test_memory_prompt_is_wiii(self):
        """Built memory prompt identifies as Wiii."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        prompt = _build_memory_response_prompt()
        assert "Wiii" in prompt

    def test_memory_prompt_no_greeting(self):
        """Built memory prompt tells not to start with greeting."""
        from app.engine.multi_agent.agents.memory_agent import _build_memory_response_prompt
        prompt = _build_memory_response_prompt()
        assert "KHÔNG bắt đầu bằng" in prompt


# =========================================================================
# TestHometownFactType — Verify HOMETOWN type added correctly
# =========================================================================

class TestHometownFactType:
    """BUG #2: Verify HOMETOWN FactType separates quê quán from location."""

    def test_hometown_in_fact_type_enum(self):
        """HOMETOWN exists in FactType enum."""
        from app.models.semantic_memory import FactType
        assert hasattr(FactType, "HOMETOWN")
        assert FactType.HOMETOWN.value == "hometown"

    def test_hometown_in_allowed_types(self):
        """'hometown' is in ALLOWED_FACT_TYPES."""
        from app.models.semantic_memory import ALLOWED_FACT_TYPES
        assert "hometown" in ALLOWED_FACT_TYPES

    def test_hometown_in_identity_decay(self):
        """'hometown' is in IDENTITY_FACT_TYPES (never decays)."""
        from app.models.semantic_memory import IDENTITY_FACT_TYPES
        assert "hometown" in IDENTITY_FACT_TYPES

    def test_hometown_not_in_professional(self):
        """'hometown' is NOT in PROFESSIONAL_FACT_TYPES."""
        from app.models.semantic_memory import PROFESSIONAL_FACT_TYPES
        assert "hometown" not in PROFESSIONAL_FACT_TYPES

    def test_location_still_in_professional(self):
        """'location' is still in PROFESSIONAL_FACT_TYPES."""
        from app.models.semantic_memory import PROFESSIONAL_FACT_TYPES
        assert "location" in PROFESSIONAL_FACT_TYPES

    def test_hometown_predicate_exists(self):
        """Predicate.HAS_HOMETOWN exists."""
        from app.models.semantic_memory import Predicate
        assert hasattr(Predicate, "HAS_HOMETOWN")
        assert Predicate.HAS_HOMETOWN.value == "has_hometown"

    def test_hometown_in_fact_type_to_predicate(self):
        """'hometown' maps to HAS_HOMETOWN in FACT_TYPE_TO_PREDICATE."""
        from app.models.semantic_memory import FACT_TYPE_TO_PREDICATE, Predicate
        assert "hometown" in FACT_TYPE_TO_PREDICATE
        assert FACT_TYPE_TO_PREDICATE["hometown"] == Predicate.HAS_HOMETOWN

    def test_hometown_predicate_is_identity(self):
        """HAS_HOMETOWN maps to 'identity' in PREDICATE_TO_OBJECT_TYPE."""
        from app.models.semantic_memory import PREDICATE_TO_OBJECT_TYPE, Predicate
        assert Predicate.HAS_HOMETOWN in PREDICATE_TO_OBJECT_TYPE
        assert PREDICATE_TO_OBJECT_TYPE[Predicate.HAS_HOMETOWN] == "identity"

    def test_hometown_in_triple_fact_type_map(self):
        """SemanticTriple.to_metadata() maps HAS_HOMETOWN to 'hometown'."""
        from app.models.semantic_memory import SemanticTriple, Predicate
        triple = SemanticTriple(
            subject="user_123",
            predicate=Predicate.HAS_HOMETOWN,
            object="Hải Phòng",
        )
        meta = triple.to_metadata()
        assert meta["fact_type"] == "hometown"

    def test_extraction_prompt_has_hometown(self):
        """Extraction prompt includes 'hometown' in fact_type list."""
        from app.engine.semantic_memory.extraction import FactExtractor

        extractor = FactExtractor(
            embeddings=MagicMock(),
            repository=MagicMock(),
        )
        prompt = extractor._build_enhanced_prompt("test message")
        assert "hometown" in prompt

    def test_extraction_prompt_differentiates_hometown_from_location(self):
        """Extraction prompt clearly separates hometown (quê) from location (nơi ở)."""
        from app.engine.semantic_memory.extraction import FactExtractor

        extractor = FactExtractor(
            embeddings=MagicMock(),
            repository=MagicMock(),
        )
        prompt = extractor._build_enhanced_prompt("test message")
        # Should have hometown with quê quán description
        assert "hometown" in prompt
        assert "quê quán" in prompt or "cố định" in prompt
        # Should have location with nơi ở/HIỆN TẠI description
        assert "HIỆN TẠI" in prompt or "nơi ở" in prompt

    def test_extraction_example_hometown_vs_location(self):
        """Extraction prompt examples show hometown vs location split."""
        from app.engine.semantic_memory.extraction import FactExtractor

        extractor = FactExtractor(
            embeddings=MagicMock(),
            repository=MagicMock(),
        )
        prompt = extractor._build_enhanced_prompt("test message")
        # Should have example: "quê Hải Phòng" → hometown:Hải Phòng
        assert "hometown:Hải Phòng" in prompt

    def test_user_fact_hometown_creates_correctly(self):
        """UserFact with HOMETOWN fact_type creates without error."""
        from app.models.semantic_memory import UserFact, FactType
        fact = UserFact(
            fact_type=FactType.HOMETOWN,
            value="Hải Phòng",
            confidence=0.95,
        )
        assert fact.fact_type == FactType.HOMETOWN
        assert fact.to_content() == "hometown: Hải Phòng"

    def test_hometown_and_location_are_separate_types(self):
        """HOMETOWN and LOCATION are distinct enum values."""
        from app.models.semantic_memory import FactType
        assert FactType.HOMETOWN != FactType.LOCATION
        assert FactType.HOMETOWN.value == "hometown"
        assert FactType.LOCATION.value == "location"


# =========================================================================
# TestFactExtractorValidation — Verify hometown is accepted by validator
# =========================================================================

class TestFactExtractorValidation:
    """Verify FactExtractor._validate_fact_type() accepts 'hometown'."""

    def test_validate_hometown(self):
        """_validate_fact_type('hometown') returns 'hometown'."""
        from app.engine.semantic_memory.extraction import FactExtractor

        extractor = FactExtractor(
            embeddings=MagicMock(),
            repository=MagicMock(),
        )
        assert extractor._validate_fact_type("hometown") == "hometown"

    def test_validate_location_still_works(self):
        """_validate_fact_type('location') still returns 'location'."""
        from app.engine.semantic_memory.extraction import FactExtractor

        extractor = FactExtractor(
            embeddings=MagicMock(),
            repository=MagicMock(),
        )
        assert extractor._validate_fact_type("location") == "location"
