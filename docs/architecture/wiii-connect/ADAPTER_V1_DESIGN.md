# Wiii Connect Adapter V1 Design

Status: Draft contract implemented; local live acceptance passed

Owner: Project leadership

Created: 2026-05-27

Related issue: #730

## Purpose

Adapter V1 is the policy layer between Wiii's path governor and any external
integration provider such as Composio, MCP, custom OAuth, or workflow bridges.

It exists to make external actions fail closed. A provider being connected does
not mean the agent can use it. The gateway must verify provider state, user/org
ownership, action curation, path policy, scope, preview evidence, approval
evidence, and audit requirements first.

## Contract Boundary

Adapter V1 is not an OAuth client and not a provider SDK. It is the shared
contract every provider implementation must satisfy.

```text
provider registry
  -> OAuth/session/vault reconciliation
  -> connection record
  -> path-selected execution request
  -> execution gateway decision
  -> provider adapter call
  -> audit ledger event
```

The implemented backend contract lives in:

```text
maritime-ai-service/app/engine/wiii_connect/adapter_v1.py
```

The curated action catalog contract lives in:

```text
maritime-ai-service/app/engine/wiii_connect/action_catalog.py
```

The backend-owned provider catalog lives in:

```text
maritime-ai-service/app/engine/wiii_connect/provider_registry.py
```

The read-only API projection lives at:

```text
GET /api/v1/wiii-connect/providers
```

The connection-session control contract lives in:

```text
maritime-ai-service/app/engine/wiii_connect/connection_sessions.py
```

The OAuth callback/vault boundary contract lives in:

```text
maritime-ai-service/app/engine/wiii_connect/callback_boundary.py
maritime-ai-service/app/engine/wiii_connect/callback_state.py
```

The vault policy and audit ledger contracts live in:

```text
maritime-ai-service/app/engine/wiii_connect/vault.py
maritime-ai-service/app/engine/wiii_connect/audit_ledger.py
```

The provider adapter readiness and authorization URL contract lives in:

```text
maritime-ai-service/app/engine/wiii_connect/provider_adapters.py
maritime-ai-service/app/engine/wiii_connect/composio_adapter.py
```

The execution gateway preflight and audit boundary lives in:

```text
maritime-ai-service/app/engine/wiii_connect/execution_gateway.py
```

The provider/action scope policy contract lives in:

```text
maritime-ai-service/app/engine/wiii_connect/scope_policy.py
```

The durable storage contract and schema live in:

```text
maritime-ai-service/app/engine/wiii_connect/persistent_storage.py
maritime-ai-service/app/engine/wiii_connect/operation_approval.py
maritime-ai-service/alembic/versions/049_create_wiii_connect_storage.py
maritime-ai-service/alembic/versions/056_create_wiii_connect_operation_approvals.py
```

Current session/status API projections:

```text
GET  /api/v1/wiii-connect/providers/{slug}/status
POST /api/v1/wiii-connect/providers/{slug}/sessions
POST /api/v1/wiii-connect/providers/{slug}/authorization-url
GET  /api/v1/wiii-connect/providers/{slug}/connections
DELETE /api/v1/wiii-connect/providers/{slug}/connections/{connection_ref}
POST /api/v1/wiii-connect/providers/{slug}/connections/{connection_ref}/scope-grant
GET  /api/v1/wiii-connect/providers/{slug}/facebook/pages
POST /api/v1/wiii-connect/providers/{slug}/facebook-post/preview
POST /api/v1/wiii-connect/providers/{slug}/facebook-post/apply
GET  /api/v1/wiii-connect/providers/{slug}/actions
GET  /api/v1/wiii-connect/providers/{slug}/activation-readiness
POST /api/v1/wiii-connect/providers/{slug}/execution-decision
POST /api/v1/wiii-connect/providers/{slug}/execute
GET  /api/v1/wiii-connect/providers/{slug}/callback
GET  /api/v1/wiii-connect/provider-adapters/status
GET  /api/v1/wiii-connect/storage/status
GET  /api/v1/wiii-connect/vault/status
GET  /api/v1/wiii-connect/audit-ledger/status
```

Frontend surfaces should consume this registry/snapshot projection instead of
inventing a separate external-provider source of truth. Until a provider has
OAuth, vault, scoped action catalog, gateway, and audit support, the registry
must keep that provider disabled and non-agent-ready.

