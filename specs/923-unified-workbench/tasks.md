# Tasks: Unified Wiii Workbench

**Input**: `specs/923-unified-workbench/`
**Issue**: #923

## Phase 1: Specification and baseline

- [x] T001 Create issue #923, branch, research, spec, plan, data model,
      capability contract, and tasks.
- [x] T002 Verify current local mode-gate/login/driver tests and record the
      existing Workbench, RAG, host, and auth boundaries.

## Phase 2: Foundational capability contracts

- [x] T101 [US1] Add failing pure tests for desktop/web host derivation and
      fail-closed defaults.
- [x] T102 [US1] Implement `src/workbench/host.ts` and use it in new Workbench
      surfaces.
- [x] T103 [US1] Add failing tests for runtime, knowledge, account, and host
      capability filtering.
- [x] T104 [US1] Implement the minimal pure capability catalog without a new
      state framework or dependency.

## Phase 3: One local-first Workbench

- [x] T201 [US1] Add failing bootstrap tests proving fresh desktop startup
      mounts the Workbench without managed-service initialization.
- [x] T202 [US1] Implement `WorkbenchApp` and replace the pre-auth binary gate.
- [x] T203 [US1] Replace Neko/Wiii mode-switch language with Connections and
      keep the managed surface lazy-loadable.
- [x] T204 [US1] Migrate legacy mode intent additively without deleting local
      sessions, cloud auth, or settings.

## Phase 4: Composable Wiii Knowledge

- [x] T301 [US2] Add knowledge connection and model-visible context event
      types with validation tests.
- [x] T302 [US2] Render Wiii Knowledge readiness/degraded status independently
      from runtime health.
- [x] T303 [US2] Connect the existing authorized Wiii Service entry and keep
      local agent actions available while disconnected.
- [x] T304 [US2] Prove failed context persistence blocks dispatch and recorded
      context replays without re-running retrieval.

## Phase 5: Codex App Server runtime

- [x] T401 [US3] Add Codex to native detection and map it to `app-server`
      without bundling or reading its credentials.
- [x] T402 [US3] Add fixture-first App Server request/response correlation,
      initialization, and unknown-message tests.
- [x] T403 [US3] Implement account/model discovery plus provider-owned browser
      or device-code challenge events.
- [x] T404 [US3] Implement thread start/resume, turn stream normalization,
      approvals, interrupt, and disposal.
- [x] T405 [US3] Integrate Codex into new-session/provider UI with honest
      account/model state and no secret persistence.

## Phase 6: Hosted web boundary

- [x] T501 [US4] Add browser-host tests proving native runtime and filesystem
      actions are absent.
- [x] T502 [US4] Add a connection-first hosted empty state and retain the
      managed Wiii surface for remote sessions.
- [x] T503 [US4] Verify the same Workbench contracts compile in desktop, web,
      and embed targets.

## Phase 7: Provider policy and delivery

- [x] T601 [US5] Add clear auth/billing ownership copy for Neko, Codex, Wiii
      Service, and Claude API/cloud provider paths.
- [x] T602 [US5] Document and test the Claude subscription-login policy gate.
- [x] T603 Run targeted/full Vitest, TypeScript, web/embed builds, Cargo tests,
      diff hygiene, and secret scan.
- [x] T604 Run native/browser visual acceptance, update public/architecture
      docs, and capture temporary evidence.
- [ ] T605 Open PR with exact evidence, risk, rollback, resolve CI/review,
      merge, rebuild/install desktop, and smoke the installed result.

## Dependencies and execution order

- Foundation blocks Workbench, knowledge, Codex, and web UI.
- Workbench boot completes before managed knowledge or new provider wiring.
- Codex and knowledge use disjoint driver/service boundaries after foundation.
- Web verification runs after the shell no longer assumes Tauri.
- Work stays sequential in this worktree; no subagents edit shared files.
