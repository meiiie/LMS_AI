# Wiii System Control Plane

Status: Active

Owner: Project leadership

Last updated: 2026-06-01

Related issue: #638

## Purpose

This document is Wiii's operating map for understanding the whole system before
debugging or changing it. It exists because patch-by-patch repair is too costly
for a product with chat, RAG, LMS host actions, visuals, Code Studio, memory,
auth, and deployment in the same active path.

The control plane answers four questions:

1. Which Wiii layer owns this behavior?
2. Which runtime flow is the request on?
3. Which signal proves that flow is healthy?
4. Where should debugging start when the signal is missing?

It complements:

- `docs/WIII_PROJECT_MENTAL_MODEL.md` for the five-layer product model.
- `docs/architecture/WIII_CODEBASE_MAP.md` for source navigation.
- `docs/architecture/wiii-connect/README.md` for the emerging connection and
  capability boundary.
- `docs/operations/WIII_REFERENCE_SYSTEMS_AUDIT_2026-05-25.md` for external
  systems Wiii should compare against before deeper runtime changes.
- `docs/operations/WIII_OPENHUMAN_REFERENCE_AUDIT_2026-05-26.md` for the
  OpenHuman-derived memory/context provenance and context-ledger requirements.
- `docs/operations/WIII_OPENCLAW_REFERENCE_AUDIT_2026-05-25.md` for the
  OpenClaw-derived control-plane, runtime ledger, and chat-baseline
  requirements.
- `docs/operations/WIII_UNDERSTAND_ANYTHING_REFERENCE_AUDIT_2026-05-25.md` for
  the system-comprehension harness, deterministic source inventory, import-map
  hotspot, and scan guardrail decision.
- `docs/operations/WIII_SELF_HARNESS.md` for static contract harnessing.
- `docs/operations/WIII_LOCAL_E2E_HARNESS.md` for local browser entry.
- `docs/operations/WIII_PRODUCT_RELEASE_RUNBOOK.md` for pinned production
  deploy and smoke.

## Current Operating Snapshot

As of 2026-05-25:

- Last accepted production deploy SHA:
  `3cc3f829eb2dcf674d11f97a3e4335334fddee3d`.
- Last production deploy workflow:
  `https://github.com/meiiie/wiii/actions/runs/26373158277`.
- Last external production smoke result: `19 passed, 0 failed`, including
  structured visual SSE `visual_open` and `visual_commit`.
- The Wiii GCP VM `wiii-production` in project `the-wiii-lab`,
  zone `asia-southeast1-c`, was intentionally stopped on 2026-05-25 to reduce
  cost. Public health checks may fail while the VM is stopped. Treat that as an
  operating state, not a code regression, until the VM is started again.
- `tools/wiii_self_harness/run_wiii_self_harness.py` passes against the current
  scenario manifest and emits `wiii.self_harness_validation.v1` with manifest
  version, manifest SHA-256 fingerprint, and normalized error codes. The
  manifest validator now treats the root, scenario, verification, and evidence
  objects as closed schemas and rejects duplicate string-list proof entries, so
  typoed fields or repeated evidence tokens cannot inflate harness coverage.
  Active scenarios must remain present in `required_scenarios`, and required
  scenario IDs must stay lowercase kebab-case, so a live control-plane contract
  cannot quietly become optional metadata. Required scenarios must also have
  `status: active`, so deferred or blocked contracts cannot remain mandatory
  without explicit reactivation. Active scenarios must include at least one
  `runtime` evidence file and one `test` evidence file, so product contracts
  cannot be proven by docs or governance metadata alone. Within a scenario,
  duplicate `kind` plus normalized repo-relative `path` evidence entries are
  rejected, so repeated file references or equivalent path spellings cannot
  inflate the manifest's evidence count.
- `.github/workflows/wiii-self-harness.yml` validates self-harness, runtime
  registry, and coverage reports with per-report SHA-256 digests, a bundle
  SHA-256 fingerprint, a self-validation JSON report, and an explicit sidecar
  validation result before CI handoff. It also writes standalone manifest and
  registry sidecars as `artifacts/wiii-self-harness-validation.json` and
  `artifacts/wiii-runtime-evidence-registry-validation.json`, so the uploaded
  run artifact exposes the exact control-plane contracts validated outside the
  report-bundle directory. Those sidecars are emitted immediately after
  report-bundle validation and before completion-audit smoke begins, so later
  handoff failures still leave manifest/registry proof in the uploaded run
  artifact. The workflow then runs
  `tools/wiii_self_harness/validate_self_harness_sidecar_parity.py` and writes
  `artifacts/wiii-self-harness-sidecar-parity-validation.json`, proving the
  standalone sidecars match the corresponding reports inside the generated
  `artifacts/wiii-self-harness/` bundle. That parity report records one
  comparison row per report with bundle path, sidecar path, matched flag, and
  canonical JSON SHA-256 values for both payloads, so the sidecar proof remains
  independently inspectable after artifact download. The parity validator
  rejects `--out` targets inside that bundle or equal to any input
  report/sidecar, so the validation step cannot pollute or overwrite the
  evidence it is checking.
  After the validators, smoke, and
  wrapper unit-test gates run, the final `if: always()` upload archives
  `wiii-self-harness-reports-${{ github.run_id }}` so operators can inspect the
  machine-readable reports after success or failure without uploading before
  later gates have executed. Its push and pull-request path filters include the
  Python and MJS runtime-evidence output helpers and their helper tests, so
  evidence writer contract changes rerun the central manifest and registry
  gates. It also runs
  `tools/wiii_self_harness/smoke_completion_audit_handoff.py` against the
  generated self-harness bundle and an empty runtime-evidence directory,
  expecting `completion_audit_ready: false` and `missing_artifact` errors, so
  the strict handoff path stays wired into CI without requiring live evidence
  artifacts on every self-harness run. The central workflow calls
  `tools/wiii_self_harness/generate_self_harness_report_bundle.py`, so
  self-harness, registry, coverage, and self-validation report generation plus
  final bundle validation stay inside Python instead of a multi-command shell
  script. The generator requires the output path to be a real directory when it
  already exists, requires that directory to be empty or absent before writing
  reports, and rejects symlink output directories or symlink output-directory
  parents before the first report write, so stale files, file-path overwrites,
  or unexpected resolved targets cannot be mixed into a new CI handoff bundle. The central `self-harness` CI job declares
  `timeout-minutes: 20`, and the harness unit tests assert that bounded timeout
  stays present. The same tests require central workflow `uses:` steps to stay
  on the approved core-action allowlist and be pinned to 40-character commit
  SHAs. They also require top-level `permissions: contents: read`, no job-level
  permission overrides, and pull-request-scoped concurrency cancellation.
  Report-bundle validation requires child JSON reports to be
  successful (`ok: true` with empty `error_codes` and empty
  `error_code_counts`) and to keep internal error lists such as `errors`,
  `validation_errors`, `coverage_errors`, `validation_error_codes`, and
  `coverage_error_codes` empty, so CI handoff cannot treat a report with hidden
  child failures as a valid bundle. It also requires every child JSON report to
  expose typed `error_code_counts`, so CI handoff cannot treat failed or weakly
  classified self-harness output as a valid bundle. Report-bundle validation also requires
  `error_code_counts` keys to match `error_codes`, rejects duplicate
  `error_codes`, and rejects zero counts for listed error codes, so failure
  summaries stay internally consistent. The self-harness and registry
  validation reports must also match the current repository manifest and
  runtime-evidence registry fingerprints, so CI cannot upload a green bundle
  generated from an older control-plane contract. The coverage JSON must also
  match the registry-validation JSON in the same bundle for registry identity,
  registry path, registry fingerprint, registry version, and requirement count,
  so CI cannot upload coverage generated from a different runtime-evidence
  registry contract or carrying stale operator-facing registry metadata. The
  report-bundle validator also compares every coverage row against the current
  `runtime_evidence_registry.json` for registry-derived identity and upload
  contract fields, including artifact tokens and diagnostic upload
  count/artifact/path metadata, raw-content absence counts, identifier-strategy
  counts/lists, external evidence mode, synthetic/credentialed external flags,
  and forbidden token/regex counts, returning
  `report_registry_coverage_row_mismatch` when a row is valid but stale or
  hand-edited. The
  coverage Markdown must also match the coverage JSON for operator-facing
  summary values, including registry identity, status, error-code counts,
  external-evidence counts, table row count, and each per-requirement coverage
  table row, so humans do not review a stale Markdown artifact while automation
  validates a different JSON payload.
  The three
  child JSON reports use closed top-level schemas, so unsupported report fields
  fail instead of being archived as unchecked metadata; known top-level values
  are also type/range validated, so allowed counts, labels, paths, layers,
  warnings, and error lists cannot carry raw objects or invalid summary values.
  Runtime evidence coverage rows now also expose `external_evidence_mode`,
  `synthetic_gap_flags`, and `credentialed_external_flags`, so CI handoff and
  operators can see LMS test-course, provider, and Composio lanes as
  credentialed external evidence while any future synthetic external gaps stay
  visible without relying on prose. The report also exposes
  `synthetic_external_gap_count`, `credentialed_external_count`, and
  `local_or_backend_count`, and bundle validation requires those top-level
  counts plus the top-level `layers` summary to match the rows.
  Completion and release audits can run the coverage report with
  `--require-no-synthetic-gaps`; if any row remains a synthetic external gap,
  the report fails with
  `coverage_synthetic_external_gap_present`.
  The stricter `--require-credentialed-external-contracts` mode also requires
  each credentialed external row to expose credential flags, live env flags,
  live guard tokens, at least two dispatch/schedule gates, raw-content absence
  checks, and identifier-strategy checks, failing with
  `coverage_credentialed_external_contract_incomplete` when the contract is
  incomplete.
  Downloaded report-bundle validation can enforce the same criterion with
  `--require-no-synthetic-gaps`, returning
  `report_coverage_synthetic_external_gap_present` against the bundled coverage
  JSON, and can enforce credentialed external contract completeness with
  `--require-credentialed-external-contracts`, returning
  `report_coverage_credentialed_external_contract_incomplete`.
  The report-bundle generator accepts the same strict flags and stops before
  writing self-validation when strict pre-validation fails, preventing stale
  successful handoff metadata from masking an incomplete external evidence
  contract.
  The runtime
  evidence coverage report also uses an exact row schema and its row count must
  match `requirement_count`, so nested coverage rows cannot hide unchecked
payloads or silently drop a registered evidence requirement; row values must
also keep expected string, string-list, boolean, and non-negative integer
shapes. For rows with a numeric freshness target, `coverage_target_met` must
equal `payload_checks >= freshness_hours`, so the bundle validator rejects a
hand-edited coverage JSON whose target flag contradicts the row counts. The
top-level `layers` summary must equal the distinct row-layer set.
The coverage Markdown table also collapses line breaks and
tabs before rendering, keeping the operator table shape stable. The report
bundle result separates `fingerprinted_report_count` from
  `self_validation_report_present`, so the canonical fingerprint scope remains
  explicit, emits bundle-level
  `error_code_counts` for CI triage, and writes the self-validation report with
  `--out` before moving it into the uploaded bundle. The uploaded report
  bundle must remain a flat, exact directory with only the five contracted
  report files; unexpected files or directories fail validation. Unexpected
  entries are scanned before the optional self-validation report, so a stale
  self-validation JSON cannot keep passing after a file or directory is added
  to the bundle. The final validation uses
  `--require-self-validation`, so the uploaded handoff artifact cannot pass
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
  directory paths as report outputs, so validation cannot pollute the directory
  it is checking or crash on a non-file output target.
- Understand-Anything deterministic scan/import-map was trialed locally as a
  supporting system-comprehension harness: `2433` tracked files, `3241`
  internal import edges, and `123` semantic batches. Generated output stays in
  ignored `.understand-anything/`.
- `tools/wiii_understand_harness/run_wiii_understand_flow_map.py` provides
  repo-owned scoped flow maps for chat baseline, LMS document preview,
  visual/Code Studio, and harness governance audits.

## Control Plane Model

Wiii should be operated through five product layers, one connection/capability
layer, and one governance layer:

| Layer | Owns | Typical failure symptom | First place to inspect |
|---|---|---|---|
| Wiii Core | turn routing, provider calls, tool loops, SSE events | wrong lane, silence, raw payloads, slow turn | `maritime-ai-service/app/services/chat_*`, `app/engine/multi_agent/**` |
| Wiii Living | continuity, identity, post-turn memory behavior | Wiii forgets, repeats, or changes persona incoherently | memory/living services and post-turn hooks |
| Wiii Host | desktop, embed, LMS, Pointy, visual/code frames | preview missing, Pointy wrong action, visual clipped | `wiii-desktop/src/**`, LMS/host bridge modules |
| Wiii Connect | connection registry, capability snapshot, provider adapters, path gating | tool appears on wrong path, connected state unclear, external action not auditable | `tool_policy_session.py`, `tool_capability_registry.py`, `docs/architecture/wiii-connect/**` |
| Wiii Org | auth, membership, tenant boundaries, permissions | wrong user/org, auth loop, cross-tenant risk | `app/auth/**`, org middleware, repositories |
| Wiii Data | PostgreSQL, pgvector, MinIO, Valkey, migrations | missing history, citations, uploads, memory, or source refs | repositories, migrations, document context paths |
| Governance | issue/branch/PR/release/harness controls | risky or unreviewable changes keep landing | `.github/**`, `docs/operations/**`, `tools/wiii_self_harness/**`, `tools/wiii_understand_harness/**` |

Do not start with a code edit until the failing symptom is mapped to one of
these layers and one active runtime flow.

## Active Runtime Flows

| Flow | User outcome | Layers | Primary entry points | Healthy signals |
|---|---|---|---|---|
| Chat stream | Wiii responds in real time with readable SSE V3 output | Core, Host, Org, Data | `chat_stream.py`, `chat_stream_coordinator.py`, `useSSEStream.ts` | `status/thinking/answer/metadata/done`, no raw tool JSON, final turn persisted |
| Uploaded document to LMS lesson | Teacher gets preview, citations/source refs, then applies with approval | Host, Core, Data, Org | `document_preview_contract.py`, `direct_node_document_preview_runtime.py`, `PreviewPanel.tsx` | preview host action emitted, source refs present, no mutation before `approval_token` |
| Visual/article figure | Inline figure appears in the answer and can be patched | Core, Host | `visual_intent_resolver.py`, `tool_collection.py`, `visual_events.py`, `VisualBlock.tsx` | required visual tool bound, `visual_open/patch`, `visual_commit`, no raw widget fences |
| Code Studio app/artifact | App-like output opens in host-owned preview shell | Core, Host | `code_studio_*`, `CodeStudioPanel.tsx`, `InlineVisualFrame.tsx` | typed tool-round outcome, safe-stop or preview, viewport frame not clipped |
| Pointy and host control | Wiii can guide or act on host UI only in the right mode | Host, Core, Org | Pointy host code, host action tools, audit route | explicit mode/capability, audit event, safe click policy respected |
| RAG and memory answer | Answer is grounded, cited, and tenant-safe | Core, Data, Org, Living | repositories, RAG services, memory services | tenant filters, active-org-scoped thread/history reads, source refs/citations, no unsupported facts from uploaded docs |
| Proactive scheduled task | Wiii runs due reminders or agent-invoke work without a user request | Living, Core, Org, Data | `scheduled_task_executor.py`, `scheduler_repository.py`, `notification_dispatcher.py` | `runtime.scheduled_tasks.*`, tenant-scoped task rows, delivery status |
| Living heartbeat | Wiii wakes periodically for reflection, journaling, briefing, skill review, and guarded proactive actions | Living, Data, Org | `heartbeat.py`, `heartbeat_runtime_support.py`, `autonomy_manager.py` | `runtime.living_agent.heartbeat.*`, org-scoped audits, approval queue status |
| Proactive outreach | Wiii sends guardrailed outbound messages after anti-spam and opt-out checks | Living, Org, Host | `proactive_messenger.py`, `channel_sender.py`, heartbeat re-engagement path | `runtime.living_agent.proactive.*`, opt-out scope, channel delivery status |
| Auth and org session | User identity and org context are stable across surfaces | Org, Host, Data | auth routers, middleware, desktop stores | verified auth, correct org, refresh works, no cross-surface token drift |
| Voice | Pointy voice status and provider-backed audio UX work safely | Host, Core | `voice.py`, desktop voice controls | feature flag/provider visible, graceful disabled state, no secret leakage |
| Production release | Reviewed `main` SHA runs through pinned images | Governance, Core, Host, Data | deploy workflow, release runbook, smoke script | image tags exist, app/nginx healthy, external smoke green |