The desktop Wiii Connect page now consumes the authenticated backend
authorization and connection-list endpoints for backend registry providers. It
opens only backend-issued Connect Links, polls sanitized connection records
through Wiii, and still keeps provider connection state separate from
`agent_ready` execution state. The frontend never calls Composio directly and
never receives provider tokens, raw payloads, or raw provider connection IDs.
Activation, execution-decision, execute, and disconnect surfaces must select an
account with Wiii's opaque `connection_ref` (`wcn_*`). Raw provider connected
account IDs are backend-internal only and are treated as "no selected
connection" if they appear in public request bodies or paths.

The activation readiness endpoint is the single operator/UI preflight for a
provider. It performs no provider network calls, creates no Connect Link, and
does not mutate local connection rows. It aggregates registry, provider adapter,
provider-managed vault, durable storage, audit ledger, curated read-only action,
local connection, and execution gateway state into one privacy-safe response so
operators can see whether Wiii is ready to connect or execute a read-only action
without guessing from logs.

## Core Entities

`WiiiConnectProviderRegistryEntry`

- provider slug, kind, auth mode, enabled state;
- whether it is agent-ready;
- connection requirements such as Connect Link, provider-managed vault ref, and
  audit readiness;
- agent-ready requirements such as scope policy, curated action catalog, and
  execution gateway;
- path allowlist;
- curated action allowlist;
- provider-specific required fields;
- default scopes and safe public metadata.

`WiiiConnectCuratedAction`

- reviewed action candidate for one provider;
- records action slug, mutation class, product path, required scopes,
  preview/approval requirements, and sanitized argument key names;
- starts disabled until the live provider schema is verified and adapter
  execution is implemented;
- never stores raw Composio schemas, provider payloads, provider responses, or
  secrets;
- exposes public catalog summary through both provider registry metadata and
  `GET /api/v1/wiii-connect/providers/{slug}/actions`.

`WiiiConnectVaultSecretRef`

- opaque pointer to credentials;
- never serializes secret values or vault paths to public metadata;
- public metadata reports only provider slug, connection-reference presence, and
  secret-version labels, never raw provider connection IDs;
- lets UI and runtime know that a vault reference exists without exposing it.

`WiiiConnectConnectionRecordV1`

- provider slug, opaque public `connection_ref`, normalized lifecycle state;
- raw provider connection ID stays backend-internal for provider execute,
  disconnect, and storage lookup;
- granted scopes;
- optional vault reference;
- sanitized account label/reference presence only.

`WiiiConnectExecutionRequest`

- provider slug, action slug, product path, mutation class;
- approval token presence flag, not token value;
- preview evidence ID, not raw preview body;
- argument key list for audit shape, not full provider payload.

`WiiiConnectExecutionDecision`

- allow/deny outcome;
- reason code;
- required scopes;
- audit tags.

`WiiiConnectAuditEvent`

- privacy-safe event around request, deny, start, success, and failure stages.

`WiiiConnectSessionStartRequest`

- provider slug, UI surface, requested scope flags, and safe request-shape keys;
- stores redirect URI presence only, not the URI value;
- redacts sensitive request metadata keys before public/audit projection.

`WiiiConnectProviderConnectionStatus`

- provider authorization readiness for UI;
- `can_start_authorization` remains false until registry, agent readiness,
  provider adapter, vault, scope policy, execution gateway, and audit are ready.

`WiiiConnectSessionStartDecision`

- returns `blocked` or `ready`;
- returns an authorization URL only when a provider adapter supplies one;
- current Composio registry entries return `blocked/provider_disabled`.

`WiiiConnectCallbackRequest`

- records only callback shape: state/code/error presence and sanitized key names;
- supports Composio Connect Link callbacks where a provider-managed connected
  account reference is present instead of a raw OAuth code;
- requires Wiii-owned signed callback state to be valid before accepting;
- never returns OAuth code, state value, token, client secret, or raw provider
  payload.

`WiiiConnectCallbackDecision`

- returns `blocked` or `accepted`;
- blocks disabled providers, provider errors, missing state, invalid state,
  missing provider connection reference, missing vault, or missing provider
  adapter;
- issues a vault reference only after vault and provider adapter are both ready.

`WiiiConnectCallbackStateClaims`

