# Wiii OpenHuman Reference Audit

Status: Active reference audit

Owner: Project leadership

Created: 2026-05-26

Related issue: #660

Related docs:

- `docs/operations/WIII_REFERENCE_SYSTEMS_AUDIT_2026-05-25.md`
- `docs/operations/WIII_SYSTEM_CONTROL_PLANE.md`
- `docs/operations/WIII_SELF_HARNESS.md`
- `docs/operations/WIII_OPENCLAW_REFERENCE_AUDIT_2026-05-25.md`

## Purpose

This audit turns OpenHuman source-level observations into concrete Wiii
memory/context observability requirements. The goal is not to copy OpenHuman.
The goal is to make Wiii's chat, document, memory, and host context path
inspectable enough that maintainers can tell which sources shaped a turn
without reading raw prompts or uploaded documents.

## Source Snapshot

External code was originally inspected from an ignored local research
workspace. The current refreshed OpenHuman reference clone used for later
Composio/Connections audit work is kept outside the Wiii repository:

```text
../_reference_research/openhuman
```

Do not treat legacy `.Codex/` exploratory folders as canonical Wiii source
inputs or committed artifacts.

| Field | Value |
|---|---|
| Remote | `https://github.com/tinyhumansai/openhuman.git` |
| Original inspected commit | `0e4729e7f2214f2fed3e23fb8d352018c0393fb3` |
| Original commit date | `2026-05-25T23:33:40+05:30` |
| Original commit title | `test(memory): serialize tests that drive the process-global memory client (#2649)` |
| Refreshed local commit for 2026-05-28 Composio pass | `6736467` |
| Local checkout note | Later Composio/Connections checks use the external `_reference_research/openhuman` clone without vendoring it into Wiii. |
| Clone mode | shallow, sparse, no submodules |

Primary OpenHuman areas reviewed:

- `README.md`
- `gitbooks/README.md`
- `gitbooks/developing/architecture/agent-harness.md`
- `docs/agent-subagent-tool-flow.md`
- `gitbooks/features/obsidian-wiki/memory-tree.md`

## Audit Summary

OpenHuman's strongest lesson for Wiii is not a specific storage engine. It is
the product discipline of making context ingestion, memory recall, and tool
output compression visible as harness contracts:

- local versus managed-service boundaries are explicit
- every connected source feeds a provenance-aware Memory Tree pipeline
- agent turns load memory context with citations instead of hiding it in an
  uninspectable prompt blob
- heavy extraction and summarization happens after the hot path
- sub-agents inherit bounded parent context and return compact results instead
  of becoming nested full sessions
- the desktop memory surface exposes source, chunk, topic, and retrieval
  diagnostics to users

Wiii does not need to become OpenHuman. Wiii needs the same class of
inspectable facts for its own active product path: chat stream, uploaded
documents, LMS preview/apply, host context, visual/Code Studio routing, and
post-turn memory.

## OpenHuman Patterns To Adopt

### 1. Memory Has A Human-Readable Provenance Shape

OpenHuman's Memory Tree canonicalizes source data into bounded Markdown chunks
with deterministic IDs and provenance metadata before later scoring and tree
summaries.

Wiii should adopt the provenance shape, not the implementation. Uploaded
documents, RAG sources, semantic memory, core memory, and host context should
all produce a bounded turn ledger that says which source classes were present,
how many items were included, and whether citations/source refs were available.

### 2. Hot Path Stays Fast; Heavy Memory Work Runs Later

OpenHuman keeps ingest cheap in the hot path and sends embeddings, entity
extraction, sealing, and digests to background workers.

Wiii should keep chat response assembly focused on context selection and source
accounting. This audit slice therefore adds an observational Context Provenance
Ledger v1 instead of changing memory retrieval or write behavior.

### 3. Dynamic Memory Context Is A Turn Input, Not Prompt Drift

OpenHuman distinguishes a stable system prompt from dynamic per-turn memory
context. Memory context is injected with citations so the UI and operators can
show provenance.

Wiii currently assembles `conversation_history`, `semantic_context`,
`core_memory_block`, `document_context`, host context, and source refs into the
multi-agent context. The missing contract is a typed summary of that context
which can be emitted through `runtime_flow_ledger` without exposing raw text.

### 4. Sub-Agent Context Is Inherited And Bounded

OpenHuman's parent session owns memory loading. Sub-agents receive a filtered
or inherited parent context and return compact results; their inner history is
not spliced back into the parent.

Wiii should apply the same debugging rule: when a tool, visual lane, LMS action,
or Code Studio path misbehaves, first inspect the parent turn's ledger and
subagent boundary evidence before changing a leaf agent.

### 5. Token Compression Is A Contract, Not A Hope

OpenHuman treats large tool outputs and fetched content as budgeted payloads
that must be summarized, truncated, or compressed with identifiers preserved.

Wiii should continue recording large document and tool payloads as counts,
hashes, source refs, and warning codes. Runtime ledgers must never become raw
document or prompt dumps.

### 6. Memory Diagnostics Are Product Infrastructure

OpenHuman surfaces memory metrics, source counts, chunk counts, topic counts,
first/latest memory, vault links, and retrieval paths.

Wiii's first step is lower-level: stream metadata gets a context provenance
ledger, the native stream wrapper persists terminal runtime ledgers, and
`/admin/runtime-flow/doctor` exposes aggregate-only diagnostics for one
session window.

## Context Provenance Ledger v1

Wiii should emit a privacy-safe context ledger under:

```text
runtime_flow_ledger.context.context_provenance
```

The v1 schema records:

- conversation history presence, char count, history item count, current-history
  retrieval status/source/counts, context budget/compaction counts and
  warnings, and summary presence
- document context presence, attachment counts, parser names, media kinds,
  provenance levels, source-ref counts, and hashed attachment identifiers
- semantic memory context presence, typed memory counts, memory type names,
  user fact counts, and core-memory presence
- episodic prior-session recall presence, match counts, event type names, score
  range, org-scope/current-session-exclusion flags, and warning codes
- host context presence, declared surface, capability names, and action count
- warning codes such as `document_context_without_source_refs`,
  `memory_context_without_typed_items`, and
  `host_context_without_capabilities`
- explicit privacy metadata: `raw_content_included=false` and
  `identifier_strategy=hash_or_count_only`

The schema must not include:

- raw user message text
- raw assistant text
- uploaded document Markdown
- semantic memory content
- core memory content
- prior-session episodic snippets
- raw file names
- provider request/response bodies
- raw approval tokens
- tool output payloads

## Do Not Copy

Wiii should not copy these OpenHuman assumptions:

- **GPL implementation code.** This audit records design lessons only.
- **Personal local-first trust boundary.** Wiii is org-aware and LMS-aware, so
  tenant, role, course, host surface, and approval boundaries remain mandatory.
- **A wholesale Obsidian vault before source safety.** Wiii should first make
  turn provenance visible, then decide whether a user/admin memory vault is
  needed.
- **Broad auto-fetch before tenant controls.** Wiii should not ingest or recall
  background data unless org and user scope are proven.
- **Managed Composio/OAuth assumptions.** Wiii host tools and LMS actions need
  Wiii-owned capability and approval contracts.
- **Diagnostics with raw content.** Counts, warning codes, hashes, and bounded
  names are acceptable; raw document and memory text are not.

## Wiii Implementation Slice

This audit maps to issue #660 and the first implementation contract:

- `maritime-ai-service/app/engine/multi_agent/context_provenance_ledger.py`
  builds the privacy-safe context ledger.
- `maritime-ai-service/app/engine/multi_agent/runtime_flow_ledger.py` embeds it
  in stream metadata.
- `maritime-ai-service/app/api/v1/chat_stream.py` forwards middleware
  `request.state.request_id` into the stream coordinator, and
  `maritime-ai-service/app/services/chat_stream_coordinator.py` preserves that
  value or generates a backend fallback `request_id`. The same value reaches
  runtime ledger, chat lifecycle events, heartbeat metadata, stream correlation
  logs, and post-response finalization continuity context/log output.
- Wiii Connect execution requests now carry the same correlation boundary into
  provider-action preflight/execution: HTTP routes read middleware/header
  `request_id`, agent tools read state/runtime context `request_id`, and the
  sanitized value is written into execution gateway metadata and persistent
  action audit ledger records. Composio provider-call boundaries also attach the
  sanitized `X-Request-ID` header to schema, execute, file-upload staging, and
  Facebook Page-list calls, and expose the same value in sanitized provider
  result metadata.
- `maritime-ai-service/app/engine/multi_agent/runtime_flow_doctor.py`
  aggregates recent runtime ledgers into privacy-safe counts and can read them
  from org-scoped session events. It now reports aggregate-only
  `request_correlation` counts for request ID presence and provider-call stage
  correlation plus stable alert codes and hourly `alert_trend` buckets without
  echoing raw IDs. Terminal stream dispatch forwards those alert codes into
  Prometheus-compatible `runtime.runtime_flow_ledger.alerts` counters, so an
  external SLO sink can alert without reading ledger payloads. The runtime SLO
  now maps those counters to deployable Prometheus rules in
  `maritime-ai-service/docs/runtime/alerts/prometheus-runtime-flow-ledger.yml`
  and an on-call runbook in
  `maritime-ai-service/docs/runtime/runbooks/runtime-flow-ledger-alerts.md`.
  Unsafe counter tokens are hashed instead of echoed into reports. It also
  builds `wiii.runtime_flow_doctor_history.v1`, a per-hour aggregate history of
  recent doctor reports from durable `session_events`, so operators can inspect
  trend movement without raw session, request, prompt, answer, or provider
  payload data. The desktop Runtime tab now exposes the recent aggregate report
  and bucketed history in an operator panel for legacy/dev or platform-admin
  sessions, hides any unsafe route, warning, or alert counter label before
  rendering, and provides the matching session-event retention control as a
  dry-run-first apply workflow with aggregate-only matched/deleted counts.
- `maritime-ai-service/scripts/probe_live_semantic_memory_write_doctor.py`
  turns post-turn memory write provenance into opt-in runtime evidence. It
  appends real `wiii.semantic_memory_write.v1` audit payloads through the
  session-event-log boundary, validates the recent semantic-memory write doctor,
  proves org-scoped aggregation excludes cross-org writes and raw non-memory
  events, and emits `semantic-memory-write-evidence.json`
  (`wiii.live_semantic_memory_write_doctor.v1`) with only hashes, counts,
  statuses, warning codes, privacy flags, and the matching org-scoped aggregate
  history summary. The artifact now also carries a status-only
  `post_turn_lifecycle` proof that semantic interaction and maintenance
  scheduling is lifecycle-owned, uses `wiii.background_task_schedule.v1`, and
  did not route through the `BackgroundTaskRunner.schedule_all` compatibility
  wrapper. The same diagnostic boundary now exposes
  `/admin/semantic-memory/doctor/history` with
  `wiii.semantic_memory_write_doctor_history.v1` bucketed by
  `event_created_at_hour`, so operators can inspect
  `recent_semantic_memory_write_history` trends without raw memory text,
  session IDs, user IDs, or org IDs. Failed semantic-memory write artifacts are
  also redacted before upload for raw memory markers, message/response text,
  cross-org markers, user/session/org/request identifiers, UUID-like
  identifiers, and sensitive field names while still failing the release
  evidence gate.
- `wiii-desktop/src/components/connect/WiiiConnectPage.tsx` reads the
  semantic-memory recent/history doctor endpoints for platform-admin or
  legacy/dev sessions and renders the same aggregate-only write counts,
  status buckets, warning codes, backend, and privacy strategy in the Runtime
  tab.
- `wiii-desktop/playwright/runtime-ledger-panel.spec.ts` now includes the same
  semantic-memory doctor recent/history endpoints in the Runtime-tab browser
  acceptance, so the operator surface is verified in a rendered app, not only
  by unit tests.
- `maritime-ai-service/app/engine/runtime/session_event_log.py` exposes a
  bounded `get_recent_events()` query for recent runtime-flow windows without
  returning session identifiers to the diagnostic response. It also exposes a
  backend-agnostic `prune_older_than()` contract for in-memory and Postgres
  event logs, and `/admin/runtime-flow/session-events/prune` gives platform
  admins an explicit dry-run-first retention control that returns only
  aggregate matched/deleted counts plus scope booleans. The default operator
  window is `SESSION_EVENT_LOG_RETENTION_DAYS`; pruning is never automatic.
- `maritime-ai-service/app/engine/runtime/native_stream_dispatch.py` persists
  terminal `runtime_flow_ledger` events without mutating SSE chunks. It also
  emits `runtime.native_stream_dispatch.finalization` counters for
  `assistant_message_append` and `runtime_flow_ledger_append` outcomes, with
  deployable Prometheus rules and the
  `maritime-ai-service/docs/runtime/runbooks/native-stream-finalization.md`
  runbook covering durable-evidence loss after a streamed turn.
- `maritime-ai-service/app/engine/runtime/native_dispatch.py` now mirrors that
  durable-evidence signal for non-stream chat with
  `runtime.native_dispatch.finalization` counters on assistant-message and
  tool-result append outcomes.
- `maritime-ai-service/app/engine/runtime/lifecycle.py` emits
  `runtime.lifecycle.hook_failures` whenever a lifecycle extension raises while
  preserving the existing fail-open request behavior. Failures are labeled by
  hook point and explicit hook-registration owner, with a bounded module-derived
  fallback for legacy callers, so post-turn side-effect failures can route to an
  owning subsystem without exposing hook payloads. Startup now installs
  Wiii-owned runtime lifecycle hooks through that same registration contract and
  emits `runtime.lifecycle.hook_runs`, so operators can distinguish "hooks are
  firing" from "hooks failed". Runtime-flow doctor endpoints now include
  aggregate lifecycle hook registration counts in `runtime_config` plus a
  `lifecycle_registrations` report with
  `wiii.runtime_lifecycle_registrations.v1`, keeping the operator surface
  privacy-safe while making default-hook and owner/point drift visible in both
  the admin payload and the desktop Runtime tab.
- `maritime-ai-service/app/engine/semantic_memory/lifecycle_hooks.py`
  registers `engine.semantic_memory` observers for `on_run_end` and
  `on_run_error`. The hooks emit `runtime.semantic_memory.lifecycle.*` metrics
  and append `semantic_memory_lifecycle` events with
  `wiii.semantic_memory_lifecycle.v1`, proving post-turn memory/audit ownership
  without duplicating background semantic-memory writes or exposing raw user
  payloads through generic lifecycle hooks.
- `maritime-ai-service/app/services/post_turn_lifecycle.py` introduces
  `PostTurnLifecycleContext` and `wiii.post_turn_lifecycle.v1`, a typed
  raw-input boundary for finalization-time background scheduling. It now owns
  semantic-memory interaction and maintenance scheduling directly while
  `BackgroundTaskRunner.schedule_all` remains a compatibility wrapper into the
  same coordinator. It emits `runtime.post_turn.lifecycle.scheduling` and a
  raw-content-free summary so semantic-memory write/maintenance scheduling is
  no longer an implicit call hidden inside orchestrator finalization or an
  aggregate background-runner method.
  The sync JSON response metadata and stream terminal runtime-flow ledger
  finalization now carry this same status-only summary, and runtime-flow
  acceptance rejects raw message/response/user/session/request/org scope in the
  public post-turn lifecycle contract. Runtime-flow ledger finalization now
  keeps sanitized `wiii.background_task_schedule.v1` task-group evidence, and
  runtime-flow doctor also builds `post_turn_lifecycle_ledger`
  (`wiii.post_turn_lifecycle_ledger.v1`) from durable
  `finalization.post_turn_lifecycle` entries. It also builds the admin
  runtime-flow doctor `post_turn_lifecycle` report with
  `wiii.post_turn_lifecycle_metrics.v1`, aggregating post-turn and background
  scheduling metrics without raw identifiers. The desktop Runtime tab renders
  both the process metrics and durable ledger groups as
  `wiii-connect-runtime-post-turn-lifecycle`, keeping post-turn memory
  scheduling visible to operators without raw payloads. The guarded
  `semantic-memory-write-evidence.json` probe now appends a durable
  `runtime_flow_ledger` event and its validator requires the org-scoped
  runtime-flow doctor/history payload to contain
  `post_turn_lifecycle_ledger.event_count=1`, so staging evidence must prove
  the lifecycle summary survived the session-event-log boundary.
  The semantic-memory write evidence registry now requires the same
  lifecycle-owned scheduling proof before accepting the
  `semantic-memory-write-evidence.json` artifact.
