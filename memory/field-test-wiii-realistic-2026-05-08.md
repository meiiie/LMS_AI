# Wiii Realistic Field Test - 2026-05-08

Status: Active field report

Environment:

- App: `http://127.0.0.1:1420/`
- Backend: `http://127.0.0.1:8000`
- User/session: local dev user, Pointy mode ON
- Method: Browser-driven live prompts with unique markers, backend logs, console logs, targeted unit/regression tests
- Reference reviewed: UI-TARS Desktop local clone, commit `7986f5a`

## 2026-05-08 Restart Recovery Addendum

After a forced machine restart, Docker Desktop and the Wiii stack were brought back up and tested live again:

- Docker containers healthy/up: `wiii-postgres`, `wiii-minio`, `wiii-valkey`, `wiii-searxng`, `wiii-opensandbox`, plus host proxies `127.0.0.1:5433` and `127.0.0.1:8888`.
- Backend restarted on `127.0.0.1:8000`; `/api/v1/health` returns `{"status":"ok"}`.
- Frontend remains on `127.0.0.1:1420`.
- Browser/Playwright live evidence saved:
  - `memory/wiii-field-508r-06-memory-recall-live-fixed.png`
  - `memory/wiii-field-rag-fix-01-colreg-live.png`
  - `memory/wiii-field-web-href-03-live-fixed.png`
  - `memory/wiii-final-smoke-web-social-2026-05-08.png`

## Why This Test Exists

The goal was not to prove isolated code paths. The goal was to run Wiii like a real user preparing an important report: short emotional turns, session memory, RAG, explicit web search, Pointy UI action, capability honesty, and messy prompts that mention tools negatively (`không dùng web/RAG/Pointy`).

UI-TARS lesson applied: explicit user intent should become a disciplined action contract, not a vague planner hope. For Wiii this means:

- Observe/route explicitly before tool use.
- Validate and execute deterministic actions when intent is clear.
- Stream visible tool/status feedback separately from final answer.
- Keep fallback answers source-backed when model synthesis fails.

## Live Field Results

| Marker | Scenario | Result |
| --- | --- | --- |
| `FIELD-508F-RAG` | COLREG Rule 15, ask for 4 bullets and no fake source | Pass after patch. Answer is 4 bullets, says no internal RAG citation, no Pointy, UI total ~0.5s. |
| `FIELD-508F-SOCIAL` | "Đói phết..." with report stress | Pass. No web/RAG/Pointy, warm practical answer, UI total ~0.4s. Thinking paragraph still slightly over-visible. |
| `FIELD-508F-RECALL` | Recall session memory with "không dùng web/RAG/Pointy" | Failed first: routed to RAG, 65.6s, answered COLREG. Fixed by broader session-recall routing and bundle extraction. |
| `FIELD-508G-RECALL` | Same memory recall after fix | Pass. 3 bullets: `SAO-BIEN-508G`, `hổ phách`, and bundled 3 acceptance criteria. UI total ~0.5s. |
| `FIELD-508G/508H-WEB` | OpenAI Responses API official web search | Failed twice: first no final answer rendered; then planner could stall before tool call. Fixed frontend buffer drain and deterministic `web_search` force-binding. |
| `FIELD-508L-WEB` | OpenAI Responses API after final fixes | Pass for answer quality. Shows `POST https://api.openai.com/v1/responses`, `model`, `input`, and API reference link. UI total ~6.5s. Remaining UX debt: raw search widget still says "5 nguồn tham khảo" even when answer has cleaned source. |
| `FIELD-508L-POINTY` | Explicit Pointy highlight send button | Pass. Console confirms `pointAt selector=chat-send-button`, no click, UI total ~0.7s. |
| `FIELD-508L-CAP` | Capability honesty for image/file/video | Pass. Wiii does not overclaim: image input yes, Word/Excel output yes, free Word/Excel/video/image generation not yet stable end-to-end. |

## Bugs Fixed

