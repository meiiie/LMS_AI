# Wiii Operations Documentation

This directory contains controlled operational documentation for Wiii.

Operational docs are different from exploratory reports:

- They describe the current source of truth for release, cleanup, governance, and runtime decisions.
- They are expected to be reviewed through issue and pull request flow.
- They must include status, date, scope, evidence, and follow-up ownership when relevant.

## Documents

- `WIII_DOCUMENTATION_GOVERNANCE.md`: documentation lifecycle, retention, issue/PR standards, and cleanup controls.
- `WIII_GITHUB_GOVERNANCE.md`: GitHub issue, PR, branch, review, label, and merge standards.
- `WIII_BRANCH_PROTECTION.md`: desired `main` branch protection settings, review requirements, and admin override policy.
- `WIII_CODEX_REVIEW_SETUP.md`: Codex GitHub Review setup, rollout, operating policy, and rollback controls.
- `WIII_LOCAL_DEMO_RUNBOOK.md`: local demo login contract, smoke gate, browser state recovery, and OpenAI Agents SDK-inspired runtime lessons.
- `WIII_PRODUCTION_AUTH_RUNBOOK.md`: production Magic Link and Google OAuth enablement, fail-closed behavior, smoke tests, and rollback.
- `WIII_PRODUCT_RELEASE_RUNBOOK.md`: production deploy lane, pinned-image rollout, smoke gates, rollback, and parallel-team safety.
- `WIII_MULTI_AGENT_MAINTAINER_PROTOCOL.md`: multi-agent ownership, maintainer review, CodeRabbit, conflict, and merge protocol.
- `BYPASS_LOG.md`: audited record of branch-protection bypasses, rationale, and restored controls.

## Promotion Rule

Working reports may start in `.Codex/reports/` or `.claude/reports/`, but any report that should guide engineering work must be promoted here or into the relevant product area docs before it becomes authoritative.

Historical checkpoints and one-off audits should not stay in this directory after
their durable findings have moved into current runbooks, active issues, or git
history.
