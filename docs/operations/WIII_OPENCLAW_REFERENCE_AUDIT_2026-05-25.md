# Wiii OpenClaw Reference Audit

Status: Active reference audit

Owner: Project leadership

Created: 2026-05-25

Related issue: #642

Related docs:

- `docs/operations/WIII_REFERENCE_SYSTEMS_AUDIT_2026-05-25.md`
- `docs/operations/WIII_SYSTEM_CONTROL_PLANE.md`
- `docs/operations/WIII_SELF_HARNESS.md`

## Purpose

This audit turns OpenClaw source-level observations into concrete Wiii
operating requirements. The goal is not to copy OpenClaw. The goal is to make
Wiii easier to diagnose by adding the missing control-plane signals before the
next runtime refactor.

Wiii's immediate problem is that ordinary chat, LMS document authoring, visual
generation, Code Studio, and Pointy host control can look like one generic chat
path. OpenClaw is useful because it treats channel routing, operator actions,
tool permissions, diagnostics, and session state as first-class control-plane
surfaces.

## Source Snapshot

External code was inspected from the ignored local research workspace:

```text
.Codex/external/reference-systems/openclaw
```

| Field | Value |
|---|---|
| Remote | `https://github.com/openclaw/openclaw.git` |
| Local HEAD | `d967760b4154ad647e23543cd56f7a6442b419dd` |
| Commit date | 2026-05-25 |
| Commit title | `docs: update changelog for #70473` |
| Clone mode | shallow, sparse |

Primary OpenClaw areas reviewed:

- `README.md`
- `docs/concepts/architecture.md`
- `docs/concepts/session.md`
- `docs/channels/channel-routing.md`
- `docs/gateway/protocol.md`
- `docs/gateway/configuration.md`
- `docs/gateway/doctor.md`
- `docs/gateway/diagnostics.md`
- `docs/gateway/health.md`
- `docs/gateway/operator-scopes.md`
- `docs/gateway/security/index.md`
- `docs/gateway/security/audit-checks.md`
- `docs/gateway/sandboxing.md`
- `docs/gateway/sandbox-vs-tool-policy-vs-elevated.md`
- `docs/gateway/prometheus.md`
- `docs/gateway/opentelemetry.md`
- `docs/cli/status.md`
- `docs/cli/sessions.md`
- `src/gateway/method-scopes.ts`
- `src/gateway/operator-scopes.ts`
- `src/gateway/control-plane-audit.ts`
- `src/agents/tool-policy.ts`
- `src/agents/tool-policy-pipeline.ts`
- `src/agents/tool-policy-audit.ts`
- `src/agents/tools-effective-inventory.ts`
- `src/agents/trace-base.ts`
- `src/agents/session-tool-result-guard.ts`

## Scope

In scope:

- Identify OpenClaw Pattern candidates that map to Wiii's current debt.
- Convert those patterns into Wiii Runtime Flow Ledger requirements.
- Define a Chat Baseline Acceptance Harness that should run before deeper
  LMS/visual/Pointy changes.
- Record what Wiii must not copy from OpenClaw.

Out of scope:

- Runtime code changes.
- New production deployment.
- Importing OpenClaw code or configuration.
- Expanding Wiii to more external chat channels.

## Audit Summary

OpenClaw's strongest lesson for Wiii is control-plane clarity. It has a single
Gateway that owns session routing, operator scopes, tool exposure, diagnostics,
health, and repair checks. Wiii does not need that exact Gateway process, but it
does need the same class of facts per turn:

- what surface sent the turn
- what session/thread/user/org boundary applied
- what route was chosen and why
- which tools were allowed, bound, suppressed, or called
- which source/document/memory context was included
- which SSE lifecycle events reached the client
- whether a host mutation was only previewed or was approved
- whether the response was finalized and persisted

Without those facts, Wiii will keep feeling "bad" because every symptom starts
as manual archaeology.

## OpenClaw Patterns To Adopt

### 1. Gateway As Control Plane, Not Product Surface

OpenClaw separates the long-lived Gateway from the chat surfaces that talk to
it. The Gateway owns the operating truth: channels, sessions, health, device
auth, tool policy, diagnostics, and repair flows.

Wiii should not create a separate Gateway now. It should create a control-plane
view of each turn inside the existing backend. The first version should be a
typed Runtime Flow Ledger emitted as stream metadata and logs, not a dashboard.

### 2. Role, Scope, And Feature Discovery Before Action

OpenClaw clients connect with roles, scopes, capabilities, commands, and feature
discovery. Method scope is only the first gate; concrete approvals can require
stricter checks.

Wiii should apply the same shape to host surfaces:

- `desktop_chat`
- `desktop_pointy`
- `embed_lms`
- `embed_public`
- `admin`
- future external channels

The surface must declare capabilities before Wiii binds host actions, Pointy
actions, visual tools, Code Studio tools, or LMS preview/apply actions.

### 3. Session Key Is Routing, Not Auth

