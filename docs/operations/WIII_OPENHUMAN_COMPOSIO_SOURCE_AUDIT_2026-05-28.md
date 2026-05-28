# Wiii OpenHuman Composio Source Audit

Status: Active reference audit

Owner: Project leadership

Created: 2026-05-27

Related issue: #730

## Scope

This audit records the OpenHuman and Composio patterns Wiii should adopt before
enabling real third-party actions through Wiii Connect.

It does not mean Wiii has broadly enabled Composio for every user or provider.
Wiii now has a read-only catalog, runtime status surface, backend-owned Connect
Link flow, connection polling, execution gateway, schema verification boundary,
and read-only execute adapter. Local #780 acceptance passed with real Composio
credentials, a Gmail auth config, a live connected Gmail account, read-only
Gmail execution, browser Wiii Connect evidence, and Facebook connection-only
OAuth. Production or staging rollout still requires target-specific credentials
and the same acceptance run against that deployed backend.

## Official Composio Runtime Model

Current Composio docs describe a session/connected-account model:

- a session is scoped to a user ID, tool access, authentication, and execution
  state;
- connected accounts are stored under the app's user ID, so executions use the
  right user's account;
- Connect Links or `session.authorize()` initiate authentication;
- Composio-managed OAuth should use hosted Connect Link rather than the older
  `initiate()` path; the REST endpoint is
  `POST /api/v3.1/connected_accounts/link`;
- Connect Link requires `auth_config_id` and a stable app user ID, and may take
  a callback URL;
- successful Connect Link responses include a hosted `redirect_url`, while Wiii
  should not expose or store `link_token` in public metadata;
- connected account responses mask sensitive credential fields by default;
- sessions can be configured with allowed toolkits, auth configs, connected
  accounts, and optionally a workbench;
- Composio Connect also exposes meta tools for search, schema fetch, multi
  execute, connection management, wait-for-connection, and remote workbench.
- Current REST tool endpoints include `GET /api/v3.1/tools/{tool_slug}` for
  detailed input/output metadata and `POST /api/v3.1/tools/execute/{tool_slug}`
  for execution with `connected_account_id`, `user_id`, and `arguments`.
- Connected-account lifecycle endpoints include
  `DELETE /api/v3.1/connected_accounts/{nanoid}`, which soft-deletes a
  connected account and prevents further provider execution while preserving
  provider-side audit history.

Sources:

- https://docs.composio.dev/docs/how-composio-works
- https://docs.composio.dev/docs/configuring-sessions
- https://docs.composio.dev/docs/auth-configuration/connected-accounts
- https://docs.composio.dev/docs/composio-connect
- https://docs.composio.dev/reference/api-reference/connected-accounts/deleteConnectedAccountsByNanoid
- https://docs.composio.dev/reference/changelog

## OpenHuman Source Findings

Audited external reference clone:

```text
../_reference_research/openhuman
```

Reference clone commits inspected for the current Composio source pass:

```text
6736467 initial pass
9a95f2f refresh pass, fetched 2026-05-29
```

This clone is intentionally outside the Wiii repository and is not a committed
artifact. Earlier exploratory clones under local agent folders such as
`.Codex/` are not canonical Wiii source inputs. The canonical Wiii evidence is
this audit document plus the Wiii Connect contracts and tests in the main
repository.

Important source files:

```text
app/src/lib/composio/composioApi.ts
app/src/lib/composio/hooks.ts
app/src/components/composio/ComposioConnectModal.tsx
app/src/components/composio/toolkitRequiredFields.ts
src/openhuman/composio/client.rs
src/openhuman/composio/ops.rs
src/openhuman/composio/oauth_handoff.rs
src/openhuman/composio/action_tool.rs
src/openhuman/composio/tools.rs
src/openhuman/composio/tools_tests.rs
src/openhuman/composio/execute_prepare.rs
src/openhuman/composio/execute_dispatch.rs
src/openhuman/memory_sync/composio/periodic.rs
src/openhuman/memory_sync/composio/providers/sync_state.rs
```

Key behaviors:

1. Frontend never talks to Composio directly in backend mode. It calls core
   JSON-RPC methods such as `openhuman.composio_authorize`,
   `openhuman.composio_list_connections`, and `openhuman.composio_execute`.
2. The core proxies through authenticated backend integration routes, so the UI
   does not receive Composio API keys or raw tokens.
3. The connection UI is a state machine: idle, needs-fields, authorizing,
   waiting, connected, expired, disconnecting, and error.
4. OAuth completion is observed by polling `listConnections()` every few
   seconds and by refreshing on configuration-change events.
5. Provider-specific required fields live in a registry, not in scattered modal
   branches.
