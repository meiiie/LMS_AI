# Wiii Connect Blueprint

Status: Draft for implementation

Owner: Architecture maintainers

Created: 2026-05-27

Related issue: #720

## Purpose

Wiii Connect is the planned connection and capability control layer for Wiii.
It exists so Wiii can reason about external apps, LMS, host bridges, documents,
visual runtimes, and future MCP tools through one contract instead of scattered
tool-specific checks.

The immediate goal is not to clone Composio. The immediate goal is to give Wiii
its own connection registry, capability snapshot, and path governor so runtime
tools can fail closed and UI can show what is actually connected.

## Product Decision

Start Wiii Connect inside the Wiii monorepo.

Create a separate `wiii-connect` repository later only after the contracts are
stable enough that package boundaries help more than they slow product repair.

Rationale:

- The first Wiii Connect providers are Wiii-native: LMS, desktop host,
  document corpus, Code Studio, Pointy, and runtime path policy.
- Those providers must be tested against current Wiii chat, SSE, preview/apply,
  and host bridge flows.
- Extracting too early would add versioning, packaging, and deployment overhead
  before the core contract is proven.
- External systems such as Composio, MCP, Nango, Klavis, Activepieces, n8n, and
  Windmill should inform provider adapters, not replace Wiii's safety model.

## OpenHuman Pattern To Adopt

OpenHuman uses Composio underneath, but its important architectural move is the
connection discipline around Composio:

1. Connections are visible runtime state, not hidden prompt assumptions.
2. Connected is distinct from agent-ready.
3. Main chat does not hold every integration action schema.
4. The orchestrator sees a small delegation handle and a set of connected
   toolkit slugs.
5. The toolkit-scoped integration agent receives the real action schemas only
   after the toolkit is selected and verified.
6. UI connection flow is a state machine: disconnected, authorizing, waiting,
   connected, expired, error, disconnecting.
7. Scope and permission toggles gate what actions the agent may call.

Wiii should adopt those rules. Wiii should not copy OpenHuman code or inherit a
personal-agent trust boundary that does not fit LMS, org, and host control.

## Provider Model

Wiii Connect should treat every connector as a provider behind a Wiii-owned
contract.

| Provider kind | Examples | Ownership |
|---|---|---|
| `wiii_native` | LMS, desktop host, document corpus, Code Studio, Pointy | Wiii owns contract and policy |
| `composio` | Facebook, Gmail, Notion, Slack, GitHub through Composio | Wiii owns policy; Composio brokers OAuth/actions |
| `mcp` | Remote or local MCP servers | Wiii owns visibility and permission gating |
| `custom_oauth` | Future Wiii-owned OAuth apps such as Facebook app branded as Wiii | Wiii owns OAuth, token vault, review, policy |
| `workflow` | Activepieces, n8n, Windmill, Pipedream-style workflow bridges | Wiii owns action exposure and approval gates |

Composio is therefore an adapter, not the foundation. Wiii-native providers must
continue working without Composio.

## Runtime Shape

The target runtime flow is:

```text
host/request context
  -> connection registry
  -> capability snapshot
  -> path governor
  -> external app action plan
  -> delegated path/toolkit agent
  -> narrowed tool/action schema
  -> execution gateway
  -> audit/ledger/stream metadata
```

The main chat path should not bind broad tool surfaces. It should choose the
active product path first, then bind only the tools allowed by the current
connection and capability snapshot.

