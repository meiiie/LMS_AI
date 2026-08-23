# Feature Specification: Neko Durable Runtime Authority

**Feature Branch**: `codex/941-feat-neko-durable-runtime`
**Created**: 2026-08-23
**Status**: In progress
**Issue**: #941
**Input**: Move local provider process/session authority from the privileged
WebView into an in-process Rust Neko service with durable, replayable facts.

## User Scenarios & Testing

### User Story 1 - Start only approved providers (Priority: P1)

A person starts Neko Core, Gemini CLI, or Codex by provider identity. The
native Neko service resolves the installed binary and approved launch
arguments; the WebView never chooses an executable or argument vector.

**Independent Test**: Attempt supported and unknown provider starts through
the native contract, then inspect the Tauri capability manifest to prove no
command available to `main` accepts arbitrary `program` or `args`.

**Acceptance Scenarios**:

1. **Given** Codex is installed, **When** Wiii requests provider `codex`,
   **Then** Rust launches only the registry-owned `app-server` contract.
2. **Given** an unknown provider or invalid profile, **When** start is
   requested, **Then** Rust rejects it before any process side effect.
3. **Given** a compromised renderer, **When** it enumerates allowed Neko
   commands, **Then** it cannot invoke raw executable spawn, kill-by-PID, or
   unscoped stdin commands.

---

### User Story 2 - Reconnect without losing lifecycle facts (Priority: P1)

A client that misses control events reconnects with its last sequence and
receives the missing ordered facts for the run stream.

**Independent Test**: Append interleaved events for two run streams, read one
stream after a cursor with a bounded limit, and prove sequence is strictly
monotonic per stream with an explicit continuation cursor.

**Acceptance Scenarios**:

1. **Given** a run stream has events 1 through 10, **When** a client reads
   after 6 with limit 2, **Then** it receives 7 and 8 plus `nextAfterSeq=8`
   and `hasMore=true`.
2. **Given** two concurrent run streams, **When** events are appended,
   **Then** each stream has its own gap-free monotonic sequence.
3. **Given** the UI reloads, **When** it lists sessions and reads events,
   **Then** state is reconstructed from Rust/SQLite rather than a React map.

---

### User Story 3 - Retry commands without duplicate side effects (Priority: P1)

A client can retry a timed-out start, write, or cancel request with the same
request ID without spawning, writing, or killing twice.

**Independent Test**: Execute the same request ID twice and prove the second
call returns the recorded outcome; reuse the ID for a different method or
payload identity and prove it fails closed.

**Acceptance Scenarios**:

1. **Given** `session/start` completed, **When** the same request is retried,
   **Then** it returns the same agent-session result without a second process.
2. **Given** a request reached an uncertain side-effect phase, **When** it is
   retried, **Then** Neko returns `unknown_outcome` and does not replay it.
3. **Given** a request ID was used for another method, **When** it is reused,
   **Then** Neko rejects the collision.

---

### User Story 4 - Recover honestly after process loss (Priority: P1)

After Neko restarts, incomplete operations are classified from committed
facts. Neko never invents continuity and never silently replays a mutation.

**Independent Test**: Seed sessions at each operation phase, reopen the
journal, and verify safe pre-side-effect phases become continuity loss while
side-effect/committed phases become `unknown_outcome`.

**Acceptance Scenarios**:

1. **Given** only `accepted` or `dispatched` was committed, **When** Neko
   recovers, **Then** no side effect is assumed and the operation fails with
   explicit continuity loss.
2. **Given** `side_effect_started` or `committed` was recorded without a
   terminal outcome, **When** Neko recovers, **Then** state becomes
   `unknown_outcome` and no automatic retry occurs.
3. **Given** a session is terminal, **When** Neko restarts, **Then** its
   terminal state remains unchanged.

## Requirements

### Functional Requirements

- **FR-001**: Rust MUST be the sole authority for approved provider
  executable resolution and launch arguments.
- **FR-002**: The `main` WebView MUST NOT hold a command permission that
  accepts arbitrary executable paths, argument vectors, PIDs, or process IDs.
- **FR-003**: Provider detection responses MUST NOT disclose resolved binary
  paths to the WebView.
- **FR-004**: Neko MUST retain separate durable provider catalog and live
  process/session ownership concepts.
- **FR-005**: Every side-effecting native request MUST contain a caller-stable
  `requestId` and a method-specific logical identity.
- **FR-006**: Repeating the same request identity MUST return the recorded
  outcome without executing the side effect twice.
- **FR-007**: Reusing a request ID for a different method or logical target
  MUST fail closed.
- **FR-008**: Operation phases MUST be `accepted`, `dispatched`,
  `side_effect_started`, `committed`, `completed`, `failed`, or
  `unknown_outcome`.
- **FR-009**: Neko MUST commit `side_effect_started` before process spawn,
  stdin write, or process cancellation is attempted.
- **FR-010**: An event MUST contain a globally unique `eventId`, a stable
  `streamId`, and a positive sequence strictly monotonic within that stream.
- **FR-011**: In this phase, one run ID MUST map to one durable event stream;
  events for multiple sessions in the run share that stream.