## Flow Monitoring Ladder

This ladder is the minimum set of observations that should exist for a healthy
turn. Some signals already exist; missing signals are the next monitoring work.

| Stage | Signal that should exist | Current evidence | Gap to close |
|---|---|---|---|
| Edge/deploy | deploy SHA, image tag, VM state, public health | deploy workflow, release smoke, GCP VM status | keep a single release status note after stop/start events |
| API ingress | request ID, user ID, org ID, session ID, endpoint | API headers, middleware request state, auth context, stream-coordinator request correlation that preserves or generates `request_id` for ledger/lifecycle/heartbeat/log/finalization continuity, Wiii Connect execution-request/gateway/audit-ledger correlation for HTTP and agent-tool actions, Composio provider-call request headers plus sanitized result metadata, `/admin/runtime-flow/doctor` aggregate `request_correlation` metrics with alert codes, lifecycle hook registration counts plus `lifecycle_registrations` / `wiii.runtime_lifecycle_registrations.v1` owner-point metadata, and hourly `alert_trend` buckets, `/admin/runtime-flow/doctor/history` bucketed aggregate history, active-org-scoped `/admin/analytics/*` aggregate SQL reads, desktop Runtime-tab operator panel for recent aggregate runtime-flow doctor counts plus bucketed doctor history and dry-run/apply session-event retention control, admin-triggered `/admin/runtime-flow/session-events/prune` retention endpoint for old `session_events`, Prometheus-compatible `runtime.runtime_flow_ledger.alerts` counters, `docs/runtime/alerts/prometheus-runtime-flow-ledger.yml` thresholds backed by `docs/runtime/runbooks/runtime-flow-ledger-alerts.md`, and launch-checklist coverage for `ENABLE_PROMETHEUS_METRICS` plus rule import | import the rule file into the live Prometheus/Alertmanager instance during the next environment deploy |
| Context build | host surface, document context, source refs, memory context | document context tests, preview contract, Context Provenance Ledger v1, typed current-history retrieval summary `wiii.chat_history_retrieval.v1`, typed context budget/compaction summary `wiii.context_budget.v1`, runtime-ledger summary fields for history count/status/source and context-budget utilization/dropped-message/status, backend source-backed document replay, backend semantic memory-turn replay, runtime acceptance evidence JSON with `browser_replay` terminal ledger/trace cases that can seed the desktop Runtime tab without raw prompt, answer, or SSE event payloads, Playwright acceptance that renders that backend evidence shape in Wiii Connect Runtime, `npm run test:e2e:runtime-ledger:browser-replay` for an already-running backend, `npm run test:e2e:runtime-ledger:browser-replay:local` which starts a disposable backend, writes backend evidence JSON, feeds that exact file into browser replay, emits `wiii.runtime_flow_browser_replay_summary.v1` hash/count summary evidence, and cleans up the backend process tree, and `.github/workflows/runtime-ledger-browser-replay-evidence.yml` can upload that summary artifact through explicit `run_browser_replay=true` or scheduled `WIII_RUNTIME_LEDGER_BROWSER_REPLAY_EVIDENCE_ENABLED=1` runs | run the exact-file browser replay workflow in staging against a persistent backend and archive the hash/count summary artifact |
| Intent/routing | selected lane and reason | typed visual/tool requirements, Code Studio outcomes, visual/Code Studio backend stream replay, desktop Runtime ledger `Route decision` row, Playwright browser acceptance that verifies route reason is visible without raw payload leakage, and exact-file browser replay summary checks for backend route counts across `lms_document_preview`, `external_connection_status`, `external_app_action`, and `visual_generation` with per-case route-reason hashes instead of raw reasons | run the broadened route replay workflow in staging against a persistent backend and archive the hash/count summary artifact |
| Subagent delegation | projected parent keys, dropped keys, child result counts, warning codes | Subagent executor attaches `wiii.subagent_execution_boundary.v1` with `wiii.subagent_handoff_boundary.v1` and `wiii.subagent_result_boundary.v1` to sanitized child results; runtime-flow trace/ledger aggregate this as `wiii.subagent_boundary_trace.v1`; focused unit tests prove parent state, kwargs, child output, sources, tools, images, private thinking, and errors are projected as count-only evidence without raw child working memory; runtime-flow acceptance now validates terminal subagent boundary schema/counts/warnings and rejects raw child payload keys; opt-in live replay `scripts/probe_live_subagent_boundary_replay.py` runs the real parallel executor, runtime-flow ledger, and runtime-flow doctor behind `WIII_LIVE_SUBAGENT_BOUNDARY_REPLAY=1 --allow-run` with hash/count-only request identity evidence, fixed parallel result-status and result-count proof, runtime-ledger done/report-count parity, handoff/result boundary aggregates, dropped-key/source/tool/evidence-image/private-thinking counts, child-output sanitization proof, doctor aggregate parity, explicit raw-request/raw-secret absence, and redacted failure artifacts that do not count as release evidence; `.github/workflows/subagent-boundary-evidence.yml` runs contract tests on relevant PRs/pushes while reserving artifact generation for explicit `run_subagent_boundary_replay=true` dispatch or scheduled `WIII_SUBAGENT_BOUNDARY_EVIDENCE_ENABLED=1`, validates raw-marker absence, and uploads the `subagent-boundary-evidence.json` artifact; desktop Runtime tab, browser replay summary, `/admin/runtime-flow/doctor`, and `/admin/runtime-flow/doctor/history` render subagent report count, projected/dropped-key counts, source/tool counts, thinking-dropped count, warning count, and raw-content flag | run the guarded subagent boundary replay in staging and archive the hash/count-only evidence |
| Retrieval/memory | query scope, tenant filters, source IDs, citation count | repository tests, source-reference helpers, active-org-scoped thread index/message pagination, current-history context/user-name reads, explicit-org message persistence, active-org history API reads/deletes, and cross-session summary injection tests, backend LMS document replay, semantic memory-turn ledger replay, user memory API `summary` with count-only provenance/privacy, desktop MemoryTab status summary, Playwright browser memory acceptance for summary fetch and clear-all, post-turn semantic write audit/doctor evidence `semantic-memory-write-evidence.json` from `scripts/probe_live_semantic_memory_write_doctor.py` with embedded `post_turn_lifecycle` lifecycle-owned semantic scheduling proof plus durable runtime-flow doctor `post_turn_lifecycle_ledger` proof, `/admin/semantic-memory/doctor/recent` plus `/admin/semantic-memory/doctor/history` with `wiii.semantic_memory_write_doctor_history.v1` aggregate buckets for `recent_semantic_memory_write_history`, redacted failure artifacts that remain diagnostic-only, desktop Runtime-tab semantic-memory doctor panel for the same aggregate recent/history reports, startup-registered semantic-memory lifecycle observers that emit `runtime.semantic_memory.lifecycle.*` metrics and `semantic_memory_lifecycle` / `wiii.semantic_memory_lifecycle.v1` session events without duplicating memory writes, lifecycle-owned post-turn semantic-memory interaction/maintenance scheduling through `wiii.post_turn_lifecycle.v1` and `runtime.post_turn.lifecycle.scheduling`, the same status-only post-turn summary plus sanitized `wiii.background_task_schedule.v1` groups in sync response metadata and stream runtime-ledger finalization, admin runtime-flow doctor `post_turn_lifecycle` aggregate metrics through `wiii.post_turn_lifecycle_metrics.v1` plus durable `post_turn_lifecycle_ledger` counts through `wiii.post_turn_lifecycle_ledger.v1`, desktop Runtime-tab `wiii-connect-runtime-post-turn-lifecycle` rendering of those process metrics and durable ledger task groups, background task group summaries through `wiii.background_task_schedule.v1` and `runtime.background_tasks.scheduling`, post-turn semantic maintenance metrics `runtime.semantic_memory.maintenance.*` for Taskiq enqueue, local fallback, prune, and summarize outcomes, and opt-in live LMS test-course replay `scripts/probe_live_lms_test_course_replay.py` that streams source-backed `lms_document_preview` through `/chat/stream/v3` with hash/count-only evidence | run the semantic-memory write evidence workflow and live LMS replay against persistent staging DB and approved test-course host settings |
| Provider/tool loop | provider/model, tool bound, tool started/result/error | `runtime_flow_ledger.runtime` carries provider/model authority, `runtime_flow_ledger.tools` carries observed/suppressed/visible tools and policy denials, `runtime_flow_ledger.stream.event_counts` carries tool_call/tool_result/error counts, backend delegate execution acceptance runs Wiii Connect delegate tool -> integration worker -> backend executor -> `runtime_flow_trace`/`runtime_flow_ledger`, guarded Wiii Connect action replay `scripts/probe_live_wiii_connect_action_replay.py` proves `ExternalAppActionPlan` -> `ExternalAppIntegrationLane` -> provider worker -> backend gateway/schema/audit/execute -> final-answer source without provider credentials and emits `wiii.live_wiii_connect_action_replay.v1` through `.github/workflows/wiii-connect-action-evidence.yml`, credentialed Composio acceptance `scripts/wiii_connect_composio_acceptance.py --out` verifies connected-account selection, live schema readiness, execution gateway, and read-only provider execution behind `WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE=1 --allow-live` and uploads `wiii-connect-composio-acceptance-evidence.json`, desktop Runtime ledger renders `Provider/model` and `Tool loop` rows, unit/browser acceptance verifies visibility without secret leakage, opt-in live probe `scripts/probe_live_provider_runtime.py` runs a credentialed LLMPool/WiiiChatModel tool-call/tool-result roundtrip with request/session/org hash proof, exact single-tool-call proof, forced tool-schema evidence, linked hashed tool-result proof, Wiii-native runtime-boundary proof, trace-duration/attribute privacy proof, and optional `/chat/stream/v3` ledger verification with done-event parity and stream-payload privacy behind `--include-stream-ledger --allow-stream-write`, with redacted failure artifacts that remain diagnostic-only, and `.github/workflows/provider-runtime-evidence.yml` runs provider probe contract tests on relevant changes while reserving live provider calls for explicit `workflow_dispatch allow_live_call=true` or scheduled runs gated by `WIII_PROVIDER_RUNTIME_EVIDENCE_ENABLED=1`, then uploads `provider-runtime-evidence.json` | run the credentialed provider runtime evidence workflow in staging against approved provider keys and archive the hash/count-only artifact |
| Autonomous scheduled execution | due-task polls, execution mode/status, delivery outcome, duration | `ScheduledTaskExecutor` emits `runtime.scheduled_tasks.polls`, `runtime.scheduled_tasks.due`, `runtime.scheduled_tasks.runs`, `runtime.scheduled_tasks.delivery`, and `runtime.scheduled_tasks.duration_ms`; Prometheus rule `prometheus-scheduled-task-executor.yml`; runbook `scheduled-task-executor.md`; product-style unit acceptance runs due reminder and agent-invoke tasks through dispatcher delivery, org-scoped mark-executed calls, and bounded metrics; creation-to-delivery acceptance creates a reminder through `tool_schedule_reminder`, then the worker delivers it through the real `WebSocketAdapter` plus in-memory `ConnectionManager` contract while preserving org-scoped delivery metadata; desktop now opens an authenticated scheduled-notification WebSocket with OAuth/JWT or legacy API-key first-message auth, renders scheduled-task delivery as a toast, and Playwright verifies reminder creation through SSE/tool/runtime-ledger evidence plus WebSocket delivery UI; opt-in live replay probe `scripts/probe_live_scheduled_task_replay.py` writes one real `scheduled_tasks` row through the scheduler tool, waits for clock due-time, polls scoped due tasks from the shared Postgres repository, executes only the created task through the same worker observability side-effect helper, delivers through the real WebSocket adapter, verifies active-to-completed DB lifecycle, cleans up by default, and emits `wiii.live_scheduler_replay_probe.v1` hash/count-only evidence; registry validation now requires request-scoped user/session/org hash evidence, `allow_all_orgs=false` due-poll proof, scheduler-tool/repository/executor/delivery replay contracts, created/completed row org and lifecycle checks, WebSocket payload hash proof, successful poll/due/run/delivery/duration metric evidence with bounded mode/status labels, `cleanup.deleted=true` without raw task IDs, database rows, metric payloads, user/session/org IDs, descriptions, or delivery payloads, and redacted failure artifacts that remain diagnostic-only; `.github/workflows/autonomy-runtime-evidence.yml` runs scheduler probe contract tests on PR/push and can upload `autonomy-scheduler-evidence.json` on explicit dispatch or `WIII_AUTONOMY_RUNTIME_EVIDENCE_ENABLED=1` schedule | run the live scheduler replay in staging against persistent DB plus a real desktop/browser session |
| Living heartbeat autonomy | heartbeat cycle status, action type/status, approval queue, duration | `HeartbeatScheduler` and runtime support emit `runtime.living_agent.heartbeat.cycles`, `runtime.living_agent.heartbeat.duration_ms`, `runtime.living_agent.heartbeat.actions`, and `runtime.living_agent.heartbeat.action_duration_ms`; Prometheus rule `prometheus-living-agent-heartbeat.yml`; runbook `living-agent-heartbeat.md`; scheduler-level acceptance executes reflect, journal, briefing, and proactive re-engagement actions in one heartbeat cycle and verifies bounded outcome metrics; heartbeat discovery notifications now use structured `proactive_message` payloads, carry `heartbeat_discovery` trigger metadata, and are delivered through org-scoped WebSocket sessions only; opt-in live probe `scripts/probe_live_heartbeat_cycle.py` requires `WIII_LIVE_HEARTBEAT_CYCLE_PROBE=1`, runs a controlled heartbeat cycle, verifies org-scoped `wiii_heartbeat_audit`, `wiii_journal`, `wiii_reflections`, `wiii_briefings`, and emotional-state deltas, and can optionally exercise proactive WebSocket re-engagement through `ProactiveMessenger` -> `NotificationDispatcher` -> `WebSocketAdapter` with hash/count-only evidence; registry validation now requires request-scoped user/session/org hash evidence, requested/effective org parity, non-noop/no-error cycle proof, reflect and journal planned/recorded action parity from the real scheduler boundary, briefing hash/count evidence, living-table scope contracts, successful heartbeat cycle/action/duration metric labels, bounded metric-label strategy, and privacy flags proving no raw identifiers, DB rows, metric payloads, emotional state, action targets, metadata values, briefing content, or socket payloads, with redacted failure artifacts that remain diagnostic-only; `.github/workflows/autonomy-runtime-evidence.yml` runs heartbeat probe contract tests on PR/push and can upload `autonomy-heartbeat-evidence.json` on explicit dispatch or `WIII_AUTONOMY_RUNTIME_EVIDENCE_ENABLED=1` schedule | run the guarded heartbeat-cycle probe in staging against persistent DB/local LLM, including `--include-proactive-websocket` when proactive messaging is enabled |
| Proactive outreach | can-send guardrail decision, send result, delivery latency | `ProactiveMessenger` emits `runtime.living_agent.proactive.can_send`, `runtime.living_agent.proactive.sends`, and `runtime.living_agent.proactive.send_duration_ms`; Prometheus rule `prometheus-proactive-messenger.yml`; runbook `proactive-messenger.md`; channel-level acceptance sends a proactive WebSocket message through `NotificationDispatcher`, the real `WebSocketAdapter`, and an in-memory `ConnectionManager`, proving same-user sessions in other orgs do not receive it; WebSocket proactive delivery now uses structured `proactive_message` payloads, and desktop browser acceptance verifies the authenticated notification socket renders a Vietnamese-first proactive toast without auth tokens in the URL; opt-in live-channel probe `scripts/probe_live_proactive_channel.py` sends one guarded proactive message through Telegram, Messenger, or Zalo using real credentials, DB opt-out/audit checks, org scope, and `wiii.live_proactive_channel_probe.v1` hash-only evidence; registry validation now requires channel enabled/credential-present proof, database opt-out/audit reachability plus request-org scope, request-org context proof, recipient/org/message hash-presence, single-send trigger/priority/raw-message flags, supported-channel proof, credential-value and credential name/value pair absence, `can_send=allowed` metric count evidence with zero blocked-guardrail metrics, delivered-send and duration metric count evidence, bounded metric-label strategy, metric-label privacy, and raw message/recipient/org/trigger-target/metric-payload/delivery-payload/credential privacy flags, with redacted failure artifacts that remain diagnostic-only and now carry the same setup contract as the preflight sidecar; `.github/workflows/autonomy-runtime-evidence.yml` runs proactive channel probe contract tests on PR/push, runs `scripts/probe_live_proactive_channel.py --preflight-only` before live sends to fail early on missing recipient/channel/credential setup, validates the privacy-safe preflight JSON with `validate_runtime_evidence_preflight.py`, prints it to the step log and summary, materializes a failed diagnostic `autonomy-proactive-channel-evidence.json` when preflight blocks the live send, and can upload the registered evidence artifact by explicit dispatch or `WIII_PROACTIVE_CHANNEL_EVIDENCE_ENABLED=1` schedule | run the credentialed probe against approved staging/live channel recipients |
| Connection/capability | connected provider slugs, scopes, path-ready status, suppressed tools | Wiii Connect snapshot `capability_summary` owns active/agent-ready connection slugs, external provider slugs, connected scope names, per-path readiness, and suppressed tool groups; snapshot tests and the desktop Path policy tab render the same contract; `ToolPolicySession` remains the enforcement input; runtime-flow acceptance now fetches the live `/api/v1/wiii-connect/snapshot` endpoint, validates the privacy-safe capability contract, and emits `wiii_connect_capability` hash/count summary evidence into the exact-file browser replay summary | run the broadened capability replay in staging against connected provider accounts and archive the hash/count summary artifact |
| SSE assembly | event order, first useful chunk, final `done` | stream coordinator tests, visual/Code Studio backend stream replay, production smoke, runtime acceptance `--sync-parity` checks that compare `/api/v1/chat` answer/metadata/runtime trace authority with `/api/v1/chat/stream/v3`, and exact-file browser replay evidence that runs parity by default for non-stream-artifact safe cases and requires `checks.sync_parity_passed >= 3`; marked safe scenarios now cover casual chat, weather tool routing, connection-status control plane, and blocked external-action plans, including sync visible-tool checks and `external_app_action_plan` parity | keep expanding parity only for lanes where sync semantics are supposed to match SSE and no stream-only artifact events are required |
| Frontend assembly | visible answer, previews, sources, visual frames | Vitest, local E2E harness, visual frame tests, desktop runtime ledger panel tests, authenticated embed LMS browser acceptance, visual/Code Studio stream browser acceptance, and exact-file browser replay that renders every backend replay case while the summary requires `validated_case_id_hashes`, visual lifecycle case counts, and Code Studio lifecycle case counts | run the full exact-file matrix in staging against a persistent backend and archive screenshots plus the hash/count summary artifact |
| Host mutation | preview request ID, approval token hash, apply result | host action audit route, token hash tests, iframe host-bridge apply browser acceptance, and guarded live LMS test-course replay that posts authenticated `preview_created` plus `apply_confirmed` audit events, applies the approved patch to a credentialed external LMS test-course webhook, cross-checks source-count and preview-to-apply audit linkage, and keeps approval/external LMS credentials out of Wiii audit payloads; `.github/workflows/lms-test-course-evidence.yml` validates the probe contract, runs and validates `scripts/probe_live_lms_test_course_replay.py --preflight-only`, uploads `lms-test-course-preflight-${{ github.run_id }}` as diagnostic-only setup evidence, and can upload `lms-test-course-evidence.json` through explicit `run_lms_replay=true` or scheduled `WIII_LMS_TEST_COURSE_EVIDENCE_ENABLED=1` runs | run and archive the credentialed LMS evidence artifact after staging test-course secrets are configured |
| Finalization | saved turn, metadata, post-turn hooks | orchestrator finalization tests, native stream dispatch `runtime.native_stream_dispatch.finalization`, non-stream dispatch `runtime.native_dispatch.finalization`, lifecycle registrations with explicit owner metadata and `registrations_at(...)` diagnostics, startup-registered runtime hooks that emit `runtime.lifecycle.hook_runs`, startup-registered `engine.semantic_memory` observers for `on_run_end`/`on_run_error`, typed `PostTurnLifecycleContext` scheduling that owns semantic interaction/maintenance scheduling while `BackgroundTaskRunner.schedule_all` remains a compatibility wrapper into the same coordinator, `wiii.post_turn_lifecycle.v1` status-only summaries, sync/stream parity checks that require that summary without raw message/response/user/session scope, `BackgroundTaskScheduleSummary` evidence for each post-turn task group, sanitized runtime-ledger finalization copies of those task groups, semantic-memory write doctor artifact validation that requires `post_turn_lifecycle.lifecycle_owned_semantic_scheduling=true`, `post_turn_lifecycle.compatibility_wrapper_used=false`, and durable `runtime_flow_doctor.post_turn_lifecycle_ledger.event_count=1`, admin runtime-flow doctor `post_turn_lifecycle` reports with `wiii.post_turn_lifecycle_metrics.v1` aggregate post-turn/background scheduling counts, admin runtime-flow doctor `post_turn_lifecycle_ledger` reports with `wiii.post_turn_lifecycle_ledger.v1` durable counts from `finalization.post_turn_lifecycle`, admin runtime-flow doctor `lifecycle_registrations` reports with `wiii.runtime_lifecycle_registrations.v1` default-hook owner/point evidence, lifecycle `runtime.lifecycle.hook_failures` labeled by explicit hook-registration owner and hook point with bounded module-inferred fallback for legacy callers, Prometheus rules/runbooks under `docs/runtime/alerts/` and `docs/runtime/runbooks/`, and exact-file browser replay summary evidence that requires every replay case to finish with saved finalization plus zero finalization errors through finalized case hashes and matching post-turn lifecycle case hashes | run the semantic-memory write evidence workflow against persistent staging services and archive the hash/count `post_turn_lifecycle_ledger` artifact |

