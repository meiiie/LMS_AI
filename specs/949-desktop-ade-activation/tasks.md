# Tasks: Desktop ADE Activation

## Phase 1: Contract and persistence foundation

- [x] T001 Add strict versioned ADE snapshot persistence in `wiii-desktop/src/ade/persistence.ts`.
- [x] T002 Add malformed/version/graph round-trip tests in `wiii-desktop/src/__tests__/ade/persistence.test.ts`.
- [x] T003 Add a small Wiii work store with persistence barrier and lifecycle validation in `wiii-desktop/src/ade/store.ts`.
- [x] T004 Test create/attach/failure transitions and prove dispatch cannot precede commit.

## Phase 2: Real execution binding

- [x] T005 Extend visible Neko session persistence with optional `NekoExecutionBinding`.
- [x] T006 Forward explicit bindings through driver creation, replacement and reconciliation.
- [x] T007 Add focused compatibility/execution-binding tests.

## Phase 3: Task-first Wiii shell

- [x] T008 Implement `WiiiAdeApp` with Work/Projects navigation and `Công việc mới` flow.
- [x] T009 Persist Task/Run before `createSession`, attach provider identity afterward, and surface failures truthfully.
- [x] T010 Mount `WiiiAdeApp` as Desktop local home while retaining Neko Chill.
- [x] T011 Add focused UI tests.

## Phase 4: Taxonomy and context

- [x] T012 Separate Wiii Work, Neko Chill and optional Wiii Service in navigation.
- [x] T013 Move Wiii Knowledge from the mode switcher into Context controls.
- [x] T014 Show Task/Run binding and lifecycle outside transcript messages.

## Phase 5: Verification and evidence

- [x] T015 Run focused/broad desktop tests, TypeScript and build.
- [x] T016 Native Rust was not changed; the mandatory Native Desktop Gate verifies the affected desktop branch in CI.
- [x] T017 Capture visual evidence.
- [x] T018 Update spec/tasks/PR evidence and resolve review findings.

## Non-goals

No standalone daemon, worktree manager, editor/LSP, Attention Inbox, cloud handoff, backend schema change, OpenCode, Claude or advanced orchestration.
