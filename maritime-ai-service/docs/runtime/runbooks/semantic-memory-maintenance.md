# Runbook: Semantic Memory Maintenance

**Alerts:** `WiiiSemanticMemoryMaintenanceError`,
`WiiiSemanticMemoryMaintenanceBrokerUnavailable` from
`docs/runtime/alerts/prometheus-semantic-memory-maintenance.yml`
**Severity:** P3 ticket
**SLO impact:** chat responses can continue, but post-turn pruning and
summarization may lag or fail. Long-term memory quality can degrade if this
stays broken.

## Symptom shape

Post-turn memory maintenance emits these counters:

| Metric | Labels | Meaning |
|--------|--------|---------|
| `runtime.semantic_memory.maintenance.enqueue` | `status`, `reason` | Taskiq handoff outcome: `enqueued`, `skipped`, or `error` |
| `runtime.semantic_memory.maintenance.runs` | `executor`, `status` | Maintenance execution outcome from `taskiq` or `local_fallback` |
| `runtime.semantic_memory.maintenance.pruned` | `executor` | Number of stale memories pruned |
| `runtime.semantic_memory.maintenance.summarized` | `executor` | Count of maintenance runs that produced a summary |

The Prometheus endpoint exposes them with underscores, for example
`runtime_semantic_memory_maintenance_runs`.

## First 5 minutes

1. **Capture labels** from the alert: `executor`, `status`, and/or `reason`.
2. **Check whether Taskiq is intended to be enabled.** If
   `ENABLE_BACKGROUND_TASKS=false`, enqueue skips are expected and should not
   page. If it is true, inspect the broker.
3. **Check recent memory write doctor output.** Use
   `/api/v1/admin/semantic-memory/doctor/recent` to see whether writes are
   blocked, missing org context, or succeeding while maintenance fails later.

## Decision tree

### Branch A - maintenance run error

- Inspect logs around `Failed to run semantic memory maintenance`.
- If `executor="taskiq"`, inspect the worker process and broker connection.
- If `executor="local_fallback"`, inspect the web process logs and recent
  changes to `prune_stale_memories` or `check_and_summarize`.

### Branch B - broker unavailable

- Verify `enable_background_tasks` and the Taskiq broker URL/config.
- If the broker is down, Wiii should fall back locally through
  `BackgroundTaskRunner._run_semantic_memory_maintenance`.
- Restore the broker before memory maintenance volume grows; local fallback is
  a resilience path, not the desired steady state for heavy memory work.

## Mitigation while debugging

- Keep interaction writes enabled. Do not disable semantic memory globally just
  to silence maintenance alerts.
- If pruning is the only failing step, fix `memory_lifecycle` and allow
  summarization to continue.
- If summarization is failing due to provider errors, memory writes can continue
  while summaries catch up later.

## Qdrant Sidecar Index

Wiii can use Qdrant as an ANN sidecar for high-dimensional active shadow
embedding spaces such as `nvidia/nv-embed-v1:4096`. PostgreSQL remains the
source of truth for memory, documents, tenant scope, metadata, and audit data.
Qdrant stores only vectors plus minimal filter payload.

Local Docker enables the sidecar by default through:

```bash
VECTOR_INDEX_BACKEND=qdrant
QDRANT_URL=http://qdrant:6333
```

Production keeps `VECTOR_INDEX_BACKEND=postgres` unless the operator explicitly
starts the profile:

```bash
VECTOR_INDEX_BACKEND=qdrant docker compose -f docker-compose.prod.yml --profile vector-index up -d
```

After promoting a new active shadow embedding space, rebuild Qdrant from
Postgres:

```bash
cd maritime-ai-service
python scripts/rebuild_qdrant_vector_index.py --batch-size 64
```

Expected result: `status` is `ok` or `skipped`, and `indexed_points` matches the
active shadow-vector row count for that entity. If Qdrant is unavailable,
retrieval falls back to the existing Postgres vector path. Rollback is:

```bash
VECTOR_INDEX_BACKEND=postgres
```

Then restart the app process. The Qdrant collection can be kept for future
rebuilds or dropped independently because it is not authoritative data.

## When the alert clears

- No new `runtime_semantic_memory_maintenance_runs{status="error"}` samples for
  60 minutes.
- Broker-unavailable enqueue samples stop or match an intentional
  `ENABLE_BACKGROUND_TASKS=false` deployment.
- Semantic memory doctor output shows writes are still hash/count-only and
  tenant-scoped.

## Related runbooks

- `runtime-lifecycle-hook-failures.md` - post-turn hook side effects.
- `native-stream-finalization.md` - streamed turn durable finalization.
- `runtime-flow-ledger-alerts.md` - runtime-flow doctor alerts.
