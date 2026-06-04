# Wiii Tool Policy Session Standard

Status: Active

Owner: Backend maintainers

Last updated: 2026-06-01

Applies to: Direct chat tool binding, runtime tool execution, host actions, LMS authoring, Pointy, web/search, weather, product search, tutor, visual tools

## Purpose

Wiii must choose the active product path before exposing tools to a model. Tool
policy is the contract that prevents a casual chat turn from drifting into web
search, a weather turn from searching the wrong entity, Pointy from appearing in
code/visual output turns, or LMS mutation tools from appearing without host
connection and approval context.

The canonical backend shape is:

```text
query/context -> TurnPathDecision -> ToolPolicySession -> bound tools -> execution guard
```

`ToolCapabilityRegistry` is the policy metadata source underneath that shape.
Tool construction remains in the native tool modules, but connection,
approval, mutation, group, and surface-scope metadata must come from
`app.engine.tools.tool_capability_registry`.

Wiii Connect is the next consolidation layer for the same contract. The current
`connection_status` map is the V0 seed of the Wiii Connect capability snapshot
documented in `docs/architecture/wiii-connect/CONNECTION_CONTRACT_V0.md`.
Policy work should extend that snapshot rather than adding unrelated
service-specific status maps.

External app actions add one more typed planning layer before tools are bound:

```text
query/context
  -> ExternalAppActionPlan
  -> ExternalAppIntegrationLane
  -> TurnPathDecision(external_app_action)
  -> ToolPolicySession
  -> provider-scoped tools
  -> Wiii Connect execution gateway
```

The plan is stored in `AgentState["_external_app_action_plan"]`. The derived
lane is stored in `AgentState["_external_app_integration_lane"]`. Both are
copied into `ToolPolicySession` for diagnostics. The lane is the Wiii analogue
of OpenHuman's integration-agent boundary: it says which executor owns the
turn (`specialized_direct_tool` or `provider_worker`), which tools may be
visible, which tool is forced, and which provider/action inventory is in scope.
It is intentionally privacy-safe: provider slug, action kind, executor, visible
tool names, forced tool name, ready provider slugs, effective action allowlists,
UI activity title, and reason only. It must never include raw prompts, provider
payloads, OAuth tokens, API keys, approval tokens, uploaded document text, or
file bytes.

For generic provider actions, the main chat must expose a small provider-worker
surface instead of a broad provider dump. The visible pair is
`tool_wiii_connect_list_actions` followed by
`tool_wiii_connect_delegate_to_integration`. The list-actions tool exposes only
the provider-scoped, runtime-enabled curated action inventory that passed
connection/scope policy; disabled catalog entries may appear in operator APIs
and UI diagnostics, but not in the agent-scoped list-actions tool. The
agent-scoped schema must not expose an `include_disabled` toggle; model-supplied
extras are ignored. The delegate tool receives a provider slug, selected action,
and task summary only; it must not expose raw provider `arguments`, mutation
overrides, preview evidence IDs, or approval flags. The backend worker maps
supported read-action arguments from the delegated task or uses internal
runtime-provided arguments, then the
backend-owned provider worker verifies gateway/schema/scope and audit policy
before executing through Wiii Connect.
`tool_wiii_connect_execute_action` remains backend-internal or diagnostic and is
not the normal main-chat contract for provider-worker turns; its capability
registry scope must stay diagnostic rather than `direct_chat`. ToolPolicySession
must enforce capability surface scopes, so diagnostic-only tools stay hidden even
if a future collector accidentally includes them in a broad candidate set.
Model-facing Wiii Connect tool schemas must not expose `connection_ref`,
connected-account IDs, or account labels. Backend account selection is derived
from the authenticated user/org context, provider lifecycle, scoped action
policy, and gateway checks; connection references are allowed only in sanitized
UI/API/operator diagnostics.
Specialized Facebook direct-apply schemas must also keep provider, Page, and
raw media selection backend-owned. The model-facing schema may carry post copy
and a bounded image policy such as `use_latest_user_image`, but it must not
expose `provider_slug`, `page_id`, raw image bytes, file names, media types, or
external image URLs.
Catalog/list-actions payloads are not provider execution results. They must not
set the final answer source, flip `observed_action_result`, or let chat answer
with "catalog loaded" as if an external action had completed.

Provider-worker turns must resolve an explicit target provider before binding
the delegation handle. If the user asks for Gmail while only Facebook is
agent-ready, the plan must fail closed for Gmail instead of routing to any other
ready provider. Ambiguous turns that name multiple providers must be clarified
or split before any provider action schema is exposed.

