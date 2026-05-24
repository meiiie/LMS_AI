# Wiii Runtime Cleanup Audit 2026-05-19

Status: Active

Owner: Project leadership

Issue: #411

Follow-up issues: #413, #415, #417, #419, #421, #423, #425, #427, #429, #431, #433, #435, #437, #439, #441, #477, #479, #481, #483, #485, #487, #489, #491, #493, #495, #497, #499, #501, #503, #505, #507, #509, #511, #513, #515, #517, #519, #521, #523, #525, #527, #533, #535, #537, #539, #549, #551, #553, #555, #557, #559, #561, #563 (owner: Architecture Maintainers)

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
- Follow-up #433 moved post-tool follow-up LLM/tool selection into
  `direct_tool_followup_runtime.py`, keeping default `llm_auto` continuation,
  visual-only rebinding, forced visual tool choice, and fallback source metadata
  behind a focused helper.
- Follow-up #435 moved post-tool follow-up invocation into
  `direct_tool_followup_runtime.py`, keeping heartbeat lifecycle,
  provider-target propagation, runtime-tier resolution, fallback invocation, and
  shutdown logging behind a focused helper.
- Follow-up #437 moved post-tool response finalization into
  `direct_tool_response_finalization_runtime.py`, keeping empty-response
  search-template fallback, forced no-tool synthesis, provider propagation, and
  widget injection behind a focused helper.
- Follow-up #439 moved post-tool source-backed search-template early returns
  into `direct_search_template_runtime.py`, keeping forced `@web-search` and
  explicit web-search evidence exits behind a focused helper.
- Follow-up #441 moved the initial deterministic forced `@web-search`
  shortcut into `direct_forced_web_search_runtime.py`, keeping tool-call/result
  SSE events, runtime invocation options, thinking trace emission, and fallback
  response construction behind a focused helper.
- Follow-up #477 moved uploaded-document source-reference helpers into
  `direct_document_source_refs.py` and domain-specific deterministic course
  plan builders into `direct_document_course_domain_plans.py`, leaving
  `direct_document_preview_payloads.py` as the preview/course payload shell and
  compatibility import surface.
- Follow-up #479 moved direct visual-turn policy into
  `direct_visual_tool_policy_runtime.py`, keeping visual intent resolution,
  visual commit detection, initial/follow-up timeout selection, and structured
  visual feature state behind one typed contract.
- Follow-up #481 moved direct tool-loop graph override resolution and
  provider/failover helpers into `direct_runtime_bindings.py`, keeping
  compatibility aliases for the legacy `graph.py` shim and making provider
  memory/runtime-tier lookup a typed per-turn policy object.
- Follow-up #483 moved repeated direct-node thinking snapshot side effects into
  `direct_node_thinking_snapshot.py`, so deterministic fast paths commit
  `thinking`, `thinking_content`, and reasoning snapshots through one helper.
- Follow-up #485 moved direct-node uploaded-document preview host-action
  execution into `direct_node_document_preview_runtime.py`, keeping forced
  preview tool choice, tool-call event capture, response sanitization,
  `tools_used`, and routing metadata updates behind one focused contract.
- Follow-up #487 moved direct-node deterministic fast-response selection into
  `direct_node_fast_response_runtime.py`, keeping Pointy guard responses,
  self/capability/meta answers, uploaded-document fact fallback, session-memory
  ack/write/recall, hunger chatter, response types, state side effects, and
  thinking snapshot provenance strings behind one focused contract.
- Follow-up #489 moved direct prompt tool binding helpers into
  `direct_prompt_tool_binding.py` and direct/code-studio tool-context prompt
  builders into `direct_prompt_tool_context.py`, while keeping graph-era
  compatibility exports and making query/state inputs explicit for best-effort
  skill prompt injection.
- Follow-up #491 moved uploaded-document preview text shaping helpers into
  `direct_document_preview_text.py`, keeping line cleanup, title selection,
  marker extraction, learning-goal shaping, role-focused markdown, and
  source-page parsing separate from host-action payload assembly.
- Follow-up #493 moved Code Studio scaffold palette, title/ARIA, shared CSS,
  RAF script wrapper, and shell composition helpers into
  `code_studio_scaffold_shell.py`, leaving `code_studio_template_scaffold.py`
  focused on spec inference, renderer registry, and public API.
