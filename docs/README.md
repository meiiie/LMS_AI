# Repository Documentation Layout

Use this folder for repository-level documentation that explains the product, the codebase, and major implementation decisions.

## Primary Entry Points

- `../README.md`: repository overview and deployment model
- `WIII_PROJECT_MENTAL_MODEL.md`: one-page product and system mental model
- `WIII_ARCHITECTURE_AUDIT.md`: opinionated audit of architectural center, strengths, and risk areas
- `WIII_TECHNICAL_SIMPLIFICATION_ROADMAP.md`: phased simplification plan and first landed slice
- `plans/2026-04-27-wiii-native-orchestration-rfc.md`: phased RFC for replacing remaining LangGraph assumptions with Wiii-owned runtime contracts
- `plans/2026-04-28-wiii-pipeline-simplification-plan.md`: current request/auth/memory/router/agent/tool/RAG/stream lifecycle and safe LangGraph/history/compat cleanup plan
- `operations/WIII_DOCUMENTATION_GOVERNANCE.md`: documentation lifecycle, cleanup controls, and issue/PR standards
- `operations/WIII_GITHUB_GOVERNANCE.md`: GitHub issue, PR, branch, review, label, and merge standards
- `operations/WIII_CODEX_REVIEW_SETUP.md`: Codex GitHub Review setup, rollout, operating policy, and rollback controls
- `operations/WIII_MULTI_AGENT_MAINTAINER_PROTOCOL.md`: multi-agent ownership, maintainer review, CodeRabbit, conflict, and merge protocol
- `operations/WIII_PRODUCT_RELEASE_RUNBOOK.md`: product release lane, pinned deploys, smoke gates, rollback, and parallel-team safety
- `operations/WIII_SYSTEM_CLEANUP_CHECKPOINT_2026-04-24.md`: current operational cleanup checkpoint and runtime truth snapshot
- `operations/WIII_REPOSITORY_HYGIENE_AUDIT_2026-04-24.md`: final cleanup verification, retained local artifacts, and rebuild runbook
- `../maritime-ai-service/docs/architecture/SYSTEM_ARCHITECTURE.md`: authoritative system architecture
- `../maritime-ai-service/docs/architecture/SYSTEM_FLOW.md`: technical request and streaming flow
- `../maritime-ai-service/docs/integration/WIII_LMS_INTEGRATION.md`: LMS contract and security model
- `../maritime-ai-service/scripts/deploy/README.md`: production deployment runbook
- `../wiii-desktop/README.md`: desktop app architecture and local workflow

## Current Layout

- `plans/`: committed design notes, implementation plans, and sprint writeups
- `operations/`: reviewed operational checkpoints, cleanup governance, release controls, and runtime truth documents
- `assets/`: committed screenshots, diagrams, and other documentation assets

## Rules

- Keep repository-wide documentation here, not in the repository root.
- Put screenshots and other doc assets under `docs/assets/`.
- Put stable planning and design documents under `docs/plans/`.
- Put reviewed cleanup, release, and governance documents under `docs/operations/`.
- Keep desktop-only docs under `wiii-desktop/docs/`.
- Do not commit agent-generated working reports. Keep temporary reports in ignored local scratch paths and promote durable findings into canonical docs.
