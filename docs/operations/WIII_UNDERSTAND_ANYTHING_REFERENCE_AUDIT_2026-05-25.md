# Wiii Understand-Anything Reference Audit

Status: Active reference audit

Owner: Project leadership

Created: 2026-05-25

Related issue: #662

Related docs:

- `docs/operations/WIII_REFERENCE_SYSTEMS_AUDIT_2026-05-25.md`
- `docs/operations/WIII_SYSTEM_CONTROL_PLANE.md`
- `docs/operations/WIII_SELF_HARNESS.md`
- `.understandignore`

## Purpose

This audit evaluates Understand-Anything as a Wiii system-comprehension
harness. The goal is not to replace Wiii Self-Harness, backend tests, frontend
tests, browser E2E, or LMS acceptance. The goal is to give maintainers a fast
way to see Wiii's codebase inventory, dependency hubs, and architectural
clusters before making more patch-by-patch runtime changes.

## Source Snapshot

External code was inspected from the ignored local research workspace:

```text
.Codex/external/reference-systems/understand-anything
```

| Field | Value |
|---|---|
| Remote | `https://github.com/Lum1104/Understand-Anything.git` |
| Inspected commit | `470cc01dc5f9236a93eb704afdd479cd5db79710` |
| Commit date | `2026-05-24T21:12:57+08:00` |
| Commit title | `Merge pull request #200 from AsimRaza10/fix/agent-model-omit-inherit` |
| Clone mode | shallow |

Primary areas reviewed:

- `README.md`
- `understand-anything-plugin/skills/understand/SKILL.md`
- `understand-anything-plugin/skills/understand/scan-project.mjs`
- `understand-anything-plugin/skills/understand/extract-import-map.mjs`
- `understand-anything-plugin/skills/understand/compute-batches.mjs`
- `understand-anything-plugin/skills/understand-domain/SKILL.md`
- `understand-anything-plugin/skills/understand-domain/extract-domain-context.py`
- `understand-anything-plugin/agents/project-scanner.md`
- `understand-anything-plugin/agents/architecture-analyzer.md`

## Bounded Wiii Trial

The deterministic parts of Understand-Anything were run locally against the
Wiii repository. Generated graph and intermediate output stayed in ignored
paths under `.understand-anything/` and must not be committed.

Commands used:

```powershell
pnpm install --frozen-lockfile; pnpm --filter @understand-anything/core build
node .Codex\external\reference-systems\understand-anything\understand-anything-plugin\skills\understand\scan-project.mjs "E:\Sach\Sua\AI_v1_product" "E:\Sach\Sua\AI_v1_product\.understand-anything\tmp\ua-scan-files.json"
node .Codex\external\reference-systems\understand-anything\understand-anything-plugin\skills\understand\extract-import-map.mjs .understand-anything\tmp\ua-import-map-input.json .understand-anything\tmp\ua-import-map-output.json
node .Codex\external\reference-systems\understand-anything\understand-anything-plugin\skills\understand\compute-batches.mjs "E:\Sach\Sua\AI_v1_product"
python .Codex\external\reference-systems\understand-anything\understand-anything-plugin\skills\understand-domain\extract-domain-context.py "E:\Sach\Sua\AI_v1_product"
```

Trial results:

| Signal | Result |
|---|---|
| Tracked files scanned | `2433` |
| Estimated complexity | `very-large` |
| Code files | `2113` |
| Config files | `92` |
| Docs files | `156` |
| Infra files | `19` |
| Script files | `22` |
| Import-map files with imports | `1277` |
| Internal import edges | `3241` |
| Semantic batches | `123` |
| Domain-context source files | `1345` |
| Domain-context entry points | `170` |

Largest language groups:

- Python: `1658`
- TypeScript: `422`
- Markdown: `153`
- YAML: `69`
- HTML: `27`
- JSON: `23`

Largest top-level areas:

- `maritime-ai-service`: `1851` files
- `wiii-desktop`: `472` files
- `docs`: `34` files
- `.github`: `19` files

Dependency hubs found by import-map:

- `maritime-ai-service/app/core/config/__init__.py`: `129` inbound imports
- `wiii-desktop/src/api/types.ts`: `129` inbound imports
- `maritime-ai-service/app/engine/multi_agent/state.py`: `93` inbound imports
- `maritime-ai-service/app/models/schemas.py`: `47` inbound imports
- `wiii-desktop/src/stores/chat-store.ts`: `45` inbound imports

High fan-out files to treat carefully during refactors:

- `wiii-desktop/src/hooks/useSSEStream.ts`: `25` internal imports
- `maritime-ai-service/app/engine/multi_agent/agents/tutor_node.py`: `25` internal imports
- `wiii-desktop/src/components/settings/SettingsPage.tsx`: `24` internal imports
- `maritime-ai-service/app/engine/multi_agent/direct_tool_rounds_runtime.py`: `22` internal imports
- `maritime-ai-service/app/engine/multi_agent/graph_streaming.py`: `21` internal imports