- `maritime-ai-service/app/services/background_tasks.py` now returns
  `BackgroundTaskScheduleSummary` with `wiii.background_task_schedule.v1` and
  emits `runtime.background_tasks.scheduling` per task group. This makes
  semantic interaction storage, maintenance enqueue/fallback, memory
  summarization, profile stats, and reflection scheduling inspectable without
  exposing prompt, response, user, session, or organization identifiers.
- `maritime-ai-service/app/engine/semantic_memory/write_audit.py` emits
  `semantic_memory_write` audit events as hash/count-only provenance for
  post-turn memory writes, including interaction writes, direct fact extraction
  and upsert writes, insight extraction writes, and direct insight stores. In
  staging/production multi-tenant mode, memory writes fail closed when request
  org context is missing instead of falling into the default org.
- `maritime-ai-service/app/engine/semantic_memory/session_runtime.py` and
  `maritime-ai-service/app/api/v1/memories.py` apply the same fail-closed org
  context check before user-requested memory deletion or factory reset paths.
  The memory list response now carries a raw-content-free `summary` with total
  counts, type counts, latest timestamp, org-scope state, available controls,
  source-kind counts, and privacy metadata. `wiii-desktop` stores this as
  `memorySummary` and renders a compact MemoryTab status strip, making the
  user-facing memory surface inspectable without exposing audit payloads.
  `wiii-desktop/playwright/runtime-ledger-panel.spec.ts` now includes browser acceptance that opens the Settings memory tab, verifies the summary strip after
  fetch, clears all memories, verifies the summary updates, and keeps
  provenance/privacy internals out of visible UI copy.
- `maritime-ai-service/app/engine/semantic_memory/visual_memory.py` applies
  the same boundary before Vision description, embedding, and IMAGE_MEMORY
  persistence, with `visual_memory` write audits when a session log is present.
- Semantic-memory read paths now share the same fail-closed tenant boundary:
  context retrieval, prioritized insight retrieval, direct fact lookup,
  relevant fact search, visual-memory retrieval, and read-only memories/insights
  APIs all refuse to fallback to the default org in staging/production when
  request org context is missing. The context provenance ledger records
  `semantic_memory_read_blocked_missing_org_context` as a warning code when
  semantic memory context injection is skipped for this reason.
- `maritime-ai-service/app/api/v1/admin_gdpr.py` applies active-org scoping to
  GDPR semantic-memory export and forget operations. In multi-tenant mode,
  admin sessions must carry an active organization before memory export/delete
  opens a DB pool; allowed memory queries bind `AND organization_id = $2`.
- `maritime-ai-service/app/engine/semantic_memory/__init__.py` exposes semantic
  memory package exports lazily, so importing privacy/audit submodules during
  repository initialization does not pull `core.py` back into a circular import.
- `maritime-ai-service/app/repositories/insight_repository.py` now enforces
  that boundary at the repository layer for insight reads, category reads, and
  insight deletion. Missing staging/production org context blocks before DB
  access, direct SQL uses `AND organization_id = :org_id`, and logs use hashed
  user/org identifiers.
- `maritime-ai-service/app/repositories/semantic_memory_repository_runtime.py`
  now enforces that boundary for core memory CRUD, type reads, keyword/factory
  deletes, access-count updates, insight eviction, and repository-level running
  summaries. Missing staging/production org context blocks before DB access or
  inline embedding work, allowed operations always bind
  `organization_id = :org_id`, and blocked logs use hash-only user/session/org
  identifiers.
- `maritime-ai-service/app/repositories/fact_repository_query_runtime.py` and
  `fact_repository_mutation_runtime.py` now enforce that boundary for user fact
  reads, semantic fact search, type/similarity lookup, metadata updates, fact
  updates, and FIFO eviction. Missing staging/production org context blocks
  before DB access, allowed queries always bind `organization_id = :org_id`,
  and blocked logs use hash-only user/org identifiers.
- `maritime-ai-service/app/repositories/vector_memory_repository.py` and
  `fact_repository_triples.py` apply the same boundary to vector recall,
  lexical fallback recall, semantic triple lookup, triple save, and generated
  triple-content updates. Missing staging/production org context blocks before
  DB access or embedding generation, allowed operations always bind
  `organization_id = :org_id`, and blocked logs use hash-only identifiers.
- `maritime-ai-service/app/repositories/dense_search_repository.py`,
  `sparse_search_repository.py`, and `dense_search_repository_runtime.py`
  apply the same boundary to knowledge/RAG search and embedding chunk writes.
  Missing staging/production org context blocks dense search, sparse search,
  embedding upserts, chunk persistence, deletes, embedding reads, and counts
  before asyncpg pool acquisition; allowed reads still use the shared-KB
  `organization_id = :org_id OR organization_id IS NULL` contract, and blocked
  logs use hash-only node/org identifiers without raw query or chunk text.
- `maritime-ai-service/app/services/embedding_space_migration_service.py`
  and `legacy_embedding_reembed_service.py` keep embedding-space maintenance
  behind explicit operator acknowledgement. Dry-run planning remains available,
  but non-dry-run legacy re-embed, full-space backfill, and shadow-space
  promotion now raise unless `acknowledge_maintenance_window=true`, preventing
  accidental mass vector rewrites or runtime read-authority changes on
  `semantic_memories` and `knowledge_embeddings`.
- `maritime-ai-service/app/services/vision_processor.py` applies that boundary
  to multimodal PDF chunk persistence. Chunk writes resolve the active knowledge
  org scope, missing staging/production org context blocks before opening a DB
  session, and existing-chunk checks/updates include
  `AND organization_id = :org_id` so the same document/page/chunk tuple cannot
  update another tenant's row.
- `maritime-ai-service/app/api/v1/sources.py` and `knowledge.py` apply the
  same boundary to source detail/list reads and knowledge statistics. Source
  detail responses can include raw chunk content, so reads now require active
  org scope before pool/connection acquisition and only return the active org's
  rows plus shared-KB rows where `organization_id IS NULL`.
- `maritime-ai-service/app/api/v1/knowledge_visualization.py` applies the
  same active-org boundary to org knowledge visualization routes. Non-admin
  scatter, graph, and RAG-flow simulation calls must carry an active
  organization matching the route organization before membership lookup or
  service execution; platform admin bypass remains explicit. The service SQL
  itself continues to bind `organization_id` for embedding scatter, graph
  construction, and RAG-flow retrieval.
- `maritime-ai-service/app/api/v1/org_knowledge.py` keeps organization
  knowledge document lifecycle operations scoped through the active
  organization. Non-platform upload/list/detail/delete helpers require active
  org context matching the route org before role or membership lookup. Status
  lifecycle updates and delete tracking-row updates bind
  `AND organization_id = $2`, so a reused or attacker-supplied document id
  cannot update another tenant's tracking row.
- `maritime-ai-service/app/engine/agentic_rag/document_retriever.py` and
  `graph_rag_retriever.py` apply the same boundary to RAG evidence-image
  lookup and GraphRAG PostgreSQL fallback enrichment. Missing staging/production
  org context returns empty evidence/additional-doc results before opening DB
  connections, while allowed reads include the active-org plus shared-KB filter.
- `maritime-ai-service/app/api/v1/admin.py` applies active-org scoping to
  direct knowledge document list/delete SQL. In multi-tenant mode, platform
  admins must carry an active organization before listing or deleting knowledge
  chunks; allowed operations bind `organization_id = :org_id`, and delete logs
  use hashed document/org identifiers.
- `maritime-ai-service/app/repositories/chat_history_repository.py` now applies
  the same boundary to canonical chat history persistence and retrieval:
  message saves, recent/session/user history reads, user-name reads/updates,
  session lookup, and user-history deletion. Missing staging/production org
  context blocks before DB access, allowed operations always bind
  `organization_id = :org_id`, explicit org arguments remain supported for
  scoped calls, and logs use hash-only user/session identifiers.
- `maritime-ai-service/app/api/v1/admin_analytics.py` now applies the active
  organization boundary to aggregate admin analytics over `chat_history`,
  `llm_usage_log`, users, and memberships. In multi-tenant mode, overview,
  LLM-usage, and user analytics default to the authenticated active org, reject
  a mismatched requested `org_id`, and fail before opening a DB pool when the
  admin token has no active org. Responses expose only scope booleans and the
  `active_org_id_not_echoed` identifier strategy, not the raw organization id.
- `maritime-ai-service/app/repositories/thread_repository.py` applies that
  boundary to server-side conversation indexes. Thread upserts, list/read,
  rename/delete, extra-data summary updates, summary reads, and counts require
  a resolved org scope; upsert existence checks and updates are now filtered by
  user and org as well as thread id, and blocked logs use hash-only
  user/thread identifiers.
- `maritime-ai-service/app/api/v1/threads.py`,
  `app/repositories/chat_history_repository.py`,
  `app/engine/context_manager.py`, `app/engine/multi_agent/graph_process.py`,
  and chat-orchestrator summary handoff now pass active org scope explicitly
  into thread index and thread-message reads instead of relying only on ambient
  request context. This keeps list/get/admin-fallback, rename/delete, message
  pagination, session-summary persistence, and first-turn previous-session
  summarization inside the authenticated organization boundary.
- `maritime-ai-service/app/services/session_summarizer.py`,
  `app/tasks/summarize_tasks.py`, `app/engine/multi_agent/graph_support.py`,
  and `app/services/input_processor_context_runtime.py` now carry the same
  explicit org scope through cross-session summary reads and background summary
  writes. Layer 3 recent-summary context is fetched with the request
  organization, milestone/background summarization receives that org, and
  summary extra-data writes bind the same active organization.
- `maritime-ai-service/app/services/input_processor_context_runtime.py`,
  `app/services/session_manager.py`, `app/services/chat_orchestrator_runtime.py`,
  `app/services/chat_orchestrator_support.py`, and
  `app/api/v1/chat_context_endpoint_support.py` now pass request/auth org
  scope into current-history context reads, user-name reads/writes, and
  user/assistant message persistence. The active turn context,
  `/context/compact`, and `/context/info` no longer depend on ambient org
  context alone when loading or writing recent chat history. SessionManager's
  in-memory `SessionState` cache now uses the same org-aware key for explicit
  session/thread ids, recent-message fallback, pronoun/language state, and
  legacy request-context callers so two organizations cannot share anti-
  repetition or continuity state when a thread id collides.
- `maritime-ai-service/app/api/v1/chat.py` and
  `app/api/v1/chat_history_endpoint_support.py` now pass authenticated org
  scope into `/history/{user_id}` page reads and deletes, so transport-owned
  history administration binds the same organization boundary as the main
  conversation turn.
- `ChatContext.history_retrieval_summary` now records
  `wiii.chat_history_retrieval.v1`, a raw-content-free current-history
  provenance summary with source, status, selected/persisted/fallback counts,
  org-scoped flag, user-name presence, and warning codes. The multi-agent
  context and Context Provenance Ledger consume that typed summary so operators
  can inspect current-history injection without seeing conversation text.
- `ChatContext.context_budget_summary` now records
  `wiii.context_budget.v1`, a raw-content-free compaction summary with budget
  totals, utilization, included/dropped message counts, summary presence,
  langchain-message count, layer metadata, and warning codes. The multi-agent
  context, Context Provenance Ledger, runtime-flow ledger, desktop Runtime tab,
  and browser replay summary consume those typed counts without exposing prompt
  or conversation content.
- Subagent parent/child boundaries now emit typed hash/count-only evidence.
  `project_state_for_subagent` and `project_kwargs_for_subagent` still filter
  parent state before child execution, while `execute_subagent` attaches
  `wiii.subagent_execution_boundary.v1` with nested
  `wiii.subagent_handoff_boundary.v1` and `wiii.subagent_result_boundary.v1`
  summaries to the sanitized `SubagentResult`. Runtime-flow trace/ledger
  aggregate this as `wiii.subagent_boundary_trace.v1`, so a parent turn can
  show projected-key counts, dropped-key counts, output/source/tool counts, and
  warning codes without importing child working memory or raw tool payloads.
  The desktop Runtime tab and browser replay summary now render those
  subagent-boundary counts, warning counts, and raw-content flags as
  operator-facing evidence; the runtime-flow doctor and hourly doctor history
  also aggregate the same subagent warning/raw-content flags without child
  identifiers. The runtime-flow acceptance harness checks terminal subagent
  boundary schema/counts/warnings and rejects raw child payload keys before
  evidence can pass. For staging verification,
  `scripts/probe_live_subagent_boundary_replay.py` runs the real parallel
  executor, runtime-flow ledger, and runtime-flow doctor behind
  `WIII_LIVE_SUBAGENT_BOUNDARY_REPLAY=1 --allow-run --out`, producing only
  UTF-8 hash/count evidence. The registered artifact now requires request,
  session, and org hash-presence flags; fixed parallel result-status and
  result-count evidence; runtime-ledger done/report-count parity;
  handoff/result boundary aggregates; counts for sources, tools, evidence
  images, dropped keys, and private thinking; child-output sanitization proof;
  runtime-flow doctor aggregate parity; zero raw-content flags; and explicit
  raw-request/raw-secret absence. Failure artifacts from this probe are also
  redacted before upload, including raw markers, bearer values, sensitive field
  names, and raw request/session/org identifiers; they remain non-release
  evidence because registry checks still require `status=pass`.
  `.github/workflows/subagent-boundary-evidence.yml` runs contract tests on
  relevant PRs/pushes while reserving evidence generation for explicit
  `run_subagent_boundary_replay=true` dispatch or scheduled
  `WIII_SUBAGENT_BOUNDARY_EVIDENCE_ENABLED=1`, then uploads the sanitized JSON
  evidence artifact.
- `maritime-ai-service/app/repositories/scheduler_repository.py` applies the
  same boundary to proactive scheduled tasks. Task creation, user list reads,
  cancellation, due-task reads, and execution status updates require a resolved
  org scope and bind `organization_id = :org_id`; missing staging/production
  request org context blocks before DB access. The background executor uses an
  explicit all-org worker path, but due-task rows carry `organization_id` into
  Wiii turn context and mark-executed/mark-failed updates so autonomous tasks do
  not lose tenant scope.
- `maritime-ai-service/app/services/scheduled_task_executor.py` now emits
  `runtime.scheduled_tasks.polls`, `runtime.scheduled_tasks.due`,
  `runtime.scheduled_tasks.runs`, `runtime.scheduled_tasks.delivery`, and
  `runtime.scheduled_tasks.duration_ms` counters/histograms with bounded
  `mode` and `status` labels. This makes proactive reminders and scheduled
  agent-invoke work observable without storing task IDs, user IDs, raw task
  descriptions, or organization identifiers in metrics. The scheduled-task
  executor unit acceptance now runs a due reminder and a due agent-invoke task
  through the real notification dispatcher payload formatter, verifies
  org-scoped mark-executed calls, and checks delivered metrics for both modes.
  A second acceptance creates a reminder through `tool_schedule_reminder`, lets
  the worker pick it up, and delivers it through the real `WebSocketAdapter`
  and in-memory `ConnectionManager` contract. Task-result delivery metadata now
  carries `organization_id` into channel adapters so WebSocket notification
  sends can use the manager's org-scoped session filter instead of broadcasting
  to every same-user session.
  The desktop client now keeps a scheduled-task notification WebSocket open
  after authentication, sends first-message auth with OAuth/JWT or legacy
  API-key user/org scope, and turns `scheduled_task` deliveries into
  Vietnamese-first toasts. Browser acceptance exercises reminder creation
  through SSE `tool_schedule_reminder` evidence and the Runtime ledger
  `scheduled_tasks` row, then injects the WebSocket delivery event and verifies
  the visible reminder toast without exposing API keys in the URL or Runtime
  panel.
  For staging/live verification, `scripts/probe_live_scheduled_task_replay.py`
  now provides an explicit opt-in replay against the configured persistent
  Postgres scheduler repository. It writes one reminder via the real scheduler
  tool, waits for its real due-time, reads it back through scoped due-task
  polling with `allow_all_orgs=false`, executes the created task through the
  same worker observability side-effect helper, delivers the result through the
  real WebSocket notification adapter, verifies the active-to-completed DB
  lifecycle, and deletes the probe row unless `--keep-task` is requested. The probe now
  emits `wiii.live_scheduler_replay_probe.v1` with
  `raw_content_included=false`, and supports `--out` for direct UTF-8 evidence
  writes. The artifact contract now requires request-scoped user/session/org
  hashes, the `scheduled_tasks` table proof, scheduler-tool/repository/executor/
  delivery replay contracts, created-row org parity, completed
  status/run/last-run/next-run state, scoped due-poll evidence, WebSocket
  `scheduled_task` payload delivery with hashed task/content identity,
  successful poll/due/run/delivery/duration metric evidence with bounded
  mode/status labels, and cleanup evidence with `cleanup.deleted=true`,
  `raw_task_id_included=false`, and no raw user/session/org IDs, DB rows,
  metric payloads, descriptions, or delivery payloads, so a live autonomy replay
  cannot pass while hiding scope drift, metric loss, or leaked task content.
  Failure artifacts are also redacted before upload for task IDs,
  user/session/org identifiers, descriptions, and sensitive field names; they
  remain diagnostic-only because registry checks still require `status=pass`.
  `.github/workflows/autonomy-runtime-evidence.yml` runs its contract tests on
  PR/push while reserving live DB writes for explicit dispatch or
  `WIII_AUTONOMY_RUNTIME_EVIDENCE_ENABLED=1` scheduled evidence collection.
