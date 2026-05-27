# Wiii Connect Adapter V1 Design

Status: Draft contract implemented

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
```

The vault policy and audit ledger contracts live in:

```text
maritime-ai-service/app/engine/wiii_connect/vault.py
maritime-ai-service/app/engine/wiii_connect/audit_ledger.py
```

The provider adapter readiness and authorization URL contract lives in:

```text
maritime-ai-service/app/engine/wiii_connect/provider_adapters.py
```

The durable storage contract and schema live in:

```text
maritime-ai-service/app/engine/wiii_connect/persistent_storage.py
maritime-ai-service/alembic/versions/049_create_wiii_connect_storage.py
```

Current session/status API projections:

```text
GET  /api/v1/wiii-connect/providers/{slug}/status
POST /api/v1/wiii-connect/providers/{slug}/sessions
POST /api/v1/wiii-connect/providers/{slug}/authorization-url
GET  /api/v1/wiii-connect/providers/{slug}/callback
GET  /api/v1/wiii-connect/provider-adapters/status
GET  /api/v1/wiii-connect/vault/status
GET  /api/v1/wiii-connect/audit-ledger/status
```

Frontend surfaces should consume this registry/snapshot projection instead of
inventing a separate external-provider source of truth. Until a provider has
OAuth, vault, scoped action catalog, gateway, and audit support, the registry
must keep that provider disabled and non-agent-ready.

## Core Entities

`WiiiConnectProviderRegistryEntry`

- provider slug, kind, auth mode, enabled state;
- whether it is agent-ready;
- path allowlist;
- curated action allowlist;
- provider-specific required fields;
- default scopes and safe public metadata.

`WiiiConnectVaultSecretRef`

- opaque pointer to credentials;
- never serializes secret values or vault paths to public metadata;
- lets UI and runtime know that a vault reference exists without exposing it.

`WiiiConnectConnectionRecordV1`

- provider slug, connection ID, normalized lifecycle state;
- granted scopes;
- optional vault reference;
- sanitized account label/reference only.

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
- never returns OAuth code, state value, token, client secret, or raw provider
  payload.

`WiiiConnectCallbackDecision`

- returns `blocked` or `accepted`;
- blocks disabled providers, provider errors, missing state, missing code, missing
  vault, or missing provider adapter;
- issues a vault reference only after vault and provider adapter are both ready.

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

`WiiiConnectAuthorizationUrlRequest`

- records only safe authorization request shape: state presence, redirect URI
  presence, requested scope flags, and sanitized metadata key names;
- does not store OAuth state, OAuth code, redirect URI value, token, client
  secret, or provider payload.

`WiiiConnectAuthorizationUrlDecision`

- returns `blocked` or `ready`;
- requires enabled provider, agent-ready registry entry, backend-created state,
  backend-bound redirect URI, bound/configured adapter, vault capability,
  persistent audit ledger, and an adapter-supplied authorization URL;
- rejects adapter/provider-kind mismatch before any OAuth handoff;
- direct session callers may not bypass adapter policy by passing a URL.

`WiiiConnectPersistentStorage`

- writes per-org, per-user connection records to `wiii_connect_connections`;
- appends privacy-safe provider/session/callback/vault/execution events to
  `wiii_connect_audit_ledger`;
- requires explicit `organization_id` and `user_id` before writing;
- stores only public vault-reference metadata, never raw vault paths or secret
  material;
- fails softly when the database or migration is unavailable, keeping providers
  blocked instead of allowing un-audited execution.

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

`connected` is only transport/auth state. `agent_ready` requires all of:

1. provider registry entry is enabled;
2. provider registry entry is marked agent-ready;
3. live connection belongs to the same provider slug;
4. live connection state is `connected`;
5. runtime path and action are allowed by the gateway.

This follows the useful OpenHuman pattern while keeping Wiii's stronger LMS,
tenant, and host-action safety boundary.

## Gateway Deny Reasons

The gateway denies by default. Current reason codes:

- `provider_disabled`
- `provider_not_agent_ready`
- `connection_missing`
- `connection_provider_mismatch`
- `connection_not_connected`
- `path_not_allowed`
- `action_not_allowed`
- `missing_scope`
- `missing_preview_evidence`
- `missing_approval_token`

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

## OAuth And Vault Requirements

Before real Composio OAuth is enabled:

- Wiii backend must create authorization sessions with state and nonce;
- session start must return a backend decision first, not let the frontend call
  Composio directly;
- authorization URLs must come from a bound provider adapter decision, not from
  raw frontend input or ad hoc session arguments;
- disabled providers must return a blocked decision with missing requirements;
- callback handling must stay blocked until state/code validation, vault storage,
  and provider adapter exchange are ready;
- callback/webhook handling must bind provider account to Wiii org/user;
- credential material must be stored in an encrypted vault or provider-managed
  backend secret store;
- every session/callback/vault/execution decision must produce a privacy-safe
  ledger record shape and be eligible for durable append before provider
  execution is allowed;
- durable persistence must bind every connection/audit write to a Wiii
  organization and user boundary;
- frontend may receive connect URLs and state labels, not tokens;
- stale pending/error OAuth rows must be cleaned up or expired safely;
- provider errors must be sanitized before reaching UI or chat.

## Write And Apply Requirements

External writes are never casual chat behavior. They require:

- selected path allows external action;
- action slug is curated;
- user/org scope grants allow the mutation class;
- preview evidence when the adapter marks it required;
- approval token presence for apply-style mutations;
- audit event before execution and after completion.

The gateway stores only token presence and evidence IDs in public metadata. Raw
approval tokens and provider payloads must remain outside chat lifecycle data.

## Next Slices

1. Wire Wiii Connect status/authorization decisions to the durable store with a
   controlled DB probe, not per-render UI guessing.
2. Add encrypted vault integration or provider-managed secret reference storage.
3. Add provider adapter implementation/configuration for one provider broker
   without enabling broad action execution.
4. Add frontend connection modal that uses Wiii backend routes only.
5. Persist provider registry and connection records behind backend-owned storage.
6. Add browser acceptance for connect, poll, disconnect, gated scope, and denied
   execute cases.
7. Enable one low-risk read-only Composio action before any write action.
