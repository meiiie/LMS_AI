# Runbook: Runtime Lifecycle Hook Failures

**Alert:** `WiiiRuntimeLifecycleHookFailure` from
`docs/runtime/alerts/prometheus-runtime-lifecycle.yml`
**Severity:** P3 ticket
**SLO impact:** requests continue by design, but a lifecycle extension failed.
Depending on the hook point, post-turn telemetry, memory, audit, or cleanup
work may be incomplete.

## Symptom shape

Lifecycle hook exceptions are swallowed so a faulty extension cannot break a
chat request. Wiii now emits `runtime.lifecycle.hook_failures`, exposed by
`/metrics` as `runtime_lifecycle_hook_failures`, with an `owner` label attached
to the hook registration and a `point` label such as `on_run_end`,
`on_run_error`, or `on_tool_end`. Legacy callers that do not provide an
explicit owner fall back to a bounded owner inferred from the hook module.
Wiii-owned runtime hooks are installed during FastAPI startup and emit
`runtime.lifecycle.hook_runs` as `runtime_lifecycle_hook_runs`, which confirms
that lifecycle registration and dispatch are active even when there are no
failures. Runtime-flow doctor endpoints include a
`lifecycle_registrations` report with schema
`wiii.runtime_lifecycle_registrations.v1`, produced by
`build_lifecycle_registration_report()`, so operators can verify installed
hook owners and default runtime hooks without inspecting request payloads.
Semantic-memory lifecycle observers are also startup-registered as
`engine.semantic_memory`; they emit
`runtime.semantic_memory.lifecycle.observed` /
`runtime.semantic_memory.lifecycle.event_appends` and append
`semantic_memory_lifecycle` events with schema
`wiii.semantic_memory_lifecycle.v1`. These events prove memory/audit ownership
at `on_run_end` and `on_run_error` without duplicating background memory writes.

## First 5 minutes

1. **Capture the `owner` and `point` labels** and deploy SHA.
2. **Search application logs** for `[lifecycle] hook` at the alert window. The
   log names the hook function and hook point without exposing payload content.
3. **Confirm registration metadata.** Open `/admin/runtime-flow/doctor/recent`
   and check `lifecycle_registrations.default_runtime_hooks.installed`,
   `owner_counts.engine.semantic_memory`, and `point_counts`. If the admin
   surface is unavailable, check the hook registration site or
   `Lifecycle.registrations_at(...)` in a shell/test harness to verify the
   explicit owner attached to the failing hook.
4. **Map owner + hook point to impact.** `engine.semantic_memory` at
   `on_run_end` suggests memory/audit follow-up, while runtime/service owners
   usually indicate telemetry, cleanup, or bridge code.

## Decision tree

### Branch A - `on_run_end` or `on_run_error`

- Inspect post-turn hooks registered by runtime, memory, or audit modules.
- Check whether finalization counters also show append failures. If yes, start
  with `native-dispatch-finalization.md` or `native-stream-finalization.md`.

### Branch B - tool or subagent hook points

- Inspect the relevant tool/subagent hook implementation and recent metadata
  shape changes.
- If the error is payload-shape related, fix the producer or hook parser. Do not
  disable lifecycle globally.

## Mitigation while debugging

- Remove or gate only the failing hook if it is clearly optional.
- Roll back recent changes to hook registration or hook payload parsing if the
  failure begins immediately after deploy.
- Keep lifecycle failure metrics enabled. They are the only compact signal that
  swallowed hook exceptions are accumulating.

## When the alert clears

- No new `runtime_lifecycle_hook_failures` samples for 60 minutes.
- Logs for the affected hook point show no repeated hook exception after the
  mitigation.

## Related runbooks

- `native-dispatch-finalization.md` - non-stream durable finalization.
- `native-stream-finalization.md` - streaming durable finalization.
- `runtime-flow-ledger-alerts.md` - runtime-flow doctor alerts.
