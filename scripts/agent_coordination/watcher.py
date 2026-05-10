#!/usr/bin/env python3
"""GitHub coordination watcher for Wiii x Maritime LMS.

The watcher is deliberately conservative:

- read-only by default
- requires --apply for GitHub writes
- posts digests to a chosen central issue, not to every watched item
- parses only explicit structured comments
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = Path(__file__).with_name("coordination_config.example.json")
SYNC_MARKER = "<!-- wiii-lms-sync:v1 -->"
SYNC_FIELDS = ("ROLE", "STATUS", "BLOCKER", "NEEDS_OTHER_REPO", "EVIDENCE", "NEXT_PATCH")


@dataclass(frozen=True)
class RepoConfig:
    key: str
    full_name: str
    role: str
    partner_repo: str
    watch_labels: tuple[str, ...]


@dataclass(frozen=True)
class WatchedItem:
    repo: str
    kind: str
    number: int
    title: str
    url: str
    labels: tuple[str, ...]
    updated_at: str
    state: str = "OPEN"
    is_draft: bool = False
    head_ref: str = ""
    base_ref: str = ""
    latest_sync: dict[str, str] | None = None


def run_gh(args: list[str], *, check: bool = True) -> str:
    proc = subprocess.run(
        ["gh", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if check and proc.returncode != 0:
        details = proc.stderr.strip() or proc.stdout.strip()
        raise RuntimeError(f"gh {' '.join(args)} failed: {details}")
    return proc.stdout


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def repo_configs(config: dict[str, Any]) -> list[RepoConfig]:
    repos: list[RepoConfig] = []
    for item in config.get("repos", []):
        repos.append(
            RepoConfig(
                key=str(item["key"]),
                full_name=str(item["full_name"]),
                role=str(item["role"]),
                partner_repo=str(item["partner_repo"]),
                watch_labels=tuple(str(x) for x in item.get("watch_labels", [])),
            )
        )
    return repos


def label_names(raw_labels: list[dict[str, Any]]) -> tuple[str, ...]:
    return tuple(str(label.get("name", "")).strip() for label in raw_labels if label.get("name"))


def should_watch(labels: tuple[str, ...], repo: RepoConfig, include_all: bool) -> bool:
    if include_all:
        return True
    label_set = set(labels)
    return bool(label_set.intersection(repo.watch_labels))


def list_repo_items(repo: RepoConfig, *, limit: int, include_all: bool) -> list[WatchedItem]:
    items: list[WatchedItem] = []
    issue_json = run_gh(
        [
            "issue",
            "list",
            "--repo",
            repo.full_name,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,url,labels,updatedAt",
        ]
    )
    for issue in json.loads(issue_json or "[]"):
        labels = label_names(issue.get("labels", []))
        if not should_watch(labels, repo, include_all):
            continue
        items.append(
            WatchedItem(
                repo=repo.full_name,
                kind="issue",
                number=int(issue["number"]),
                title=str(issue["title"]),
                url=str(issue["url"]),
                labels=labels,
                updated_at=str(issue.get("updatedAt", "")),
            )
        )

    pr_json = run_gh(
        [
            "pr",
            "list",
            "--repo",
            repo.full_name,
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,title,url,labels,updatedAt,isDraft,headRefName,baseRefName",
        ]
    )
    for pr in json.loads(pr_json or "[]"):
        labels = label_names(pr.get("labels", []))
        if not should_watch(labels, repo, include_all):
            continue
        items.append(
            WatchedItem(
                repo=repo.full_name,
                kind="pr",
                number=int(pr["number"]),
                title=str(pr["title"]),
                url=str(pr["url"]),
                labels=labels,
                updated_at=str(pr.get("updatedAt", "")),
                is_draft=bool(pr.get("isDraft")),
                head_ref=str(pr.get("headRefName") or ""),
                base_ref=str(pr.get("baseRefName") or ""),
            )
        )
    return items


def parse_sync_comment(body: str) -> dict[str, str] | None:
    if SYNC_MARKER not in body:
        return None
    parsed: dict[str, str] = {}
    for raw_line in body.splitlines():
        line = raw_line.strip()
        for field in SYNC_FIELDS:
            prefix = f"{field}:"
            if line.startswith(prefix):
                parsed[field] = line[len(prefix) :].strip()
    return parsed or None


def latest_sync_for(item: WatchedItem) -> dict[str, str] | None:
    command = "pr" if item.kind == "pr" else "issue"
    try:
        raw = run_gh(
            [
                command,
                "view",
                str(item.number),
                "--repo",
                item.repo,
                "--comments",
                "--json",
                "comments",
            ]
        )
    except RuntimeError:
        return None
    comments = json.loads(raw or "{}").get("comments", [])
    latest: dict[str, str] | None = None
    for comment in comments:
        parsed = parse_sync_comment(str(comment.get("body") or ""))
        if parsed:
            parsed["COMMENT_AUTHOR"] = str(comment.get("author", {}).get("login") or "")
            parsed["COMMENT_CREATED_AT"] = str(comment.get("createdAt") or "")
            latest = parsed
    return latest


def collect_items(config: dict[str, Any], *, limit: int, include_all: bool, enrich: bool) -> list[WatchedItem]:
    items: list[WatchedItem] = []
    for repo in repo_configs(config):
        for item in list_repo_items(repo, limit=limit, include_all=include_all):
            if enrich:
                item = WatchedItem(**{**item.__dict__, "latest_sync": latest_sync_for(item)})
            items.append(item)
    return sorted(items, key=lambda x: x.updated_at, reverse=True)


def render_digest(items: list[WatchedItem], config: dict[str, Any]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    observer = config.get("observer", {})
    lines = [
        "<!-- wiii-lms-observer-digest:v1 -->",
        f"## Wiii x LMS Coordination Digest - {now}",
        "",
        f"Observer: `{observer.get('name', 'observer-agent')}`",
        f"Mode: `{observer.get('mode', 'report-only')}`",
        "",
    ]
    if not items:
        lines.append("No watched open issues or PRs found.")
        return "\n".join(lines)

    blockers: list[WatchedItem] = []
    needs_review: list[WatchedItem] = []
    for item in items:
        status = (item.latest_sync or {}).get("STATUS", "").lower()
        if status == "blocked" or "blocked:other-repo" in item.labels:
            blockers.append(item)
        if status in {"needs_review", "verified"}:
            needs_review.append(item)

    lines.extend(["### Blockers", ""])
    if blockers:
        for item in blockers:
            sync = item.latest_sync or {}
            lines.append(
                f"- `{item.repo}#{item.number}` {item.title} - "
                f"{sync.get('BLOCKER') or 'blocked; see labels/comments'}"
            )
            if sync.get("NEXT_PATCH"):
                lines.append(f"  Next: {sync['NEXT_PATCH']}")
    else:
        lines.append("- No structured blockers found.")

    lines.extend(["", "### Watched Items", ""])
    for item in items:
        sync = item.latest_sync or {}
        status = sync.get("STATUS", "no-sync-comment")
        role = sync.get("ROLE", "unknown")
        labels = ", ".join(item.labels) if item.labels else "no labels"
        draft = " draft" if item.is_draft else ""
        lines.append(f"- `{item.repo}#{item.number}` [{item.kind}{draft}] {item.title}")
        lines.append(f"  URL: {item.url}")
        lines.append(f"  Labels: {labels}")
        lines.append(f"  Latest sync: `{status}` by `{role}`")
        if sync.get("EVIDENCE"):
            lines.append(f"  Evidence: {sync['EVIDENCE']}")
        if sync.get("NEEDS_OTHER_REPO"):
            lines.append(f"  Needs: `{sync['NEEDS_OTHER_REPO']}`")

    if needs_review:
        lines.extend(["", "### Human Review Queue", ""])
        for item in needs_review:
            lines.append(f"- `{item.repo}#{item.number}` {item.title} - {item.url}")

    lines.extend(
        [
            "",
            "### Observer Rule",
            "",
            "This digest is advisory. It does not merge, deploy, or approve PRs.",
        ]
    )
    return "\n".join(lines)


def parse_issue_ref(value: str) -> tuple[str, str]:
    if "#" not in value:
        raise ValueError("--post-to must look like owner/repo#123")
    repo, number = value.rsplit("#", 1)
    if not repo or not number.isdigit():
        raise ValueError("--post-to must look like owner/repo#123")
    return repo, number


def bootstrap_labels(config: dict[str, Any], *, apply: bool) -> None:
    labels = config.get("labels", [])
    repos = repo_configs(config)
    for repo in repos:
        for label in labels:
            name = str(label["name"])
            color = str(label.get("color", "ededed")).lstrip("#")
            description = str(label.get("description", ""))
            if not apply:
                print(
                    "DRY-RUN gh label create",
                    name,
                    "--repo",
                    repo.full_name,
                    "--color",
                    color,
                )
                continue
            create_args = [
                "label",
                "create",
                name,
                "--repo",
                repo.full_name,
                "--color",
                color,
                "--description",
                description,
            ]
            proc = subprocess.run(
                ["gh", *create_args],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            if proc.returncode == 0:
                print(f"created {repo.full_name}:{name}")
                continue
            edit_args = [
                "label",
                "edit",
                name,
                "--repo",
                repo.full_name,
                "--color",
                color,
                "--description",
                description,
            ]
            run_gh(edit_args)
            print(f"updated {repo.full_name}:{name}")


def create_thread(config: dict[str, Any], *, title: str, body: str, apply: bool) -> None:
    repos = repo_configs(config)
    created: list[tuple[str, str]] = []
    base_body = body.strip() or (
        "Cross-repository coordination issue for Wiii x Maritime LMS integration.\n\n"
        "Agents should use the structured sync comment contract from "
        "`docs/operations/WIII_LMS_AGENT_COORDINATION.md`."
    )
    for repo in repos:
        labels = "coord:watch,integration:wiii-lms,agent:observer"
        partner_links = "\n".join(f"- {r}#{n}" for r, n in created)
        full_body = base_body
        if partner_links:
            full_body += f"\n\nPartner coordination issue(s):\n{partner_links}\n"
        if not apply:
            print(f"DRY-RUN create issue in {repo.full_name}: {title}")
            continue
        out = run_gh(
            [
                "issue",
                "create",
                "--repo",
                repo.full_name,
                "--title",
                title,
                "--body",
                full_body,
                "--label",
                labels,
            ]
        ).strip()
        match = re.search(r"/issues/(\d+)", out)
        number = match.group(1) if match else "unknown"
        created.append((repo.full_name, number))
        print(out)
    if apply and len(created) > 1:
        summary = "\n".join(f"- {repo}#{number}" for repo, number in created)
        print("created coordination thread:\n" + summary)


def cmd_snapshot(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    items = collect_items(config, limit=args.limit, include_all=args.all, enrich=args.enrich)
    if args.json:
        print(json.dumps([item.__dict__ for item in items], indent=2, ensure_ascii=False))
    else:
        print(render_digest(items, config))
    return 0


def cmd_digest(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    items = collect_items(config, limit=args.limit, include_all=args.all, enrich=True)
    digest = render_digest(items, config)
    if not args.post_to:
        print(digest)
        return 0
    repo, number = parse_issue_ref(args.post_to)
    if not args.apply:
        print("DRY-RUN would post digest to", args.post_to)
        print(digest)
        return 0
    run_gh(["issue", "comment", number, "--repo", repo, "--body", digest])
    print(f"posted digest to {args.post_to}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    sub = parser.add_subparsers(dest="command", required=True)

    labels = sub.add_parser("bootstrap-labels", help="Create/update coordination labels.")
    labels.add_argument("--apply", action="store_true", help="Write labels through gh.")
    labels.set_defaults(func=lambda args: (bootstrap_labels(load_config(args.config), apply=args.apply), 0)[1])

    thread = sub.add_parser("create-thread", help="Create paired coordination issues.")
    thread.add_argument("--title", required=True)
    thread.add_argument("--body", default="")
    thread.add_argument("--apply", action="store_true", help="Create issues through gh.")
    thread.set_defaults(
        func=lambda args: (create_thread(load_config(args.config), title=args.title, body=args.body, apply=args.apply), 0)[1]
    )

    snapshot = sub.add_parser("snapshot", help="Print watched issues/PRs.")
    snapshot.add_argument("--limit", type=int, default=20)
    snapshot.add_argument("--all", action="store_true", help="Include open items even without watch labels.")
    snapshot.add_argument("--enrich", action="store_true", help="Fetch and parse latest sync comments.")
    snapshot.add_argument("--json", action="store_true")
    snapshot.set_defaults(func=cmd_snapshot)

    digest = sub.add_parser("digest", help="Render or post an observer digest.")
    digest.add_argument("--limit", type=int, default=20)
    digest.add_argument("--all", action="store_true", help="Include open items even without watch labels.")
    digest.add_argument("--post-to", help="Central issue ref, e.g. meiiie/wiii#123.")
    digest.add_argument("--apply", action="store_true", help="Post digest through gh.")
    digest.set_defaults(func=cmd_digest)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except Exception as exc:  # pragma: no cover - CLI safety net
        print(f"watcher error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