OpenClaw explicitly treats session keys as routing/context selectors, not
authorization. That matters because direct messages, groups, rooms, webhooks,
and cron jobs can all map to different session scopes.

Wiii must keep `session_id`, `thread_id`, LMS course IDs, host-action request
IDs, and visual session IDs as routing/correlation fields only. Auth must remain
`user_id`, `organization_id`, verified token, membership, and explicit host
surface capability.

### 4. Operator Status, Doctor, And Diagnostics Are Product Features

OpenClaw exposes `status`, `health`, `doctor`, diagnostics export, stability
events, and slash-command style operator flows. Those commands are not cosmetic;
they are how maintainers find broken state without guessing.

Wiii should add equivalent read-only operating views in this order:

1. Runtime Flow Ledger for each chat turn.
2. Chat Baseline Acceptance Harness using the ledger.
3. A read-only `wiii doctor` or admin status surface that summarizes config,
   feature flags, VM/deploy state, LMS/host-action safety, and stream health.

### 5. Tool Policy Pipeline With Effective Inventory

OpenClaw resolves tool exposure through profiles, provider policies,
global/agent policies, sandbox policy, explicit allow/deny, plugin groups, and
audit logs for removed tools.

Wiii's active equivalent is visual intent, Code Studio, host actions, Pointy,
web search, and document preview tools. The next Wiii contract should record:

- requested capability
- bound tools
- suppressed tools
- suppression reason
- source of the rule
- whether a forced host action or visual tool was selected

This supports the existing zero-debt goal for visual intent and tool capability
sync.

### 6. Privacy-Safe Diagnostics By Default

OpenClaw diagnostics intentionally keep operational facts while omitting prompt
text, response text, tool outputs, tokens, cookies, raw IDs, and raw payloads by
default. Metrics use bounded, low-cardinality labels and count dropped series.

Wiii should follow the same rule. Runtime Flow Ledger v1 must not persist raw
uploaded documents, chat text, provider bodies, approval tokens, credentials, or
tool output payloads. It should persist counts, hashes, bounded names, statuses,
durations, and IDs that are already safe to correlate.

### 7. Oversized Payloads Become Diagnostics, Not Broken Streams

OpenClaw records payload-size events without storing raw bodies. Wiii has
several active paths that can produce large payloads: uploaded documents, visual
HTML, Code Studio apps, tool results, and source references.

Wiii should record oversized or truncated payload events with:

- payload class
- original byte count when safe
- emitted byte count
- truncation reason
- stream event affected
- whether the user saw a safe fallback

### 8. Idempotency And Correlation For Side Effects

OpenClaw requires idempotency keys for side-effecting methods. Wiii's critical
side effects are LMS apply, host action apply/publish, Pointy actions, visual
commit, and document preview/apply transitions.

Wiii should require a stable idempotency/correlation key for host action preview
and apply flows. For LMS, mutation remains invalid unless a preview produced an
approval token and the apply call references that approved preview.

### 9. Non-Main Or External Sessions Get Stricter Defaults

OpenClaw's sandbox model can apply stricter execution policy outside main
sessions. The exact personal-assistant sandbox model does not map directly to
Wiii, but the default posture does.

Wiii should treat LMS embed, public embed, Pointy host control, and external
future channels as more restrictive than normal desktop chat. Host actions and
Pointy clicks should be unavailable unless the surface declares the capability
and the request lane explicitly requires it.

### 10. Session Lists And Maintenance Stay Bounded

OpenClaw bounds session listing and separates stored session rows from live
channel health. Wiii should make the same distinction:

- thread/session history is not proof the stream is healthy
- production health is not proof an LMS preview/apply flow works
- production smoke is not proof a host mutation is safe

Ledger-backed acceptance tests should distinguish stored chat state, live stream
events, and host-action side effects.

## Do Not Copy

Wiii should not copy these OpenClaw assumptions:

- **Single-operator trust model.** OpenClaw is designed around one trusted
  personal operator boundary. Wiii is an org-aware LMS and desktop platform, so
  user, organization, role, course, and host surface remain hard boundaries.
- **Host tool defaults for main sessions.** Wiii must not treat desktop chat as
  permission to mutate LMS, click Pointy, or expose broad tool access.
- **Channel sprawl before baseline health.** Wiii should stabilize ordinary
  chat, LMS preview/apply, visual routing, and Pointy no-action policy before
  adding more external channels.
- **Session key as security.** Session and thread IDs are routing facts only.
- **Diagnostics with raw content.** Wiii should not persist uploaded document
  text, prompt text, provider bodies, raw approval tokens, or tool output
  payloads in control-plane diagnostics.
- **No replay as an excuse for missing UX recovery.** If Wiii SSE clients miss a
  terminal event, the frontend still needs a refresh/persistence strategy.

## Runtime Flow Ledger v1

The next implementation slice should add a privacy-safe, typed turn ledger for
chat-stream turns. It can start as metadata/logging without a database table.

