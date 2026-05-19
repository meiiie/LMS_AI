# Wiii Agentic Codebase Harness

Status: Active

Owner: Project leadership

Last updated: 2026-05-19

This document translates large-codebase agent practices into Wiii's repository
workflow. The goal is not to add ceremony. The goal is to make Wiii easier to
navigate, safer to edit, and less dependent on tribal memory.

## Principles

1. Load broad context once, specialized context only when needed.
2. Start from a scoped subsystem when the task is scoped.
3. Prefer live code search over stale mental models.
4. Separate exploration from editing for broad changes.
5. Keep WIP reviewable by contract, not by enthusiasm.
6. Put durable learnings in docs, not chat.
7. Let deterministic checks enforce what prompts should not have to remember.

## Layered Context

Wiii uses layered agent guidance:

| Layer | File | Purpose |
|---|---|---|
| Repository | `AGENTS.md` | global rules, governance, risk surfaces |
| Backend | `maritime-ai-service/AGENTS.md` | backend runtime navigation and tests |
| Frontend | `wiii-desktop/AGENTS.md` | chat/embed/voice/visual UI navigation and tests |
| Skills | `.agents/skills/**/SKILL.md` | on-demand workflows |
| Operations | `docs/operations/**` | governance, deploy, recovery, release |
| Architecture | `docs/architecture/**` | system maps and contracts |
| Specs | `specs/**` | feature-specific plans and tasks |

Root guidance should stay compact. Path-specific guidance should carry the local
details.

## Exploration Protocol

For broad or unclear tasks:

1. Read root `AGENTS.md`.
2. Read the path-specific `AGENTS.md` for the subsystem.
3. Read the relevant architecture or operation doc.
4. Use `rg` and focused file reads to map the exact path.
5. Write a short finding or plan before editing.
6. Edit only the scoped files.
7. Run the smallest meaningful checks.
8. Update docs if the contract changed.

For narrow bugs, skip broad architecture reading once the relevant subsystem is
known, but still obey the local `AGENTS.md`.

## PR Slicing Rules

Split work by contract:

- tool call parsing and dispatch
- streaming lifecycle
- Markdown rendering
- LMS preview/apply approval
- document memory and provenance
- voice transport and provider config
- visual artifact runtime
- deployment config
- docs and harness

Do not mix deploy changes with runtime changes unless the issue is specifically
about production rollout.

## Reviewability Budget

Default governance limits remain:

- maximum 150 changed files
- maximum 20,000 total changed lines

Wiii should normally aim much smaller:

- backend runtime PR: 3 to 12 files
- frontend UI PR: 3 to 15 files
- docs-only PR: 1 to 8 files
- deploy PR: as small as possible, with rollback notes

If a branch grows beyond that, split before opening ready-for-review.

## Deterministic Checks

Use checks to enforce basics:

```powershell
git status --short
git diff --check
```

Backend focused checks:

```powershell
cd maritime-ai-service
python -m ruff check app/ tests/unit/ --select=E9,F63,F7
python -m pytest tests/unit/<focused-test>.py -q --tb=short
```

Frontend focused checks:

```powershell
cd wiii-desktop
npx vitest run src/__tests__/<focused-test>.test.tsx
npx tsc --noEmit
```

Run broader suites only after focused checks are green or when the PR touches a
shared contract.

## Repository Hygiene Rules

Never commit:

- `.env*`
- provider keys or tokens
- local logs
- screenshots from temporary runs
- generated `dist`, `dist-embed`, coverage, cache, or dependency folders
- one-off scratch scripts without ownership

When a session produces useful but mixed WIP, preserve it with a named stash or
branch before cleanup. Do not hide it inside an unrelated PR.

## WIP Recovery Pattern

Use this pattern when work has become too broad:

```powershell
git status -sb
git diff --shortstat
git stash push -u -m "<clear-wip-name>"
git switch -c codex/<narrow-cleanup-or-fix>
```

Then recover slices with:

```powershell
git stash list --format="%H %gd %s"
git stash show --stat <stash-commit-hash>
git checkout <stash-commit-hash> -- path/to/file
```

Use the stash message to select the right entry, then use its commit hash.
Avoid `stash@{0}` in durable docs because stash positions change as new entries
are created or dropped.

Only restore files for the PR slice being prepared.

## Maintenance Cadence

Every 3 to 6 months, review:

- root and path-specific `AGENTS.md`
- active skills
- stale local branches
- feature flags and tiers
- docs that describe runtime paths
- scripts used by deploy or local startup

Remove or archive docs that no longer match code. Keep the codebase map current.
