# Pointy v9/F18 handoff - 2026-05-07

Status: current handoff
Owner: Wiii Agentic / Pointy workstream
Workspace: `E:\Sach\Sua\AI_v1`
Branch observed: `main...origin/main`

## TL;DR

Pointy is now best understood as Wiii's on-screen body, not primarily as a backend tool. The reliable contract is a hybrid:

1. Deterministic explicit tag path: the model emits `[POINT:<bare-id>]` or `[POINT:<bare-id>:<caption>]`; frontend parses it from the streamed answer and queues cursor movement.
2. Embodied fallback path: if prose naturally mentions an available UI target with a pointing/clicking/location intent, frontend detects the target from the answer text and queues cursor movement.

Both paths converge on `pointy.pointAt(...)`, then `resolveSelector(...)`, then the spring/min-jerk `CursorRegistry` motion layer.

The legacy/tool-compatible `pointy_action` SSE path still matters as a compatibility surface. Do not remove it casually; it catches tool/host-action based commands and is a useful wire-level regression guard.

## Final Verification In This Session

Backend presenter regression:

```powershell
cd maritime-ai-service
$env:PYTHONIOENCODING='utf-8'; python -m pytest tests/unit/test_chat_stream_presenter.py -q -p no:capture --tb=short
```

Result: `12 passed in 4.39s`.

Frontend Pointy parser/queue/motion regression:

```powershell
cd wiii-desktop
npx vitest run src/__tests__/dispatch-multi-target.test.ts src/__tests__/inline-tag-parser.test.ts src/__tests__/embodied-parser.test.ts src/pointy-host/__tests__/min-jerk-trajectory.test.ts src/pointy-host/__tests__/motion-engine.test.ts
```

Result: `5 passed`, `91 tests passed`.

Direct `pytest ...` was not available on PATH in this shell; `python -m pytest ...` worked.

## Architecture

### Dispatch Path 1: explicit tag

Source contract:

- Backend host context tells the LLM to use exact inventory ids and append `[POINT:<id>]` at the end when the user asks about UI.
- Valid tag grammar is `[POINT:<bare-id>]`, `[POINT:<bare-id>:<caption>]`, or `[POINT:none]`.
- Bare ids are intentionally not CSS selectors.

Runtime flow:

1. `WiiiDesktopHostAdapter` injects inventory and body-schema instructions into the model context.
2. Backend streams answer tokens as `answer` or `answer_delta`; Pointy tags must remain present on the SSE answer stream so frontend can parse them.
3. `useSSEStream.ts` accumulates the raw streamed answer in `fullAnswerTextRef`.
4. `tryStreamingDispatch(...)` calls `parseAllPointTags(...)`.
5. Tags go through `enqueueTagPoints(...)`.
6. Tag enqueue cancels in-flight embodied guesses, clears pending embodied queue items, flips tag-priority for the stream, and dispatches via `pointAt(...)`.

Important source files:

- `maritime-ai-service/app/engine/context/adapters/wiii_desktop.py`
- `wiii-desktop/src/hooks/useSSEStream.ts`
- `wiii-desktop/src/pointy-host/inline-tag-parser.ts`
- `wiii-desktop/src/pointy-host/dispatch-queue.ts`
- `wiii-desktop/src/pointy-host/api.ts`

### Dispatch Path 2: embodied prose fallback

Source contract:

- If the model does not emit a tag, the frontend still scans answer text for element label/synonym plus pointing/clicking/location intent.
- Threshold is intentionally realistic, currently `0.6`.
- The fallback must only use available targets from the scanned page inventory. Do not guess ids.

Runtime flow:

1. `useSSEStream.ts` runs `tryStreamingDispatch(...)` on each answer chunk.
2. On sentence boundary (`.`, `!`, `?`, newline, `~`), it gets targets from the mounted Pointy scanner or `[data-wiii-id]` fallback.
3. `detectAllEmbodiedPoints(...)` scores sentence-target pairs.
4. Matches go through `enqueueEmbodiedPoints(...)`.
5. If an explicit tag has already fired in the same stream, embodied enqueue returns `0`.

Important source files:

- `wiii-desktop/src/hooks/useSSEStream.ts`
- `wiii-desktop/src/pointy-host/embodied-parser.ts`
- `wiii-desktop/src/pointy-host/dispatch-queue.ts`
- `wiii-desktop/src/pointy-host/integration.ts`
- `wiii-desktop/src/pointy-host/scanner.ts`

### SSE compatibility path

This is not the preferred body-schema path, but it remains an important compatibility surface:

1. Runtime or tool bus creates a canonical `pointy_action` payload.
2. `create_pointy_action_event(...)` wraps it as `StreamEvent(type="pointy_action", ...)`.
3. `serialize_stream_event(...)` must include `pointy_action` in its allowlist.
4. `wiii-desktop/src/api/sse.ts` must dispatch `event: pointy_action`.
5. `useSSEStream.ts` handles `onPointyAction` and calls `pointy.pointAt`, `pointy.moveTo`, or `pointy.clear`.

Important source files:

- `maritime-ai-service/app/engine/multi_agent/stream_utils.py`
- `maritime-ai-service/app/api/v1/chat_stream_presenter.py`
- `wiii-desktop/src/api/sse.ts`
- `wiii-desktop/src/hooks/useSSEStream.ts`

## Files Modified Or Central To This Handoff

Six main runtime/transport surfaces to keep in view:

1. `wiii-desktop/src/hooks/useSSEStream.ts`
2. `wiii-desktop/src/api/sse.ts`
3. `wiii-desktop/src/pointy-host/bridge.ts`
4. `maritime-ai-service/app/api/v1/chat_stream_presenter.py`
5. `maritime-ai-service/app/services/chat_stream_coordinator.py`
6. `maritime-ai-service/app/engine/multi_agent/stream_utils.py`

Supporting Pointy/body-schema files:

- `maritime-ai-service/app/engine/context/adapters/wiii_desktop.py`
- `maritime-ai-service/app/engine/skills/library/wiii-pointy/SKILL.md`
- `wiii-desktop/src/pointy-host/inline-tag-parser.ts`
- `wiii-desktop/src/pointy-host/embodied-parser.ts`
- `wiii-desktop/src/pointy-host/dispatch-queue.ts`
- `wiii-desktop/src/pointy-host/api.ts`
- `wiii-desktop/src/pointy-host/motion-engine.ts`
- `wiii-desktop/src/pointy-host/min-jerk-trajectory.ts`
- `wiii-desktop/src/pointy-host/registry.ts`
- `wiii-desktop/src/pointy-host/awareness.ts`

Tests already useful:

- `maritime-ai-service/tests/unit/test_chat_stream_presenter.py`
- `maritime-ai-service/tests/unit/test_sprint222_host_adapters.py`
- `wiii-desktop/src/__tests__/dispatch-multi-target.test.ts`
- `wiii-desktop/src/__tests__/inline-tag-parser.test.ts`
- `wiii-desktop/src/__tests__/embodied-parser.test.ts`
- `wiii-desktop/src/pointy-host/__tests__/min-jerk-trajectory.test.ts`
- `wiii-desktop/src/pointy-host/__tests__/motion-engine.test.ts`
- `wiii-desktop/src/pointy-host/__tests__/registry.test.ts`

## Four Critical Gotchas

### 1. Tuple event bug

The stream coordinator loop expects objects with `.type` and `.content`. If any runtime path yields legacy tuple-style data, it must be normalized before `_with_latency_metadata(...)`, `accumulated_answer`, and `serialize_stream_event(...)` touch it.

Practical invariant: by the time events enter the coordinator serialization loop, they should be `StreamEvent`-like objects, not raw tuples.

### 2. Missing bus converter case

`pointy_action` must be present in every converter/dispatcher layer that sees stream events:

- `StreamEventType.POINTY_ACTION`
- `create_pointy_action_event(...)`
- `serialize_stream_event(...)` allowlist
- frontend `SSEEventHandler.onPointyAction`
- frontend `dispatchEvent(...)` switch case

If any one layer drops it, logs may show "tool dispatched" while the cursor never moves.

### 3. Raw dict yield

Raw dicts are dangerous in the full stream path. A dict can look valid at the producer boundary but still fail later when the coordinator expects `event.type`.

Practical invariant: normalize raw dicts at the boundary into `StreamEvent(type=..., content=..., node=..., details=...)`. Never rely on downstream code to infer an event shape from arbitrary dicts.

### 4. LLM non-determinism

Do not assume the model will always emit `[POINT:...]`, even with clear prompt instructions. The tag path is best when it appears; the embodied parser is the safety net when it does not.

Tests should prove both:

- explicit tag queues and wins over embodied guesses
- natural prose can still dispatch at threshold `0.6`

## Test Playbook

### Manual smoke

1. Start backend and desktop dev app.
2. Open Wiii Desktop.
3. In DevTools, check `window.__wiiiInventory__()` returns visible target ids.
4. Ask: `nút gửi tin nhắn ở đâu`.
5. Expected: Vietnamese prose answer, no raw `[POINT:...]` visible in final chat bubble, cursor moves to the send target.
6. Run `window.__wiiiPointTest__('chat-send-button')` if available to isolate DOM/motion from LLM/SSE.
7. Run `window.__wiiiEmbodiedTest__('Nút gửi tin nhắn ở góc dưới phải nè.')` if available to isolate embodied parsing.