- `maritime-ai-service/app/repositories/learning_profile_repository.py` applies
  the same boundary to adaptive learning profiles. Profile reads, creation,
  weak/strong-area updates, and stats increments require a resolved org scope,
  bind `organization_id = :org_id`, and log only hash identifiers when blocked.
  Migration `054` changes `learning_profile` identity from `user_id` alone to
  `(organization_id, user_id)`, allowing the same LMS/user identifier to keep
  separate personalization state across tenants. Rollback can collapse per-org
  profiles back to one row per user, so operators should back up the table
  before downgrading if per-org learning history must be preserved.
- `maritime-ai-service/app/engine/character/character_repository.py` and
  `character_state.py` apply the same boundary to Wiii living character state.
  Character block reads, creation, updates, experience logs, experience reads,
  counts, and cleanup require a resolved org scope and bind
  `organization_id = :org_id`; missing staging/production org context blocks
  before DB access with hash-only logs. The state manager cache key includes
  org scope so the same user id cannot reuse living state across tenants.
  BackgroundTaskRunner passes `org_id` into character reflection so
  post-response reflection reads/writes do not depend on reset contextvars.
  Migration `055` changes character block uniqueness from `(user_id, label)`
  to `(organization_id, user_id, label)` and backfills required org ids.
  Rollback can collapse per-org character blocks back to one row per
  user/label, so operators should back up the table before downgrading if
  per-org living state must be preserved.
- `maritime-ai-service/app/engine/semantic_memory/cross_platform.py` applies
  the same boundary to cross-platform memory merge, activity summary, and
  platform activity reads. Merge SQL is org-filtered, blocked merges emit
  `cross_platform_memory_merge` write audits, and logs/merge metadata use
  hash-only identifiers instead of raw legacy platform IDs.
- `maritime-ai-service/app/engine/semantic_memory/temporal_graph.py` now
  scopes the in-memory Zep/Graphiti-style temporal graph by resolved
  organization context instead of `user_id` alone. Single-tenant behavior stays
  compatible, same-user graphs in different orgs stay isolated, and
  staging/production multi-tenant writes fail closed before entity/relation/
  episode mutation when org context is missing.
- `maritime-ai-service/app/repositories/user_graph_repository.py` now applies
  the same boundary to the Neo4j learning/user graph. User, module, topic,
  studied/completed, weak-at, and prerequisite operations preserve legacy
  single-tenant Cypher, but multi-tenant request-scoped operations match or
  merge nodes with `organization_id`; missing staging/production org context
  blocks before opening a Neo4j session and logs only hashed identifiers.
- `maritime-ai-service/app/repositories/neo4j_knowledge_repository.py`,
  `app/engine/agentic_rag/graph_rag_retriever.py`, and
  `app/services/graph_rag_service.py` now apply the same boundary to the
  Neo4j document/entity GraphRAG layer. Entity create, relation create,
  relation lookup, document-entity lookup, and legacy Neo4j hybrid search
  preserve single-tenant Cypher, but request-scoped multi-tenant paths
  match/merge with `organization_id`; missing staging/production org context
  blocks before opening a Neo4j session, and GraphRAG call-sites pass current
  org context into Neo4j lookups when available.
- `maritime-ai-service/app/engine/context_manager.py` applies the same
  fail-closed boundary to persistent running summaries. In request-scoped
  multi-tenant turns, in-memory summary cache keys include org scope, DB
  load/persist/delete paths use read/write scope resolvers, and missing
  production/staging org context cannot read legacy unscoped cache entries or
  fall back to the default org.
- `maritime-ai-service/app/core/security.py` applies the same boundary at
  authenticated identity projection. In staging/production multi-tenant mode,
  JWT and LMS-service JWT auth bind tenant context to the token's
  `active_organization_id`; `X-Organization-ID` may only match that token org,
  not override it, and header-only org context for token-bound auth is
  rejected. Optional-auth endpoints only fall back to anonymous when no
  credentials were supplied; invalid API keys, invalid Bearer tokens, and
  token/org mismatches remain hard auth failures instead of silently losing
  identity. General API-key and development compatibility paths remain
  unchanged.
- `maritime-ai-service/app/core/middleware.py` mirrors that boundary before
  setting request-scoped org `ContextVar`s. In staging/production multi-tenant
  mode, a Bearer request with `X-Organization-ID` must match the token's active
  org before middleware loads org metadata or sets downstream context; mismatch
  and header-only token-bound org attempts return 403 with no context leakage.
- `maritime-ai-service/app/auth/organization_context.py`,
  `token_service.py`, and first-party login routers keep token lifecycle aligned
  with that boundary. Google OAuth, dev-login, and magic-link flows resolve the
  default login org once, best-effort ensure membership, embed the same org into
  access tokens and refresh identity snapshots, and return that same org to the
  client. In strict staging/production multi-tenant mode, refresh rotation
  refuses legacy `refresh_tokens` schemas that cannot preserve Identity V2 org
  columns instead of minting org-less access tokens.
- `maritime-ai-service/app/services/chat_orchestrator_multi_agent.py` applies
  the same boundary to hot-path chat request scope. In staging/production
  multi-tenant mode, a chat turn without request/current organization context
  now fails before domain routing instead of silently using
  `default_organization_id`; development and single-tenant fallback behavior
  remains available.
- `maritime-ai-service/app/api/v1/chat.py` and `chat_stream.py` apply the
  same boundary at transport canonicalization. In staging/production
  multi-tenant mode, request-body `organization_id` is not promoted to the
  canonical chat identity when the authenticated identity has no active org;
  the request-scope guard then fails closed rather than letting body-only org
  data bypass tenant context.
- `maritime-ai-service/app/api/v1/websocket.py` applies the same boundary to
  WebSocket chat turns. In staging/production multi-tenant mode, the
  connection must establish an org during auth/query negotiation, per-message
  metadata cannot switch to another org or create a body-only org, and the
  downstream org `ContextVar` is reset after each turn so one WebSocket message
  cannot leak tenant context into the next.
- `maritime-ai-service/app/engine/living_agent/social_browser.py` now applies
  the same boundary to autonomous browsing memory reads and writes. Smart topic
  selection reads only org-scoped semantic memories, browsing-log writes fail
  closed without org context, and high-relevance discovery insights are stored
  as org-scoped `social_browsing_insight` writes with hash-only metadata and
  audit summaries.
- `maritime-ai-service/app/engine/living_agent/journal.py` applies the same
  boundary to daily autonomous journaling. Existing-entry checks, recent-entry
  reads, and journal inserts require a resolved org scope; missing staging/
  production org context blocks writing before DB reads or local-LLM calls.
- `maritime-ai-service/app/engine/living_agent/heartbeat_runtime_support.py`
  applies the same boundary to heartbeat pending actions and audit rows.
  Pending-action queue/load/complete paths and heartbeat audit inserts require
  resolved org scope, mutate rows with `AND organization_id = :org_id` where
  applicable, and skip persistence fail-closed when staging/production request
  org context is missing. The heartbeat loop now emits
  `runtime.living_agent.heartbeat.cycles`,
  `runtime.living_agent.heartbeat.duration_ms`,
  `runtime.living_agent.heartbeat.actions`, and
  `runtime.living_agent.heartbeat.action_duration_ms` with bounded status and
  action-type labels, so autonomous reflection, journaling, briefing, skill
  review, and approval queues are observable without raw action targets. The
  heartbeat audit acceptance now runs one scheduler cycle with reflect, journal,
  briefing, and proactive re-engagement actions, verifies each handler path is
  reached, and checks success metrics without requiring live outbound channels.
  Heartbeat discovery notifications now use a structured `proactive_message`
  payload with `heartbeat_discovery` trigger metadata and org-scoped WebSocket
  delivery, so autonomous discoveries are user-visible without broadcasting to
  same-user sessions in another organization. The guarded live probe
  `maritime-ai-service/scripts/probe_live_heartbeat_cycle.py` now turns that
  into an operator-run contract: `WIII_LIVE_HEARTBEAT_CYCLE_PROBE=1` plus
  `--allow-write` runs a controlled heartbeat cycle, checks org-scoped journal,
  reflection, briefing, heartbeat-audit, and emotional-state deltas, and can
  optionally exercise proactive WebSocket re-engagement with
  `--include-proactive-websocket`; probe output is hash/count-only and declares
  `raw_content_included=false`. The artifact contract now requires the cycle to
  be request-scoped, non-noop, error-free, to carry user/session/org hash
  presence plus requested/effective org parity, to plan and record reflection
  plus journal actions through the real scheduler boundary with metadata keys
  but without metadata values or raw targets, to write a briefing with only
  hashed/count evidence, to prove living-table scope contracts, and to expose
  successful heartbeat cycle/action/duration metric labels. It also requires
  explicit privacy flags proving no raw identifiers, DB rows, metric payloads,
  emotional state, action targets, action metadata values, briefing content, or
  socket payloads. The probe supports
  `--out` so staging evidence is UTF-8 JSON even when launched from PowerShell.
  Failed heartbeat artifacts are also redacted before upload for user/session/
  org identifiers, UUID-like identifiers, action targets containing those
  identifiers, and sensitive field names while still failing the release
  evidence gate. The shared autonomy evidence workflow validates that schema
  and can upload `autonomy-heartbeat-evidence.json` from staging without
  exposing user, session, or content identifiers.
- `maritime-ai-service/app/engine/living_agent/autonomy_manager.py` applies
  the same boundary to autonomy graduation. Graduation stats aggregate only
  org-scoped heartbeat audit rows, approved/pending graduation state is keyed
  by `(organization_id, key)`, and migration `053` backfills legacy autonomy
  state to the default org before adding the composite key.
- `maritime-ai-service/app/engine/living_agent/narrative_synthesizer.py`
  propagates the requested org into skill summaries and filters hot-path cached
  goals by org when an explicit org is supplied, so the living narrative cannot
  mix skill or goal state from another tenant.
- `maritime-ai-service/app/engine/living_agent/emotion_engine_support.py` and
  `emotion_engine.py` apply the same boundary to emotional persistence and
  known-user relationship tiers. Persistent state delete/load/insert paths are
  org-filtered, missing staging/production org context blocks state reads and
  writes, and the known-user cache is org-scoped while preserving legacy
  single-tenant/defaulted behavior.
- `maritime-ai-service/app/repositories/emotional_state_repository.py` applies
  the same boundary to emotional snapshot history. Snapshot saves, latest
  reads, history reads, and cleanup deletes require resolved org scope and use
  direct `organization_id = :org_id` filters so heartbeat snapshots and
  retention cannot cross tenant history.
- `maritime-ai-service/app/engine/living_agent/briefing_composer.py` applies
  the same boundary to scheduled briefings. Composition and delivery fail
  closed before LLM calls or outbound sends when staging/production org context
  is missing, browsing highlights are read per org, delivered-today suppression
  is keyed per org, and `wiii_briefings` audit rows include `organization_id`.
- `maritime-ai-service/app/engine/living_agent/proactive_messenger.py` applies
  the same boundary before autonomous outreach. Sends, opt-out writes, opt-out
  reads, and proactive message logs require a resolved org scope; missing
  staging/production org context fails closed before delivery, and logs use
  hash-only user/channel recipient references. It now emits
  `runtime.living_agent.proactive.can_send`,
  `runtime.living_agent.proactive.sends`, and
  `runtime.living_agent.proactive.send_duration_ms` with bounded guardrail and
  send-result labels, so operators can distinguish expected anti-spam blocks
  from missing-org and delivery failures without raw message content. Migration
  `050` backfills legacy proactive rows to the default org and changes opt-out
  preferences to a per-org user key. The WebSocket proactive channel now routes
  through `NotificationDispatcher` and the real `WebSocketAdapter` using a
  structured `proactive_message` payload; acceptance coverage proves a
  proactive send reaches only the current-org `ConnectionManager` session when
  the same user is also connected in another org. The desktop notification
  socket parses that proactive payload, keeps OAuth/API credentials out of the
  WebSocket URL, and browser acceptance verifies a Vietnamese-first proactive
  toast is visible to the user. For credentialed outbound channels,
  `scripts/probe_live_proactive_channel.py` now provides an explicit opt-in
  live probe that sends one proactive message through Telegram, Messenger, or
  Zalo only when an operator supplies `WIII_LIVE_PROACTIVE_CHANNEL_PROBE=1`,
  `--allow-send`, and a safe recipient; `--out` writes
  `wiii.live_proactive_channel_probe.v1` UTF-8 hash/count-only evidence. The
  artifact contract requires enabled-channel and credential-present proof,
  recipient/org/message hash-presence, send-attempt trigger/priority/raw-message
  flags, supported-channel proof, credential-value absence, database
  opt-out/audit reachability plus request-org scope, request-org context proof,
  non-empty message count, the fixed `operator_live_channel_probe` trigger, a
  single-outbound-send contract, `can_send=allowed` metric-count evidence with
  zero blocked guardrail metrics, delivered-send and duration metric-count
  evidence, bounded metric-label strategy, metric-label privacy, and raw
  message/recipient/org/trigger-target/metric-payload/delivery-payload/
  credential privacy flags. A channel replay cannot pass by merely returning
  `delivered=true` while skipping guardrail, telemetry, scope, or privacy proof.
  Failed proactive-channel artifacts are also redacted before upload for
  recipient identifiers, organization identifiers, message text, UUID-like
  identifiers, credential name/value pairs, and sensitive field names while
  still failing the release evidence gate. Failure artifacts now carry the same
  `wiii.live_evidence_setup_contract.v1` `required_next` diagnostics as the
  preflight sidecar, so a failed run remains audit-useful without becoming a
  substitute pass. The same autonomy workflow now runs
  `scripts/probe_live_proactive_channel.py --preflight-only` before a live
  send, producing `wiii.proactive_channel_preflight.v1` setup diagnostics
  without sending a message or archiving raw recipient values, credential
  names, or credential values. The preflight payload is validated with
  `validate_runtime_evidence_preflight.py`, printed to the step log/summary,
  and is not uploaded as a substitute artifact. When preflight blocks the live
  send, the workflow materializes a failed
  `autonomy-proactive-channel-evidence.json` diagnostic artifact with the same
  setup contract before exiting non-zero. The same autonomy workflow runs
  non-credentialed contract tests on PR/push and can upload
  `autonomy-proactive-channel-evidence.json` only through explicit dispatch or
  `WIII_PROACTIVE_CHANNEL_EVIDENCE_ENABLED=1` schedule.
- `maritime-ai-service/app/engine/living_agent/routine_tracker.py` applies
  the same boundary to learned user activity patterns. Interaction recording,
  routine reads, frequency calculation, and inactive-user discovery require a
  resolved org scope; migration `051` backfills legacy routines to the default
  org and changes routine profiles to a per-org user key so proactive timing
  cannot be learned or queried across tenants.
