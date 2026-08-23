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
  no longer contains a previously reconciled, provably terminal projection
  because retention pruned it, Workbench MUST durably retire that checkpoint
  so it cannot block respawn forever. Missing active or `unknown_outcome`
  checkpoints MUST remain blocking.
- **FR-024**: Completed and failed request identities MUST have a documented,
  bounded retry window. Accepted, dispatched, side-effect-started, committed,
  and `unknown_outcome` identities MUST NOT be pruned automatically.
- **FR-025**: Runtime shutdown MUST close admission before draining owned
  processes. A provider probe already in flight MUST re-check admission before
  spawn. A fresh start MUST publish its `Starting/Accepted` session projection
  before any unlocked workspace or provider-discovery I/O, so reconnect cannot
  mistake an accepted operation for an idle Task.
- **FR-026**: If both bounded IPC attempts lose a `session/start` response,
  the TypeScript client MUST retain the same request, agent-session, Run,
  Environment, listener and early transport buffer for a caller-level retry,
  even when `RuntimeRegistry` gives that retry a fresh preparation ID. The
  retained bootstrap buffer MUST have aggregate frame and byte ceilings;
  overflow MUST detach listeners, request cancellation with the retained
  identity, and remain fail-closed until cancellation is confirmed. Session
  deletion MUST reconcile or cancel retained unresolved starts first.
- **FR-027**: Unix provider discovery and execution MUST reject before spawn
  until an approved non-escapable containment primitive exists. Windows probes
  MUST enforce a producer ceiling with a bounded pipe. Probe output is trusted
  only after checked process-tree cleanup, and process reaping MUST have a
  finite deadline.
- **FR-028**: On Unix, the durable journal directory MUST be owner-only and
  the main SQLite database plus WAL/SHM sidecars MUST not be accessible to
  group or other users.
- **FR-029**: Native reconciliation, retirement, and uncertain-cleanup events
  MUST persist in an additive companion store. The shared Workbench v2 session
  snapshot MUST contain only event discriminators understood by the previous
  desktop release so a full-release rollback can still hydrate conversations.
  The native companion MUST commit before the compatible transcript so a later
  transcript failure cannot silently hide a native lifecycle fact. Hydration
  MUST recover this expected partial-write generation by advancing only the
  allocator high-water mark from the validated merged event log.
- **FR-030**: A live runtime cleanup that does not prove cancellation reached a
  safe terminal state MUST leave a durable blocking tombstone, render the
  visible session as an error, and prevent replacement execution until native
  reconciliation establishes `completed`, `failed`, or `cancelled`. Cleanup
  that has no result from the live runtime registry is unobserved and therefore
  MUST be treated as uncertain, not as a successful detach. Cleanup
  success/failure MUST use a tagged outcome and MUST NOT depend on truthiness of
  the rejection reason. Formatting an arbitrary rejection value MUST be
  non-throwing and bounded so the durable tombstone cannot be skipped.
- **FR-031**: Native cancellation MUST verify complete process-tree termination.
  An OS termination failure or missing owner for a side-effecting live session
  MUST transition the request and native session to `unknown_outcome`; it MUST
  NOT commit `cancelled`, `failed`, or another respawn-permitting terminal fact.
- **FR-032**: The Codex account bootstrap UI MUST derive a stable logical caller
  identity from its workspace across retry attempts, component remounts and
  WebView reloads, but each new attempt MUST receive a fresh Run identity. An
  unresolved caller retry MUST retain its original Run; a durable non-terminal
  native Run MUST block an automatic duplicate App Server launch after volatile
  client state is lost.
- **FR-033**: Admission of a fresh `session/start` request, its listable
  `Starting/Accepted` projection, and `session.created` MUST commit in one
  transaction. Shutdown MAY reject a new identity but MUST preserve replay of
  an already-recorded identity.
- **FR-034**: Windows providers and probes MUST be assigned to a kill-on-close
  Job Object before their suspended leader begins execution. Cleanup MUST query
  that Job Object until no active member remains; PID ancestry is not proof of
  cleanup because an intermediate process may exit first.
- **FR-035**: A live exit notice MUST carry `terminationProven` and
  `terminalStatePersisted`. The renderer MUST NOT treat leader exit alone as
  completed cleanup, notify driver exit handlers, or skip an explicit
  cancellation/reconciliation attempt unless both complete process-tree
  termination and the durable terminal lifecycle transition are proven.
- **FR-036**: Post-spawn setup or ownership-commit failure MAY become ordinary
  `failed` only after native cleanup proves the complete process tree stopped.
  `unknown_outcome` is reserved for unproven cleanup or an uncertain persisted
  side effect.
