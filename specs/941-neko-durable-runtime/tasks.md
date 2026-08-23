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

- [x] T501 Run focused Rust and Vitest suites plus TypeScript: 42 Rust/security
  tests and the latest 208-test review regression slice passed on 2026-08-23.
- [x] T502 Run full Rust/desktop suites and web/embed builds: 2,921 Vitest
  across 173 files,
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
- [x] T507 Close final durability gaps: reconcile native state/replay during
  Workbench hydration, retain unresolved start identity across caller retry,
  reject post-shutdown starts, bound terminal request retention, and protect
  Unix probe captures with owner-only permissions.
- [x] T508 Close final re-review races: re-read native state after replay,
  retain the original execution and transport buffers across real
  RuntimeRegistry retries, and protect the Unix SQLite directory/database/
  sidecars with owner-only permissions.
- [x] T509 Preserve unresolved start authority when Rust explicitly reports
  `unknown_outcome`; ordinary pre-side-effect native rejections may release the
  client identity, but uncertain starts cannot mint a replacement operation.
- [x] T510 Keep duplicate `accepted`/`dispatched` operations unresolved while
  their original caller may still run, and classify start-worker join failure
  as `unknown_outcome` so it cannot release the shared start identity.
- [x] T511 Replay durable starts before volatile workspace checks, bound probe
  capture growth during production and terminate its process tree, and make
  provider writer/reader thread creation fallible before ownership commit.
- [x] T512 Observe provider exit independently from stdout EOF, reject live
  frames above 4 MiB as a terminal protocol failure, and reconcile every
  native Run for a visible Task before allowing respawn.
- [x] T513 Bound aggregate pre-handler bootstrap output, cancel retained
  unresolved starts before deletion, reject every unterminated EOF frame, and
  retire stale Workbench checkpoints after native terminal projection pruning.
- [x] T514 Retain unknown-outcome projections through maintenance, move native
  checkpoints into a rollback-compatible companion store, and persist a
  respawn-blocking tombstone on every live-cleanup path when cancellation cannot
  be proven terminal, including idle reaping and mode exit.
- [x] T515 Represent cleanup success/failure with a tagged outcome and verify
  every legal falsy JavaScript rejection remains an uncertain failure.
- [x] T516 Format arbitrary cleanup rejection values without throwing so a
  hostile value cannot prevent durable tombstone persistence.
- [x] T517 Publish accepted starts before unlocked provider probes, require a
  verified process-tree termination before safe terminal state, and retain one
  Codex account-bootstrap caller identity across uncertain UI retries.
- [x] T518 Publish accepted ownership before volatile workspace I/O, derive the
  Codex bootstrap identity across remount/reload, enforce a producer-side
  Windows probe quota, check every probe cleanup, and bound process reaping.
- [x] T519 Atomically commit start request/projection/event admission, replace
  Windows PID ancestry with pre-execution Job Object ownership, preserve
  `terminationProven` through live exit IPC, classify verified post-spawn
  cleanup as failed rather than unknown, and normalize Windows workspace
  casing aliases without collapsing POSIX identity.
- [x] T520 Reconcile `cancelled: false` before releasing renderer ownership,
  require non-escapable containment (Windows Job Object), reject Unix launch
  before spawn, and retain verified terminal facts
  until their lifecycle transaction commits.
- [x] T521 Close final client/storage review gaps: give concurrent identical
  frames independent request identities while preserving bounded IPC retries,
  persist native checkpoints before compatible transcripts, preserve legal
  POSIX backslashes, classify missing registry cleanup as uncertain, recognize
  undecodable recorded starts, and exact-lock the WebView capability set.
- [x] T522 Close runtime-authority review gaps: fail closed on all Unix provider
  launches until same-UID migration is impossible, withhold renderer exit until
  termination and persistence are both proven, flush retained terminal facts on
  session hydration, retain facts across projection-read errors, and mint a
  fresh Codex bootstrap Run for each proven new attempt.
- [x] T523 Recover a validated native-first partial snapshot by repairing only
  its sequence high-water mark, scope write identities to one invocation and
  its bounded IPC retry, and publish exit-supervision ownership so cancellation
  cannot mistake the monitor hand-off for a missing process.

## Dependencies

1. Phase 1 freezes semantics.
2. Lifecycle and provider contracts precede SQLite/process work.
3. Journal precedes side-effecting runtime commands.
4. Native commands/capabilities precede TypeScript migration.
5. Broad verification follows implementation and documentation.
