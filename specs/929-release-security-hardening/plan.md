# Implementation Plan: Release and Desktop Trust Hardening

**Branch**: `929-release-security-hardening` | **Date**: 2026-08-23 | **Spec**: [spec.md](spec.md)  
**Issue**: [#929](https://github.com/meiiie/wiii/issues/929)

## Summary

Harden Wiii in three independently reversible implementation slices: license
truth, Tauri trust boundaries, and release-state truth. Reuse the existing
release checker and Tauri ACL system; do not introduce a second policy engine.

## Technical Context

**Language/Version**: Python 3.11, TypeScript 5.x, Rust 2021  
**Primary Dependencies**: Tauri v2, React 18, Vite 8, existing Python release tooling  
**Storage**: N/A; configuration and repository metadata only  
**Testing**: Python unittest, Vitest, TypeScript, Cargo/Tauri build validation  
**Target Platform**: Windows x64, Linux x64, macOS arm64/x64, hosted web/embed  
**Project Type**: Monorepo with desktop app, web surfaces, and FastAPI service  
**Performance Goals**: No startup or steady-state performance regression  
**Constraints**: Keep configurable service endpoints, local ACP, SSE/WebSocket,
sandboxed artifacts, and current installer identity working  
**Scale/Scope**: Four P0 findings; no product feature expansion

## Constitution Check

- **Native Runtime Ownership**: Pass. No provider/runtime abstraction changes.
- **Living Memory With Tenant Safety**: Pass. No memory or tenant data changes.
- **Streaming-First UX**: Pass with verification. CSP must preserve SSE and
  WebSocket behavior for allowed Wiii Service endpoints.
- **Safe Tools, Visuals, And Host Control**: Strengthened. Splash loses host
  authority; application commands become explicit.
- **Multi-Agent Change Discipline**: Pass. One issue and spec govern three
  narrow PRs with disjoint objectives and rollback notes.

## Design Decisions

### D1. Extend the existing release checker

`tools/release/wiii_release.py` already owns version and brand consistency.
License and changelog-state checks belong there instead of a new script.

### D2. Separate application CSP from artifact CSP

The application CSP constrains Wiii's WebView. Existing visual artifacts remain
inside sandboxed blob iframes with their own generated CSP. The app policy will
allow only the browser primitives actually required to host those frames.

### D3. Use explicit Tauri application-command permissions

Declare all commands in `tauri_build::AppManifest`. Grant `close_splash` only to
the splash capability and grant file/process/health commands only to main-window
capabilities. Add a command-side label check as defense in depth.

### D4. Treat VERSION as a target, not publication evidence

Normal validation checks a non-empty candidate notes source. Tag validation
requires a dated matching release section. Documentation reports no stable
release until the protected workflow creates one.

## Project Structure

```text
specs/929-release-security-hardening/
|-- spec.md
|-- plan.md
|-- research.md
`-- tasks.md

tools/release/
|-- wiii_release.py
`-- test_wiii_release.py

wiii-desktop/src-tauri/
|-- build.rs
|-- tauri.conf.json
|-- capabilities/
`-- src/commands/splash.rs

README.md
SECURITY.md
CHANGELOG.md
docs/releases/
```

**Structure Decision**: Keep policy in existing release and Tauri configuration
surfaces. Add only capability files and tests required to make boundaries
explicit.

## Rollout and Rollback

1. Merge license metadata/gate; rollback by reverting that PR.
2. Merge CSP and ACL segmentation; rollback the whole security PR if a supported
   desktop workflow is blocked, then restore only the narrow missing directive
   or permission in a follow-up.
3. Merge release-state truth; rollback documentation and checker behavior
   together. Never create or move a tag to simulate rollback.

No database, session schema, provider state, or installed application identifier
changes in this plan.

## Verification

```powershell
python -m unittest discover -s tools/release -p 'test_*.py' -v
python tools/release/wiii_release.py check
cd wiii-desktop
npm test -- --run
npx tsc --noEmit
npm run build
npm run build:embed
cargo check --manifest-path src-tauri/Cargo.toml
```

For the Tauri PR, also inspect the generated capability manifest and run the
native build smoke where the host has required platform dependencies.