The proactive channel workflow also uploads
`autonomy-proactive-channel-preflight-${{ github.run_id }}` as a 14-day
diagnostic artifact from `autonomy-proactive-channel-preflight.json` after the
privacy-safe preflight validation; if validation fails, the workflow removes
the preflight file before any diagnostic upload. That sidecar is only for
operator setup triage;
`autonomy-proactive-channel-evidence.json` remains the registered artifact
required for Runtime Evidence Registry coverage. If preflight is valid but not
dispatch-ready, the workflow writes a failed registered-artifact diagnostic with
the same `setup_contract` by passing the validated preflight JSON to
`--failure-from-preflight --failure-preflight-json` before exiting non-zero;
this keeps completion-audit runs source-bound without allowing setup failures
to pass release evidence.

Runtime alert rule files currently owned by this ladder:
`prometheus-runtime-flow-ledger.yml`, `prometheus-native-stream-dispatch.yml`,
`prometheus-native-dispatch.yml`, `prometheus-runtime-lifecycle.yml`, and
`prometheus-semantic-memory-maintenance.yml`,
`prometheus-scheduled-task-executor.yml`, and
`prometheus-living-agent-heartbeat.yml`, plus
`prometheus-proactive-messenger.yml`.
Their runbooks are `runtime-flow-ledger-alerts.md`,
`native-stream-finalization.md`, `native-dispatch-finalization.md`, and
`runtime-lifecycle-hook-failures.md`, plus
`semantic-memory-maintenance.md`, `scheduled-task-executor.md`, and
`living-agent-heartbeat.md`, plus `proactive-messenger.md`.

