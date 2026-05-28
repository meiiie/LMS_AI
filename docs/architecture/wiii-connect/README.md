# Wiii Connect Blueprint

Status: Draft for implementation

Owner: Architecture maintainers

Created: 2026-05-27

Related issue: #720

## Purpose

Wiii Connect is the planned connection and capability control layer for Wiii.
It exists so Wiii can reason about external apps, LMS, host bridges, documents,
visual runtimes, and future MCP tools through one contract instead of scattered
tool-specific checks.

The immediate goal is not to clone Composio. The immediate goal is to give Wiii
its own connection registry, capability snapshot, and path governor so runtime
tools can fail closed and UI can show what is actually connected.

## Product Decision

Start Wiii Connect inside the Wiii monorepo.

Create a separate `wiii-connect` repository later only after the contracts are
stable enough that package boundaries help more than they slow product repair.

Rationale:

- The first Wiii Connect providers are Wiii-native: LMS, desktop host,
  document corpus, Code Studio, Pointy, and runtime path policy.
- Those providers must be tested against current Wiii chat, SSE, preview/apply,
  and host bridge flows.
- Extracting too early would add versioning, packaging, and deployment overhead
  before the core contract is proven.
- External systems such as Composio, MCP, Nango, Klavis, Activepieces, n8n, and
  Windmill should inform provider adapters, not replace Wiii's safety model.

## OpenHuman Pattern To Adopt

OpenHuman uses Composio underneath, but its important architectural move is the
connection discipline around Composio:

1. Connections are visible runtime state, not hidden prompt assumptions.
2. Connected is distinct from agent-ready.
3. Main chat does not hold every integration action schema.
4. The orchestrator sees a small delegation handle and a set of connected
   toolkit slugs.
5. The toolkit-scoped integration agent receives the real action schemas only
   after the toolkit is selected and verified.
6. UI connection flow is a state machine: disconnected, authorizing, waiting,
   connected, expired, error, disconnecting.
7. Scope and permission toggles gate what actions the agent may call.

Wiii should adopt those rules. Wiii should not copy OpenHuman code or inherit a
personal-agent trust boundary that does not fit LMS, org, and host control.

## Provider Model

Wiii Connect should treat every connector as a provider behind a Wiii-owned
contract.

| Provider kind | Examples | Ownership |
|---|---|---|
| `wiii_native` | LMS, desktop host, document corpus, Code Studio, Pointy | Wiii owns contract and policy |
| `composio` | Facebook, Gmail, Notion, Slack, GitHub through Composio | Wiii owns policy; Composio brokers OAuth/actions |
| `mcp` | Remote or local MCP servers | Wiii owns visibility and permission gating |
| `custom_oauth` | Future Wiii-owned OAuth apps such as Facebook app branded as Wiii | Wiii owns OAuth, token vault, review, policy |
| `workflow` | Activepieces, n8n, Windmill, Pipedream-style workflow bridges | Wiii owns action exposure and approval gates |

Composio is therefore an adapter, not the foundation. Wiii-native providers must
continue working without Composio.

## Runtime Shape

The target runtime flow is:

```text
host/request context
  -> connection registry
  -> capability snapshot
  -> path governor
  -> delegated path/toolkit agent
  -> narrowed tool/action schema
  -> execution gateway
  -> audit/ledger/stream metadata
```

The main chat path should not bind broad tool surfaces. It should choose the
active product path first, then bind only the tools allowed by the current
connection and capability snapshot.

## V0 Scope

Wiii Connect V0 should stay small:

- Define typed connection and capability snapshot records.
- Normalize current runtime status for server, host bridge, LMS authoring,
  host actions, Pointy, document corpus, web/weather/search, and visual/Code
  Studio paths.
- Feed `ToolPolicySession` and `TurnPathDecision` from the same snapshot shape.
- Expose the snapshot to the frontend runtime dashboard without leaking tokens,
  raw documents, prompt text, or provider payloads.
- Keep all mutating tools behind preview and approval evidence.
- Record enough metadata in runtime ledgers to debug wrong-path behavior.