- `maritime-ai-service/app/engine/living_agent/reflector.py` applies the same
  boundary before daily/weekly self-reflection. Reflection generation, recent
  reflection reads, duplicate checks, saved entries, and journal/emotion/
  browsing/skill summaries use one resolved org scope; missing staging/
  production org context blocks generation before DB reads or local-LLM calls.
- `maritime-ai-service/app/engine/living_agent/goal_manager.py` applies the
  same boundary to dynamic autonomous goals. Goal creation, status/progress
  updates, stale-goal review, seeded goals, and goal queries require a resolved
  org scope and mutate rows with `AND organization_id = :org_id`. Migration
  `052` backfills legacy goals to the default org, makes org scope required,
  and adds an org/status/update index.
- `maritime-ai-service/app/engine/living_agent/identity_core.py` scopes the
  hot-path self-identity cache by organization. Identity context only compiles
  insights matching the current org scope, cold-path insight generation blocks
  missing staging/production org context before reflection or local-LLM reads,
  and generated insights are tagged with the resolved org.
- `maritime-ai-service/app/engine/living_agent/skill_builder.py` applies the
  same boundary to autonomous skill discovery, learning, usage tracking, skill
  listing, and metadata updates. Missing staging/production org context blocks
  learning before DB reads or local-LLM calls, row mutations include
  `AND organization_id = :org_id`, and logs use hash-only skill identifiers.
  `skill_learner.py` now persists metadata through this guarded builder path
  instead of updating `wiii_skills` by bare id.
- `ChatContext.memory_retrieval_summary` records typed, privacy-safe recall
  metrics for semantic context assembly: relevant memory count, insight count,
  user fact count, memory type names, fact type names, insight categories, and
  warning codes. `context_provenance_ledger` consumes that count-only summary
  so operators can inspect memory recall paths without raw memory text.
- `maritime-ai-service/app/engine/runtime/episodic_retrieval.py` applies the
  same fail-closed read-scope boundary before prior-session recall. When a
  request-scoped org is available, the query is org-filtered even when the
  caller omits `org_id`.
- `ChatContext.episodic_retrieval_summary` records typed, privacy-safe
  prior-session recall metrics: match count, event type names, score range,
  org-scope/current-session-exclusion flags, and warning codes.
  `context_provenance_ledger` consumes that count-only summary so operators can
  inspect episodic recall paths without exposing prior-session snippets.
- `maritime-ai-service/app/services/background_tasks.py` keeps the post-turn
  semantic-memory write as a minimum interaction task and schedules pruning plus
  threshold summarization as separate cold-path maintenance. When
  `enable_background_tasks=true` and a Taskiq broker is available, this
  maintenance is enqueued to the worker broker; otherwise it falls back to the
  existing FastAPI background task path. Fact extraction no longer runs
  stale-memory pruning inline, so memory-agent and explicit memory writes do
  not pay that cleanup cost before extracting facts. The handoff and execution
  path now emits `runtime.semantic_memory.maintenance.enqueue`,
  `runtime.semantic_memory.maintenance.runs`,
  `runtime.semantic_memory.maintenance.pruned`, and
  `runtime.semantic_memory.maintenance.summarized` counters, so operators can
  distinguish disabled background tasks, broker-unavailable local fallback,
  worker failures, and successful cold-path pruning/summarization without raw
  memory content.
- `maritime-ai-service/app/tasks/semantic_memory_tasks.py` is the broker-safe
  task entrypoint for semantic-memory maintenance. It restores org context,
  runs pruning, then checks summarization, allowing worker processes to rebuild
  their own `SemanticMemoryEngine` rather than depending on request-local
  service injection. Task results and logs use hash-only identifiers so broker
  result storage does not become a raw user/session identifier leak.
- `maritime-ai-service/app/services/memory_lifecycle.py` applies the same
  fail-closed org-context check before pruning can read or delete user facts,
  and emits `memory_pruning` write audits when a session log is available.
- `maritime-ai-service/app/engine/semantic_memory/write_doctor.py` aggregates
  recent memory-write audits and bucketed history into operator-safe memory
  diagnostics with `wiii.semantic_memory_write_doctor_history.v1`.
- `maritime-ai-service/app/engine/tools/memory_tools.py`,
  `app/engine/tools/rag_tools.py`, `app/engine/tools/tutor_tools.py`, and
  `app/engine/tools/scheduler_tools.py`, plus
  `app/engine/character/character_tools.py`, now bind ContextVar state to the
  active tool runtime identity instead of only mutating a shared per-task state
  object. When user, organization, chat session, or scheduler domain identity
  changes, memory tool caches, RAG sources/native thinking/reasoning trace/
  confidence, active tutor lesson ids, scheduled-task user/domain state, and
  Living character self-edit state reset before the next tool call, so reused
  async contexts cannot carry personal cache entries, provenance sources,
  learning sessions, scheduler targets, or character notes across tenants.
  Character note/read/experience tools also pass the resolved runtime
  organization into the character manager/repository instead of relying on a
  possibly stale ambient org context. The same logic preserves state for the
  same identity and still supports legacy callers that only pass `user_id` or
  no explicit runtime metadata.
- `maritime-ai-service/app/engine/search_platforms/facebook_context.py` and
  `app/services/chat_stream_coordinator.py` now treat the optional Facebook
  cookie as a request-scoped raw credential instead of an ambient value that can
  survive across a reused async context. Stream V3 binds either the current
  request's `x-facebook-cookie` value or an explicit empty cookie for the whole
  generator, then restores the previous ContextVar token in `finally`, so a
  later request without a cookie cannot inherit a prior user's logged-in
  Facebook session. The low-level `facebook_cookie_scope()` API gives tests and
  future endpoints the same scoped-reset contract without logging or persisting
  the cookie value.
- `maritime-ai-service/app/engine/search_platforms/adapters/tiktok_research.py`
  now binds its in-memory Client Access Token cache to a non-reversible
  fingerprint of the active TikTok `client_key`/`client_secret` pair. A cached
  provider token is reused only when the credential fingerprint still matches;
  credential rotation or a different runtime credential pair forces a fresh
  token exchange and overwrites the old cache entry. The fingerprint is not
  logged or serialized, and tests assert that raw key/secret values are not
  stored as the cache key.
- `maritime-ai-service/app/services/notifications/privacy.py` and the
  Telegram, Messenger, and Zalo notification adapters now keep outbound
  notification diagnostics on a hash/redacted boundary. Successful sends log
  `recipient_ref=sha256:...` rather than raw recipient ids, and the dispatcher
  uses the same hash-only marker for unknown-channel diagnostics. Provider
  errors, WebSocket failures, and network exceptions pass through
  `sanitize_notification_detail()`, which removes configured bot/API/OA
  credentials, URL query values such as `apikey`, `access_token`, `chat_id`,
  `user_id`, and `text`, plus the attempted message when it appears in an
  exception string. Messenger no longer returns provider response bodies in
  public `NotificationResult.detail`; Zalo, Telegram, WebSocket, and dispatcher
  paths preserve status/error usefulness without echoing raw tokens, recipients,
  or message text.
- `maritime-ai-service/app/auth/magic_link_session_store.py` now keeps
  magic-link WebSocket and Valkey session diagnostics on a hash/redacted
  boundary. In-memory and distributed register, missing-session, publish, and
  delivery logs emit `session_ref=sha256:...` instead of raw `session_id`
  values; WebSocket, Valkey publish/subscriber, payload-decode, shutdown, and
  connection failure diagnostics sanitize exception text and explicitly remove
  matching session ids and auth payload values before logging. Successful
  Valkey startup also avoids printing the configured Valkey URL, so credentials
  embedded in connection strings cannot appear in auth diagnostics.
- `maritime-ai-service/app/auth/magic_link_router.py` now applies the same
  hash/redacted boundary before the session-store layer. Magic-link creation,
  verification, missing WebSocket, timeout, disconnect, and WebSocket error
  diagnostics emit `email_ref`, `session_ref`, and `user_ref` hashes instead
  of raw email addresses, user ids, or WebSocket session ids. Magic-link auth
  audit metadata records `email_ref` for success/failure events, and WebSocket
  exception text is sanitized with the active session id removed before
  logging.
- `maritime-ai-service/app/auth/email_service.py` keeps the magic-link email
  delivery boundary on the same diagnostic contract. Resend success/failure
  logs and the development fallback emit `email_ref` instead of raw recipient
  addresses. Provider errors redact the recipient, verification URL/token,
  Resend API key, and configured sender before logging. The development
  fallback still lets the request endpoint return `dev_verify_url` outside
  production, but the logger no longer prints raw verification URLs.
- `maritime-ai-service/app/auth/auth_audit.py` now keeps fail-open audit
  persistence diagnostics on that same boundary. Database/driver failures emit
  `user_ref` and `org_ref` hashes plus provider/result status, while exception
  detail removes matching user, org, IP, user-agent, reason, and nested
  metadata values before passing through the runtime secret redactor.
- `maritime-ai-service/app/auth/token_service.py` now keeps refresh-token
  replay, rotation, and revocation diagnostics on the same hash/redacted auth
  boundary. Replay detection logs `user_ref=sha256:...` and
  `family_ref=sha256:...` instead of raw `user_id` or refresh-token
  `family_id`, and the `token_replay_detected` audit reason records only the
  family hash plus purge count. Auxiliary audit-failure diagnostics also pass
  through the runtime secret redactor before logging, preserving operator
  signal without leaking token family identifiers or user ids.
- `maritime-ai-service/app/auth/user_service.py` now keeps OAuth/federated
  identity-linking diagnostics on the same hash/redacted auth boundary. User
  create, identity link/unlink, exact-provider login, verified-email auto-link,
  unverified-email block, deactivate, and reactivate logs emit `user_ref`,
  `email_ref`, `provider_sub_ref`, or `identity_ref` hashes instead of raw
  email addresses, user ids, provider subjects, or identity ids. Identity
  linked/unlinked audit metadata records only the hash refs while preserving
  the internal raw values needed for database writes and token ownership.
- `maritime-ai-service/app/auth/google_oauth.py` and
  `dev_login_router.py` now keep first-party login diagnostics on that same
  boundary. Google OAuth token-exchange failures redact provider error text,
  authorization codes, and configured client secrets before logging or writing
  auth-audit `reason`; default-org assignment logs emit `user_ref`/`org_ref`.
  Dev-login fallback/audit diagnostics redact raw dev email/provider subject,
  and successful dev-login logs emit `user_ref`/`email_ref` while preserving
  the raw values only inside token issuance, audit ownership, and the expected
  client response.
- `maritime-ai-service/app/auth/lms_auth_router.py` and
  `lms_token_exchange.py` now apply the same diagnostic boundary to
  backend-to-backend LMS token exchange. Signature setup errors, request
  validation errors, exchange failures, connector-grant refresh warnings, and
  org-membership warnings log only `connector_ref`, `lms_user_ref`,
  `user_ref`, and `org_ref` hashes plus redacted detail. Public failure
  responses stay generic, and auth-audit metadata stores `connector_ref`
  instead of raw connector ids while raw LMS identity values remain available
  only to HMAC validation, identity federation, token issuance, and successful
  client responses.
- `maritime-ai-service/app/services/living_continuity.py` no longer writes
  Living sentiment episodes as raw SQL outside the memory boundary. Living
  episode persistence now resolves the same memory write scope, sets request
  org context for background execution, writes `organization_id`/`session_id`,
  appends `living_episode` write audits, passes org scope into relationship
  tier lookup, and blocks in staging/production multi-tenant mode when org
  context is missing.
- `maritime-ai-service/app/api/v1/admin.py` exposes
  `/admin/runtime-flow/doctor`, `/admin/runtime-flow/doctor/recent`,
  `/admin/runtime-flow/doctor/history`, and
  `/admin/semantic-memory/doctor/recent` plus
  `/admin/semantic-memory/doctor/history` as read-only platform-admin
  diagnostics with safe runtime flags for native stream dispatch and
  session-log backend. It also exposes
  `/admin/runtime-flow/session-events/prune` as a dry-run-default retention
  control whose desktop operator surface requires a matched dry-run before
  apply and never renders raw org IDs, event types, or event payloads.
- `maritime-ai-service/scripts/wiii_runtime_flow_acceptance.py` includes a
  source-backed LMS document preview replay scenario. The scenario injects
  `user_context.document_context` with source references plus LMS host
  capabilities, then requires the terminal runtime ledger to show uploaded
  documents, source refs, document media/source-ref kinds, host surface and
  capabilities, `preview_required=true`, and no apply attempt before approval.
- The same harness now writes a `browser_replay` evidence section for each
  accepted scenario when `--evidence-json` is used. Each case carries terminal
  `runtime_flow_ledger` and `runtime_flow_trace` as seeded assistant metadata,
  so desktop Playwright can replay backend-produced provenance evidence in the
  Runtime tab. Raw prompt text, raw answer text, and raw SSE event payloads are
  not exported; answer evidence is hash/length only. Safe token-derived
  booleans and hashes can remain visible when the underlying runtime produces
  them, but approval-token proof is owned by the LMS host bridge and
  test-course evidence lanes rather than required in the backend-to-browser
  summary artifact.
- `maritime-ai-service/tests/unit/test_context_provenance_ledger.py` proves
  source counts and warning codes without raw content leakage.
- `maritime-ai-service/tests/unit/test_wiii_runtime_flow_acceptance.py` proves
  the source-backed replay context is carried into request payloads and that
  the acceptance contract rejects LMS preview turns that attempt apply before
  approval.
- `maritime-ai-service/scripts/probe_live_lms_test_course_replay.py` turns the
  source-backed LMS preview replay into an opt-in live backend and credentialed
  external test-course probe. It requires
  `WIII_LIVE_LMS_TEST_COURSE_REPLAY=1`, `--allow-write`,
  `--allow-external-lms-write`, `WIII_LMS_TEST_COURSE_APPLY_URL`, and
  `WIII_LMS_TEST_COURSE_APPLY_TOKEN`, streams the uploaded-document turn
  through `/api/v1/chat/stream/v3`, requires
  terminal `lms_document_preview` ledger evidence, extracts the preview
  `host_action` without printing raw params, and posts authenticated
  `preview_created` plus `apply_confirmed` audit events to
  `/api/v1/host-actions/audit`. The probe then applies the approved patch to
  the configured external LMS test-course webhook, hashes endpoint,
  credential, request, course/lesson, preview-token, and content evidence, and
  keeps approval and LMS credentials out of Wiii audit payloads. The evidence
  contract now requires request/session/org/course/
  lesson hash presence, SSE V3 terminal-event proof, source-backed host
  capability proof, context-provenance privacy, saved finalization plus
  sanitized `wiii.post_turn_lifecycle.v1`, source-count parity across runtime
  provenance, preview host action, preview audit, and apply audit, hashed
  preview-to-apply audit linkage, audit status-code/action/metadata parity,
  raw-content audit metadata flags, external write acknowledgement, and
  explicit raw SSE/document/request/auth header/host-action/audit/preview-token/
  approval-token/external-LMS request/response/token/endpoint absence. `--out`
  writes the hash/count evidence as UTF-8 JSON without relying on shell
  redirection.
- `maritime-ai-service/tests/unit/test_probe_live_lms_test_course_replay.py`
  proves the live LMS probe guards, host-action extraction, audit payload
  shaping, token-safe summaries, and no-apply-before-approval evidence checks.
- `.github/workflows/lms-test-course-evidence.yml` runs the LMS replay probe
  contract tests on relevant PRs/pushes and can produce
  `lms-test-course-evidence.json` through explicit
  `workflow_dispatch run_lms_replay=true` or scheduled runs gated by
  `WIII_LMS_TEST_COURSE_EVIDENCE_ENABLED=1`; the artifact is registered as
  `wiii.live_lms_test_course_replay.v1` runtime evidence.
- The runtime acceptance harness now includes
  `semantic_memory_turn_context_replay`, which seeds a prior turn and requires
  the terminal ledger to report `expected_memory_retrieval_status="ready"`,
  at least one relevant memory, and at least one memory context before treating
  a memory-aware turn as accepted.
