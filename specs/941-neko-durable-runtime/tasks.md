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

- [x] T101 Add failing lifecycle-transition and recovery tests.
- [x] T102 Implement pure run and operation transition validators.
- [x] T103 Add failing Rust provider-registry tests.
- [x] T104 Move executable candidates, probes, launch args and profile rules to
  the Rust provider registry.

## Phase 3: Durable journal

- [x] T201 Add SQLite schema and WAL/foreign-key/busy-timeout tests.
- [x] T202 Implement per-stream monotonic append and bounded cursor replay.
- [x] T203 Implement request identity, collision detection and recorded-result
  replay without storing raw request payloads.
- [x] T204 Implement conservative startup recovery and secret-exclusion tests.

## Phase 4: Runtime authority

- [x] T301 Implement in-process `NekoRuntime` session/process ownership.
- [x] T302 Replace raw native commands with provider/session/events commands.
- [x] T303 Remove raw spawn/PID/stdin permissions and lock the invariant in
  `security_contract.rs`.
- [x] T304 Route live stdout/exit through agent-session event channels while
  keeping high-volume payloads out of SQLite.

## Phase 5: TypeScript migration

- [x] T401 Remove binary paths and launch arguments from WebView contracts.
- [x] T402 Subscribe to session channels before start and migrate transport
  send/dispose to idempotent native session commands.
- [x] T403 Add the explicit legacy-local execution binding for the current UI.
- [x] T404 Update affected factory/store/UI tests without changing visuals.

## Phase 6: Verification and delivery

- [x] T501 Run focused Rust and Vitest suites plus TypeScript: 29 Rust/security
  tests and the final 28-test regression slice passed on 2026-08-23.
- [x] T502 Run full Rust/desktop suites and web/embed builds: 2,878 Vitest,
  TypeScript, Clippy `-D warnings`, native release build, web and embed passed.
- [x] T503 Update architecture/operational docs and task evidence truthfully;
  release check, 15 release tests, 445 self-harness tests and PR harness passed.
- [x] T504 Harden review findings: bounded provider probes and session writers,
  second-instance focus, journal retention/checkpoint, structural capability
  tests, replay validation, atomic state/event commits, canonical launch paths,
  early-event buffering, discovery recovery and native-response cleanup.
- [x] T505 Address the second review round and keep merge blocked on fresh
  required CI and a clean final review.
- [x] T506 Address the latest authority/liveness review: keep provider probing
  outside the lifecycle lock, replace blocking process waits with retained
  non-blocking ownership, and assign a fresh Run to every runtime replacement.

## Dependencies

1. Phase 1 freezes semantics.
2. Lifecycle and provider contracts precede SQLite/process work.
3. Journal precedes side-effecting runtime commands.
4. Native commands/capabilities precede TypeScript migration.
5. Broad verification follows implementation and documentation.
