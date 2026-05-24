# Wiii Next Session Zero-Debt Handoff

Status: Active handoff

Owner: Project leadership

Created: 2026-05-24

Purpose: give the next Codex section enough durable context to continue Wiii
technical-debt cleanup without relying on this long chat thread.

## Read This First

This handoff is intentionally operational. It is not a replacement for:

- `AGENTS.md`
- `docs/operations/WIII_GITHUB_GOVERNANCE.md`
- `docs/operations/WIII_AGENTIC_CODEBASE_HARNESS.md`
- `docs/WIII_PROJECT_MENTAL_MODEL.md`
- path-specific `AGENTS.md` files
- relevant `.agents/skills/**/SKILL.md`

The next section should start by reading those files, then this handoff, then
only the focused files for the next slice.

## Current Repository State

Working repo:

```text
E:\Sach\Sua\AI_v1_product
```

Expected base branch:

```text
main
```

As of the end of the previous section, `main` was synced with `origin/main`
after these cleanup PRs landed:

- `#616` `refactor(backend): type code studio node preflight`
- `#618` `fix(desktop): harden visual frame UX harness`
- `#620` `refactor(backend): type code studio node lifecycle`

Important local verification already completed in the previous section:

- backend Code Studio focused tests passed
- graph-routing ambiguous simulation regression passed
- backend targeted ruff passed
- desktop visual frame focused Vitest passed
- `npx tsc --noEmit` passed
- `npm run build:embed` passed
- Playwright smoke against `http://127.0.0.1:1420/` returned HTTP 200 with no
  console/page errors on the unauthenticated shell
- `git diff --check` passed

Known CLI gotcha:

- `uv run` may create `maritime-ai-service/uv.lock`; remove it only after
  verifying the resolved absolute path is exactly
  `E:\Sach\Sua\AI_v1_product\maritime-ai-service\uv.lock`.
- PowerShell does not support Bash `&&`; run commands separately.

## Product Goal To Preserve

The original product goal remains:

1. Teacher uploads Word/PDF in LMS product.
2. Wiii parses and grounds to the uploaded document.
3. User says "tạo cho mình bài học" / "tạo bài giảng".
4. Wiii calls a preview host action.
5. Wiii must not ask vague follow-up questions when the document and intent are
   sufficient.
6. Wiii must not invent wrong templates, COLREG content, or unsupported source
   facts when an uploaded document is present.
7. LMS shows preview/diff/citations/source references.
8. Teacher presses Apply.
9. Apply uses `approval_token`.
10. Draft content appears clearly in the course editor.

Hard safety rule:

```text
Never let Wiii mutate LMS course content without preview + approval_token.
```

Do not hardcode behavior for `BanGioiThieu_NCKH_25_26.43.docx` or any single
file.

## What "Debt Equals Zero" Means

Do not interpret "zero debt" as "no file is large" or "no future refactor is
possible." In this project, "debt = 0" means:

- no known high-risk debt in the active product goal is undocumented
- no duplicated logic remains on the active request path without a typed
  contract or an issue
- no broad deterministic fallback can silently create misleading LMS/visual
  output
- no user-facing mojibake/markdown/rendering bug remains in the touched UX path
- every meaningful behavior change has targeted tests
- every merge has issue, PR, verification, risk notes, and rollback notes
- any remaining large module is either actively owned, documented, or outside
  the current product-critical slice

If a debt is discovered but too large to safely finish in one slice, create a
tracking issue and document why it is deferred.

## Current Cleanup Progress

Recently cleaned:

- `direct_node_runtime.py` is no longer the primary debt hotspot.
- direct pre-LLM stages now have typed preflight/document/image/fast-response
  contracts.
- Code Studio node now has:
  - typed preflight contract
  - typed provider execution contract
  - typed scaffold fallback intent/policy
  - typed event sink contract
  - typed final-state contract
- Visual iframe runtime now has:
  - typed `wiii-visual-sync`
  - explicit `sizingMode`
  - iframe runtime dataset markers
  - host ready/busy state
  - focused visual frame tests

The next real debt is no longer "split the node." It is capability sync and
visual intent/tool routing.

## Highest-Value Next Debt

### 1. Visual Intent And Tool Capability Sync

Likely files:

- `maritime-ai-service/app/engine/multi_agent/visual_intent_resolver.py`
- `maritime-ai-service/app/engine/multi_agent/visual_intent_support.py`
- `maritime-ai-service/app/engine/multi_agent/visual_intent_presets.py`
- `maritime-ai-service/app/engine/multi_agent/tool_collection.py`
- `maritime-ai-service/app/engine/multi_agent/visual_runtime_metadata_contract.py`
- `maritime-ai-service/app/engine/tools/visual_code_runtime_contract.py`
- `maritime-ai-service/app/engine/tools/code_studio_app_intent_contract.py`

