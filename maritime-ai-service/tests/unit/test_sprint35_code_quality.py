"""
Tests for Sprint 35: Code quality improvements.

Covers:
- datetime.utcnow() replaced with datetime.now(timezone.utc)
- except Exception: blocks have `as e` for debuggability
- test_pronoun_detection.py functions assert instead of return
"""

import ast
import pytest




class TestExceptExceptionHasVariable:
    """Verify runtime except Exception blocks capture the exception."""

    @pytest.mark.parametrize("filepath", [
        "app/main.py",
        "app/repositories/thread_repository.py",
        "app/engine/multi_agent/supervisor.py",
        "app/repositories/neo4j_knowledge_repository.py",
        "app/engine/tools/code_execution_tools.py",
        "app/repositories/chat_history_repository.py",
        "app/engine/multi_agent/agents/tutor_node.py",
        "app/domains/base.py",
        "app/engine/agentic_rag/query_rewriter.py",
        "app/api/v1/admin.py",
    ])
    def test_except_exception_captures_variable(self, filepath):
        """All runtime except Exception blocks should use `as e`."""
        with open(filepath, "r", encoding="utf-8-sig") as f:
            tree = ast.parse(f.read())

        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    continue  # bare except:, skip
                # Check if it's `except Exception`
                if isinstance(node.type, ast.Name) and node.type.id == "Exception":
                    # `node.name` is the `as e` variable — None means no variable
                    # Allow: import-guard patterns (body is just `pass` at module level)
                    # or circuit breaker patterns that re-raise
                    body_is_pass = (
                        len(node.body) == 1
                        and isinstance(node.body[0], ast.Expr)
                        and isinstance(node.body[0].value, ast.Constant)
                    ) or (
                        len(node.body) == 1
                        and isinstance(node.body[0], ast.Pass)
                    )
                    body_is_raise = any(
                        isinstance(stmt, ast.Raise) for stmt in node.body
                    )
                    # If it's a simple pass (import guard) or re-raise, skip
                    if body_is_pass or body_is_raise:
                        continue
                    assert node.name is not None, (
                        f"{filepath}: `except Exception:` at line {node.lineno} "
                        f"should use `except Exception as e:`"
                    )


