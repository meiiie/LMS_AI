"""Phase 33c episodic retrieval — Runtime Migration #207.

Locks the contract:
- Empty / too-short query → [] (no DB call).
- Pool unavailable → [] (logged at debug, no raise).
- Query SQL composition matches expected params.
- render_for_prompt empty when no matches.
- render_for_prompt truncates each snippet at the configured cap.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier
from app.engine.runtime.episodic_retrieval import (
    EpisodicMatch,
    render_for_prompt,
    search_prior_user_turns,
)


# ── input-validation short-circuits ──

@pytest.mark.parametrize("query", ["", "  ", "ab"])
async def test_too_short_query_returns_empty_list_without_db(query):
    """Tiny / blank queries must not hit the DB — they would match
    too much and produce noise."""
    with patch(
        "app.core.database.get_asyncpg_pool",
        new_callable=AsyncMock,
    ) as pool_mock:
        out = await search_prior_user_turns(user_id="u", query=query)
    assert out == []
    pool_mock.assert_not_called()


async def test_zero_limit_returns_empty():
    out = await search_prior_user_turns(
        user_id="u", query="some text", limit=0
    )
    assert out == []


# ── pool unavailable ──

async def test_pool_unavailable_returns_empty(monkeypatch):
    async def boom():
        raise RuntimeError("no pool here")

    monkeypatch.setattr(
        "app.core.database.get_asyncpg_pool", boom, raising=False
    )
    out = await search_prior_user_turns(user_id="u", query="some text")
    assert out == []


# ── happy path with mocked pool ──

@pytest.fixture
def mock_pool_with_rows():
    """Fixture: returns a pool whose .acquire() yields a connection
    with .fetch returning canned rows. Lets us inspect the SQL + args
    without a live Postgres."""
    rows = [
        {
            "session_id": "s-1",
            "seq": 5,
            "event_type": "user_message",
            "text": "Tên mình là Hùng và mình thích COLREGs",
            "created_at": "2026-05-01T10:00:00Z",
        },
        {
            "session_id": "s-2",
            "seq": 12,
            "event_type": "assistant_message",
            "text": "Wiii nhớ rồi nha Hùng~",
            "created_at": "2026-05-02T11:00:00Z",
        },
    ]

    captured_calls: list[tuple] = []

    class FakeConn:
        async def fetch(self, sql, *args):
            captured_calls.append((sql, args))
            return rows

    class FakePool:
        def acquire(self):
            class _CtxManager:
                async def __aenter__(self):
                    return FakeConn()

                async def __aexit__(self, *exc):
                    return None

            return _CtxManager()

    return FakePool(), captured_calls


async def test_returns_episodic_matches_with_score(monkeypatch, mock_pool_with_rows):
    pool, _ = mock_pool_with_rows

    async def get_pool():
        return pool

    monkeypatch.setattr(
        "app.core.database.get_asyncpg_pool", get_pool, raising=False
    )
    out = await search_prior_user_turns(user_id="user-1", query="Hùng")
    assert len(out) == 2
    assert isinstance(out[0], EpisodicMatch)
    assert out[0].session_id == "s-1"
    assert out[0].seq == 5
    assert out[0].event_type == "user_message"
    # Score is bounded.
    for m in out:
        assert 0.0 <= m.score <= 1.0


async def test_query_composition_includes_user_filter(
    monkeypatch, mock_pool_with_rows
):
    pool, captured = mock_pool_with_rows

    async def get_pool():
        return pool

    monkeypatch.setattr(
        "app.core.database.get_asyncpg_pool", get_pool, raising=False
    )
    await search_prior_user_turns(user_id="user-A", query="search me")
    sql, args = captured[0]
    assert "session_events" in sql
    assert "(payload->>'user_id_hash') = $1" in sql
    assert "(payload->>'user_id') = $2" in sql
    assert args[0] == hash_runtime_identifier("user-A")
    assert args[1] == "user-A"
    assert args[2] == "%search me%"


async def test_query_composition_excludes_current_session(
    monkeypatch, mock_pool_with_rows
):
    pool, captured = mock_pool_with_rows

    async def get_pool():
        return pool

    monkeypatch.setattr(
        "app.core.database.get_asyncpg_pool", get_pool, raising=False
    )
    await search_prior_user_turns(
        user_id="u", query="hello world", exclude_session_id="current-sess"
    )
    sql, args = captured[0]
    assert "session_id <> $4" in sql
    assert args[3] == "current-sess"


async def test_query_composition_filters_by_org(
    monkeypatch, mock_pool_with_rows
):
    pool, captured = mock_pool_with_rows

    async def get_pool():
        return pool

    monkeypatch.setattr(
        "app.core.database.get_asyncpg_pool", get_pool, raising=False
    )
    await search_prior_user_turns(
        user_id="u", query="hello world", org_id="org-A"
    )
    sql, args = captured[0]
    assert "org_id = $4" in sql
    assert args[3] == "org-A"


async def test_multi_tenant_missing_org_context_blocks_db(monkeypatch):
    from app.core.config import settings
    from app.core.org_context import current_org_id

    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")
    token = current_org_id.set(None)
    try:
        with patch(
            "app.core.database.get_asyncpg_pool",
            new_callable=AsyncMock,
        ) as pool_mock:
            out = await search_prior_user_turns(
                user_id="user-private",
                query="hello world",
            )
    finally:
        current_org_id.reset(token)

    assert out == []
    pool_mock.assert_not_called()


async def test_query_uses_current_org_context_when_org_arg_missing(
    monkeypatch,
    mock_pool_with_rows,
):
    from app.core.config import settings
    from app.core.org_context import current_org_id

    pool, captured = mock_pool_with_rows

    async def get_pool():
        return pool

    monkeypatch.setattr(settings, "enable_multi_tenant", True)
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "default_organization_id", "default")
    monkeypatch.setattr(
        "app.core.database.get_asyncpg_pool", get_pool, raising=False
    )
    token = current_org_id.set("org-A")
    try:
        await search_prior_user_turns(user_id="u", query="hello world")
    finally:
        current_org_id.reset(token)

    sql, args = captured[0]
    assert "org_id = $4" in sql
    assert args[3] == "org-A"


async def test_db_error_returns_empty_no_raise(monkeypatch):
    """A DB error must NOT bubble up — episodic is best-effort."""

    class FailingConn:
        async def fetch(self, sql, *args):
            raise RuntimeError("simulated DB outage")

    class FailingPool:
        def acquire(self):
            class _CtxManager:
                async def __aenter__(self):
                    return FailingConn()

                async def __aexit__(self, *exc):
                    return None

            return _CtxManager()

    async def get_pool():
        return FailingPool()

    monkeypatch.setattr(
        "app.core.database.get_asyncpg_pool", get_pool, raising=False
    )
    out = await search_prior_user_turns(user_id="u", query="hello")
    assert out == []


# ── render_for_prompt ──

def test_render_for_prompt_empty_when_no_matches():
    assert render_for_prompt([]) == ""


def test_render_for_prompt_includes_each_match():
    matches = [
        EpisodicMatch(
            session_id="s1", seq=1, event_type="user_message",
            text="Tên mình là Hùng", created_at="t1", score=0.6,
        ),
        EpisodicMatch(
            session_id="s2", seq=4, event_type="assistant_message",
            text="Wiii nhớ rồi", created_at="t2", score=0.5,
        ),
    ]
    out = render_for_prompt(matches)
    assert "Trí nhớ từ các phiên trước" in out
    assert "user_message" in out
    assert "Tên mình là Hùng" in out
    assert "assistant_message" in out
    assert out.endswith("\n")


def test_render_for_prompt_truncates_long_snippets():
    long_text = "A" * 500
    matches = [
        EpisodicMatch(
            session_id="s1", seq=1, event_type="user_message",
            text=long_text, created_at="t", score=0.5,
        )
    ]
    out = render_for_prompt(matches, max_chars_per_match=50)
    # Each match line stays at or under the cap (plus the prefix).
    snippet_line = [l for l in out.splitlines() if l.startswith("- ")][0]
    assert len(snippet_line) < 100  # well under the cap + prefix overhead
    assert "…" in snippet_line  # truncation marker preserved