Recommended fields:

| Group | Fields |
|---|---|
| Correlation | `turn_trace_id`, `request_id`, `stream_id`, `endpoint`, `created_at` |
| Identity boundary | `user_id_hash`, `organization_id_hash`, `auth_method`, `role`, `membership_checked` |
| Session boundary | `session_id`, `thread_id`, `message_id`, `conversation_id`, `surface_session_id` |
| Host surface | `host_surface`, `host_capabilities`, `host_surface_trusted`, `lms_context_present`, `pointy_mode_present` |
| Input context | `document_context_present`, `uploaded_document_count`, `uploaded_document_ids_hash`, `source_ref_count`, `memory_context_count`, `history_message_count` |
| Routing | `route_lane`, `route_reason`, `routing_confidence`, `selected_agent`, `final_agent`, `visual_intent_kind`, `document_authoring_intent` |
| Provider | `model_provider`, `model_name`, `runtime_authoritative`, `fallback_used`, `fallback_reason` |
| Tool policy | `tool_policy_snapshot_id`, `bound_tools`, `suppressed_tools`, `suppression_reasons`, `forced_tool_choice` |
| Tool lifecycle | `tool_event_counts`, `tool_error_codes`, `visual_event_ids`, `host_action_ids`, `pointy_action_ids` |
| Retrieval | `retrieval_used`, `retrieval_query_count`, `retrieval_source_count`, `citation_count`, `tenant_filter_applied` |
| Stream | `sse_event_counts`, `sse_event_order`, `first_status_ms`, `first_answer_ms`, `done_seen`, `metadata_seen`, `raw_payload_guard_triggered` |
| Host mutation safety | `preview_required`, `preview_emitted`, `approval_token_present`, `approval_token_hash`, `apply_attempted`, `mutation_blocked_reason` |
| Finalization | `response_saved`, `thread_view_upserted`, `background_tasks_scheduled`, `finalization_status`, `error_code` |
| Latency | `latency_ms_by_stage`, `total_duration_ms`, `provider_duration_ms`, `tool_loop_duration_ms` |

Rules:

- Raw prompt, response, provider body, tool result payload, uploaded document
  text, and approval token values are not stored.
- Hashes must be one-way and only for correlation/debugging.
- Arrays must be bounded.
- Missing expected fields should be explicit `null` or `unknown`, not omitted
  silently.
- The ledger must be available in tests without starting all production
  services.

## Chat Baseline Acceptance Harness

Ordinary chat should be the first acceptance flow because it is the easiest
place for hidden routing, stream, memory, or frontend assembly debt to appear.

Minimum scenarios:

| Scenario | User prompt | Required outcome |
|---|---|---|
| Vietnamese greeting | `xin chào Wiii, hôm nay bạn thế nào?` | normal chat lane, readable Vietnamese answer, no tool, no visual, no Pointy, `done_seen=true` |
| Simple factual chat | `giải thích ngắn gọn sự khác nhau giữa API và SDK` | no host action, no raw JSON, final answer persists |
| Inline code explanation | `cho mình ví dụ nhỏ về Promise trong JavaScript` | markdown/code renders as chat text, not Code Studio unless explicitly requested |
| No uploaded document | `tóm tắt tài liệu mình đã tải lên` with no document context | Wiii asks for document/context instead of inventing facts |
| LMS intent without LMS surface | `tạo cho mình bài học` from normal desktop chat without uploaded document | no LMS mutation, no preview host action, asks for missing context |
| Slow stream heartbeat | simulated slow provider/toolless stream | heartbeat/status visible, finalization still runs |

Required assertions:

- `host_surface` is recorded.
- `route_lane` is direct/chat or equivalent non-tool lane.
- `bound_tools` is empty or limited to explicitly safe chat-only tools.
- `suppressed_tools` includes host actions, Pointy, visual, and Code Studio when
  the request does not ask for them.
- SSE event order includes terminal `done`.
- The final answer contains no raw provider tool-call JSON, host-action JSON, or
  widget fences.
- `response_saved` and `thread_view_upserted` are true.
- `latency_ms_by_stage` exists even when the provider is mocked.

## Next Wiii Work Slices

1. `test/feat`: add Runtime Flow Ledger v1 to chat stream metadata and focused
   unit tests.
2. `test`: add Chat Baseline Acceptance Harness around mocked or local
   streaming, without requiring full Docker.
3. `refactor`: route visual/tool capability decisions into the ledger so tool
   binding drift is visible.
4. `test(lms)`: rerun real LMS document preview/apply acceptance only after the
   baseline chat ledger is green.

## Acceptance For This Audit

- The audit names the OpenClaw patterns Wiii should adopt.
- The audit explicitly names what Wiii should not copy.
- Runtime Flow Ledger v1 has a concrete field map.
- Chat Baseline Acceptance Harness has concrete scenarios and assertions.
- The reference systems baseline, operations index, docs index, and Self-Harness
  point to this document.
