# Wiii Branch Protection Policy

Status: Active

Owner: Project leadership

Last updated: 2026-08-16

Applies to: `main`, release branches, hotfix branches, merge-queue config, required checks, review requirements, agent PR hygiene

## Why this document exists

Branch protection is configured in GitHub's UI, not in a file. If the UI config drifts from policy, the repo quietly loses its guarantees. This document is the single source of truth: maintainers reconcile GitHub settings against this file, and any change to policy must land here first.

This matters more for Wiii than for a typical repo because multiple AI agents (Codex, Claude, CodeRabbit, and more in future) file pull requests in parallel. Branch protection must guarantee traceability and machine-verifiable evidence without manufacturing approval through a second account controlled by the same maintainer.

## `main` — Required Settings

Configure under **Settings → Branches → Branch protection rules → `main`**.

### Review requirements

- **Require a pull request before merging**: ✅
- **Required approving reviews**: **0**
- **Dismiss stale reviews when new commits are pushed**: ❌
- **Require review from Code Owners**: ❌
- **Require approval of the most recent push**: ❌
- **Allow specified actors to bypass required pull requests**: ❌

Reviews remain encouraged and risk-based. `CODEOWNERS` routes expertise and review requests, but neither a human approval nor a second maintainer account is a merge token. Actionable review findings and every review conversation still must be resolved.

### Status check requirements

- **Require status checks to pass before merging**: ✅
- **Require branches to be up to date before merging**: ✅
- **Required status check**: `Gate Summary` from `merge-gate.yml`

`Gate Summary` is the stable aggregate contract. It fails closed when the change-specific backend, desktop, governance, hygiene, or reviewability gates it owns do not pass. Other CI, CodeQL, image, security, and release checks remain visible evidence and should be allowed to finish before high-risk merges even when GitHub does not list them as separate required contexts.

### Merge rules

- **Require conversation resolution before merging**: ✅ (CodeRabbit-suggested conversations count)
- **Require signed commits**: ❌ (recommended, but not enforced until every supported automation identity can sign reliably)
- **Require linear history**: ✅ (squash or rebase — no merge commits)
- **Require deployments to succeed before merging**: ❌ (deployments are manual for now)
- **Lock branch**: ❌
- **Do not allow bypassing the above settings**: ⚠️ `enforce_admins: false`; normal owner workflow still uses a PR and waits for `Gate Summary`. Admin bypass is reserved for documented recovery.

### Push rules

- **Restrict who can push to matching branches**: ❌ (the required-PR rule is the write boundary)
- **Allow force pushes**: ❌
- **Allow deletions**: ❌

### Merge queue (optional once agent PR volume > ~20/week)

- **Require merge queue**: ❌ today
- **Merge method**: Squash
- **Build concurrency**: 5
- **Minimum group size**: 1 (one PR per queue entry — merging groups risks coupling unrelated changes)
- **Maximum group size**: 3
- **Wait time before merging**: 5 minutes (lets CodeRabbit finish async review)

## Release branches (`release/*`, `hotfix/*`)

Same rules as `main`, except:

- Only maintainers can create or merge
- Backports must link to the original `main` PR
- Hotfix branches must include a rollback note in the PR body

## Branch naming — enforced via CODEOWNERS and workflow

Branch prefixes and their meaning live in `docs/operations/WIII_GITHUB_GOVERNANCE.md` (`codex/`, `fix/`, `feature/`, `chore/`, `docs/`, `hotfix/`). Mergeable PRs must originate from one of these prefixes.

## Agent identity and attribution

Automated agents that push commits or open PRs must:

1. Use a **dedicated bot GitHub account** (recommended: `wiii-codex[bot]`, `wiii-claude[bot]`). Shared real-human credentials are prohibited.
2. **Sign commits** using the bot account's verified key.
3. Record the producing model in the commit trailer, for example:
   ```
   Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
   Co-Authored-By: Codex gpt-5-mini <noreply@openai.com>
   ```
