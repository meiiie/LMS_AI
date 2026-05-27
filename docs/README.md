# Repository Documentation Layout

Use this folder for repository-level documentation that explains the product, the codebase, and major implementation decisions.

## Primary Entry Points

- `../README.md`: repository overview and deployment model
- `WIII_PROJECT_MENTAL_MODEL.md`: one-page product and system mental model
- `architecture/WIII_CODEBASE_MAP.md`: concise codebase map for maintainers and coding agents
- `architecture/wiii-connect/README.md`: Wiii Connect blueprint for connection registry, capability governor, provider adapters, and extraction criteria
- `architecture/wiii-connect/CONNECTION_CONTRACT_V0.md`: first Wiii Connect connection and path capability contract
- `WIII_ARCHITECTURE_AUDIT.md`: opinionated audit of architectural center, strengths, and risk areas
- `WIII_TECHNICAL_SIMPLIFICATION_ROADMAP.md`: phased simplification plan and first landed slice
- `operations/WIII_AGENTIC_CODEBASE_HARNESS.md`: large-codebase agent workflow, context layering, and WIP recovery pattern
- `operations/WIII_SYSTEM_CONTROL_PLANE.md`: whole-system operating map, active flow monitoring ladder, and debugging protocol
- `operations/WIII_SELF_HARNESS.md`: static scenario harness for active product-path contracts
- `operations/WIII_REFERENCE_SYSTEMS_AUDIT_2026-05-25.md`: external reference systems audit baseline and local clone workspace
- `operations/WIII_OPENHUMAN_REFERENCE_AUDIT_2026-05-26.md`: OpenHuman-derived memory/context provenance audit and Wiii context ledger requirements
- `operations/WIII_OPENCLAW_REFERENCE_AUDIT_2026-05-25.md`: OpenClaw-derived control-plane audit and Wiii runtime ledger/chat baseline requirements
- `plans/2026-04-27-wiii-native-orchestration-rfc.md`: phased RFC for replacing remaining LangGraph assumptions with Wiii-owned runtime contracts
- `plans/2026-04-28-wiii-pipeline-simplification-plan.md`: current request/auth/memory/router/agent/tool/RAG/stream lifecycle and safe LangGraph/history/compat cleanup plan
- `operations/WIII_DOCUMENTATION_GOVERNANCE.md`: documentation lifecycle, cleanup controls, and issue/PR standards
- `operations/WIII_GITHUB_GOVERNANCE.md`: GitHub issue, PR, branch, review, label, and merge standards
- `operations/WIII_SPEC_KIT_WORKFLOW.md`: Spec Kit constitution, specification, planning, and multi-agent workflow for Wiii
- `operations/WIII_CODEX_REVIEW_SETUP.md`: Codex GitHub Review setup, rollout, operating policy, and rollback controls
- `operations/WIII_MULTI_AGENT_MAINTAINER_PROTOCOL.md`: multi-agent ownership, maintainer review, CodeRabbit, conflict, and merge protocol
- `operations/WIII_PRODUCT_RELEASE_RUNBOOK.md`: product release lane, pinned deploys, smoke gates, rollback, and parallel-team safety
- `operations/WIII_PRODUCTION_AUTH_RUNBOOK.md`: production Magic Link and Google OAuth setup, smoke tests, and rollback
- `../maritime-ai-service/docs/architecture/SYSTEM_ARCHITECTURE.md`: authoritative system architecture
- `../maritime-ai-service/docs/architecture/SYSTEM_FLOW.md`: technical request and streaming flow
- `../maritime-ai-service/docs/integration/WIII_LMS_INTEGRATION.md`: LMS contract and security model
- `../maritime-ai-service/scripts/deploy/README.md`: production deployment runbook
- `../wiii-desktop/README.md`: desktop app architecture and local workflow

## Current Layout

- `plans/`: reviewed design notes and active implementation plans
- `operations/`: reviewed governance, release, auth, and runtime operation documents
- `architecture/`: current maps and contracts for navigating the system
- `assets/`: committed documentation assets that are referenced by canonical docs

## Archive / Audit Log

- `operations/WIII_REPO_RECOVERY_AUDIT_2026-05-19.md`: temporary/history recovery record for issue #397; durable process guidance lives in `operations/WIII_AGENTIC_CODEBASE_HARNESS.md`.

## Rules

- Keep repository-wide documentation here, not in the repository root.
- Put screenshots and other doc assets under `docs/assets/`.
- Put stable planning and design documents under `docs/plans/`.
- Put reviewed cleanup, release, and governance documents under `docs/operations/`.
- Keep desktop-only docs under `wiii-desktop/docs/`.
- Do not commit agent-generated working reports. Keep temporary reports in ignored local scratch paths and promote durable findings into canonical docs.
- Delete superseded checkpoints, sprint reports, and unreferenced screenshots after their durable content is represented by the current runbooks or GitHub issues.