- verifies the Wiii-owned `wiii_state` query value appended to provider callback
  URLs;
- binds callbacks back to the Wiii organization/user boundary without exposing
  the raw state value in audit or public metadata;
- rejects tampered, expired, wrong-provider, and malformed state values.

`WiiiConnectVaultCapability`

- reports whether a vault backend is enabled and can accept external secrets;
- default status is disabled/fail-closed;
- public metadata never exposes vault namespaces, key IDs, or secret material.

`WiiiConnectVaultSecretWriteDecision`

- decides whether OAuth/API/provider secret material may enter a vault adapter;
- blocks disabled providers, disabled vaults, missing secret material, unsupported
  secret kinds, and non-accepting vault backends;
- returns only an opaque `WiiiConnectVaultSecretRef` when ready.

`WiiiConnectAuditLedgerRecord`

- normalizes session, callback, vault, provider, and execution audit events;
- recursively redacts sensitive keys before public projection;
- current contract is storage-agnostic and reports persistent storage as not yet
  configured.

`WiiiConnectProviderAdapterCapability`

- reports whether an adapter implementation is bound and configured;
- reports which operations are available: authorization URL creation, callback
  exchange, and action execution;
- defaults every external provider kind to unbound and not authorization-ready.

`WiiiConnectComposioAdapterConfig`

- reads backend-only Composio settings without exposing `composio_api_key` in
  public metadata;
- supports provider-to-`auth_config_id` maps via JSON or comma-separated text;
- reports disabled, missing API key, missing auth config map, or configured
  status as provider adapter capability metadata;
- issues Composio hosted Connect Link URLs only through the authenticated Wiii
  backend route after registry, adapter, provider-managed vault, and durable
  audit checks pass;
- lists Composio connected accounts only through an authenticated Wiii backend
  route filtered by the Wiii external user ID and provider auth config;
- hashes the Wiii org/user boundary into a stable non-PII Composio user ID;
- redacts `link_token`, provider account IDs, API keys, auth config IDs, and raw
  provider errors from audit/public metadata;
- keeps action execution disabled by default;
- enables action execution only when
  `enable_wiii_connect_composio_readonly_execute` and
  `composio_readonly_action_allowlist` explicitly name a curated read-only
  action for that provider.

`WiiiConnectComposioToolSchemaResult`

- verifies a curated Composio tool with `GET /api/v3.1/tools/{tool_slug}`
  before execution;
- exposes only status, reason, schema presence, sanitized argument keys, and
  sanitized required keys;
- never returns raw Composio schema descriptions, provider payloads, examples,
  OAuth scopes, API keys, auth config IDs, or provider error bodies.

`WiiiConnectComposioExecuteResult`

- wraps `POST /api/v3.1/tools/execute/{tool_slug}` for one curated read-only
  action after the gateway and schema verifier pass;
- sends provider arguments only from the backend adapter call and never records
  those values in public metadata or audit records;
- returns only execution status, reason, HTTP status code, safe top-level data
  keys, and presence flags for provider error/session/log fields;
- never returns email bodies, provider response data, `log_id`, session IDs,
  OAuth tokens, Composio API keys, or raw error bodies.

`WiiiConnectComposioConnectionListResult`

- normalizes Composio `connected_accounts` responses into
  `WiiiConnectConnectionRecordV1`;
- filters calls by Wiii-owned external user ID and provider `auth_config_id`;
- returns only connection lifecycle metadata and public vault-reference presence;
- never returns credential state, provider raw payloads, auth config IDs, API
  keys, or provider error bodies.

`WiiiConnectComposioDisconnectResult`

- wraps Composio connected-account soft delete through
  `DELETE /api/v3.1/connected_accounts/{nanoid}`;
- is reached only after Wiii has authenticated the user, fetched the stored
  org/user/provider connection, and marked the local Wiii connection disabled;
- returns only provider status, reason, status code, connection-reference
  presence, and success boolean;
- never returns the connected-account ID, provider response body, provider
  errors, OAuth tokens, auth config IDs, or Composio API keys in public or audit
  metadata.

`WiiiConnectAuthorizationUrlRequest`

- records only safe authorization request shape: state presence, redirect URI
  presence, requested scope flags, and sanitized metadata key names;
