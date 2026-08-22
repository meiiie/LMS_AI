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