Why it matters:

- This is where Wiii decides whether a request should be text, chart runtime,
  article figure, Code Studio app, artifact, Mermaid, or LMS host action.
- It is the next likely source of drift: user asks for one thing, Wiii binds the
  wrong tool/lane.
- It controls the long-term fix for "template fallback rộng" and "Wiii dùng
  Pointy/tool sai lane."

Desired direction:

- keep visual intent as a typed decision
- make tool filtering/capability inventory deterministic and testable
- avoid duplicate cue lists across resolver, tool collection, and runtime
  metadata
- preserve Vietnamese and mojibake-tolerant matching where product data already
  contains legacy strings
- prefer canonical Unicode Vietnamese in new tests/copy

Suggested first PR:

```text
refactor(backend): type visual intent tool requirements
```

Possible issue title:

```text
Make visual intent tool requirements auditable
```

Acceptance:

- `required_visual_tool_names()` becomes the single source for required visual
  tools.
- `tool_collection.py` consumes a typed visual tool requirement/capability
  contract instead of repeating intent interpretation.
- tests cover:
  - chart request keeps `tool_generate_visual`
  - simulation/app request requires `tool_create_visual_code`
  - artifact request requires `tool_create_visual_code`
  - Mermaid request does not drift to legacy chart/app tools
  - analytical/text request leaves non-visual tools alone
  - explicit web search remains stronger than visual intent when applicable

### 2. Code Studio Tool Rounds And Scaffold Boundary

Likely files:

- `maritime-ai-service/app/engine/multi_agent/code_studio_tool_rounds.py`
- `maritime-ai-service/app/engine/multi_agent/code_studio_scaffold_fallback_policy.py`
- `maritime-ai-service/app/engine/multi_agent/code_studio_template_scaffold.py`

Why it matters:

- `code_studio_tool_rounds.py` still carries timeout/tool-loop/scaffold bridging
  complexity.
- Scaffold fallback is now contract-gated, but the injection path should stay
  narrow and auditable.

Desired direction:

- isolate tool-round timeout outcomes from scaffold fallback resolution
- keep scaffold fallback as a last-resort typed decision
- never allow generic simulation/app templates to masquerade as successful
  previews

Suggested PR:

```text
refactor(backend): type code studio tool-round outcomes
```

### 3. VisualBlock And Code Studio UX Surface

Likely files:

- `wiii-desktop/src/components/chat/VisualBlock.tsx`
- `wiii-desktop/src/components/layout/CodeStudioPanel.tsx`
- `wiii-desktop/src/components/common/InlineVisualFrame.tsx`
- `wiii-desktop/src/lib/visual-frame-document.ts`
- `wiii-desktop/src/lib/visual-frame-contract.ts`

Why it matters:

- Users complained about iframe clipping, markdown/code streaming, and
  "artifact/visual" presentation quality.
- The visual iframe harness is improved, but real authenticated Code Studio
  local E2E still needs screenshot evidence when dev login/session is available.

Desired direction:

- keep visual app chrome host-owned
- avoid nested cards and clipped iframes
- show code streaming and preview state clearly
- keep Vietnamese labels correct
- no raw HTML/JSON/tool-call payloads in chat

Suggested PR:

```text
fix(desktop): polish visual block code studio shell
```

### 4. LMS Document Preview Apply E2E

Likely files:

- `maritime-ai-service/app/engine/multi_agent/direct_document_*`
- `maritime-ai-service/app/engine/multi_agent/direct_tool_rounds_runtime.py`
- `wiii-desktop/src/lib/document-followup-intent.ts`
- host action / preview panel tests
- LMS embed and host receiver code

Why it matters:

- This is the original business-critical bug.
- Backend local unit tests were green, but product/local E2E should be repeated
  after each major capability-routing refactor.

Desired direction:

- upload real DOCX/PDF
- ask "tạo cho mình bài học"
- confirm preview host action, citations/source refs, diff, Apply with
  `approval_token`, and draft content in course editor
- if product still fails, trace:
  - frontend `document_context`
  - SSE payload
  - backend tool routing
  - host_action emit
  - LMS receiver

## Skills To Use

Always read only the needed parts of each skill.

Mandatory at session start:

- `software-change-management-using-git`
- `debugging-strategies`

Use when touching Wiii/LMS/host actions:

- `wiii-app-widget-bridge`

Use when touching visual/code studio runtime:

- `wiii-visual-runtime`
- `wiii-code-studio-director`
- `wiii-code-studio-critic`
- `wiii-artifact-composer`
- `wiii-canvas-simulation`
- `wiii-chart-runtime`

Use when testing browser/localhost:

- `browser:browser` or Playwright fallback
- `chrome-extension-routing` only if the task specifically involves the Codex
  Chrome extension or in-browser route diagnosis
- `webapp-testing` when doing local app E2E and screenshots

Use when UI/accessibility is touched:

- `accessibility-compliance`
- `responsive-design`

Use when touching Tauri/native shell:

- `tauri`

Use when the user asks for diagrams/spec-driven planning:

- relevant `speckit-*` skills

## External References To Re-Check When Needed

Use primary sources first. These links were verified from web search on
2026-05-24 and should be re-opened if exact details matter in a future turn.

- Anthropic, "How Claude Code works in large codebases: Best practices and
  where to start":
  `https://claude.com/blog/how-claude-code-works-in-large-codebases-best-practices-and-where-to-start`
- Anthropic engineering, "Claude Code: Best practices for agentic coding":
  `https://www.anthropic.com/engineering/claude-code-best-practices`
- OpenHuman repository:
  `https://github.com/tinyhumansai/openhuman`
- OpenHuman skills registry:
  `https://github.com/tinyhumansai/openhuman-skills`
- Pipecat repository:
  `https://github.com/pipecat-ai/pipecat`
- UI-TARS paper:
  `https://arxiv.org/abs/2501.12326`

How to use them:

- Claude Code large-codebase guidance: scope each section, avoid context debt,
  make durable docs, use fresh prompt + narrow task, verify with tests.
- OpenHuman: borrow architecture ideas only, not code blindly: typed tools,
  turn lifecycle, memory/provenance, approval as first-class contract,
  capability inventory, token/context compression before LLM.
- Pipecat: voice/RTVI/VAD/transport concepts only when working on realtime
  voice. Do not add GPU requirements unless the chosen STT/TTS/VAD provider
  requires it.
- UI-TARS: GUI perception/grounding and action safety concepts for Pointy/LMS
  host action work. Do not let Pointy click when the user asked for code/visual
  generation.

## Clean Code And Architecture Rules

Use these rules for every slice:

1. Prefer typed contracts over implicit dict conventions.
2. Keep node runtimes thin; move lifecycle stages into named helpers.
3. Keep side effects visible and injectable in tests.
4. One source of truth for capability/tool inventory.
5. One source of truth for preview/apply approval contracts.
6. No broad deterministic template fallback on app/simulation lanes.
7. Preserve Vietnamese-first user copy.
8. New Vietnamese text should be valid Unicode, not mojibake.
9. Existing mojibake-tolerant tests may remain only when they intentionally
   guard legacy data.
10. Use structured parsers/contracts instead of ad hoc string parsing when
    possible.
11. Do not mix deploy, runtime behavior, docs cleanup, and frontend redesign in
    one PR unless the issue explicitly says so.
12. No secrets, `.env*`, logs, generated dist, dependency folders, coverage,
    or local screenshots in commits.
13. Add focused tests proportional to risk.
14. After a refactor, the public behavior should be unchanged unless the issue
    is explicitly a behavior fix.

## Test Matrix

Backend focused:

```powershell
cd maritime-ai-service
uv run --python 3.12 --extra dev pytest tests/unit/<focused-test>.py -q --tb=short
uv run --python 3.12 --extra dev ruff check <changed files>
```

Desktop focused:

```powershell
cd wiii-desktop
npx vitest run src/__tests__/<focused-test>.test.tsx --pool forks --maxWorkers=1
npx tsc --noEmit
npm run build:embed
```

Repository:

```powershell
git diff --check
git status --short --branch
```

Browser/localhost:

- If a dev server is already running at `http://127.0.0.1:1420/`, smoke it.
- If authenticated UX is needed, use the in-app browser or Playwright with the
  existing local auth state when available.
- Capture evidence for frontend-visible changes, or state why screenshots were
  not available.

LMS product/local E2E:

- Upload a real DOCX/PDF.
- Ask "tạo cho mình bài học" or "tạo bài giảng".
- Verify host preview action, not chat-only text.
- Verify preview/diff/citations/source references.
- Verify Apply uses `approval_token`.
- Verify draft content appears in the course editor.

## Governance And PR Rules

Use the repo governance unless the user explicitly gives an emergency override.

Normal flow:

1. `git status --short --branch`
2. create or link issue
3. create branch from `main`
4. make scoped edits
5. run focused checks
6. `git diff --check`
7. commit with conventional title
8. push
9. open PR with:
   - summary
   - linked issue
   - scope / non-scope
   - verification commands and results
   - risk / rollback
   - reviewer focus
10. watch CI
11. merge only when safe

Branch naming:

```text
codex/<issue-number>-<type>-<outcome-slug>
```

Examples:

```text
codex/621-refactor-visual-tool-requirements
codex/622-fix-code-studio-visual-block-shell
```

PR title:

```text
refactor(backend): type visual intent tool requirements
fix(desktop): polish code studio visual shell
test(lms): cover document preview approval apply
```

CodeRabbit / bypass rule:

- If all repo-owned checks are green and CodeRabbit fails only with
  `Insufficient review credits`, add a governance comment:

```text
Governance note: repo-owned checks are green for this PR (...list checks...).
CodeRabbit failed with "Insufficient review credits", so there is no actionable
automated review feedback to resolve. Proceeding with maintainer/admin merge
under the active cleanup mandate.
```

- Then merge with admin if branch protection blocks normal merge:

```powershell
gh pr merge <PR> --squash --admin --delete-branch
```

- Do not bypass if any repo-owned check fails, if there is an unresolved
  security/auth/LMS approval risk, or if CodeRabbit provides actionable review
  feedback rather than a credit failure.

## Suggested Next Prompt

The user can paste this into the next section:

```text
/goal Tiếp tục Wiii zero-debt cleanup từ handoff:

Trước hết đọc:
- AGENTS.md
- maritime-ai-service/AGENTS.md nếu chạm backend
- wiii-desktop/AGENTS.md nếu chạm frontend
- docs/operations/WIII_GITHUB_GOVERNANCE.md
- docs/operations/WIII_AGENTIC_CODEBASE_HARNESS.md
- docs/WIII_PROJECT_MENTAL_MODEL.md
- docs/operations/WIII_NEXT_SESSION_ZERO_DEBT_HANDOFF_2026-05-24.md

Dùng SKILL tối thiểu:
- software-change-management-using-git
- debugging-strategies
- wiii-app-widget-bridge nếu chạm LMS/host action
- wiii-visual-runtime, wiii-code-studio-director, wiii-code-studio-critic nếu chạm visual/Code Studio
- webapp-testing/browser nếu cần test localhost/browser

Mục tiêu:
Giải quyết nợ kỹ thuật còn lại cho đến khi không còn debt kiến trúc quan trọng
trong active product path. Định nghĩa "debt = 0" theo handoff: không còn debt
high-risk undocumented, không còn duplicated active-path logic thiếu typed
contract, không còn fallback rộng gây output sai, tests xanh, PR có issue/risk/
rollback/verification rõ.

Ưu tiên tiếp theo:
1. Visual intent + tool capability sync:
   - visual_intent_resolver.py
   - visual_intent_support.py
   - visual_intent_presets.py
   - tool_collection.py
   - visual_runtime_metadata_contract.py
   - visual_code_runtime_contract.py
   - code_studio_app_intent_contract.py
   Mục tiêu: typed visual tool requirement/capability contract, một nguồn sự
   thật cho tool cần bind, không drift giữa chart/article/app/artifact/Mermaid,
   không rơi vào legacy visual tools sai lane.

2. Sau đó bóc tiếp code_studio_tool_rounds.py nếu còn scaffold/tool-loop debt:
   typed tool-round outcomes, scaffold fallback chỉ là contract-gated last resort.

3. Sau đó quay lại frontend VisualBlock/CodeStudioPanel UX nếu còn clipping,
   markdown/code streaming display, raw payload, hoặc tiếng Việt lỗi.

4. Cuối cùng chạy lại LMS document preview/apply E2E:
   upload DOCX/PDF thật -> "tạo cho mình bài học" -> preview host action ->
   citations/source refs -> Apply bằng approval_token -> draft hiện trong course editor.

Ràng buộc:
- Không hardcode theo file BanGioiThieu.
- Không mutate LMS nếu chưa qua preview + approval_token.
- Không cho Pointy click khi user đang yêu cầu tạo code/visual/mô phỏng.
- Không bịa nội dung ngoài tài liệu khi đã có uploaded document.
- Không commit secrets, .env*, logs, dist, coverage, screenshots tạm.
- Giữ tiếng Việt user-facing đúng dấu, không mojibake trong copy mới.
- Dùng apply_patch cho edits thủ công.
- PowerShell không dùng &&.
- Nếu uv tạo maritime-ai-service/uv.lock thì xóa sau khi verify đúng absolute path.

Quy trình:
- kiểm tra git status/worktree
- mở issue cho từng lát cắt non-trivial
- branch codex/<issue>-<type>-<slug>
- sửa scoped, test focused, git diff --check
- mở PR với summary/scope/non-scope/verification/risk/rollback
- nếu repo-owned checks xanh và CodeRabbit chỉ fail vì Insufficient review credits,
  comment governance note rồi admin squash merge
- sau merge sync main và tiếp tục lát cắt kế tiếp

Hãy tiến hành, đừng dừng ở phân tích; chỉ dừng nếu gặp blocker thật sự hoặc rủi
ro production/LMS approval không thể tự xác minh.
```
