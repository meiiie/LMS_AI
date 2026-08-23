# Tasks: Desktop ADE Activation

## Phase 1: Contract and persistence foundation

- [ ] T001 Add strict versioned ADE snapshot persistence in `wiii-desktop/src/ade/persistence.ts`.
- [ ] T002 Add malformed/version/graph round-trip tests in `wiii-desktop/src/__tests__/ade/persistence.test.ts`.
- [ ] T003 Add a small Wiii work store with persistence barrier and lifecycle validation in `wiii-desktop/src/ade/store.ts`.
- [ ] T004 Test create/attach/failure transitions and prove dispatch cannot precede commit.

## Phase 2: Real execution binding

- [ ] T005 Extend visible Neko session persistence with optional `NekoExecutionBinding`.
- [ ] T006 Forward explicit bindings through driver creation, replacement and reconciliation.
- [ ] T007 Add focused compatibility/execution-binding tests.

## Phase 3: Task-first Wiii shell

- [ ] T008 Implement `WiiiAdeApp` with Work/Projects navigation and `Công việc mới` flow.
- [ ] T009 Persist Task/Run before `createSession`, attach provider identity afterward, and surface failures truthfully.
- [ ] T010 Mount `WiiiAdeApp` as Desktop local home while retaining Neko Chill.
- [ ] T011 Add focused UI tests.

## Phase 4: Taxonomy and context

- [ ] T012 Separate Wiii Work, Neko Chill and optional Wiii Service in navigation.
- [ ] T013 Move Wiii Knowledge from the mode switcher into Context controls.
- [ ] T014 Show Task/Run binding and lifecycle outside transcript messages.

## Phase 5: Verification and evidence

- [ ] T015 Run focused/broad desktop tests, TypeScript and build.
- [ ] T016 Run native Rust/Tauri verification when affected.
- [ ] T017 Capture visual evidence.
- [ ] T018 Update spec/tasks/PR evidence and resolve review findings.

## Non-goals

No standalone daemon, worktree manager, editor/LSP, Attention Inbox, cloud handoff, backend schema change, OpenCode, Claude or advanced orchestration.
