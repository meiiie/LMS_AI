# Runbook: Native Stream Finalization Failure

**Alert:** `WiiiNativeStreamFinalizationFailure` from
`docs/runtime/alerts/prometheus-native-stream-dispatch.yml`
**Severity:** P2 page
**SLO impact:** the user may have received a streamed answer, but Wiii may have
lost durable session evidence needed for wake, replay, runtime-flow diagnostics,
or post-turn incident analysis.

## Symptom shape

Native stream dispatch emits `runtime.native_stream_dispatch.finalization`
after finalization append attempts. The Prometheus endpoint exposes the counter
as `runtime_native_stream_dispatch_finalization` with these labels:

| Label | Meaning |
|-------|---------|
| `stage` | Finalization stage, currently `assistant_message_append` or `runtime_flow_ledger_append` |
| `status` | Append outcome: `success` or `error` |
| `stream_status` | Stream outcome before finalization: `success` or `error` |
| `transport` | Runtime transport, currently `stream/v3` |

## First 5 minutes

1. **Capture the alert labels** and deploy SHA. The `stage` label tells
   whether user-visible assistant evidence or runtime-flow ledger evidence was
   lost.
2. **Check session event log health.** If the backend is Postgres-backed, look
   for pool exhaustion or insert failures around the alert window. If it is
   in-memory, confirm the process did not restart during the incident window.
3. **Compare with stream health.** If `stream_status="error"`, inspect the
   upstream generator failure path and jump to `chat-5xx-surge.md` or
   `chat-latency-spike.md` when users are affected.

## Decision tree

### Branch A - `assistant_message_append`

- Durable session evidence for the assistant turn failed. Inspect
  `session_events` writes, DB pool state, and recent changes to
  `SessionEventLog.append`.
- If chat output reached users but session evidence is missing, preserve logs
  from the alert window before restarting the service. Replay/wake evidence may
  be incomplete for those turns.

### Branch B - `runtime_flow_ledger_append`

- The terminal ledger reached dispatch but was not persisted. Runtime-flow
  alert counters may still have fired, but `/admin/runtime-flow/doctor/recent`
  can under-count that window because durable ledger rows are missing.
- Inspect ledger payload shape and session event log inserts. If the payload is
  malformed, fix the ledger producer. If inserts are failing broadly, use
  `db-pool-exhaustion.md`.

## Mitigation while debugging

- Roll back the current deploy if the first alert appears after code touching
  native stream dispatch, session event logging, runtime-flow ledger projection,
  or database connection management.
- If sync chat remains healthy and only streaming finalization is affected,
  disable `enable_native_stream_dispatch` for the affected environment until the
  finalization path is stable.
- Do not disable `/metrics` or the finalization counter. It is the only compact
  signal that tells operators a streamed turn lost durable evidence.

## When the alert clears

- No new `status="error"` finalization samples for 30 minutes.
- Recent `/api/v1/admin/runtime-flow/doctor/recent` output should again show
  ledger event counts that match expected stream traffic.

## Related runbooks

- `runtime-flow-ledger-alerts.md` - ledger doctor alerts and request correlation.
- `chat-5xx-surge.md` - user-visible chat failures.
- `chat-latency-spike.md` - stream stalls or slow finalization.
- `db-pool-exhaustion.md` - persistence-backed finalization failures.