6. `connected` is not the same as `agent-ready`. OpenHuman has a separate
   agent-ready toolkit set so connected but uncurated providers do not enter
   the agent tool loop.
7. User scope preferences gate read, write, and admin action visibility.
8. Actions hidden by scope are reported as gated capabilities with UI unlock
   paths; the model cannot elevate scopes by itself.
9. The integration agent receives toolkit-scoped action schemas only after the
   toolkit is selected and verified.
10. Execution paths include retry handling for the post-OAuth readiness gap.
11. Meta OAuth flows clean up stale pending/error rows and back off on 429-like
    failures.
12. Error messages and sync logs are sanitized to avoid leaking provider URLs,
    JSON payloads, message bodies, or PII.
13. Later OpenHuman source narrows tool listing with optional action tags,
    currently guarded so tag filters are forwarded only for toolkits that
    explicitly support them, such as GitHub.
14. OpenHuman adds backend-owned helper routes for provider-specific views,
    such as listing GitHub repositories, instead of forcing every provider
    UX through the generic execute path.
15. OpenHuman gates periodic Composio memory-sync work when the user disables
    Memory Tree or is signed out, preventing background connector traffic when
    the runtime is not allowed to sync.
16. OpenHuman records request-budget reset observability for Composio sync so
    operators can distinguish policy pauses, budget resets, and provider
    failures.

### Source Evidence Notes

Frontend RPC boundary:

- `app/src/lib/composio/composioApi.ts` wraps connection, authorize, scope, and
  execute operations in `callCoreRpc(...)` methods such as
  `openhuman.composio_list_connections`, `openhuman.composio_authorize`, and
  `openhuman.composio_execute`. This is the source-level evidence for "frontend
  does not call Composio directly".
- `app/src/lib/composio/hooks.ts` fetches toolkits and connections together and
  then polls `listConnections()` on an interval. It also refreshes on a
  window-level Composio config-change event. This is the evidence for
  post-OAuth polling and config-change reconciliation.

Connection modal and required fields:

- `app/src/components/composio/ComposioConnectModal.tsx` documents the modal
  state flow: disconnected, required-field collection, authorize, browser
  handoff, polling, connected, expired, disconnecting, and error.
- The same component calls `getRequiredFieldsForToolkit(...)` and
  `validateRequiredFieldValues(...)` instead of hard-coding per-provider form
  branches.
- `app/src/components/composio/toolkitRequiredFields.ts` is the declarative
  registry for provider-specific required fields. The important lesson for Wiii
  is not the field list itself; it is that provider-specific connection
  requirements live in a registry and the modal reads the registry.

Core client routing:

- `src/openhuman/composio/client.rs` has a mode-aware
  `create_composio_client(...)` factory. Backend mode uses OpenHuman backend
  integration routes; direct mode uses a BYO Composio API key path.
- Wiii should adopt the backend-owned adapter boundary, but not the initial
  BYO-key product path. Wiii has LMS/org/audit requirements, so Wiii's first
  path must keep Composio API keys backend-only.
- `src/openhuman/composio/ops.rs` keeps some operations backend-only when they
  depend on backend bookkeeping, while mode-aware operations use the factory.
  This supports Wiii's decision to keep provider execution behind a Wiii-owned
  gateway rather than exposing raw provider calls.

OAuth cleanup and retry:

- `src/openhuman/composio/oauth_handoff.rs` clears stale non-active Meta OAuth
  connection rows before new handoff attempts and wraps rate-limit-shaped
  authorize errors with retry/guidance behavior. Wiii should keep this class of
  cleanup in the provider adapter/control plane rather than in chat prompts.

Agent tool and scope discipline:

- `src/openhuman/composio/tools.rs` exposes a small agent tool surface:
  list toolkits, list connections, authorize, list tools, execute.
- The same file explicitly excludes scope elevation from the agent tool set.
  Users must toggle scopes in the Connections UI.
- `evaluate_tool_visibility(...)` checks curated action catalogs and user scope
  preferences before execution.
- `composio_list_tools` filters actions to connected toolkits and can report
  that a toolkit has no agent-ready actions.
- `composio_execute` enforces read-only sandbox constraints, user scope
  preferences, and curated whitelist membership before delegating execution.
- `src/openhuman/composio/tools_tests.rs` pins this behavior with tests for
  stable tool metadata, no scope-elevation tool, read-only sandbox blocks for
  write/admin actions, pass-through for read actions, connected-toolkit
  filtering, uncurated toolkit messaging, and backend/direct routing.
- The 2026-05-29 refresh shows `composio_list_tools` now accepts optional
  action tags and forwards them only when the selected toolkit supports that
  filter. This is a more precise version of the same policy: narrow the action
  catalog before the agent sees schemas, and do not rely on broad toolkit
  visibility.