Providerless follow-up actions may inherit a provider only from recent Wiii
Connect context, and only when that context contains exactly one provider inside
a provider status/action exchange. For example, after a Facebook capability or
connection-status turn, `đăng bài: "..." là được` may resolve to Facebook. If no
single provider context is present, Wiii must not guess a provider or expose an
integration tool surface.

Providerless external-app actions that name an external surface but not a
provider, such as posting to "mang xa hoi" or sending to an unspecified app,
must still route to `external_app_action` and fail closed with
`missing_provider_target`. They must not fall back to normal chat where the
model can invent whether Wiii can act.

Specialized external actions must also have one runtime owner. For Facebook
direct publish, the backend-owned Wiii Connect gateway owns preview/apply/result
synthesis; host-declared actions with the same public tool name must be filtered
out before tool generation so the host-action bridge cannot shadow the backend
gateway or expose legacy `connection_ref`/Page/media schemas to the model.
Final user-facing prose must come from the gateway/action result
envelope, not from a second model guess.

Runtime observability must prove this contract. `RuntimeFlowLedger` embeds a
privacy-safe `runtime_flow_trace` projection from final `AgentState` into
terminal metadata/done payloads. The trace records the selected
`TurnPathDecision`, final `ToolPolicySession`, external action plan, integration
lane, sanitized Wiii Connect gateway/action result, policy-denied tool calls,
provider-worker result classification, and final answer source. Generic
provider-worker traces should promote `worker_outcome`, `worker_failed_stage`,
and `worker_reason` from the integration-worker classification so operators can
see whether a turn completed, blocked at action policy, waited for preview or
approval, failed at gateway/schema/execution, or remained unknown without
digging through raw tool JSON. If an external action result is observed without
an explicit final-answer source, the trace must flag
`missing_explicit_final_answer_source` so acceptance harnesses can catch
"action succeeded but answer contradicted it" regressions.

Direct tool dispatch events are part of the same public surface as runtime
trace metadata. SSE `tool_call` events and in-memory `tool_call_events` must
redact account references, connected-account IDs, Page IDs, raw media payloads,
provider payloads, approval/token/secret fields, and raw prompts before they are
streamed or recorded. Executors may still receive the validated internal args
they need, but public event payloads must never echo model-supplied
`connection_ref`, `page_id`, `image_base64`, `image_url`, or token-like values,
including on policy-denied tool calls.
Tool result ledgers use `sanitize_tool_result_for_event` before results are
stored in `tool_call_events`; direct and Code Studio tool messages may keep the
internal raw result for follow-up synthesis, visual emission, and artifact
delivery, but event ledgers, host-action params, runtime trace metadata, and
stream summaries must only carry public-safe JSON/text. The runtime acceptance
harness must validate both public `tool_call` args and public `tool_result`
payloads so result-side provider/code leakage is caught as a product contract
failure, not as an incidental log inspection.
For visual and Code Studio lanes, acceptance must also validate the stream
lifecycle evidence in the runtime ledger: inline visual turns need observed
`visual_runtime` plus `visual_open` and `visual_commit`, while Code Studio app
turns need observed `code_studio` plus `code_open` and `code_complete`.
No-action chat replay must also prove absence, not just suppression metadata:
Pointy, host-action, visual, and Code Studio stream events are forbidden when a
normal chat turn did not request those surfaces.

Runtime logs are part of the same observability contract. Backend logging must
be UTF-8 safe on Windows terminals, redirected files, and production containers
so Vietnamese prompts, provider names, and policy reasons cannot trigger
`UnicodeEncodeError` and hide the real runtime failure. The logging layer may
escape characters as a last-resort fallback, but it must never let console
encoding break the chat stream or suppress path/tool diagnostics.

Runtime diagnosis must also be read-only and derived, not manually curated.
`WiiiConnectionSnapshot.doctor_report()` and
`/api/v1/wiii-connect/doctor` summarize ready, guarded, and blocked product
paths from the same connection snapshot consumed by `ToolPolicySession`. This
is the Wiii equivalent of an OpenClaw doctor surface: it tells operators whether
the blocker is a missing host/LMS/document connection, no agent-ready external
provider, or an expected runtime approval gate. The doctor report must not carry
raw prompts, provider bodies, tokens, connection IDs, approval tokens, or
uploaded document text.

