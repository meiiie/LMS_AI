# Tasks: Neko Chill Workspace Shell

**Input**: `specs/904-neko-workspace-shell/`
**Issue**: #904

## Phase 1: Contract and persistence foundation

- [x] T001 Add failing driver tests for initial stable/legacy controls,
      reported commands, session-info, and source-specific control writes in
      `wiii-desktop/src/__tests__/neko-chill/acp-driver.test.ts`.
- [x] T002 Extend `drivers/types.ts` and `drivers/acp/driver.ts` with the
      normalized capability contract; keep all ACP shapes private.
- [x] T003 Add failing persistence/store tests for v1 migration, workspace,
      profile, controls, commands, and updatedAt.
- [x] T004 Implement the additive session/index model and exact-workspace
      driver factory contract.

## Phase 2: User Story 1 - Project workspace and navigation (P1)

- [x] T101 [US1] Add a tested native folder selection helper and require a
      `WorkspaceRef` before `createSession` can spawn an agent.
- [x] T102 [US1] Implement the read-only Neko profile probe/parser in
      `src-tauri/src/commands/neko_agent.rs` with Rust unit tests.
- [x] T103 [US1] Extend the agent store and new-session view with
      workspace-scoped Neko profile discovery and launch selection.
- [x] T104 [US1] Replace flat navigation with searchable workspace groups,
      dense session rows, status indicators, and legacy attachment.
- [x] T105 [US1] Test two-project grouping, search fields, full-history
      reachability, exact cwd, cancelled dialog, and legacy behavior.

## Phase 3: User Story 2 - Capability controls and slash palette (P2)

- [x] T201 [US2] Wire store control/command events and pending/failure state;
      prohibit control changes during turns or permissions.
- [x] T202 [US2] Add capability-backed mode/model/config popovers to the
      composer; show Neko launch model as locked and explained.
- [x] T203 [US2] Add keyboard slash completion merging documented client
      commands with agent-reported commands and clear source labels.
- [x] T204 [US2] Test Neko modes, Gemini model routing, stable config routing,
      empty agent commands, client command execution, and keyboard selection.

## Phase 4: User Story 3 - Active session context (P3)

- [x] T301 [US3] Add the compact responsive session inspector and enrich the
      header/composer workspace context.
- [x] T302 [US3] Apply session-info title/timestamp updates and safe outer
      emphasis cleanup for reasoning labels.
- [x] T303 [US3] Add accessibility/responsive tests for inspector, controls,
      labels, focus, and narrow-window behavior.

## Phase 5: Verification and delivery

- [x] T401 Run targeted Neko tests, full desktop Vitest, TypeScript, embed
      build, Rust tests/check, `git diff --check`, and self-review the diff.
- [x] T402 Run Neko Core + Gemini native acceptance, record selected cwd and
      capability requests, and capture wide/narrow screenshots.
- [ ] T403 Update feature/task status and `docs/STATE.md`; open a linked PR
      with exact gates, risk, rollback, research/license note, and evidence.
- [ ] T404 Resolve review/CI findings, merge only when required gates are
      green, rebuild/install the native app, and verify the installed result.

## Dependencies and delivery order

- T001-T004 establish the contract and block all UI work.
- US1 is independently useful and makes spawning safe.
- US2 depends on the normalized driver contract, not on inspector UI.
- US3 consumes the metadata produced by US1/US2.
- No subagents or parallel write scopes are used in this workspace.