- **FR-037**: Workspace-scoped bootstrap identities MUST normalize aliases that
  the host treats as the same path. In particular, Windows drive and UNC paths
  MUST normalize separator and casing differences without collapsing distinct
  case-sensitive POSIX paths or backslashes that are legal POSIX filename
  characters.
- **FR-038**: A native cancellation response with `cancelled: false` MUST be
  reconciled against the durable session projection. A remaining active or
  uncertain record MUST fail closed and MUST NOT release renderer ownership.
- **FR-039**: Provider launch MUST use non-escapable OS containment. Windows
  MUST use a pre-execution Job Object. Unix hosts MUST reject before spawn until
  an approved primitive prevents same-UID migration; a writable cgroup leaf or
  POSIX process group MUST NOT be treated as complete containment.
- **FR-040**: A verified native exit whose terminal lifecycle transaction
  fails MUST remain pending inside the runtime authority. The renderer MUST be
  told that terminal persistence is unproven. Cancellation and `session/list`
  hydration MUST retry that exact terminal fact before returning a safe result;
  failure to read the session projection after termination MUST retain the fact.
- **FR-041**: Each concurrent logical `session/write` invocation MUST receive
  its own request identity even when serialized frames are byte-identical. A
  bounded IPC retry of one invocation MUST reuse that invocation's identity;
  a later caller invocation MUST receive a fresh identity. Caller-level retry
  after an unresolved outcome MUST NOT be inferred from frame contents.
- **FR-042**: Native process exit supervision MUST publish its in-flight
  ownership before removing the process from the live map. Matching
  cancellation and `session/list` hydration MUST fail closed until the exact
  terminal fact is committed; they MUST NOT convert this hand-off into missing
  ownership or a provisional `unknown_outcome` session transition.
- **FR-043**: A verified cancellation or shutdown terminal fact that cannot
  commit its lifecycle event MUST be retained durably before authority returns.
  Startup recovery and maintenance MUST preserve the linked session/request,
  and later reconciliation MUST atomically commit session state, event and any
  idempotent cancellation result without repeating process termination.
- **FR-044**: `session/write` MUST reject literal CR or LF delimiters before
  request admission so one request identity can dispatch exactly one provider
  frame.
- **FR-045**: Provider detection MUST distinguish host containment being
  unsupported from the provider not being installed; UI MUST not report the
  former as an installation failure.
- **FR-046**: Windows suspended-launch setup failures MUST check termination
  and reap the leader within the existing finite deadline. No cleanup path may
  block indefinitely while holding lifecycle serialization.
- **FR-047**: Codex account bootstrap ownership MUST live outside React
  component lifetime. Failed cleanup MUST remain retryable and block a
  replacement bootstrap until the prior App Server reaches a proven terminal
  result.
- **FR-048**: Provider spawn and discovery MUST preserve a machine-readable
  distinction between a safe rejection and post-spawn cleanup that was not
  proven. The latter MUST become `unknown_outcome` for an admitted start and
  MUST NOT authorize an automatic replacement process.
- **FR-049**: Graceful shutdown MUST wait for every published process-exit
  supervisor to finish its exact terminal reconciliation after lifecycle
  serialization is released. Application exit MUST NOT abandon a supervisor
  between process-map hand-off and durable terminal commit.
- **FR-050**: Neko mode teardown MUST enumerate retained control-client starts,
  refresh that enumeration after in-flight runtime preparation settles, request
  authoritative cancellation before recording exit, and persist cleanup
  uncertainty when cancellation cannot be proven.
- **FR-051**: A failed live-runtime disposer MUST retain its cleanup authority
  and MUST be retryable with the same provider cancellation identity. A later
  close, delete, teardown, or replacement MUST serialize behind any active
  attempt, retry only unresolved disposers, and keep replacement fail-closed
  until cleanup succeeds.
- **FR-052**: Retained live-runtime cleanup MUST preserve the provider/native
  session identity. A later successful retry MUST append an explicit
  `native-runtime-cleanup-resolved` fact so an earlier uncertainty tombstone no
  longer blocks safe close, delete, teardown, or replacement.
- **FR-053**: A replacement driver MAY be prepared while the previous runtime
  is live, but MUST NOT become the current binding until prior cleanup is
  proven. If prior cleanup fails, the prepared replacement MUST be closed and
  no replacement binding may remain observable.
