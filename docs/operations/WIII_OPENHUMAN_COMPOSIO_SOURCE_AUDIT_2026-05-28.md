# Wiii OpenHuman Composio Source Audit

Status: Active reference audit

Owner: Project leadership

Created: 2026-05-27

Related issue: #730

## Scope

This audit records the OpenHuman and Composio patterns Wiii should adopt before
enabling real third-party actions through Wiii Connect.

It does not mean Wiii has enabled Composio. Wiii currently has a read-only
catalog and runtime status surface. Real OAuth and provider execution must wait
for the Adapter V1 gateway, vault, scope policy, and audit ledger.

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

Sources:

- https://docs.composio.dev/docs/how-composio-works
- https://docs.composio.dev/docs/configuring-sessions
- https://docs.composio.dev/docs/auth-configuration/connected-accounts
- https://docs.composio.dev/docs/composio-connect
- https://docs.composio.dev/reference/changelog

## OpenHuman Source Findings

Audited local reference clone:

```text
.Codex/external/reference-systems/openhuman
```

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
records. It still needs connection listing/polling, frontend modal UX, curated
action catalog, execution gateway hardening for real provider actions, and
end-to-end browser acceptance before Composio actions can be enabled for real
users.
