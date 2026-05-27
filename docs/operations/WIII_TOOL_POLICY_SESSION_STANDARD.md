# Wiii Tool Policy Session Standard

Status: Active

Owner: Backend maintainers

Last updated: 2026-05-26

Applies to: Direct chat tool binding, runtime tool execution, host actions, LMS authoring, Pointy, web/search, weather, product search, tutor, visual tools

## Purpose

Wiii must choose the active product path before exposing tools to a model. Tool
policy is the contract that prevents a casual chat turn from drifting into web
search, a weather turn from searching the wrong entity, Pointy from appearing in
code/visual output turns, or LMS mutation tools from appearing without host
connection and approval context.

The canonical backend shape is:

```text
query/context -> TurnPathDecision -> ToolPolicySession -> bound tools -> execution guard
```

`ToolCapabilityRegistry` is the policy metadata source underneath that shape.
Tool construction remains in the native tool modules, but connection,
approval, mutation, group, and surface-scope metadata must come from
`app.engine.tools.tool_capability_registry`.

Wiii Connect is the next consolidation layer for the same contract. The current
`connection_status` map is the V0 seed of the Wiii Connect capability snapshot
documented in `docs/architecture/wiii-connect/CONNECTION_CONTRACT_V0.md`.
Policy work should extend that snapshot rather than adding unrelated
service-specific status maps.

## Required Contract

Every direct chat turn should have a `ToolPolicySession` in `AgentState` when
tool selection is evaluated.

Runtimes that already perform their own tool selection, such as Code Studio,
tutor, and product search, should record the same contract with
`build_visible_tool_policy_session`: the candidate set is the collected tool
inventory, and the visible set is the runtime-selected tool bundle actually
bound to the model.

The session records:

- `path`: active path such as `casual_chat`, `weather_lookup`, `web_search`,
  `maritime_search`, `lms_document_preview`, `pointy_guidance`, or
  `visual_generation`.
- `candidate_tool_names`: tools collected before final policy filtering.
- `visible_tool_names`: final tools bound to the model after runtime pruning.
- `allowed_tool_names` and `allowed_tool_prefixes`: positive allow rules for
  narrow paths.
- `forbidden_tool_names` and `forbidden_tool_prefixes`: explicit negative rules.
- `connection_status`: fail-closed service status such as LMS authoring
  connection, host capability presence, and weather provider availability.
- `approval_required_tool_names`: tools that require preview/approval evidence.
- `tool_capabilities`: serialized registry metadata for candidate tools, used
  for auditability and later loop migration.

The capability registry records:

- capability group: web search, weather, LMS authoring, host action, Pointy,
  product search, visual, knowledge search, utility, or Code Studio output;
- permission level: read, write, or host control;
- required connection: LMS authoring, weather provider, or host actions;
- whether the tool mutates state or requires host-issued approval evidence;
- intended surface scope, such as direct chat, tutor, product search,
  Code Studio, host, LMS, or visual runtime.

## Runtime Rules

1. Path-specific tools must be exposed only through `ToolPolicySession`.
2. A tool not visible in `visible_tool_names` must not execute, even if a model
   emits a raw or stale tool call.
3. LMS authoring tools require an active LMS host connection. Apply tools also
   require host-issued approval evidence.
4. Weather may expose a fail-closed status tool on `weather_lookup`, but it must
   not fall back to generic web search unless the user explicitly requests web
   search.
5. Pointy must stay out of code, visual, simulation, artifact, and LMS output
   creation paths unless the active path explicitly allows it.
6. Denied tool calls should emit a visible tool result that explains the policy
   denial instead of silently doing nothing.

## Verification

Policy changes should include focused tests for:

- prompt/bind-time visibility;
- execution-time denial;
- narrow path dominance over broad fallback paths;
- connection-gated host/LMS tools;
- no raw internal tool names leaking into user-facing prose.

When Wiii Connect snapshot code lands, also test that snapshots contain only
status, scopes, counts, and warning codes, never tokens, raw uploaded document
content, prompt text, or provider payloads.

Recommended commands:

```powershell
cd maritime-ai-service
python -m pytest tests/unit/test_tool_policy_session.py tests/unit/test_turn_path_governor.py tests/unit/test_direct_tool_rounds_runtime.py -q --tb=short
python -m ruff check app/ tests/unit/ --select=E9,F63,F7
git diff --check
```
