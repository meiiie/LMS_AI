# AGENTS.md - Desktop And Embed

Status: Active

Owner: Frontend maintainers

Applies to: `wiii-desktop/**`

Read the root `AGENTS.md` first. This file narrows guidance for the Tauri,
React, embed, chat, Pointy, voice, and visual-artifact frontend surfaces.

## Frontend Mental Model

The desktop project owns the user-visible shape of Wiii:

- chat input and message rendering
- SSE V3 stream consumption
- preview and source-reference panels
- LMS embed behavior
- Pointy host control
- voice controls and audio UX
- visual/code-studio artifact display
- persisted local settings and session state

Frontend changes are product changes. Even small CSS or Markdown edits can alter
teacher trust, LMS safety, and perceived intelligence.

## High-Risk Surfaces

Treat these as high-risk:

- SSE event handling and final answer assembly
- persisted Zustand stores
- auth token storage and refresh behavior
- embed auth and host bridge messages
- preview/apply UI for LMS host actions
- source references and citation display
- Pointy dispatch and DOM targeting
- microphone, voice, and hotkey behavior
- sandboxed visual/code artifact rendering

## User Experience Contracts

Preserve these contracts unless a PR explicitly changes them:

- Wiii must never show raw internal tool JSON as the final answer.
- Markdown tables, lists, links, and citations must render as readable blocks.
- Mutating LMS actions must stay behind preview and approval.
- Source references must remain visible when an answer uses uploaded documents.
- Pointy should act only when the user enables or invokes that mode.
- Voice mode must clearly show whether it is listening, speaking, or idle.
- Visual artifacts must be framed without clipping important controls or text.
- Vietnamese UI copy should be natural and accented unless the surrounding
  surface is intentionally English.

## Where To Start

Common frontend entry points:

- Chat shell: `src/EmbedApp.tsx`
- Chat input: `src/components/chat/ChatInput.tsx`
- SSE stream hook: `src/hooks/useSSEStream.ts`
- Markdown rendering: `src/components/common/MarkdownRenderer.tsx`
- Markdown styles: `src/styles/markdown.css`
- Preview panel: `src/components/layout/PreviewPanel.tsx`
- Source helpers: `src/lib/source-references.ts`
- Host bridge: `src/lib/embed-bridge.ts`
- Context bridge: `src/lib/context-bridge.ts`
- Pointy host: `src/pointy-host/**`
- Visual artifacts: `src/components/chat/VisualArtifactCard.tsx`,
  `src/components/chat/VisualBlock.tsx`,
  `src/components/common/InlineVisualFrame.tsx`

## Verification

Use focused checks before broad suites:

```powershell
cd wiii-desktop
npx vitest run src/__tests__/tool-execution-strip.test.tsx src/__tests__/interleaved-block-sequence.test.tsx
npx vitest run src/__tests__/preview-panel-ui.test.tsx src/__tests__/context-bridge.test.ts
npx tsc --noEmit
```

For embed-visible changes, run or document a browser/Playwright check. For
visual runtime changes, capture screenshot evidence when practical.

## Editing Guidance

- Keep renderer fixes in renderer or repair helpers, not inside random chat
  components.
- Keep host bridge contracts typed in `src/lib/**` before wiring UI behavior.
- Avoid adding hidden global state for chat lifecycle.
- Prefer explicit UI states over inferred string checks.
- Do not commit `dist`, `dist-embed`, coverage, screenshots from temporary runs,
  local logs, or secrets.
- Do not combine UI polish, voice runtime, and LMS mutation behavior in one PR.