- Follow-up #495 moved Code Studio scaffold topic-library data, concept
  matching, deterministic title/palette/object/motion/count inference, and
  `extract_scaffold_spec` / `detect_scaffold_kind` into
  `code_studio_scaffold_spec.py`, leaving `code_studio_template_scaffold.py`
  as a renderer registry plus compatibility import surface.
- Follow-up #497 moved direct-answer visible stream text helpers into
  `direct_stream_text_runtime.py`, keeping incomplete `<thinking>` stripping,
  native chunk part extraction, duplicate answer-delta comparison, visible
  thinking cleanup/alignment, and pseudo-stream answer chunking outside the
  provider fallback shell.
- Follow-up #499 split deterministic uploaded-document course plan builders by
  domain into `direct_document_course_lms_plan.py` and
  `direct_document_course_maritime_plans.py`, leaving
  `direct_document_course_domain_plans.py` as a compatibility export surface for
  existing document preview/tool-loop imports.
- Follow-up #501 moved uploaded-document course title extraction, source
  section parsing, domain classification, document-map clustering, quality
  reporting, and generic course-plan construction into
  `direct_document_course_analysis.py`, leaving
  `direct_document_preview_payloads.py` focused on preview/course host-action
  payload assembly plus compatibility exports.
- Follow-up #503 moved direct-node tool selection policy into
  `direct_node_tool_selection.py`, keeping short-chatter/toolless guards,
  force-bound `@web-search`/Pointy required-tool handling, runtime recommender
  must-include behavior, and uploaded-document preview tool rebinding behind a
  focused helper.
- Follow-up #505 moved direct-node host UI navigation timeout handling into
  `direct_node_host_timeout.py`, keeping the bounded fallback, answer-delta
  emission, and standalone-vs-LMS copy selection outside the main provider/tool
  execution branch.
- Follow-up #507 moved direct-node execution preparation into
  `direct_node_execution_prep.py`, keeping visual forced-tool policy,
  provider/model state propagation, timeout profile selection, fallback
  provider allowlisting, tool binding, message assembly, and runtime context
  construction behind a focused helper.
- Follow-up #509 moved direct-node LLM preflight into
  `direct_node_llm_preflight.py`, keeping direct/native LLM selection,
  unsupported-native fallback, uploaded visual guard decisions, and
  natural-conversation penalty binding outside the main direct node.
- Follow-up #511 moved direct-node response cleanup and empty-body
  source-backed fallback into `direct_node_response_cleanup.py`, keeping
  visible answer sanitization, DSML/tool-call residue stripping, codebase
  deterministic fallback snapshots, template fallback metrics, and tools-used
  reconstruction behind focused helpers.
- Follow-up #513 moved direct-node visible-thinking finalization into
  `direct_node_visible_thinking_finalization.py`, keeping aligned thinking,
  unsafe thought clearing, language checks, emotional-rescue thinking, and
  snapshot side effects outside the main direct node.
- Follow-up #521 closed the obsolete private-helper compatibility export
  surface in `direct_tool_rounds_runtime.py`; tests now import synthesis,
  web-search policy, uploaded-document payload, document text, and Pointy
  selector helpers from their owning modules while the shell only exposes
  `execute_direct_tool_rounds_impl`.
- Follow-up #523 moved graph runtime wait-surface and Code Studio regex
  bindings to their canonical modules, closing obsolete graph-era re-exports
  from `direct_execution.py`.
- Follow-up #525 moved direct prompt consumers to canonical turn-contract,
  tool-binding, and tool-context modules, closing obsolete compatibility export
  tuples and implicit private-helper re-exports from `direct_prompts.py`.
- Follow-up #527 made runtime metrics timing use a high-resolution monotonic
  clock, so local Windows verification and CI Linux record `time_block()`
  durations through the same stable contract.
- Follow-up #533 moved direct selfhood/origin prompt contracts into
  `direct_prompt_selfhood.py`, keeping identity-turn detection, answer-shape
  lines, and the selfhood system prompt behind one focused module while
  `direct_prompts.py` remains the system-message assembly shell.
- Follow-up #535 moved direct visible-thinking prompt guidance and domain
  thinking-example loading into `direct_prompt_visible_thinking.py`, keeping
  source-backed/codebase thinking instructions separate from the direct prompt
  assembly shell.
