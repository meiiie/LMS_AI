# Wiii Documentation Governance

Status: Active

Owner: Project leadership

Last updated: 2026-05-10

Applies to: repository documentation, operational reports, architecture notes, cleanup artifacts, release checkpoints

## Executive Policy

Wiii documentation is managed as an engineering control plane, not as a scratchpad.

The repository may contain exploratory reports, but only reviewed documents in canonical documentation locations should be treated as source of truth. The goal is to keep engineering decisions auditable, current, and easy to operate under release pressure.

## Canonical Locations

| Location | Purpose | Authority |
|---|---|---|
| `docs/README.md` | Repository documentation index | Canonical |
| `docs/operations/` | Operational checkpoints, governance, cleanup plans, release controls | Canonical |
| `docs/plans/` | Approved design and implementation plans | Canonical after review |
| `docs/assets/` | Documentation assets referenced by canonical docs | Canonical only when referenced or explicitly retained as source material |
| `maritime-ai-service/docs/` | Backend architecture, integration, and deployment docs | Canonical for backend scope |
| `wiii-desktop/docs/` and `wiii-desktop/README.md` | Desktop-specific documentation | Canonical for desktop scope |
| `.Codex/` | Local Codex scratch output, logs, reports, and probes | Non-canonical, ignored |
| `.claude/` | Retired legacy/local Claude scratch output | Non-canonical, ignored |

## Artifact Classes

| Class | Examples | Required handling |
|---|---|---|
| Source-of-truth docs | Architecture, integration contracts, governance | Reviewed PR, stable path, explicit status |
| Operational checkpoint | Cleanup checkpoint, release readiness, runtime truth sheet | Date-stamped, evidence-backed, owner assigned |
| Decision record | Architecture or policy decision | Include context, decision, consequences, rollback path |
| Working report | Deep audit, debug trace, temporary inventory | Time-boxed, non-canonical, promote or archive |
| Generated artifact | Logs, screenshots, json dumps, html reports | Keep out of canonical docs unless referenced |

## Lifecycle

1. Create working notes only when investigation is still unstable.
2. Promote durable conclusions into canonical docs before they are used to guide implementation.
3. Link the canonical doc from `docs/README.md` or the nearest area README.
4. Open an issue for non-trivial cleanup, governance, or architecture work.
5. Open a PR with explicit scope, risk, verification, and rollback notes.
6. Archive or delete superseded working reports after promotion.

## Retention Policy

Working reports should not grow without bounds.

- Keep active reports while they are attached to an open issue or PR.
- Promote any report that becomes operational guidance.
- Delete untracked scratch reports after their content is consolidated.
- Delete or archive tracked historical reports only through a separate retention PR with an explicit inventory.
- Do not bulk-delete tracked reports, migrations, tests, data, or docs without a written inventory and review.
- As of 2026-04-24, legacy tracked report trees were removed from source control. Do not re-add them; promote durable content into `docs/operations/` instead.
- As of 2026-05-10, superseded checkpoint, audit, sprint-plan, and unreferenced screenshot artifacts were removed after current runbooks and issues became the source of truth.
- As of 2026-05-10, tracked legacy `.claude/` coordination files and `.Codex` scratch samples were removed from `main`; use `AGENTS.md`, `.agents/skills/`, `docs/`, `.github/`, and active issues instead.

Recommended review cadence:

- Weekly during active stabilization.
- Before every release checkpoint.
- After any major runtime incident or migration repair.

## Issue Standard

Every non-trivial documentation cleanup issue should include:

- Problem statement.
- Scope and non-scope.
- Current source-of-truth conflicts.
- Files or directories affected.
- Acceptance criteria.
- Verification plan.
- Known risks and rollback path.

## Pull Request Standard

Every documentation governance PR should include:

- Summary of promoted canonical docs.
- List of removed or archived scratch artifacts.
- Explicit statement that unrelated code changes were not staged.
- Verification command output or reason tests were not run.
- Risk notes for deleted or superseded documents.
- Link to the tracking issue.

## Cleanup Controls

Use the following controls before deleting documentation or generated artifacts:

- Verify `git status --short` and separate owned changes from unrelated work.
- Prefer deleting untracked scratch output only after promotion.
- Do not use broad recursive deletion in a dirty worktree unless the target is generated, ignored, and verified.
- Do not delete source-like data, migrations, tests, or integration docs as generic cleanup.
- Keep cleanup PRs narrow. Documentation policy changes should not be mixed with runtime code fixes.

## Runtime Truth Rules

Documentation must describe the runtime that exists, not the runtime that was planned.

For Wiii, this means:

- State whether a doc is current, historical, or proposed.
- Prefer measured runtime snapshots over manually maintained assumptions.
- Record feature flags and provider status from the running environment when making release decisions.
- Identify drift explicitly, especially around auth, memory, migration state, orchestration, and tool surfaces.
- Keep old architecture names only as compatibility notes when the live runtime has moved.
- Remove old architecture documents that still describe a superseded runtime as active.

## Review Gates

Documentation changes are ready for merge only when:

- The canonical index points to the new or updated documents.
- Superseded scratch reports are removed or explicitly left with a reason.
- The PR does not stage unrelated source changes.
- Follow-up runtime fixes are captured in issues rather than hidden in prose.
- The rollback path is obvious: revert the docs PR or restore a removed report from git history.
