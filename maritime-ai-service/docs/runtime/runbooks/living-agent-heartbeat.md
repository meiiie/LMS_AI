# Runbook: Living-Agent Heartbeat

**Alerts:** `WiiiLivingAgentHeartbeatCycleError`,
`WiiiLivingAgentHeartbeatActionFailure`,
`WiiiLivingAgentHeartbeatApprovalBacklog` from
`docs/runtime/alerts/prometheus-living-agent-heartbeat.yml`
**Severity:** P3 ticket
**SLO impact:** chat can continue, but Wiii's autonomous continuity, reflection,
journaling, briefing, skill review, or proactive re-engagement may stall.

## Symptom shape

The heartbeat loop emits these metrics:

| Metric | Labels | Meaning |
|--------|--------|---------|
| `runtime.living_agent.heartbeat.cycles` | `status` | Cycle result: `success`, `noop`, or `error` |
| `runtime.living_agent.heartbeat.duration_ms` | `status` | Cycle duration after planning, execution, persistence, and audit |
| `runtime.living_agent.heartbeat.actions` | `action_type`, `status` | Action result: `success`, `error`, `timeout`, or `queued` |
| `runtime.living_agent.heartbeat.action_duration_ms` | `action_type`, `status` | Per-action duration |

The Prometheus endpoint exposes them with underscores, for example
`runtime_living_agent_heartbeat_actions`.

## First 5 minutes

1. **Capture labels** from the alert: `status` for cycle alerts and
   `action_type/status` for action alerts.
2. **Check feature flags** for the affected action family:
   `enable_living_agent`, social browsing, briefing, journaling, skill learning,
   proactive messaging, and `living_agent_require_human_approval`.
3. **Check tenant scope logs.** Missing org context should fail closed and log
   `heartbeat_runtime_blocked_missing_org_context` with hash-only identifiers.
4. **Check autonomous discovery visibility.** WebSocket discovery notifications
   should be structured `proactive_message` payloads with
   `trigger="heartbeat_discovery"` and org-scoped delivery metadata.

## Decision tree

### Branch A - cycle error

- Inspect logs around `[HEARTBEAT] Cycle failed`.
- If the error happens before planning, check soul loading and emotion state
  loading.
- If it happens after actions, check emotional snapshot persistence,
  `save_state_to_db`, SoulBridge broadcast, and graduation checks.

### Branch B - action error or timeout

- Use the `action_type` label to narrow the subsystem:
  `browse_social`, `learn_topic`, `reflect`, `write_journal`, `send_briefing`,
  `review_skill`, or `check_goals`.
- For `timeout`, inspect local LLM/Ollama and tool latency before increasing
  the 60s action timeout.
- For `browse_social` or `learn_topic`, verify approval policy and tenant-safe
  memory reads before allowing broader autonomy.
- For discovery notification regressions, verify `notify_discovery_impl`
  carries `organization_id` metadata into `NotificationDispatcher` so a
  same-user session in another org does not receive the heartbeat discovery.

### Branch C - approval backlog

- Confirm whether `living_agent_require_human_approval=true` is intentional.
- Inspect `wiii_pending_actions` through an org-scoped admin path; do not query
  or mutate pending actions by raw action id alone.
- If backlog is expected during rollout, record the exception and keep the
  metric visible.

## Live heartbeat-cycle probe

Use the guarded probe when unit metrics are green but staging needs evidence
that a real heartbeat cycle can write durable living-agent rows:

```bash
cd maritime-ai-service
WIII_LIVE_HEARTBEAT_CYCLE_PROBE=1 python scripts/probe_live_heartbeat_cycle.py --allow-write
```

The default path runs a controlled heartbeat cycle for reflection and
journaling, then composes and audit-writes a briefing outside wall-clock
briefing windows. Output is hash/count-only and verifies rows in
`wiii_heartbeat_audit`, `wiii_journal`, `wiii_reflections`, `wiii_briefings`,
and `wiii_emotional_snapshots`.

The accepted evidence artifact must also prove request-scoped user/session/org
hash presence, matching requested/effective org hashes, planned and recorded
reflect/journal actions, per-action metadata keys without metadata values,
briefing content hash/count evidence, successful cycle/action counters, cycle
and action duration observations, DB-scope contracts for the living tables, and
explicit privacy flags for no raw user, session, org, DB row, metric payload,
emotional state, action target, action metadata value, briefing content, or
socket payload data.

To exercise a real proactive side effect without external channels, use:

```bash
WIII_LIVE_HEARTBEAT_CYCLE_PROBE=1 python scripts/probe_live_heartbeat_cycle.py --allow-write --include-proactive-websocket
```

That path runs heartbeat re-engagement through `ProactiveMessenger`,
`NotificationDispatcher`, and `WebSocketAdapter` against an in-memory
`ConnectionManager`, then verifies a `wiii_proactive_messages` row and a
`proactive_message` WebSocket payload. It requires
`living_agent_enable_proactive_messaging=true`; if guardrails block delivery,
the probe fails instead of treating action dispatch as success.

## Mitigation while debugging

- Disable only the affected sub-feature flag when possible; avoid disabling the
  entire living agent for a single action-type regression.
- Keep audit persistence enabled. Heartbeat audits are the durable evidence for
  autonomy behavior and graduation checks.
- Do not remove approval gates to clear queued-action alerts. Drain or resolve
  the queue through the approval path.

## When the alert clears

- No new `runtime_living_agent_heartbeat_cycles{status="error"}` samples for
  60 minutes.
- No new `runtime_living_agent_heartbeat_actions{status=~"error|timeout"}`
  samples for 60 minutes.
- Queued-action growth has stopped or is tied to an intentional human-approval
  rollout.

## Related runbooks

- `scheduled-task-executor.md` - user-scheduled autonomous reminders and agent
  tasks.
- `semantic-memory-maintenance.md` - post-turn memory maintenance workers.
- `runtime-lifecycle-hook-failures.md` - post-turn hook side effects.