- does not store OAuth state, OAuth code, redirect URI value, token, client
  secret, or provider payload.

`WiiiConnectAuthorizationUrlDecision`

- returns `blocked` or `ready`;
- requires enabled provider, backend-created state, backend-bound redirect URI,
  bound/configured adapter, vault capability, persistent audit ledger, and an
  adapter-supplied authorization URL;
- does not require `agent_ready`; users may connect accounts before Wiii exposes
  curated actions to agents;
- rejects adapter/provider-kind mismatch before any OAuth handoff;
- direct session callers may not bypass adapter policy by passing a URL.

`WiiiConnectPersistentStorage`

- writes per-org, per-user connection records to `wiii_connect_connections`;
- reads the latest sanitized per-org/per-user/provider connection record for
  execution gateway decisions;
- appends privacy-safe provider/session/callback/vault/execution events to
  `wiii_connect_audit_ledger`;
- requires explicit `organization_id` and `user_id` before writing;
- stores only public vault-reference metadata, never raw vault paths or secret
  material;
- fails softly when the database or migration is unavailable, keeping providers
  blocked instead of allowing un-audited execution.
- is exposed through controlled status/probe APIs with database probing disabled
  by default, so normal UI renders do not block on storage connectivity.

`WiiiConnectExecutionGatewayDecision`

- is the audited preflight boundary before any provider action can execute;
- requires the authenticated Wiii org/user connection record from persistent
  storage, not a frontend-supplied connection claim;
- checks registry enabled state, `agent_ready`, path allowlist, curated action
  allowlist, stored connection scopes, Wiii-owned scope policy, preview
  evidence, approval-token presence, adapter execution capability, and
  persistent audit readiness;
- treats provider connection scope and Wiii policy scope as separate gates:
  a provider account may be connected and still blocked with
  `scope_policy_denied` if the effective provider policy does not grant the
  required read/write/apply/admin scope for that path/action;
- records only action slug, path, mutation, approval-token presence, preview
  evidence presence, and sanitized argument key names;
- never accepts raw provider arguments, raw provider payloads, OAuth tokens,
  approval token values, Composio API keys, or provider response bodies;
- generic execution filters caller arguments through the curated
  `wiii_connect_argument_key_policy.v1` before provider execution, and
  mutating actions do not trust caller/model preview IDs or approval-present
  booleans. Only a specialized backend flow that verifies a backend-issued
  preview/apply token may pass trusted operation policy into the executor;
- remains the required preflight boundary for both execution-decision and real
  execution routes. The execute route may call Composio only after this gateway
  returns `allowed`, the live schema check passes, required schema argument
  keys are present, and started/succeeded/failed audit records can be appended.

The first catalog candidate is `GMAIL_FETCH_EMAILS`, a read-only Gmail action
listed in current Composio docs. It stays disabled unless backend runtime flags
explicitly enable Wiii Connect Composio read-only execution and the provider
allowlist names the action. Local #780 acceptance validated the live Composio
schema, Wiii-owned scope policy, explicit `connection_ref` selection, execution
gateway, and read-only execute path for a connected Gmail account.

The first controlled apply path is Facebook Page posting through
`FACEBOOK_CREATE_POST` and `FACEBOOK_CREATE_PHOTO_POST`. It is disabled by
default and requires `enable_wiii_connect_composio_apply_execute` plus a
provider allowlist naming the actions. The desktop Wiii Connect UI exposes it as
a preview/apply composer, not as casual chat execution: the user must select a
specific `connection_ref`, grant read/preview/apply scope for that connection,
select a Page, review the generated preview, and submit the backend-issued
approval token before Wiii can call Composio. User-selected images are staged
through Composio's file upload request flow; Wiii never accepts arbitrary local
file paths from a model/tool call for this mutation. When the operation approval
table is deployed, the preview also records a pending request fingerprint and
apply must consume that pending row, making replay of the same approved preview
a backend-ledger denial rather than a prompt-level convention. The row stores
only hashes, status, expiry, and safe shape metadata; it does not store the post
message, Page ID, connection ref, media bytes/URL, provider payload, or approval
token.
`probe_live_wiii_connect_facebook_post_replay.py` and
`.github/workflows/wiii-connect-facebook-post-replay-evidence.yml` turn that
contract into opt-in runtime evidence: preview must record a pending ledger row,
first apply must consume it, and replay must block before schema or provider
execution.

