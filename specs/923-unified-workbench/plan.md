# Implementation Plan: Unified Wiii Workbench

**Branch**: `codex/923-feat-unified-workbench` | **Date**: 2026-08-16 | **Spec**: `specs/923-unified-workbench/spec.md`
**Issue**: #923

## Summary

Replace the binary Wiii Cloud/Neko Chill entry gate with a local-first
Workbench composition. Introduce small host and capability contracts, retain
the existing ACP ledger/runtime, expose Wiii Service as an optional managed
connection, add an official Codex App Server driver, and ensure the hosted web
build advertises only browser-safe capabilities. Preserve the existing cloud
surface as a compatibility route until adapter parity is measured.

## Technical Context

**Language/Version**: TypeScript 5, React 18, Rust stable, Python 3 backend unchanged
**Primary Dependencies**: Tauri 2, Zustand, existing ACP driver, Codex App Server JSON-RPC, Wiii SSE V3
**Storage**: Existing Tauri store/localStorage session snapshots; existing Wiii Service databases
**Testing**: Vitest, Testing Library, Playwright, Cargo tests/check, Vite web/embed builds
**Target Platform**: Windows/macOS/Linux desktop and modern hosted browsers
**Project Type**: Existing desktop/web frontend plus existing managed backend
**Performance Goals**: no network work on local-first boot; capability evaluation synchronous; no transcript regression
**Constraints**: Vietnamese-first, no new frontend dependency, no destructive migration, fail-closed native/web boundary
**Scale/Scope**: one shell, current local ACP sessions, optional Wiii Service, one new Codex runtime adapter

## Constitution Check

- **I Native Runtime Ownership**: provider protocols stay in thin drivers and
  normalize into Wiii driver/events. PASS.
- **II Living Memory With Tenant Safety**: managed RAG/memory stays server
  authorized; no client-supplied org trust is introduced. PASS.
- **III Streaming-First UX**: runtime and knowledge states are explicit and
  provider events stream through the current transcript. PASS.
- **IV Safe Tools And Host Control**: web host denies native capabilities;
  permissions fail closed; provider tokens remain provider-owned. PASS.
- **V Change Discipline**: issue #923, feature branch, Spec Kit artifacts,
  additive contracts, staged tests, compatibility surface, and rollback. PASS.

Post-design re-check: PASS. No constitution exception or schema migration.

## Architecture

### Composition boundary

`WorkbenchApp` owns only product composition and host-aware navigation.
`NekoChillApp` is renamed by presentation to the default local Workbench while
its durable stores remain unchanged. Wiii managed UI boot is lazy and opened
only from an explicit connection/surface action.

### Host boundary

One `workbench/host.ts` module replaces scattered direct Tauri detection for
new Workbench surfaces. `desktop` can launch local runtimes and choose local
workspaces. `web` can use only authenticated remote runtime/knowledge paths.

### Capability catalog

A pure catalog filters runtime/knowledge definitions by host requirements and
returns an honest unavailable reason. UI renders catalog facts; it does not
infer support from labels or environment variables.

### Knowledge boundary

Wiii Service remains unchanged in this first implementation slice. The
frontend connection descriptor and model-context event establish the contract;
actual automatic retrieval injection follows existing authorized APIs and must
commit evidence before dispatch. Service failure cannot mutate runtime health.

### Codex boundary

Rust adds Codex to read-only binary detection and reuses the existing dumb
stdio process pipe. TypeScript owns App Server request correlation and event
normalization. The adapter initializes, reads account/models, starts/resumes a
thread, streams events, resolves approvals, interrupts turns, and disposes.
Provider credentials and refresh remain inside Codex.

### Compatibility and migration

Legacy `mode=wiii` is treated as an intent to surface the managed connection,
not as authority to bypass the unified shell. Existing auth/session keys are
not rewritten or deleted. The legacy cloud surface remains lazy-loadable while
capability parity is incomplete.

## Project Structure

```text
specs/923-unified-workbench/
|-- spec.md
|-- research.md
|-- data-model.md
|-- plan.md
|-- tasks.md
`-- contracts/workbench-capabilities.md

wiii-desktop/
|-- src/workbench/
|   |-- host.ts
|   |-- capabilities.ts
|   |-- WorkbenchApp.tsx
|   `-- components/ConnectionsPanel.tsx
|-- src/neko-chill/
|   |-- drivers/codex/
|   |-- drivers/types.ts
|   |-- drivers/factory.ts
|   `-- session-events.ts
|-- src/App.tsx
|-- src-tauri/src/commands/neko_agent.rs
`-- src/__tests__/workbench/
```

**Structure Decision**: Add one product-level `workbench` layer above the
existing Neko runtime subtree. Do not move the mature session store during the
behavioral migration. Protocol code stays inside driver-specific directories.

## Verification

1. Host and capability pure contract tests.
2. App bootstrap tests proving no cloud init on local-first boot.
3. Existing Neko mode/session/ledger/runtime tests.
4. Codex fixture tests for protocol and fail-closed approvals.
5. Hosted-web tests without Tauri globals.
6. `npx vitest run`, `npx tsc --noEmit`, `npm run build:web`,
   `npm run build:embed`, `cargo test`, and `cargo check`.
7. Native Windows and browser visual acceptance with temporary evidence.

## Risk and rollback

- **Auth risk**: never log/persist provider secrets; external-token Codex mode
  is deliberately unsupported. Roll back the Codex catalog entry/driver.
- **Session risk**: keep existing snapshots and provider ids additive. Roll
  back the Workbench entry while retaining all session data.
- **RAG risk**: no server query or tenant contract changes in the foundation;
  knowledge connection remains optional. Roll back UI/catalog only.
- **Web risk**: native capability checks default false. A regression removes
  functionality rather than granting authority.
- **UX risk**: retain the legacy managed surface behind Connections until
  parity is proven.
