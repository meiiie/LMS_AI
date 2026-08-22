# Tasks: Neko Durable Runtime Authority

**Input**: `specs/941-neko-durable-runtime/`

**Issue**: #941

## Phase 1: Contract and baseline

- [x] T001 Create issue #941 and a branch from current `main`.
- [x] T002 Specify ordering, replay, idempotency, operation phases, recovery,
  lifecycle transitions, storage exclusions, scope and rollback.
- [x] T003 Record focused pre-change baseline: 9 Rust tests, 35 focused
  Vitest tests, and TypeScript passed on 2026-08-23.

## Phase 2: Pure native contracts

- [ ] T101 Add failing lifecycle-transition and recovery tests.
- [ ] T102 Implement pure run and operation transition validators.
- [ ] T103 Add failing Rust provider-registry tests.
- [ ] T104 Move executable candidates, probes, launch args and profile rules to
  the Rust provider registry.

## Phase 3: Durable journal

- [ ] T201 Add SQLite schema and WAL/foreign-key/busy-timeout tests.
- [ ] T202 Implement per-stream monotonic append and bounded cursor replay.
- [ ] T203 Implement request identity, collision detection and recorded-result
  replay without storing raw request payloads.
- [ ] T204 Implement conservative startup recovery and secret-exclusion tests.

## Phase 4: Runtime authority

- [ ] T301 Implement in-process `NekoRuntime` session/process ownership.
- [ ] T302 Replace raw native commands with provider/session/events commands.
- [ ] T303 Remove raw spawn/PID/stdin permissions and lock the invariant in
  `security_contract.rs`.
- [ ] T304 Route live stdout/exit through agent-session event channels while
  keeping high-volume payloads out of SQLite.

## Phase 5: TypeScript migration

- [ ] T401 Remove binary paths and launch arguments from WebView contracts.
- [ ] T402 Subscribe to session channels before start and migrate transport
  send/dispose to idempotent native session commands.
- [ ] T403 Add the explicit legacy-local execution binding for the current UI.
- [ ] T404 Update affected factory/store/UI tests without changing visuals.

## Phase 6: Verification and delivery

- [ ] T501 Run focused Rust and Vitest suites plus TypeScript.
- [ ] T502 Run full Rust/desktop suites and web/embed builds.
- [ ] T503 Update architecture/operational docs and task evidence truthfully.
- [ ] T504 Open PR, resolve actionable review, and follow CI through merge.

## Dependencies

1. Phase 1 freezes semantics.
2. Lifecycle and provider contracts precede SQLite/process work.
3. Journal precedes side-effecting runtime commands.
4. Native commands/capabilities precede TypeScript migration.
5. Broad verification follows implementation and documentation.
