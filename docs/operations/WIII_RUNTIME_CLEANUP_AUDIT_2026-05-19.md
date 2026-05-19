# Wiii Runtime Cleanup Audit 2026-05-19

Status: Active

Owner: Project leadership

Issue: #411

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

- `direct_node_runtime.py` and `direct_tool_rounds_runtime.py` remain large.
  The long-term cleanup direction is lifecycle, tool-loop, tool-dispatch, and
  response-finalization modules with contract tests around SSE V3 parity.
- `code_studio_template_scaffold.py` is still a large deterministic fallback.
  The next durable step is a renderer registry plus scaffold-quality gates
  that reject generic templates for simulation requests.
- Some tests still import compatibility `graph.py` modules. Move tests toward
  `runtime.py` imports when the external import window can close.

## Verification Notes

Targeted commands used during this pass:

```powershell
cd maritime-ai-service
uv run --with pytest --with hypothesis --with pytest-asyncio pytest tests/unit/test_code_studio_template_scaffold.py -q --tb=short
uv run --with pytest --with hypothesis --with pytest-asyncio pytest tests/unit/test_subagent_phase3.py tests/unit/test_subagent_search.py tests/unit/test_sprint202_curated_cards.py -q --tb=short
```

The first command passed with 52 tests. The second command passed with 140
tests after adding the required `pytest-asyncio` test plugin to the temporary
uv environment.
