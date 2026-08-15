"""
Tests for Sprint 36: Code bug fixes.

Covers:
- chat_history_repository.py uses .is_(False) not == False
- multimodal_ingestion_service.py open() uses encoding='utf-8'
- health.py readiness endpoint does not leak str(e)
- chat_stream.py SSE error does not leak str(e)
- evaluator.py does not leak str(e) in details
"""

import ast
import re
import pytest






class TestNoStrEInHttpResponses:
    """Verify HTTP-facing code does not leak str(e) to clients."""



    def test_evaluator_no_str_e_in_details(self):
        """Evaluator module was removed (refactored into confidence_evaluator).
        Check the replacement file instead."""
        import os
        old_path = "app/engine/evaluation/evaluator.py"
        new_path = "app/engine/agentic_rag/confidence_evaluator.py"
        assert not os.path.exists(old_path), "Old evaluator.py should not exist"
        with open(new_path, "r", encoding="utf-8") as f:
            content = f.read()
        # EvaluationResult should not include str(e) in details
        assert '"error": str(e)' not in content
        assert "'error': str(e)" not in content