The same report must also diagnose each external provider as a lifecycle:
registry, account, agent policy, and per-action gateway. This is the Wiii
equivalent of OpenHuman's Connections page. `connected` means Wiii has an
account/reference; `agent_ready` means the account has enough scoped policy to
be considered by the runtime; `ready` still does not mean free execution,
because the gateway must approve the selected action for that turn. The frontend
Runtime tab should show this provider diagnosis so a tester can see why Facebook
or another connector is blocked/guarded without asking the model to guess.
Provider status answers must use the same distinction: if storage contains an
active Facebook account but the adapter is not bound or configured, the answer is
"connected but not agent-ready", not "Facebook is unavailable" and not a prompt
guess.

Connection/readiness diagnostics are provider-scoped. A readiness request for
Facebook must use a Facebook curated action, or no action, never a Gmail default
action. Provider/action mismatches should fail closed and surface in policy
metadata instead of being hidden in UI copy.

Provider status questions are also provider-scoped control-plane turns. If the
user asks whether Facebook, Gmail, GitHub, or another registered provider is
connected or usable, Wiii must answer from the Wiii Connect snapshot/readiness
state instead of letting the model guess. The answer must preserve the
OpenHuman-style distinction between `connected` and `agent_ready`: a stored or
active account can be visible while provider execution remains blocked by
adapter, gateway, scope, action allowlist, or audit policy.

Connection account flow is a backend contract. Provider connection rows,
activation-readiness responses, runtime snapshots, and doctor diagnostics should
prefer `connection_lifecycle.version =
wiii_connect_connection_lifecycle.v1` when present. The lifecycle enum is
`disconnected`, `authorizing`, `waiting`, `connected`, `expired`, or `error`;
client-only transitional states such as disconnecting may be rendered locally
but must not be mistaken for backend readiness. Lifecycle metadata is limited to
safe status, reason, booleans, and required next steps. It must not include
connection IDs, account labels, OAuth tokens, callback payloads, approval
tokens, or provider bodies.
Provider-status fast answers must prefer this lifecycle over older
`connection_state` fields, and `runtime_flow_trace.tool_policy_session` must
preserve sanitized `connection_status` so operators can audit which lifecycle
state governed the no-tool/control-plane answer.
Blocked `external_app_action_plan` metadata must carry the same sanitized
`connection_lifecycle` for its target provider when available, so a fail-closed
action turn and a provider-status answer explain readiness from one backend
source of truth.

The same provider-scoped status answer is the fallback for blocked generic
provider actions. If a user asks Wiii to read Gmail or create a GitHub issue
while the requested provider is not `agent_ready`, the external-app action plan
must fail closed and return the snapshot-derived reason. It must not expose the
provider-worker delegation tool, action schemas, or an alternate ready provider
as a substitute for the requested provider.

The provider-worker preflight contract is implemented in
`app.engine.wiii_connect.integration_worker`. It is the backend-owned boundary
between the collapsed delegate tool and provider execution: validate provider
scope, select one curated action through action policy, emit privacy-safe stage
metadata, then hand execution to the gateway-backed backend action executor.
Gateway blocks that ask for user/runtime work must stay typed as lifecycle
states, not generic failures: missing arguments become `validation_failed`,
missing preview evidence becomes `preview_required`, and missing approval
evidence becomes `approval_required`. The tool still returns `success: false`
and no provider execution occurs until the required state is satisfied.

## Required Contract

Every direct chat turn should have a `ToolPolicySession` in `AgentState` when
tool selection is evaluated.

No-tool turns are still governed turns. Casual chat, direct prose, deterministic
fast responses, blocked provider-status answers, and any provider-backed turn
that intentionally binds no tool must still emit both
`runtime_flow_trace.turn_path_decision` and
`runtime_flow_trace.tool_policy_session`. A missing policy session on a
successful no-tool answer is a regression because operators can no longer prove
whether tools were deliberately withheld or simply skipped by an unobserved
runtime branch.

Runtimes that already perform their own tool selection, such as Code Studio,
tutor, and product search, should record the same contract with
`build_visible_tool_policy_session`: the candidate set is the collected tool
inventory, and the visible set is the runtime-selected tool bundle actually
bound to the model.

The session records:

- `path`: active path such as `casual_chat`, `weather_lookup`, `web_search`,
  `maritime_search`, `lms_document_preview`, `pointy_guidance`, or
  `visual_generation`.
- `candidate_tool_names`: tools collected before final policy filtering.
- `visible_tool_names`: final tools bound to the model after runtime pruning.
- `allowed_tool_names` and `allowed_tool_prefixes`: positive allow rules for
  narrow paths.
- `forbidden_tool_names` and `forbidden_tool_prefixes`: explicit negative rules.
- `connection_status`: fail-closed service status such as LMS authoring
  connection, host capability presence, and weather provider availability.