- The same harness now has an opt-in `--sync-parity` mode for scenarios marked
  `sync_parity=True`. It calls `/api/v1/chat` after the SSE replay and compares
  sync answer presence, provider/model/agent metadata, sanitized
  `runtime_flow_trace`, route authority, provider authority, visible tool
  surface, and blocked `external_app_action_plan` authority against the
  `/api/v1/chat/stream/v3` result. The marked parity set now includes casual
  chat, weather routing, connection-status control-plane prompts, and safe
  blocked external-action prompts; prelude/continuation cases stay SSE-only
  because the sync parity runner intentionally isolates sessions.
- `maritime-ai-service/tests/unit/test_wiii_connect_tools.py` now includes a
  backend execution acceptance that invokes the real Wiii Connect delegate tool,
  lets the integration worker select a curated Gmail action, runs the backend
  executor through schema, gateway, audit, and execute stages, then feeds the
  resulting tool call/result into `runtime_flow_trace` and
  `runtime_flow_ledger`. This turns provider/tool-loop observability into a
  runtime contract instead of a seeded UI-only ledger.
- `maritime-ai-service/scripts/probe_live_wiii_connect_action_replay.py`
  registers that external-app action contract as
  `wiii.live_wiii_connect_action_replay.v1` evidence. The artifact proves the
  request/session/user/org/prompt identities only by hash presence, keeps the
  provider worker stage sequence and argument-plan keys/counts explicit,
  requires org/user-scoped connection lookup plus execution audit stages, and
  records privacy flags showing raw prompt, request identifiers, provider
  payloads, audit metadata, connection identifiers, and final-answer text are
  absent from archived evidence. Failed action replay artifacts are also
  redacted before upload for raw prompt text, request/session/user/org
  identifiers, connection identifiers, provider markers, argument markers,
  bearer/API-key fields, and sensitive field names while still failing the
  release evidence gate.
- `maritime-ai-service/scripts/probe_live_wiii_connect_facebook_post_replay.py`
  registers the Facebook post preview/apply replay as
  `wiii.live_wiii_connect_facebook_post_replay.v1` evidence. The artifact
  proves request/session/user/org hash presence, preview approval recording,
  approval credential and preview evidence hash-presence, first-apply approval
  consumption, replay blocking before gateway/schema/provider execution,
  user/org-scoped storage lookup, provider executor count/privacy flags, and
  count/status-only audit stages while excluding post text, Page values,
  connection refs, approval tokens, API keys, account IDs, provider arguments,
  provider responses, request payloads, and raw replay responses. Failed
  Facebook post replay artifacts are redacted for raw message markers, Page
  values, request/session/user/org identifiers, connection identifiers,
  approval credentials, provider markers, bearer/API-key fields, and sensitive
  field names while still failing the release evidence gate.
- `maritime-ai-service/scripts/wiii_connect_composio_acceptance.py --out` now
  hardens the credentialed external-provider lane with structured evidence for
  connected-account selection, fail-closed and allowed gateway decisions, live
  schema readiness, required argument coverage, successful read-only execution
  metadata, and privacy flags that exclude bearer values/env names, connection
  refs, account IDs, raw schemas, provider arguments, provider payloads, and
  provider responses. The matching workflow now runs `--preflight-only` first,
  emitting `wiii.connect_composio_acceptance_preflight.v1` setup diagnostics
  without calling the backend or provider, so missing backend URL, bearer/auth
  setup, connected-account flags, or argument JSON fails before a live
  credentialed execution attempt. The preflight output omits raw backend URLs,
  bearer values/env names, connection refs, raw arguments, provider payloads,
  and provider responses, is printed to the GitHub step log/summary for
  operator diagnosis, and cannot stand in for the registered evidence artifact.
  When that validated preflight is not dispatch-ready, the workflow now writes
  a failed `wiii-connect-composio-acceptance-evidence.json` registered-artifact
  diagnostic with the same setup contract before exiting non-zero. This keeps
  completion audits source-bound and inspectable while still requiring a real
  connected-account read-only execution to pass the release gate.
- `maritime-ai-service/scripts/probe_live_provider_runtime.py` adds the guarded
  live provider side of that contract. It requires
  `WIII_LIVE_PROVIDER_RUNTIME_PROBE=1` plus `--allow-call`, routes through
  LLMPool/WiiiChatModel, forces a harmless `record_probe_fact` tool-call/
  tool-result roundtrip, emits linked tool-result and tracing-span evidence,
  records provider/model authority, proves Wiii-native runtime-boundary and
  forced tool-schema contracts, proves request/session/org scope by hash,
  requires an exact single hashed tool call, and keeps tool arguments, provider
  responses, provider payloads, request identifiers, and trace attributes
  hash/count-only. It can optionally verify terminal `/chat/stream/v3`
  `runtime_flow_ledger` provider/model authority, `runtime_authoritative=true`,
  done-event count parity, saved finalization, sanitized
  `wiii.post_turn_lifecycle.v1` evidence, request/session/org hashes, and
  stream privacy flags for SSE data, request payloads, prompts, and auth secrets
  behind `--include-stream-ledger --allow-stream-write`. The
  `.github/workflows/provider-runtime-evidence.yml` workflow runs provider
  probe contract tests on relevant PRs/pushes and can produce a
  UTF-8 `provider-runtime-evidence.json` artifact through explicit
  `workflow_dispatch allow_live_call=true` or scheduled runs gated by
  `WIII_PROVIDER_RUNTIME_EVIDENCE_ENABLED=1`. The workflow now runs
  `--preflight-only` first, producing only status/count readiness output so
  missing operator setup fails before any provider call without standing in for
  the live artifact. The preflight payload is printed to the step log/summary
  rather than uploaded as a sidecar artifact. The `vertex` provider path must be backed by
  `VERTEX_API_KEY`, the same setting consumed by `settings.vertex_api_key`.
  Failed provider runtime artifacts are also redacted before upload for raw
  request/session/user/org identifiers, stream prompts, API-key values,
  provider credential markers, sensitive field names, UUID-like identifiers,
  and forced tool argument values while still failing the release evidence gate.
