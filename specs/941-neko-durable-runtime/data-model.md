# Data Model: Neko Durable Runtime Authority

## Runtime entities

### RuntimeSession

- `agentSessionId`: stable native execution identity
- `taskId`, `runId`, `environmentId`: opaque Wiii ADE references
- `providerId`, `providerVersion`: provider facts at start
- `workspacePath`: selected workspace boundary; never an executable
- `state`: ADE-compatible run state
- `operationPhase`: latest side-effect phase
- `continuity`: `active`, `continuity_lost`, or `unknown_outcome`
- optional OS PID for diagnosis only; UI cannot act by PID

### IdempotencyRecord

- `requestId`: global caller-generated key
- `method`: native control method
- `targetId`: stable logical target, never raw parameters
- `phase`: operation phase
- optional bounded result/error JSON owned by Neko
- timestamps

The tuple `(requestId, method, targetId)` identifies one operation. A request
ID reused with any other method/target is a collision.

Completed and failed records have a 90-day replay window. Non-terminal and
`unknown_outcome` records are retained until an explicit future policy can
prove deletion cannot permit a repeated side effect.

### ControlEvent

- `eventId`: UUID
- `streamId`: exact run stream identity
- `seq`: positive monotonic integer within `streamId`
- `at`: UTC timestamp
- `type`: normalized Neko event type
- optional session identity
- bounded Neko-generated payload

No raw provider frame or terminal line is a `ControlEvent` in Phase 2A.

### PendingTerminalFact

- `agentSessionId`: one retained exact lifecycle fact per native session
- optional linked cancellation `requestId`
- target run state, operation phase and continuity
- bounded normalized event type/payload
- optional bounded idempotent request result

This is a recovery record, not a second lifecycle projection. It exists only
when native process-tree termination is already known but the authoritative
session/event transaction failed. Startup recovery and retention skip linked
rows until this fact is reconciled; reconciliation removes it in the same
transaction that commits the terminal event and optional request result.

### Workbench reconciliation companion

The additive `neko-chill-native-runtime.json` companion may contain runtime-only
`native-runtime-reconciled`, `native-runtime-retired`, and
`native-runtime-cleanup-uncertain` events with native session/run identity,
state, operation phase, continuity and consumed replay cursor/count. They are
bounded read-model checkpoints; they do not copy native event payloads or
replace the native journal. They deliberately do not enter the shared v2
transcript snapshot, preserving rollback readability for the previous desktop
release. Missing unknown/active projections never create retirement facts.

## SQLite schema direction

```text
runtime_sessions
  agent_session_id PK
  task_id
  run_id
  environment_id
  provider_id
  provider_version
  workspace_path
  state
  operation_phase
  continuity
  pid nullable
  created_at
  updated_at

control_requests
  request_id PK
  method
  target_id
  phase
  result_json nullable
  error_code nullable
  created_at
  updated_at

control_events
  event_id PK
  stream_id
  seq
  at
  event_type
  agent_session_id nullable FK
  payload_json
  UNIQUE(stream_id, seq)

pending_terminal_facts
  agent_session_id PK FK
  request_id nullable FK
  fact_json
  updated_at
```

The schema intentionally has no columns for token, secret, cookie,
authorization, environment dump, prompt, provider frame, stdin line or
terminal output.

## Operation phase state machine

```text
accepted
  -> dispatched
  -> failed

dispatched
  -> side_effect_started
  -> failed

side_effect_started
  -> committed
  -> failed (only when failure is proven)
  -> unknown_outcome

committed
  -> completed
  -> failed
  -> unknown_outcome
```

`completed`, `failed`, and `unknown_outcome` are terminal for one request ID.

## Run transition contract

Allowed transitions:

```text
queued -> starting | cancelled
starting -> running | failed | cancelled | unknown_outcome
running -> waiting | verifying | failed | cancelled | unknown_outcome
waiting -> running | failed | cancelled | unknown_outcome
verifying -> running | review | failed | cancelled | unknown_outcome
review -> completed | failed | cancelled | unknown_outcome
```

Terminal states `completed`, `failed`, `cancelled`, and `unknown_outcome` have
no outgoing transition. A retry is a new Run.

## Recovery matrix

| Persisted fact | Recovery | Automatic side effect |
| --- | --- | --- |
| Terminal request/session | preserve | none |
| `accepted` / `dispatched` | `continuity_lost`, failed | none |
| `side_effect_started` | `unknown_outcome` | none |
| `committed` without terminal completion | `unknown_outcome` | none |
| retained verified terminal fact | preserve for exact reconciliation | none |
| Active session with no live in-process owner | `continuity_lost` | none |
