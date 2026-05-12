# Wiii Memory Index

Status: Active
Last updated: 2026-05-12

This directory stores high-signal handoff notes for future Wiii Agentic sessions. Keep entries short, source-backed, and linked to the deeper handoff file.

## Project Status (Current)

### 2026-05-12 - Product doc-to-course hardening deployed

Read when continuing Wiii x Maritime LMS production readiness, precision document parsing, doc-to-course preview/apply, deployment smoke, or Pointy product E2E:

- [handoff-product-doc-to-course-2026-05-12.md](handoff-product-doc-to-course-2026-05-12.md)

Key anchors:

- Latest production Wiii SHA: `df0d226d3e6f3b7d15fe2fcc611cf26374f99212`.
- Deploy run `25729067217` passed: pinned image validation, precision capacity guard, structured visual lifecycle, public Pointy bundle, and `19 passed, 0 failed`.
- Long maritime research DOCX product smoke passed with Docling: `225491` characters, `168` assets, `6` chapters, `18` lessons, `12` sources, no HoLiLiHu/manual leakage.
- Verified apply smoke passed: LMS preview/diff/citation shown, teacher approval apply succeeded, authenticated API found marker, stale section title absent.
- Merged hardening PRs: `#358`, `#360`, `#362`, `#364`, `#366`, `#368`.
- Remaining true debt: committed Pointy product E2E smoke, page/layout citation fidelity, video pipeline revalidation, vision-provider revalidation, and embed chunk-size performance.

### 2026-05-08 - Realistic Wiii field test and core fixes

Read when continuing production-hardening for Wiii web/search, session memory recall, RAG fallback quality, Pointy explicit actions, or UX streaming:

- [field-test-wiii-realistic-2026-05-08.md](field-test-wiii-realistic-2026-05-08.md)

Key anchors:

- Browser field prompts covered RAG, social, memory store/recall, web search, Pointy explicit highlight, and capability honesty.
- Fixed critical live failures: memory recall misrouted to RAG, explicit web search ending blank/stalling before tool call, answer buffer swallowed at `done`, and OpenAI Responses API source synthesis drifting to unrelated OpenAI blogs.
- Restart-recovery pass also fixed session memory self-read, Vietnamese `Không dùng...` trimming, `[FIELD-CORE-*]` marker route hijack, URL/domain spacing in web answers, and provider-unavailable fallback policy.
- Latest live pass: `FIELD-FINAL-WEB-01` renders real OpenAI docs anchors, `FIELD-RAG-FIX-01` routes to `rag_agent`, `FIELD-508R-06` recalls exactly 3 bullets, `FIELD-CORE-POINTY-01` dispatches `chat-send-button`, and `FIELD-FINAL-SOCIAL-01` answers naturally without tools.
- Latest backend verification: `86 passed`; ruff passed for changed backend/test files.
- Remaining UX debt: raw search widget source list still needs source-cleaning parity with final answer; visible thinking can still feel too narrator-like.

### 2026-05-07 - UI-TARS Desktop review for Pointy / host actions

Read when improving Pointy, host-action feedback, browser/control strategy, or UI action telemetry:

- [ui-tars-desktop-review-2026-05-07.md](ui-tars-desktop-review-2026-05-07.md)

Key anchors:

- External UI-TARS snapshot reviewed at `E:\Sach\Sua\_external\UI-TARS-desktop`, commit `7986f5a`.
- Main lesson: do not clone UI-TARS wholesale; bring its action contract, parser/validator discipline, telemetry, and hybrid DOM/visual strategy into Wiii selectively.
- Implemented first step: structured Pointy dispatch telemetry plus tests.
- Follow-up implemented: direct turn contract, Pointy tag-vs-tool route discipline, `auto:...` synthetic id support across prompt/backend/frontend parser, and deterministic Pointy fast-path answer when action is already resolved.
- Latest verification: backend route/prompt/Pointy subset `122 passed`; frontend Pointy subset `9 passed`, `159 tests passed`; `npx tsc --noEmit` passed.
- Browser smoke on `http://127.0.0.1:1420/`: prompt `nút gửi tin nhắn ở đâu` now answers consistently with cursor action: `Mình đã trỏ vào Gửi tin nhắn cho cậu thấy ngay.`

### 2026-05-07 - Pointy v9/F18 handoff and verified state

Read first when continuing Pointy body-schema, SSE, dispatch queue, or cursor motion work:

- [handoff-pointy-v9-f18-2026-05-07.md](handoff-pointy-v9-f18-2026-05-07.md)

Key anchors:

- Pointy has two primary dispatch paths: explicit `[POINT:<bare-id>]` tags and embodied prose fallback.
- `pointy_action` SSE remains a compatibility/wire-regression path.
- Latest targeted verification recorded here: backend presenter `12 passed`; frontend Pointy subset `91 passed`.
- Protect the dirty worktree; do not revert unrelated changes.

### 2026-05-07 - Next-session bootstrap prompt

Use this when opening a new Codex session for the next phase:

- [next-session-prompt-2026-05-07.md](next-session-prompt-2026-05-07.md)

Key anchors:

- Reads 8 required sources in order.
- Preserves the seven thinking rules, priority order, six-step workflow, and anti-pattern list.
- Starts with a fixed Vietnamese opening line so the next session enters the right tone and process.

## Maintenance Rules

- Add newest entries at the top of `Project Status (Current)`.
- Prefer exact file paths, commands, and observed test results.
- Distinguish verified facts from planned next steps.
- If a handoff file references a manual smoke, include the exact date, command, environment, and outcome.