Current V0 backend work has started the OpenHuman-style boundary with
`ExternalAppActionPlan` and `ExternalAppIntegrationLane`: a direct chat turn
resolves the provider/action kind before Wiii Connect tools are exposed.
Facebook direct publish is the first specialized plan. Generic provider actions
now expose a narrow provider-worker pair to main chat:
`tool_wiii_connect_list_actions` for provider-scoped curated inventory, then
`tool_wiii_connect_delegate_to_integration` for the backend-owned worker. The
agent-scoped list-actions surface hides disabled catalog entries even if the
broader UI/operator API can show them for diagnostics, and its schema does not
expose the diagnostic `include_disabled` toggle. The worker selects from
the effective action allowlist, verifies
gateway/schema/scope/audit policy, and executes through Wiii Connect. This is
not yet a full nested integration-agent conversation loop, but the main chat no
longer binds broad catalog/execute provider tools as its primary contract.
The delegate schema is also narrow: model-facing calls carry provider, selected
action, and task summary, while raw provider arguments, mutation overrides,
preview evidence, and approval flags stay backend/runtime-owned. For supported
read actions, the worker can map safe provider arguments from the delegated task
before live schema verification.
Generic execution has the same backend-owned operation boundary. The generic
tool and `/api/v1/wiii-connect/providers/{slug}/execute` route filter caller
arguments through `wiii_connect_argument_key_policy.v1` before provider calls,
so backend-owned keys such as account/Page selectors, publication controls,
media handles, and token-like fields cannot cross into Composio from a
model/API caller. Apply-style mutations also require verified backend
operation policy. Caller-supplied preview evidence IDs or approval-present
booleans are treated as unverified claims and ignored; the specialized
preview/apply route is the path that verifies backend-issued approval tokens.
That specialized route now has a durable operation approval ledger when
`wiii_connect_operation_approvals` is present. Preview records a pending
fingerprint under the authenticated org/user/provider/action boundary, and
apply must consume the same pending row before schema verification or provider
execution. The ledger stores only hashes, evidence ID presence, status, expiry,
and safe shape flags; it does not store post text, Page IDs, connection refs,
media, provider payloads, or approval tokens. Environments that have not yet
run the optional migration keep the previous stateless HMAC token fallback, so
rollout and rollback do not break existing previews.
Model-facing Wiii Connect schemas do not expose `connection_ref` or connected
account identifiers; backend account selection remains tied to authenticated
user/org context, provider lifecycle, scoped policy, and gateway verification.
Facebook direct publish follows the same rule for provider/Page/media binding:
the model-facing schema carries the post copy and a bounded image policy only,
while provider slug, Page id, raw image bytes, file names, media types, and
external image URLs stay backend/runtime-owned.
The broad backend execute tool is diagnostic-scoped in the capability registry;
provider-worker main chat uses only list-actions plus delegate.
List-actions is an inventory/readiness step only; it is not treated as a
completed external action for final-answer synthesis or action-result ledgers.
The durable backend proof for this lane is
`wiii-connect-action-evidence.json` (`wiii.live_wiii_connect_action_replay.v1`):
`probe_live_wiii_connect_action_replay.py` drives the real
`ExternalAppActionPlan` -> `ExternalAppIntegrationLane` -> integration worker
-> backend gateway/schema/audit/execute -> final-answer path while faking only
the provider adapter boundary, so CI can verify the action lane without
provider credentials or raw argument leakage.
Facebook direct publish has a narrower replay proof:
`wiii-connect-facebook-post-replay-evidence.json`
(`wiii.live_wiii_connect_facebook_post_replay.v1`) is produced by
`probe_live_wiii_connect_facebook_post_replay.py`. It drives the real
preview/apply endpoints, proves preview records a pending operation approval,
the first apply consumes it, and a second apply is blocked before gateway,
schema, or provider execution. The artifact keeps only statuses, counts,
presence flags, and hashes.

The provider-worker planning contract lives in
`maritime-ai-service/app/engine/wiii_connect/integration_worker.py`. It records
the worker version, selected provider, scoped allowlist, selected action,
mutation class, prompt-presence flag, stage sequence, and result
classification without storing raw prompt text, provider arguments, OAuth
tokens, API keys, approval tokens, or provider payloads. The chat-facing
delegate tool is now a thin adapter into that worker plan.
The scoped allowlist comes from the effective action inventory for the current
turn. A connected or agent-ready provider with no visible action inventory is
not enough to expose schemas to the model; the action plan blocks with
`no_agent_ready_actions` and the integration lane returns no tools.

Provider selection is provider-scoped, not opportunistic. The target provider
must come from explicit user language and must itself be agent-ready. If the
user asks for Gmail while Facebook is the only ready provider, Wiii blocks the
Gmail action and points back to Wiii Connect rather than routing to Facebook or
letting the model improvise. If a request names multiple providers, Wiii blocks
the action plan until the turn is split or clarified.

Specialized actions have a single runtime owner. Facebook direct publish is
owned by the backend Wiii Connect gateway, not by the generic host-action bridge,
even when the host advertises a same-name capability. The gateway result is the
source of final chat prose so Wiii cannot both publish successfully and answer
as though nothing happened.
Legacy Wiii Connect host-action preview/apply capabilities are filtered before
tool generation on external-app turns, so their older account/Page/media schemas
cannot shadow the backend gateway or leak into the model-visible toolset.

Activation/readiness diagnostics are also provider-scoped. The UI and backend
derive default diagnostic actions from the selected provider's curated catalog;
for example, a Facebook card probes a Facebook curated action, not Gmail's
`GMAIL_FETCH_EMAILS`. This keeps the connection panel from becoming a prompt
guessing surface.

