# Wiii Runtime Cleanup Audit 2026-05-19

Status: Active

Owner: Project leadership

Issue: #411

Follow-up issues: #413, #415, #417, #419, #421, #423, #425, #427, #429, #431 (owner: Architecture Maintainers)

## Purpose

This audit records the cleanup boundary for the May 2026 runtime hygiene pass.
It is intentionally practical: remove or quarantine confusing legacy surfaces
without broad deletes, secret exposure, or unreviewed product behavior changes.

## Cleaned In This Pass

- Product-search, RAG, and tutor helper logic now lives under
  `subagents/*/runtime.py`.
- `subagents/*/graph.py` is reduced to a compatibility shim that preserves old
  imports and explicit `build_*_subgraph()` deprecation failures.
- Code Studio scaffold primitive and legacy-kind mapping moved into
  `code_studio_scaffold_contract.py`, so routing and tests can depend on a
  small typed contract instead of importing the full HTML renderer.
- Follow-up #413 moved direct Pointy selector/inventory policy into
  `direct_pointy_runtime.py`.
- Follow-up #413 moved explicit web-search forcing and fallback-selection
  policy into `direct_web_search_policy.py`.
- Follow-up #413 moved current-session memory fast-path parsing/recall into
  `direct_session_memory_runtime.py` and shared direct text folding into
  `direct_text_utils.py`.
- Follow-up #413 moved Code Studio scaffold renderer dispatch into
  `code_studio_scaffold_registry.py` and visible Vietnamese fallback copy into
  `code_studio_scaffold_captions.py`.
- Follow-up #415 moved deterministic uploaded-document host-action execution
  into `direct_document_host_action_runtime.py`, keeping preview-only
  tool-call/result, host-action emission, thinking trace, and user response as
  one tested contract.
- Follow-up #417 added `code_studio_scaffold_quality.py` so explicit
  simulation/canvas requests cannot silently fall back to generic data-band
  templates when no topic classifier matches.
- Follow-up #419 moved scene and data-band renderer bodies into
  `code_studio_scaffold_scene_renderers.py`, leaving the main scaffold module
  to select specs, own shared shell helpers, and register render functions.
- Follow-up #421 moved particle-field, oscillation, function-plot, and
  timeline renderer bodies into `code_studio_scaffold_core_renderers.py`,
  completing the Code Studio primitive renderer split behind the registry.
- Follow-up #423 moved direct tool-round message construction into
  `direct_tool_message_runtime.py`, reducing provider/tool message-shape logic
  inside the main tool loop before larger dispatch/synthesis extraction.
- Follow-up #425 moved generic direct tool dispatch into
  `direct_tool_dispatch_runtime.py`, preserving SSE `tool_call`/`tool_result`
  event shape, runtime invocation options, search-query adjustment, and
  unknown-tool recovery while leaving Pointy, visual, reflection, handoff, and
  final synthesis orchestration in the main loop.
- Follow-up #427 moved visible-answer extraction and final synthesis
  instruction construction into `direct_final_synthesis_runtime.py`, preserving
  compatibility aliases in the main tool-round module while leaving final
  synthesis execution and provider fallback unchanged.
- Follow-up #429 moved direct final synthesis execution into
  `direct_final_synthesis_runtime.py`, keeping the no-tool synthesis pass,
  heartbeat lifecycle, provider resolution, moderate timeout profile, and
  message insertion behind a focused helper.
- Follow-up #431 moved round-0 search convergence hint policy into
  `direct_tool_convergence_runtime.py`, keeping sparse-result self-eval,
  rich-result stop hints, native message handling, and log metadata behind a
  focused helper.

## Preserved Intentionally

- `graph.py` shim files remain because existing tests and possible external
  imports still rely on those module paths. They are no longer the home of
  active runtime logic.
- Code Studio deterministic scaffold remains because it is a failure-mode UX
  guard when LLM visual tool planning stalls. The cleanup separates contract
  from renderer; it does not claim the renderer is the final visual system.
- DeepSeek provider catalog entries remain as explicit legacy/failover/test
  coverage. Qwen remains the NVIDIA default.
- Auth, role, token, and memory compatibility paths were not mechanically
  removed because they are high-risk tenant and identity surfaces.

## Not Repository Trash