- **FR-054**: A driver that becomes owned after its preparation scope was
  revoked MUST receive a new retryable cleanup scope. A one-shot rejected
  Promise is not cleanup authority and MUST NOT be discarded.
- **FR-055**: After graceful shutdown joins all published exit supervisors, it
  MUST flush terminal facts retained by those supervisors before returning.
  A provider probe whose leader exited MUST still classify failed descendant
  cleanup as post-spawn cleanup uncertainty.
- **FR-056**: Before starting a Codex account bootstrap for a different
  workspace, the client MUST reconcile both renderer-retained identities and
  durable native sessions, then cancel every non-terminal Codex bootstrap from
  older workspace identities. It MUST attempt every independent cleanup before
  reporting failures. Any failure MUST block the new workspace launch;
  unrelated starts and the current workspace identity MUST remain untouched.
- **FR-057**: Retained-start discovery MUST union renderer memory with
  non-terminal durable Codex bootstrap sessions and MUST be used by mode-exit
  teardown after runtime preparation settles. Durable bootstrap cancellation
  MUST remain scoped to Codex and MUST NOT terminate another provider sharing
  the same Task.
- **FR-058**: Mode exit MUST continue cancelling renderer-known starts when
  durable catalog discovery fails, then report that discovery uncertainty.
  Cancellation failures for catalog-only identities MUST be propagated. When
  post-spawn process-tree cleanup is proven, Neko MUST retain the exact failed
  session and request outcome before attempting the authoritative transaction.
- **FR-059**: A durable discovery failure MUST NOT hide any cancellation
  failure encountered during the same teardown. Codex bootstrap handoff MUST
  seed renderer-retained identities before durable discovery, and native spawn
  errors MUST distinguish pre-spawn rejection, proven post-spawn cleanup, and
  unproven cleanup. Proven post-spawn cleanup MUST use the retained terminal
  fact path rather than the pre-spawn rejection path. Provider discovery MUST
  propagate both post-spawn outcomes instead of misreporting them as
  `not_installed`, including delayed reader failure, drain timeout, or output
  overflow observed after process-tree termination was proven.
- **FR-060**: Provider-list error presentation MUST preserve cleanup proof: a
  proven post-spawn probe failure MUST NOT be labelled as unproven cleanup,
  while genuinely uncertain termination MUST remain explicit and fail closed.

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
  transport events; Unix provider probes reject before spawn; and Unix journal
  files are owner-only.
- **SC-007**: Tests prove atomic start admission rollback, shutdown-safe replay,
  Windows Job Object ownership across an exited intermediate, host-aware
  workspace identity with fresh Run attempts, Unix pre-spawn rejection, and
  fail-closed handling of an unproven or unpersisted exit notice.
- **SC-008**: Tests prove retained cancel/shutdown facts survive journal
  recovery, cancellation result commits atomically, embedded frame delimiters
  are rejected, host-unsupported discovery is explicit, and failed Codex
  bootstrap cleanup prevents replacement until a successful retry.
- **SC-009**: Tests prove post-spawn cleanup uncertainty remains structured,
  shutdown waits for published exit supervision, and mode exit fails closed
  when a retained native start cannot be cancelled.
- **SC-010**: Tests prove successful sibling disposers are not repeated, failed
  cleanup can be retried, and a replacement provider starts only after the
  retained cleanup reaches a proven result.
- **SC-011**: Tests prove late-owned cleanup remains retryable, replacement is
  never published across failed prior cleanup, provider identity survives
  retry, and close/delete/respawn paths can resolve an uncertainty tombstone.
- **SC-012**: Tests prove a workspace handoff deduplicates and cancels older
  Codex bootstrap identities before spawn, recovers durable starts after
  renderer memory loss, attempts sibling cleanup after one failure, and never
  spawns the new workspace when reconciliation fails.
- **SC-013**: Tests prove mode exit cancels a durable Codex bootstrap after
  renderer reload and durable reconciliation ignores a non-Codex AgentSession
  sibling attached to the same Task.
- **SC-014**: Tests prove catalog-read failure cannot skip known-start cleanup,
  catalog-only cancellation failure is observable, and a proven spawn cleanup
  fact survives transaction failure/recovery without becoming
  `unknown_outcome`.
- **SC-015**: Tests prove combined discovery/cancellation failures are both
  observable, Codex handoff cancels renderer-known identities even when native
  discovery fails, post-spawn cleanup classification is machine-readable, and
  provider discovery propagates every post-spawn failure disposition.
- **SC-016**: Tests prove provider discovery messages distinguish proven
  process-tree cleanup from cleanup whose outcome remains uncertain.
