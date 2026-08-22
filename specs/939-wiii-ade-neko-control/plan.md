# Implementation Plan: Wiii ADE and Neko Control Foundation

**Branch**: `codex/939-feat-wiii-ade-neko-control` | **Date**: 2026-08-23 | **Spec**: `specs/939-wiii-ade-neko-control/spec.md`
**Issue**: #939

## Summary

Introduce a small, executable foundation for Wiii ADE and Neko Agent Fabric:
pure ADE entity/graph contracts, a versioned Neko control envelope, one
production provider registry for current local adapters, a replaceable Tauri
control client, and backward-compatible capability snapshots on runtime attach.
Do not build a daemon, database, worktree manager or ADE shell in this slice.

## Technical Context

**Language/Version**: TypeScript 5, React 18; existing Rust/Tauri host unchanged
except through existing commands

**Primary Dependencies**: existing Zustand, Tauri IPC/events, ACP driver,
Codex App Server driver; no new dependency

**Storage**: existing versioned Neko session snapshots and append-only events

**Testing**: Vitest, TypeScript, existing desktop build checks

**Target Platform**: Windows/macOS/Linux Tauri desktop; browser fails closed

**Project Type**: existing desktop/web monorepo

**Performance Goals**: pure graph validation linear in entity/reference count;
registry lookup constant time

**Constraints**: Vietnamese-first UI unchanged, no destructive migration, no
provider credentials, additive persisted fields only

**Scale/Scope**: three implemented local providers and foundation contracts
for future ADE work

## Constitution Check

- **I Native Runtime Ownership**: Neko/Wiii types remain native; provider
  protocols stay in adapters. PASS.
- **II Living Memory With Tenant Safety**: no memory, org or tenant path
  changes. PASS.
- **III Streaming-First UX**: normalized event contract is specified; current
  streaming behavior remains unchanged. PASS.
- **IV Safe Tools And Host Control**: control methods fail closed and current
  Tauri permissions are reused. PASS.
- **V Multi-Agent Change Discipline**: issue #939, dedicated branch, narrow
  desktop/runtime scope, tests, rollback and no UI/backend mixing. PASS.

Post-design re-check: PASS. The in-process client is explicitly transitional,
so the feature does not misrepresent React-independent durability.

## Architecture

### ADE domain

`src/ade/domain.ts` contains JSON-compatible entity interfaces and one pure
graph validator. It has no store or UI dependency. This establishes identity
and relationship invariants without prematurely choosing SQLite tables or
frontend state management.

### Neko contracts and registry

`src/neko/contracts.ts` contains provider integration/capability snapshot
types and validation helpers. `provider-registry.ts` is the single TypeScript
catalog for implemented provider metadata and launch arguments. The existing
Workbench capability catalog derives local runtime entries from it.

### Control client

`control-protocol.ts` defines versioned envelopes and fail-closed parsing.
`control-client.ts` adapts current Tauri commands/events into a replaceable
client. Existing stores and drivers call this client instead of raw command
names. Rust remains the process owner for this slice.

### Historical capability truth

Drivers publish only capabilities they establish. `RuntimeRegistry` combines
observed driver facts with provider registry metadata into a versioned
snapshot. The runtime-attached event persists it. Its field is optional during
parsing so v1/v2 existing local snapshots remain readable.

## Project Structure

```text
specs/939-wiii-ade-neko-control/
|-- spec.md
|-- research.md
|-- data-model.md
|-- plan.md
|-- quickstart.md
|-- tasks.md
`-- contracts/neko-control-protocol.md

wiii-desktop/src/
|-- ade/domain.ts
|-- neko/
|   |-- contracts.ts
|   |-- control-protocol.ts
|   |-- control-client.ts
|   `-- provider-registry.ts
|-- neko-chill/
|   |-- drivers/types.ts
|   |-- drivers/factory.ts
|   |-- runtime-manager.ts
|   |-- session-events.ts
|   `-- stores/neko-agent-store.ts
|-- workbench/capabilities.ts
`-- __tests__/
    |-- ade/domain.test.ts
    `-- neko/
        |-- control-protocol.test.ts
        `-- provider-registry.test.ts
```

**Structure Decision**: Add one dependency-light `ade` domain and one `neko`
control layer above the mature `neko-chill` adapters. Do not move existing
driver/session files while changing their contract.

## Verification

1. Focused ontology, control, provider registry, runtime and persistence tests.
2. `npx tsc --noEmit`.
3. `npm run build:web` and `npm run build:embed` when imports affect shared
   browser builds.
4. `git diff --check` and `specify check`.
5. No screenshot is required because this slice intentionally changes no
   visible UI.

## Risk and rollback

- **Persistence risk**: the capability field is additive and optional when
  reading. Roll back code while retaining unknown JSON fields/events.
- **Provider risk**: launch arguments move, not change. Focused tests freeze
  all three current invocation contracts.
- **Authority risk**: the client remains backed by existing Tauri commands;
  no new native permission is introduced.
- **Protocol risk**: v1 is internal and versioned; unsupported operations fail
  before side effects.
- **Rollback**: revert the PR. No database, provider session or user setting
  requires migration or deletion.