- `tools/wiii_self_harness/runtime_evidence_registry.json` and
  `tools/wiii_self_harness/validate_runtime_evidence_registry.py` now provide a
  machine-checked Runtime Evidence Registry for the provider, subagent,
  scheduler, heartbeat, proactive-channel, LMS test-course, and browser Runtime
  replay evidence artifacts. The registry fails closed if a registered workflow drops
  `contents: read`, artifact upload, schema validation, live env flag, explicit
  guard flag, dispatch/schedule gate, unique JSON artifact name, or introduces
  `pull_request_target`. Registry root, requirement, freshness, payload-check,
  and payload-check `when` objects are closed-schema allowlists, so typoed
  fields or decorative config cannot silently bypass validation. Registry proof
  paths must use validator-approved dot-path syntax: `payload_checks[].path`
  may use explicit `*` wildcard segments for list entries only, while freshness
  timestamps, `length_equals_path`, and payload-check `when` paths may not
  because artifact validation reads those through single-value lookup.
  `length_equals_path` subjects must still be JSON arrays, so object maps
  cannot stand in for ordered replay or audit sequences.
  Payload-check operation
  values are typed before artifact validation: `min` must be a JSON number,
  `sorted_equals` must be a list, and payload-check `when` clauses must select
  exactly one explicit `equals` or `not_equals` condition instead of falling
  back to truthiness. Expected `equals`, `sorted_equals` entries, and `when`
  comparison values must be non-null JSON scalars, keeping proof expectations
  simple and deterministic. It rejects broadened
  workflow permissions:
  registered evidence workflows must keep top-level permissions exactly at
  `contents: read`, with no extra scopes, `write` permissions, or job-level
  overrides. Registered evidence workflow paths must live directly under
  `.github/workflows/`, so registry entries cannot point at arbitrary YAML files
  outside GitHub Actions execution. It also fails if the workflow no longer
  runs the registered contract tests, no longer validates the registered
  artifact with the matching `--requirement-id`, or uploads a different
  artifact path under the registered evidence token. Contract-test run-step path
  matches must be bounded and shell comments are ignored, so a commented-out
  `pytest`/`vitest` command or `test_file.py.disabled` cannot stand in for
  `test_file.py`. Registered contract tests
  must be actual Python `test_*.py` files or TypeScript `*.test.ts`/`*.spec.ts`
  test files, so helper modules, docs, or data files cannot stand in as proof.
  Contract-test paths must also be unique after normalized repo-relative path
  comparison, so the same test cannot inflate coverage through equivalent path
  spellings.
  Each registered artifact must forbid baseline
  secret payload tokens `api_key`, `access_token`, and `authorization`, so live
  evidence privacy does not depend only on probe-specific raw markers.
  Registered `forbidden_payload_regexes` must compile and remain unique within
  each requirement, so malformed or duplicate privacy regexes fail in the
  registry gate before runtime artifact validation.
  Registry string-list obligations such as forbidden tokens, contract tests,
  live env flags, guard tokens, gates, and artifact tokens must not duplicate
  values, preventing repeated entries from inflating proof coverage. Forbidden
  payload tokens must also be unique after case folding, matching the
  artifact validator's case-insensitive secret scan.
  Critical top-level workflow keys (`on`, `permissions`, `concurrency`, and
  `jobs`) must be unique, so a later duplicate block or scalar assignment
  cannot override the safe block that the validator inspected.
  Registered evidence workflow checkouts must
  set `persist-credentials: false`, so CI proof jobs do not keep GitHub tokens
  in local git configuration after checkout. Registered evidence workflows must
  keep every `uses:` step as a real step field directly under a job-level
  `steps:` list on the approved core-action allowlist and pin it to a
  40-character commit SHA instead of a mutable version tag; third-party, local,
  and shell-text action references fail closed unless the allowlist changes
  intentionally. They must also keep top-level concurrency scoped to the
  workflow, event, and ref, and use
  `cancel-in-progress: ${{ github.event_name == 'pull_request' }}`, so PR
  reruns collapse without canceling scheduled or manually dispatched runtime
  evidence. Manual live-evidence gates registered as lowercase snake-case
  `allow_*` or `run_*` tokens must be `workflow_dispatch` boolean inputs with
  `default: false` and must be referenced by an `inputs.<name> == true`
  dispatch condition. Scheduled live-evidence gates registered as uppercase
  `WIII_*_EVIDENCE_ENABLED` tokens must be guarded by `vars.<name> == '1'`, so
  nightly runtime evidence remains opt-in through the repository or environment
  variable boundary. Each
  registered requirement must declare exactly one manual dispatch gate and
  exactly one scheduled vars gate, and unsupported gate-token shapes fail
  before workflow inspection. The live evidence job's job-level `if:` must
  bind those registered manual and scheduled gate tokens as the exact
  dispatch-or-schedule expression and must not add fallback events such as
  `push`; mentioning the same token in an env block, comment, setup step, or
  echo is not accepted as job scheduling proof because the validator reads job
  `if:` expressions rather than whole-file text. Manual dispatch inputs must be real children of the
  top-level `on: workflow_dispatch` event and declare non-comment
  `type: boolean` and `default: false` fields, so commented schema hints or
  copied fake event blocks cannot turn an unsafe manual input into an accepted
  live-run gate. Manual dispatch input names and schema fields that control
  description, required status, type, and default must not be duplicated, so a
  later YAML key cannot override the opt-in `default: false` gate the validator
  inspected. Event names directly under the top-level `on:` map must be unique,
  so a later duplicate `push` or `workflow_dispatch` block cannot override the
  filtered/gated event block the validator inspected. Registered live
  env flags must be uppercase `WIII_*` environment variables, must not reuse
  scheduled `_EVIDENCE_ENABLED` gate tokens, and must be assigned as
  `WIII_*: "1"` inside a real workflow `env:` map. A shell `run: |` line or
  unrelated YAML field that only spells the same flag is not accepted as live
  runtime enablement. Workflow `env:` maps must not duplicate registered live
  env flags, so a later YAML key cannot override the `WIII_*: "1"` value the
  validator inspected. Every registered guard token must be an
  explicit `--allow-*` lowercase kebab-case CLI flag and must appear in the
  same workflow step that invokes the registered probe script, so token-only
  mentions cannot stand in for live-run proof. The registered probe path is
  matched as a bounded command token after shell comments are stripped, so a
  commented-out probe command or path-prefix spoof such as `probe.py.disabled`
  cannot stand in for live evidence execution. Registered probes must be Python
  `.py` or Node ESM `.mjs` scripts, so the registry cannot point live proof at
  arbitrary text, docs, or data files. The live evidence job must also
  checkout the repository with `persist-credentials: false` before invoking the
  registered probe, so artifact generation cannot rely on checkout state from
  another job or from after registered code has already run. The checkout
  credential setting must be a direct `with:` map scalar on a real checkout
  `uses:` step, so commented `persist-credentials: false` hints, fake
  `uses: actions/checkout` lines, or YAML-looking `- uses:` list items inside
  `run: |` cannot stand in for a hardened checkout.
  When a registered
  live probe uses a multiline `run: |` step, that step must start with
  `set -euo pipefail`, so
  missing shell inputs and pipeline failures fail closed before artifact
  validation or upload. The registered probe must be invoked by a direct shell
  command line whose first executed argument is the probe path (`python` /
  `python3` for `.py` probes or `node` for `.mjs` probes); `echo`,
  `python -m ...`, or wrapper text that merely mentions the probe path does not
  count, and probe guard tokens plus Python probe `--out <artifact>` must appear
  as argv on that same direct probe command before any shell control operator.
  Text after `;`, `&&`, pipes, or another command cannot satisfy the probe
  contract. For Python probes, the same invocation step must write
  the registered artifact with `--out <artifact>` using an exact artifact
  filename match. Each runtime evidence requirement must also have one workflow
  job that binds the registered live env flag, probe guard, artifact validator
  command with the matching `--requirement-id`, exact artifact filename, and
  exact artifact upload token, so validation and upload cannot drift away from
  the probe that produced the payload or pass through path-prefix/token-prefix
  spoofing. The artifact validator proof must be a Python command that invokes
  the canonical `tools/wiii_self_harness/validate_runtime_evidence_artifact.py`
  path, or `../tools/wiii_self_harness/validate_runtime_evidence_artifact.py`
  from component working directories, so an `echo`, text-only mention, or
  same-named validator script in another directory does not count as artifact
  validation. The validator command must pass exactly one artifact positional
  and exactly one `--requirement-id` value matching the registry entry, so later
  text or extra arguments cannot spoof a different validation target. The upload
  step must then target that same filename in the validation step's
  `working-directory`, or the bare filename when no working directory is set;
  registered upload enforcement uses that job-local validation-derived path, so
  a second upload step cannot reuse the same artifact token for a different
  same-basename sidecar.
  The same job must order those steps as probe, then artifact validation, then upload, so
  unvalidated payloads cannot be uploaded as runtime evidence. The live evidence job must either execute all registered contract
  tests itself or declare
  `needs: contract` against a contract job that checks out the repo with
  `persist-credentials: false` before running those registered tests and has no
  job-level `if:`, so scheduled/manual runtime evidence cannot bypass or
  conditionally skip the contract job. Any workflow reference to
  the GitHub Actions `secrets` context, including dot or bracket syntax, must
  stay inside a job whose `if:` exactly matches one registered
  workflow-dispatch/schedule evidence gate pair and that job must declare
  `needs: contract`. The same job must also match a registered live evidence
  requirement by live env flag, probe guard, validator command, and
  validation-derived upload path, so a gated sidecar job cannot hold credentials
  outside the runtime proof chain; top-level, contract-job, PR, or push secret
  references fail registry validation. When a registered live probe exposes
  `allow_production`, its workflow must expose a manual `allow_production`
  gate; the input must be manual-only, boolean, default false,
  unique by input name, and free of duplicated schema fields such as
  `description`, `required`, `type`, or `default`;
  `ALLOW_PRODUCTION_INPUT` must derive only from
  `workflow_dispatch && inputs.allow_production || false` inside a real
  workflow `env:` map rather than a comment or text block, must not duplicate
  within that map, and must be bound on the same registered live probe step
  that appends the production override flag; each registered probe command must
  receive the appended production-override args array without resetting,
  unsetting, or redeclaring that array after the append, including through
  shell read/mapfile builtins;
  `--allow-production` may only be appended inside the explicit
  `ALLOW_PRODUCTION_INPUT == "true"` shell guard. The production-override scan
  ignores heredoc bodies, including non-identifier delimiter words, so copied
  guard text inside generated files cannot stand in for executed shell control
  flow, and it does not treat shell here-strings as heredocs. For registered
  Python probes, every live guard token must also be a real `argparse`
  `add_argument(..., action="store_true")` CLI flag, so comments, constants,
  and docstrings cannot spoof probe-side operator acknowledgements. For
  registered MJS probes, every live guard token must be enforced through a
  top-level fail-closed `process.argv.includes(...)` check, and registry
  validation ignores comments, nested unused functions, and template-literal
  usage text when proving that guard. The
  MJS `fail()` helper must exit with a non-zero literal status so a missing
  operator acknowledgement cannot be logged as a successful run. The probe-level
  unit contracts also force `settings.environment=production` and prove each
  production-aware live probe refuses without `--allow-production` while
  accepting the same guard path with the explicit acknowledgement. Every registered live
  evidence job must also declare `environment: wiii-runtime-evidence`, giving
  maintainers one GitHub Environment where approvals, environment-scoped
  secrets, and deployment history can be configured for runtime evidence
  collection. Registered
  evidence jobs must also declare bounded
  `timeout-minutes` values, so hung live probes fail clearly
  instead of consuming runners indefinitely. Registered evidence workflows must
  keep workflow job IDs unique inside the `jobs:` map, so a later duplicate job
  cannot override the contract job or guarded live-evidence job that the
  validator inspected. Registered evidence workflows must
  not duplicate job-level control fields that determine execution order,
  gating, environment, runner, timeout, or steps, so a later YAML field cannot
  override the safe contract dependency or live-run gate the validator inspected.
  Registered evidence workflows must
  not enable `continue-on-error`; probe, validator, upload, and contract
  failures must stop as failed CI evidence rather than being masked by a later
  artifact upload. Registered evidence workflows must also not enable shell
  xtrace (`set -x`, `set -o xtrace`, `bash -x`, or `sh -x`) because traced
  commands can leak secret-bearing provider and runtime arguments into GitHub
  Actions logs. Registered artifact upload steps
  must use `if: always()`, `if-no-files-found: error`, and bounded
  `retention-days`, so failed evidence runs can still leave an
  operator-inspectable artifact when a payload was produced while missing
  expected evidence files fail loudly. Those upload fail-safe fields must be
  non-comment YAML scalars on the real upload step or its `with:` map, so
  commented `if: always()` / `if-no-files-found: error` hints or matching
  lines inside multiline `path: |` bodies cannot stand in for real upload behavior.
  Upload step fields and upload `with:` fields that control action identity,
  failure preservation, retention, and paths must not be duplicated, so a later
  YAML field cannot override the safe value the validator inspected.
  Each upload path must stay to exactly one explicit repo-relative JSON
  evidence file whose basename matches the registered artifact, with no globs,
  directory-only paths, expressions, environment-variable or home-directory
  expansion, absolute paths, repo escapes, or extra JSON sidecars, so runtime
  evidence uploads cannot silently grow into raw logs or workspace snapshots.
  Every `actions/upload-artifact` step in a registered
  evidence workflow must bind one of that workflow's registered artifact
  filenames and upload tokens exactly through real `with:` map fields; a token
  that only appears inside a multiline `path: |` scalar is ignored. Extra upload steps outside the registry contract are
  rejected. Registry artifact tokens must be unique lowercase kebab-case names
  ending in `${{ github.run_id }}`, so uploaded evidence can be traced to one
  workflow run without mutable aliases.
  Registered evidence workflow PR and
  push path filters must be real children of the top-level `on:` event and
  cover the workflow file, `tools/wiii_self_harness/**`, the registered probe
  file, and all registered contract tests, so changes to proof code
  automatically run the corresponding evidence workflow. Copied `push.paths`
  or `pull_request.paths` blocks under unrelated YAML maps are ignored. Event
  filter keys that control paths, ignored paths, branches, or ignored branches
  must not be duplicated inside `push` or `pull_request`, so a later YAML key
  cannot override the path filters the validator inspected. `paths-ignore` and
  `branches-ignore` are rejected on those events, and explicit `branches`
  filters must include `main`, so a workflow cannot keep the required path list
  while silently skipping proof-code changes through a narrower event filter. Each
  registered contract test must also be executed from a workflow `run` step
  through `pytest` or `vitest`; a path filter, comment, or `echo` line no
  longer counts as proof that the test suite runs. The runner must start the
  shell command line directly, so text emitted by `echo` or another wrapper
  command cannot masquerade as a test run;
  registered workflow, probe, and contract-test paths must not contain
  symlinks, so registry validation cannot read proof code through a pointer to
  another local file.
  `.github/workflows/wiii-self-harness.yml` runs that validator alongside the
  scenario manifest. The scenario-manifest validator emits
  `wiii.self_harness_validation.v1`, manifest version, a manifest SHA-256
  fingerprint, and normalized `error_codes`, so CI handoff can classify
  missing evidence paths or tokens without parsing prose output. Its root,
  scenario, verification, and evidence objects are closed-schema allowlists,
  and string-list proof fields reject duplicate values, so typoed fields or
  repeated evidence tokens cannot inflate static contract coverage. Active
  scenarios must remain in `required_scenarios`, and required IDs must stay
  lowercase kebab-case, so live control-plane contracts cannot quietly become
  optional metadata. Required scenarios must also have `status: active`, so
  deferred or blocked contracts cannot stay mandatory without explicit
  reactivation. Active scenarios must include at least one `runtime` evidence
  file and one `test` evidence file, so required product contracts cannot be
  proven by docs or governance metadata alone. Duplicate `kind` plus
  normalized repo-relative `path` evidence entries are rejected within each
  scenario, so repeated file references or equivalent path spellings cannot
  inflate static evidence counts. The
  Self-Harness workflow validates self-harness, runtime registry, and coverage
  JSON/Markdown reports with per-report SHA-256 digests, a bundle SHA-256
  fingerprint, a self-validation JSON report, and an explicit sidecar
  validation result before CI handoff. It also writes standalone
  `artifacts/wiii-self-harness-validation.json` and
  `artifacts/wiii-runtime-evidence-registry-validation.json` sidecars, so the
  uploaded CI artifact carries the exact manifest and registry contracts
  validated outside the report-bundle directory. Those sidecars are emitted
  immediately after report-bundle validation and before completion-audit smoke
  begins, so later handoff failures still leave manifest/registry proof in the
  uploaded run artifact. The workflow then runs
  `tools/wiii_self_harness/validate_self_harness_sidecar_parity.py` and writes
  `artifacts/wiii-self-harness-sidecar-parity-validation.json`, proving the
  standalone sidecars match the corresponding reports inside the generated
  `artifacts/wiii-self-harness/` bundle. That parity artifact records one
  comparison row per report with bundle path, sidecar path, matched flag, and
  canonical JSON SHA-256 values for both payloads, so artifact review can prove
  exactly which standalone sidecars matched the bundle. The parity validator
  rejects `--out` targets inside that bundle or equal to any input
  report/sidecar, so the validation step cannot pollute or overwrite the
  evidence it is checking.
  After the validators, smoke, and wrapper
  unit-test gates run, the final `if: always()` upload archives
  `wiii-self-harness-reports-${{ github.run_id }}` so operators can inspect the
  machine-readable control-plane contract after success or failure without
  uploading before later gates have executed. Its push and pull-request path
  filters include the Python and MJS runtime-evidence output helpers and their
  helper tests, so evidence writer contract changes rerun the central manifest
  and registry gates.
  It also runs a completion-audit handoff smoke against the generated
  self-harness bundle and an empty runtime-evidence directory, expecting
  `completion_audit_ready: false` and `missing_artifact` errors, so the strict
  handoff path stays wired into CI without requiring live evidence artifacts on
  every self-harness run.
  The central workflow calls
  `tools/wiii_self_harness/generate_self_harness_report_bundle.py`, so
  self-harness, registry, coverage, and self-validation report generation plus
  final bundle validation stay inside Python instead of a multi-command shell
  script. The generator requires the output path to be a real directory when it
  already exists, requires that directory to be empty or absent before writing
  reports, and rejects symlink output directories or symlink output-directory
  parents before the first report write, so stale files, file-path overwrites,
  or unexpected resolved targets cannot be mixed into a new CI handoff bundle.
  The central `self-harness` CI job declares `timeout-minutes: 20`, and the
  harness unit tests assert that bounded timeout stays present, so the
  control-plane gate fails clearly instead of hanging indefinitely. The same
  tests require central workflow `uses:` steps to stay on the approved
  core-action allowlist and be pinned to 40-character commit SHAs. They also
  require top-level `permissions: contents: read`, no job-level permission
  overrides, and pull-request-scoped concurrency cancellation.
  `tools/wiii_self_harness/validate_self_harness_report_bundle.py` validates
  that downloaded report bundle for required files, schemas, fingerprints,
  per-report SHA-256 digests, a bundle SHA-256 fingerprint, error-code lists,
  typed `error_code_counts` on every child JSON report, Markdown coverage
  markers, child JSON report success (`ok: true` with empty `error_codes` and
  empty `error_code_counts`), empty child-report internal error lists such as
  `errors`, `validation_errors`, `coverage_errors`, `validation_error_codes`,
  and `coverage_error_codes`, unexpected files or directories, and the optional
  self-validation report without adding that self-report to the canonical bundle
  fingerprint. The bundle shape is intentionally flat: only the five report
  files named by the contract may appear in the uploaded directory.
  Unexpected entries are scanned before the optional self-validation report is
  validated, so a stale self-validation JSON cannot keep passing after a file or
  directory is added to the bundle.
  The self-harness validation report must match the current repository
  `wiii_self_harness_scenarios.json` manifest fingerprint, and the registry
  validation report must match the current `runtime_evidence_registry.json`
  fingerprint. This prevents a green bundle generated from an older
  control-plane contract or older runtime-evidence registry from being accepted
  by the current checkout.
  The coverage JSON must also match the registry-validation JSON in the same
  bundle for `registry_name`, `registry_path`, `registry_fingerprint_sha256`,
  `registry_version`, and `requirement_count`, so CI cannot upload a coverage
  report generated from a different runtime-evidence registry contract or
  carrying stale operator-facing registry identity/path metadata.
  The report-bundle validator also compares each coverage row back to the
  current `runtime_evidence_registry.json` for registry-derived identity,
  upload, diagnostic upload, freshness, external evidence mode,
  synthetic/credentialed external flags, raw-content absence counts,
  identifier-strategy counts/lists, forbidden token/regex counts, guard, and
  dispatch-gate fields,
  returning `report_registry_coverage_row_mismatch` if a valid-looking row
  drifts from the active registry contract.
  The coverage Markdown must also match the coverage JSON for operator-facing
  summary values, including registry identity, status, error-code counts,
  external-evidence counts, table row count, and each per-requirement coverage
  table row, so humans do not review a stale Markdown artifact while automation
  validates a different JSON payload.
  The three child JSON reports use closed top-level schemas in the bundle
  validator; unsupported fields fail validation instead of being archived as
  unchecked metadata. Known top-level values are also type/range validated, so
  allowed counts, labels, paths, layers, warnings, and error lists cannot carry
  raw objects or invalid summary values.
  The runtime evidence coverage report also uses an exact row schema and the
  row count must match `requirement_count`; row values must also keep expected
  string, string-list, boolean, and non-negative integer shapes, so nested
  coverage rows cannot carry unchecked payloads, invalid counts, or silently
  drop a registered evidence requirement. For rows with a numeric freshness
  target, `coverage_target_met` must equal
  `payload_checks >= freshness_hours`, so a hand-edited coverage JSON cannot
  claim a target status that contradicts the registered proof density. The
  top-level `layers` summary must equal the distinct layer values present in
  the coverage rows, so operator summaries cannot advertise a stale or invented
  product layer. Coverage rows now also expose `external_evidence_mode`,
  `synthetic_gap_flags`, and
  `credentialed_external_flags`, so LMS test-course, provider, and Composio
  lanes appear as `credentialed_external` while any future synthetic external
  gap remains machine-visible. The report also emits
  top-level `synthetic_external_gap_count`, `credentialed_external_count`, and
  `local_or_backend_count`, and bundle validation requires those counts to
  match the coverage rows.
  Completion and release audits can run the coverage report with
  `--require-no-synthetic-gaps`; while any row remains
  `synthetic_external_gap`, the report fails with stable error code
  `coverage_synthetic_external_gap_present`.
  The stricter `--require-credentialed-external-contracts` mode additionally
  fails credentialed external rows without credential flags, live env flags,
  live guard tokens, at least two dispatch/schedule gates, raw-content absence
  checks, and identifier-strategy checks, using
  `coverage_credentialed_external_contract_incomplete`.
  Downloaded report-bundle validation can require the same state with
  `--require-no-synthetic-gaps`, failing the bundled coverage JSON with
  `report_coverage_synthetic_external_gap_present`.
  It can also require complete credentialed external contracts with
  `--require-credentialed-external-contracts`, returning
  `report_coverage_credentialed_external_contract_incomplete`.
  The report-bundle generator accepts both strict flags and stops before
  writing self-validation when strict pre-validation fails, so handoff metadata
  cannot claim a successful completion-audit bundle while synthetic evidence or
  incomplete external evidence remains.
  Child JSON report `error_code_counts` keys must match `error_codes`,
  `error_codes` must not contain duplicates, and listed error-code counts must
  be positive, so handoff automation cannot receive contradictory failure
  summaries.
  The result exposes `fingerprinted_report_count` and
  `self_validation_report_present` so automation can distinguish canonical
  fingerprint scope from the optional self-validation file, emits bundle-level
  `error_code_counts` for CI triage, and keeps the self-validation JSON report
  outside the bundle until it has been generated through `--out`. The final validation
  uses `--require-self-validation`, so the uploaded handoff artifact cannot pass
  without `self-harness-report-bundle-validation.json`. That self-validation
  payload must describe the pre-self canonical bundle with `report_count=4`,
  `fingerprinted_report_count=4`, `self_validation_report_present=false`, and
  `rows` matching the four canonical report names in canonical order plus
  their statuses, schema versions, SHA-256 digests, and error lists/codes.
  Top-level pass/fail/unexpected and error-code-count fields must also match
  those canonical rows. Row entries may contain only those canonical fields,
  and the top-level payload must match the self-validation report schema
  exactly, so the self-validation report cannot hide raw payloads in extra
  properties.
  The report-bundle CLI rejects `--out` locations inside the bundle root,
  including resolved symlink targets, and rejects direct/parent symlink or
  directory paths as report outputs, so validation cannot create unregistered
  files in the report directory it is checking or crash on a non-file output target.
  The registry-validator report is self-described with
  `wiii.runtime_evidence_registry_validation.v1`, so CI handoff can pin the
  registry-validation output contract separately from evidence payload and
  bundle report contracts. It also reports the registry integer version and a
  registry contract SHA-256 fingerprint over the registry name, version, and
  requirements, so operators can compare the exact contract validated by CI.
  Registry validation JSON and failure summaries also expose normalized
  `error_codes` for registry-shape, workflow, upload, permissions,
  path-filter, artifact-name, payload-check, and freshness failures, so
  automation does not need to scrape raw validation text.
  `tools/wiii_self_harness/validate_runtime_evidence_artifact.py` is now the
  shared payload validator used by the evidence workflows, so schema, privacy,
  forbidden-token, freshness, and minimum-success checks live in the registry
  instead of being duplicated as inline workflow Python. The artifact validator
  CLI revalidates the registry contract before reading artifact payloads, so
  direct workflow or operator use cannot silently trust a malformed registry
  file. Forbidden-token checks
  are case-insensitive, so `Authorization`-style capitalization changes do not
  bypass artifact privacy validation, and registry validation rejects
  case-insensitive duplicate forbidden-token entries before CI evidence runs.
  Per-artifact validation rejects symlink artifact paths before reading JSON, so
  the workflow gate cannot validate a pointer to local state instead of the
  produced evidence file.
  Artifact JSON parsing rejects non-finite constants such as `NaN` or
  `Infinity`, and numeric `min` checks treat booleans and numeric-looking
  strings as non-numeric, so runtime evidence cannot satisfy duration/count
  thresholds with JSON-adjacent values that are not strict finite numbers.
  `sorted_equals`
  checks compare JSON-canonical multiset values instead of Python's native
  mixed-type ordering, so malformed mixed-type lists fail as payload mismatches
  rather than crashing the validator.
  Manifest, registry, report, and freshness version/count fields also reject
  boolean-as-integer values, so `true` cannot stand in for `1` in control-plane
  contracts.
  The same strict JSON stance applies to manifest, registry, report-bundle, and
  bundle freshness reads: non-finite JSON constants are treated as parse
  failures before report contracts or evidence freshness can be trusted, and
  duplicate object keys are rejected before a later key can silently override
  an earlier contract value. That parser policy is centralized in
  `tools/wiii_self_harness/strict_json.py` so new control-plane readers inherit
  the same behavior instead of copying local parser hooks. The strict JSON
  tests also guard the runtime reader modules against direct `json.load` or
  `json.loads` use, so future readers cannot bypass the shared policy silently.
  Self-harness, registry, coverage, runtime-evidence bundle, and report-bundle
  CLIs also reject direct/parent symlink and directory paths as `--out` report targets, so CI
  handoff failures stay typed JSON errors instead of filesystem redirects or
  crashes.
  Every registered runtime evidence
  requirement must also include payload checks that prove raw content is absent
  through a `raw_content_included == false` field and that identifiers use an
  approved `identifier_strategy`, keeping OpenHuman-style provenance explicit
  rather than relying only on forbidden-token scans. Payload checks must also
  be unique by path, operation, and condition, so evidence requirements cannot
  carry duplicate or contradictory proof obligations for the same payload field.
  Artifact upload tokens must include either the requirement ID or the artifact
  stem, so valid-looking upload names remain traceable to the registered proof
  instead of becoming opaque evidence handles.
  The validator report itself now has
  `wiii.runtime_evidence_artifact_validation.v1`, separate from the produced
  artifact payload `schema_version`, so downstream gates can version the
  validation-result contract independently from runtime evidence payloads. Its
  JSON output and failure summary also expose normalized `error_codes` and
  `error_code_counts`, so automation can classify and count schema, privacy,
  freshness, and payload-check failures without scraping raw error text. Bundle
  validation reuses the same artifact error-code taxonomy for payload
  validation failures, preventing drift between per-artifact workflow gates and
  downloaded-bundle handoff reports. Even when a caller passes `--requirement-id`, artifact validation
  rejects files whose filename does not match the registered artifact name, so
  a valid payload cannot be silently substituted under the wrong evidence
  handle.
  `tools/wiii_self_harness/report_runtime_evidence_coverage.py` renders the
  same registry as a review/operations table so the active runtime evidence
  surface can be inspected without reading each workflow by hand, including
  artifact upload tokens, diagnostic upload counts/artifacts, raw-content
  absence counts, and identifier-strategy coverage per requirement.
  The report now fails closed when any registered artifact falls below
  `payload_checks >= freshness_hours`, turning the OpenHuman-style evidence
  density target into a CI-enforced runtime contract instead of a dashboard
  convention. Its JSON/Markdown output uses
  `wiii.runtime_evidence_coverage_report.v1` as the report-level schema,
  separate from each evidence row's payload `schema_version`, and carries the
  registry name, integer version, and contract SHA-256 fingerprint used to
  build the coverage table. Registry validation failures and coverage-density
  gate failures are exposed as `validation_error_codes` and
  `coverage_error_codes`, plus a top-level `error_codes` union and
  `error_code_counts`, so handoff automation can route and count failures
  without scraping Markdown text. Coverage Markdown table cells collapse line
  breaks and tabs before rendering, so malformed registry text cannot reshape
  the operator handoff table. When invoked with `--out`, the coverage report
  refuses to write over the runtime evidence registry contract file or to a
  direct/parent symlink or directory output target.
  The stricter `--require-no-synthetic-gaps` mode converts remaining synthetic
  external evidence into `coverage_synthetic_external_gap_present`, preserving
  a machine-readable fail condition if any lane regresses to synthetic evidence.
  `--require-credentialed-external-contracts` then checks that credentialed
  external lanes still expose env flags, guard tokens, dispatch/schedule gates,
  raw-content absence checks, and identifier-strategy checks.
  The report-bundle validator exposes the same flag for downloaded handoff
  artifacts and emits `report_coverage_synthetic_external_gap_present` when the
  uploaded coverage JSON still contains synthetic external gaps.
  It also exposes `--require-credentialed-external-contracts` and emits
  `report_coverage_credentialed_external_contract_incomplete` for incomplete
  credentialed external rows. The generator uses the same strict pre-validation
  path before writing self-validation, preventing stale successful bundle
  metadata during the OpenHuman-style completion audit.
  The central workflow also runs `validate_self_harness_report_bundle.py` as an
  explicit strict CLI step and uploads
  `artifacts/wiii-self-harness-report-bundle-validation.json`, so operator
  handoff has an independent sidecar validation result outside the recursive
  in-bundle self-validation file.
  It also renders runtime evidence coverage Markdown with
  `--require-no-synthetic-gaps` and
  `--require-credentialed-external-contracts`, so the operator-facing coverage
  table cannot pass under looser evidence rules than the strict bundle gates.
  `tools/wiii_self_harness/validate_runtime_evidence_bundle.py` validates a
  downloaded artifact directory against all registered evidence contracts,
  emits JSON/Markdown report schema
  `wiii.runtime_evidence_bundle_report.v1`, reports the validated registry name
  and integer registry version, returns the same schema with `ok: false`,
  structured `errors`, normalized `error_codes`, and `error_code_counts` for
  early `--format json` CLI failures, revalidates the full runtime evidence registry contract before
  reading artifacts, and can take `--self-harness-report-bundle` to first
  validate the downloaded self-harness report bundle with required
  self-validation, no-synthetic-gap enforcement, and
  credentialed-external-contract enforcement, then require its coverage JSON's
  registry fingerprint, registry version, and `requirement_count` to match the
  artifact-validation registry. When that link is present, the runtime evidence
  bundle report records the self-harness report-bundle root, bundle fingerprint
  SHA-256, and validation schema, plus a
  `completion_audit_fingerprint_sha256` over the runtime evidence bundle
  fingerprint and linked report-bundle fingerprint/schema. Standalone artifact
  validation can still report `ok: true`; completion handoff should run with
  `--require-completion-audit-link` and require `completion_audit_ready: true`
  so an artifact-only pass is not mistaken for a full OpenHuman-style audit.
  `generate_completion_audit_handoff.py` packages that strict validation path
  into one handoff command, writes top-level `completion-audit-handoff.json`
  and `completion-audit-handoff.md` files plus JSON and Markdown runtime
  evidence bundle reports, repeats the completion-audit, runtime-bundle, and
  self-harness-bundle fingerprints at the top level, and rejects output
  directories inside either evidence input bundle, existing non-empty output
  directories, file targets, direct symlinks, and symlink parents. It then runs
  the handoff validator against the generated directory before returning
  success, so generator bugs cannot produce an unvalidated operator bundle.
  `validate_completion_audit_handoff.py` validates downloaded handoff bundles by
  requiring the exact four reports, strict JSON parsing, top-level fingerprint
  parity with the nested runtime report, runtime JSON parity with the nested
  report object, exact JSON-derived Markdown documents and runtime artifact
  table row parity, row `error_codes` provenance from normalized row `errors`, and no
  freshness timestamp contradictions, status/proof contradictions, row path
  provenance contradictions, duplicate or empty registered runtime row
  identities, or unexpected files. The
  central smoke step runs that validator against its generated smoke handoff
  bundle before reporting success, then runs the validator CLI as a separate
  step that writes `artifacts/wiii-completion-audit-smoke-validation.json` for
  upload.
  The smoke JSON includes `release_gate_validation`, proving the empty-evidence
  handoff is structurally valid but rejected by the completion readiness gate
  with `handoff_completion_audit_not_ready`. The smoke assertion also requires
  the structural and release-gate validation payloads to expose opposite
  `require_completion_audit_ready` values and distinct validation fingerprints.
  The same strict gate result is also uploaded as
  `artifacts/wiii-completion-audit-smoke-release-gate-validation.json`, giving
  operator handoff a standalone machine-readable negative release-gate artifact.
  `validate_completion_audit_smoke.py` then validates the smoke summary,
  strict release-gate sidecar, and structural validation sidecar together,
  rejecting embedded/sidecar mismatches, wrong policy modes, non-distinct
  policy fingerprints, or drift from the expected empty-evidence not-ready
  report.
  `report_completion_audit_readiness.py` also renders
  `artifacts/wiii-completion-audit-readiness-non-lms.json` with
  `--exclude-requirement-id lms-test-course-replay`, exposing full and scoped
  readiness, missing/failed requirement IDs, blocker lists, and the linked
  self-harness bundle fingerprint/schema while preserving the full
  completion-audit release gate. The same report includes `scoped_next_actions`
  with the registry workflow, probe, dispatch/schedule gate, live guard,
  expected artifact token, and current error-code evidence for each included
  missing/failed requirement. It also exposes `scoped_next_action_count` and
  `scoped_next_actions_fingerprint_sha256`, a canonical SHA-256 digest of the
  readiness report schema plus action list.
  `validate_completion_audit_readiness.py` gates that report for
  schema, count/list, scope, blocker, next-action count/fingerprint, error-code,
  and link-field consistency.
  `generate_completion_audit_run_plan.py` now turns the validated non-LMS
  readiness report into a closed-schema operator run plan for the scoped
  blockers. It carries workflow-dispatch inputs, schedule env flags, live probe
  env flags, live guard tokens, artifact tokens, preflight source SHA-256,
  source-validation state, and translated `required_next` setup categories such
  as approved recipient, backend URL, or credential configuration, while
  keeping secret values and raw identifiers out of the artifact.
  `validate_completion_audit_run_plan.py` recomputes the run-item fingerprint
  from the run-plan schema, readiness schema, `scoped_next_actions`
  fingerprint, and run-item payload. The setup, acceptance, and structured
  verification-spec fingerprints are also schema-bound, and source validation
  can bind the plan back to the readiness report SHA-256, so the operator
  handoff remains auditable and cannot be used as a live-evidence substitute.
  `generate_completion_audit_launch_pack.py` converts that run plan into a
  privacy-safe execution pack for supported blockers, including `gh workflow
  run` command templates, local preflight/live probe templates,
  preflight/artifact validator commands, artifact download commands, and the
  required GitHub input, variable, secret, and environment names. For the
  current non-LMS blocker set it supports `autonomy-proactive-channel` and
  `wiii-connect-composio-acceptance`. `validate_completion_audit_launch_pack.py`
  verifies the closed schema, command coverage, privacy flags, launch-item,
  setup, acceptance, command-spec, and post-launch verification-spec
  fingerprints, optional run-plan SHA-256 parity, and with `--repo-root` the
  referenced workflow/probe files plus workflow input/variable/secret/artifact
  tokens. Those launch fingerprints are schema-bound and source-bound to the
  matching run-plan fingerprints, keeping execution handoff bound to audited
  evidence rather than prompt instructions.
  The smoke sidecar outputs are rejected if they would be written inside the
  generated handoff bundle, the runtime-evidence input bundle, or the
  self-harness report input bundle, including resolved symlink targets, and
  duplicate sidecar paths are rejected before generation, so smoke reporting
  cannot mutate the evidence set after structural validation has already read
  it.
  The validator's default mode accepts structurally valid not-ready smoke
  bundles; release gates should add `--require-completion-audit-ready`, which
  fails with `handoff_completion_audit_not_ready` unless the handoff proves
  `completion_audit_ready: true`; that policy mode is included in the
  validation bundle fingerprint, keeping structural validation fingerprints
  distinct from release-gate fingerprints even when both modes pass.
  The same validation bundle fingerprint binds the validation schema version,
  each validation row's status, raw error text, normalized error codes, report
  name, and report SHA-256 so operator triage details cannot be rewritten while
  preserving the machine fingerprint.
  Unexpected completion-handoff sidecars are normalized by kind: regular files
  produce `unexpected_handoff_report_file` and are fingerprinted, directories
  produce `unexpected_handoff_report_directory`, and symlinks produce
  `unexpected_handoff_report_symlink` without hashing the target.
  The nested runtime bundle JSON report is also closed-schema; top-level extras
  fail as `runtime_bundle_json_unsupported_fields`, `row_count` must match
  `rows`, and `error_code_counts` must use positive counts with keys matching
  the unique `error_codes` list. It also requires the complete canonical
  runtime bundle schema, including registry name/version, normalized UTC
  `validated_at`, bundle roots, self-harness validation schema, and required
  SHA-256 fingerprints. Handoff validation also requires canonical runtime row
  fields, recomputes `bundle_fingerprint_sha256` from the row manifest,
  recomputes `completion_audit_fingerprint_sha256` from the runtime bundle and
  self-harness report bundle manifest, requires handoff roots to match runtime
  report roots, requires `ok` and `completion_audit_ready` to match row status
  plus self-harness link readiness, and recomputes `passed_count`,
  `missing_count`, `failed_count`, `unexpected_count`, and `error_code_counts`
  from row status/error-code data. The row manifest fingerprint includes
  runtime report `schema_version`, `validated_at`, each row's reported
  `age_hours`, each row's `errors`, and normalized `error_codes`, so a forged
  summary cannot pass by only editing the schema contract, freshness decision
  point, rendered freshness age, operator-facing failure details, top-level
  counters, copied fingerprints, or readiness booleans.
  It reports
  each artifact's SHA-256 digest, emits a registry contract SHA-256 fingerprint
  plus bundle-level
  SHA-256 fingerprint over the canonical artifact manifest, including relative
  artifact paths and normalized error codes, records the normalized UTC
  `validated_at` timestamp used for freshness decisions, exposes the same
  normalized error codes plus bundle-level `error_codes` and
  `error_code_counts` in JSON/Markdown
  reports for operator triage, and
  makes release or incident handoff fail on missing, duplicated,
  schema-invalid, stale, privacy-leaking, symlinked, or bundle-escaping runtime
  evidence. Symlinked bundle roots are rejected before artifact lookup. The
  bundle validator also applies the same safe artifact-name rule before
  filesystem matching, so custom registry input cannot widen evidence lookup
  with glob-pattern metacharacters or validate the same evidence twice through
  duplicate requirement IDs or artifact names.
  Non-object registry requirement entries become failed bundle rows rather than
  being skipped, and unregistered non-directory bundle entries, including
  non-JSON raw-log sidecars, become failed rows. The bundle report exposes
  `unexpected_count` for quick handoff triage,
  keeps `requirement_count` tied to registry requirements, and uses `row_count`
  for the full handoff table including extra failed rows. Valid local
  unexpected files also receive SHA-256 digests and participate in the bundle
  fingerprint, while symlinked or escaping unexpected entries report path
  errors instead of being hashed. Duplicate artifact matches receive a manifest
  digest over relative duplicate paths, valid per-file hashes, and path errors,
  so duplicate evidence also affects the bundle fingerprint without following
  unsafe links. Markdown bundle output collapses table-cell line breaks and tab
  spacing so operator handoff tables stay readable. CLI `--registry` and
  `--out` sidecar
  paths, including direct symlink locations, symlink parents, and resolved targets, must stay outside
  the bundle root so registry input and report generation cannot pollute the
  evidence directory with unregistered files; `--out` also rejects
  direct/parent symlink and directory targets so JSON failure reporting does
  not collapse into filesystem redirects or errors.
  Live Python evidence probes share `scripts/runtime_evidence_output.py` for
  UTF-8 JSON artifact writes, and that helper rejects direct symlink, parent
  symlink, and directory output targets before writing through a same-directory
  temp file, flush/fsync, and atomic replace. Registry validation also reads
  the helper next to registered Python probes and fails if the atomic
  temp-file primitives are removed; it also requires the workflow contract job
  and path filters to include the Python runtime evidence output helper test. Registry
  validation requires registered Python probes to define `--out` as an actual
  `argparse.add_argument(...)` CLI flag and to import `emit_json_payload` from
  that helper, so a local function with the same name cannot bypass the shared
  output guard. It also requires an `emit_json_payload(..., out_path)` call, so
  a probe cannot merely mention `--out` while silently writing evidence through
  a side channel. Registered Python probes are also forbidden from direct
  evidence file writes such as `write_text`, write-mode `open`, aliased
  `io.open`/`codecs.open`/`builtins.open`, aliased `json.dump`, imported
  `dump`, and low-level `os.open`/`os.write`, with literal or constant write
  modes both rejected, keeping evidence emission behind the shared guard.
  Registry validation also requires registered MJS evidence wrappers to parse
  `--out` from `process.argv`, assign the same returned output property from
  both `--out <path>` and `--out=<path>` branches, and forward that parsed path
  into `WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON`; their workflow command
  must pass the exact registered artifact path on the `node ...probe...`
  invocation, and the parsed summary env binding must live inside the
  `spawnSync(process.execPath, [runner, ...forwarded], ...)` runner options
  before the wrapper reaches
  `wiii-desktop/scripts/runtime-evidence-output.mjs` for the same direct
  symlink, parent symlink, and directory output-target rejection before
  same-directory temp-file write, fsync, and atomic rename. Registry validation
  reads the sibling `runtime-evidence-output.mjs` helper and fails if its
  atomic temp-file primitives are removed; it also requires the workflow
  contract job and path filters to include `test-runtime-evidence-output.mjs`.
  Registered MJS probes are also forbidden from raw `node:fs`
  and `node:fs/promises` evidence writes such as `writeFileSync`,
  `fs.writeFileSync`, `fs.promises.writeFile`, or aliased `writeFile` imports
  from `node:fs/promises`, including destructured dynamic-import aliases from
  `await import("node:fs")` or `await import("node:fs/promises")`, plus
  destructured `require("node:fs")` or `require("node:fs/promises")` aliases,
  and default-export aliases such as `fs.default[writer](...)` or
  `fsDefault[writer](...)`. Destructured aliases with default initializers such
  as `writeFileSync: writer = null` are rejected the same way. Destructured
  `promises` namespaces from `node:fs`, such as
  `const { promises: fsPromises } = require("node:fs")`, are also rejected when
  they call `writeFile`/`appendFile` directly or through a computed writer.
  Inline module expressions such as `require("node:fs")[writer](...)` or
  `(await import("node:fs/promises"))[writer](...)` are rejected as well.
  Dot, bracket, and optional-chain property calls such as `fs.writeFileSync(...)`,
  `fs["writeFileSync"](...)`, `fs[writer](...)`, and
  `fs[promisesBucket][writer](...)`, including `fs?.[writer](...)` and
  `fs?.[promisesBucket]?.[writer](...)`, are rejected when the computed
  property is a literal string or string constant. Dynamic `import(...)` and
  `require(...)` module specifiers are also rejected when `node:fs` or
  `node:fs/promises` is hidden behind a string constant, including simple
  concatenated constants such as `"node:" + "fs"` or
  `"write" + "FileSync"`, so browser replay JSON cannot bypass the shared
  output guard through a JavaScript side channel.
