"""
Unit test conftest — shared fixtures for all unit tests.

Sprint 154: Added mock_agent_state and patch_settings factory fixtures.
Sprint 163: Added DB connection hang prevention fixtures.
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


@pytest.fixture(autouse=True)
def _disable_rate_limiting():
    """Disable slowapi rate limiting in unit tests.

    The in-memory rate limiter accumulates request counts across the full
    test suite.  Since all tests share the same client IP (127.0.0.1),
    rate limits can be hit when many endpoint tests run together.
    Disabling the limiter prevents cross-test interference.
    """
    from app.core.rate_limit import limiter

    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture(autouse=True)
def _reset_shared_db_unavailable_state():
    """Keep shared DB cooldown state from leaking between unit tests."""
    from app.core.database import clear_shared_database_unavailable

    clear_shared_database_unavailable()
    yield
    clear_shared_database_unavailable()


@pytest.fixture(autouse=True)
def _prevent_db_connection_hangs():
    """Prevent unit tests from hanging on DB connection attempts.

    Sprint 163: Several singletons (CharacterStateManager,
    SemanticMemoryRepository, asyncpg pool) attempt to connect to
    PostgreSQL during construction.  Without a running DB, these
    connections hang indefinitely instead of failing fast.  This
    fixture prevents the most common hang sources.
    """
    mock_mgr = MagicMock()
    mock_mgr.compile_living_state.return_value = ""

    # Mock engine that fails fast instead of hanging
    mock_engine = MagicMock()
    mock_engine.connect.side_effect = RuntimeError("No DB in unit tests")
    mock_engine.execute.side_effect = RuntimeError("No DB in unit tests")

    with (
        patch(
            "app.engine.character.character_state.get_character_state_manager",
            return_value=mock_mgr,
        ),
        patch(
            "app.services.memory_lifecycle.prune_stale_memories",
            new_callable=AsyncMock,
            return_value=0,
        ),
        patch(
            "app.core.database.get_shared_engine",
            return_value=mock_engine,
        ),
    ):
        yield


@pytest.fixture
def mock_agent_state():
    """Factory for AgentState dict with all required fields.

    Use directly or override fields:
        state = mock_agent_state
        state["query"] = "custom query"
    """
    return {
        "query": "test query",
        "user_id": "test-user",
        "session_id": "test-session",
        "response": "",
        "final_response": "",
        "thinking_content": "",
        "routing_decision": {},
        "routing_metadata": {},
        "tool_call_events": [],
        "domain_id": "maritime",
        "domain_config": {"name_vi": "Hàng hải"},
        "_trace_id": None,
        "_event_bus_id": None,
        "context": {
            "user_name": "Test User",
            "pronoun_style": "tôi-bạn",
            "is_follow_up": False,
            "user_facts": [],
            "recent_phrases": [],
            "langchain_messages": [],
            "total_responses": 0,
            "name_usage_count": 0,
            "mood_hint": "",
        },
        "current_agent": "",
        "next_agent": "",
        "agent_outputs": {},
    }


@pytest.fixture
def patch_settings(mock_settings):
    """Patch get_settings() globally for the test.

    Usage:
        def test_something(patch_settings):
            patch_settings.enable_product_search = True
            # ... test code using settings ...
    """
    with patch("app.core.config.get_settings", return_value=mock_settings):
        yield mock_settings