Runtime Evidence Registry artifacts are tracked by
`tools/wiii_self_harness/runtime_evidence_registry.json` and validated by
`tools/wiii_self_harness/validate_runtime_evidence_registry.py`. The registry
validation result uses `wiii.runtime_evidence_registry_validation.v1` in JSON
and text summary output, so CI handoff tooling can pin the registry-validator
report contract independently. It also reports the registry integer version and
a registry contract SHA-256 fingerprint over the registry name, version, and
requirements, so operators can compare the exact contract validated by CI.
Registry validation JSON and failure summaries also expose normalized
`error_codes` for registry-shape, workflow, upload, permissions, path-filter,
artifact-name, payload-check, and freshness failures, so automation does not
need to scrape raw validation text.
The registry root, each runtime evidence requirement, and nested proof objects
such as `freshness`, `payload_checks[]`, and payload-check `when` clauses are
closed-schema allowlists; unknown keys are rejected so typoed fields or
decorative config cannot drift outside the machine-checked contract.
Registry proof paths must also use validator-approved dot-path syntax:
`payload_checks[].path` may use explicit `*` wildcard segments for list entries
only, while freshness timestamps, `length_equals_path`, and payload-check
`when` paths may not because artifact validation reads those through
single-value path lookup. `length_equals_path` subjects must still be JSON
arrays, so object maps cannot stand in for ordered replay or audit sequences.
Payload-check operation values are typed before artifact validation as well:
`min` must be a JSON number, `sorted_equals` must be a list, and payload-check
`when` clauses must select exactly one explicit `equals` or `not_equals`
condition instead of falling back to truthiness. Expected `equals`,
`sorted_equals` entries, and `when` comparison values must be non-null JSON
scalars, keeping proof expectations simple and deterministic.
Produced JSON artifacts are validated by
`tools/wiii_self_harness/validate_runtime_evidence_artifact.py` against the same
registry, including `payload_schema_field`, `forbidden_payload_tokens`, and
`payload_checks`, plus per-artifact freshness (`generated_at` and
`max_age_hours`). The artifact validator CLI revalidates the registry contract
before reading the artifact payload, so direct workflow/operator use cannot
silently trust a malformed registry file. Forbidden payload token checks are case-insensitive, so
secret-like labels cannot bypass validation through capitalization changes.
The registry applies the same semantics by rejecting case-insensitive
duplicate forbidden-token entries before a workflow can inflate privacy proof
coverage.
Per-artifact validation rejects symlink artifact paths before reading JSON, so
the workflow gate cannot validate a pointer to local state instead of the
produced evidence file.
Artifact JSON parsing rejects non-finite constants such as `NaN` or `Infinity`,
and numeric `min` checks treat booleans and numeric-looking strings as
non-numeric, so runtime evidence cannot satisfy duration/count thresholds with
JSON-adjacent values that are not strict finite numbers. `sorted_equals` checks
compare JSON-canonical multiset values instead of Python's native mixed-type
ordering, so malformed mixed-type lists fail as payload mismatches rather than
crashing the validator.
Manifest, registry, report, and freshness version/count fields also reject
boolean-as-integer values, so `true` cannot stand in for `1` in control-plane
contracts.
The same strict JSON stance applies to manifest, registry, report-bundle, and
bundle freshness reads: non-finite JSON constants are treated as parse failures
before report contracts or evidence freshness can be trusted, and duplicate
object keys are rejected before a later key can silently override an earlier
contract value. That parser policy is centralized in
`tools/wiii_self_harness/strict_json.py` so new control-plane readers inherit
the same behavior instead of copying local parser hooks. The strict JSON tests
also guard the runtime reader modules against direct `json.load` or
`json.loads` use, so future readers cannot bypass the shared policy silently.
Self-harness, registry, coverage, runtime-evidence bundle, and report-bundle
CLIs also reject direct/parent symlink and directory paths as `--out` report targets, so CI
handoff failures stay typed JSON errors instead of filesystem redirects or
crashes.
That artifact validation result uses
`wiii.runtime_evidence_artifact_validation.v1` in JSON and text summary output,
separate from the produced artifact payload `schema_version`, so downstream
gates can version the validator report contract independently. Its JSON output
and failure summary also expose normalized `error_codes` and
`error_code_counts`, so automation can classify and count schema, privacy,
freshness, and payload-check failures without scraping raw error text. Bundle
validation reuses the same artifact error-code taxonomy for payload validation
failures, preventing drift between per-artifact workflow gates and
downloaded-bundle handoff reports.
Even when a caller passes `--requirement-id`, artifact validation rejects files
whose filename does not match the registered artifact name, so a valid payload
cannot be silently substituted under the wrong evidence handle.
Every registered runtime evidence requirement must include payload checks that
prove raw content is absent through a `raw_content_included == false` field and
that identifiers use an approved `identifier_strategy`, keeping provenance
hash/count strategy explicit instead of depending only on forbidden-token scans.
Every registered runtime evidence requirement must also forbid baseline secret
payload tokens `api_key`, `access_token`, and `authorization`, so live evidence
privacy does not depend only on probe-specific raw markers.
Registered `forbidden_payload_regexes` must compile and must be unique within
the requirement, so malformed or duplicate privacy guards fail in the registry
gate instead of at late artifact-validation time.
String-list obligations in the registry, including forbidden tokens, contract
tests, live env flags, guard tokens, gates, and artifact tokens, must be unique
within their field, preventing repeated values from inflating apparent proof
coverage. Forbidden payload tokens are additionally unique after case folding,
matching the artifact validator's case-insensitive secret scan.
Payload checks must also be unique by path, operation, and condition, so a
requirement cannot carry duplicate or contradictory proof obligations for the
same payload field.
Artifact upload tokens must include either the requirement ID or the artifact
stem, so registry-valid workflow uploads remain traceable to the registered
runtime proof instead of becoming opaque upload handles.
The registry validator also requires every registered contract-test path to be
referenced by its evidence workflow and executed from a `run` step through
`pytest` or `vitest`, so declared proof obligations cannot drift away from the
CI job that is supposed to run them. The workflow run-step path match must be
bounded and shell comments are ignored, so a commented-out `pytest`/`vitest`
command or `test_file.py.disabled` cannot stand in for `test_file.py`. The
runner must start the shell command line directly, so text emitted by `echo` or
another wrapper command cannot masquerade as a test run.
Registered contract tests must be actual
Python `test_*.py` files or TypeScript `*.test.ts`/`*.spec.ts` test files, so
helper modules, docs, or data files cannot stand in as proof. Contract-test
paths must also be unique after normalized repo-relative path comparison, so
the same test cannot inflate coverage through equivalent path spellings. It also checks that each
workflow's artifact-validation command targets the registered artifact with the
matching `--requirement-id`, and that the upload-artifact step uploads that same
artifact under the registered artifact token. The artifact path passed to
`validate_runtime_evidence_artifact.py` must normalize to the exact registered
filename, so validating `tmp/<artifact>` or another sidecar with the same
basename cannot stand in for the file that will be uploaded. The subsequent
upload step must target that same file in the validation step's
`working-directory` (`<working-directory>/<artifact>`), or the bare artifact
filename when no working directory is set; token-only workflow drift is not
accepted as runtime proof. Registered evidence workflow paths must live
directly under `.github/workflows/`, so registry entries cannot point at
arbitrary YAML files outside GitHub Actions execution. Registered evidence workflows must keep top-level
permissions exactly at `contents: read`, with no extra scopes or job-level
permission overrides. Critical top-level workflow keys (`on`, `permissions`,
`concurrency`, and `jobs`) must be unique, so a later duplicate block cannot
or scalar assignment cannot override the safe block that the validator
inspected. They must also harden checkout steps with
`persist-credentials: false`, keeping workflow credentials out of post-checkout
git configuration by default. Every `uses:` step in registered evidence
workflows must be a real step field directly under a job-level `steps:` list,
stay on the approved core-action allowlist, and be pinned to 40-character
commit SHAs instead of mutable version tags; third-party, local, and shell-text
action references fail closed unless the allowlist is intentionally changed. Registered
evidence workflows must also declare top-level concurrency with
`group: ${{ github.workflow }}-${{ github.event_name }}-${{ github.ref }}` and
`cancel-in-progress: ${{ github.event_name == 'pull_request' }}`, so superseded
PR checks can collapse without canceling scheduled or manual evidence runs.
Manual live-evidence gates registered as lowercase snake-case `allow_*` or
`run_*` tokens must be `workflow_dispatch` boolean inputs with `default: false`
and must be referenced by an `inputs.<name> == true` dispatch condition.
Scheduled live-evidence gates registered as uppercase
`WIII_*_EVIDENCE_ENABLED` tokens must be guarded by
`vars.<name> == '1'`, so nightly runtime evidence remains opt-in through the
repository or environment variable boundary. Each registered requirement must
declare exactly one manual dispatch gate and exactly one scheduled vars gate,
and unsupported gate-token shapes fail before workflow inspection. The live
evidence job's job-level `if:` must bind those registered manual and scheduled
gate tokens as the exact dispatch-or-schedule expression and must not add
fallback events such as `push`; the validator reads job `if:` expressions
rather than whole-file text, so mentioning the same token in an env block,
comment, setup step, or echo is not accepted as job scheduling proof.
Manual dispatch inputs must be real children of the top-level `on:
workflow_dispatch` event and declare non-comment `type: boolean` and
`default: false` fields, so commented schema hints or copied fake event blocks
cannot turn an unsafe manual input into an accepted live-run gate. Manual
dispatch input names and schema fields that control description, required
status, type, and default must not be duplicated, so a later YAML key cannot
override the opt-in `default: false` gate the validator inspected. Event names
directly under the top-level `on:` map must be unique, so a later duplicate
`push` or `workflow_dispatch` block cannot override the filtered/gated event
block the validator inspected.
Registered live env flags must be uppercase `WIII_*` environment variables,
must not reuse scheduled `_EVIDENCE_ENABLED` gate tokens, and must be assigned
as `WIII_*: "1"` inside a real workflow `env:` map. A shell `run: |` line or
unrelated YAML field that only spells the same flag is not accepted as live
runtime enablement. Workflow `env:` maps must not duplicate registered live
env flags, so a later YAML key cannot override the `WIII_*: "1"` value the
validator inspected. Every registered guard token must be an
explicit `--allow-*` lowercase kebab-case CLI flag and must appear in the same
workflow step that invokes the registered probe script. Token-only mentions in
comments, echo steps, or unrelated setup are not accepted as live evidence
proof. The registered probe path is matched as a bounded command token after
shell comments are stripped, so a commented-out probe command or path-prefix
spoof such as `probe.py.disabled` cannot stand in for live evidence execution.
Registered probes must be Python `.py` or Node ESM `.mjs` scripts, so
the registry cannot point live proof at arbitrary text, docs, or data files.
The live evidence job must also checkout the repository with
`persist-credentials: false` before invoking the registered probe, so artifact
generation cannot rely on checkout state from another job or from after the
probe has already run. The checkout credential setting must be a direct
`with:` map scalar on a real checkout `uses:` step, so commented
`persist-credentials: false` hints, fake `uses: actions/checkout` lines, or
YAML-looking `- uses:` list items inside `run: |` cannot stand in for a
hardened checkout.
When a registered live probe uses a multiline `run: |` step, that step must
start with `set -euo pipefail`, so missing shell inputs and pipeline failures
fail closed before artifact validation or upload.
The registered probe must be invoked by a direct shell command line whose first
executed argument is the probe path (`python` / `python3` for `.py` probes or
`node` for `.mjs` probes); `echo`, `python -m ...`, or wrapper text that merely
mentions the probe path does not count. Probe guard tokens and the Python probe
`--out <artifact>` argument must be argv on that same direct probe command,
before any shell control operator; text after `;`, `&&`, pipes, or another
command cannot satisfy the probe contract.
For Python probes, the same invocation step must write the registered artifact
with `--out <artifact>` using an exact artifact filename match. Each runtime
evidence requirement must also have one workflow job that binds the registered
live env flag, probe guard, artifact validator command with the matching
`--requirement-id`, exact artifact filename, and exact artifact upload token,
so validation and upload cannot drift away from the probe that produced the
payload or pass through path-prefix/token-prefix spoofing. The artifact
validator proof must be a Python command that invokes the canonical
`tools/wiii_self_harness/validate_runtime_evidence_artifact.py` path, or
`../tools/wiii_self_harness/validate_runtime_evidence_artifact.py` from
component working directories, so an `echo`, text-only mention, or same-named
validator script in another directory does not count as artifact validation.
The validator command must pass exactly one artifact positional and exactly one
`--requirement-id` value matching the registry entry, so later text or extra
arguments cannot spoof a different validation target. The same job must order
those steps as probe, then artifact validation, then upload, so unvalidated
payloads cannot be uploaded as runtime evidence. The live evidence job must
either execute every registered
contract test itself or declare `needs: contract` against a contract job that
checks out the repo with `persist-credentials: false` before running those
registered tests and has no job-level `if:`, so scheduled/manual evidence
cannot bypass or conditionally skip the contract job. Any workflow reference
to the GitHub Actions `secrets` context, including dot or bracket syntax, must
stay inside a job whose `if:` exactly matches one registered
workflow-dispatch/schedule evidence gate pair and that job must declare
`needs: contract`. The same job must also match a registered live evidence
requirement by live env flag, probe guard, validator command, and
validation-derived upload path, so a gated sidecar job cannot hold credentials
outside the runtime proof chain; top-level, contract-job, PR, or push secret
references fail registry validation.
When a registered live probe exposes `allow_production`, its workflow must
expose a manual `allow_production` gate; the input must be manual-only,
boolean, default false, unique by input name, and free of duplicated schema
fields such as `description`, `required`, `type`, or `default`;
`ALLOW_PRODUCTION_INPUT` must derive only from `workflow_dispatch &&
inputs.allow_production || false` inside a real workflow `env:` map rather
than a comment or text block, must not duplicate within that map, and must be
bound on the same registered live probe step that appends the production
override flag; each registered probe command must receive the appended
production-override args array without resetting, unsetting, or redeclaring
that array after the append, including through shell read/mapfile builtins;
`--allow-production` may only be appended inside the explicit
`ALLOW_PRODUCTION_INPUT == "true"` shell guard. The production-override scan
ignores heredoc bodies, including non-identifier delimiter words, so copied
guard text inside generated files cannot stand in for executed shell control
flow, and it does not treat shell here-strings as heredocs.
For registered Python probes, every live guard token must also be a real
`argparse` `add_argument(..., action="store_true")` CLI flag, so comments,
constants, and docstrings cannot spoof probe-side operator acknowledgements.
For registered MJS probes, every live guard token must be enforced through a
top-level fail-closed `process.argv.includes(...)` check, and registry
validation ignores comments, nested unused functions, and template-literal
usage text when proving that guard. The MJS
`fail()` helper must exit with a non-zero literal status so a missing operator
acknowledgement cannot be logged as a successful run.
The probe-level unit contracts also force `settings.environment=production`
and prove each production-aware live probe refuses without `--allow-production`
while accepting the same guard path with the explicit acknowledgement.
Every registered live evidence job must also declare
`environment: wiii-runtime-evidence`, giving maintainers one GitHub
Environment where approvals, environment-scoped secrets, and deployment history
can be configured for runtime evidence collection.
Every registered evidence workflow job must declare `timeout-minutes`, so
stalled live probes and browser replays fail as bounded operational evidence
instead of hanging indefinitely.
Registered evidence workflows must not enable `continue-on-error`; probe,
validator, upload, and contract failures must stop as failed CI evidence rather
than being masked by a later artifact upload.
Registered evidence workflows must also not enable shell xtrace (`set -x`,
`set -o xtrace`, `bash -x`, or `sh -x`) because traced commands can leak
secret-bearing provider and runtime arguments into GitHub Actions logs.
Workflow job IDs must be unique inside the `jobs:` map, so a later duplicate
job cannot override the contract job or guarded live-evidence job that the
validator inspected.
Job-level control fields that determine execution order, gating, environment,
runner, timeout, or steps must not be duplicated, so a later YAML field cannot
override the safe contract dependency or live-run gate the validator inspected.
Registered artifact upload steps must use `if: always()`,
`if-no-files-found: error`, and bounded `retention-days`, preserving failure
evidence for operator handoff when a probe or validator fails after writing a
payload while failing loudly when the expected evidence file is absent. Those
upload fail-safe fields must be non-comment YAML scalars on the real upload
step or its `with:` map, so commented `if: always()` /
`if-no-files-found: error` hints or matching lines inside multiline
`path: |` bodies cannot stand in for real
upload behavior. Upload step fields and upload `with:` fields that control
action identity, failure preservation, retention, and paths must not be
duplicated, so a later YAML field cannot override the safe value the validator
inspected. Each upload path must stay to exactly one explicit repo-relative
JSON evidence file whose basename matches the registered artifact, with no
globs, directory-only paths, expressions, environment-variable or home-directory
expansion, absolute paths, repo escapes, or extra JSON sidecars, so runtime
evidence uploads cannot silently grow into raw logs or workspace snapshots. Every
`actions/upload-artifact` step in a registered evidence workflow must bind one
of that workflow's registered artifact filenames and upload tokens exactly
through real `with:` map fields; a token that only appears inside a multiline
`path: |` scalar is ignored. The registry check derives the allowed upload path
from the job-local artifact validation step, so an extra upload step cannot
reuse a registered token for a different same-basename sidecar. Extra upload
steps outside the registry contract are rejected. Registry artifact tokens must
be unique lowercase kebab-case names ending in `${{ github.run_id }}`, so
uploaded evidence can be traced to one workflow run without mutable aliases.
Every registered evidence workflow must also trigger on PR and push changes
through real top-level `on:` event path filters for its own workflow file,
`tools/wiii_self_harness/**`, its registered probe file, and all registered
contract-test paths, so proof-code drift runs the proof job instead of waiting
for manual dispatch. Copied `push.paths` or `pull_request.paths` blocks under
unrelated YAML maps are ignored. Event filter keys that control paths, ignored
paths, branches, or ignored branches must not be duplicated inside `push` or
`pull_request`, so a later YAML key cannot override the path filters the
validator inspected. `paths-ignore` and `branches-ignore` are rejected on
those events, and explicit `branches` filters must include `main`, so a
workflow cannot keep the required path list while silently skipping proof-code
changes through a narrower event filter.
Registered workflow, probe, and contract-test paths must not contain symlinks,
so registry validation cannot read proof code through a pointer to another
local file.
Runtime evidence bundle audits enforce the same freshness
policy across downloaded artifact directories so old proof cannot be mistaken
for current runtime health. `tools/wiii_self_harness/report_runtime_evidence_coverage.py`
renders the same source of truth as an operator-readable coverage table for
review and incident handoff, including artifact upload tokens, diagnostic
upload counts/artifacts, raw-content absence counts, and identifier-strategy
coverage for every requirement. The report now fails CI
when any registered artifact has fewer payload checks than its freshness window
in hours, turning the evidence-density target into a durable gate instead of a
dashboard convention. Its JSON/Markdown output uses
`wiii.runtime_evidence_coverage_report.v1` as the report-level schema,
separate from each evidence row's payload `schema_version`, and carries the
registry name, integer version, and contract SHA-256 fingerprint used to build
the coverage table. Registry validation failures and coverage-density gate
failures are exposed as `validation_error_codes`, `coverage_error_codes`, and
a top-level `error_codes` union, so handoff automation can route failures
without scraping Markdown text. When invoked with `--out`, the coverage report
refuses to write over the runtime evidence registry contract file or to a
direct/parent symlink or directory output target.
For stricter completion audits, `--require-no-synthetic-gaps` fails the same
report with `coverage_synthetic_external_gap_present` until every external
runtime evidence row is credentialed or local/backend-verifiable rather than
synthetic.
`--require-credentialed-external-contracts` then hardens those credentialed
external rows by requiring env flags, guard tokens, dispatch/schedule gates,
raw-content absence checks, and identifier-strategy checks.
The self-harness report-bundle validator accepts the same flag and fails the
downloaded bundle with `report_coverage_synthetic_external_gap_present` when
the uploaded coverage JSON still reports synthetic external gaps.
It also accepts `--require-credentialed-external-contracts` and reports
`report_coverage_credentialed_external_contract_incomplete` when a bundled
coverage row is missing its external contract proof.
`generate_self_harness_report_bundle.py --require-no-synthetic-gaps
--require-credentialed-external-contracts` uses the same strict validation
before writing self-validation, so a completion-audit bundle cannot include a
stale success report while a synthetic external gap or incomplete external
contract remains.
The central workflow also runs `validate_self_harness_report_bundle.py` as an
explicit strict CLI step and uploads
`artifacts/wiii-self-harness-report-bundle-validation.json`, so operator
handoff has an independent sidecar validation result outside the recursive
in-bundle self-validation file.
It also renders runtime evidence coverage Markdown with
`tools/wiii_self_harness/report_runtime_evidence_coverage.py --format markdown --require-no-synthetic-gaps --require-credentialed-external-contracts`,
so operator-facing coverage output cannot pass under looser evidence rules than
the strict bundle gates.
`tools/wiii_self_harness/validate_runtime_evidence_bundle.py`
validates a downloaded artifact directory against the full registry for release
or incident evidence handoff, emits JSON/Markdown report schema
`wiii.runtime_evidence_bundle_report.v1`, reports the validated registry name
and integer registry version, returns the same schema with `ok: false`,
structured `errors`, normalized `error_codes`, and `error_code_counts` for
early `--format json` CLI failures, revalidates the full runtime evidence registry contract before
reading artifacts, and can take `--self-harness-report-bundle` to first validate
the downloaded self-harness report bundle with required self-validation,
no-synthetic-gap enforcement, and credentialed-external-contract enforcement,
then require its coverage JSON's registry fingerprint, registry version, and
`requirement_count` to match the artifact validation registry. When that link
is present, the runtime evidence bundle report records the self-harness
report-bundle root, bundle fingerprint SHA-256, and validation schema, plus a
`completion_audit_fingerprint_sha256` over the runtime evidence bundle
fingerprint and linked report-bundle fingerprint/schema. Standalone artifact
validation can still report `ok: true`; completion handoff should run with
`--require-completion-audit-link` and require `completion_audit_ready: true` so
an artifact-only pass is not mistaken for a full OpenHuman-style audit.
`generate_completion_audit_handoff.py` packages that strict validation path into
one handoff command, writes top-level `completion-audit-handoff.json` and
`completion-audit-handoff.md` files plus JSON and Markdown runtime evidence
bundle reports, repeats the completion-audit, runtime-bundle, and
self-harness-bundle fingerprints at the top level, can bind optional
`--readiness-report`, `--control-chain-report`, `--setup-gap-report`, and
`--setup-gap-markdown-report` summaries with source SHA-256 values, exposes
`release_handoff_ready` separately from runtime-only `completion_audit_ready`,
adds top-level `runtime_blockers` derived from non-passed runtime rows, and
adds `release_blocker_count` plus `release_blockers` as a deterministic union
of runtime evidence failures, runtime readiness fallback blockers,
control-chain readiness blockers, dispatch readiness blockers, setup-gap
requirement keys, and setup-gap summary blockers for invalid setup-gap
summaries or diagnostic mismatches. Setup-gap blockers carry privacy-safe
`resolution_actions` with category/key, recommended evidence kind, safe
source-handle options, binding token count, and attestation option count.
Runtime-evidence blockers can also carry a readiness-derived
`recovery_action` with workflow, probe, live env flag, live guard,
dispatch/schedule gate, artifact token, preflight `required_next`, and
normalized error-code evidence, so the handoff points to the next auditable
attempt without exposing secrets or raw identifiers. It
rejects output
directories inside either evidence input bundle, existing non-empty output
directories, file targets, direct symlinks, and symlink parents. It then runs
the handoff validator against the generated directory before returning success,
so generator bugs cannot produce an unvalidated operator bundle. The
`--allow-not-ready` flag only changes the CLI exit code after that structural
validation succeeds; it does not mark `release_handoff_ready` true or bypass
the release/control-chain gates.
`validate_completion_audit_handoff.py` validates downloaded handoff bundles by
requiring the exact four reports, strict JSON parsing, top-level fingerprint
parity with the nested runtime report, runtime JSON parity with the nested
report object, exact JSON-derived Markdown documents and runtime artifact table
row parity, control-chain/setup-gap summary schema and bounded setup-key parity,
`release_handoff_ready` recomputation from runtime readiness plus any embedded
control/setup summaries, top-level `runtime_blockers` parity with the nested
runtime rows, `release_blockers` parity with runtime rows, runtime readiness,
embedded readiness/control/setup summaries, readiness-derived recovery actions,
and setup-gap pending-check action metadata,
row `error_codes` provenance from normalized row
`errors`, and no
freshness timestamp contradictions, status/proof contradictions, row path
provenance contradictions, duplicate or empty registered runtime row
identities, or unexpected files. The
`generate_completion_audit_recovery_plan.py` and
`validate_completion_audit_recovery_plan.py` pair turns that handoff into a
machine-readable recovery contract: runtime blockers become
`workflow_probe_recovery` items, setup gaps become per-handle
`setup_resolution` items, and remaining release gates become
`gate_dependency` items. The validator can compare the plan back to the source
handoff with `--handoff-json`, preserving action counts, privacy flags,
`action_items_fingerprint_sha256`, and execution-group dependency fingerprints
so autonomous follow-up cannot silently drift from the audited release
blockers. Execution groups separate operator setup, guarded runtime dispatch,
and final release-gate validation with `ready_for_autonomous_dispatch` and
`blocked_by_external_setup` flags, giving Wiii a deterministic queue boundary
instead of asking an agent to infer order from prose.
`run_completion_audit_recovery_queue.py` and
`validate_completion_audit_recovery_queue.py` make that boundary executable in
dry-run form: the queue report records `queue_state`, per-group status,
dependency-blocked groups, `next_group_ids`, and a
`group_status_fingerprint_sha256`, then validates back to the recovery plan and
handoff source so autonomous follow-up cannot skip external setup or reorder
runtime dispatch before prerequisites are proven.
`generate_completion_audit_recovery_work_order.py` and
`validate_completion_audit_recovery_work_order.py` then expand only the queue's
selected `next_group_ids` into a source-bound work order. The work order marks
operator-owned setup tasks, autonomous-safe runtime recovery tasks, blocked
dependencies, `autonomous_dispatch_allowed`, and
`work_order_fingerprint_sha256`, giving Wiii an auditable handoff from
deterministic planning into either setup evidence collection or guarded
dispatch.
`report_completion_audit_recovery_work_order_status.py` and
`validate_completion_audit_recovery_work_order_status.py` bind that handoff
back to actual setup-state evidence. They classify each selected task as
`satisfied`, `pending`, `blocked_by_missing_setup_state`, or
`ready_for_dispatch`, derive `completed_group_ids` and
`selected_group_complete`, and use `task_status_fingerprint_sha256` so the
system can advance dependencies only from validated setup evidence, not from an
agent's prose claim.
`generate_completion_audit_recovery_queue_progress.py` and
`validate_completion_audit_recovery_queue_progress.py` apply that evidence back
to the recovery queue. They use `completed_group_ids` as the only completion
input, recompute `queue_state`, `next_group_ids`, and group statuses from the
source recovery plan, and fingerprint the result with
`queue_progress_fingerprint_sha256`. This is the transition layer that lets
Wiii move from operator setup into autonomous runtime dispatch without trusting
prompt text or stale queue state.
`generate_completion_audit_recovery_dispatch_authorization.py` and
`validate_completion_audit_recovery_dispatch_authorization.py` add the next
machine-readable gate after queue progress. The authorization artifact is
`wiii.completion_audit_recovery_dispatch_authorization.v1` and records
`authorization_state`, `autonomous_dispatch_allowed`, `authorized_group_ids`,
`blocked_group_ids`, `dispatch_gate_enforced`, `live_command_specs_included`,
per-item live env flags, guard tokens, artifact tokens, preflight requirements,
and `authorization_fingerprint_sha256`. Setup-blocked queues stay
`blocked_by_queue` with no dispatch items; only a ready
`runtime-evidence-dispatch` group can authorize workflow/probe recovery, and an
optional dispatch gate must match the same requirement before unlocked live
command specs are exposed. This gives Wiii a source-bound dispatch decision
between dependency advancement and live execution rather than letting an agent
infer allowed recovery actions from prose.
`run_completion_audit_recovery_dispatch_authorization.py` and
`validate_completion_audit_recovery_dispatch_run.py` then materialize that
decision into a dry-run or explicitly allowed live dispatch report. The run
artifact is `wiii.completion_audit_recovery_dispatch_run.v1` and records
`run_state`, denied items, command rows, execution counts, no raw output flags,
and `recovery_dispatch_run_fingerprint_sha256`. It refuses command
materialization while the authorization is blocked or while a ready
authorization lacks dispatch-gate command specs, and live execution requires
both `--execute` and `--allow-live-dispatch`. This keeps the recovery path
machine-operated without letting an agent jump from "authorized in principle"
to arbitrary shell execution.
`validate_completion_audit_recovery_control_chain.py` closes the recovery
control loop by validating the plan, queue, work order, work-order status,
progress, authorization, and dispatch run as one source-bound chain. It emits
`wiii.completion_audit_recovery_control_chain_validation.v1` with
`chain_state`, `recovery_chain_ready`, `operator_setup_required`,
`autonomous_dispatch_allowed`, group transitions, command count, and
`chain_fingerprint_sha256`. It can pass while
`chain_state=operator_setup_required`, but stale hashes, mismatched
fingerprints, skipped group transitions, or commands materialized from a
blocked queue fail the chain.
`generate_completion_audit_recovery_checkpoint.py` and
`validate_completion_audit_recovery_checkpoint.py` turn that validated chain
into a resumable checkpoint artifact:
`wiii.completion_audit_recovery_checkpoint.v1`. The checkpoint records the
control-chain SHA-256, replayed chain fingerprint, `resume_state`, next group
IDs, blocked/completed/authorized groups, required next inputs, command count,
and false privacy flags for raw output/evidence/secret inclusion. The validator
regenerates the checkpoint from the referenced recovery control-chain and
replays that chain's embedded sources, so a later run cannot resume from a
hand-edited checkpoint or stale control-chain path.
central smoke step runs that validator against its generated smoke handoff
bundle before reporting success, then runs the validator CLI as a separate step
that writes `artifacts/wiii-completion-audit-smoke-validation.json` for upload.
The smoke JSON includes `release_gate_validation`, proving the empty-evidence
handoff is structurally valid but rejected by the completion readiness gate with
`handoff_completion_audit_not_ready`. The smoke assertion also requires the
structural and release-gate validation payloads to expose opposite
`require_completion_audit_ready` values and distinct validation fingerprints.
The same gate now requires `release_handoff_ready: true`, so a runtime-evidence
green handoff cannot pass release while setup-gap/control-chain summaries still
show pending external work.
The same strict gate result is also uploaded as
`artifacts/wiii-completion-audit-smoke-release-gate-validation.json`, giving
operator handoff a standalone machine-readable negative release-gate artifact.
`validate_completion_audit_smoke.py` then validates the smoke summary, the
strict release-gate sidecar, and the structural validation sidecar as one
contract, rejecting mismatched embedded/sidecar validation payloads, wrong
policy modes, non-distinct policy fingerprints, or any drift from the expected
empty-evidence not-ready report.
`report_completion_audit_readiness.py` also renders
`artifacts/wiii-completion-audit-readiness-non-lms.json` from the same runtime
evidence bundle with `--exclude-requirement-id lms-test-course-replay`, so
operators can track current non-LMS progress without weakening
`completion_audit_ready`. The report exposes both full and scoped readiness,
their missing/failed requirement IDs, blocker lists, and the linked self-harness
bundle fingerprint/schema. With `--preflight-dir`, it also carries
privacy-safe preflight summaries from known live-evidence setup probes and
links them to matching scoped next actions after validating the raw preflight
JSON with `validate_runtime_evidence_preflight.py`. Downstream readiness
validators can repeat `--preflight-dir` or `--readiness-preflight-dir` so
runtime-evidence artifacts and separately uploaded setup-preflight files remain
source-bound without staging copies. Without `--preflight-dir`,
the reporter may use a validator-clean embedded `preflight` or
`preflight_summary` from the registered failure artifact for the same
requirement as setup context only; it still leaves the runtime evidence row
failed. Its `scoped_next_actions`
for included missing/failed requirements include the registry workflow, probe,
dispatch/schedule gate, live guard, expected artifact token, current error-code
evidence, and any matching preflight status plus `required_next` hints needed
for the next run. The report also carries `preflight_summary_count`,
`preflight_summaries`, each preflight source SHA-256, validation schema,
validation `ok` flag, validation error codes, `scoped_next_action_count` and
`scoped_next_actions_fingerprint_sha256`, a canonical SHA-256 digest of the
readiness report schema plus action list. `validate_completion_audit_readiness.py` gates that artifact for
schema, count/list, scope, blocker, next-action count/fingerprint, preflight
summary/next-action parity, optional raw preflight source SHA-256/source-payload
parity when `--preflight-dir` is supplied, including embedded
`artifact.json#preflight` and `artifact.json#preflight_summary` sources,
error-code, and link-field consistency; release gates still use the full
completion-audit validator.
`generate_completion_audit_run_plan.py` consumes that validated readiness JSON
and emits a closed-schema operator run plan for the remaining scoped blockers.
Its `--preflight-dir` option may be repeated, because it validates readiness
source parity before emitting the plan.
The plan keeps workflow-dispatch inputs, schedule env flags, live probe env
flags, live guard tokens, artifact tokens, preflight source SHA-256, and
source-validation state bound to each requirement, then translates
`required_next` into explicit operator setup categories without storing secrets
or raw identifiers. `validate_completion_audit_run_plan.py` recomputes the
run-item fingerprint from the run-plan schema, readiness schema,
`scoped_next_actions` fingerprint, and run-item payload. Its setup,
acceptance, and structured verification-spec fingerprints are also
schema-bound, and source validation can check the plan against the source
readiness report SHA-256, so the operator handoff cannot drift from the audited
blocker list.
`generate_completion_audit_launch_pack.py` takes the run plan one step closer
to execution by emitting command templates for supported live blockers:
workflow dispatch, local preflight, preflight validation, local
failure-from-preflight materialization, local live probe, artifact validation,
and artifact download. For the current non-LMS blockers it
binds those templates to `autonomy-proactive-channel` and
`wiii-connect-composio-acceptance`, listing only GitHub input, variable, secret,
and environment names. The failure materialization command is a structured
`uses_shell=false` argv spec that must bind `--failure-preflight-json` to the
local preflight output and `--out` to the registered failed-evidence artifact,
so setup diagnostics cannot drift from the validated preflight source.
`validate_completion_audit_launch_pack.py` checks the
closed schema, privacy flags, command coverage, launch-item fingerprint, setup
fingerprint, acceptance fingerprint, command-spec fingerprint, post-launch
verification-spec fingerprint, and optional source run-plan SHA-256 parity.
Those launch fingerprints are schema-bound and source-bound to the matching
run-plan fingerprints. With `--repo-root`, it also verifies that referenced
workflow/probe files exist and that the workflow source still contains the
declared input, variable, secret, artifact, and conditional-secret tokens.
The canonical run-plan and launch-pack verification specs then regenerate the
setup-state and dispatch-gate artifacts from the validated launch pack, so live
dispatch can only be unlocked by the same source-bound setup chain that
operators receive in the handoff.
`generate_completion_audit_setup_state.py` then converts the launch-pack
binding map into a privacy-safe setup-state JSON template. With `--repo-root`,
it marks only workflow-input handles proven by the source-controlled launch
command contract. Environment flags, credential slots, approved recipients,
backend connectivity, and connected provider accounts remain pending until
separate live setup evidence supplies them.
`validate_completion_audit_setup_state.py` checks that state against the
launch-pack source when `--launch-pack` is supplied. The setup state can remain
valid while `dispatch_ready=false`; operator or CI automation marks individual
checks present only with safe source handles from the binding tokens, not raw
secret values, backend URLs, recipient IDs, or provider account identifiers.
`generate_completion_audit_setup_handle_plan.py` converts the pending checks
into a source-bound handle plan listing safe recommended
`requirement_id:category:key=source_handle` specs plus matching
`requirement_id:category:key=source_handle@evidence_kind:evidence_ref`
attestation specs, and `validate_completion_audit_setup_handle_plan.py`
validates that handoff against the setup-state fingerprint, allowlisted
evidence kinds, and per-token attestation coverage before any patch is
generated.
`report_completion_audit_setup_gaps.py` renders those pending handles as
`wiii.completion_audit_setup_gap_report.v1` and can merge failed proactive,
LMS test-course, or Composio runtime-evidence diagnostics from
`--runtime-evidence-dir` or direct `--proactive-channel-evidence`,
`--lms-test-course-evidence`, and `--composio-acceptance-evidence` paths. The
report emits only counts, source-handle options, artifact hashes,
`required_next` labels, and mapped setup keys; if a failed preflight still
requires a setup key that the setup-state marks present, it sets
`setup_diagnostics_consistent=false` and lists
`diagnostic_present_setup_mismatches`. That artifact gives CI/operators a
machine-readable stale-run or miswired-dispatch diagnosis without treating
diagnostics as setup proof or unlocking live dispatch.
It also splits pending checks into
`diagnostic_pending_setup_check_count` and
`non_diagnostic_pending_setup_check_count`, keeping the current preflight
blocker distinct from remaining setup-contract attestations. Per-requirement
`diagnostic_pending_setup_keys` and `non_diagnostic_pending_setup_keys` use only
bounded `category:key` labels, so operators can inspect the handoff without raw
identifiers or credential values.
`validate_completion_audit_control_chain.py --setup-gap-report` binds that
diagnostic report back to the exact setup-handle plan SHA-256 and requires its
privacy flags to stay false, so source drift or hand-edited setup-gap reports
cannot pass the control-chain gate.
`validate_completion_audit_setup_gaps.py` is the standalone setup-gap gate:
it checks the closed schema, summary counts, report fingerprint, mapped
`required_next` parity, mismatch counts, privacy flags, and optional
`--setup-handle-plan` source parity before the artifact is used by CI or
operator handoff. With `--markdown-report`, it also checks that the
operator-facing Markdown report matches the JSON summary and per-requirement
lines; `validate_completion_audit_control_chain.py` accepts the same Markdown
artifact through `--setup-gap-markdown-report`.
`generate_completion_audit_setup_attestation_template.py` creates the
operator-facing pending template from that plan. It carries only safe
source-handle and attestation-spec options, keeps
`selected_attestation_spec` and `operator_evidence_ref_handle` empty, and
`validate_completion_audit_setup_attestation_template.py` rejects preselected
evidence, raw identifiers, or source-plan drift. This gives operators a
machine-checkable setup handoff without treating the template itself as live
setup proof.
`generate_completion_audit_setup_attestation_from_template.py` is the next
bounded step after an operator chooses safe template options: every repeated
`--select` must match an attestation spec from the template, duplicate choices
for one setup check are rejected, and `--require-all-pending` can require one
selection for every pending check before producing the strict attestation and
optional patch artifacts.
`smoke_completion_audit_setup_attestation.py` exercises the same handoff as a
CI sidecar: it selects one safe template option per pending setup check,
generates the strict attestation, applies it to a copied setup state, emits an
attested dispatch gate, and materializes dispatch commands in dry-run mode
only. This proves the operator-template unlock mechanism stays intact without
turning a smoke-selected artifact into live setup proof; the production
non-LMS setup state, dispatch gate, dispatch run, and control chain still
remain fail-closed until real credentialed/external setup evidence is supplied.
`validate_completion_audit_setup_attestation_smoke.py` revalidates that smoke
sidecar against the template, original setup state, generated attestation,
derived patch, attested setup state, dispatch gate, and dispatch-run report, so
the mechanism check is independently source-bound.
`generate_completion_audit_setup_handle_patch.py` creates that patch from
repeated `requirement_id:category:key=source_handle` handles and binds it to
the current setup-state SHA-256/schema/fingerprint, so operators do not have to
write the patch JSON by hand.
`generate_completion_audit_setup_attestation.py` is the stricter live-setup
path: each repeated `--attest` binds a setup handle to an allowlisted evidence
kind and safe evidence reference using
`requirement_id:category:key=source_handle@evidence_kind:evidence_ref`. It can
also emit the matching setup-handle patch with `--patch-out`, and
`validate_completion_audit_setup_attestation.py` verifies that the attestation,
patch, and current setup-state source all match before the patch is applied.
This keeps credential slots, approved recipients, backend readiness, and
connected-provider setup evidence machine-checkable without storing secret
values or raw external identifiers in generated control-plane artifacts.
`generate_completion_audit_setup_attestation_from_handles.py` is the
automation-friendly variant: it consumes a closed-schema
`wiii.completion_audit_setup_handle_evidence.v1` file bound to the current
setup-handle plan SHA-256/fingerprint and setup-state source, then emits the
same attestation plus optional patch. It only accepts handles for pending setup
checks when the source handle matches a binding token and the evidence kind
matches the plan recommendation, so CI can draft setup attestations from safe
proof handles without reading credential values or raw external identifiers.
`probe_completion_audit_setup_handle_evidence.py` can produce that evidence
file from local CI/runtime environment presence after explicit
`--allow-env-read`. It supports truthy environment-flag proof,
secret-present, variable-present, approved-recipient, and backend-health
handles, writes only source handles and evidence refs, and requires
`--allow-network` before checking backend health.
It can also consume a sanitized
`wiii-connect-composio-acceptance-evidence.json` pass artifact through
`--composio-acceptance-evidence` to prove only the Composio connected-provider,
execution-gateway policy, and read-only schema handles. The probe requires the
artifact to be a registered pass artifact with passing check statuses, safe
privacy flags, and read-only scope/schema proof; failure and preflight-only
artifacts produce no handles. Composio-derived evidence refs include the
acceptance artifact SHA-256 and still omit provider account IDs, connection
refs, backend URLs, provider arguments, provider responses, and raw schemas.
It can also consume a sanitized `autonomy-proactive-channel-evidence.json`
pass artifact through `--proactive-channel-evidence` to prove only the
proactive runtime channel credential, approved-recipient, and selected-channel
handles. That path requires delivered live-send proof, operator approval
acknowledgement, recipient hash presence, configured channel/credential proof,
database guardrail scope, delivered metrics, and false raw-identifier/raw-
payload privacy flags. Failure and preflight-only artifacts produce no handles;
proactive-derived evidence refs include the artifact SHA-256 and still omit raw
recipient IDs, organization IDs, message text, credential values, delivery
payloads, and metric payloads.
For normal post-run operation, pass the downloaded runtime evidence bundle with
`--runtime-evidence-dir <bundle-dir>` instead of naming each artifact. The probe
only inspects the canonical `autonomy-proactive-channel-evidence.json` and
`wiii-connect-composio-acceptance-evidence.json` files from that directory,
including standard downloaded-artifact subdirectories. Duplicate canonical
matches and symlinked artifact paths fail closed; the explicit artifact flags
remain available when a caller needs to bind a single known file. Missing,
failed, preflight-only, or schema-drifted bundle artifacts still produce no
setup handles. In the generated post-run chain,
`validate_runtime_evidence_bundle.py` first writes
`<runtime-evidence-bundle-report-json>`, and the setup-handle probe receives
that report through `--runtime-evidence-bundle-report`; canonical artifacts
must have passed bundle rows with matching SHA-256 before they can contribute
setup handles.
`promote_completion_audit_runtime_evidence.py` wraps that post-run promotion
path for repeatable CI/operator use: it requires the validated bundle report to
be `ok=true` and `completion_audit_ready=true`, probes setup handles from the
bundle with matching row SHA-256, writes setup-handle evidence, generates and
applies the setup attestation, emits an attested dispatch gate, and materializes
a dry-run dispatch report. It never executes live dispatch; incomplete bundle
reports, missing handles, stale sources, or still-pending setup produce
`wiii.completion_audit_runtime_evidence_promotion.v1` with `promotion_ready=false`.
Generated run plans and launch packs include a source-bound sidecar path that
uses this bundle probe to write `<setup-handle-evidence-json>`, generate
`<setup-attestation-json>`, apply it into `<setup-state-attested-json>`, and
materialize `<dispatch-gate-attested-json>` / `<dispatch-run-attested-json>` in
dry-run. The canonical pending setup-state and control-chain reports remain
available, so partial evidence produces an explicit pending sidecar report
rather than silently unlocking live dispatch.
It fails closed with no usable handles rather than marking setup ready from
absence of evidence.
`apply_completion_audit_setup_attestation.py` applies that stricter artifact
directly: it validates the attestation against the current setup-state and
optional launch-pack source, derives the setup-handle patch internally, reuses
the canonical setup-state applier, and emits a normal setup-state artifact.
CI or operators therefore do not need to persist a separate hand-managed patch
file, while stale attestation sources, raw evidence references, unbound handles,
secrets, backend URLs, recipients, provider account IDs, and provider payloads
still fail before live dispatch can unlock.
`apply_completion_audit_setup_state.py` provides the source-bound apply path
for that handoff: it consumes a closed-schema
`wiii.completion_audit_setup_handle_patch.v1` patch, rejects unbound or raw
handles, requires the patch's setup-state SHA-256/schema/fingerprint to match
the current source setup-state, recomputes the setup-state fingerprint and
counts, and emits a normal setup-state artifact for downstream validation.
`validate_completion_audit_setup_handle_patch.py` exposes those same checks as
a standalone preflight, so CI can reject stale or unbound setup-handle patches
before any setup-state artifact is rewritten.
`generate_completion_audit_dispatch_gate.py` consumes that setup state plus the
launch pack and emits the final fail-closed live-dispatch gate:
`unlocked_live_command_specs` stays empty while setup is pending and is filled
only from source launch-pack command specs after every setup check is present.
While setup is pending, the gate may still carry
`blocked_diagnostic_command_specs.local_failure_from_preflight`, sourced from
the launch pack, so a failed diagnostic artifact can be materialized without
unlocking workflow dispatch or live probe commands.
`validate_completion_audit_dispatch_gate.py` then checks the gate against both
`--launch-pack` and `--setup-state`, so live dispatch cannot be unlocked by
editing a generated gate artifact or by inserting raw setup values.
`run_completion_audit_dispatch_gate.py` is the final fail-closed materializer:
it validates source parity first, emits an `ok=false` dispatch-run report while
the gate is not ready, keeps live `commands` empty, and may include unexecuted
`diagnostic_commands` copied from
`blocked_diagnostic_command_specs.local_failure_from_preflight` so operators can
write the failed registered diagnostic from the validated preflight source
without unlocking workflow dispatch or local live probes. It only materializes
or executes allowlisted no-shell live argv after the gate is ready. Live
execution requires the explicit `--execute --allow-live-dispatch` pair, and the
resulting report excludes raw stdout, stderr, secrets, credentials, and
recipient/backend identifiers.
`validate_completion_audit_dispatch_run.py` validates that report independently
and can regenerate the dry-run report from the current dispatch gate plus
launch/setup sources, so a stale or hand-edited dispatch-run artifact cannot be
used as the final live-dispatch proof, and a ready report cannot keep blocked
diagnostic commands.
`run_completion_audit_dispatch_diagnostics.py` then gives operators and CI a
separate non-live path for those pending diagnostics: it consumes the validated
dispatch-run report, refuses ready dispatch reports, dry-runs by default, and
can bind the launch-pack `preflight_source_file` entries with
`--preflight-source-dir <dir>`. Execution requires
`--execute --allow-diagnostic-execution --preflight-source-dir <dir>`; before
running a diagnostic command it finds the source preflight, verifies the source
SHA-256 from the launch pack, extracts embedded `#preflight` or
`#preflight_summary` payloads when needed, validates the closed preflight
schema, stages only that validated JSON into the probe working directory, and
rebinds placeholder argv values to parse-safe diagnostic values from that
preflight contract before execution. A probe's intentional
`--failure-from-preflight` failure exit is accepted only when the failed
registered output artifact exists, hashes cleanly, and embeds a preflight that
still validates; otherwise the diagnostic command is counted as failed. The
report records `preflight_stages`, `argv_rebound`,
`unresolved_placeholder_count`, `output_artifact_sha256`, and
`output_artifact_validated` without raw payloads. Its companion validator
regenerates the dry-run from the dispatch-run source and the same optional
source directory, so diagnostic artifact materialization remains source-bound
and cannot be mistaken for a live dispatch unlock, unstaged local file, or
operator-side placeholder substitution.
`validate_completion_audit_control_chain.py` then validates the whole
readiness-to-dispatch chain in one pass, including readiness, run-plan,
launch-pack, setup-state, setup-handle plan, dispatch-gate, dispatch-run,
optional setup-attestation template/smoke, optional dispatch-diagnostics source
links, optional `--recovery-control-chain`, and optional
`--recovery-checkpoint`. When
`--setup-attestation-smoke` is supplied with its template and
out-dir, the chain validator reuses the smoke validator to re-check the
generated strict attestation, patch, attested setup-state, attested dispatch
gate, and dry-run dispatch report. The same generated reports, or real
operator-produced equivalents, can also be supplied directly with
`--setup-attestation`, `--setup-attestation-patch`,
`--attested-setup-state`, `--attested-dispatch-gate`, and
`--attested-dispatch-run`; in that mode the control-chain requires the
attested setup-state/gate/run to be dispatch-ready and the attested dispatch
run to be `ok=true`. When `--dispatch-diagnostics` is supplied, the chain
validator reuses the dispatch diagnostics validator against the same
dispatch-run, launch-pack, setup-state, and optional
`--diagnostics-preflight-source-dir` inputs, then checks command counts,
dispatch-run fingerprint, and SHA-256 linkage. When
`--recovery-control-chain` is supplied, the validator replays that recovery
report from its embedded source paths, compares replayed state/fingerprint
fields, exposes recovery readiness fields, and requires
`release_gate_ready=true` before aggregate `control_chain_ready` can become true.
When `--recovery-checkpoint` is supplied, the validator also binds the resume
checkpoint to that same recovery chain and exposes the aggregate
`recovery_resume_state` and `recovery_required_resume_inputs`, so operators can
resume from a machine-checked boundary rather than a detached checkpoint. The
aggregate validator can write that machine-readable report with `--out`, and
rejects directory, direct-symlink, and parent-symlink report targets before
writing. Its repeated
`--readiness-preflight-dir` inputs let the same check validate readiness
preflight source hashes across mixed runtime-evidence and setup-preflight
artifact directories. This gives CI and operators a single end-to-end check
that the chain is structurally valid while still not ready, rather than a pile
of individually valid artifacts that could be mixed from different runs.
The completion-audit validators should also write and upload `--out`
validation sidecars for each smoke, readiness, run-plan, launch-pack,
setup-state, setup-handle, setup-gap, setup-attestation, dispatch, and recovery
boundary before the aggregate report, preserving inspectable proof without
relying on CI stdout logs.
Each completion-audit validator must route its sidecar write through
`safe_report_output.safe_write_report_text`, so directory, direct-symlink, and
parent-symlink report targets are rejected before any parent directory creation
or UTF-8 write.
Completion-audit artifact writers use the same helper for `--out` and
`--patch-out` artifacts after their domain-specific validation, removing raw
per-script `Path.write_text(...)` report-output paths from the control chain.
The smoke sidecar outputs are rejected if they would be written inside the
generated handoff bundle, the runtime-evidence input bundle, or the self-harness
report input bundle, including resolved symlink targets, and duplicate sidecar
paths are rejected before generation, so smoke reporting cannot mutate the
evidence set after structural validation has already read it.
The validator's default mode accepts structurally valid not-ready smoke bundles;
release gates should add `--require-completion-audit-ready`, which fails with
`handoff_completion_audit_not_ready` unless the handoff proves
`completion_audit_ready: true`; that policy mode is included in the validation
bundle fingerprint, keeping structural validation fingerprints distinct from
release-gate fingerprints even when both modes pass.
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
`rows`, and `error_code_counts` must use positive counts with keys matching the
unique `error_codes` list. It also requires the complete canonical runtime
bundle schema, including registry name/version, normalized UTC `validated_at`,
bundle roots, self-harness validation schema, and required SHA-256
fingerprints. Handoff validation also requires canonical runtime row fields,
recomputes `bundle_fingerprint_sha256` from the row manifest, recomputes
`completion_audit_fingerprint_sha256` from the runtime bundle and self-harness
report bundle manifest, requires handoff roots to match runtime report roots,
requires `ok` and `completion_audit_ready` to match row status plus
self-harness link readiness, and recomputes `passed_count`, `missing_count`,
`failed_count`, `unexpected_count`, and `error_code_counts` from row
status/error-code data. The row manifest fingerprint includes runtime report
`schema_version`, `validated_at`, each row's reported `age_hours`, each row's
`errors`, and normalized `error_codes`, so a forged summary cannot pass by only
editing the schema contract, freshness decision point, rendered freshness age,
operator-facing failure details, top-level counters, copied fingerprints, or
readiness booleans.
It reports each artifact's SHA-256 digest, emits a registry contract SHA-256 fingerprint plus
bundle-level SHA-256 fingerprint over the canonical artifact manifest,
including relative artifact paths and normalized error codes, records the
normalized UTC `validated_at` timestamp used for freshness decisions, exposes
the same normalized error codes plus bundle-level `error_codes` and
`error_code_counts` in
JSON/Markdown reports for operator triage, and
rejects symlinked bundle roots, symlinked artifacts, or resolved paths outside
the bundle before reading JSON.
It also applies the same safe artifact-name rule before filesystem matching, so
a custom registry cannot turn release handoff validation into a glob-pattern
search, and rejects duplicate requirement IDs or artifact names before reading
files. Non-object requirement entries become failed bundle rows rather than
being skipped, and unregistered non-directory bundle entries, including
non-JSON raw-log sidecars, become failed rows.
The bundle report also exposes `unexpected_count` for quick handoff triage,
keeps `requirement_count` tied to registry requirements, and uses `row_count`
for the full handoff table including extra failed rows. Valid local unexpected
files also receive SHA-256 digests and participate in the bundle fingerprint,
while symlinked or escaping unexpected entries report path errors instead of
being hashed. Duplicate artifact matches receive a manifest digest
over relative duplicate paths, valid per-file hashes, and path errors, so
duplicate evidence also affects the bundle fingerprint without following unsafe
links. Markdown bundle output collapses table-cell line breaks and tab spacing
so operator handoff tables stay readable. CLI `--registry` and `--out` sidecar
paths, including direct symlink locations, symlink parents, and resolved targets, must stay outside the
bundle root so registry input and report generation cannot pollute the evidence
directory with unregistered files; `--out` also rejects direct/parent symlink
and directory targets so JSON failure reporting does not collapse into
filesystem redirects or errors.
Core self-harness report-output CLIs route their final `--out` writes through
`safe_report_output.safe_write_report_text` after their domain-specific
manifest/registry/bundle checks, giving the control plane one shared write-time
guard for directory, direct-symlink, and parent-symlink report targets.
The same centralization is enforced across non-test self-harness Python modules:
only `safe_report_output.py` may call `Path.write_text(...)` directly, so future
runtime-evidence, completion-audit, or report-bundle tools cannot add a raw
write path outside the shared guard. The helper writes through a same-directory
temporary file plus atomic replace after flush/fsync, so control-plane artifacts
are either the previous complete report or the new complete report.
The registry currently covers
`provider-runtime-evidence.json`,
`subagent-boundary-evidence.json`, `autonomy-scheduler-evidence.json`,
`autonomy-heartbeat-evidence.json`,
`autonomy-proactive-channel-evidence.json`, and
`lms-test-course-evidence.json`, and
`semantic-memory-write-evidence.json`, and
`wiii-connect-action-evidence.json`, and
`wiii-connect-facebook-post-replay-evidence.json`, and
`wiii-connect-composio-acceptance-evidence.json`, and
`runtime-flow-browser-replay-summary.json`, with schemas
`wiii.live_provider_runtime_probe.v1`,
`wiii.live_subagent_boundary_replay.v1`,
`wiii.live_scheduler_replay_probe.v1`,
`wiii.live_heartbeat_cycle_probe.v1`,
`wiii.live_proactive_channel_probe.v1`, and
`wiii.live_lms_test_course_replay.v1`,
`wiii.live_semantic_memory_write_doctor.v1`, and
`wiii.live_wiii_connect_action_replay.v1`, and
`wiii.live_wiii_connect_facebook_post_replay.v1`, and
`wiii.live_wiii_connect_composio_acceptance.v1`, and
`wiii.runtime_flow_browser_replay_summary.v1`. It fails closed when a registered
workflow loses `contents: read`, artifact upload, schema validation, live env
flag, guard flag, dispatch/schedule gate, unique JSON artifact name, or
introduces `pull_request_target`. Artifact names must stay safe lowercase
kebab-case JSON file names, so bundle validation cannot be widened by glob
pattern metacharacters.
Live Python evidence probes share `scripts/runtime_evidence_output.py`, support
`--out <artifact>.json`, and write UTF-8 JSON through the shared helper, so
Windows PowerShell redirection cannot turn runtime evidence into UTF-16 files
that fail release validation. The shared helper rejects direct symlink, parent
symlink, and directory output targets, then writes through a same-directory
temporary file, flushes/fsyncs it, and atomically replaces the target. Registry
validation also reads the helper next to registered Python probes and fails if
the atomic temp-file primitives are removed; it also requires the workflow
contract job and path filters to include the Python runtime evidence output
helper test. Registry validation requires
registered Python probes to define `--out` as an actual
`argparse.add_argument(...)` CLI flag and to import `emit_json_payload` from
that helper, so a local function with the same name cannot bypass the shared
output guard. It also requires an `emit_json_payload(..., out_path)` call, so a
probe cannot merely mention `--out` while silently writing evidence through a
side channel. Registered Python probes are also forbidden from direct evidence
file writes such as `write_text`, write-mode `open`, aliased `json.dump`,
imported `dump`, aliased `io.open`/`codecs.open`/`builtins.open`, and low-level
`os.open`/`os.write`, with literal or constant write modes both rejected,
keeping evidence emission behind the shared guard.
Registry validation also requires
registered MJS evidence wrappers to parse `--out` from `process.argv` and
assign the same returned output property from both `--out <path>` and
`--out=<path>` branches before forwarding that parsed path into
`WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_JSON`; their workflow command must
pass the exact registered artifact path on the `node ...probe...` invocation
and the parsed summary env binding must live inside the
`spawnSync(process.execPath, [runner, ...forwarded], ...)` runner options before
the wrapper reaches the shared `runtime-evidence-output.mjs` writer, which
rejects direct symlink, parent symlink, and directory output targets, then
writes through a same-directory temporary file, fsyncs it, and atomically
renames it into place. Registry validation reads the sibling
`runtime-evidence-output.mjs` helper and fails if its atomic temp-file
primitives are removed; it also requires the workflow contract job and path
filters to include `test-runtime-evidence-output.mjs`. Registered MJS probes are also forbidden from raw `node:fs`
and `node:fs/promises` evidence writes such as `writeFileSync`,
`fs.writeFileSync`, `fs.promises.writeFile`, or aliased `writeFile` imports
from `node:fs/promises`, including destructured dynamic-import aliases from
`await import("node:fs")` or `await import("node:fs/promises")`, plus
destructured `require("node:fs")` or `require("node:fs/promises")` aliases,
and default-export aliases such as `fs.default[writer](...)` or
`fsDefault[writer](...)`; destructured aliases with default initializers such
as `writeFileSync: writer = null` are rejected the same way; destructured
`promises` namespaces from `node:fs`, such as
`const { promises: fsPromises } = require("node:fs")`, are also rejected when
they call `writeFile`/`appendFile` directly or through a computed writer; inline
module expressions such as `require("node:fs")[writer](...)` or
`(await import("node:fs/promises"))[writer](...)` are rejected as well, so
dot, bracket, and optional-chain property calls such as `fs.writeFileSync(...)`,
`fs["writeFileSync"](...)`, `fs[writer](...)`, and
`fs[promisesBucket][writer](...)`, including `fs?.[writer](...)` and
`fs?.[promisesBucket]?.[writer](...)`, are rejected when the computed property
is a literal string or string constant. Dynamic `import(...)` and
`require(...)` module specifiers are also rejected when `node:fs` or
`node:fs/promises` is hidden behind a string constant, including simple
concatenated constants such as `"node:" + "fs"` or `"write" + "FileSync"`, so
browser replay JSON cannot bypass the shared output guard through a JavaScript
side channel.