- The runtime acceptance harness now includes visual and Code Studio stream
  replay contracts. `visual_inline_figure_stream_replay` requires
  `tool_generate_visual`, observed `visual_runtime`, and terminal ledger event
  counts for `visual_open` and `visual_commit`. `code_studio_app_stream_replay`
  requires `tool_create_visual_code`, observed `code_studio`, and terminal
  ledger event counts for `code_open` and `code_complete`.
- The casual chat replay now proves no-action suppression by forbidding
  `host_action`, `host_action_result`, `pointy_action`, `visual_open`,
  `visual_commit`, `code_open`, and `code_complete` event counts in addition to
  requiring suppressed host, Pointy, visual, and Code Studio surfaces.
- `wiii-desktop/src/lib/runtime-flow-trace.ts` and
  `wiii-desktop/src/components/connect/WiiiConnectPage.tsx` now expose a
  host-facing `runtime_flow_ledger` panel beside the trace panel. The view model
  prefers pending stream metadata, redacts sensitive text, renders a compact
  `Route decision` row with selected path reason, bind/force-tool state, and
  final agent, exposes provider/model authority plus tool-loop call/result/
  denial counts, warns when visual or Code Studio lifecycle events are
  incomplete, and flags Pointy/host/visual/code event leakage on no-action chat
  turns.
