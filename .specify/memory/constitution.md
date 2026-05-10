# Wiii Constitution

Status: Active

Owner: Project leadership

Ratified: 2026-05-09

Last amended: 2026-05-10

## Core Principles

### I. Native Runtime Ownership
Wiii owns its runtime. New orchestration, routing, tool execution, memory, RAG, streaming, and provider code must use WiiiRunner-native contracts instead of adding framework lock-in. LangChain and LangGraph are not active runtime dependencies; any remaining references must be treated as historical, compatibility, or cleanup-tracking context unless a specific file proves otherwise.

Runtime changes must preserve explicit message, tool, model, and stream contracts. Adapters for OpenAI-compatible, Gemini, NVIDIA, DeepSeek, Anthropic, LMS, MCP, browser, or future providers must remain thin boundary layers around Wiii-native types.

### II. Living Memory With Tenant Safety
Wiii should feel continuous, but memory must be disciplined. Persona, human facts, relationship state, goals, craft preferences, episodic recall, and world/context memory must remain separable, inspectable, and testable. Memory must fail closed across users, organizations, and LMS tenants.

Any change touching semantic memory, long-term memory, chat history, identity, pronoun resolution, compacting, or recall must include tests or an explicit verification note for continuity, privacy boundaries, and UI-visible behavior.

### III. Streaming-First User Experience
Wiii must not appear silent while doing work. Chat, tool, RAG, visual, code, simulation, and host-action flows must emit timely SSE V3 status, thinking, metadata, answer, error, and done/finalization events. Sync and streaming endpoints must stay behaviorally aligned unless a documented feature flag intentionally differs.

Provider health, route/supervisor latency, tool latency, finalization guards, and fallback decisions must be observable through structured telemetry. Slow paths should be measured before being redesigned.

### IV. Safe Tools, Visuals, And Host Control
Tool execution and host control are high-risk product surfaces. Pointy, LMS bridge, browser-like actions, RAG tools, web search/fetch, code studio, document/video context, voice, and simulations must use explicit contracts, stable selectors or body schemas, safe defaults, and fail-closed behavior.

Mutating actions such as submit, pay, enroll, delete, logout, or irreversible navigation require stronger gating than highlight, scroll, cursor, tour, read, search, or explain. Visual and simulation outputs must be accessible, responsive, patchable, and grounded in user intent.

### V. Multi-Agent Change Discipline
Many agents may work on Wiii at the same time, so every non-trivial change must stay narrow, reviewable, and issue-linked. Do not mix cleanup, docs, runtime behavior, migrations, UI refactors, dependency changes, and governance changes unless the issue explicitly calls for it.

Agents must protect unrelated dirty work, never revert changes they did not make, and report exact verification commands. PRs must include risk, rollback, and test notes for backend, auth, memory, tenant isolation, provider/runtime, MCP, deployment, and streaming changes.

## Current Runtime Constraints

The canonical source of truth is `AGENTS.md`, `docs/`, `.github/`, `.agents/skills/`, active GitHub issues, and current code. Legacy local scratch folders such as `.claude/` and `.Codex/` must stay ignored and must not be treated as governance, runtime, or architecture truth.

Wiii currently centers on these production surfaces:

- `maritime-ai-service/`: FastAPI backend, WiiiRunner orchestration, native message/tool/provider contracts, RAG/CRAG, semantic memory, auth, org context, LMS integration, deployment assets, and backend tests.
- `wiii-desktop/`: Tauri v2 desktop app, React 18, TypeScript, Zustand stores, SSE V3 UI, embed surfaces, Pointy host runtime, frontend tests, and E2E smoke coverage.
- `docs/`: architecture, operations, governance, pipeline plans, demo runbooks, integration notes, and future SDD/spec artifacts.
- `.github/`: issue templates, PR template, CODEOWNERS, Actions, Dependabot, CodeRabbit/Codex review automation, and merge governance.

## Spec-Driven Workflow

Use Spec Kit for architecture-sensitive, ambiguous, cross-agent, or multi-phase work. Small safe fixes may remain direct PRs when the issue and scope are obvious.

Preferred flow:

- `$speckit-constitution`: update governing principles when project rules change.
- `$speckit-specify`: capture user-visible behavior and non-goals before design.
- `$speckit-plan`: map contracts, data flow, tests, risk, and rollback.
- `$speckit-tasks`: split implementation into dependency-ordered tasks suitable for multiple agents.
- `$speckit-implement`: execute only after the spec, plan, and tasks are coherent.

Spec artifacts must be treated as living review artifacts. If implementation drifts, update the relevant spec or plan in the same PR.

## Quality Gates

Choose the smallest meaningful verification set for changed paths and report exact commands and results.

Required by surface:

- Backend/runtime/provider/memory/RAG/tooling: targeted `pytest`, `ruff check app/ --select=E9,F63,F7`, and contract tests for changed flows.
- Desktop/embed/Pointy/UI: targeted `vitest`, `npx tsc --noEmit`, `npm run build:embed` or `npm run build:pointy` when relevant.
- Governance/docs/spec changes: `git diff --check`, link to issue/PR, and consistency check against `AGENTS.md` plus current active docs.
- High-risk auth, tenant, memory, provider, migration, MCP, and deployment changes: risk, rollback, and failure-mode notes.

## Governance

This constitution complements `AGENTS.md` and `docs/operations/WIII_GITHUB_GOVERNANCE.md`. If guidance conflicts, the stricter production-safety rule wins, and the conflict must be resolved in the next governance PR.

Amendments require a documented rationale, scope, migration notes when behavior changes, and review from project leadership or an explicitly delegated maintainer.

**Version**: 1.0.1 | **Ratified**: 2026-05-09 | **Last Amended**: 2026-05-10
