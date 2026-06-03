"""Cross-session episodic retrieval over the durable session log.

Phase 33c of the runtime migration epic (issue #207). Wiii's existing
memory layers cover within-session context (recent window + summary)
and slow-changing facts (core_memory_block). This module fills the
gap for "I mentioned this 3 days ago in another chat" — semantic /
keyword recall across the user's PRIOR sessions.

Primitive only. The wiring step (calling this from the multi-agent
context builder so retrieved snippets show up in the prompt) lives in
a follow-up commit so the primitive can land + be reviewed on its own.

Design points:
- **Scope to user_id + org_id** — never leak prior turns across users
  or across orgs. The session_events table is already org-aware
  (Phase 14), so the SQL filter is straightforward.
- **Exclude current session** — we don't want to dilute the recent
  window with content the conversation_window manager already shows.
  Caller passes ``exclude_session_id`` for the active turn.
- **Text-similarity for now**, embedding-based later. The
  ``session_events.payload`` jsonb has a ``text`` field for both
  user_message and assistant_message events — Postgres ``ILIKE`` +
  trigram or full-text search picks up keyword overlap fast. When the
  team adopts pgvector for session_events (separate phase) we can
  swap the SELECT for a vector-distance query without changing the
  caller.
- **Defensive on missing data**. If the durable log isn't enabled
  (``enable_session_event_log=False``, in-memory backend), this
  module returns an empty list instead of raising — the caller's
  prompt builder treats no-results as "no episodic context" and
  proceeds normally.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from app.engine.runtime.event_payload_sanitizer import hash_runtime_identifier
from app.engine.semantic_memory.write_audit import resolve_memory_read_scope

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class EpisodicMatch:
    """One matching prior turn with enough context to render a citation.

    ``score`` is implementation-defined (today: substring overlap
    proxy). Callers should treat it as "higher is more relevant"
    without leaning on the exact number.
    """

    session_id: str
    seq: int
    event_type: str
    text: str
    created_at: str
    score: float


async def search_prior_user_turns(
    *,
    user_id: str,
    query: str,
    limit: int = 5,
    exclude_session_id: Optional[str] = None,
    org_id: Optional[str] = None,
    min_query_length: int = 3,
) -> list[EpisodicMatch]:
    """Return up to ``limit`` prior turns from this user that look related.

    Returns ``[]`` when:
    - ``query`` is too short / empty (avoids matching everything).
    - The asyncpg pool isn't available (e.g. in-memory event log).
    - The user has no prior session_events.
    - The DB query raises (logged at warning, never re-raised — episodic
      retrieval is a best-effort enhancement, not a hard dependency).
    """
    cleaned = (query or "").strip()
    if len(cleaned) < min_query_length:
        return []
    if limit <= 0:
        return []
    user_id_hash = hash_runtime_identifier(user_id)
    if not user_id_hash:
        return []
    scope = resolve_memory_read_scope()
    if not scope.write_allowed:
        logger.warning(
            "[episodic] retrieval blocked for user_hash=%s: %s",
            user_id_hash,
            scope.state,
        )
        return []
    effective_org_id = org_id
    if not effective_org_id and scope.state != "single_tenant_default":
        effective_org_id = scope.org_id

    try:
        from app.core.database import get_asyncpg_pool

        pool = await get_asyncpg_pool()
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "[episodic] asyncpg pool unavailable; returning []: %s", exc
        )
        return []

    # Build the WHERE clause defensively. New session_events store only
    # user_id_hash; the raw user_id fallback keeps pre-sanitizer rows
    # searchable until they are backfilled or aged out.
    params: list = [user_id_hash, user_id, f"%{cleaned.lower()}%"]
    where_parts = [
        "((payload->>'user_id_hash') = $1 OR (payload->>'user_id') = $2)",
        "lower(payload->>'text') LIKE $3",
    ]
    if exclude_session_id:
        params.append(exclude_session_id)
        where_parts.append(f"session_id <> ${len(params)}")
    if effective_org_id:
        params.append(effective_org_id)
        where_parts.append(f"org_id = ${len(params)}")

    sql = (
        "SELECT session_id, seq, event_type, "
        "       payload->>'text' AS text, "
        "       created_at "
        "FROM session_events "
        f"WHERE {' AND '.join(where_parts)} "
        "ORDER BY created_at DESC "
        f"LIMIT {int(limit)}"
    )

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "[episodic] retrieval query raised; returning []: %s", exc
        )
        return []

    needle_lower = cleaned.lower()
    matches: list[EpisodicMatch] = []
    for row in rows:
        text = row["text"] or ""
        # Score proxy: more occurrences = higher score, with a cap.
        # When we move to pgvector, replace this with the cosine
        # distance from the embedding query.
        text_lower = text.lower()
        occurrences = text_lower.count(needle_lower) if needle_lower else 0
        score = min(1.0, 0.4 + 0.2 * occurrences)
        matches.append(
            EpisodicMatch(
                session_id=row["session_id"],
                seq=int(row["seq"]),
                event_type=row["event_type"],
                text=text,
                created_at=str(row["created_at"]),
                score=score,
            )
        )

    return matches


def render_for_prompt(
    matches: list[EpisodicMatch], *, max_chars_per_match: int = 200
) -> str:
    """Render a compact prompt-ready block from a list of matches.

    Returns "" when ``matches`` is empty so callers can ``+`` it into
    the system prompt unconditionally without worrying about extra
    blank lines.
    """
    if not matches:
        return ""

    lines = ["Trí nhớ từ các phiên trước (chỉ tham khảo, đừng nhắc lại nguyên văn):"]
    for m in matches:
        snippet = m.text.strip()
        if len(snippet) > max_chars_per_match:
            snippet = snippet[: max_chars_per_match - 1].rstrip() + "…"
        lines.append(f"- ({m.event_type}, seq {m.seq}) {snippet}")
    return "\n".join(lines) + "\n"


__all__ = ["EpisodicMatch", "search_prior_user_turns", "render_for_prompt"]
