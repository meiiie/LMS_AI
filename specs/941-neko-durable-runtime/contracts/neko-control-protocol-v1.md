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

Completed and failed request identities are replayable for 90 days. Startup
maintenance may prune them after that window. Requests in `accepted`,
`dispatched`, `side_effect_started`, `committed`, or `unknown_outcome` are not
automatically pruned: deleting those identities could permit an uncertain
side effect to be repeated.

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

The legacy Workbench compatibility binding maps its stable visible session to
one Task. Every `RuntimeRegistry` replacement maps to a fresh Run and
Environment, even when the adapter resumes the same provider-owned
conversation ID. A terminal Run is never reopened to represent a new process.

Provider discovery is read-only and occurs outside the global lifecycle lock
after request identity is durably accepted. Completed request replay is
resolved before discovery, so a later provider upgrade or removal cannot
invalidate a recorded start result. Provider stdout EOF does not prove process
exit; Neko retains ownership and polls non-blockingly until exit or explicit
release. Runtime shutdown closes start admission before draining children; a
probe already in flight re-checks that gate before creating a session or
spawning a process.

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
finishes.
