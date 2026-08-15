# Wiii Core request and event flow

**Status:** Canonical
**Updated:** 2026-08-15

## 1. Standard turn

```text
client
  -> FastAPI route
  -> request ID / auth / organization / rate-limit middleware
  -> input validation and session resolution
  -> context and capability snapshot
  -> runtime lane and model selection
  -> retrieval, memory, tools, or delegated worker
  -> response presentation
  -> durable conversation/runtime records
  -> bounded post-turn lifecycle
```

The same semantic turn may be presented as one JSON response or an ordered SSE
stream. Transport differences must not change identity, policy, tool approval,
or side-effect semantics.

## 2. Entry and trust establishment

1. The edge assigns or propagates a request identifier.
2. Authentication resolves the canonical user and authentication method.
3. Organization middleware resolves tenant context and permissions.
4. Route-level dependencies enforce the capability required by the endpoint.
5. Input models reject malformed or oversized data before runtime execution.

Host roles, connector IDs, target user IDs, and organization headers are hints
until matched to authenticated server-side state.

## 3. Context assembly

The input lifecycle resolves only context allowed for this turn:

- thread/session history;
- organization and domain configuration;
- uploaded document references;
- selected memory and retrieval results with source metadata;
- host capabilities declared by the active surface;
- Wiii Connect providers/actions that are connected and agent-ready;
- model/profile/reasoning policy.

Each selected fact must be attributable. State present only in a UI store,
database table, or connector response is not model-visible until the runtime
adds it to the ordered input/event record.

## 4. Lane and tool selection

The runtime chooses an execution lane before exposing tools. The main model
receives a small, relevant surface rather than every registered capability.

```text
intent + context + policy
  -> lane decision
  -> bounded tool/capability collection
  -> optional specialist/provider worker
  -> execution gateway
```

External application actions are provider-scoped. An available Facebook
connection cannot satisfy a Gmail request. A connected provider with no
effective actions is not agent-ready.

## 5. SSE presentation

`POST /api/v1/chat/stream/v3` emits ordered events representing meaningful
lifecycle changes. A typical consumer sees:

```text
request/session accepted
  -> reasoning/status deltas
  -> retrieval/source or artifact events
  -> tool/host-action start
  -> tool/host-action result, denial, failure, or unknown outcome
  -> answer deltas
  -> final usage/completion
```

The presenter sanitizes backend state into a stable public shape. The desktop
client projects events into transcript, status, tool cards, files, previews,
and artifacts. It must preserve event order and make terminal failures visible.

## 6. Read-only tool flow

1. Planner selects a tool from the effective collection.
2. Runtime validates the model arguments and injects backend-owned context.
3. Gateway applies policy and executes with bounded timeout.
4. Result is sanitized, recorded, and presented.
5. The model may synthesize a response from the recorded result.

A list-actions or readiness call is inventory, not completion of the user's
external task.

## 7. Mutating action flow

```text
model/user intent
  -> normalized operation plan
  -> preview or explicit approval request
  -> backend-issued operation fingerprint/token/ledger row
  -> apply with same actor + scope + operation
  -> consume approval before provider mutation
  -> execute once
  -> record confirmed result
```

Caller-supplied flags such as `approved=true` are not proof. Approval binds to
the authenticated actor, organization, provider/host, action, normalized
arguments, expiry, and preview evidence. Reusing a consumed approval is denied.

If execution begins but confirmation is lost, the ledger records
`unknown_outcome`. Automatic retry is prohibited until the external state is
reconciled or the user explicitly authorizes a new operation.

## 8. Documents, files, and artifacts

Uploaded documents produce bounded context and source references. Generated
course plans, code, HTML, Markdown, diagrams, or other outputs are artifacts,
not oversized chat strings. The host presents them in the workspace pane.

Document-to-course remains a host capability that can be supplied by an LMS
adapter. The core contract is preview-first: generate and inspect the plan,
then apply through a separately authorized action.

## 9. Post-turn lifecycle

After the user-visible response is finalized, bounded background work may write
usage, facts, memories, insights, schedules, or runtime diagnostics. These jobs
inherit the user/organization provenance of the turn. Failure is recorded and
retried only by its own idempotent policy; it cannot rewrite the already
delivered answer.

## 10. Failure handling

| Failure point | Required behavior |
| --- | --- |
| Authentication/tenant | Reject before runtime execution |
| Model/provider unavailable | Use allowed fallback or return explicit degraded error |
| Retrieval empty | Continue only if the lane permits; do not fabricate sources |
| Tool denied | Present denial and reason; no execution |
| Tool timeout before start | Fail without side effect |
| Mutation confirmation lost | Record `unknown_outcome`; no automatic replay |
| Stream interrupted | Preserve committed events and allow contract-safe resume |
| Post-turn job fails | Record separately; do not invalidate delivered answer |

## 11. Diagnosis

Trace one request using request ID, Wiii session/thread ID, runtime path, model,
tool-call/action ID, and artifact hash. Compare the first layer where expected
state diverges: presentation, transport, session/context, runtime, side effect,
then evidence. See the [Wiii operating model](../../../docs/operations/WIII_SYSTEM_CONTROL_PLANE.md).
