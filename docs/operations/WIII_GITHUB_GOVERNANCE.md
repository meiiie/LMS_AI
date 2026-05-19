# Wiii GitHub Governance

Status: Active

Owner: Project leadership

Last updated: 2026-05-19

Applies to: issues, pull requests, branch protection, reviews, CodeRabbit, labels, merge readiness, release hygiene

## Executive Policy

GitHub is the operational control plane for Wiii engineering work.

Every non-trivial change must be traceable from issue to branch to pull request to verification evidence. The default standard is not "code exists"; the standard is "reviewers can understand scope, risk, validation, and rollback without reconstructing the investigation from chat history."

For multi-agent work, also follow `WIII_MULTI_AGENT_MAINTAINER_PROTOCOL.md`.

## Required Flow

1. Open or link an issue for non-trivial work.
2. Create a branch from `main` using the naming standard below.
3. Keep commits scoped and reviewable.
4. Open a draft PR early for visibility.
5. Move to ready-for-review only after verification evidence is present.
6. Merge only when branch protection, review, and risk gates pass.

## Naming Standard

Names are operational metadata. They must let a maintainer understand owner,
issue, risk, and outcome without opening five tabs.

Use lowercase ASCII, hyphen-separated words, and stable product/domain terms.
Avoid spaces, underscores, emoji, personal jokes, vague suffixes such as
`final`, `new`, `tmp`, `fix2`, or date-only names. Keep names short enough to
read in GitHub, terminal output, and deployment logs.

## Issue Naming

Issue titles describe the problem or outcome, not the implementation guess.

Good:

- `Guard raw provider tool-call JSON from rendering as chat text`
- `Document professional branch, PR, and naming standards`
- `Preserve LMS approval tokens through preview apply`

Avoid:

- `Fix bug`
- `Wiii broken again`
- `Do cleanup`
- `Try new agent architecture`

Issue titles may include a product area when it improves routing, but labels
remain the authoritative area/risk metadata.

## Branch Naming

Use these prefixes:

| Prefix | Use |
|---|---|
| `codex/` | Codex-authored implementation, docs, cleanup, or analysis work. Preferred for AI-assisted branches. |
| `fix/` | Human-authored production bug fix. |
| `feature/` | Product feature work. |
| `chore/` | Tooling, dependencies, cleanup, or build maintenance. |
| `docs/` | Documentation-only work. |
| `test/` | Test coverage, harnesses, fixtures, or smoke checks. |
| `ci/` | CI, GitHub Actions, deploy automation, or repository automation. |
| `refactor/` | Behavior-preserving code structure changes. |
| `hotfix/` | Urgent production repair. Requires explicit issue and rollback note. |

Canonical format:

```text
<prefix>/<issue-number>-<change-kind>-<outcome-slug>
```

For non-Codex human branches where the prefix already states the change kind,
the shorter form is allowed:

```text
<prefix>/<issue-number>-<outcome-slug>
```

Allowed change kinds:

| Kind | Use |
|---|---|
| `fix` | User-visible or operational defect repair. |
| `feat` | New product capability. |
| `docs` | Documentation and governance. |
| `test` | Tests, fixtures, smoke checks, or harnesses. |
| `refactor` | No intentional behavior change. |
| `chore` | Maintenance, dependency, generated config cleanup. |
| `ci` | GitHub Actions, deploy automation, release plumbing. |
| `perf` | Performance improvement with measurable target. |
| `security` | Security/privacy hardening. |
| `audit` | Investigation, inventory, recovery, or traceability work. |

Good:

- `codex/401-docs-github-naming-standard`
- `codex/399-fix-raw-tool-call-json`
- `fix/399-raw-tool-call-json`
- `feature/428-lms-course-preview`
- `hotfix/512-auth-refresh-loop`

Avoid:

- `codex/wiii-next`
- `fixbug`
- `final-cleanup`
- `new-ui-test`
- `codex/2026-05-19`

Use `noissue` only for genuinely trivial repository hygiene that cannot justify
an issue, for example `docs/noissue-readme-typo`. Do not use `noissue` for
runtime, auth, data, deployment, memory, LMS, provider, or governance changes.

## Branch Lifecycle

- Create branches from current `main`.
- Keep one objective per branch.
- Open a draft PR early when work is non-trivial.
- Delete remote and local branches after merge once the product worktree is
  synced.