- `external_app_action_plan`: the provider/action boundary chosen before
  binding Wiii Connect tools, including sanitized target-provider
  `connection_lifecycle` for blocked action turns when available.
- `external_app_integration_lane`: the executor/tool-visibility lane derived
  from the action plan before the direct loop invokes the model.
- `approval_required_tool_names`: tools that require preview/approval evidence.
- `tool_capabilities`: serialized registry metadata for candidate tools, used
  for auditability and later loop migration.
- `integration_worker`: for delegate results, privacy-safe metadata with worker
  version, provider slug, selected action, mutation, scoped allowlist,
  prompt-presence flag, stage sequence, and result classification. The
  classification should make it clear whether a turn completed, was blocked at
  provider/action policy, failed at gateway/schema/argument validation/execute,
  or is waiting for preview/approval without exposing provider payloads.

The capability registry records:

- capability group: web search, weather, LMS authoring, host action, Pointy,
  product search, visual, knowledge search, utility, or Code Studio output;
- permission level: read, write, or host control;
- required connection: LMS authoring, weather provider, or host actions;
- whether the tool mutates state or requires host-issued approval evidence;
- intended surface scope, such as direct chat, tutor, product search,
  Code Studio, host, LMS, or visual runtime.

## Runtime Rules

1. Path-specific tools must be exposed only through `ToolPolicySession`.
2. A tool not visible in `visible_tool_names` must not execute, even if a model
   emits a raw or stale tool call.
3. LMS authoring tools require an active LMS host connection. Apply tools also
   require host-issued approval evidence.
4. Weather may expose a fail-closed status tool on `weather_lookup`, but it must
   not fall back to generic web search unless the user explicitly requests web
   search.
5. Pointy must stay out of code, visual, simulation, artifact, and LMS output
   creation paths unless the active path explicitly allows it.
6. Denied tool calls should emit a visible tool result that explains the policy
   denial instead of silently doing nothing.
7. External app actions must select an `ExternalAppActionPlan` before exposing
   provider tools. Generic provider actions bind only the collapsed integration
   delegation tool for agent-ready providers; direct Facebook publish binds only
   the planned direct apply tool.
8. External app actions must derive an `ExternalAppIntegrationLane` from the
   plan and use that lane for prompt-visible tool selection. Main chat code
   should not add provider-specific force-tool branches.
9. The requested provider slug in the plan must match an agent-ready provider;
   another ready provider must not satisfy the request.
10. Provider action schemas must consume the plan's effective action inventory
    as the source of model-visible action slugs. If a provider is connected or
    agent-ready but the effective inventory has no visible action for this turn,
    the plan must block with `no_agent_ready_actions` and expose no Wiii
    Connect tool schemas.
11. A specialized external action must expose exactly one owner/tool instance
    for its public tool name. Backend-owned Wiii Connect actions take precedence
    over generic host-action generated tools.
12. Readiness and activation probes must derive their default action from the
    selected provider's curated catalog.
13. Terminal stream metadata must include enough sanitized runtime trace data to
    reconstruct path selection, tool visibility, external-app gateway result,
    and final-answer source without reading raw provider payloads or prompts.
    Registry evidence for this lane is `wiii-connect-action-evidence.json`
    (`wiii.live_wiii_connect_action_replay.v1`), produced by
    `probe_live_wiii_connect_action_replay.py` and validated by
    `.github/workflows/wiii-connect-action-evidence.yml`. That evidence must
    prove request/session/user/org/prompt hash presence, provider-worker stage
    sequence readiness, argument-plan key/count coverage, org/user-scoped
    connection lookup, execution audit stages/statuses, and privacy flags that
    keep raw prompts, request identifiers, provider payloads, audit metadata,
    connection identifiers, and final-answer text out of archived artifacts.
14. `tool_call` stream/event args must be sanitized before publication; policy
    denial paths must not echo the exact forbidden args that caused the denial.

## Verification

Policy changes should include focused tests for:

- prompt/bind-time visibility;
- execution-time denial;
- narrow path dominance over broad fallback paths;
- connection-gated host/LMS tools;
- no raw internal tool names leaking into user-facing prose.

When Wiii Connect snapshot code lands, also test that snapshots contain only
status, scopes, counts, and warning codes, never tokens, raw uploaded document
content, prompt text, or provider payloads.

Recommended commands:

```powershell
cd maritime-ai-service
python -m pytest tests/unit/test_tool_policy_session.py tests/unit/test_turn_path_governor.py tests/unit/test_direct_tool_rounds_runtime.py -q --tb=short
python -m ruff check app/ tests/unit/ --select=E9,F63,F7
git diff --check
```