## Debugging Protocol

When Wiii feels "bad", classify the symptom before changing code:

| Symptom | Start here | First proof to collect |
|---|---|---|
| Public site is down | release/deploy flow | VM status, deploy run, `/api/v1/health/live` |
| Chat is silent or slow | chat stream flow | SSE event sequence and provider/tool latency |
| Answer ignores uploaded document | document/RAG flow | document context payload, source refs, route decision |
| LMS content mutates unsafely | host mutation flow | host action preview event, audit row, approval token handling |
| Visual appears as raw payload | visual flow | `visual_open/commit` events and frontend renderer state |
| Code Studio opens wrong surface | Code Studio flow | tool-round outcome and requested preview/code view |
| Pointy clicks at the wrong time | Pointy/host control flow | mode/capability decision and host action audit |
| User/org looks wrong | auth/org flow | auth context, org middleware, persisted frontend state |
| Memory feels incoherent | Living/Data flow | memory write/read path and post-turn hooks |
| Proactive reminder or scheduled agent task is missing | Proactive scheduled task flow | `runtime.scheduled_tasks.*`, scheduler repository logs, notification delivery status |
| Living heartbeat stopped reflecting, journaling, or briefing | Living heartbeat flow | `runtime.living_agent.heartbeat.*`, heartbeat audit rows, approval queue status |
| Proactive outbound message did not arrive | Proactive outreach flow | `runtime.living_agent.proactive.*`, opt-out guardrail reason, channel delivery status |