## Current UX Surface

The first product-facing Wiii Connect surface lives inside the desktop shell as
the `Wiii Connect` page. It is an observability and governance page, not a
third-party OAuth console yet.

The page must:

- present a Connections catalog with provider tabs (`Wiii native`, `Composio`,
  `Channels`, `MCP Servers`, and workflow bridges), category filters, search,
  connection cards, and a read-only detail panel;
- read only the sanitized `chat_lifecycle.capabilities.wiii_connect` snapshot;
- show connection status, agent-ready state, scopes, counts, warnings, and path
  policy in grouped UI;
- summarize tool/provider state without exposing raw tool schemas, provider
  payloads, document text, approval token values, OAuth tokens, or API keys;
- show external providers such as Composio, MCP, custom OAuth, and workflow
  bridges as disabled catalog entries until a vault, permission gate, provider
  adapter, and execution audit exist;
- stay observational until backend execution gateways and reviewable adapter
  contracts are implemented.

V0 must not:

- Build native Facebook/Gmail OAuth connectors.
- Store third-party OAuth tokens before an encrypted vault and revocation model
  exist.
- Let any provider adapter bypass Wiii's path governor.
- Make production LMS mutations possible without `approval_token`.

## Fail-Closed Product Rules

| Surface | Rule |
|---|---|
| LMS preview | Requires active LMS/host authoring connection. |
| LMS apply | Requires active LMS connection, write/apply scope, preview evidence, and `approval_token`. |
| Host actions | Require host bridge capability presence for this surface. |
| Pointy | Must not execute for code, visual, simulation, artifact, or LMS authoring output paths unless explicitly allowed by that path. |
| Document-grounded chat | If uploaded documents are the active source, do not invent outside facts or silently fall back to web search. |
| Web/weather/search | Bind only for explicit live/current/search intent, not generic conversation drift. |
| External apps | If not connected, tell the user to connect the app in Wiii Connections. Do not fake a live app answer from stale memory. |
| External writes | Require explicit scope, preview when available, and action audit. |

## Extraction Criteria

Create a standalone `wiii-connect` repository only when all of these are true:

- V0 contract is stable across backend tests and frontend dashboard.
- At least two Wiii-native providers use the same registry shape.
- At least one external adapter, such as Composio or MCP, uses the same shape.
- Runtime ledgers show connection/capability decisions without raw secrets.
- CI can test contract packages without booting the full product stack.
- Maintainers agree that versioned packages reduce coupling instead of adding
  integration friction.

Until then, Wiii Connect remains an architecture and implementation area inside
this repository.

## Next Implementation Slices

1. Add a backend `wiii_connect` contract module that emits a privacy-safe
   capability snapshot from existing LMS, host, weather, document, Pointy, and
   tool policy state.
2. Update `ToolPolicySession` to consume the snapshot as the source of
   connection status instead of building ad hoc connection maps.
3. Extend the frontend Wiii Connect page/runtime dashboard to display the same
   snapshot, grouped by provider and path. Initial catalog UX now exists; keep
   it read-only until real provider adapters exist.
4. Add tests proving that LMS apply, Pointy, web/weather, document-grounded
   chat, and visual/Code Studio paths bind only the right tools.
5. Use `ADAPTER_V1_DESIGN.md` as the contract for external providers. Composio
   connection can be enabled only after registry, vault/provider-managed
   secrets, OAuth/session callback, storage, and audit checks are ready. Agent
   action execution remains disabled by default and can only be enabled for a
   curated read-only allowlist after schema verification and execution gateway
   approval.
6. Keep the backend `provider_registry.py` as the source of truth for disabled
   external provider catalog entries; frontend catalog state should converge on
   this projection.
7. Add one low-risk read-only Composio action through the gateway before any
   write/apply action. The backend boundary now supports one curated Gmail
   read-only action behind config, schema verification, gateway, and audit; the
   remaining work is live credential acceptance and disconnect/reconnect UX.
