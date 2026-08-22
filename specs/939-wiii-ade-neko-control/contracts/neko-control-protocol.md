# Neko Control Protocol v1

Status: foundation contract; first transport is the existing Tauri command and
event bridge. A standalone daemon is explicitly not claimed by this version.

## Boundary

```text
Wiii ADE client
    |
    | Neko Control Protocol
    v
Neko execution authority
    |
    +-- Codex App Server adapter
    +-- ACP v1 adapter
    `-- future native / SDK / CLI / PTY adapters
```

Provider protocols never leak into ADE task identity. Neko normalizes common
execution facts and preserves bounded provider extensions.

## Envelope

Every request contains:

- `v`: `1`
- `requestId`: caller-generated stable correlation ID
- `method`: one supported method
- `params`: method-specific JSON object

Every response contains the same version and request ID plus exactly one of
`result` or `error`. Unknown versions and methods fail before side effects.

## Methods

| Method | Purpose | Side effect |
| --- | --- | --- |
| `initialize` | Negotiate protocol and client facts | no |
| `provider/list` | Discover installed providers and readiness | no |
| `session/list` | Enumerate execution sessions | no |
| `session/start` | Start a provider session for one ADE run | yes |
| `session/resume` | Reattach an existing provider session | yes |
| `session/cancel` | Cancel the active turn/session operation | yes |
| `approval/resolve` | Commit a human/policy decision | yes |

The initial in-process client implements provider discovery/profile probing and
process transport through existing least-privilege Tauri commands. Remaining
session methods describe the stable daemon boundary and stay unavailable until
the server advertises them.

## Events

- `session.created`, `session.started`, `session.resumed`
- `run.state_changed`
- `message.started`, `message.delta`, `message.completed`
- `plan.updated`
- `tool.started`, `tool.updated`, `tool.completed`
- `terminal.output`
- `file.changed`
- `approval.requested`, `approval.resolved`
- `artifact.created`
- `usage.updated`
- `process.exited`

Events carry stable `eventId`, monotonic `seq`, timestamp, optional task/run/
session identity, normalized payload and bounded provider extensions. Event
ordering and persistence authority belong to the Neko server implementation,
not the WebView.

## Capability snapshot

Common fields:

```json
{
  "v": 1,
  "providerId": "codex",
  "providerVersion": "0.149.0",
  "integration": "native-structured",
  "protocol": "codex-app-server",
  "capabilities": {
    "resume": true,
    "fork": false,
    "modelSelection": true,
    "reasoning": true,
    "modes": false,
    "slashCommands": false,
    "approvals": true,
    "toolEvents": true,
    "usage": false,
    "diff": true,
    "subagents": false,
    "nativeReview": false,
    "sessionList": false,
    "sessionHistory": false,
    "backgroundWork": false
  },
  "extensions": {}
}
```

`false` means not established for that historical snapshot and therefore not
available to common UI. Extensions accept JSON scalar values only, have stable
keys, and must never contain secrets or raw provider events.

## Errors

Stable error codes:

- `unsupported_version`
- `unsupported_method`
- `provider_not_found`
- `provider_unavailable`
- `invalid_request`
- `invalid_state`
- `permission_required`
- `continuity_lost`
- `unknown_outcome`
- `internal_error`

Errors are data, not display strings. The Vietnamese UI derives actionable
copy from code plus safe details.

## Compatibility

- Adding optional fields or event methods is backward-compatible.
- Removing/renaming fields requires a new protocol version.
- Provider capability changes create a new session snapshot; they do not
  rewrite historical snapshots.
- ACP v1/v2 negotiation remains inside the ACP adapter.
