# Implementation Plan: Desktop ADE Activation

**Branch**: `codex/949-feat-desktop-ade-activation` | **Date**: 2026-08-24 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/949-desktop-ade-activation/spec.md`

## Summary

Activate the existing ADE ontology as the default local desktop product model.
A small Wiii work repository persists a validated `AdeGraph`; the new local
shell creates Task/Run records before dispatch and passes their identities into
the existing Neko Control path. Neko Chill remains intact as the manual Agent
Fabric/session console and receives only narrow navigation/context taxonomy
changes.

## Technical Context

**Language/Version**: TypeScript 5.x, React 18, Rust stable (existing native runtime)
**Primary Dependencies**: Zustand, Tauri v2 plugin-store, existing Neko Control client/runtime
**Storage**: Strict versioned local Tauri store with browser fallback through `src/lib/storage.ts`
**Testing**: Vitest/Testing Library, TypeScript, existing Rust/Tauri gate, Vite build
**Target Platform**: Wiii Desktop on Windows, Linux and macOS; local browser development fallback
**Project Type**: Tauri desktop application
**Performance Goals**: Hydrate small ADE graph before local shell becomes interactive; no per-token work-state writes
**Constraints**: Offline-capable, persistence-before-dispatch, backwards-compatible Neko transcripts, no backend migration
**Scale/Scope**: One initial Run per created Task; existing Neko Core, Gemini CLI and Codex providers

## Constitution Check

- **Native Runtime Ownership**: Pass. Execution still goes through Neko Control;
  UI receives no raw process authority.
- **Living Memory With Tenant Safety**: Not affected. Knowledge remains an
  optional context capability and no managed memory data is copied locally.
- **Streaming-First UX**: Pass. Existing Neko streams remain unchanged; work
  records add explicit launch/failure state outside the transcript.
- **Safe Tools And Host Control**: Pass. Work is committed before provider side
  effects and no new filesystem command is introduced.
- **Multi-Agent Change Discipline**: Pass. Issue #949 deliberately excludes
  daemon extraction, worktrees, editor/LSP, cloud/backend and new providers.

Post-design check: the storage contract stays Wiii-owned, the execution binding
stays Neko-owned, provider conversation identity remains opaque, and Git/files
remain source truth.

## Project Structure

### Documentation

```text
specs/949-desktop-ade-activation/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── work-execution.md
└── tasks.md
```

### Source Code

```text
wiii-desktop/src/
├── ade/
│   ├── domain.ts
│   ├── lifecycle.ts
│   ├── persistence.ts
│   ├── store.ts
│   └── WiiiAdeApp.tsx
├── neko-chill/
│   ├── NekoChillApp.tsx
│   ├── persistence.ts
│   ├── drivers/factory.ts
│   ├── stores/neko-session-store.ts
│   └── components/SessionInspector.tsx
└── App.tsx

wiii-desktop/src/__tests__/
├── ade/
└── neko-chill/
```

**Structure Decision**: Extend the established `src/ade` and `src/neko-chill`
boundaries. Do not add a second runtime manager or product-wide state container.

## Design Decisions

1. **Separate work snapshot**: ADE product state uses its own store rather than
   extending provider transcript snapshots.
2. **Strict hydration**: Unsupported/corrupt snapshots produce an actionable
   error; no default save occurs until the user explicitly creates work.
3. **Persistence barrier**: `createTaskRun` commits a valid graph, returns the
   execution binding, and only then may UI call Neko `createSession`.
4. **Binding in visible session**: Store execution identity with the Neko
   session so replacement/reconciliation reuses real ADE IDs after reload.
5. **Thin activation shell**: Build Work/Projects plus Task creation and status,
   not a speculative editor, dashboard or orchestration framework.
6. **Preserve Neko UI**: The existing session-first shell is correct inside
   Neko Chill; it becomes a subordinate surface rather than being rewritten.

## Failure Modes And Rollback

- Corrupt ADE state: fail closed and show retry/recovery guidance; never
  overwrite automatically.
- Commit succeeds, provider fails: retain Task/Run and transition Run to failed.
- Native outcome uncertain: persist `unknown_outcome`, do not retry.
- AgentSession record commit fails after native attach: Neko's persisted
  execution binding preserves recovery identity; show failure rather than
  claiming an attached work record.
- Rollback: the new ADE store can be ignored by the previous release; existing
  Neko transcript schema accepts absence of the optional binding.

## Verification

```powershell
cd wiii-desktop
npx vitest run src/__tests__/ade src/__tests__/neko-chill
npx tsc --noEmit
npm run build
cd src-tauri
cargo test --locked
cargo clippy --locked --all-targets -- -D warnings
cargo build --locked
```

Capture desktop browser/Tauri screenshots for fresh work home, new-task flow,
task-bound Neko session and Neko manual launcher.

## Complexity Tracking

No constitution violations. The new Zustand store is a projection over one
strict persistence module, not a second execution authority.