## Lifecycle States

Adapter V1 normalizes provider states into:

- `disconnected`
- `authorizing`
- `waiting`
- `connected`
- `expired`
- `error`
- `disabled`

Composio-like statuses map as follows:

| Provider status | Wiii state |
|---|---|
| `ACTIVE`, `CONNECTED` | `connected` |
| `PENDING`, `INITIATED`, `INITIALIZING` | `waiting` |
| `AUTHORIZING` | `authorizing` |
| `EXPIRED` | `expired` |
| `FAILED`, `ERROR` | `error` |
| `DISABLED` | `disabled` |
| unknown/empty | `disconnected` |

## Agent-Ready Gate

`connected` is only transport/auth state. A provider may be enabled for
connection without being `agent_ready`. `agent_ready` is required for execution
and requires all of:

1. provider registry entry is enabled;
2. provider registry entry is marked agent-ready;
3. live connection belongs to the same provider slug;
4. live connection state is `connected`;
5. the caller selected an explicit opaque `connection_ref` for execution;
6. runtime path and action are allowed by the gateway.

This follows the useful OpenHuman pattern while keeping Wiii's stronger LMS,
tenant, and host-action safety boundary.

## Gateway Deny Reasons

The gateway denies by default. Current reason codes:

- `provider_disabled`
- `provider_not_agent_ready`
- `connection_selection_required`
- `connection_missing`
- `connection_provider_mismatch`
- `connection_not_connected`
- `path_not_allowed`
- `action_not_allowed`
- `missing_scope`
- `scope_policy_denied`
- `missing_preview_evidence`
- `missing_approval_token`
- `provider_adapter_mismatch`
- `provider_adapter_not_bound`
- `provider_adapter_not_configured`
- `provider_adapter_cannot_execute`
- `audit_ledger_not_persistent`

The action is allowed only after all checks pass.

## Composio Adapter Mapping

Composio should enter Wiii through this contract:

```text
Composio toolkit catalog
  -> Wiii registry entry
Composio adapter capability
  -> Wiii authorization URL decision
  -> Wiii OAuth/session handoff
Composio connected account
  -> Wiii connection record
Composio tool/action schema
  -> Wiii curated action allowlist
Composio execute
  -> Wiii execution gateway -> adapter call
```

Wiii must not expose Composio's broad meta-tools directly to normal chat. The
path governor selects the product path first. Only then may a scoped integration
agent receive curated action schemas for the selected provider.

Execution preflight and execution calls must pass an explicit Wiii opaque
`connection_ref` (`wcn_*`). They must not accept raw provider connected-account
IDs or fall back to the latest stored account for a provider. This keeps
multi-account integrations deterministic and matches the source-audited
OpenHuman/Composio pattern where connection state is visible first, then a
specific connected account is chosen before tools run.

## OAuth And Vault Requirements

Before real Composio OAuth is enabled:

- backend settings must explicitly set `enable_wiii_connect_composio`, provide a
  Composio project API key, and map provider slugs to Composio auth config IDs;
- `POST /api/v1/wiii-connect/providers/{slug}/authorization-url` must require
  Wiii authentication before any provider call;
- Wiii must use Composio hosted Connect Link
  `/api/v3.1/connected_accounts/link` for Composio-managed OAuth instead of the
  older direct initiate flow;
- provider connection readiness must stay separate from `agent_ready`; account
  connection can be enabled before any curated action schema is exposed to an
  agent;
- Wiii backend must create authorization sessions with state and nonce;
- session start must return a backend decision first, and the frontend must
  never call Composio directly;
- connection polling must call Wiii backend only; Wiii backend may call
  Composio `GET /api/v3.1/connected_accounts` with user/auth-config filters and
  then upsert sanitized records into Wiii storage;
- authorization URLs must come from a bound provider adapter decision, not from
  raw frontend input or ad hoc session arguments;
- Wiii must append signed `wiii_state` to the provider callback URL before
  calling Composio, and callbacks must verify that state before any connection
  upsert;
- user-requested disconnect must call Wiii backend only. Wiii must fetch the
  stored connection by org/user/provider, disable the local connection before
  provider cleanup, then call Composio connected-account delete from the backend
  and audit both started and completion states;