## Findings For Wiii

### 1. Wiii Needs A System-Comprehension Harness, But Not In The Hot Path

Understand-Anything is useful as an operator/developer aid for seeing the
system before changing it. It should sit beside Wiii Self-Harness as a
comprehension reference, not inside runtime behavior and not as a blocker for
production serving.

### 2. The Deterministic Scripts Are The Safest First Adoption

The scanner, import-map extractor, and batcher produce concrete facts without
asking an LLM to infer file paths. For Wiii, those deterministic outputs are
more immediately useful than a full generated dashboard because they identify
the large areas, dependency hubs, and batch boundaries that should shape audit
order.

### 3. Full Graph Generation Remains Optional

The full `/understand` workflow expects plugin-level agent dispatch and writes
`.understand-anything/knowledge-graph.json`. Use it only in local ignored
workspaces until Wiii decides whether any graph artifact should be versioned.
For now, do not commit generated graphs.

### 4. Windows Domain Scan Needs Guardrails

The lightweight domain-context script found real backend/frontend entry points,
but it also picked up untracked generated files under
`wiii-desktop/dist-embed/assets`. This appears to be a Windows path separator
and ignore-pattern mismatch in the reference tool's Python scanner. Wiii should
therefore treat domain-context output as advisory unless the generated output
paths are excluded by a curated scan profile or the upstream scanner normalizes
paths.

### 5. Dependency Hubs Should Shape Future Slices

The highest inbound hubs match the places Wiii already feels risky:

- backend config and multi-agent state
- frontend API/event type surfaces
- chat store and settings store
- direct-node/tool-loop orchestration
- SSE stream assembly

Future refactors touching these hubs need focused tests and an explicit
rollback note because a small edit can affect many active flows.

## Repo-Owned Wrapper

Wiii now keeps a small wrapper around the deterministic Understand-Anything
scanner and import-map extractor:

```text
tools/wiii_understand_harness/run_wiii_understand_flow_map.py
```

The wrapper exposes named flow profiles instead of asking each maintainer to
reconstruct path lists by hand:

- `chat-baseline`
- `lms-document-preview`
- `visual-code-studio`
- `self-harness`

Example:

```powershell
python tools/wiii_understand_harness/run_wiii_understand_flow_map.py --profile lms-document-preview
```

The wrapper writes generated scan, import input, import-map, and summary files
under ignored `.understand-anything/tmp/`. The summary records selected files,
support files, language/category counts, import-map stats, and top inbound and
outbound dependency hubs. It does not run the full LLM graph workflow, does not
enable auto-update hooks, and does not prove runtime safety.

## Adoption Decision

Adopt Understand-Anything as a supporting system-comprehension harness for Wiii
development.

Use it for:

- source inventory before broad subsystem audits
- dependency hub detection before refactors
- onboarding maps for backend, frontend, docs, and governance areas
- local graph/dashboard exploration when a maintainer installs the plugin

Do not use it for:

- proving runtime behavior
- proving LMS preview/apply safety
- replacing Wiii Self-Harness scenarios
- replacing unit, browser, or production smoke checks
- storing raw uploaded documents, private runtime data, or generated graph
  artifacts in git

## Guardrails

- `.understand-anything/` is ignored in `.gitignore`.
- `.understandignore` is tracked and excludes generated output, local agent
  scratch, logs, secrets, binary assets, and build artifacts.
- Do not enable Understand-Anything auto-update hooks on Wiii until graph
  versioning policy is approved.
- Do not commit `node_modules`, generated dashboards, generated graphs, or
  intermediate scan files.
- Treat LLM-authored graph summaries as navigation aids, not architecture
  authority. Code, tests, Wiii Self-Harness, and operating docs remain
  authoritative.
- Re-run deterministic scan/import-map when a future audit touches a large
  dependency hub.
- Keep repo-owned flow profiles in
  `tools/wiii_understand_harness/run_wiii_understand_flow_map.py` focused on
  active Wiii flows, not broad directory dumps.

## Follow-Up Issues

Open separate issues before expanding this slice:

1. Keep the repo-owned deterministic scan/import-map wrapper current as Wiii
   flow ownership changes.
   Owner: Project leadership. Target: ongoing.
2. Decide whether a generated knowledge graph should ever be versioned, and if
   so, define size limits, privacy policy, update cadence, and review rules.
   Owner: Project leadership. Target: 2026-06-12.
3. Re-run a scoped graph on `maritime-ai-service/app/engine/multi_agent` before
   the next large Core refactor.
   Owner: Wiii Core maintainer. Target: 2026-06-05.
4. Re-run a scoped graph on `wiii-desktop/src/components/chat` before the next
   frontend chat/visual/Code Studio UX refactor.
   Owner: Wiii Host maintainer. Target: 2026-06-05.