Runtime trace is part of the product contract, not a debug afterthought.
Terminal SSE metadata/done payloads carry a sanitized `runtime_flow_trace` that
records path selection, tool policy, external app action plan, integration lane,
gateway/action result, provider-worker outcome/failure stage, policy denials,
and final answer source. This gives Wiii an OpenHuman-style action lifecycle
audit: if a connector action succeeds, the final answer must be sourced from
that action result rather than a fresh model guess; if that source is missing,
the trace flags it for harnesses.
Direct `tool_call` stream events and tool-call ledgers are held to the same
privacy boundary. They may show safe task parameters, but they must redact
model-supplied account references, Page IDs, raw media payloads, provider
payloads, approval/token/secret fields, and raw prompts before publication,
including when the runtime denies the tool call by policy. Internal executors
can still receive backend-owned args after policy/schema validation; public
events cannot echo `connection_ref`, `page_id`, `image_base64`, `image_url`, or
token-like values.

Runtime doctor is the read-only operator view over the same snapshot. The
`/api/v1/wiii-connect/doctor` endpoint derives path readiness, guarded paths,
blocked paths, external provider readiness, and top blockers from the
privacy-safe Wiii Connect snapshot. It does not inspect logs, prompts, provider
payloads, OAuth secrets, approval tokens, or raw documents. The frontend Runtime
tab consumes this report so a browser tester can see whether a failure is
`missing_required_connection`, `no_agent_ready_external_provider`, or a guarded
approval path before changing prompts or tool descriptions.

The doctor report now includes provider-scoped diagnostics in the same style as
OpenHuman Connections. Each external provider is summarized through registry,
account, agent-policy, and gateway stages. A connected provider can therefore be
shown as `guarded` rather than falsely `ready`: the account exists, but each
action must still pass the gateway and audit policy before Wiii may execute it.
If a local account/reference exists while the Composio adapter is disabled or
unconfigured, Wiii still reports the account stage as connected and the adapter
or agent-policy stage as blocked. This avoids the earlier contradiction where
Wiii could store a Facebook connection and still answer as though no connection
existed at all.
The payload remains sanitized: it exposes slugs, status, counts, reasons, and
next required policy steps, not connection IDs, account labels, tokens, or raw
provider responses.

Connection lifecycle is now a versioned backend contract rather than a UI-only
inference. Provider connection records, activation-readiness responses, runtime
snapshots, and doctor diagnostics may carry
`connection_lifecycle.version = wiii_connect_connection_lifecycle.v1` with one
of `disconnected`, `authorizing`, `waiting`, `connected`, `expired`, or
`error`. This is the OpenHuman-style account flow: it says whether the account
is in OAuth, waiting for callback, active, expired, or broken before any
agent-ready/action inventory decision is considered. The contract contains only
provider slug, state, safe reason, booleans, and required next steps; it must not
carry connection IDs, account labels, tokens, provider payloads, or raw callback
data.
Provider-status chat answers and runtime traces must also consume this lifecycle
when present. A stale `connection_state` or broad `status` field must not
override `connection_lifecycle`; if the backend says the account is `expired`,
chat should report the expired OAuth/account flow and trace should preserve that
decision in `tool_policy_session.connection_status`. Blocked external action
plans must reuse the same sanitized lifecycle in their own metadata so runtime
ledgers can explain why an action tool stayed hidden without exposing OAuth or
provider payloads.

## V0 Scope

Wiii Connect V0 should stay small:

- Define typed connection and capability snapshot records.
- Normalize current runtime status for server, host bridge, LMS authoring,
  host actions, Pointy, document corpus, web/weather/search, and visual/Code
  Studio paths.
- Feed `ToolPolicySession` and `TurnPathDecision` from the same snapshot shape.
- Record an `ExternalAppActionPlan` for external provider turns before binding
  any Wiii Connect tool schemas, with sanitized target-provider lifecycle on
  blocked plans when available.
- Derive an `ExternalAppIntegrationLane` and expose only the collapsed
  integration delegation tool for generic provider-worker turns.
- Scope generic provider-worker turns to the requested provider only; other
  ready providers remain invisible to that turn.
- Expose the snapshot to the frontend runtime dashboard without leaking tokens,
  and expose a doctor report that explains path readiness/blockers from the same
  snapshot without leaking raw documents, prompt text, or provider payloads.
- Expose provider connection lifecycle as a backend control-plane contract, not
  as copied UI text or model prompt guidance.
- Keep all mutating tools behind preview and approval evidence.
- Record enough metadata in runtime ledgers to debug wrong-path behavior.
- Require external action ledgers to show gateway result and final-answer
  source for every connector action turn.

## Current UX Surface

The first product-facing Wiii Connect surface lives inside the desktop shell as
the `Wiii Connect` page. It is an observability and governance page, not a
third-party OAuth console yet.

The page must:

- present a Connections catalog with provider tabs (`Wiii native`, `Composio`,
  `Channels`, `MCP Servers`, and workflow bridges), category filters, search,
  connection cards, and a read-only detail panel;
- read only the sanitized `chat_lifecycle.capabilities.wiii_connect` snapshot;
- show connection status, agent-ready state, scopes, counts, warnings, and path
  policy in grouped UI;
