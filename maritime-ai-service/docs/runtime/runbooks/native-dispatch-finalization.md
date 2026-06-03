# Runbook: Native Dispatch Finalization Failure

**Alert:** `WiiiNativeDispatchFinalizationFailure` from
`docs/runtime/alerts/prometheus-native-dispatch.yml`
**Severity:** P2 page
**SLO impact:** a non-stream chat run completed or failed, but Wiii could not
append durable evidence needed for wake, replay, tool-result audit, or incident
analysis.

## Symptom shape

Native dispatch emits `runtime.native_dispatch.finalization` after durable
append attempts in the non-stream chat path. The Prometheus endpoint exposes the
counter as `runtime_native_dispatch_finalization` with these labels:

| Label | Meaning |
|-------|---------|
| `stage` | Finalization stage: `assistant_message_append` or `tool_result_append` |
| `status` | Append outcome: `success` or `error` |
| `run_status` | Chat run outcome before append: `success` or `error` |
| `transport` | Runtime transport, currently `chat` |

## First 5 minutes

1. **Capture alert labels** and deploy SHA. `stage` tells whether the assistant
   closure event or a declared tool result failed to persist.
2. **Check session event log writes.** Inspect Postgres pool health, DB insert
   errors, and recent changes to `SessionEventLog.append`.
3. **Compare with stream finalization.** If stream and non-stream finalization
   alerts fire together, treat the event log backend as the shared suspect.

## Decision tree

### Branch A - `assistant_message_append`

- The run closure event did not persist. This can make wake/replay see an open
  turn or miss an error closure.
- Inspect the `assistant_message` payload shape for recent code changes, then
  inspect DB insert errors. If inserts fail broadly, use `db-pool-exhaustion.md`.

### Branch B - `tool_result_append`

- Tool-result replay/audit evidence did not persist. Inspect serialized
  `tool_calls` from response metadata and recent sanitizer changes.
- If one tool shape dominates, fix the tool metadata producer instead of
  broadening the event schema.

## Mitigation while debugging

- Roll back the current deploy if alerts start after changes to native dispatch,
  session event logging, tool-call metadata, or event payload sanitization.
- If only non-stream dispatch is affected, route canaried orgs back to the
  legacy chat path while preserving the alert and logs for root-cause analysis.

## When the alert clears

- No new `status="error"` finalization samples for 30 minutes.
- A focused native dispatch test should show both assistant and tool-result
  finalization counters incrementing with `status="success"`.

## Related runbooks

- `native-stream-finalization.md` - SSE stream finalization failures.
- `runtime-lifecycle-hook-failures.md` - post-turn hook failures.
- `db-pool-exhaustion.md` - persistence backend failures.
