# Runbook: Scheduled Task Executor

**Alerts:** `WiiiScheduledTaskExecutorPollError`,
`WiiiScheduledTaskExecutionFailure`, `WiiiScheduledTaskDeliveryMissed` from
`docs/runtime/alerts/prometheus-scheduled-task-executor.yml`
**Severity:** P3 ticket
**SLO impact:** chat can continue, but proactive reminders and autonomous
agent-invoke tasks may stop running or fail to reach the user.

## Symptom shape

The scheduled task executor emits these counters:

| Metric | Labels | Meaning |
|--------|--------|---------|
| `runtime.scheduled_tasks.polls` | `status` | Due-task polling outcome: `success` or `error` |
| `runtime.scheduled_tasks.due` | none | Count of due tasks returned by the worker poll path |
| `runtime.scheduled_tasks.runs` | `mode`, `status` | Per-task execution outcome for `agent` or `notification` mode |
| `runtime.scheduled_tasks.delivery` | `mode`, `status` | Result notification outcome: `delivered` or `not_delivered` |
| `runtime.scheduled_tasks.duration_ms` | `mode`, `status` | Per-task execution duration including notify and mark-executed/failed |

The Prometheus endpoint exposes them with underscores, for example
`runtime_scheduled_tasks_runs`.

## First 5 minutes

1. **Capture labels** from the alert: `mode` and `status` for run/delivery
   alerts, or `status=error` for poll alerts.
2. **Check whether the executor is running.** Confirm the backend process called
   `get_scheduled_task_executor().start()` and did not immediately shut down.
3. **Inspect scheduler repository logs** for missing org context, DB errors, or
   failed `mark_executed` / `mark_failed` updates.
4. **Run the opt-in live replay on staging** when DB writes are safe:
   `WIII_LIVE_SCHEDULER_REPLAY=1 python scripts/probe_live_scheduled_task_replay.py --allow-write --organization-id <org_id>`.
   The probe creates one reminder through `tool_schedule_reminder`, waits for a
   real due-time, verifies scoped Postgres due-task polling, WebSocket delivery,
   completed row state, and deletes the probe row by default.

## Live scoped replay probe

Use the live replay only in a staging or explicitly approved live maintenance
window. It requires both `WIII_LIVE_SCHEDULER_REPLAY=1` and `--allow-write`,
refuses `settings.environment=production` unless `--allow-production` is
provided, and deletes the probe row by default. Use `--keep-task` only when
preserving database evidence intentionally.

```powershell
cd maritime-ai-service
$env:WIII_LIVE_SCHEDULER_REPLAY='1'
python scripts\probe_live_scheduled_task_replay.py --allow-write --organization-id default
```

The probe writes one `scheduled_tasks` row through the real scheduler tool,
waits for clock due-time, reads due tasks with `allow_all_orgs=False`, executes
only the created task through `ScheduledTaskExecutor`, delivers through the real
`WebSocketAdapter`, verifies the completed database row, and avoids polling or
executing unrelated due tasks in the environment.

The accepted evidence artifact is hash/count-only. It must prove request-scoped
user/session/org hashes, `due_poll_allow_all_orgs=false`, the created task's org
hash matches the request scope, completed row status/run/last-run/next-run
state, WebSocket payload task/content hashes, and successful
`runtime.scheduled_tasks.polls`, `.due`, `.runs`, `.delivery`, and
`.duration_ms` observations. It must also prove the scheduler-tool,
repository-poll, executor, delivery, DB lifecycle, metric-label, and cleanup
contracts, and it must not include raw task IDs, user IDs, session IDs,
organization IDs, database rows, metric payloads, reminder descriptions, or
delivery payloads.

## Decision tree

### Branch A - poll error

- Inspect logs around `[EXECUTOR] Poll error` and repository calls to
  `get_due_tasks(allow_all_orgs=True)`.
- Verify the database is reachable and the `scheduled_tasks` table exists.
- If this follows a migration, verify scheduler repository SQL still selects
  `organization_id` so worker execution can preserve tenant scope.

### Branch B - agent run error or timeout

- Inspect logs around `[EXECUTOR] Task ... execution failed` or
  `[EXECUTOR] Task ... timed out`.
- Verify `scheduler_agent_timeout` is realistic for the current provider and
  tool budget.
- Check the corresponding runtime-flow metrics for provider/tool failures.
- Do not retry by hand without preserving the task's `organization_id`.

### Branch C - notification delivery missed

- Inspect `NotificationDispatcher.notify_task_result` logs and channel
  availability.
- If `runtime.scheduled_tasks.runs{status="success"}` is increasing while
  delivery misses rise, the autonomy loop is running but the user-visible
  result path is broken.
- Verify WebSocket/desktop notification routes before changing scheduler logic.

## Mitigation while debugging

- For broad execution failures, temporarily disable new proactive task creation
  at the product surface while keeping repository reads scoped.
- For provider timeouts, raise `scheduler_agent_timeout` only after checking the
  affected mode and recent provider latency.
- For delivery-only failures, keep the executor running so one-time tasks do not
  pile up silently, then repair the dispatcher path.

## When the alert clears

- No new `runtime_scheduled_tasks_polls{status="error"}` samples for 60 minutes.
- No new `runtime_scheduled_tasks_runs{status=~"error|timeout"}` samples for
  60 minutes.
- Delivery misses stop or match an intentional disabled channel deployment.

## Related runbooks

- `runtime-flow-ledger-alerts.md` - turn-level provider/tool/ledger failures.
- `semantic-memory-maintenance.md` - post-turn memory maintenance workers.
- `runtime-lifecycle-hook-failures.md` - post-turn hook side effects.
