# Wiii Multi-Agent Maintainer Protocol

Status: Active

Owner: Project leadership

Last updated: 2026-08-16

Applies to: Codex agents, human maintainers, CodeRabbit, PR ownership, file ownership, review gates, conflict control

## Executive Policy

Wiii uses multiple agents in the same repository. That increases throughput, but it also increases the chance of overlapping edits, hidden context loss, accidental cleanup, and unreviewed behavioral changes.

The maintainer protocol exists to make every change attributable, reviewable, and reversible. The default rule is simple: one PR should have one owner, one purpose, explicit file ownership, and enough verification evidence that another maintainer can safely merge or reject it without reading private chat history.

## Roles

| Role | Responsibility |
|---|---|
| PR Owner | Owns scope, branch hygiene, final diff, verification evidence, and merge readiness. |
| Implementing Agent | Makes scoped edits inside declared ownership boundaries. |
| Reviewer Agent | Reviews for bugs, regressions, missing tests, and policy violations. |
| CodeRabbit | Automated review assistant for risk discovery and reviewer routing. |
| Human Maintainer | Final authority for merge, bypass, rollback, and production risk acceptance. |

CodeRabbit is advisory. It may block through required checks, but it does not replace maintainer judgment.

## Branch and PR Ownership

Every non-trivial branch must declare:

- PR owner.
- Linked issue.
- Change purpose.
- Owned file paths or subsystems.
- Out-of-scope areas.
- Verification plan.

For agent-heavy work, add the ownership declaration in the PR body before implementation is broad enough to conflict with another agent.

Recommended ownership block:

```text
PR owner:
Agents involved:
Owned paths:
Out-of-scope paths:
Conflict risk:
Verification owner:
Merge decision owner:
```

## File Ownership Rules

Only one active agent should own a subsystem at a time unless the PR owner explicitly splits work into disjoint paths.

Safe examples:

- Agent A owns `maritime-ai-service/app/auth/**`.
- Agent B owns `wiii-desktop/src/components/settings/**`.
- Agent C owns `docs/operations/**`.

Unsafe examples:

- Two agents both refactor `supervisor.py`.
- One agent formats all backend files while another edits RAG behavior.
- Cleanup deletes generated-looking files without checking whether scripts reference them.

If ownership overlaps, stop and resolve before editing. Do not rely on later merge conflict resolution to discover product-level conflicts.

## Multi-Agent Handoff Format

Every agent handoff must include:

- Goal completed or current blocker.
- Files changed.
- Files intentionally not touched.
- Tests or checks run.
- Known risks.
- Next suggested action.

Do not hand off vague state such as "mostly done" or "needs cleanup" without file paths and verification status.

## PR Lifecycle

1. Create or link issue.
2. Create branch from fresh `main`.
3. Open draft PR early.
4. Declare ownership and out-of-scope paths.
5. Commit in logical slices.
6. Keep the PR draft while tests, docs, or review evidence are incomplete.
7. Request review only after the diff is coherent and verification is documented.
8. Resolve CodeRabbit and human review conversations before merge.
9. Squash merge unless a maintainer explicitly chooses another strategy.

## Required Merge Gates

Minimum gates for `main`:

- Pull request required.
- Zero approving reviews required; request review according to risk and expertise.
- CODEOWNERS routes expertise but is not a merge gate.
- All review conversations resolved.
- Strict `Gate Summary` required.
- Force pushes blocked.
- Branch deletion blocked.

All relevant CI failures must be visible and addressed in the merge decision even when only the aggregate `Gate Summary` is configured as a required context.

## CodeRabbit Operating Rules

CodeRabbit should:

- Review draft PRs for early feedback.
- Run incremental reviews on new commits.
- Use path-specific instructions for auth, memory, RAG, MCP, desktop, migrations, and GitHub governance.
- Suggest labels but not auto-apply them.
- Keep review tone technical and direct.
- Treat governance and CI changes as high-risk.

CodeRabbit should not be used to justify broad automated rewrites. A maintainer must still verify whether comments are valid in Wiii's architecture.

## Maintainer Review Checklist

Before approving, verify:

- Scope matches the linked issue.
- PR body lists exact verification evidence.
- No unrelated dirty worktree changes are included.
- No secrets, local config, cache, dependency folders, binaries, or private data are committed.
- Auth, tenant isolation, memory continuity, MCP/tool exposure, and migrations were considered when relevant.
- Frontend-visible changes include UI evidence or a clear reason why not.
- Rollback path is concrete.
- CodeRabbit findings are resolved, intentionally deferred, or explicitly rejected with rationale.

## Conflict Protocol

When a conflict or unexpected dirty file appears:

1. Stop broad edits.
2. Identify owner, branch, file, and intended behavior.
3. Preserve user or other-agent changes.
4. Resolve by narrow patch, not wholesale replacement.
5. Re-run relevant checks.
6. Document the resolution in the PR.

Never use destructive reset, checkout, or clean commands to force progress unless the maintainer explicitly approves the exact target.

## Prohibited Patterns

Do not:

- Use `git add -A` on a shared dirty worktree.
- Commit `.env*`, tokens, local secrets, or private data.
- Commit dependency folders, caches, logs, screenshots, or local test outputs.
- Mix repository cleanup with runtime behavior changes.
- Force-push shared branches without explicit maintainer approval.
- Rewrite migrations without a migration safety note.
- Delete data files, binaries, or PDFs without checking references.
- Treat generated-looking files as disposable without proving they are unreferenced.

## Required PR Comment for Agent Work

For PRs with multiple agents or large automated edits, add a comment before ready-for-review:

```text
Agent coordination summary

PR owner:
Agents involved:
Owned paths:
Conflict checks:
CodeRabbit status:
Verification:
Known risks:
Ready-for-review decision:
```

This comment is required because chat transcripts are not a stable audit trail.

## Current Repository Policy

The repository currently uses classic branch protection rather than GitHub rulesets. This is sufficient for the current single-maintainer repository. Move to rulesets when multiple GitHub teams exist or when environment-specific bypass rules are needed.

Branch protection should require CodeRabbit now. Backend, desktop, and image-build checks should become required after those workflows are consistently green on `main`.