Provider-specific helper endpoints:

- `app/src/lib/composio/composioApi.ts` now wraps
  `openhuman.composio_list_github_repos` as a backend-owned RPC. The UI can
  render a provider-specific repository picker without receiving Composio API
  keys or calling the generic `composio_execute` action path.
- For Wiii this argues for explicit provider helper endpoints when a product
  surface needs structured provider state, rather than asking chat/tool loops
  to execute a broad provider action just to populate UI.

Background sync discipline:

- `src/openhuman/memory_sync/composio/periodic.rs` now checks the scheduler
  gate before each periodic Composio sync tick. When memory is user-disabled or
  the session is signed out, the tick becomes a cheap no-op before config load,
  API client creation, connection listing, or provider walks.
- `src/openhuman/memory_sync/composio/providers/sync_state.rs` logs daily
  request-budget resets. This separates expected budget lifecycle from
  provider failures in ops logs.
- Wiii does not yet expose Composio periodic sync as a user feature. If Wiii
  adds background connector sync later, it must be gated by explicit product
  state, org/user session state, and budget/audit signals before provider
  calls happen.

Wiii consequence:

- Wiii should keep a smaller, stricter first surface than OpenHuman:
  backend-issued Connect Links, provider-managed vault references, Wiii-owned
  activation readiness, curated read-only action allowlist, execution gateway,
  and audit ledger. Do not expose broad Composio meta-tools or direct BYO API
  key mode in normal Wiii chat.

## What Wiii Should Adopt

Wiii should adopt these rules:

- frontend talks to Wiii backend only;
- backend owns provider registry, OAuth/session reconciliation, and execution
  policy;
- UI shows state and starts OAuth, but cannot grant itself execution rights;
- connection status is separate from agent-ready status;
- main chat sees only path/capability summaries, not a broad action catalog;
- integration-specific agents get narrowed action schemas after path and
  provider selection;
- provider-specific helper views are backend-owned when UI needs structured
  provider state, rather than being implemented as generic chat executions;
- action catalogs should support further narrowing dimensions, such as tags or
  task scopes, only after the backend registry declares the provider supports
  them;
- background connector sync must be gated by user/org/runtime state before it
  resolves credentials or calls provider APIs;
- sync budgets, pauses, and resets should be visible as safe operational
  signals, not hidden inside provider errors;
- write/apply operations require scope and evidence;
- action attempts are audited before and after provider execution.

## What Wiii Should Not Copy Blindly

Wiii should not expose direct BYO Composio API key mode as the first product
path. That mode is useful for a personal desktop agent, but Wiii has LMS,
organization, host action, tenant, and audit requirements. Wiii should start
with a server-side adapter and vault-backed secret references.

Wiii should not treat Composio meta tools as general chat tools. Composio's
meta-tool model is powerful, but Wiii must keep path governance first: choose
the product path, verify the connection, narrow the action catalog, then
execute through Wiii's gateway.

Wiii should not turn provider-specific UI needs into broad agent tool
execution. If a future Wiii Connect page needs "list repositories", "list
pages", or "list calendars", add a narrow backend-owned helper endpoint with a
reviewed response shape and audit behavior.

Wiii should not add background Composio sync until there is a user-visible
enablement flag, org/session gate, budget control, and safe pause/resume audit
story. A connected account is not consent for indefinite background polling.

## Adapter V1 Requirements

Before Wiii enables Composio:

- `connected` must mean only OAuth/session state;
- `agent_ready` must require enabled provider adapter, curated action catalog,
  path policy, user/org scope grant, and gateway support;
- vault records must be opaque references, never frontend tokens;
- OAuth callbacks must validate state/nonce and bind to org/user context;
- execution requests must pass through a single gateway;
- writes must require scope and preview/approval evidence when applicable;
- audit events must record requested, denied, started, succeeded, and failed
  states without raw request/response bodies;
- external provider failures must be surfaced as sanitized reason codes.

## Current Wiii Position

Wiii now has a V0 snapshot/dashboard, V1 policy contract, provider registry,
callback/vault boundary, durable connection/audit storage, controlled storage
probe, Composio adapter configuration status, an authenticated Connect Link
client path that calls Composio only after policy preflight passes, signed
callback state, and callback reconciliation into durable Wiii connection
records. It also has an authenticated connection-listing/polling boundary that
calls Composio `connected_accounts` only through Wiii backend, filters listing
to private connected accounts for the selected Wiii user/auth config, and
upserts sanitized connection records. The desktop Wiii Connect page can now
start a backend-owned Connect Link, open only backend-issued URLs, refresh/poll
sanitized provider connection records, and show connection state separately
from agent-ready execution state. It can also request backend-owned disconnect for a
provider connection and update the local UI state to disabled without exposing
raw provider payloads or connection IDs. Wiii now also has an authenticated execution
gateway preflight endpoint that fetches the stored org/user connection record,
checks path/action/scope/evidence/adapter/audit policy, and appends a
privacy-safe execution ledger record without calling Composio action execution.
Provider connection selection now uses an opaque Wiii `connection_ref` in
frontend and harness requests; raw provider connected-account IDs remain
backend-internal for Composio execute/disconnect calls.
Wiii also has a curated action catalog contract with a
`GMAIL_FETCH_EMAILS` read-only candidate, so future action exposure has a
reviewable allowlist rather than a broad Composio tool dump. This candidate was
chosen because current Composio Gmail docs list it as an available tool, while
current Facebook docs still describe Facebook actions as coming soon.