- Follow-up #537 moved live-evidence planner prompt text and hint-list
  formatting into `direct_prompt_evidence.py`, keeping current-source lookup
  guidance separate from the direct prompt assembly shell.
- Follow-up #539 moved uploaded-document context plan recording, preview
  response sanitization, and the early LMS document-preview preflight into
  `direct_node_document_preflight.py`, keeping preview-before-planner safety
  visible as a focused lifecycle helper.
- Follow-up #541 moved direct-node image-input preflight into
  `direct_node_image_input_preflight.py`, keeping uploaded-document image-error
  cleanup, vision-unavailable fallback, and base64 image analysis ahead of the
  planner LLM.
- Follow-up #543 moved uploaded-document LMS host-action shortcut contracts
  into `direct_document_host_action_shortcuts.py`, keeping preview/course
  approval-token safety text out of the direct tool-loop shell.
- Follow-up #545 moved the Code Studio delivery-first answer contract into
  `direct_prompt_code_studio.py`, keeping artifact/code delivery UX rules out
  of the general direct prompt assembly shell.
- Follow-up #547 moved the late analytical answer contract into
  `direct_prompt_analytical_answer.py`, keeping market/math/codebase answer
  style rules separate from direct system prompt assembly.
- Follow-up #549 moved direct-node event sink creation and event dispatch into
  `direct_node_event_sink.py`, keeping capture + SSE bus forwarding out of the
  direct-node runtime shell.
- Follow-up #551 moved direct-node turn-start resolution into
  `direct_node_turn_start.py`, keeping deterministic greetings, explicit
  web-search detection, and source-backed codebase fast answers behind a small
  tested lifecycle contract.
- Follow-up #553 moved direct-node turn policy setup into
  `direct_node_turn_policy.py`, keeping routing metadata, identity/social
  chatter policy, visual effort upgrade, provider override selection, and
  codebase/uploaded-document guards behind a typed lifecycle contract.
- Follow-up #555 connected high-severity AI-slop detection to Code Studio
  visual-code validation, so structural emoji and obvious hero-gradient slop
  force a repair turn before preview instead of opening weak app chrome.
- Follow-up #557 moved direct-node no-LLM fallback selection into
  `direct_node_llm_fallback.py`, keeping source-backed codebase fallback,
  phase fallback, and explicit-provider fail-closed behavior behind a typed
  helper before the larger LLM execution shell is split.
- Follow-up #559 added a guarded assistant-markdown normalization pass for
  collapsed tables, horizontal rules, and inline lists; made Code Studio
  previews render through the `app`/`immersive` iframe lane; and let tall app
  frames scroll internally instead of clipping simulations.
- Follow-up #561 moved visual-intent runtime metadata and Code Studio
  visual-code lane resolution behind typed contracts. Tool runtime metadata is
  now built through `VisualToolRuntimeIntent`, and `tool_create_visual_code`
  resolves presentation intent, studio lane, artifact kind, renderer kind,
  patch strategy, quality profile, and runtime manifest through
  `VisualCodeRuntimeContract` before validation/payload build.
- Follow-up #563 moved direct-node LLM/tool execution result finalization into
  `direct_node_llm_execution_finalization.py`, keeping response extraction,
  cleanup, source-backed empty-response fallback, visible-thinking finalization,
  and `tool_call_events` / `tools_used` state side effects behind one tested
  helper while preserving host-timeout execution and exception salvage in the
  main shell.
- Follow-up #565 moved deterministic Code Studio scaffold fallback decisions
  behind `code_studio_scaffold_fallback_policy.py`. Tool-round timeouts,
  no-tool-call responses, and outer Code Studio node exceptions now resolve a
  typed `VisualCodeRuntimeContract` before engaging a template fallback.
  Generic app/simulation failures are suppressed with an auditable safe-stop
  response; artifact fallback remains allowed when the contract says it is the
  right lane.
- Follow-up #567 added a typed Code Studio app-intent contract for simulations,
  quizzes, dashboards, mini tools, interactive tables, search/code widgets, and
  artifacts. Visual intent metadata, Code Studio payload metadata, runtime
  manifests, prompt guidance, and fallback metrics now carry app category,
  required surface, controls, state/readout expectations, feedback hooks, and
  reject-if-missing criteria instead of relying on generic `simulation` or
  `react_app` labels alone.

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

