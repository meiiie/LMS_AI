#!/usr/bin/env python3
"""Smoke test production RAG chat against an already-ingested corpus.

The script intentionally avoids printing secrets. It reports only response
shape, source/document evidence, and a short answer preview for operator QA.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


DEFAULT_QUERY = (
    "According to COLREGs, in a crossing situation between two power-driven "
    "vessels with risk of collision, which vessel should give way? Cite the "
    "knowledge source if available."
)
DEFAULT_USER_AGENT = "Wiii-RAG-Chat-Smoke/1.0"


def _read_secret_env(name: str | None) -> str | None:
    if not name:
        return None
    value = os.getenv(name)
    if value and value.strip():
        return value.strip()
    return None


def _json_post(
    url: str,
    *,
    payload: dict[str, Any],
    bearer_token: str,
    timeout: float,
) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {bearer_token}",
            "Content-Type": "application/json",
            "User-Agent": DEFAULT_USER_AGENT,
        },
        method="POST",
    )
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


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a production RAG chat smoke query using a platform-admin JWT."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("WIII_BASE_URL", "https://wiii.holilihu.online"),
        help="Wiii API base URL.",
    )
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--domain-id", default="maritime")
    parser.add_argument("--bearer-token-env", default="WIII_ADMIN_JWT")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--require-source", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    bearer_token = _read_secret_env(args.bearer_token_env)
    if not bearer_token:
        print(f"Missing bearer token env: {args.bearer_token_env}", file=sys.stderr)
        return 2

    base_url = args.base_url.rstrip("/") + "/"
    chat_url = urljoin(base_url, "api/v1/chat")
    session_id = f"production-rag-smoke-{int(time.time())}"
    payload = {
        "user_id": "github-actions-rag-smoke",
        "message": args.query,
        "role": "teacher",
        "session_id": session_id,
        "domain_id": args.domain_id,
        "thinking_effort": "medium",
    }

    status_code, response = _json_post(
        chat_url,
        payload=payload,
        bearer_token=bearer_token,
        timeout=args.timeout,
    )
    data = response.get("data") if isinstance(response, dict) else {}
    metadata = response.get("metadata") if isinstance(response, dict) else {}
    answer = (data or {}).get("answer") or ""
    sources = (data or {}).get("sources") or []
    document_ids = (metadata or {}).get("document_ids_used") or []
    tools_used = (metadata or {}).get("tools_used") or []
    agent_type = (metadata or {}).get("agent_type")
    query_type = (metadata or {}).get("query_type")
    provider = (metadata or {}).get("provider")
    model = (metadata or {}).get("model")
    preview = " ".join(answer.split())[:500]

    print(
        "RAG chat smoke: "
        f"http={status_code}, status={response.get('status')!r}, "
        f"answer_chars={len(answer)}, sources={len(sources)}, "
        f"document_ids={document_ids}, tools={tools_used}, "
        f"agent_type={agent_type!r}, query_type={query_type!r}, "
        f"provider={provider!r}, model={model!r}"
    )
    if preview:
        print(f"Answer preview: {preview}")

    if status_code >= 400:
        detail = response.get("detail") or response.get("message") or response
        print(f"RAG chat smoke failed: {detail}", file=sys.stderr)
        return 1
    if response.get("status") != "success" or not answer.strip():
        print("RAG chat smoke failed: response did not contain a successful answer.", file=sys.stderr)
        return 1
    if args.require_source and not sources and not document_ids:
        print(
            "RAG chat smoke failed: no source citations or document_ids_used returned.",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