- provider polling must not reanimate a locally disabled
  `user_disconnect_requested` row if Composio still reports the account active
  during cleanup or eventual consistency windows;
- stale `authorizing`, `waiting`, and `error` local OAuth rows are expired by
  the backend under the Wiii org/user/provider boundary before readiness,
  listing, or execution checks rely on local connection state;
- authorization URL decisions may consume durable audit readiness only from an
  explicit storage probe or backend-controlled storage status, never from
  frontend claims;
- disabled providers must return a blocked decision with missing requirements;
- missing connection requirements block OAuth/session start, while missing
  agent-ready requirements only block tool/action exposure;
- callback handling must validate Wiii-owned signed state before trusting
  provider error/status fields, and must stay blocked until signed state
  validation, provider-managed connection reference or code presence, vault
  storage, and provider adapter exchange are ready;
- callback/webhook handling must bind provider account to Wiii org/user;
- credential material must be stored in an encrypted vault or provider-managed
  backend secret store;
- every session/callback/vault/execution decision must produce a privacy-safe
  ledger record shape and be eligible for durable append before provider
  execution is allowed;
- execution decisions must be requested through the authenticated Wiii backend
  gateway and must fetch the connection record from Wiii storage by org/user;
- real action execution must be requested through
  `POST /api/v1/wiii-connect/providers/{slug}/execute`, not direct Composio
  calls from frontend or chat;
- read-only Composio execution must verify the live tool schema before the
  provider call, block if required schema argument keys are missing, and append
  privacy-safe started plus completion audit events when execution proceeds;
- credentialed acceptance evidence must record only structured hash/count
  observations for selected-account presence, gateway decisions, live schema
  readiness, required argument coverage, provider execution metadata, and
  privacy flags; it must not archive connection refs, account IDs, bearer
  values/env names, raw schemas, provider arguments, provider payloads, or
  provider responses;
- durable persistence must bind every connection/audit write to a Wiii
  organization and user boundary;
- frontend may receive connect URLs and state labels, not tokens;
- stale pending/error OAuth rows must be cleaned up or expired safely; the
  current backend policy marks stale `authorizing`, `waiting`, and `error`
  rows as `expired` before readiness/listing/execution control-plane checks;
- provider errors must be sanitized before reaching UI or chat;
- Composio action execution must remain disabled unless the provider has a
  curated read-only action allowlist, live schema verification, scope policy,
  execution gateway approval, persistent audit, and a stored connected account.

## Write And Apply Requirements

External writes are never casual chat behavior. They require:

- selected path allows external action;
- action slug is curated;
- user/org scope grants allow the mutation class;
- preview evidence when the adapter marks it required;
- approval token presence for apply-style mutations;
- durable operation approval consumption when the optional approval ledger table
  is present;
- audit event before execution and after completion.

The gateway stores only token presence and evidence IDs in public metadata. Raw
approval tokens and provider payloads must remain outside chat lifecycle data.

## Next Slices

1. Add a curated Composio action catalog contract for one low-risk read-only
   provider action. Done for Gmail; local live acceptance passed with real
   credentials and a connected account.
2. Bind Composio adapter `can_execute_actions` only for that curated read-only
   action and keep writes disabled. Done for the backend boundary; local live
   Gmail execution acceptance passed.
3. Add disconnect/delete/reconnect lifecycle controls behind the same policy.
   Backend disconnect and desktop lifecycle controls are implemented. Facebook
   connection-only OAuth/listing acceptance passed locally; optional disconnect
   remains an explicit operator run when cleanup is desired.
4. Add acceptance for connect, denied execute, gated scope, and reconnect cases.
   A backend/operator harness now exists at
   `maritime-ai-service/scripts/wiii_connect_composio_acceptance.py` for
   adapter/storage/audit/connect/list/read-only-execute/disconnect checks. Live
   local Gmail browser acceptance passed: Wiii Connect rendered connected,
   Agent-ready/read-only readiness, gateway allowed, and no raw `wcn_*`, auth
   config, token, API key, or client secret markers.
5. Expire stale local OAuth rows before real rollout. Done for stale
   `authorizing`, `waiting`, and `error` rows at the durable storage/API
   boundary.

For production or staging, Composio remains a controlled rollout: configure the
same flags/secrets in the target environment and rerun #780 acceptance against
that deployed backend before enabling general users.
