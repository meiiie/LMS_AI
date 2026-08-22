# Tasks: Release and Desktop Trust Hardening

**Input**: [spec.md](spec.md), [plan.md](plan.md), [research.md](research.md)

**Issue**: [#929](https://github.com/meiiie/wiii/issues/929)

## Phase 1 - Contract

- [x] T001 Confirm the four P0 findings against `origin/main` and public GitHub state.
- [x] T002 Record user-visible behavior, non-goals, security boundaries, and rollback.

## Phase 2 - License truth (PR 1)

- [x] T003 [US2] Change Tauri bundle metadata and README badge text to AGPL-3.0-only.
- [x] T004 [US2] Add path-specific license checks to `tools/release/wiii_release.py`.
- [x] T005 [US2] Add release-tool tests for valid and drifted core/SDK metadata.
- [x] T006 [US2] Run release tests, metadata check, diff check, and open a focused PR.

## Phase 3 - Desktop trust boundary (PR 2)

- [x] T007 [US1] Add a non-null application CSP based on verified runtime needs.
- [x] T008 [US1] Declare application commands in `wiii-desktop/src-tauri/build.rs`.
- [x] T009 [US1] Replace the shared default capability with splash and main concern files.
- [x] T010 [US1] Add defense-in-depth caller validation to `close_splash`.
- [x] T011 [US1] Add static boundary tests for CSP, window targets, origin scope, and commands.
- [x] T012 [US1] Run Rust, Vitest, TypeScript, web/embed, and native build verification.

## Phase 4 - Release truth (PR 3)

- [x] T013 [US3] Make candidate notes and stable dated notes distinct in the release checker.
- [x] T014 [US3] Add tests proving stable tag validation fails on candidate-only metadata.
- [x] T015 [US3] Correct changelog links, README installation copy, SECURITY support state,
  and release documentation to match the absence of a stable release.
- [x] T016 [US3] Run release tests/checks and dispatch a complete candidate build after merge.

## Phase 5 - Closure

- [x] T017 Review the public tag/release/license state after all PRs merge.
- [x] T018 Create ordered P1 follow-up issues for modularity, feature flags,
  dependency locking, and development-environment hardening.
- [x] T019 Update #929 with final evidence and close only when every acceptance criterion passes.

## Dependencies

- T003-T006 may merge independently.
- T007-T012 may merge independently after this contract PR.
- T013-T016 may merge independently after this contract PR.
- T017-T019 require all three implementation PRs.

No task requires or authorizes publishing an unsigned stable release.
