# Wiii Tool Policy Session Standard

Status: Active

Owner: Backend maintainers

Last updated: 2026-05-26

Applies to: Direct chat tool binding, runtime tool execution, host actions, LMS authoring, Pointy, web/search, weather, visual tools

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

## Required Contract

Every direct chat turn should have a `ToolPolicySession` in `AgentState` when
tool selection is evaluated.

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

Recommended commands:

```powershell
cd maritime-ai-service
python -m pytest tests/unit/test_tool_policy_session.py tests/unit/test_turn_path_governor.py tests/unit/test_direct_tool_rounds_runtime.py -q --tb=short
python -m ruff check app/ tests/unit/ --select=E9,F63,F7
git diff --check
```
