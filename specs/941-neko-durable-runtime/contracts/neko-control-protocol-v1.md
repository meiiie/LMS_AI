# Neko Control Protocol v1: Durable Runtime Semantics

This document tightens the foundation contract from issue #939. The first
server remains in-process Rust/Tauri; transport separation is not part of v1.

## Request identity

Every side-effecting request has a stable `requestId`. The server records the
method and logical target before dispatch.

- Same request ID, method and target after completion: return the same result.
- Same request ID while outcome is uncertain: return `unknown_outcome`.
- Same request ID with another method or target: return `invalid_request`.
- The server never retries a side effect merely because a response was lost.
- A client that exhausts its bounded IPC retry keeps the same logical
  `requestId`, `agentSessionId`, original Run/Environment binding, subscribed
  transport listener and early-event buffer for the caller's next start
  attempt. A new renderer preparation ID does not create a new logical start.
- The pre-handler bootstrap buffer is bounded to 256 frames and 8 MiB in
  aggregate. Overflow is terminal for that client transport: listeners are
  detached and Neko cancels the retained logical start with its original
  cancellation identity. The identity remains unresolved if cancellation
  cannot be confirmed, and close/delete fails closed rather than forgetting it.
- Before deleting any other retained start, the client first replays its exact
  original `session/start` identity when no native projection is visible. A
  still-accepted/dispatched request returns `unknown_outcome` and keeps deletion
  blocked; a completed replay is cancelled, while a recorded pre-side-effect
  failure proves there is no process to cancel.
- `provider_busy` proves a bounded writer queue rejected the frame before it
  was enqueued. A caller may retry that frame only with a new request ID.
- Native start errors prefixed with `unknown_outcome:` are authoritative but
  unresolved. The control client retains the original request, agent-session,
  Run/Environment binding and listeners; it must not downgrade that result to
  an ordinary deterministic rejection or mint a replacement start identity.
- A duplicate request observed in `accepted` or `dispatched` remains unresolved
  while the original caller may still be running. Startup recovery, rather than
  a concurrent caller, converts abandoned pre-side-effect requests into
  explicit continuity loss.
- Stable request syntax is validated before lookup; volatile workspace
  availability is checked only for a new execution. A recorded or unresolved
  start therefore remains replayable if its workspace was renamed or is
  temporarily unavailable.
- A new start publishes a listable `Starting/Accepted` session and its creation
  event before any unlocked workspace or provider-discovery I/O. Account-probe
  retries derive one workspace-scoped caller identity across component remount
  and WebView reload; a durable non-terminal native Run blocks duplicate launch
  when the renderer's volatile retained-start map has been lost.

Completed and failed request identities are replayable for 90 days. Startup
maintenance may prune them after that window. Requests in `accepted`,
`dispatched`, `side_effect_started`, `committed`, or `unknown_outcome` are not
automatically pruned. Runtime-session projections in `unknown_outcome` are also
retained: deleting either identity could permit an uncertain side effect to be
repeated.

## Native methods implemented in Phase 2A

| Method | Native input | Durable side effect |
| --- | --- | --- |
| `provider/list` | none | no |
| `provider/profiles` | provider ID, workspace | no |
| `session/list` | optional run ID | no |
| `session/start` | request/session/run/provider/environment/workspace/profile IDs | process spawn |
| `session/write` | request ID, agent-session ID, one provider frame | stdin write; frame is not persisted |
| `session/cancel` | request/run/session IDs | process termination |
| `events/read` | stream ID, after sequence, limit | no |

`session/write` exists as a private transport primitive for the current ACP
and Codex adapters. It is scoped to a Rust-owned agent-session identity and is
idempotent by request ID. It does not accept a PID or executable.

Provider discovery captures are owner-only on Unix and output-bounded while the
probe is running. Windows uses a MAX+1-byte pipe reader, so the producer cannot
grow a capture file between monitor polls. Probe output is accepted only after
checked tree termination; leader reaping and descendant cleanup have explicit
deadlines. Probe and agent launches use isolated process ownership; timeout,
output overflow, helper-thread failure and shutdown terminate the owned process
tree rather than accepting an unverified cleanup. Live provider stdout is parsed
with a 4 MiB per-frame ceiling; an oversized, unterminated or invalid UTF-8
frame is a terminal provider-protocol failure, not an unbounded renderer input.
EOF never acts as an implicit delimiter for a short partial frame.

