# Tasks: Desktop Agent Workbench

**Input**: `specs/906-desktop-agent-workbench/`
**Issue**: #906

## Phase 1: Evidence and specification

- [x] T001 Reproduce the custom-titlebar failure and identify the missing
      Tauri ACL operations.
- [x] T002 Study official DeepSeek Harness, Reasonix Desktop, Tauri/Windows
      guidance, and current human-agent UX research; record bounded decisions.
- [x] T003 Create issue #906, feature branch, spec, research, plan, and tasks.

## Phase 2: User Story 1 - Reliable native chrome (P1)

- [x] T101 [US1] Add failing titlebar tests for minimize, maximize/restore,
      close, resize synchronization, accessibility, and native failures.
- [x] T102 [US1] Grant the least-privilege Tauri window capabilities used by
      the shared custom titlebar.
- [x] T103 [US1] Refactor `TitleBar.tsx` to typed awaited actions, native
      maximize state, restore glyph, drag behavior, and composition slots.
- [x] T104 [US1] Expose Wiii's existing command palette from the titlebar and
      preserve login/browser behavior.

## Phase 3: User Story 2 - Neko command center (P2)

- [x] T201 [US2] Add failing UI/pure tests for all-session search, grouped
      actions/commands/sessions, keyboard navigation, and command insertion.
- [x] T202 [US2] Implement pure command item creation and
      `NekoCommandCenter.tsx` without new dependencies or persistence.
- [x] T203 [US2] Integrate Ctrl+K/titlebar activation with session navigation,
      client actions, and composer draft insertion.

## Phase 4: User Story 3 - Progressive workbench (P3)

- [x] T301 [US3] Move Neko mode/command/sidebar controls into the shared
      titlebar and make the project tree independently collapsible.
- [x] T302 [US3] Default the inspector closed, preserve its responsive overlay,
      and improve explicit runtime/model/status hierarchy.
- [x] T303 [US3] Add concise empty-session and progressive new-session guidance
      while preserving provider-backed controls.
- [x] T304 [US3] Extend UI tests for panel disclosure, active context, empty
      state, narrow layout semantics, and accessible targets.

## Phase 5: Verification and delivery

- [x] T401 Run targeted/full Vitest, TypeScript, embed/desktop builds, Cargo
      checks, `git diff --check`, and self-review.
- [x] T402 Run packaged Windows acceptance for caption buttons, Ctrl+K,
      session navigation, command insertion, and panel behavior; capture
      wide/narrow screenshots.
- [~] T403 Update Spec Kit status and umbrella `docs/STATE.md`; open a linked
      PR with exact evidence, risk, rollback, and research/license notes.
- [ ] T404 Resolve review/CI findings, merge when green, rebuild/install Wiii,
      and verify the installed result.

## Dependencies and delivery order

- Native chrome is the blocker and is completed before visual polish.
- The command center consumes existing session/command data and precedes the
  workbench layout integration.
- Progressive layout changes consume the shared titlebar slots and command
  center callbacks.
- Work remains sequential in this workspace; no subagents edit shared files.
