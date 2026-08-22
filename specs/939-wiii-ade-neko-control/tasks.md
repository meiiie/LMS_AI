# Tasks: Wiii ADE and Neko Control Foundation

**Input**: `specs/939-wiii-ade-neko-control/`  
**Issue**: #939

## Phase 1: Specification and baseline

- [x] T001 Create issue #939 and branch from current `main`.
- [x] T002 Write spec, research decisions, data model, protocol, plan,
  quickstart and task artifacts.
- [x] T003 Record focused pre-change test/typecheck baseline (39 focused
  Vitest tests and TypeScript passed on 2026-08-23).

## Phase 2: Wiii ADE ontology (US1)

- [ ] T101 [US1] Add failing graph-validation tests in
  `wiii-desktop/src/__tests__/ade/domain.test.ts`.
- [ ] T102 [US1] Implement JSON-compatible entity contracts and graph
  validation in `wiii-desktop/src/ade/domain.ts`.
- [ ] T103 [US1] Prove one task can own multiple runs/sessions without identity
  conflation.

## Phase 3: Neko control and provider truth (US2)

- [ ] T201 [US2] Add failing control envelope/version tests in
  `wiii-desktop/src/__tests__/neko/control-protocol.test.ts`.
- [ ] T202 [US2] Implement `src/neko/control-protocol.ts` with stable error
  codes and fail-closed parsing.
- [ ] T203 [US2] Add failing provider registry/launch tests in
  `wiii-desktop/src/__tests__/neko/provider-registry.test.ts`.
- [ ] T204 [US2] Implement `src/neko/contracts.ts` and
  `src/neko/provider-registry.ts` for Neko Core, Gemini CLI and Codex.
- [ ] T205 [US2] Implement the replaceable Tauri control client in
  `src/neko/control-client.ts` and route agent discovery/profile/spawn through
  it.
- [ ] T206 [US2] Derive local Workbench runtime capability entries from the
  production provider registry.

## Phase 4: Historical capability snapshots (US3)

- [ ] T301 [US3] Add failing runtime/session-event tests for snapshot creation,
  round-trip validation and legacy compatibility.
- [ ] T302 [US3] Let drivers publish established provider capabilities without
  exposing protocol-specific payloads.
- [ ] T303 [US3] Persist the versioned capability snapshot in
  `runtime-attached` events and accept legacy events without it.
- [ ] T304 [US3] Verify unknown provider IDs and unbounded extensions fail
  closed.

## Phase 5: Verification and review

- [ ] T401 Run focused Vitest and TypeScript checks.
- [ ] T402 Run affected web/embed builds and repository hygiene checks.
- [ ] T403 Update task status and architecture documentation to match the
  implementation exactly.
- [ ] T404 Commit, push, open the issue-linked PR with risk/rollback evidence,
  and resolve relevant review/CI findings.

## Dependencies

1. Phase 1 defines the contract.
2. ADE ontology and Neko protocol tests may proceed independently.
3. Provider registry precedes control-client migration.
4. Capability snapshots depend on provider contracts and current driver facts.
5. Broad verification and PR review follow all implementation phases.