- `direct_node_runtime.py` remains large, but session-memory parsing/recall,
  thinking-effort policy, emergency fallback/salvage helpers, uploaded-context
  guards, operational/meta/chatter fast-response selection, visible
  thought helpers, thinking snapshot side effects, document-preview
  host-action rebinding/execution/preflight, image-input preflight,
  direct-node event sink lifecycle, direct-node turn-start lifecycle,
  direct-node turn-policy lifecycle, direct-node tool selection, LLM preflight,
  LLM-unavailable fallback selection, execution preparation, LLM/tool execution
  result finalization,
  exception/source fallback lifecycle, final state/domain notice handling, and
  host UI timeout handling have moved out. The long-term cleanup direction is
  lifecycle modules and SSE V3 parity modules with narrow contract tests. Its
  obsolete private helper compatibility export tuples are now closed; tests
  import helper contracts from their owning modules.
- `direct_prompts.py` remains the main direct prompt assembly surface. Force-bound
  skill directives, Pointy inventory prompt injection, the direct turn contract,
  provider-aware tool binding, tool-context prompt builders, selfhood/origin
  prompt contracts, visible-thinking prompt guidance, and live-evidence prompt
  contracts, Code Studio delivery prompt rules, and analytical answer contracts
  now live in focused helper modules, and consumers import those helper
  contracts directly.
- `direct_tool_rounds_runtime.py` is now a smaller orchestration shell. Pointy,
  explicit web-search policy, deterministic document host-action execution,
  uploaded-document preview/course payload shell, uploaded-document course
  analysis/generic planning, uploaded-document text shaping, document source
  refs, domain-specific course plan builder modules, visual-turn policy,
  document host-action shortcut contracts, graph/runtime binding resolution, per-turn provider policy, message
  builders, generic tool dispatch, final synthesis helper construction, final
  synthesis execution, post-tool convergence policy, follow-up LLM
  selection/invocation, response finalization, post-tool search-template
  returns, and forced web-search shortcuts have moved out. Its obsolete
  private-helper compatibility export surface is now closed; internal tests and
  consumers import only the orchestration entry point from this shell.
- `direct_execution.py` is now closer to a provider invocation/fallback shell:
  visible answer/thinking text shaping moved to `direct_stream_text_runtime.py`,
  and graph runtime bindings now load wait-surface and Code Studio regex helpers
  from their canonical modules instead of through direct execution.