The expected loop is:

1. Reproduce with the smallest real surface.
2. Identify the runtime flow and layer.
3. Collect the nearest signal from the monitoring ladder.
4. Form one hypothesis about the missing or wrong signal.
5. Patch the narrow contract, then add a test or harness scenario.

## Harness Relationship

Wiii currently has four harness levels:

| Harness | Purpose | What it proves | What it does not prove |
|---|---|---|---|
| Wiii Self-Harness | static contract manifest | critical evidence files and tokens still exist | runtime behavior works |
| Understand-Anything Trial | source inventory and dependency graph | codebase size, dependency hubs, semantic batches, and scan pollution | runtime behavior, LMS safety, or product acceptance |
| Understand-Anything Flow Map Wrapper | scoped deterministic scan/import-map profiles | selected flow files, support files, import-map stats, and dependency hotspots | runtime behavior, LMS safety, or product acceptance |
| Local E2E Harness | browser/bootstrap smoke | local app can authenticate and reach chat UI | LMS production acceptance works |
| Production Smoke | deployed release smoke | public health, embed, Pointy, structured visual SSE | deep document/LMS apply flow works |

The runtime flow ledger now exists as the first compact per-turn record for
request ID, session ID, route decision, provider/tool calls, SSE lifecycle,
host-action IDs, source refs, context provenance, and finalization status. The
runtime acceptance harness now includes backend source-backed LMS document
preview replay, semantic memory-turn replay, backend visual/Code Studio stream
replay, and Pointy/host/visual/code no-action suppression in the casual chat
replay. Its evidence JSON now includes a `browser_replay` section with terminal
`runtime_flow_ledger` and `runtime_flow_trace` assistant metadata for each
scenario; raw prompts, raw answers, and SSE event payloads are excluded, and
answer evidence is reduced to hash/length. This gives the browser Runtime-tab
acceptance lane a real backend-export shape to consume instead of hand-copying
mock ledger fixtures. Playwright now seeds a desktop conversation from that
`wiii.runtime_flow_browser_replay.v1` shape and verifies the Runtime tab renders
the ledger/trace while keeping raw prompt/answer text absent. The desktop
script `npm run test:e2e:runtime-ledger:browser-replay` closes the local/staging
loop by running `wiii_runtime_flow_acceptance.py --evidence-json` first, then
passing the generated JSON path through `WIII_RUNTIME_FLOW_BROWSER_REPLAY_JSON`
so the browser test consumes the exact backend artifact. That backend replay
export now uses the shared `emit_json_payload` helper, so the artifact is UTF-8
JSON and direct symlink, parent symlink, and directory output targets are
rejected before the browser lane can consume redirected evidence. For one-command local
evidence, `npm run test:e2e:runtime-ledger:browser-replay:local` starts a
disposable dev backend when none is healthy, runs the same exact-file replay,
and cleans up the backend process tree it started. The browser replay loader
also rejects raw prompt, raw answer, raw SSE event payload, and token-like
values before seeding local storage, so staging artifacts cannot accidentally
become a private-data replay fixture. A disposable local backend run has passed
this exact-file loop end to end; the runner invokes Playwright without a shell
through the local `@playwright/test` CLI, so grep arguments remain exact and
command arguments are not shell-concatenated. On success it writes
`wiii.runtime_flow_browser_replay_summary.v1`, a hash/count-only summary with
exact evidence-file replay proof, evidence SHA-256, case counts, doctor counts,
safe sync-parity pass counts, backend route-path counts, case/event hashes,
per-case raw prompt/answer/SSE/assistant-content absence flags, route-reason
hash presence, visual/Code Studio lifecycle case counts, finalization
saved/error counts, post-turn lifecycle schema/privacy/hash counts, every
browser-validated, backend-finalized, and post-turn lifecycle case hash, and
terminal ledger facts
suitable for staging archive without raw prompt, answer, route reason, or SSE
payload content. The
same replay now covers the deterministic visual fast-path with terminal
`runtime_flow_trace` and the Code Studio app lane after route precedence rejects
providerless Wiii Connect and domain-search false positives for app/simulation
creation turns. The
runner also stores timestamped summary copies in a retained archive directory
and maintains `wiii.runtime_flow_browser_replay_summary_archive.v1` index
metadata so operators can compare recent staging replays without storing raw
turn payloads; `WIII_RUNTIME_FLOW_BROWSER_REPLAY_SUMMARY_ARCHIVE_LIMIT`
defaults to 25 and `0` disables archival.
`.github/workflows/runtime-ledger-browser-replay-evidence.yml` wraps this path
with `WIII_RUNTIME_LEDGER_BROWSER_REPLAY_EVIDENCE=1 --allow-run`, validates the
summary through the Runtime Evidence Registry, and uploads
`runtime-flow-browser-replay-summary.json` when `run_browser_replay=true` or
`WIII_RUNTIME_LEDGER_BROWSER_REPLAY_EVIDENCE_ENABLED=1`. The registry uses
list-wide payload checks for `browser_replay.cases.*`, so every replay case must
carry valid ledger/trace schemas, prompt-hash evidence, route-reason hash
evidence, event-name hash evidence, per-case raw-payload absence flags, and no
apply attempt before the summary artifact can pass. It also
requires every replay case to report saved backend finalization, zero
finalization errors, and finalized case hashes matching the declared case
count, so the Runtime-tab replay cannot pass on turns that rendered but were
not durably finalized. It also requires every replay case to carry
`wiii.post_turn_lifecycle.v1` status-only finalization evidence with
`privacy.raw_content_included=false`, `identifier_strategy=status_only`, a
boolean background scheduling flag, no raw turn-scope keys, and lifecycle case
hashes matching the declared case count. It also
requires at least three safe sync-parity checks to pass in the same backend
acceptance run, so the artifact proves `/chat` and `/chat/stream/v3` parity for
safe replay lanes rather than only stream-side rendering. It also
requires aggregate route counts for `lms_document_preview`,
`external_connection_status`, `external_app_action`, and `visual_generation`,
plus at least one source/document/preview case and at least one complete visual
and Code Studio lifecycle case. The same artifact now carries
`wiii_connect_capability`, a snapshot-derived hash/count summary for connection
counts, connected-provider/scope hash lists, per-path readiness counts, and
path reason hashes from `/api/v1/wiii-connect/snapshot`; the registry requires
the snapshot version, five path-readiness entries, at least one ready path, and
raw-content exclusion. It requires at least one doctor-ready path but does not
require aggregate
doctor status to be `pass`, because local and staging replay environments can
be legitimately degraded by optional missing integrations while the exact-file
acceptance checks still pass. Raw approval-token proof remains covered by the
LMS host bridge and test-course evidence lanes rather than being required in
this backend-to-browser summary. It also checks
`len(browser_replay.cases) == evidence.case_count` and
`len(browser_replay.validated_case_id_hashes) == evidence.case_count`,
`len(browser_replay.finalized_case_id_hashes) == evidence.case_count`,
the post-turn lifecycle case-hash list length equals `evidence.case_count`, and
zero finalization errors, preventing inconsistent summary counts, partially
rendered replay matrices, missing lifecycle finalization proof, or unsaved
backend turns from passing release or incident handoff.
The desktop Runtime tab now renders sanitized `runtime_flow_ledger`
facts, including a compact `Route decision` row with selected path reason,
bind/force-tool state, final agent, provider/model authority, visible
tool-loop call/result/denial counts, and flags missing visual/Code Studio
lifecycle or no-action leaks. In legacy/dev or platform-admin sessions, the
same Runtime tab now also fetches `/admin/runtime-flow/doctor/recent` and
renders aggregate-only turn, route, finalization, request-correlation, alert,
hourly trend, and lifecycle-hook registration counts through a
`wiii-connect-runtime-flow-doctor-panel` plus
`wiii-connect-runtime-lifecycle-hooks`;
counter labels are displayed only when they match the safe bounded token
contract, so unsafe route/warning/alert labels are hidden even if a backend
regression sends them. The same backend now exposes
`/admin/runtime-flow/doctor/history`, which groups recent durable ledger events
into per-hour aggregate doctor reports. The Runtime tab renders this through a
`wiii-connect-runtime-flow-doctor-history` table so operators can inspect
recent health movement by bucket without reading session IDs, request IDs, raw
turn text, or payloads. The same panel exposes the session-event retention
control as an explicit dry-run/apply workflow: dry-run reports matched counts
first, apply stays disabled until a dry-run has matched rows, and the UI only
renders aggregate counts, cutoff, retention window, scope booleans, and privacy
strategy. The same durable `session_events` store now has an explicit
platform-admin retention endpoint, `/admin/runtime-flow/session-events/prune`,
backed by both in-memory and Postgres event-log implementations. It defaults to
dry-run, returns only aggregate matched/deleted counts plus scope booleans, and
uses `SESSION_EVENT_LOG_RETENTION_DAYS` as the operator default; pruning is not
automatic. Backend acceptance now also drives the actual
Wiii Connect delegate tool through the integration worker and backend executor,
then proves the resulting action trace and terminal ledger preserve provider,
model, tool-call, tool-result, worker-outcome, audit, and finalization evidence
without exposing provider account IDs or prompt-derived private arguments.
The guarded Wiii Connect external-app action replay now turns that contract into
a registry artifact: `scripts/probe_live_wiii_connect_action_replay.py` requires
`WIII_LIVE_WIII_CONNECT_ACTION_REPLAY=1 --allow-run`, resolves a Gmail provider
action plan and integration lane, runs the provider worker through backend
gateway/schema/audit/execute, derives the final answer from the action-result
envelope, and emits `wiii-connect-action-evidence.json` with hash/count-only
evidence for request/session/user/org/prompt identity, provider-worker stage
sequence, argument-plan keys/counts, scoped connection lookup, execution audit
stages/statuses, final-answer presence, and privacy flags excluding raw prompt,
request identifiers, provider arguments/payloads, audit metadata, connection
identifiers, and final-answer text. Failed action replay artifacts are redacted
before upload and remain diagnostic-only.
`.github/workflows/wiii-connect-action-evidence.yml` runs its unit
contract on PRs/pushes and can upload the artifact through explicit
`run_wiii_connect_action_replay=true` or scheduled
`WIII_CONNECT_ACTION_EVIDENCE_ENABLED=1` runs. The provider adapter boundary is
locally faked for this artifact, so the proof is backend gateway/lane evidence,
not credentialed external-provider evidence.
The Facebook post preview/apply replay has its own mutation-specific registry
artifact: `scripts/probe_live_wiii_connect_facebook_post_replay.py` requires
`WIII_LIVE_WIII_CONNECT_FACEBOOK_POST_REPLAY=1 --allow-run`, drives the real
Wiii Connect FastAPI preview/apply endpoints with a local provider boundary,
and emits `wiii-connect-facebook-post-replay-evidence.json`
(`wiii.live_wiii_connect_facebook_post_replay.v1`). The payload proves preview
records a pending durable operation approval, the first apply consumes it, the
replay attempt blocks with `approval_record_already_consumed` before gateway,
schema, or provider execution, request/session/user/org hash presence,
approval credential and preview evidence hash-presence, user/org-scoped
storage lookup, provider executor count/privacy flags, and count/status-only
audit stages. No post text, Page ID, connection ref, approval token, API key,
account ID, provider arguments, provider responses, request payload, or raw
replay response appears in the artifact. Failed Facebook post replay artifacts
are redacted before upload and remain diagnostic-only.
`.github/workflows/wiii-connect-facebook-post-replay-evidence.yml`
runs the contract tests on PRs/pushes and can upload the artifact through
explicit `run_wiii_connect_facebook_post_replay=true` or scheduled
`WIII_CONNECT_FACEBOOK_POST_REPLAY_EVIDENCE_ENABLED=1` runs.
Credentialed Composio acceptance now has a separate registry lane:
`scripts/wiii_connect_composio_acceptance.py --out` emits
`wiii.live_wiii_connect_composio_acceptance.v1` only when
`WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE=1 --allow-live` is supplied. The
registered artifact requires a connected Gmail account, execution-ready
activation, fail-closed missing-connection gateway proof, allowed execution
gateway proof, live schema readiness, required argument coverage, and
successful read-only provider execution. Its payload must carry structured
hash/count-only observations for backend health, authentication source,
provider registry, adapter/storage/audit readiness, activation readiness,
gateway decisions, selected-account presence, schema/execution metadata, and
privacy flags showing connection refs, account IDs, bearer values/env names,
raw schemas, provider arguments, provider responses, and provider payloads are
not archived.
`.github/workflows/wiii-connect-composio-acceptance-evidence.yml` runs unit
contract checks on PRs/pushes and can upload
`wiii-connect-composio-acceptance-evidence.json` through explicit
`run_composio_acceptance=true` or scheduled
`WIII_CONNECT_COMPOSIO_ACCEPTANCE_EVIDENCE_ENABLED=1` runs.
The workflow first runs
`scripts/wiii_connect_composio_acceptance.py --preflight-only`, which emits
`wiii.connect_composio_acceptance_preflight.v1` setup diagnostics without
calling the backend or provider. That preflight fails early on missing live
flag, `--allow-live`, backend URL, bearer/auth setup, connected-account flags,
or invalid argument JSON, and it omits raw backend URLs, bearer values/env
names, connection refs, raw arguments, provider payloads, and provider
responses. The workflow prints the payload to the step log and GitHub step
summary, uploads `wiii-connect-composio-acceptance-preflight-${{ github.run_id }}`
from `wiii-connect-composio-acceptance-preflight.json` as a 14-day diagnostic
artifact after validation, and then exits with the preflight status. If
`validate_runtime_evidence_preflight.py` fails, the workflow removes the
preflight file before any diagnostic upload. It is diagnostic-only and cannot
replace the registered credentialed execution artifact. When preflight is valid
but not dispatch-ready, the workflow writes a failed
`wiii-connect-composio-acceptance-evidence.json` registered-artifact diagnostic
from the validated preflight file via
`--failure-from-preflight --failure-preflight-json` before exiting non-zero;
that file keeps completion audits source-bound but still fails release
validation until a real connected-account read-only execution succeeds.
The guarded live provider runtime probe now covers the credentialed provider
edge directly: `scripts/probe_live_provider_runtime.py` requires
`WIII_LIVE_PROVIDER_RUNTIME_PROBE=1` plus `--allow-call`, uses LLMPool and
WiiiChatModel instead of raw provider HTTP, forces a harmless
`record_probe_fact` tool-call/tool-result roundtrip with provider/model
authority, request/session/org hash-presence proof, exact single-tool-call
proof, linked hashed tool-result proof, tracing-span duration evidence, and
root privacy flags that keep raw tool arguments, provider responses, provider
payloads, request identifiers, and stream payloads out of the artifact. It can
optionally verify the terminal `/chat/stream/v3` `runtime_flow_ledger` when
`--include-stream-ledger --allow-stream-write` is explicitly supplied, including
stream provider/model authority, `runtime_authoritative=true`, done-event
counts, saved finalization, sanitized `wiii.post_turn_lifecycle.v1` evidence,
request/session/org hash-presence proof, and stream privacy flags for SSE data,
request payloads, prompts, and API keys.
The provider workflow runs
`scripts/probe_live_provider_runtime.py --preflight-only` before the live
provider call so missing provider setup fails early without producing or
uploading a substitute release artifact. That preflight remains
hash/count/status-only and excludes credential names and values. The workflow
prints the preflight JSON to the step log and GitHub step summary before
exiting with the preflight status, and validates that JSON with
`validate_runtime_evidence_preflight.py --requirement-id provider-runtime-tool-loop`;
it does not upload a separate diagnostic artifact. The `vertex` dispatch path
must receive `VERTEX_API_KEY`, matching `settings.vertex_api_key` used by the
runtime provider.
The guarded live LMS test-course replay now covers the backend and credentialed
external test-course side of the source-backed host flow:
`scripts/probe_live_lms_test_course_replay.py` requires
`WIII_LIVE_LMS_TEST_COURSE_REPLAY=1`, `--allow-write`,
`--allow-external-lms-write`, `WIII_LMS_TEST_COURSE_APPLY_URL`, and
`WIII_LMS_TEST_COURSE_APPLY_TOKEN`, streams an uploaded
document turn through `/api/v1/chat/stream/v3`, requires terminal
`lms_document_preview` ledger evidence, extracts the emitted preview
`host_action` without printing raw params, and posts authenticated
`preview_created` and `apply_confirmed` events to `/api/v1/host-actions/audit`
with preview-token hashes and no approval-token echo. It then posts the approved
patch to the external LMS test-course webhook and records only endpoint,
credential, request, course/lesson, preview-token, and content hashes plus
status-code/count evidence. The registered artifact
now also requires request/session/org/course/lesson hash-presence flags, SSE V3
terminal-event evidence, source-backed host capability proof, context
provenance privacy, saved finalization plus sanitized
`wiii.post_turn_lifecycle.v1`, source-count parity across runtime provenance,
preview host action, preview audit, and apply audit, hashed preview-to-apply
audit linkage, audit status-code/action/metadata parity, raw-content metadata
flags, and explicit raw SSE/document/request/auth/header/host-action/audit/
preview-token/approval-token/external-LMS request/response/token/endpoint
absence. `.github/workflows/lms-test-course-evidence.yml` runs its contract
tests on relevant PRs/pushes and can produce
`lms-test-course-evidence.json` through explicit `run_lms_replay=true` or
scheduled `WIII_LMS_TEST_COURSE_EVIDENCE_ENABLED=1` when the external LMS
test-course secrets are configured.
Before live replay, the workflow now runs
`scripts/probe_live_lms_test_course_replay.py --preflight-only`, validates
`wiii.lms_test_course_preflight.v1` with
`validate_runtime_evidence_preflight.py --requirement-id lms-test-course-replay`,
and uploads `lms-test-course-preflight-${{ github.run_id }}` as a 14-day
diagnostic artifact. The preflight includes the same closed
`wiii.live_evidence_setup_contract.v1` style used by proactive-channel and
Composio acceptance diagnostics: abstract handles for live flags, write
acknowledgements, external LMS endpoint/token setup, and backend transport,
without raw endpoint, token, bearer, request ID, or document values. A
`--failure-from-preflight --failure-preflight-json` run can materialize a failed
registered artifact from that validated sidecar for completion-audit diagnosis,
but it remains fail-closed because the registry still requires `status=pass`.
Semantic-memory write provenance now has a dedicated registry lane:
`scripts/probe_live_semantic_memory_write_doctor.py` requires
`WIII_LIVE_SEMANTIC_MEMORY_WRITE_DOCTOR=1 --allow-run`, appends real
`wiii.semantic_memory_write.v1` audit payloads through the session-event-log
interface, and emits `semantic-memory-write-evidence.json`
(`wiii.live_semantic_memory_write_doctor.v1`). The artifact proves the recent
doctor report is org-scoped, cross-org write events are excluded, raw non-memory
session events are ignored, blocked missing-org writes are counted, and no raw
message, response, user ID, session ID, org ID, or secret-like text appears.
It now also carries the org-scoped aggregate history report, proving the
`recent_semantic_memory_write_history` bucket matches the same write counts and
privacy boundary.
The read-only admin surface now also exposes
`/admin/semantic-memory/doctor/history` with
`wiii.semantic_memory_write_doctor_history.v1`, bucketed by
`event_created_at_hour` for `recent_semantic_memory_write_history`, using only
aggregate counts, statuses, warning codes, and privacy flags.
The desktop Runtime tab reads the same recent/history endpoints for
platform-admin or legacy/dev sessions and renders only aggregate write counts,
status buckets, warning codes, backend type, and privacy strategy.
The Runtime-tab browser acceptance now mocks those semantic-memory doctor
endpoints alongside the runtime-flow doctor endpoints and proves the operator
surface renders `wiii-connect-semantic-memory-doctor-panel` plus
`wiii-connect-semantic-memory-doctor-history` without raw memory markers.
`.github/workflows/semantic-memory-write-evidence.yml` runs its contract tests
on PRs/pushes and can upload the artifact through explicit
`run_semantic_memory_write_doctor=true` or scheduled
`WIII_SEMANTIC_MEMORY_WRITE_EVIDENCE_ENABLED=1` runs.
Wiii Connect snapshots now also include a
privacy-safe `capability_summary` with connected provider slugs, granted scope
names, per-path ready/guarded/blocked status, and suppressed tool groups, and
the desktop Path policy tab renders that backend-owned summary. The
local Runtime ledger browser acceptance now seeds an authenticated desktop
session, opens Wiii Connect Runtime, verifies ledger/trace facts, asserts
token-like values are redacted, verifies route-decision reason visibility, and
captures screenshots. It also sends a
mocked chat stream through the desktop SSE path where the complete
`runtime_flow_ledger` arrives on the terminal `done` event, then proves Wiii
Connect shows visual and Code Studio lifecycle counts from that terminal
ledger. The same browser lane now sends a source-backed memory-context turn,
surfaces `context.context_provenance` source kinds, memory types, prior-session
episodic recall counts/event types/score range/scope flags, warning codes, and
`hash_or_count_only` privacy metadata in the Runtime tab, and keeps the
diagnostic rows readable instead of truncating them. It also opens Settings >
Trí nhớ, verifies the user memory API `summary` strip in a real browser, clears
all memories, and verifies the aggregate summary updates without exposing
`semantic_fact`, `hash_or_count_only`, or `raw_content_included` internals in
the UI. The browser lane now also opens the embed entry, authenticates with a
JWT-style identity, posts LMS capabilities/context, uploads markdown course
content through the paperclip flow, verifies the outbound chat request carries
host/document context, and proves the terminal ledger records
`lms_document_preview` with hash/count-only document provenance plus
`preview_required=true`, `approval_token_present=true`, and
`apply_attempted=false`. A second embed browser acceptance now runs Wiii inside
a parent iframe host harness, opens the host-action preview, clicks the teacher
apply CTA, verifies the iframe sends `wiii:action-request` with
`authoring.apply_lesson_patch`, `preview_token`, and `approval_token`, receives
`wiii:action-response`, and submits a Wiii audit payload that excludes the raw
approval token. Completion evidence still requires running the guarded workflow
against the configured external LMS test course and archiving the resulting
artifact bundle.