### SSE wire

Check answer streaming and compatibility event behavior separately:

- For body-schema tag/embodied path, answer chunks must reach frontend as `answer` or `answer_delta` and feed `fullAnswerTextRef`.
- For legacy/tool path, capture the stream and confirm `event: pointy_action` is emitted with a `content.action` such as `ui.highlight`.
- Always confirm the stream ends with `event: done`.
- If a cursor command exists in backend logs but not on the wire, inspect `chat_stream_presenter.py` first.
- If it is on the wire but not handled, inspect `wiii-desktop/src/api/sse.ts` and `useSSEStream.ts`.

### Unit

Backend:

```powershell
cd maritime-ai-service
$env:PYTHONIOENCODING='utf-8'; python -m pytest tests/unit/test_chat_stream_presenter.py tests/unit/test_sprint222_host_adapters.py -q -p no:capture --tb=short
```

Frontend:

```powershell
cd wiii-desktop
npx vitest run src/__tests__/dispatch-multi-target.test.ts src/__tests__/inline-tag-parser.test.ts src/__tests__/embodied-parser.test.ts src/pointy-host/__tests__/min-jerk-trajectory.test.ts src/pointy-host/__tests__/motion-engine.test.ts src/pointy-host/__tests__/registry.test.ts
```

Repository hygiene:

```powershell
git diff --check
git status --short
```

### Stress

Run or add tests for:

- Multiple tags in one answer: cursor visits in order.
- Duplicate targets: queue dedupes stable signatures.
- Tag emitted after embodied has already guessed: tag cancels embodied.
- Missing selector: queue emits `wiii:pointy:dispatch-failed` and advances instead of stalling.
- New stream starts while old queue is active: `clearDispatchQueue()` resets state.
- Slow token stream: parser still dispatches on sentence boundary and final `onDone` safety pass.
- Reduced motion: `MotionEngine` snaps instead of animating.
- Model does not emit tag: embodied path still works if target and intent are source-backed.

## Open Paths Forward

### Priority 1: cursor motion math

Goal: make movement feel intentional, stable, and physically credible.

Recommended plan:

1. Read `min-jerk-trajectory.ts`, `motion-engine.ts`, `registry.ts`, and their tests.
2. Add focused tests before editing for edge geometry:
   - very small target width
   - very large viewport distance
   - mid-flight target redirect
   - dock return after pointAt
   - reduced-motion branch
   - transform rounding and no jitter at rest
3. Inspect `CURSOR_TIP_X` / `CURSOR_TIP_Y` and target center math in `api.ts`.
4. Keep changes surgical; do not mix motion math with parser/SSE changes.
5. Re-run Pointy frontend suite.

### Priority 2: awareness and feedback

Goal: make Wiii aware of where its body is and when dispatch failed.

Recommended plan:

1. Read `awareness.ts`, `integration.ts`, `user-attention.ts`, and host context injection.
2. Make the awareness snapshot source-backed and compact enough for prompts.
3. Preserve bridge compatibility with LMS/WebMCP style contracts.
4. Prefer `WidgetResultV1`-style thinking for future feedback surfaces: `widget_id`, `widget_kind`, `status`, `summary`, `payload`, `session_id`, `message_id`, `timestamp`.
5. Do not dump raw payloads into chat.

### Priority 3: art and personality

Goal: polish cursor art only after behavior is stable.

Recommended plan:

1. Preserve no-jitter constraints: no transform CSS animation competing with JS `translate3d`.
2. Keep `pointer-events: none`.
3. Keep accessibility and reduced-motion behavior.
4. Make visual state changes expressive but testable.

## Anti-Patterns To Avoid

- Do not revive `tool_pointy_*` as the main path. It may exist as compatibility, not as the body-schema path.
- Do not guess ids outside `available_targets`.
- Do not emit CSS selectors in `[POINT:...]`; use bare ids.
- Do not strip `[POINT:...]` before the frontend parser has seen the raw answer text.
- Do not claim "cursor moved" unless dispatch success is visible or verified.
- Do not combine parser, SSE, motion, art, and docs changes in one unbounded patch.
- Do not treat CodeRabbit/Codex review as a replacement for human ownership on high-risk surfaces.
- Do not trust a single manual smoke if unit/wire contract tests are missing.

## Current Context Notes

- `sse_capture.txt` exists and shows a completed SSE stream with `event: done`, but it is not by itself a full Pointy proof.
- A capture in that file references model `deepseek-ai/deepseek-v4-flash`, provider `nvidia`, and a successful `done` event after metadata.
- Worktree observed on 2026-05-07 was very dirty with many unrelated modified/untracked files. Future work must protect existing user changes and avoid broad revert/reset.
