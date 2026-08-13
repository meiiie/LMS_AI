"""Sprint 222: Verify ALL agent paths include host_context_prompt."""
import pytest
import inspect






def test_answer_generator_accepts_host_context_prompt():
    """answer_generator should have host_context_prompt parameter."""
    from app.engine.agentic_rag.answer_generator import AnswerGenerator
    sig = inspect.signature(AnswerGenerator.generate_response)
    assert "host_context_prompt" in sig.parameters