The legacy Workbench compatibility binding maps its stable visible session to
one Task. Every `RuntimeRegistry` replacement maps to a fresh Run and
Environment, even when the adapter resumes the same provider-owned
conversation ID. A terminal Run is never reopened to represent a new process.

Provider discovery is read-only and occurs outside the global lifecycle lock
after request identity and its `Starting/Accepted` session projection are
durably accepted. Completed request replay is
resolved before discovery, so a later provider upgrade or removal cannot
invalidate a recorded start result. Provider stdout EOF does not prove process
exit; a dedicated monitor polls the owned child independently of stdout reads.
If the leader exits while a descendant retains inherited stdio, Neko closes the
isolated process tree without waiting for pipe EOF. Cancellation or exit may
commit a respawn-permitting terminal state only when the OS termination result
proves that tree stopped; otherwise Neko records `unknown_outcome`. Runtime
shutdown closes start admission before draining children; a probe already in
flight re-checks that gate before spawning a process.

Workbench hydration reconciles every native AgentSession mapped to the visible
Task, not only the newest record. Any active or `unknown_outcome` execution
blocks respawn even when a newer Run is already terminal. Native `session/list`
is the complete retained projection catalog: when a formerly reconciled,
provably terminal projection has been pruned, Workbench appends a retirement
fact and stops treating that historical checkpoint as a live respawn barrier.
An absent active/unknown checkpoint remains blocking. Reconciliation and
uncertain-cleanup facts live in an additive companion store; the shared v2
Workbench transcript keeps its previous-release event vocabulary.

On Unix the journal parent is owner-only (`0700`), and the SQLite database,
WAL and shared-memory sidecars are owner-only (`0600`).

## Event ordering

```json
{
  "v": 1,
  "eventId": "uuid",
  "streamId": "run-82",
  "seq": 126,
  "at": "2026-08-23T00:00:00Z",
  "type": "session.started",
  "runId": "run-82",
  "agentSessionId": "session-21",
  "payload": {}
}
```

- `eventId` is globally unique.
- `streamId` is the durable run stream ID.
- `seq` is strictly monotonic within one `streamId` only.
- Database row IDs and arrival order are not protocol ordering.
- A session creation or lifecycle state transition and its corresponding
  durable event commit in the same SQLite transaction. Renderer delivery
  happens only after that commit and is recoverable through replay.

## Replay

Request:

```json
{ "streamId": "run-82", "afterSeq": 581, "limit": 100 }
```

Response:

```json
{
  "streamId": "run-82",
  "events": [],
  "nextAfterSeq": 581,
  "hasMore": false
}
```

`limit` outside 1..500 is rejected. Events are returned in ascending sequence.
`nextAfterSeq` equals the last returned sequence or the caller cursor when no
event is returned.

During Workbench hydration, the compatibility read model lists native
sessions, matches them to the visible Task, and consumes `events/read` from its
last recorded cursor before the session becomes usable. It persists a bounded
reconciliation checkpoint rather than copying native event payloads into the
visible transcript. `unknown_outcome` and native-active sessions without a
live renderer transport remain locked against automatic respawn.

Lifecycle replay is retained for 30 days and capped at 10,000 events per run.
The latest event in every known stream is retained as a sequence high-water
mark, so compaction may create a historical gap but never resets or reuses a
stream sequence. Clients must accept the first returned sequence being greater
than `afterSeq + 1`; restoring a full historical transcript is outside Phase
2A because provider stdout and message/tool deltas remain live-only.

## Durable versus live-only

Durable in Phase 2A:

- session created/started
- run state changed
- operation phase and idempotency outcome
- process exited
- continuity lost / unknown outcome recovery

Live-only in Phase 2A:

- provider stdout/JSON-RPC frames
- message/tool deltas
- terminal output

These live payloads remain owned by current provider adapters and Workbench
session persistence. Their absence from SQLite is an explicit security and
volume boundary, not a claim of full daemon replay.

Provider discovery captures only bounded output. On Unix, the temporary
capture is created with owner-only mode `0600` and removed when the probe
finishes. On Windows, a bounded pipe closes after one byte beyond the ceiling,
and no unbounded capture file is created.
