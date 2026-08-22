# Implementation Plan: Neko Durable Runtime Authority

**Branch**: `codex/941-feat-neko-durable-runtime` | **Date**: 2026-08-23 | **Spec**: `specs/941-neko-durable-runtime/spec.md`
**Issue**: #941

## Summary

Replace the raw Tauri process utility exposed to `main` with an in-process
Rust `NekoRuntime`. Rust owns approved provider resolution, process/session
lifecycle, idempotency records and a replayable SQLite WAL lifecycle journal.
Current ACP and Codex protocol parsing remains TypeScript-side. No UI redesign,
worktree manager or standalone daemon is included.

## Technical Context

**Language/Version**: Rust 2021/Tauri 2; TypeScript 5/React 18

**Dependencies**: `rusqlite` with bundled SQLite, `uuid`, `chrono`; existing
Tauri events and provider adapters

**Storage**: one local SQLite database in the Tauri app-local-data directory;
WAL, foreign keys and bounded lifecycle records

**Testing**: Rust unit/integration tests, Vitest control-client/driver tests,
TypeScript, embed build and Tauri security-contract tests

**Target**: Windows, macOS and Linux desktop; browser continues to fail closed

## Constitution Check

- **I Native Runtime Ownership**: Rust/Neko becomes local lifecycle authority;
  provider protocols remain adapters. PASS.
- **II Living Memory With Tenant Safety**: no memory or tenant data changes;
  no provider credentials enter SQLite. PASS.
- **III Streaming-First UX**: existing live provider stream remains; durable
  lifecycle replay is additive. PASS.
- **IV Safe Tools And Host Control**: raw executable/PID capability is removed
  from the privileged WebView. PASS.
- **V Multi-Agent Change Discipline**: issue #941, one runtime/security slice,
  explicit non-goals, tests and rollback. PASS.

## Implementation shape

```text
src-tauri/src/neko/
|-- mod.rs              NekoRuntime facade and process ownership
|-- provider.rs         approved native provider catalog/probes
|-- journal.rs          SQLite schema, idempotency and replay
`-- lifecycle.rs        pure run/operation transitions and recovery

src-tauri/src/commands/neko_agent.rs
`-- provider/session/events commands only

src/neko/control-client.ts
`-- Tauri adapter using provider/session IDs, never program/args/PID
```

The runtime stores `Arc`-backed inner state so stdout/reaper threads can update
the same process table and journal. Tauri setup opens the database and manages
the runtime. App exit asks the runtime to cancel owned processes.

## Migration and compatibility

The current Neko UI does not yet create ADE Task/Run/Environment records. Its
driver factory supplies namespaced `legacy-local/*` execution references to
the native service. This is a compatibility binding only and does not create
or claim Wiii ADE entities.

No existing Workbench transcript or provider session is rewritten. The new
database starts as an additive local lifecycle journal. Unknown or corrupt
journal state fails local Neko startup instead of silently deleting data.

## Risk and rollback

- **Security**: highest risk is accidentally retaining a raw native command or
  leaking a resolved binary path. Contract tests inspect capabilities and
  serialized detection responses.
- **Durability**: SQLite is additive; no old data migration. Recovery never
  retries an uncertain operation.
- **Provider regression**: freeze the three current launch contracts in Rust
  tests and run affected TypeScript suites.
- **Rollback**: revert the complete PR/release. Do not restore raw spawn as a
  partial hotfix. The additive SQLite file can remain unused by older builds.

## Verification

1. Rust tests for lifecycle, provider registry, journal ordering/replay,
   idempotency, recovery and schema secret exclusion.
2. Tauri security contract proving raw process permissions are absent.
3. Focused Vitest for control client, driver factory, session/runtime paths.
4. Full Rust and desktop tests, TypeScript, web/embed builds and hygiene.
5. No screenshot: this phase intentionally changes authority, not visible UI.

