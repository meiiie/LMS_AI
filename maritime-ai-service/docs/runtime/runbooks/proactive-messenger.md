# Runbook: Proactive Messenger

**Alerts:** `WiiiProactiveMessengerMissingOrgContext`,
`WiiiProactiveMessengerDeliveryFailed` from
`docs/runtime/alerts/prometheus-proactive-messenger.yml`
**Severity:** P3 ticket
**SLO impact:** chat can continue, but Wiii's autonomous outbound messages may
be blocked or fail after passing guardrails.

## Symptom shape

The proactive messenger emits these metrics:

| Metric | Labels | Meaning |
|--------|--------|---------|
| `runtime.living_agent.proactive.can_send` | `status`, `reason` | Guardrail decision: `allowed` or `blocked` with bounded reason |
| `runtime.living_agent.proactive.sends` | `status` | Send result: `delivered`, `delivery_failed`, `blocked_guardrail`, or `blocked_missing_org_context` |
| `runtime.living_agent.proactive.send_duration_ms` | `status` | End-to-end send attempt duration |

The Prometheus endpoint exposes them with underscores, for example
`runtime_living_agent_proactive_sends`.

## First 5 minutes

1. **Capture labels** from the alert: `status` and, for guardrail checks,
   `reason`.
2. **Check org context.** Missing org context should fail closed before delivery
   and log `proactive_message_blocked_missing_org_context` with hash-only user
   identifiers.
3. **Check channel delivery.** If `status="delivery_failed"`, inspect
   `channel_sender` and the configured outbound channel before changing
   proactive guardrails.
4. **Check product visibility for WebSocket outreach.** WebSocket sends should
   deliver a structured `proactive_message` payload. The desktop notification
   socket should render it as a proactive toast while keeping auth credentials
   out of the WebSocket URL.
5. **Run an approved live-channel probe** when external credentials and a safe
   recipient are available. The probe is opt-in and sends exactly one outbound
   message through `ProactiveMessenger`.

## Live credentialed channel probe

Use this only in staging or an explicitly approved live maintenance window. It
requires `WIII_LIVE_PROACTIVE_CHANNEL_PROBE=1`, `--allow-send`, and an explicit
`--recipient-id`; production also requires `--allow-production`. The probe
checks channel config, DB reachability for opt-out/audit behavior, current org
scope, guardrails, and `runtime.living_agent.proactive.*` metrics. It prints
hashes/counts only, never raw recipient IDs, message bodies, org identifiers, or
credentials. Expected evidence includes recipient/org/message hash-presence,
`send_attempt.raw_message_included=false`, channel support/enabled/credential
proof with `credential_value_included=false`, `can_send_allowed_count>=1`,
`send_delivered_count>=1`, `send_duration_observed=true`, database
opt-out/audit reachability, request-org context proof, metric-label privacy, and
privacy flags for raw message, recipient, org, delivery payload, and channel
credentials.

```powershell
cd maritime-ai-service
$env:WIII_LIVE_PROACTIVE_CHANNEL_PROBE='1'
python scripts\probe_live_proactive_channel.py --allow-send --channel telegram --recipient-id <safe_chat_id> --organization-id default
```

Supported channels are `telegram`, `messenger`, and `zalo`. Use an internal
test recipient, not a real learner, unless the send is part of an approved live
incident check.
The evidence artifact must show a single `operator_live_channel_probe` send,
request-org opt-out/audit scope, `can_send=allowed` with zero blocked guardrail
metrics, delivered-send and duration metrics, bounded metric-label strategy,
and no raw recipient, organization, message, trigger target, metric payload,
delivery payload, or channel credential values.

## Decision tree

### Branch A - missing org context

- Verify the caller set `current_org_id` before invoking `send` or `can_send`.
- Check whether a heartbeat re-engagement path dropped org context before
  calling `ProactiveMessenger`.
- Do not bypass the guardrail with a body/header org alone; the context must be
  request-scoped or otherwise resolved through the memory-scope resolver.

### Branch B - delivery failed

- Inspect `channel_sender.send_to_channel` for the selected channel.
- Verify the channel is enabled and credentials are present.
- For `channel="websocket"`, verify the payload type is `proactive_message`
  and rerun the browser acceptance:
  `cd wiii-desktop; npx playwright test -c playwright.runtime-ledger.config.ts --grep "proactive WebSocket"`.
- For credentialed outbound channels, run
  `scripts/probe_live_proactive_channel.py` with the affected channel and a safe
  recipient before changing delivery code.
- Keep anti-spam checks enabled while fixing transport; a delivery failure
  means guardrails passed.

### Branch C - blocked guardrail is high but not alerting

- Reasons such as `feature_disabled`, `quiet_hours`, `daily_limit`, `cooloff`,
  and `opted_out` are expected product controls.
- If they are unexpectedly high, tune the product policy in a separate change
  with owner approval.

## Mitigation while debugging

- For missing org context, fix the caller path and replay with the same org
  scope; do not manually deliver the raw content.
- For delivery failures, pause only the affected outbound channel if possible.
- Keep opt-out and daily-limit checks active.

## When the alert clears

- No new `runtime_living_agent_proactive_sends{status="delivery_failed"}`
  samples for 60 minutes.
- No new missing-org proactive samples for 60 minutes.
- Channel logs show delivery success or an intentional disabled-channel state.

## Related runbooks

- `living-agent-heartbeat.md` - heartbeat actions and approval queues.
- `scheduled-task-executor.md` - user-scheduled autonomous tasks.
- `runtime-lifecycle-hook-failures.md` - post-turn hook side effects.