## Next Execution Order

Proceed in this order unless production risk forces a hotfix:

1. **Reference systems audit**
   - Start with OpenHuman for memory/context/living-agent structure.
   - Start with OpenClaw for gateway/session/tool/trace structure.
   - Convert findings into concrete Wiii flow-ledger and chat-baseline
     requirements.
   - Current OpenClaw output:
     `docs/operations/WIII_OPENCLAW_REFERENCE_AUDIT_2026-05-25.md`.
   - Current OpenHuman output:
     `docs/operations/WIII_OPENHUMAN_REFERENCE_AUDIT_2026-05-26.md`.

2. **Chat stream baseline**
   - Run ordinary Vietnamese chat prompts with no document, no LMS, no visual,
     and no Pointy action.
   - Verify route decision, SSE order, frontend rendering, no raw payload, and
     finalization.

3. **LMS document preview/apply acceptance**
   - Use a safe test tenant/course.
   - Upload real DOCX/PDF.
   - Ask for a lesson in Vietnamese.
   - Verify preview, source refs, citations, `approval_token`, and final draft.
   - For backend/staging evidence, run
     `WIII_LIVE_LMS_TEST_COURSE_REPLAY=1 WIII_LMS_TEST_COURSE_APPLY_URL=<url> WIII_LMS_TEST_COURSE_APPLY_TOKEN=<token> python scripts/probe_live_lms_test_course_replay.py --allow-write --allow-external-lms-write --out lms-test-course-evidence.json`
     and keep only the hash/count-only UTF-8 output.
   - For CI-collected evidence, dispatch
     `.github/workflows/lms-test-course-evidence.yml` with
     `run_lms_replay=true`, or enable
     `WIII_LMS_TEST_COURSE_EVIDENCE_ENABLED=1` for scheduled staging runs.