The backend now has the first read-only execution boundary for that candidate:
deployment must set `enable_wiii_connect_composio_readonly_execute` plus
`composio_readonly_action_allowlist`; Wiii then fetches the live Composio tool
schema, requires the normal gateway decision to be allowed, calls the Composio
execute endpoint only from the backend, and records sanitized started plus
completion audit events. This is deliberately not a broad Composio enablement:
write/apply actions, Composio meta-tools, direct frontend Composio calls, raw
schemas, raw provider outputs, provider tokens, and Composio API keys remain
outside public/chat metadata.

The backend now also has a user-requested disconnect boundary. Wiii fetches the
stored connection by authenticated org/user/provider, marks the local connection
`disabled` before provider cleanup so future agent execution fails closed, then
calls Composio connected-account delete from the backend and writes sanitized
started/completion audit records. This follows OpenHuman's useful connection
state discipline while keeping Wiii's stronger tenant and audit boundary. Wiii
also prevents provider polling from re-enabling a locally disabled
`user_disconnect_requested` connection if Composio still reports it active
during cleanup or eventual consistency windows.

Wiii now also has an operator acceptance harness:
`maritime-ai-service/scripts/wiii_connect_composio_acceptance.py`. It verifies
adapter readiness, durable storage, audit readiness, curated action exposure,
missing-connection denial, backend-owned Connect Link creation, sanitized
connection listing, optional read-only execution, and optional backend-owned
disconnect without calling Composio directly from the harness.

Wiii also exposes a single authenticated activation-readiness projection for a
provider. It aggregates registry, Composio adapter, provider-managed vault,
durable storage, audit ledger, curated read-only action, stored connection, and
execution gateway state without contacting Composio or issuing a Connect Link.
This is the Wiii-side equivalent of the OpenHuman connection discipline: the UI
and operators can see whether a provider is ready to connect and separately
whether it is ready for read-only agent execution, while raw connection IDs,
vault references, auth configs, API keys, and provider payloads remain hidden.
The live acceptance harness now treats this projection as a required gate:
`ready_to_connect=true` is required before Connect Link issuance, and
`ready_to_execute_readonly=true` is required when operator acceptance asks for
execution readiness or read-only provider execution.
The same harness also has a dry readiness-report mode for setup work before
real credentials are present. That mode calls only Wiii's activation-readiness
projection, prints failed gates plus `required_next` hints, and deliberately
does not issue Connect Links, list provider accounts, execute provider actions,
or disconnect accounts.

Wiii now keeps the execution side stricter than the storage helper: execution
readiness, execution-decision, and execute calls require an explicit selected
opaque connection reference. They do not silently reuse the latest stored
provider account.
This preserves the OpenHuman-style connection discipline while avoiding unsafe
multi-account ambiguity once Composio is enabled with real users.

Wiii now also separates provider connection scopes from Wiii-owned scope
policy. The stored connection record can report provider/session scopes, but
the execution gateway also evaluates `scope_policy.py` from the effective
provider entry before adapter execution. A connected account with `read` on the
connection is still blocked with `scope_policy_denied` unless Wiii's runtime
policy grants the required scope for the selected action/path. This mirrors the
source-audited OpenHuman rule that user/toolkit scope preferences gate actions
instead of letting a connected OAuth account automatically enter the agent loop.

Remaining work before broad production enablement: configure production
Composio project credentials and auth config IDs, rerun the acceptance harness
plus browser acceptance through Wiii's connect/list/execute/disconnect
endpoints in that target environment, and decide whether Wiii should keep using
Composio as an adapter or graduate specific providers to Wiii-owned OAuth apps.

The 2026-05-29 OpenHuman refresh does not invalidate Wiii's Adapter V1 shape.
It tightens the next enablement bar: Wiii can keep the current connect/list/
execution gateway path, but any provider-specific browser UX should enter as a
backend helper endpoint, and any future background sync must have an explicit
runtime gate and budget signal before it can be considered production-ready.
