# Wiii project mental model

Wiii is an open AI workbench and durable agent runtime. It brings conversations,
models, tools, files, memory, artifacts, permissions, and connected systems into
one inspectable workspace.

## Product names

| Name | Meaning |
| --- | --- |
| **The Wiii Lab** | Organization and publisher |
| **Wiii** | Platform, runtime, and stable technical namespace |
| **Wiii Workbench** | Desktop/web workspace used by people |
| **Wiii Cloud** | Account-backed managed mode |
| **Neko Chill** | No-account local-agent workspace inside Wiii Workbench |
| **Neko** | Mascot and product companion |
| **Neko Core** | One ACP-compatible local runtime provider |
| **Wiii Connect** | Governed boundary for external systems and capabilities |

LMS is a supported Wiii Connect adapter. It is not the product category, the
runtime architecture, or the default user journey.

## The six layers

### Wiii Core

Owns the current turn: API entry, model selection, routing, retrieval, tool
execution, structured output, and streaming. Core must be deterministic about
which path executed and must expose enough events to diagnose it.

### Wiii Living

Owns continuity beyond the current turn: memories, user facts, goals, emotional
state, reflections, scheduled work, and post-turn lifecycle. Living state must
remain attributable to a user and organization and must not silently become
prompt context.

### Wiii Host

Owns the environment where work is visible: desktop, web/embed, project files,
previews, artifacts, and host actions. The host presents permissions and
outcomes; it does not invent successful tool results.

### Wiii Connect

Owns external capability discovery, connection readiness, narrowed action
schemas, approval, execution policy, and audit. ACP, MCP, OAuth applications,
LMS, documents, and workflow systems enter Wiii through explicit contracts.

### Wiii Org

Owns identity, tenants, roles, settings, feature policy, ownership, and audit
boundaries. Client-supplied organization or user identifiers are never trusted
without server-side authorization.

### Wiii Data

Owns durable records and retrieval substrate: PostgreSQL/pgvector, optional
graph context, object storage, caches, migrations, and evidence artifacts.

## The two session authorities

Wiii Workbench owns the visible local transcript, workspace, and UI event log.
An ACP provider owns its provider session and opaque continuation state. Wiii
stores the provider session identifier alongside its local session and resumes
it after process replacement. It never duplicates the visible transcript by
blindly loading provider history into an already restored UI.

A fact can influence a model only after it enters the ordered model-visible
event stream. UI-only state, an unrecorded tool response, or an inferred crash
outcome is not model knowledge.

## The side-effect rule

A mutation is recorded before execution. Its terminal state is one of:

- confirmed success;
- confirmed failure;
- denied or cancelled;
- `unknown_outcome` after interruption.

Unknown mutations are investigated or explicitly retried by the user. They are
never silently replayed.

## What “done” means

A feature is complete when:

1. its owning layer and source of truth are clear;
2. the user can see relevant state and failure modes;
3. persistence and restart behavior are defined;
4. permissions and tenant boundaries fail closed;
5. focused tests prove local behavior;
6. live claims have raw, privacy-safe evidence;
7. release and rollback effects are documented.

Use the [codebase map](architecture/WIII_CODEBASE_MAP.md) to find the owner and
the [operating model](operations/WIII_SYSTEM_CONTROL_PLANE.md) to diagnose a
cross-layer failure.