- **FR-012**: Event replay MUST support `afterSeq`, a bounded `limit`, an
  explicit `nextAfterSeq`, and `hasMore`.
- **FR-013**: SQLite MUST use WAL, foreign keys, a busy timeout, and unique
  constraints for request identity plus `(stream_id, seq)` ordering.
- **FR-014**: SQLite MUST store durable lifecycle facts only. Provider
  credentials, environment values, raw prompts, raw provider frames, and
  high-volume terminal output MUST NOT be stored.
- **FR-015**: Startup recovery MUST classify incomplete pre-side-effect work
  as continuity loss and uncertain side-effect work as `unknown_outcome`.
- **FR-016**: Recovery MUST NOT automatically respawn a provider, resend a
  frame, or repeat cancellation.
- **FR-017**: ADE graph validation and run lifecycle validation MUST remain
  separate pure contracts.
- **FR-018**: Invalid run state transitions MUST be rejected without mutating
  the run. Retry creates a new run; it does not reopen a terminal run.
- **FR-019**: Existing Neko Core, Gemini CLI, and Codex protocols MUST remain
  in TypeScript adapters for this phase; Rust owns transport lifecycle but
  does not parse provider reasoning or transcript payloads.
- **FR-020**: Current local Neko sessions MUST keep working through a
  compatibility binding until the ADE task UI supplies native Task/Run IDs.
  The visible session identity remains the Task, while every runtime
  replacement MUST receive a fresh Run and Environment identity.
- **FR-021**: A standalone `neko-daemon` MUST NOT be claimed by this phase;
  the Rust authority remains inside the Tauri process.
- **FR-022**: Slow provider discovery and process-exit observation MUST NOT
  hold the global lifecycle-operation lock. EOF on provider stdout MUST NOT be
  treated as proof that the child process exited. Exit observation MUST run
  independently from stdout consumption, and each live provider frame MUST be
  byte-bounded before it is decoded or emitted to the renderer. EOF before a
  newline delimiter is a protocol failure even when the partial frame is below
  the byte ceiling.
- **FR-023**: Restored Workbench sessions MUST reconcile every matching native
  session record and replay cursor before hydration becomes usable, then
  re-read each native session projection after replay to observe lifecycle
  transitions committed during that read. Any native `unknown_outcome` or
  unattached active process MUST fail closed rather than trigger a replacement,
  even when a newer native Run is terminal. When the complete native catalog
  no longer contains a previously reconciled projection because terminal
  retention pruned it, Workbench MUST durably retire that checkpoint so it
  cannot block respawn forever.
- **FR-024**: Completed and failed request identities MUST have a documented,
  bounded retry window. Accepted, dispatched, side-effect-started, committed,
  and `unknown_outcome` identities MUST NOT be pruned automatically.
- **FR-025**: Runtime shutdown MUST close admission before draining owned
  processes. A provider probe already in flight MUST re-check admission before
  session creation or spawn.
- **FR-026**: If both bounded IPC attempts lose a `session/start` response,
  the TypeScript client MUST retain the same request, agent-session, Run,
  Environment, listener and early transport buffer for a caller-level retry,
  even when `RuntimeRegistry` gives that retry a fresh preparation ID. The
  retained bootstrap buffer MUST have aggregate frame and byte ceilings;
  overflow MUST detach listeners, request cancellation with the retained
  identity, and remain fail-closed until cancellation is confirmed. Session
  deletion MUST reconcile or cancel retained unresolved starts first.
- **FR-027**: Provider probe capture files MUST be created owner-only on Unix;
  capture contents remain bounded and are deleted after the probe.
- **FR-028**: On Unix, the durable journal directory MUST be owner-only and
  the main SQLite database plus WAL/SHM sidecars MUST not be accessible to
  group or other users.

### Non-goals

- Worktree, Environment Manager, sandbox, Attention Inbox, Fleet Dashboard,
  ADE shell, OpenCode, Claude, cloud handoff, and cross-process daemon IPC.
- Replaying raw terminal/provider streams from SQLite.
- Migrating legacy visible transcripts into the native lifecycle journal.

## Success Criteria

- **SC-001**: A security-contract test proves the WebView capability contains
  only provider/session-level Neko commands and no legacy raw process command.
- **SC-002**: Rust tests cover provider resolution, replay pagination,
  per-stream ordering, idempotent replay, collision rejection, recovery and
  forbidden lifecycle transitions.
- **SC-003**: TypeScript tests prove the control client subscribes before
  start, passes no executable, and disposes a session idempotently.
- **SC-004**: Existing affected Neko driver/runtime/persistence tests,
  TypeScript, Rust tests and desktop builds pass.
- **SC-005**: Documentation states exactly which lifecycle events are durable
  and which high-volume/provider payloads remain live-only.
- **SC-006**: Tests prove hydration consumes native replay before enabling a
  restored session and re-reads state after replay; shutdown rejects late
  starts; terminal request retention is bounded without pruning uncertain
  identities; real registry retries preserve one start and its buffered
  transport events; and Unix probe/journal files are owner-only.