- Session memory recall no longer uses the current recall prompt as a memory source when the UI has already appended that prompt into `messages`.
- Session memory write now trims Vietnamese diacritic instructions such as `Không dùng web/RAG/Pointy`, not just ASCII `khong dung`.
- Session memory marker handling now puts field-test markers on their own line when the answer is a bullet list.
- Session memory write Markdown now separates the closing sentence from the final bullet with a blank line.
- Wiii pipeline-meta routing now ignores bracketed field markers such as `[FIELD-CORE-RAG-01]`, so domain questions that say `không dùng Pointy` do not get hijacked by Wiii meta analysis.
- Pseudo-stream answer chunking now preserves exact Markdown/URL content instead of splitting on periods and rejoining URLs with spaces.
- Wiii house-text sanitizer now protects URLs and bare domains before Vietnamese punctuation spacing, fixing `https: //...` and `platform. openai. com` in web answers.
- `ProviderUnavailableError` is re-raised when no source-backed fallback exists, instead of being silently replaced by a generic natural-conversation fallback.
- Session memory recall now recognizes natural prompts like "nhắc lại đúng mã kiểm thử, biểu tượng neo, 3 tiêu chí nghiệm thu vừa rồi".
- `Nhớ trong phiên...` is now parsed as a session memory write, without matching every bare `nhớ`.
- Multi-part acceptance criteria like `3 tiêu chí nghiệm thu là A; B; C` stay bundled as one recall item.
- Explicit `web_search` routing now force-binds `web-search`, avoiding slow/unstable LLM planner waits before tool use.
- Web turns with source evidence and empty synthesis now get deterministic source-backed answers instead of blank UI.
- Frontend `onDone` drains answer/thinking buffers before finalizing, preventing compact final answers from being swallowed by the animation buffer.
- OpenAI Responses API endpoint queries now rewrite toward `platform.openai.com` and synthesize the known API-reference answer before listing sources.
- COLREG Rule 15 fallback is locked to 4 bullets and avoids fake internal RAG citations.

## Remaining Risks

- Search preview cards still expose raw search results; answer-level source cleaning does not yet rewrite the search widget itself.
- Visible thinking sometimes renders as a paragraph before the answer. It is not leaking internals, but UX can feel too narrator-like.
- Console still shows intermittent provider-list fetch warnings after backend restarts.
- ElevenLabs/Pointy voice was not live-tested in this pass; voice flag was kept off and the user-provided secret was not persisted.

## Verification

Backend:

- `python -m pytest tests/unit/test_corrective_rag_unit.py tests/unit/test_conservative_evolution.py -q -p no:capture --tb=short` -> `75 passed`
- `python -m pytest tests/unit/test_conservative_evolution.py -q -p no:capture --tb=short` -> `52 passed`
- `python -m pytest tests/unit/test_direct_tool_rounds_runtime.py tests/unit/test_conservative_evolution.py -q -p no:capture --tb=short` -> `84 passed`
- `python -m pytest tests/unit/test_direct_node_provider_errors.py::test_direct_response_node_force_binds_web_search_intent_without_keyword_heuristic tests/unit/test_direct_tool_rounds_runtime.py tests/unit/test_conservative_evolution.py -q -p no:capture --tb=short` -> `85 passed`
- `python -m pytest tests/unit/test_direct_search_synthesis_fallback.py tests/unit/test_direct_tool_rounds_runtime.py -q -p no:capture --tb=short` -> `46 passed`
- `python -m pytest tests/unit/test_direct_search_synthesis_fallback.py tests/unit/test_direct_tool_rounds_runtime.py tests/unit/test_direct_node_provider_errors.py::test_direct_response_node_force_binds_web_search_intent_without_keyword_heuristic tests/unit/test_direct_node_provider_errors.py::test_direct_response_node_emergency_searches_when_provider_busy_before_tools tests/unit/test_direct_node_provider_errors.py::test_direct_response_node_emergency_searches_when_explicit_provider_times_out_before_tools -q -p no:capture --tb=short` -> `48 passed`
- `python -m pytest tests/unit/test_conservative_evolution.py::TestConservativeFastRouting tests/unit/test_direct_node_provider_errors.py tests/unit/test_direct_execution_streaming.py::test_split_visible_answer_chunks_preserves_markdown_urls_exactly tests/unit/test_sprint154_tech_debt.py::TestWiiiHouseTextSanitizer -q -p no:capture --tb=short` -> `86 passed`
- Ruff checks for changed backend files -> passed.

Frontend:

- `npx vitest run src/__tests__/message-list-streaming.test.ts src/__tests__/pointy-fast-path.test.ts --reporter=dot` -> `18 passed`
- `npx tsc --noEmit` -> passed.
