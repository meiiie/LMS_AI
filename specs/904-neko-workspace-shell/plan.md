# Implementation Plan: Neko Chill Workspace Shell

**Branch**: `codex/904-neko-workspace-shell` | **Date**: 2026-08-13 | **Spec**: `specs/904-neko-workspace-shell/spec.md`
**Issue**: #904

## Summary

Evolve the existing Neko Chill v0 shell without changing its no-login or
local-only boundaries. Add explicit workspace metadata and project-grouped
navigation; extend the normalized driver seam with capability-backed controls,
commands, and session metadata; expose those facts in the composer and a
compact inspector. Use the existing Tauri folder dialog and process transport,
with a small read-only Rust probe for Neko launch profiles. No new dependency
or backend work is required.

## Technical Context

**Language/Version**: TypeScript 5 + React 18; Rust/Tauri v2
**Primary Dependencies**: Zustand + Immer, Lucide React, Tauri store/dialog APIs
**Storage**: Existing tauri-plugin-store/localStorage fallback, additive v2 index
**Testing**: Vitest + Testing Library, TypeScript, Vite embed build, Cargo check/test
**Target Platform**: Tauri desktop (Windows acceptance; macOS/Linux compatible)
**Project Type**: Existing desktop app feature subtree
**Performance Goals**: Search 200 hydrated sessions without visible delay; no token-stream persistence regression
**Constraints**: Pre-auth and local-only; no Wiii backend; no fake capabilities; no Waku code reuse
**Scale/Scope**: One desktop shell, two reference agents, existing local transcripts

## Constitution Check

- **I Native Runtime Ownership**: normalized Wiii-owned contract; ACP stays at
  the driver boundary; no runtime framework added. PASS.
- **II Living Memory/Tenant Safety**: local session metadata only; no auth,
  org, cloud memory, or tenant surface. PASS.
- **III Streaming-First UX**: existing streaming path is preserved; control
  work has explicit pending/error state. PASS.
- **IV Safe Tools/Host Control**: explicit workspace prevents accidental home
  authority; permissions remain fail-closed; profile probing is read-only.
  PASS.
- **V Change Discipline**: issue #904, isolated feature branch, Spec Kit
  artifacts, desktop gates and rollback notes. PASS.

Post-design re-check: no constitution exception is required.

## Architecture

### Workspace flow

The native dialog returns one absolute folder. `createSession` accepts a
`WorkspaceRef` and optional launch profile. That immutable launch config is
passed to `createDriverForAgent`; the factory no longer resolves home. A legacy
session may attach its first workspace, which deliberately disposes any stale
driver and restarts on the next prompt.

### Capability flow

`AcpDriver.start()` normalizes stable config options and legacy mode/model
fields from `session/new`. It keeps a private control-route map. Notifications
replace commands/config/session metadata. The store persists display snapshots
but every live driver start refreshes them. UI selectors call one normalized
`setConfigOption` operation.

### Neko profile flow

After a workspace is selected, a Tauri command runs the already-detected Neko
binary as `neko profiles` with that folder as cwd. A bounded parser accepts only
the documented profile lines. Selecting a profile adds `--profile <id>` to the
ACP launch args and records provider/model; no config file is changed.

### UI hierarchy

- Sidebar: mode switcher, new-session and search actions, workspace groups,
  dense session rows, legacy group.
- New-session view: required workspace, agent roster, Neko launch profile.
- Header: active title/project, runtime status, inspector/close actions.
- Transcript: existing content blocks with a safe reasoning-label cleanup.
- Composer: workspace strip, slash palette, mode/model controls, send/cancel.
- Inspector: local session facts and capability availability; collapses at
  narrower widths.

## Project Structure

```text
wiii-desktop/
|-- src-tauri/src/commands/neko_agent.rs
|-- src/neko-chill/
|   |-- NekoChillApp.tsx
|   |-- workspace.ts
|   |-- components/
|   |   |-- SessionSidebar.tsx
|   |   |-- NewSessionView.tsx
|   |   |-- SessionInspector.tsx
|   |   |-- NekoComposer.tsx
|   |   `-- NekoTranscript.tsx
|   |-- drivers/types.ts
|   |-- drivers/acp/driver.ts
|   |-- drivers/factory.ts
|   |-- stores/neko-agent-store.ts
|   |-- stores/neko-session-store.ts
|   `-- persistence.ts
`-- src/__tests__/neko-chill/
```

**Structure Decision**: Keep every UI/data change inside the existing
`neko-chill` subtree. Only the existing Neko Tauri process command gains the
profile probe. Cloud chat/auth/embed files remain untouched.

## Verification and evidence

1. Driver fixture/unit tests for normalization and write routing.
2. Store/persistence migration tests for workspace and metadata.
3. UI tests for grouping/search/new-session gating/slash keyboard behavior.
4. `npx vitest run src/__tests__/neko-chill`
5. `npx tsc --noEmit`
6. `npm run build:embed`
7. `cargo test neko_agent` and `cargo check` in `src-tauri`
8. Native Windows run against Neko Core and Gemini; screenshot at wide and
   narrow widths; verify selected cwd and model/mode command behavior.

## Risk and rollback

- Persistence additions are optional on read, so reverting leaves transcript
  payloads intact and older clients ignore index fields.
- Profile parsing may drift; failure degrades to the agent default and never
  blocks session creation.
- Legacy Gemini model routing is isolated in ACP driver code and feature
  detected. Removing it later cannot affect Neko mode controls.
- Rollback is a single feature PR revert; no backend or user config migration
  is performed.

