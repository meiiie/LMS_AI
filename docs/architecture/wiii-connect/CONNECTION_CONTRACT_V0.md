# Wiii Connect Contract V0

Status: Draft for implementation

Owner: Architecture maintainers

Created: 2026-05-27

Related issue: #720

## Purpose

This document defines the first shared data contract for Wiii Connect. It is the
shape that backend runtime policy, frontend capability UI, and later provider
adapters should converge on.

V0 is observational and policy-facing. It must not carry secrets, raw user
content, raw document text, provider request bodies, provider response bodies,
or approval tokens.

## Connection Snapshot

```text
WiiiConnectionSnapshot
  version
  generated_at
  surface
  connections[]
  path_capabilities[]
  warnings[]
```

### Connection Record

```text
WiiiConnection
  id
  provider_kind
  slug
  label
  status
  agent_ready
  scopes
  capabilities
  required_for_paths
  source
  last_checked_at
  reason
  warnings
```

Allowed `provider_kind` values:

- `wiii_native`
- `composio`
- `mcp`
- `custom_oauth`
- `workflow`

Allowed `status` values:

- `connected`
- `not_connected`
- `pending`
- `expired`
- `error`
- `preview`
- `disabled`

Allowed scope booleans:

- `read`
- `preview`
- `write`
- `apply`
- `admin`

## V0 Native Connections

| Slug | Provider kind | Meaning |
|---|---|---|
| `server` | `wiii_native` | Backend reachable from current client. |
| `host` | `wiii_native` | Desktop/embed host context is present. |
| `host_actions` | `wiii_native` | Host bridge exposed callable actions. |
| `lms_authoring` | `wiii_native` | LMS authoring preview/apply path is available. |
| `document_corpus` | `wiii_native` | Uploaded or indexed document context is present. |
| `pointy` | `wiii_native` | Pointy target inventory or mode is available. |
| `web_search` | `wiii_native` | Web search provider can be bound. |
| `weather` | `wiii_native` | Weather provider can be bound or fail-closed. |
| `visual_runtime` | `wiii_native` | Inline visual/article figure tools can be bound. |
| `code_studio` | `wiii_native` | Code Studio app/artifact tools can be bound. |

## Path Capability Record

```text
WiiiPathCapability
  path
  allowed_connection_slugs
  required_connection_slugs
  allowed_tool_groups
  forbidden_tool_groups
  mutation_policy
  delegation_policy
```

Allowed `mutation_policy` values:

- `none`
- `preview_only`
- `approval_token_required`
- `explicit_user_confirmation_required`

Allowed `delegation_policy` values:

- `direct_only`
- `delegate_to_path_agent`
- `delegate_to_integration_agent`

## Required Path Rules

| Path | Required connection | Mutation policy | Notes |
|---|---|---|---|
| `casual_chat` | none | `none` | No broad tool binding. |
| `weather_lookup` | `weather` | `none` | No generic web fallback unless user asks. |
| `web_search` | `web_search` | `none` | Explicit live/current/search intent only. |
| `document_grounded_answer` | `document_corpus` | `none` | No unsupported outside facts. |
| `lms_document_preview` | `lms_authoring` | `preview_only` | Must preserve citations/source refs. |
| `lms_document_apply` | `lms_authoring` | `approval_token_required` | Never execute without host-issued approval evidence. |
| `host_ui_action` | `host_actions` | `explicit_user_confirmation_required` | Host control must be audited. |
| `pointy_guidance` | `pointy` | `none` | Only explicit Pointy-like turns. |
| `visual_generation` | `visual_runtime` | `none` | Do not bind Pointy click tools. |
| `code_studio_output` | `code_studio` | `none` | Use Code Studio path tools only. |
| `external_app_action` | external provider slug | path-specific | Delegate to integration agent after connection verification. |

## Privacy Rules

The snapshot may contain:

- connection slug and status
- capability names
- scope booleans
- counts
- warning codes
- hashed or opaque connection identifiers
- high-level reason strings

The snapshot must not contain:

- OAuth access or refresh tokens
- API keys
- raw approval tokens
- uploaded document text
- raw user messages
- raw assistant messages
- provider request/response bodies
- personally identifying account fields unless explicitly allowed by the
  surface and sanitized for UI

## Relationship To Existing Runtime

Existing Wiii code already has several pieces of this direction:

- `ToolCapabilityRegistry` describes tool policy metadata.
- `ToolPolicySession` records per-turn tool visibility and connection status.
- `TurnPathDecision` chooses the path before tools are bound.
- Frontend `CapabilityStatusBar` displays server, host, LMS, Pointy, and path
  state.

Wiii Connect V0 should consolidate these pieces behind one snapshot instead of
creating a parallel status system.

## SSE Runtime Projection

The first frontend-facing projection is additive on the existing SSE V3
`chat_lifecycle` event:

```text
chat_lifecycle.capabilities.wiii_connect = WiiiConnectionSnapshot
```

## Host Action Result Bridge

Wiii host actions are two-phase:

1. Backend tool loop emits `host_action` with an opaque `request_id`, action
   name, and sanitized params.
2. Frontend/host executes the action through the declared bridge or local Wiii
   Connect adapter.
3. Frontend submits a sanitized `HostActionResultRequest` to
   `/api/v1/host-actions/result`.
4. Backend resumes the in-flight turn when the `request_id`, action, user, and
   organization match a pending waiter.

This mirrors OpenHuman's parked approval/tool-result pattern without allowing
the frontend to self-grant scope. Connection, scope, gateway, preview, and
approval policy still belong to backend Wiii Connect.

The result bridge may carry:

- `request_id`
- action name
- success boolean
- short summary
- error code/message
- sanitized result data

The result bridge must not carry:

- OAuth access or refresh tokens
- API keys
- raw approval tokens
- raw image base64
- provider secrets

If no pending waiter exists, the API acknowledges the submission as ignored.
That keeps older clients and non-continuation host actions backward-compatible.

This projection is for observability and browser acceptance only. It must use
the same privacy rules as the backend snapshot:

- no raw document text or filenames
- no raw user prompt
- no provider request/response bodies
- no API keys, OAuth tokens, or approval token values
- only connection status, capability labels, path policy, counts, warnings, and
  safe reason codes

Frontend storage must sanitize the projection again before persisting lifecycle
metadata. The UI may summarize connection rows and path counts, but should not
show raw tool schema payloads in chat.

## Desktop UX Projection

The desktop shell has a first-class `Wiii Connect` page for the same projection.
It is a read-only V0 control-plane view:

- the default `Danh bạ` view is a Connections catalog with provider tabs,
  category filters, search, cards, and a detail panel so users can see Wiii
  native capabilities next to future Composio/channel/MCP/workflow adapters;
- connection cards show provider kind, status, agent-ready state, scopes,
  capability counts, path usage, safe count metadata, and warnings;
- path policy shows required connection slugs, allowed/forbidden tool groups,
  mutation policy, and delegation policy;
- runtime diagnostics summarize observed/suppressed tool groups instead of raw
  tool names;
- external provider adapters are visible only as disabled rows until Wiii has a
  vault, permission gate, adapter contract, and execution audit for them. They
  must not show as connected just because another product such as OpenHuman can
  connect through Composio.

This page must not become a separate source of truth. Backend runtime policy,
SSE lifecycle metadata, chat dashboard chips, and the Wiii Connect page should
continue to read the same sanitized snapshot shape.

## Implementation Order

1. Add typed backend snapshot builders around current runtime status.
2. Add tests for snapshot privacy and fail-closed statuses.
3. Make `ToolPolicySession` consume snapshot connection status.
4. Surface snapshot to frontend runtime dashboard.
5. Add provider adapters after native paths are stable.
