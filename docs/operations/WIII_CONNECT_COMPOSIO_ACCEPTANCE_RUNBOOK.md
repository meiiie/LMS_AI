# Wiii Connect Composio Acceptance Runbook

Status: Active

Owner: Project leadership

Last updated: 2026-05-28

Scope: operator acceptance for enabling Composio through Wiii Connect

## Purpose

This runbook proves that Composio is entering Wiii through Wiii Connect policy,
not through direct frontend calls or broad chat tools.

The acceptance harness is:

```text
maritime-ai-service/scripts/wiii_connect_composio_acceptance.py
```

It calls only Wiii backend endpoints. It does not call Composio directly. Normal
output redacts bearer tokens, authorization URLs, callback state, connection
IDs, vault references, and provider credentials.

## Required Backend Configuration

Set these in the backend deployment environment, not in git:

```text
enable_wiii_connect_composio=true
composio_api_key=<Composio project API key>
composio_auth_config_map={"gmail":"<Composio Gmail auth_config_id>"}
enable_wiii_connect_composio_readonly_execute=true
composio_readonly_action_allowlist={"gmail":["GMAIL_FETCH_EMAILS"]}
```

The committed `.env.example` files use uppercase environment variable names for
operator convention. The backend settings loader is case-insensitive, so those
uppercase names map to the lowercase settings shown above. Never place real
Composio API keys or auth config IDs in committed example files.

The database must also have migration `049_create_wiii_connect_storage.py`
applied so these tables exist:

```text
wiii_connect_connections
wiii_connect_audit_ledger
```

Do not enable write/apply/admin actions in this phase.

## Acceptance Sequence

Run from `maritime-ai-service/`.

Before issuing a Connect Link manually, check activation readiness through Wiii:

```powershell
curl -H "Authorization: Bearer <jwt>" "http://localhost:8080/api/v1/wiii-connect/providers/gmail/activation-readiness?probe_database=true"
```

The response must be treated as the operator preflight. It does not contact
Composio, does not create an OAuth session, and does not expose raw connection
IDs or secrets. `ready_to_connect=true` means Wiii has enough local policy,
adapter, vault, storage, and audit readiness to issue a backend-owned Connect
Link. `ready_to_execute_readonly=true` additionally requires a live stored
connection and a runtime-enabled curated read-only action.

The acceptance harness enforces the same projection automatically:

- every run requires activation readiness to report `ready_to_connect=true`
  before Connect Link issuance;
- runs with `--require-execution-ready` or `--execute-readonly` also require
  activation readiness to report `ready_to_execute_readonly=true` for the
  selected connection before provider execution.

Before secrets are available, operators can run a dry readiness report that
does not issue a Connect Link, list provider accounts, execute provider actions,
or disconnect anything:

```powershell
python scripts/wiii_connect_composio_acceptance.py --backend-url http://localhost:8080 --auth-mode dev-login --provider gmail --readiness-report-only
```

The report prints `ready_to_connect`, `ready_to_execute_readonly`, and failed
activation gates with `required_next` hints. It is designed for preflight and
environment setup; it is not a substitute for the live acceptance sequence.

For PR or issue evidence, write the optional sanitized JSON artifact to a local
temporary path:

```powershell
python scripts/wiii_connect_composio_acceptance.py --backend-url http://localhost:8080 --auth-mode dev-login --provider gmail --readiness-report-only --target-env local --commit-sha <deployed-commit> --evidence-json "$env:TEMP\wiii-connect-composio-acceptance.json"
```

The JSON includes check names, pass/fail status, elapsed time, target label,
deployed commit, and whether a connection was selected for action execution. It
intentionally strips bearer tokens, Connect URLs, callback state, raw connection
IDs, vault references, and provider payloads. Do not commit generated evidence
files; attach or summarize the sanitized output in the issue/PR when needed.

For local dev-login:

```powershell
python scripts/wiii_connect_composio_acceptance.py --backend-url http://localhost:8080 --auth-mode dev-login --provider gmail --print-connect-url
```

For staging or production with a JWT:

```powershell
$env:WIII_ACCEPTANCE_BEARER_TOKEN="<jwt>"
python scripts/wiii_connect_composio_acceptance.py --backend-url https://wiii.example.com --auth-mode bearer --provider gmail --print-connect-url
```

The `--print-connect-url` output is operator-only. Open it, complete Gmail OAuth,
then rerun without printing the link:

```powershell
python scripts/wiii_connect_composio_acceptance.py --backend-url http://localhost:8080 --auth-mode dev-login --provider gmail --expect-connected --require-execution-ready
```

To execute the read-only action after the live Composio schema is known, pass
arguments matching that schema:

```powershell
python scripts/wiii_connect_composio_acceptance.py --backend-url http://localhost:8080 --auth-mode dev-login --provider gmail --expect-connected --require-execution-ready --execute-readonly --arguments-json '{"max_results":1}'
```

If the schema uses different argument names, do not change Wiii code blindly.
Pass the live schema-compatible JSON through `--arguments-json` and record the
accepted shape in the PR or release note.

Optional disconnect acceptance:

```powershell
python scripts/wiii_connect_composio_acceptance.py --backend-url http://localhost:8080 --auth-mode dev-login --provider gmail --expect-connected --disconnect
```

Disconnect is intentionally explicit because it disables the local Wiii
connection row before provider cleanup.

## Pass Criteria

Composio is ready to enable only when all of these are true:

- adapter readiness reports `authorization_ready=true`;
- storage readiness reports persistent connection and audit tables;
- audit readiness reports `persistent=true`;
- activation readiness reports `ready_to_connect=true` before OAuth and
  `ready_to_execute_readonly=true` after OAuth plus action allowlist;
- stale local `authorizing`, `waiting`, and `error` OAuth rows are expired by
  the Wiii backend before readiness/listing/execution checks use local
  connection state;
- provider registry returns Gmail as a Composio provider;
- curated actions include only the intended read-only action;
- execution gateway blocks a missing-connection execution request;
- execution gateway blocks execution when no explicit connection id is selected;
- the acceptance harness treats any missing-selection deny reason other than
  `connection_selection_required` as a failed policy proof;
- Connect Link is issued by Wiii backend;
- after OAuth, connection listing returns an active connected account;
- connection listing returns an opaque `connection_ref`, not the raw provider
  connected-account ID;
- execution gateway allows the selected read-only action only for the stored
  org/user connection;
- optional execution succeeds through `POST /api/v1/wiii-connect/providers/gmail/execute`;
- optional disconnect disables local Wiii state and completes provider cleanup.

## Failure Interpretation

Common blocked reasons:

| Reason | Meaning |
|---|---|
| `provider_adapter_not_configured` | Missing Composio API key or auth config map. |
| `audit_ledger_not_persistent` | Migration or database connection is missing. |
| `connection_selection_required` | The caller has not selected a stored provider connection id for execution. |
| `connection_missing` | OAuth has not completed or the selected connection does not belong to this org/user. |
| `provider_not_agent_ready` | Read-only action execution is not enabled for the curated allowlist. |
| `action_not_allowed` | The action is not in Wiii's curated catalog for that provider. |
| `missing_scope` | The stored connection lacks the required scope grant. |
| `tool_schema_not_found` | Composio's live schema does not match the curated action/provider. |

Treat provider errors as acceptance failures until the sanitized reason is
understood. Do not expose raw provider responses in chat or frontend UI.

## Rollback

Disable the feature flags:

```text
enable_wiii_connect_composio=false
enable_wiii_connect_composio_readonly_execute=false
```

Keep the tables and audit records. They contain only Wiii control-plane metadata
and are useful for incident review. Revoke/delete the provider connection
through the Wiii Connect UI or the harness `--disconnect` path.

## Source Notes

Composio's current connected-account API documents hosted auth link creation at
`POST /api/v3.1/connected_accounts/link`, connected-account listing, and
connected-account delete. The legacy direct connected-account creation path is
documented as deprecated for Composio-managed OAuth, which is why Wiii uses
Connect Link behind the backend adapter.
