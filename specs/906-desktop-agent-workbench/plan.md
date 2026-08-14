# Implementation Plan: Desktop Agent Workbench

**Branch**: `codex/906-desktop-agent-workbench` | **Date**: 2026-08-13 | **Spec**: `specs/906-desktop-agent-workbench/spec.md`
**Issue**: #906

## Summary

Repair the shared custom titlebar at its actual Tauri ACL boundary, then make
the titlebar a calm entry point to each app's existing navigation. Add one
Neko-owned command center that projects existing client actions, reported ACP
commands, and persisted sessions. Make sidebar and inspector state explicit
and progressively disclosed. No backend, ACP, persistence, provider, or auth
contract changes are required.

## Technical Context

**Language/Version**: TypeScript 5, React 18, Rust/Tauri v2 configuration
**Primary Dependencies**: Tauri window API, Zustand, Lucide React, Testing Library
**Storage**: Existing local Neko persistence; no schema change
**Testing**: Vitest, TypeScript, Vite, Cargo/Tauri build, native Windows acceptance
**Target Platform**: Tauri desktop; browser/embed must continue to omit titlebar chrome
**Project Type**: Existing desktop application
**Performance Goals**: Local filtering over 200 sessions without perceptible delay
**Constraints**: Vietnamese-first; no new dependency; no reference-code copying; preserve close-to-tray
**Scale/Scope**: Shared titlebar plus the existing Neko workspace shell and tests

## Constitution Check

- **I Native Runtime Ownership**: UI projects existing Wiii/ACP contracts; no
  orchestration or provider layer is introduced. PASS.
- **II Living Memory/Tenant Safety**: search reads the same local session
  records already shown by Neko; no cloud/tenant path changes. PASS.
- **III Streaming-First UX**: working/cancel state remains visible and the
  inspector no longer steals default transcript width. PASS.
- **IV Safe Tools/Host Control**: commands are inserted for review, never
  auto-executed; Tauri ACL is least-privilege. PASS.
- **V Change Discipline**: issue #906, isolated branch, Spec Kit artifacts,
  focused desktop tests, native evidence, and revertable UI/config changes. PASS.

Post-design re-check: no exception is required.

## Architecture

### Shared native chrome

`TitleBar` remains the only renderer of caption controls. It obtains the
current `Window`, queries `isMaximized`, and subscribes to native resize events.
All actions go through one awaited error-reporting helper. Composition slots
allow Wiii to open its existing command palette and Neko to supply its mode,
command-center, and sidebar controls without duplicating caption code.

The capability grants the exact commands invoked by the component. Rust's
existing `CloseRequested` handler continues to implement hide-to-tray.

### Neko command projection

`NekoCommandCenter` builds ephemeral view items from current store state:

- actions: new session, toggle project tree, attach/view project, session info;
- commands: active session's reported commands plus documented client actions;
- sessions: every persisted session using the sidebar's searchable fields.

Selecting a session navigates immediately. Selecting an agent command emits an
insert request to `NekoComposer`, where the draft is focused but not submitted.
No new store or persistence field is needed.

### Progressive workbench layout

`NekoChillApp` owns sidebar, inspector, and palette visibility. The inspector
defaults closed. The sidebar can be restored from the titlebar. At narrow
widths the existing inspector overlay remains; the default transcript stays
uncompressed. New/empty states explain workspace, model/profile, `/`, Ctrl+K,
and stop behavior only when relevant.

## Project Structure

```text
wiii-desktop/
|-- src-tauri/capabilities/default.json
|-- src/components/layout/TitleBar.tsx
|-- src/neko-chill/
|   |-- NekoChillApp.tsx
|   |-- command-items.ts
|   `-- components/
|       |-- NekoCommandCenter.tsx
|       |-- SessionSidebar.tsx
|       |-- NewSessionView.tsx
|       |-- NekoTranscript.tsx
|       |-- NekoComposer.tsx
|       `-- SessionInspector.tsx
|-- src/__tests__/layout/title-bar.test.tsx
`-- src/__tests__/neko-chill/neko-shell-ui.test.tsx
```

**Structure Decision**: Use the existing shared layout and Neko subtree. One
small pure command-item module keeps search deterministic and directly tested;
no general command framework is added.

## Verification and evidence

1. Titlebar tests mock the typed Tauri window API and exercise every action,
   resize synchronization, accessible labels, and failure reporting.
2. Neko UI tests seed multiple projects/commands and exercise Ctrl+K,
   keyboard navigation, command insertion, sidebar/inspector disclosure, and
   empty state.
3. `npx vitest run src/__tests__/layout/title-bar.test.tsx src/__tests__/neko-chill`
4. `npx vitest run`
5. `npx tsc --noEmit`
6. `npm run build:embed`
7. `npm run build` and `cargo check`/Tauri package build as appropriate.
8. Native Windows acceptance and wide/narrow screenshots.

## Risk and rollback

- **ACL risk**: window capabilities are security-sensitive. Grant only the
  five documented window permissions and verify browser builds remain inert.
- **Focus risk**: two command palettes exist by mode. Route Ctrl+K inside the
  already-separated mode trees; do not mount both active palettes together.
- **Session risk**: palette actions operate on current store references and do
  not mutate transcripts except through existing actions.
- **Rollback**: revert the feature PR. No migration, backend data, or user
  configuration must be undone.
