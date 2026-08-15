# Wiii Core system architecture

**Status:** Canonical
**Updated:** 2026-08-15
**Scope:** `maritime-ai-service`

## 1. Role in Wiii

Wiii Core is the service runtime behind account-backed Wiii Workbench, web and
embed clients, managed integrations, and organization-aware agent workflows.
It receives authenticated work, selects a bounded execution path, streams
inspectable events, and persists the records needed for continuity and audit.

Neko Chill can also connect directly to a local ACP provider. That local path
does not turn Wiii Core into the authority for the provider's durable session;
the workbench and provider follow their separate ACP ownership contract.

## 2. Logical architecture

```text
Clients and hosts
  desktop | web/embed | service clients | adapter webhooks
        |
        v
FastAPI entry + middleware
  request ID | auth | org context | rate limits | feature policy
        |
        v
Request lifecycle
  input -> session/context -> route -> execute -> present -> post-turn
        |
        +---- Wiii runtime / multi-agent lanes
        +---- retrieval and semantic memory
        +---- host actions and generated artifacts
        +---- Wiii Connect provider workers
        |
        v
Durable state and evidence
  PostgreSQL/pgvector | object storage | cache | optional graph | audit ledgers
```

## 3. Runtime boundaries

### API and middleware

`app/main.py`, the application factory, `app/api/v1/`, `app/auth/`, and
`app/core/` own transport and trust establishment. The middleware stack creates
correlation and tenant context before business logic executes. Routes must not
trust client-supplied identity or organization fields independently of that
context.

### Request lifecycle

`app/services/` owns orchestration around a turn: input normalization, session
resolution, model availability and policy, runtime invocation, presentation,
usage, and post-turn work. HTTP and SSE paths should share semantics even when
their presentation differs.

### Execution runtime

`app/engine/runtime/` defines Wiii-owned lanes and model contracts.
`app/engine/multi_agent/` owns planning, narrowed tool collections, direct and
delegated tool rounds, runtime provenance, and specialized document/visual
paths. Provider SDK details stay behind `app/engine/llm_providers/`.

### Retrieval and living state

Retrieval combines dense/sparse search, source policy, and optional graph
context. Semantic memory and living-agent systems operate under explicit user,
organization, lifecycle, and provenance rules. A stored fact is not
automatically model-visible; context assembly must select and record it.

### Host and Wiii Connect actions

Host actions represent capabilities supplied by the active client/host. Wiii
Connect represents external accounts and provider actions. Both are narrowed by
capability, policy, schema, approval, and authenticated context before
execution. Model-facing arguments exclude backend-owned selectors and secrets.

LMS, Composio, social channels, MCP servers, and future applications are
adapters. Provider connectivity never bypasses Wiii's policy and audit layer.

## 4. Data ownership

| Data | Authority | Required property |
| --- | --- | --- |
| User and organization | Wiii Org records | Server-authorized ownership |
| Conversation/thread | Session repositories | Ordered, attributable history |
| Model-visible context | Runtime event/provenance records | Reconstructable selection |
| Memory and insight | Living/memory repositories | User/org scope and source |
| External connection | Wiii Connect registry/vault | No model-visible secret |
| Approval | Backend-issued ledger/token | Bound to operation fingerprint and actor |
| Side-effect outcome | Tool/host action ledger | confirmed/failed/denied/unknown |
| Live evidence | Raw probe artifact + registry | Fresh, private, commit-attributable |

PostgreSQL is the primary relational authority. pgvector supports vector
retrieval. Object storage owns generated or ingested binary objects. Caches may
accelerate a result but cannot become the only copy of durable authority.

## 5. Security model

- Authentication establishes a canonical Wiii identity.
- Organization and resource authorization are enforced server-side.
- Host/adapter roles are local overlays, not platform-admin authority.
- Webhooks verify signatures over raw bytes before parsing.
- Mutations use preview/approval/apply where the capability supports it.
- Backend-owned account selectors, provider arguments, and credentials are not
  exposed to the model.
- Logs and evidence use hashes, counts, status, and bounded diagnostics instead
  of raw private content.
- Feature flags fail closed when a required service, migration, vault, or
  policy dependency is unavailable.

## 6. Reliability model

Every request carries correlation state across transport, runtime, tools, and
presentation. Tool calls have explicit start and terminal states. A crash or
timeout that prevents confirmation produces an unknown outcome rather than an
assumed retry. Post-turn work must not corrupt the already delivered response;
its failure is recorded separately.

Health endpoints separate process liveness, dependency readiness, and deeper
model/provider diagnosis. A healthy process does not imply every provider is
available.

## 7. Extension rules

Add a capability by choosing the owning boundary first:

- New model/provider behavior goes behind the provider and runtime contract.
- New knowledge behavior goes through ingestion, repositories, retrieval, and
  source presentation.
- New external application behavior becomes a Wiii Connect provider/action,
  not a globally bound tool.
- New host-only behavior becomes a declared host action with result audit.
- New persisted state requires a migration, repository boundary, tenancy tests,
  and rollback plan.

Avoid a second orchestration authority, direct provider calls from the API, UI-
only authorization, or feature-specific session stores.

## 8. Verification map

| Change | Minimum proof |
| --- | --- |
| Route/schema | API unit/contract tests and OpenAPI compatibility check |
| Runtime/tool routing | focused multi-agent/runtime tests and ledger assertions |
| Memory/retrieval | ownership, provenance, retrieval, and migration tests |
| External mutation | policy + preview/apply + replay/unknown-outcome tests |
| Tenant/auth | adversarial cross-user/cross-org tests |
| Live provider claim | guarded runtime evidence probe and registry validation |

See [System flow](SYSTEM_FLOW.md) for sequencing and the repository
[operating model](../../../docs/operations/WIII_SYSTEM_CONTROL_PLANE.md) for
cross-surface diagnosis.