- Before deleting old local branches, verify either the PR is merged or
  `git cherry origin/main <branch>` has no `+` commits.
- Keep named stashes only when they preserve valuable WIP; include date and
  reason in the stash message.

## Issue Rules

Use issue forms rather than blank issues.

Required issue properties:

- Clear problem or objective.
- Severity or category.
- Scope and non-scope.
- Acceptance criteria.
- Verification plan.
- Risk notes for auth, identity, memory, tenant isolation, migrations, provider/runtime behavior, or data exposure.

Do not use issues as vague reminders. If an issue cannot define success, it is not ready for implementation.

## Pull Request Rules

Every PR must include:

- Summary of user/system outcome.
- Linked issue or explicit reason no issue exists.
- In-scope and out-of-scope boundaries.
- PR owner, agents involved, owned paths, and conflict risk when multiple agents contribute.
- Exact verification commands and results.
- Rollback or recovery notes.
- Reviewer focus areas.

PR titles must be suitable as squash commit titles. Use Conventional Commit
style:

```text
<type>(<scope>): <imperative outcome>
```

The scope is optional for small changes:

```text
<type>: <imperative outcome>
```

Allowed PR title types:

| Type | Use |
|---|---|
| `fix` | Bug or regression repair. |
| `feat` | New product capability. |
| `docs` | Documentation-only change. |
| `test` | Test-only or harness change. |
| `refactor` | Behavior-preserving code movement. |
| `chore` | Maintenance with no product behavior change. |
| `ci` | CI/deploy automation. |
| `build` | Build system or dependency packaging. |
| `perf` | Performance improvement. |
| `revert` | Revert a previous change. |
| `security` | Security/privacy hardening. |

Preferred scopes are stable subsystem names such as `backend`, `desktop`,
`embed`, `lms`, `rag`, `voice`, `pointy`, `memory`, `auth`, `deploy`, `docs`,
`governance`, or `ci`.

Good:

- `fix(backend): route raw provider tool-call JSON`
- `docs(governance): add GitHub naming standard`
- `feat(lms): preview course drafts before approval apply`
- `ci(deploy): pin production image smoke checks`

Avoid:

- `Update files`
- `big cleanup`
- `WIP`
- `final fix`
- `[codex] stuff`

Use GitHub draft state for unfinished PRs; do not encode WIP state in the
title. PR titles may include the issue number only through GitHub metadata,
not as noisy title prefixes.

Every PR must avoid:

- Mixed unrelated changes.
- Hidden local environment changes.
- Secrets, tokens, real private data, or `.env*` files.
- Broad cleanup mixed with runtime behavior changes.
- Database schema changes without migration notes.

## Review Gates

Minimum review expectations:

- One approving review for normal changes.
- Owner review for auth, identity, memory, migration, tenant isolation, provider runtime, deployment, or GitHub governance changes.
- Reviewability gate passing for normal PRs. The default limit is 150 changed files and 20,000 total changed lines.
- CodeRabbit review/check resolved or explicitly documented as not applicable.
- Codex Review requested for high-risk changes once enabled, or explicitly documented as not required.
- Screenshot or recording evidence for frontend-visible changes.
- Explicit test evidence or explicit explanation when tests are not run.

High-risk PRs require extra scrutiny:

- Auth/JWT/OAuth/LMS token exchange.
- Cross-tenant data access.
- Semantic memory or long-term user memory.
- Streaming persistence and chat history.
- Alembic migrations and schema changes.
- Provider selection/failover behavior.
- MCP/tool exposure.
- Release/deployment configuration.

## Reviewability Gate

Wiii uses `.github/workflows/merge-gate.yml` to fail PRs that are too large for reliable human or automated review.

Default limits:

- Maximum changed files: 150.
- Maximum total changed lines: 20,000 additions plus deletions.

If a PR exceeds either limit, split it by subsystem before review. Good split boundaries include backend runtime, desktop UI, deployment, docs/governance, tests, or one feature flag at a time.

Maintainer bypass is allowed only for exceptional repository-wide work such as generated lockfile refreshes, mechanical renames, or emergency repair. The PR body must include:

- Why the change cannot be split safely.
- Which maintainer approved the bypass.
- Extra verification evidence that compensates for reduced reviewability.