4. **Wiii Connect V0 snapshot**
   - Consolidate current server, host, LMS, document, Pointy, weather/search,
     visual, Code Studio, and external adapter status into a privacy-safe
     capability snapshot.
   - For backend action-lane evidence, run
     `WIII_LIVE_WIII_CONNECT_ACTION_REPLAY=1 python scripts/probe_live_wiii_connect_action_replay.py --allow-run --out wiii-connect-action-evidence.json`
     and keep only the hash/count-only UTF-8 output.
   - For CI-collected action-lane evidence, dispatch
     `.github/workflows/wiii-connect-action-evidence.yml` with
     `run_wiii_connect_action_replay=true`, or enable
     `WIII_CONNECT_ACTION_EVIDENCE_ENABLED=1` for scheduled staging runs.
   - For Facebook preview/apply replay evidence, run
     `WIII_LIVE_WIII_CONNECT_FACEBOOK_POST_REPLAY=1 python scripts/probe_live_wiii_connect_facebook_post_replay.py --allow-run --out wiii-connect-facebook-post-replay-evidence.json`
     and keep only the hash/count/status UTF-8 output.
   - For CI-collected Facebook replay evidence, dispatch
     `.github/workflows/wiii-connect-facebook-post-replay-evidence.yml` with
     `run_wiii_connect_facebook_post_replay=true`, or enable
     `WIII_CONNECT_FACEBOOK_POST_REPLAY_EVIDENCE_ENABLED=1` for scheduled runs.
   - For credentialed Composio evidence, run
     `WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE=1 python scripts/wiii_connect_composio_acceptance.py --allow-live --backend-url <staging-url> --auth-mode bearer --provider gmail --expect-connected --require-execution-ready --execute-readonly --arguments-json '{"query":"from:me","max_results":1}' --out wiii-connect-composio-acceptance-evidence.json`
     against an approved connected test account.
   - For CI-collected credentialed evidence, dispatch
     `.github/workflows/wiii-connect-composio-acceptance-evidence.yml` with
     `run_composio_acceptance=true`, or enable
     `WIII_CONNECT_COMPOSIO_ACCEPTANCE_EVIDENCE_ENABLED=1` for scheduled staging
     runs.
   - Keep it in-repo until at least two native providers and one external
     adapter share the same shape.
   - Use the snapshot to feed tool policy before adding a standalone
     `wiii-connect` repository.

5. **Runtime flow ledger**
   - Add a typed, privacy-safe turn trace surface.
   - Keep it log/metadata first; avoid a dashboard until the schema is stable.
   - Include route decision, selected tools, source counts, visual/host events,
     provider/model, and finalization status.

6. **Stream and route replay cases**
   - Add golden replay scenarios for uploaded document, visual, Code Studio,
     RAG, and Pointy no-action cases.
   - Current backend replay covers uploaded document, semantic memory-turn,
     visual inline figure, Code Studio app stream, and Pointy/host no-action
     suppression contracts.
   - Keep production smoke lightweight; keep mutation acceptance isolated.

7. **Frontend acceptance matrix**
   - Runtime ledger browser acceptance for Wiii Connect is now covered by
     `npm run test:e2e:runtime-ledger`, including terminal `done`
     ledger propagation for visual, Code Studio, source-backed document,
     semantic memory, episodic recall provenance, authenticated embed LMS
     document upload, and iframe host-bridge preview/apply.
   - Real LMS test-course browser run with preview/apply.
   - Visual/Code Studio frame screenshots.
   - Markdown/code streaming and source-reference visibility.

8. **Living/memory audit**
   - Map post-turn hooks and memory write/read paths.
   - Add tenant-safe replay checks before changing memory behavior.

## Operating Rules

- Do not treat a green unit suite as product readiness when the active flow is
  LMS/host/browser-visible.
- Do not treat a green production smoke as proof that LMS mutation acceptance is
  safe.
- Do not mutate LMS content without preview plus approval evidence.
- Do not debug visuals or Code Studio without checking the lane decision first.
- Do not restart the GCP VM just to inspect code; start it only when a public
  smoke or production acceptance run is needed.
- Promote durable findings into this document, the codebase map, Self-Harness,
  or a GitHub issue. Chat memory is not an operating control.