- render backend `connection_lifecycle` as the source of truth for account flow
  whenever it is present, while keeping transient UI states such as local
  disconnecting local to the client;
- summarize tool/provider state without exposing raw tool schemas, provider
  payloads, document text, approval token values, OAuth tokens, or API keys;
- show external providers such as Composio, MCP, custom OAuth, and workflow
  bridges as disabled catalog entries until a vault, permission gate, provider
  adapter, and execution audit exist;
- stay observational until backend execution gateways and reviewable adapter
  contracts are implemented.

V0 must not:

- Build native Facebook/Gmail OAuth connectors.
- Store third-party OAuth tokens before an encrypted vault and revocation model
  exist.
- Let any provider adapter bypass Wiii's path governor.
- Make production LMS mutations possible without `approval_token`.

## Fail-Closed Product Rules

| Surface | Rule |
|---|---|
| LMS preview | Requires active LMS/host authoring connection. |
| LMS apply | Requires active LMS connection, write/apply scope, preview evidence, and `approval_token`. |
| Host actions | Require host bridge capability presence for this surface. |
| Pointy | Must not execute for code, visual, simulation, artifact, or LMS authoring output paths unless explicitly allowed by that path. |
| Document-grounded chat | If uploaded documents are the active source, do not invent outside facts or silently fall back to web search. |
| Web/weather/search | Bind only for explicit live/current/search intent, not generic conversation drift. |
| External apps | If not connected, tell the user to connect the app in Wiii Connections. Do not fake a live app answer from stale memory. |
| External writes | Require explicit scope, preview when available, and action audit. |

## Extraction Criteria

Create a standalone `wiii-connect` repository only when all of these are true:

- V0 contract is stable across backend tests and frontend dashboard.
- At least two Wiii-native providers use the same registry shape.
- At least one external adapter, such as Composio or MCP, uses the same shape.
- Runtime ledgers show connection/capability decisions without raw secrets.
- CI can test contract packages without booting the full product stack.
- Maintainers agree that versioned packages reduce coupling instead of adding
  integration friction.

Until then, Wiii Connect remains an architecture and implementation area inside
this repository.

## Next Implementation Slices

1. Add a backend `wiii_connect` contract module that emits a privacy-safe
   capability snapshot from existing LMS, host, weather, document, Pointy, and
   tool policy state.
2. Update `ToolPolicySession` to consume the snapshot as the source of
   connection status instead of building ad hoc connection maps.
3. Extend the frontend Wiii Connect page/runtime dashboard to display the same
   snapshot, grouped by provider and path. Initial catalog UX now exists; keep
   it read-only until real provider adapters exist.
4. Add tests proving that LMS apply, Pointy, web/weather, document-grounded
   chat, and visual/Code Studio paths bind only the right tools.
5. Use `ADAPTER_V1_DESIGN.md` as the contract for external providers. Composio
   connection can be enabled only after registry, vault/provider-managed
   secrets, OAuth/session callback, storage, and audit checks are ready. Agent
   action execution remains disabled by default and can only be enabled for a
   curated read-only allowlist after schema verification and execution gateway
   approval.
6. Keep the backend `provider_registry.py` as the source of truth for disabled
   external provider catalog entries; frontend catalog state should converge on
   this projection.
7. Add one low-risk read-only Composio action through the gateway before any
   write/apply action. The backend boundary now supports one curated Gmail
   read-only action behind config, schema verification, required-argument
   gating, gateway, and audit; it also supports backend-owned disconnect that
   disables local Wiii state before provider cleanup. The desktop Wiii Connect
   page can now call the backend disconnect boundary through opaque
   `connection_ref` values and keep reconnect on the backend Connect Link path.
   The operator acceptance harness now exists in
   `maritime-ai-service/scripts/wiii_connect_composio_acceptance.py`; registry
   collection uses `--out` with
   `WIII_LIVE_WIII_CONNECT_COMPOSIO_ACCEPTANCE=1 --allow-live` and validates
   `wiii-connect-composio-acceptance-evidence.json`
   (`wiii.live_wiii_connect_composio_acceptance.v1`) through
   `.github/workflows/wiii-connect-composio-acceptance-evidence.yml`. The
   remaining rollout work is running it with approved real Composio credentials
   and a live Gmail connection on staging.
   Facebook post replay collection uses
   `probe_live_wiii_connect_facebook_post_replay.py --out` with
   `WIII_LIVE_WIII_CONNECT_FACEBOOK_POST_REPLAY=1 --allow-run` and validates
   `wiii-connect-facebook-post-replay-evidence.json`
   (`wiii.live_wiii_connect_facebook_post_replay.v1`) through
   `.github/workflows/wiii-connect-facebook-post-replay-evidence.yml`.