4. Open PRs as the bot account. A human PR owner declares themselves in the PR template's `PR owner` field and is accountable for the final diff.

Why: agent-produced commits under a human's account distort attribution and make post-incident review harder. A bot account with a verified key is explicit and revocable.

## Owner-directed risk-based review policy

Adopted: 2026-08-16, tracked by issue #925.

Wiii requires PR traceability, a current `Gate Summary`, linear history, and resolution of review conversations. It does not require an approval, CODEOWNERS approval, stale-review dismissal, or last-push approval at the branch level. This removes the incentive to switch to `@wiiiii123` merely to manufacture an approval from another account controlled by the same maintainer.

`CODEOWNERS` remains useful ownership and routing metadata. Review should be requested when an independent reviewer with relevant expertise is available, especially for security, identity, migrations, release signing, tool execution, and workflow changes. If no independent reviewer is available, the PR owner records risk, rollback, and verification evidence and waits for all relevant automated checks.

`enforce_admins: false` remains a recovery valve, not the normal merge path. A use of `--admin` that skips a required setting is a bypass event and must be logged. Reconsider mandatory approvals when the project has at least two genuinely independent active maintainers or if incident evidence shows the risk-based policy is insufficient.

## CODEOWNERS routing

- **@meiiie** — primary maintainer and repository admin.
- **@wiiiii123** — secondary ownership contact retained for routing and continuity.

Both may review, but neither identity is required to unlock a merge. Add future owners to represent real responsibility, not to satisfy a mechanical approval count.

## Bypass and emergency repair

- Bypassing branch protection requires a human maintainer to temporarily disable the rule, perform the change, then re-enable.
- Every bypass event must:
  - Be logged in `docs/operations/BYPASS_LOG.md` within 24 hours.
  - Include: date, actor, branch, reason, linked incident ticket, re-enable confirmation.
- Repeated bypasses (3+ per quarter) trigger a policy review PR to this file.

## Dependabot and automated PRs

- Dependabot PRs require a PR, the current required checks, and resolved conversations; approval remains risk-based.
- Auto-merge is permitted **only** for:
  - Patch updates
  - Security-only updates
  - Grouped updates explicitly allow-listed in `.github/dependabot.yml`
- Any major-version Dependabot PR must be reviewed manually.

## Review escalation for sensitive paths

For PRs touching any of these paths, request independent domain review when available and wait for all relevant automated checks:

- `maritime-ai-service/app/auth/**` — identity, tokens, OAuth flows
- `maritime-ai-service/app/core/security*.py` — authorization, role resolution
- `maritime-ai-service/alembic/**` — database schema and migrations
- `.github/workflows/**` — CI / automation surface
- `maritime-ai-service/app/mcp/**` — external tool exposure

These paths are also flagged in `.coderabbit.yaml` `path_instructions` for deeper review.

## Reconciliation checklist (run quarterly)

Maintainer re-walks this list each quarter and opens an `Operations` issue for any drift:

1. GitHub UI `main` rule matches the _Required Settings_ section above: PR required, zero required approvals, strict `Gate Summary`, conversation resolution, linear history, and no force-push/deletion.
2. `CODEOWNERS` reflects real routing responsibility; it is not treated as a required-review gate.
3. `.github/workflows/*.yml` job names still match the _Required status checks_ list.
4. `.coderabbit.yaml` is present and has not been disabled.
5. Dependabot auto-merge allowlist has not silently expanded.
6. No bypass events were unlogged.
7. The risk-based review policy still matches maintainer capacity and incident evidence.

## Related Documents

- `docs/operations/WIII_GITHUB_GOVERNANCE.md` — the broader GitHub workflow policy.
- `docs/operations/WIII_MULTI_AGENT_MAINTAINER_PROTOCOL.md` — agent ownership rules.
- `CODE_OF_CONDUCT.md` — contributor behavior baseline.
- `SECURITY.md` — vulnerability disclosure.
- `CONTRIBUTING.md` — branching, commits, review expectations for contributors.
