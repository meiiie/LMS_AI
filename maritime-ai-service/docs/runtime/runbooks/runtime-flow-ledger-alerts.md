# Runbook: Runtime-Flow Ledger Alerts

**Alerts:** `WiiiRuntimeFlowLedgerCritical`,
`WiiiRuntimeFlowLedgerError`, `WiiiRuntimeFlowLedgerWarningBurst`
from `docs/runtime/alerts/prometheus-runtime-flow-ledger.yml`
**Severity:** P1 page for critical, P2 page for error, P3 ticket for
warning bursts
**SLO impact:** these alerts do not directly mean user-visible downtime.
They mean the runtime control plane lost correlation, finalization, privacy,
or stream-integrity guarantees that make incidents diagnosable and safe.

## Symptom shape

Terminal streaming dispatch emits `runtime.runtime_flow_ledger.alerts` for
doctor alert codes derived from the terminal `runtime_flow_ledger`. The
Prometheus endpoint exposes that counter as
`runtime_runtime_flow_ledger_alerts` with these labels:

| Label | Meaning |
|-------|---------|
| `code` | Stable doctor alert code such as `missing_request_id` |
| `severity` | Doctor severity: `warning`, `error`, or `critical` |
| `status` | Stream dispatch terminal status: `success` or `error` |
| `transport` | Runtime transport, currently `stream/v3` |

## Alert code guide

| Code | Likely cause |
|------|--------------|
| `raw_content_flag` | Context provenance says raw/private content entered a ledger-visible diagnostic path |
| `provider_call_stage_request_id_mismatch` | Provider-call stage correlation disagrees with the turn request ID |
| `provider_call_stage_request_id_missing` | A provider-call stage did not receive a sanitized request ID |
| `missing_done_event` | SSE terminal `done` event was not observed before finalization |
| `failed_finalization` | Post-stream finalization reported error/failed/exception |
| `missing_request_id` | Ingress or stream coordinator did not preserve/generate request correlation |
| `context_warning` | Context provenance emitted a privacy-safe warning |

## First 5 minutes

1. **Capture the Prometheus labels.** Keep `code`, `severity`,
   `status`, and `transport`. Do not paste raw ledger payloads into incident
   channels.
2. **Open the aggregate doctor endpoint** for recent events:
   ```bash
   curl -sS "$WIII_API_BASE/api/v1/admin/runtime-flow/doctor/recent?limit=100" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```
   Inspect `status`, `alerts`, `request_correlation`, and `alert_trend`.
3. **Check whether the spike is deploy-correlated.** Compare the alert start
   time to the latest deploy SHA and any config changes touching stream
   dispatch, Wiii Connect, Composio, context provenance, or finalization.

## Decision tree

### Branch A - Critical privacy/correlation alert

- `raw_content_flag`: stop the affected canary or roll back the deploy that
  touched context assembly or ledger projection. Preserve the doctor response
  and inspect `context_provenance` code paths before re-enabling.
- `provider_call_stage_request_id_mismatch`: treat as a cross-boundary
  correlation bug. Inspect Wiii Connect request metadata, Composio provider
  headers, and any gateway action executor changes from the incident window.

### Branch B - Error-level stream or finalization alert

- `missing_done_event`: inspect SSE assembly and native stream dispatch first.
  If users also see broken or hanging chat, jump to `chat-5xx-surge.md` or
  `chat-latency-spike.md`.
- `failed_finalization`: inspect session event log, chat history persistence,
  and post-turn hooks. If the persistence layer is failing broadly, jump to
  `db-pool-exhaustion.md`.
- `provider_call_stage_request_id_missing`: verify every external app or
  provider call path receives sanitized `request_id` metadata before execution.

### Branch C - Warning burst

- `missing_request_id`: inspect API middleware, stream request headers, and
  stream coordinator fallback request ID generation. The desired behavior is
  preserve a trusted incoming ID or generate `req_*` before lifecycle, ledger,
  heartbeat, log, and finalization paths run.
- `context_warning`: inspect the aggregate `context_warnings` count in the
  doctor response. If one warning dominates, fix that context producer rather
  than suppressing the ledger alert.

## Mitigation while debugging

- Roll back the current deploy if the first alert appears immediately after
  code touching stream dispatch, Wiii Connect, provider adapters, context
  provenance, or finalization.
- If only native streaming is affected and sync chat remains healthy, disable
  `enable_native_stream_dispatch` for the affected environment until the
  regression is isolated.
- Keep `/metrics` and the runtime-flow doctor endpoint enabled. Disabling
  observability hides the control-plane failure rather than mitigating it.

## When the alert clears

- Critical and error counters must have no new events for 30 minutes.
- Warning bursts must stay below threshold for 60 minutes.
- `/api/v1/admin/runtime-flow/doctor/recent` should report `status="ready"` or
  show only understood residual warnings in `alert_trend`.

## Related runbooks

- `chat-5xx-surge.md` - user-visible chat failures.
- `chat-latency-spike.md` - stream stalls or slow finalization.
- `db-pool-exhaustion.md` - persistence-backed finalization failures.
- `provider-failover.md` - upstream provider degradation.