- `wiii-desktop/src/__tests__/runtime-flow-trace.test.ts` and
  `wiii-desktop/src/__tests__/wiii-connect-page.test.tsx` prove the desktop
  Runtime tab receives sanitized ledger facts and renders them without leaking
  token-like values.
- `maritime-ai-service/app/engine/wiii_connect/snapshot.py` now emits a
  privacy-safe `capability_summary` that consolidates connected provider slugs,
  granted scope names, per-path ready/guarded/blocked status, and suppressed
  tool groups into the Wiii Connect snapshot. The desktop Path policy tab reads
  the same summary instead of relying only on scattered capability UI state.
- `wiii-desktop/playwright/runtime-ledger-panel.spec.ts` and
  `wiii-desktop/playwright.runtime-ledger.config.ts` add a repeatable browser
  acceptance lane for the same host-facing contract. The spec seeds a
  disposable authenticated desktop session, opens Wiii Connect Runtime,
  verifies `runtime_flow_ledger` and `runtime_flow_trace` facts, asserts a
  token-like host capability is displayed as `[redacted]`, verifies route
  decision reason visibility, sends a mocked chat stream with visual and Code
  Studio lifecycle events, proves terminal
  `done.runtime_flow_ledger` payloads reach persisted assistant metadata,
  seeds a conversation from the backend `browser_replay` evidence shape and
  proves the Runtime tab can consume that terminal ledger/trace metadata
  without raw prompt/answer leakage, sends a source-backed memory-context stream, proves
  `context.context_provenance` source kinds, memory types, prior-session
  episodic recall counts/event types/score range/scope flags, warning codes,
  and `hash_or_count_only` privacy metadata reach the Runtime tab, opens the
  embed entry with JWT-style auth, posts LMS host capabilities/context, uploads
  markdown course content through the paperclip flow, verifies the outbound chat
  request carries host/document context, proves terminal
  `done.runtime_flow_ledger` records `lms_document_preview` with hash/count-only
  document provenance plus preview-required, approval-evidence-present, and
  no-apply-attempted host-action flags, then runs the embed app inside a parent
  iframe host harness to click the preview apply CTA, verify the
  `wiii:action-request`/`wiii:action-response` bridge, and prove the Wiii audit
  request excludes the raw approval token. The browser lane captures
  screenshots for frontend-visible evidence.
- `wiii-desktop/scripts/run-runtime-ledger-browser-replay.mjs` turns that
  browser replay into an exact-file staging loop: it runs
  `wiii_runtime_flow_acceptance.py --evidence-json`, stores the sanitized
  artifact through the shared `emit_json_payload` helper under ignored
  `test-results/` by default, then runs the focused Playwright Runtime-tab browser replay with
  `WIII_RUNTIME_FLOW_BROWSER_REPLAY_JSON` pointing at the generated backend
  file. The shared backend export path writes UTF-8 JSON and rejects direct
  symlink, parent symlink, and directory output targets before the browser lane
  can consume redirected evidence. The Playwright loader validates the replay schema and rejects raw
  prompt, raw answer, raw SSE event payload, provider payload, params, and
  token-like values before seeding the desktop conversation. The runner calls
  Playwright through the local `@playwright/test` CLI without shell
  concatenation so the focused `--grep` remains exact on Windows as well as
  Unix-like shells. When the replay passes, it writes
  `wiii.runtime_flow_browser_replay_summary.v1`, a hash/count-only summary with
  exact evidence-file replay proof, evidence SHA-256, case counts, doctor
  counts, safe sync-parity pass counts, backend route-path counts, per-case
  case/event hashes, route-reason hash presence, raw prompt/answer/SSE/
  assistant-content absence flags, visual/Code Studio lifecycle case counts,
  finalization saved/error counts, every browser-validated, backend-finalized,
  and post-turn lifecycle case hash, plus terminal post-turn lifecycle
  schema/privacy evidence that can be archived without raw prompt, answer,
  route reason, SSE payload, or provider payload content. The default
  browser-replay evidence run
  now exports the source-backed LMS preview route, Wiii Connect status and
  blocked-action routes, a missing-provider blocked-action route, plus visual
  and Code Studio stream routes before browser replay. It passes
  `--sync-parity` by default for the non-stream-artifact safe cases, so the
  artifact proves `/chat` and `/chat/stream/v3` parity plus route and
  frontend-surface diversity from backend evidence rather than only mocked
  browser ledgers. Visual fast-path turns now attach terminal
  `runtime_flow_trace`, and Code Studio app/simulation turns are kept out of
  providerless Wiii Connect and domain-search false positives before browser
  replay validates their lifecycle evidence. The same acceptance run now fetches
  `/api/v1/wiii-connect/snapshot`, validates the privacy-safe capability
  contract, and carries `wiii_connect_capability` into the summary as
  hash/count evidence for connection counts, connected-provider/scope hashes,
  per-path readiness, suppressed-tool groups, and path-reason hashes without
  raw connection refs or account labels. It also writes retained timestamped
  summary copies and a
  `wiii.runtime_flow_browser_replay_summary_archive.v1` index under the archive
  directory. The summary now carries the archive index contract and path-count
  consistency evidence for Wiii Connect capability snapshots, with
  `WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_ARCHIVE_LIMIT` defaulting to 25 and
  `0` disabling archival when an environment wants only the latest summary.
- `.github/workflows/runtime-ledger-browser-replay-evidence.yml` wraps the
  exact-file replay with
  `WIII_RUNTIME_LEDGER_BROWSER_REPLAY_EVIDENCE=1 --allow-run`, validates the
  resulting `runtime-flow-browser-replay-summary.json` through the Runtime
  Evidence Registry, and can upload the summary through explicit
  `workflow_dispatch run_browser_replay=true` or scheduled runs gated by
  `WIII_RUNTIME_LEDGER_BROWSER_REPLAY_EVIDENCE_ENABLED=1`. The registry checks
  `browser_replay.cases.*` list-wide, so a later replay case cannot bypass the
  summary contract just because the first case is valid, and
  `length_equals_path` proves the declared case count matches the actual replay
  case array length. The same contract requires every replay case to report
  saved backend finalization, zero finalization errors, and
  `len(browser_replay.finalized_case_id_hashes) == evidence.case_count`, so a
  replay cannot pass by rendering an unsaved or failed turn. It now also
  requires every saved-finalization replay case to expose
  `wiii.post_turn_lifecycle.v1` status-only evidence with no raw turn-scope
  keys, privacy `raw_content_included=false`,
  `identifier_strategy=status_only`, a boolean background scheduling flag, and
  a post-turn lifecycle case-hash list whose length equals
  `evidence.case_count`, so browser replay cannot pass on a turn whose
  terminal ledger lost post-response lifecycle proof. The summary
  contract requires passing acceptance checks,
  at least three safe sync-parity passes, Playwright validation for every replay
  case, at least one doctor-ready path, prompt-hash evidence, valid ledger/trace
  schemas, exact evidence-file replay proof, per-case route-reason and event
  hash evidence, per-case raw-payload absence flags, aggregate counts for
  `lms_document_preview`,
  `external_connection_status`, `external_app_action`, and `visual_generation`,
  at least one source/document/preview case, at least one complete visual
  lifecycle case, at least one complete Code Studio lifecycle case, and no apply
  attempt. It also requires a valid `wiii_connect_snapshot.v0` capability
  summary with five path-readiness entries, ready-path evidence, per-path
  reason hashes, and raw-content exclusion. It permits aggregate doctor status
  such as `degraded` when optional integrations are absent in local or staging
  environments.
- `wiii-desktop/scripts/run-runtime-ledger-browser-replay-local.mjs` wraps the
  exact-file replay for local acceptance: it reuses an already-healthy backend
  or starts a disposable dev backend, waits for `/health`, runs the evidence
  export plus browser replay, writes backend logs under ignored `test-results/`,
  and terminates only the backend process tree it started.
- `wiii-desktop/src/lib/runtime-flow-trace.ts` now turns
  `runtime_flow_ledger.context.context_provenance` into readable
  operator-facing rows. It surfaces source-ref kinds, semantic memory/fact/
  insight categories, episodic recall status/count/event/score/scope metadata,
  context-budget utilization and dropped-message counts, preview/apply approval
  evidence, warning codes, and privacy strategy without showing raw document,
  memory, approval tokens, or prior-session snippet text.
- `wiii-desktop/src/api/sse.ts` now passes parsed `done` event payloads to
  `useSSEStream`, and `wiii-desktop/src/hooks/useSSEStream.ts` merges terminal
  `done` metadata over earlier stream metadata before `finalizeStream`. This
  prevents the desktop host from losing the final runtime ledger when the
  backend emits the complete ledger only at stream termination.
- `maritime-ai-service/tests/unit/test_living_continuity.py` proves Living
  episode writes fail closed without org context and emit hash/count-only write
  audits without raw user or response text.
- `maritime-ai-service/tests/unit/test_runtime_flow_doctor.py` proves aggregate
  diagnostics do not include raw prompt, document, memory, request, or session
  text.
- `maritime-ai-service/tests/unit/test_admin_runtime_flow_doctor.py` proves the
  admin diagnostic response stays aggregate-only, including semantic-memory
  write history.
- Direct tool result ledgers now use `sanitize_tool_result_for_event` before
  storing results in `tool_call_events`, so Wiii Connect/provider outputs,
  Code Studio tool results, forced search shortcut results, and document
  host-action shortcut results keep internal raw messages for synthesis,
  visual emission, and artifact delivery while public event ledgers redact
  `connection_ref`, connected-account IDs, Page IDs, raw media/provider payloads,
  raw code/HTML payload keys, approval/token/secret fields, and bearer-style
  substrings.
- `tools/wiii_self_harness/wiii_self_harness_scenarios.json` adds the
  `memory-context-provenance-ledger` and
  `wiii-connect-public-tool-event-boundary` scenarios.

This slice is intentionally narrow. It changes memory maintenance timing,
worker handoff, tenant enforcement, Living episode write safety, episodic
recall observability/org scoping, and backend replay acceptance for
source-backed LMS document preview turns and semantic memory-turn retrieval
ledgers, visual/Code Studio stream replay contracts, plus public tool-result
event sanitization, host-facing runtime ledger display, and a repeatable
browser acceptance check for that display, terminal `done` ledger propagation,
iframe host-bridge preview/apply, and host-facing context provenance rows
including episodic recall summaries, but does not change semantic memory
retrieval ranking, semantic memory content selection, document parsing, LMS
mutation behavior, visual generation algorithms, Code Studio generation
quality, or provider routing. Rollback is
limited to disabling
`enable_background_tasks`, reverting
the task/broker handoff so maintenance falls back to the in-process background
path, removing the acceptance replay scenario if a target environment cannot
yet host LMS preview tools, stable semantic memory retrieval, or stable
visual/Code Studio stream events, hiding the desktop Runtime ledger panel while
leaving backend metadata intact, removing the `test:e2e:runtime-ledger`
browser lane while keeping the unit-level Runtime tab tests, reverting
terminal `done` metadata propagation in the desktop SSE parser if an older
backend sends malformed done payloads, hiding the host-facing context
provenance rows while keeping backend ledger metadata, disabling
`enable_living_continuity`
while investigating Living episode persistence,
disabling `enable_cross_platform_memory`
while investigating cross-platform memory merge/read scoping, or reverting the
tool-result event sanitizer call sites while keeping internal tool messages
unchanged.

## Follow-Up Issues

Open separate issues before changing these larger surfaces:

1. Expand source-backed, memory-turn, visual, Code Studio, and the guarded LMS
   evidence workflow from backend/browser ledger acceptance to a credentialed
   external LMS test-course preview/apply run.
2. Finish auditing remaining specialized memory stores and tenant filters
   outside the semantic, episodic, Living, visual, cross-platform, and
   temporal-graph/user-graph/Neo4j document-graph paths.
3. Decide whether Wiii needs a user-visible memory vault after provenance data
   is stable.
