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

Current session/status API projections:

```text
GET  /api/v1/wiii-connect/providers/{slug}/status
POST /api/v1/wiii-connect/providers/{slug}/sessions
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
Composio connect link / session authorize
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
- disabled providers must return a blocked decision with missing requirements;
- callback/webhook handling must bind provider account to Wiii org/user;
- credential material must be stored in an encrypted vault or provider-managed
  backend secret store;
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

1. Add OAuth callback/token-exchange placeholder that is still fail-closed until
   vault storage exists.
2. Add encrypted vault integration or provider-managed secret reference storage.
3. Add frontend connection modal that uses Wiii backend routes only.
4. Persist provider registry and connection records behind backend-owned storage.
5. Add browser acceptance for connect, poll, disconnect, gated scope, and denied
   execute cases.
6. Enable one low-risk read-only Composio action before any write action.