Do not treat a green CodeRabbit status as sufficient when CodeRabbit states that review was skipped because the PR is too large.

## Current Branch Protection Baseline

As of 2026-04-26, `main` is configured with:

- Pull request required before merge.
- One approving review required.
- CODEOWNERS review required.
- Stale approvals dismissed when new commits are pushed.
- Last push approval required.
- Conversation resolution required.
- Branches must be up to date before merge.
- `CodeRabbit` required as a status check.
- Admin enforcement enabled.
- Linear history required.
- Force pushes disabled.
- Branch deletion disabled.

After `.github/workflows/merge-gate.yml` is merged into `main`, add `Gate Summary` as a required status check. Do not add the check before the workflow exists on `main`, or open PRs can become stuck on a missing required context.

Verify the live baseline with:

```bash
gh api repos/meiiie/wiii/branches/main/protection \
  --jq '{required_status_checks, required_pull_request_reviews, enforce_admins, required_linear_history}'
```

## Branch Protection Recommendation

Configure `main` with:

- Require pull request before merge.
- Require at least one approval.
- Dismiss stale approvals when new commits are pushed.
- Require CODEOWNERS review.
- Require last push approval when available.
- Require conversation resolution before merge.
- Require the `CodeRabbit` status check.
- Require the `Gate Summary` status check after the merge-gate workflow is stable on `main`.
- Require branches to be up to date before merge when practical.
- Block force pushes.
- Block branch deletion.
- Restrict who can bypass protections.

Recommended required checks:

- CodeRabbit.
- Gate Summary.
- CodeQL checks after they are consistently green across representative PRs.

Do not require currently failing CI checks until they are made consistently green on `main`; otherwise branch protection becomes noise instead of a control.

## CodeRabbit Policy

CodeRabbit is configured through `.coderabbit.yaml`.

For public/open-source repositories, CodeRabbit may evaluate PRs using the base-branch configuration. Policy changes in `.coderabbit.yaml` become authoritative after they are merged into `main`.

Repository policy:

- Review draft PRs and incremental pushes.
- Use assertive review profile for security, correctness, and maintainability.
- Fail CodeRabbit commit status when actionable review failures remain.
- Keep generated/dependency/local artifacts out of review scope.
- Apply path-specific instructions for auth, core config, multi-agent graph, RAG, living agent, MCP, migrations, frontend, GitHub automation, and operational docs.
- Suggest labels and reviewers, but do not auto-apply or auto-assign.
- Keep `request_changes_workflow` disabled until the team confirms CodeRabbit false-positive rate on real PRs.

Maintainers must resolve, defer, or explicitly reject CodeRabbit findings before merge. CodeRabbit does not replace human ownership.

## Codex Review Policy

Native Codex GitHub Review is configured outside the repository through Codex Settings, then guided by the top-level `AGENTS.md` file.

Repository policy:

- Keep a top-level `AGENTS.md` with a `## Review guidelines` section for Codex.
- Use manual `@codex review` comments for high-risk PRs until the team confirms the noise level is acceptable.
- Consider enabling Automatic reviews only after several useful manual reviews.
- Treat Codex Review as an additional P0/P1-focused review signal, not as a replacement for CodeRabbit, CODEOWNERS, or maintainer accountability.
- Resolve, defer with rationale, or explicitly reject actionable Codex findings before merge.
- If Codex Review is not run on a high-risk PR, document why in the PR body.

Setup and rollback details live in `docs/operations/WIII_CODEX_REVIEW_SETUP.md`.

## CODEOWNERS Policy

`CODEOWNERS` starts conservative with the repository owner as default owner.

As the team grows, split ownership by area:

- Backend platform.
- Frontend desktop.
- Auth/security.
- Data/migrations.
- AI runtime/provider layer.
- Documentation/governance.

Do not add fictional teams or inactive owners. CODEOWNERS must route reviews to people who can actually approve.

## Label Taxonomy

Recommended labels:

| Label | Meaning |
|---|---|
| `bug` | Defect or regression. |
| `enhancement` | Product or platform improvement. |
| `maintenance` | Cleanup, governance, tooling, dependency, or operational work. |
| `needs-triage` | Issue needs prioritization and ownership. |
| `priority:P0` | Release blocker, security/data risk, or production outage. |
| `priority:P1` | Major path broken or high-impact regression. |
| `priority:P2` | Important but workaround exists. |
| `area:backend` | Backend API/service/runtime. |
| `area:frontend` | Desktop/web UI. |
| `area:memory` | Semantic memory, core memory, identity continuity. |
| `area:auth` | Auth, OAuth, JWT, LMS token exchange. |
| `area:rag` | Retrieval, ingestion, embeddings, citations. |
| `area:mcp-tools` | MCP, tool registry, tool execution. |
| `area:docs` | Documentation and governance. |
| `risk:migration` | Database/schema risk. |
| `risk:security` | Security/privacy/tenant-isolation risk. |

Labels should clarify routing and risk. Avoid label sprawl.

Label naming rules:

- `area:<name>` labels identify ownership and routing.
- `risk:<name>` labels mark review hazards.
- `priority:P0`, `priority:P1`, and `priority:P2` labels communicate urgency.
- General labels use short lowercase nouns such as `bug`, `enhancement`, and
  `maintenance`.
- One-off labels for a single PR, agent, or experiment are not allowed.

## Documentation, Release, and Artifact Names

Operational documentation should use stable, searchable names:

- Runbooks: `WIII_<AREA>_RUNBOOK.md`
- Governance docs: `WIII_<AREA>_GOVERNANCE.md`
- Durable standards: `WIII_<AREA>_STANDARD.md`
- Temporary dated audits: `WIII_<AREA>_AUDIT_YYYY-MM-DD.md`

Examples:

- `WIII_GITHUB_GOVERNANCE.md`
- `WIII_AGENTIC_CODEBASE_HARNESS.md`
- `WIII_REPO_RECOVERY_AUDIT_2026-05-19.md`

Local scratch artifacts must stay ignored unless explicitly promoted:

- Use `artifacts/YYYYMMDD-<purpose>/` for local evidence bundles.
- Use `docs/assets/screenshots/<issue>-<purpose>.png` only when the image is
  durable PR evidence.
- Do not commit `tmp`, `final`, `new`, or personal desktop export names.

Release and deploy identifiers must be traceable to git:

- Human release notes: `YYYY-MM-DD <scope> release`.
- Git tags, when used: `wiii-vYYYY.MM.DD.N`.
- Container/deploy references must include an immutable commit SHA or digest.
- Smoke sessions should include issue or PR context when practical, for example
  `smoke-pr400-raw-tool-call-json`.

## Commit Standard

Use concise conventional-style subjects:

- `fix: guard service identity memory writes`
- `feat: add host action capability matrix`
- `docs: add repository hygiene audit`
- `chore: remove legacy report artifacts`
- `test: cover stream cancellation persistence`

Commit rules:

- One logical change per commit.
- Do not commit generated caches or local dependency folders.
- Do not commit unrelated worktree changes.
- Do not amend shared commits unless explicitly agreed.
- The final squash title should match the PR title unless the maintainer
  intentionally sharpens it at merge time.
- Commit bodies should explain why and how verification was done when risk is
  non-obvious.

## Merge Strategy

Default strategy:

- Squash merge for multi-commit feature/docs/cleanup PRs.
- Rebase merge only for clean linear human-curated commits.
- Merge commit only when preserving branch topology matters.

PR title should become the squash commit title.

## Release Readiness

A PR is release-ready only when:

- Issue acceptance criteria are satisfied.
- Verification evidence is present.
- Documentation is updated when behavior, operations, or public contracts change.
- Rollback path is documented.
- Feature flags and defaults are understood.
- No unrelated modified files are included.

## Cleanup and Generated Artifacts

Repository hygiene rules:

- Do not commit `.Codex/`, `.claude/`, dependency folders, caches, logs, screenshots, local probes, or local test outputs.
- Promote durable findings into `docs/operations/` or the relevant product docs.
- Keep cleanup PRs separate from behavior changes.
- Use explicit deletion targets instead of broad clean commands.

## Emergency Work

For urgent production fixes:

1. Open a `hotfix/` branch.
2. Link an incident or bug issue.
3. Keep scope minimal.
4. Include exact rollback.
5. Backfill tests and documentation immediately after stabilization.

Hotfix urgency does not waive review. It changes review speed, not review quality.
