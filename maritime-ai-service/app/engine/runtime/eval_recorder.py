"""Eval recorder — production-runtime-as-eval-substrate.

Phase 6 of the runtime migration epic (issue #207). The deliberate
philosophy here, borrowed from Anthropic's
``demystifying-evals-for-ai-agents``: the **same code path** that serves
production traffic also writes the records consumed by the regression
suite. There is no separate "eval system" — there is one runtime, with
recording optionally turned on.

This module ships only the snapshot format and the JSONL writer. Wiring
into ``ChatOrchestrator.process(record=True)`` and the replay script
land in follow-up PRs once the on-disk shape is locked in.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.engine.runtime.event_payload_sanitizer import (
    redact_runtime_secret_text,
    sanitize_runtime_payload,
)

logger = logging.getLogger(__name__)


_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._-]+")

def _safe_segment(value: Optional[str], default: str) -> str:
    """Sanitise a path segment so eval recordings can't escape ``base_dir``.

    Maps unknown / empty values to ``default`` and replaces every
    non-``[A-Za-z0-9._-]`` character with ``_``. Anchors path traversal
    attempts (``..``) to a literal underscore.
    """
    cleaned = _SAFE_SEGMENT.sub("_", value or "")
    cleaned = cleaned.strip("._-")
    return cleaned or default


def sanitize_eval_payload(value: Any, *, _depth: int = 0) -> Any:
    """Sanitize eval snapshots without destroying replay-useful structure."""
    return sanitize_runtime_payload(value, _depth=_depth)


def _restore_replay_text_shape(raw_value: Any, safe_value: Any) -> Any:
    if isinstance(raw_value, dict) and isinstance(safe_value, dict):
        restored = dict(safe_value)
        for raw_key, raw_item in raw_value.items():
            key = str(raw_key)
            if key in {"content", "message", "text"} and isinstance(
                raw_item, str
            ):
                restored[key] = redact_runtime_secret_text(raw_item)
                continue
            if key in restored:
                restored[key] = _restore_replay_text_shape(
                    raw_item, restored[key]
                )
        return restored
    if isinstance(raw_value, list) and isinstance(safe_value, list):
        return [
            _restore_replay_text_shape(raw_item, safe_item)
            for raw_item, safe_item in zip(raw_value, safe_value)
        ] + safe_value[len(raw_value) :]
    return safe_value


def _safe_record_payload(record: "EvalRecord") -> dict[str, Any]:
    raw_payload = record.model_dump(mode="json")
    safe_payload = sanitize_eval_payload(raw_payload)
    if not isinstance(safe_payload, dict):
        return {}
    safe_payload["request"] = _restore_replay_text_shape(
        raw_payload.get("request"), safe_payload.get("request")
    )
    return safe_payload


class EvalRecord(BaseModel):
    """One turn snapshot — the durable unit of eval replay.

    Fields are intentionally flat so JSONL diffing stays trivial. Caller
    fills only what is observable; everything else has a sane default.
    """

    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    """Unique ID for this turn snapshot."""

    session_id: str
    """Session this turn belongs to. Must match SessionEventLog.session_id."""

    org_id: Optional[str] = None
    """Multi-tenant org scope; ``None`` for personal workspace."""

    timestamp: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    """ISO-8601 UTC. Used as the partition key for storage."""

    request: dict
    """Serialized ``TurnRequest`` (or arbitrary call args)."""

    retrieved_docs: list[dict] = Field(default_factory=list)
    """RAG retrieval — list of ``{doc_id, score, snippet}`` (best-effort)."""

    tool_calls: list[dict] = Field(default_factory=list)
    """Each entry: ``{name, args, result}``. Order matches model output."""

    response: str = ""
    """Final assistant text shown to the user."""

    sources: list[dict] = Field(default_factory=list)
    """Citations: ``{id, page, bbox, content_type, ...}``."""

    metadata: dict = Field(default_factory=dict)
    """Provider, model, latency_ms, token counts, host action emissions."""

    replay_seed: Optional[str] = None
    """Optional deterministic seed so future replay can reproduce stochastic
    sampling. ``None`` = non-deterministic (default)."""


class EvalRecorder:
    """Append-only JSONL writer with date + org partitioning.

    Storage layout::

        {base_dir}/{org_id}/{YYYY-MM-DD}/{session_id}.jsonl

    Concurrency: a single asyncio.Lock guards the directory tree to keep
    the JSONL append atomic from the recorder's point of view. The file
    handle is opened in append mode per-write so multiple recorders
    against the same file do not need to coordinate further (the kernel
    serialises ``write()`` of a single line up to ``PIPE_BUF`` bytes;
    eval lines are far smaller than that limit).

    Sandbox: ``record_id`` and dynamic path segments (``org_id`` /
    ``session_id``) are sanitised so a hostile input cannot write outside
    ``base_dir``.
    """

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)
        self._lock = asyncio.Lock()

    def _path_for(self, record: EvalRecord) -> Path:
        org = _safe_segment(record.org_id, default="_personal")
        day = _safe_segment(record.timestamp[:10], default="unknown-date")
        session = _safe_segment(record.session_id, default="_unknown")
        return self.base_dir / org / day / f"{session}.jsonl"

    async def write(self, record: EvalRecord) -> Path:
        """Append a single record to its partition file. Returns the path written."""
        path = self._path_for(record)
        async with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps(_safe_record_payload(record), ensure_ascii=False) + "\n"
            # ``newline=""`` keeps the literal "\n" byte on Windows so JSONL
            # tools downstream see a UNIX-style line-terminated stream.
            with path.open("a", encoding="utf-8", newline="") as f:
                f.write(line)
        return path

    async def read_session(
        self, *, session_id: str, org_id: Optional[str] = None, day: str
    ) -> list[EvalRecord]:
        """Read every record for a single session on a given day partition.

        ``day`` is the ``YYYY-MM-DD`` partition; callers normally derive
        it from ``record.timestamp[:10]``.
        """
        org = _safe_segment(org_id, default="_personal")
        day = _safe_segment(day, default="unknown-date")
        session = _safe_segment(session_id, default="_unknown")
        path = self.base_dir / org / day / f"{session}.jsonl"
        if not path.exists():
            return []
        records: list[EvalRecord] = []
        async with self._lock:
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        records.append(EvalRecord.model_validate_json(line))
                    except Exception as exc:  # noqa: BLE001 — log + skip
                        logger.warning(
                            "[EvalRecorder] skipped malformed record: %s", exc
                        )
        return records

    async def list_sessions(
        self, *, org_id: Optional[str] = None, day: str
    ) -> list[str]:
        """List session IDs that have recordings on a given day."""
        org = _safe_segment(org_id, default="_personal")
        day = _safe_segment(day, default="unknown-date")
        partition = self.base_dir / org / day
        if not partition.exists():
            return []
        return sorted(p.stem for p in partition.glob("*.jsonl"))

    async def list_days(self, *, org_id: Optional[str] = None) -> list[str]:
        """List ``YYYY-MM-DD`` partition directories present for an org.

        Validates each candidate via ``strptime`` so junk like ``2026-XX-01``
        or ``abcd-ef-gh`` is filtered out — callers can rely on every
        returned name being a real calendar date.
        """
        from datetime import datetime

        org = _safe_segment(org_id, default="_personal")
        org_dir = self.base_dir / org
        if not org_dir.exists():
            return []
        valid: list[str] = []
        for d in org_dir.iterdir():
            if not d.is_dir() or len(d.name) != 10:
                continue
            try:
                datetime.strptime(d.name, "%Y-%m-%d")
            except ValueError:
                continue
            valid.append(d.name)
        return sorted(valid)

    async def prune_older_than(
        self, *, retention_days: int, today: Optional[str] = None
    ) -> dict[str, int]:
        """Delete partition directories older than ``retention_days``.

        Returns a per-org count of partitions removed. Idempotent — safe to
        call from a daily cron. Pass ``today`` (YYYY-MM-DD) for tests; in
        production it defaults to UTC today.
        """
        from datetime import date, datetime, timedelta, timezone

        if retention_days <= 0:
            return {}

        if today is None:
            today_dt = datetime.now(timezone.utc).date()
        else:
            today_dt = datetime.strptime(today, "%Y-%m-%d").date()
        cutoff: date = today_dt - timedelta(days=retention_days)

        if not self.base_dir.exists():
            return {}

        removed: dict[str, int] = {}
        async with self._lock:
            for org_dir in self.base_dir.iterdir():
                if not org_dir.is_dir():
                    continue
                count = 0
                for day_dir in list(org_dir.iterdir()):
                    if not day_dir.is_dir() or len(day_dir.name) != 10:
                        continue
                    try:
                        day_dt = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if day_dt < cutoff:
                        for jsonl in day_dir.glob("*.jsonl"):
                            jsonl.unlink()
                        try:
                            day_dir.rmdir()
                        except OSError:
                            # Directory not empty (race with a concurrent
                            # writer) or perm error — leave it for the next
                            # cron tick. Do not count as removed.
                            continue
                        count += 1
                if count:
                    removed[org_dir.name] = count
        return removed


def diff_records(original: EvalRecord, replayed: dict[str, Any]) -> dict[str, Any]:
    """Compute simple regression metrics between an original record and a replay.

    Pure helper — no LLM judging. Higher = more similar.
    """
    orig_text = (original.response or "").strip()
    new_text = str(replayed.get("response", "")).strip()

    orig_tokens = set(orig_text.lower().split())
    new_tokens = set(new_text.lower().split())
    if orig_tokens or new_tokens:
        token_jaccard = len(orig_tokens & new_tokens) / max(
            1, len(orig_tokens | new_tokens)
        )
    else:
        token_jaccard = 1.0

    orig_tools = [(c.get("name"), c.get("args")) for c in original.tool_calls]
    new_tools = [
        (c.get("name"), c.get("args")) for c in (replayed.get("tool_calls") or [])
    ]

    orig_source_ids = {s.get("id") for s in original.sources if s.get("id")}
    new_source_ids = {
        s.get("id") for s in (replayed.get("sources") or []) if s.get("id")
    }
    if orig_source_ids:
        sources_overlap = len(orig_source_ids & new_source_ids) / len(orig_source_ids)
    else:
        sources_overlap = 1.0

    return {
        "token_jaccard": token_jaccard,
        "tool_calls_match": orig_tools == new_tools,
        "sources_overlap": sources_overlap,
        "latency_delta_ms": (
            replayed.get("latency_ms", 0)
            - original.metadata.get("latency_ms", 0)
        ),
    }


__all__ = ["EvalRecord", "EvalRecorder", "diff_records", "sanitize_eval_payload"]