The development worktree `E:\Sach\Sua\AI_v1` still has untracked LinkedIn/MCP
work and `.mcp.json` changes. Those are user/WIP files, not cleanup targets.

The product worktree may contain ignored local build/test outputs such as
`.venv`, `.pytest_cache`, `.ruff_cache`, `__pycache__`, `wiii_service.egg-info`,
desktop `node_modules`, `dist-pointy`, or Tauri `target`. These should be
deleted only with explicit target paths and never together with `.env*`,
backups, data PDFs, or local skill folders.

## Remaining Debt

- `direct_node_runtime.py` remains large, but session-memory parsing/recall
  has moved out. The long-term cleanup direction is lifecycle,
  response-finalization, and SSE V3 parity modules with narrow contract tests.
- `direct_tool_rounds_runtime.py` remains large, but Pointy and explicit
  web-search policy plus deterministic document host-action execution, message
  builders, generic tool dispatch, final synthesis helper construction, and
  final synthesis execution plus post-tool convergence policy have moved out.
  The next durable step is separating follow-up LLM selection from the main loop.
- `code_studio_template_scaffold.py` is still a large deterministic fallback,
  but contract, renderer dispatch, caption copy, and explicit-simulation
  quality policy are no longer embedded in the renderer body. Scene and
  data-band bodies plus particle, oscillation, timeline, and function-plot
  bodies have moved behind the registry boundary. The next durable step is
  shrinking topic/spec extraction data and helpers if product quality evidence
  shows that the deterministic fallback remains too broad.
- Some tests still import compatibility `graph.py` modules. Move tests toward
  `runtime.py` imports when the external import window can close.

## Verification Notes

Targeted commands used during this pass:

```powershell
cd maritime-ai-service
uv run --with pytest --with hypothesis --with pytest-asyncio pytest tests/unit/test_code_studio_template_scaffold.py -q --tb=short
uv run --with pytest --with hypothesis --with pytest-asyncio pytest tests/unit/test_subagent_phase3.py tests/unit/test_subagent_search.py tests/unit/test_sprint202_curated_cards.py -q --tb=short
uv run --with pytest --with hypothesis --with pytest-asyncio pytest tests/unit/test_direct_tool_rounds_runtime.py -q --tb=short
uv run --with pytest --with hypothesis --with pytest-asyncio pytest tests/unit/test_conservative_evolution.py tests/unit/test_direct_node_provider_errors.py -q --tb=short
```

The first command passed with 52 tests. The second command passed with 140
tests after adding the required `pytest-asyncio` test plugin to the temporary
uv environment. In follow-up #413, the Code Studio scaffold command passed
with 54 tests, the direct tool-round command passed with 56 tests, and the
combined direct-runtime regression set passed with 205 tests.
In follow-up #415, the direct tool-round command passed with 57 tests after
adding the document host-action shortcut contract test.
In follow-up #417, the Code Studio scaffold command passed with 56 tests after
adding the explicit-simulation quality gate.
In follow-up #419, the same scaffold command passed with 56 tests after moving
scene and data-band renderer bodies out of the monolithic scaffold module.
In follow-up #421, the same scaffold command passed with 57 tests after moving
the remaining primitive renderer bodies out of the monolithic scaffold module.
In follow-up #423, the direct tool-round command passed with 57 tests after
moving direct message builders out of the main tool loop.
In follow-up #425, the direct tool-round command passed with 60 tests after
moving generic dispatch out of the main tool loop and adding focused
`direct_tool_dispatch_runtime.py` tests.
In follow-up #427, the direct tool-round command passed with 57 tests after
moving final synthesis helper bodies out of the main tool loop.
In follow-up #429, the direct tool-round command passed with 59 tests after
moving direct final synthesis execution into
`direct_final_synthesis_runtime.py`. Targeted ruff checks, repository
`ruff check app/ --select=E9,F63,F7`, and `git diff --check` also passed for
the no-tool synthesis, heartbeat, provider-resolution helper refactor.
In follow-up #431, the direct tool-round command passed with 64 tests after
moving post-tool convergence hint policy into
`direct_tool_convergence_runtime.py`. Targeted ruff checks, repository
`ruff check app/ --select=E9,F63,F7`, and `git diff --check` also passed for
the convergence policy extraction.
