#!/usr/bin/env python3
"""Seed a small maritime text corpus into the Wiii pgvector knowledge base.

The script is intentionally idempotent: the API writes deterministic chunk
node IDs from document_id + chunk_index, so re-running updates the same corpus.
Secrets are read from environment variables and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


DEFAULT_CORPUS = (
    Path(__file__).resolve().parent
    / "data"
    / "maritime_seed_corpus"
    / "colregs_teaching_seed_v1.md"
)
DEFAULT_DOCUMENT_ID = "maritime-colregs-teaching-seed-v1"
DEFAULT_TITLE = "COLREGs teaching seed corpus v1"
DEFAULT_USER_AGENT = "Wiii-KB-Seed/1.0"


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    api_key: str | None = None,
    bearer_token: str | None = None,
    timeout: float = 60.0,
) -> tuple[int, dict[str, Any]]:
    body = None
    headers = {
        "Accept": "application/json",
        # Cloudflare can block Python's default urllib user agent with 1010.
        # Keep this explicit so production dry-runs behave like curl/browser
        # probes without weakening auth on write endpoints.
        "User-Agent": DEFAULT_USER_AGENT,
    }
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    elif api_key:
        headers["X-API-Key"] = api_key

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw else {}
            return response.status, parsed
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            parsed = {"detail": raw[:500]}
        return exc.code, parsed
    except URLError as exc:
        raise RuntimeError(f"Could not reach {url}: {exc}") from exc


def _read_secret_env(name: str | None) -> str | None:
    if not name:
        return None
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    return None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Seed the Wiii knowledge base with a small COLREGs teaching corpus."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("WIII_BASE_URL", "http://localhost:8000"),
        help="Wiii API base URL, for example https://wiii.holilihu.online",
    )
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS), help="Markdown corpus path.")
    parser.add_argument("--document-id", default=DEFAULT_DOCUMENT_ID)
    parser.add_argument("--title", default=DEFAULT_TITLE)
    parser.add_argument("--domain-id", default="maritime")
    parser.add_argument("--organization-id", default=None)
    parser.add_argument(
        "--api-key-env",
        default="WIII_API_KEY",
        help="Environment variable that contains X-API-Key. Fallback: API_KEY.",
    )
    parser.add_argument(
        "--bearer-token-env",
        default="WIII_ADMIN_JWT",
        help="Environment variable that contains a platform-admin JWT.",
    )
    parser.add_argument("--stats-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout", type=float, default=90.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    base_url = args.base_url.rstrip("/") + "/"
    stats_url = urljoin(base_url, "api/v1/knowledge/stats")
    ingest_url = urljoin(base_url, "api/v1/knowledge/ingest-text")

    api_key = _read_secret_env(args.api_key_env) or _read_secret_env("API_KEY")
    bearer_token = _read_secret_env(args.bearer_token_env)

    print(f"Target: {base_url.rstrip('/')}")
    before_status, before = _json_request(
        stats_url,
        api_key=api_key,
        bearer_token=bearer_token,
        timeout=args.timeout,
    )
    print(
        "Before stats: "
        f"http={before_status}, chunks={before.get('total_chunks')}, "
        f"documents={before.get('total_documents')}, warning={before.get('warning')!r}"
    )
    if args.stats_only:
        return 0 if before_status < 400 else 1

    corpus_path = Path(args.corpus)
    content = corpus_path.read_text(encoding="utf-8").strip()
    if not content:
        print(f"Corpus is empty: {corpus_path}", file=sys.stderr)
        return 2

    payload = {
        "content": content,
        "document_id": args.document_id,
        "domain_id": args.domain_id,
        "title": args.title,
        "organization_id": args.organization_id,
    }

    if args.dry_run:
        print(
            "Dry run: "
            f"document_id={args.document_id}, domain_id={args.domain_id}, "
            f"bytes={len(content.encode('utf-8'))}"
        )
        return 0

    if not api_key and not bearer_token:
        print(
            "Missing credentials. Set WIII_ADMIN_JWT for platform-admin JWT "
            "or WIII_API_KEY/API_KEY when the target environment permits admin API-key ingestion.",
            file=sys.stderr,
        )
        return 2

    ingest_status, ingest = _json_request(
        ingest_url,
        method="POST",
        payload=payload,
        api_key=api_key,
        bearer_token=bearer_token,
        timeout=args.timeout,
    )
    print(
        "Ingest result: "
        f"http={ingest_status}, status={ingest.get('status')!r}, "
        f"document_id={ingest.get('document_id')!r}, chunks={ingest.get('total_chunks')}, "
        f"detail={ingest.get('detail')!r}"
    )
    if ingest_status >= 400:
        return 1

    after_status, after = _json_request(
        stats_url,
        api_key=api_key,
        bearer_token=bearer_token,
        timeout=args.timeout,
    )
    print(
        "After stats: "
        f"http={after_status}, chunks={after.get('total_chunks')}, "
        f"documents={after.get('total_documents')}, domain_breakdown={after.get('domain_breakdown')}"
    )
    return 0 if after_status < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