- Code Studio deterministic fallback is now split across contract, spec,
  quality, captions, registry, shell, and renderer modules. The remaining debt
  is product quality rather than module size: high-severity slop is now gated
  before preview, and the first markdown/iframe UX cleanup landed in #559. The
  scaffold should keep moving away from broad template fallback when the
  primary visual tool path is healthy. Follow-up #561 introduced typed runtime
  contracts for visual intent metadata and Code Studio visual-code lanes, and
  follow-up #565 now uses those contracts to suppress broad app/simulation
  scaffold fallback in product flows. Follow-up #567 introduced typed app
  category contracts so the next quality frontier is local/product E2E evidence
  and stricter generated-code critique, not adding more ad-hoc templates.
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
In follow-up #433, the direct tool-round command passed with 67 tests after
moving follow-up LLM/tool selection into `direct_tool_followup_runtime.py`.
Targeted ruff checks, repository `ruff check app/ --select=E9,F63,F7`, and
`git diff --check` also passed for the follow-up selection extraction.
In follow-up #435, the direct tool-round command passed with 69 tests after
moving post-tool follow-up invocation into `direct_tool_followup_runtime.py`.
Targeted ruff checks also passed for the follow-up invocation extraction.
In follow-up #437, the direct tool-round command passed with 71 tests after
moving post-tool response finalization into
`direct_tool_response_finalization_runtime.py`. Targeted ruff checks also
passed for the response finalization extraction.
In follow-up #439, the direct tool-round command passed with 74 tests after
moving post-tool source-backed search-template returns into
`direct_search_template_runtime.py`. Targeted ruff checks also passed for the
search-template return extraction.
In follow-up #441, the direct tool-round command passed with 76 tests after
moving the deterministic forced web-search shortcut into
`direct_forced_web_search_runtime.py`. Targeted ruff checks also passed for the
forced web-search shortcut extraction.
In follow-up #466, targeted direct-node reasoning tests passed after moving
direct thinking-effort policy into `direct_node_thinking_effort.py`.
In follow-up #468, targeted direct-node provider error tests passed after
moving emergency search fallback, synthetic tool event emission, and salvage
helpers into `direct_node_emergency_fallbacks.py`.
In follow-up #469, the direct tool-round command passed with 81 tests after
moving uploaded-document preview/course payload builders into
`direct_document_preview_payloads.py`. Targeted ruff checks also passed for the
payload extraction.
In follow-up #471, targeted direct-node document preview/provider tests passed
after moving LMS document-preview host-action rebinding into
`direct_node_document_preview_rebind.py`.
In follow-up #473, direct prompt contract tests passed after moving
force-bound skill directives, Pointy inventory prompt injection, and direct
turn-contract helpers into `direct_prompt_turn_contracts.py`.
In follow-up #477, the direct tool-round command passed with 81 tests after
moving uploaded-document source-reference helpers and deterministic domain
course plan builders out of `direct_document_preview_payloads.py`. Targeted
ruff checks also passed for the document payload/source-ref/course-plan modules.
In follow-up #479, the direct tool-round command plus the new visual policy
tests passed with 84 tests after moving visual-turn policy into
`direct_visual_tool_policy_runtime.py`. Targeted ruff checks also passed for
the direct loop and visual policy module.
In follow-up #481, the direct tool-round command plus focused runtime binding
tests passed with 84 tests after moving graph override binding resolution and
provider/failover helpers into `direct_runtime_bindings.py`. Targeted ruff
checks also passed for the package shim, direct runtime bindings, and direct
tool loop.
In follow-up #483, targeted direct-node regression tests plus focused thinking
snapshot helper tests passed with 117 tests after moving repeated direct-node
thinking snapshot writes into `direct_node_thinking_snapshot.py`. Targeted ruff
checks also passed for direct-node runtime and the new helper.
In follow-up #485, focused direct-node document preview helper tests plus
direct-node provider/preview regression tests passed with 38 tests after moving
forced uploaded-document preview execution into
`direct_node_document_preview_runtime.py`. Targeted ruff checks, repository
`ruff check app/ --select=E9,F63,F7`, and `git diff --check` also passed for
the preview preflight extraction.
In follow-up #487, focused deterministic fast-response helper tests plus
conservative/direct-node/document-context regressions passed with 90 tests after
moving fast-response selection into `direct_node_fast_response_runtime.py`.
Targeted ruff checks also passed for the direct-node runtime, the new helper,
and the focused regression set.
In follow-up #489, focused prompt/tool-context tests plus graph routing and
legacy direct binding regressions passed with 192 tests after moving direct
tool binding and tool-context prompt builders out of `direct_prompts.py`.
Additional direct-node/guidance prompt tests passed with 69 tests. Targeted
ruff checks, repository `ruff check app/ --select=E9,F63,F7`, and
`git diff --check` also passed for the prompt tool-context extraction.
In follow-up #491, focused document-preview text tests plus direct tool-round
regressions passed with 86 tests after moving text cleanup/title/source-page
helpers into `direct_document_preview_text.py`. The broader LMS/document
preview contract regression set passed with 107 tests. Targeted ruff checks,
repository `ruff check app/ --select=E9,F63,F7`, and `git diff --check` also
passed for the text helper extraction.
In follow-up #493, the Code Studio scaffold regression set passed with 57 tests
after moving palette/title/ARIA/CSS/script/shell helpers into
`code_studio_scaffold_shell.py`. The broader Code Studio scaffold plus graph
routing regression set passed with 131 tests. Targeted ruff checks, repository
`ruff check app/ --select=E9,F63,F7`, and `git diff --check` also passed for
the shell helper extraction.
In follow-up #495, the Code Studio scaffold regression set passed with 57 tests
after moving deterministic intent/spec extraction into
`code_studio_scaffold_spec.py`. Targeted ruff checks passed for the spec and
renderer shell import surfaces.
In follow-up #497, the direct execution streaming regression set passed with 22
tests after moving visible stream text helpers into
`direct_stream_text_runtime.py`. Targeted ruff checks passed for the direct
execution compatibility wrapper and new helper module.
In follow-up #499, the document preview/tool-loop regression set passed with
93 tests after splitting uploaded-document course plan builders into LMS and
maritime modules. The focused host UI/tool surface regression set passed with
14 tests. Targeted ruff checks, repository `ruff check app/ --select=E9,F63,F7`,
and `git diff --check` also passed for the domain plan builder split.
In follow-up #501, the document preview/tool-loop regression set passed with
93 tests after moving course analysis and generic planning helpers out of
`direct_document_preview_payloads.py`. The focused host UI/tool surface
regression set passed with 14 tests. Targeted ruff checks, repository
`ruff check app/ --select=E9,F63,F7`, and `git diff --check` also passed for
the course analysis extraction.
In follow-up #503, focused direct-node tool-selection tests plus direct-node
document-preview, fast-response, conservative-evolution, and provider-error
regressions passed with 104 tests after moving direct-node tool selection into
`direct_node_tool_selection.py`. Targeted ruff checks, repository
`ruff check app/ --select=E9,F63,F7`, and `git diff --check` also passed for
the extraction.
In follow-up #505, focused direct-node host-timeout tests plus direct-node
tool-selection, document-preview, fast-response, and provider-error
regressions passed with 46 tests after moving host UI timeout fallback into
`direct_node_host_timeout.py`. Targeted ruff checks, repository
`ruff check app/ --select=E9,F63,F7`, and `git diff --check` also passed for
the extraction.
In follow-up #507, focused direct-node execution-preparation tests plus
direct-node tool-selection, host-timeout, and provider-error regressions passed
with 41 tests after moving direct-node execution preparation into
`direct_node_execution_prep.py`.
In follow-up #509, focused direct-node LLM-preflight tests plus direct-node
execution-preparation, tool-selection, host-timeout, document-preview,
fast-response, and provider-error regressions passed with 53 tests after
moving LLM preflight into `direct_node_llm_preflight.py`.
In follow-up #511, focused direct-node response-cleanup tests plus direct-node
LLM-preflight, execution-preparation, tool-selection, host-timeout,
document-preview, fast-response, and provider-error regressions passed with 57
tests after moving response cleanup into `direct_node_response_cleanup.py`.
In follow-up #513, focused direct-node visible-thinking finalization tests plus
direct-node response-cleanup, LLM-preflight, execution-preparation,
tool-selection, host-timeout, document-preview, fast-response, and
provider-error regressions passed with 60 tests after moving visible-thinking
finalization into `direct_node_visible_thinking_finalization.py`.
In follow-up #515, helper-level exception fallback tests plus provider-error,
visible-thinking finalization, response-cleanup, LLM-preflight,
execution-preparation, tool-selection, host-timeout, document-preview, and
fast-response regressions passed with 64 tests after moving salvage,
provider-unavailable, source-template, emergency search, explicit-provider, and
generic fallback handling into `direct_node_exception_fallbacks.py`.
In follow-up #517, helper-level final-state tests plus the same focused
direct-node regression set passed with 68 tests after moving final thinking
snapshot resolution, `final_response`/`agent_outputs` assignment, current-agent
marking, and general-intent domain notice handling into
`direct_node_final_state.py`.
In follow-up #519, affected import-surface tests passed with 142 tests and the
focused direct-node regression set still passed with 68 tests after moving
private direct-node helper imports from `direct_node_runtime.py` to their owning
modules and removing obsolete compatibility export tuples/imports from the
runtime.
In follow-up #521, the direct tool-round regression set passed with 81 tests
after moving private helper imports from `direct_tool_rounds_runtime.py` to
their owning modules and removing obsolete compatibility aliases/export tuples
from the tool-round orchestration shell.
In follow-up #523, direct execution streaming tests and graph routing tests
passed after moving graph runtime wait-surface and Code Studio regex bindings
away from `direct_execution.py` and into their canonical helper modules.
In follow-up #525, direct prompt contract tests, direct tool-round force-skill
tests, and graph prompt compatibility tests passed after moving prompt helper
consumers to the canonical turn-contract, tool-binding, and tool-context
modules.
In follow-up #527, the runtime metrics regression tests passed after switching
`time_block()` from the coarse Windows monotonic clock to high-resolution
`perf_counter_ns()`.
In follow-up #559, the desktop targeted markdown/Code Studio/iframe regression
set passed with 59 tests, full desktop Vitest passed with 2481 tests, TypeScript
typecheck passed, `build:embed` passed, and local browser smoke loaded the Wiii
chat shell on `http://127.0.0.1:1420/`.
