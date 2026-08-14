# Tasks: Neko Chill Mode — No-Login Local-Agent Surface (ACP)

**Spec**: `specs/731-neko-chill-mode/spec.md` · **Plan**: `plan.md` · **Issue**: #886

Format: `[ID] [P?] [Story] Description` — `[P]` = parallelizable with its
phase siblings. Every task lands with the desktop gate green
(`npx vitest run && npx tsc --noEmit`); slices that could touch the cloud
surface also run `npm run build:embed`.

## Phase 1: Setup (Shared Infrastructure)

- [x] T101 Scaffold `wiii-desktop/src/neko-chill/` subtree + `drivers/types.ts`
      with the `DriverEvent` union and `Driver` interface exactly as in
      plan § Architecture 2 (FR-010). Pure types + vitest for exhaustiveness.
- [x] T102 [P] `mode-store.ts`: persisted mode selection (`wiii` | `neko-chill`)
      via tauri plugin-store with localStorage fallback (FR-001); unit tests
      for persistence + default.
- [x] T103 [P] `src-tauri/src/commands/neko_agent.rs`: process table +
      `detect_agents`, `spawn_agent`, `write_agent_stdin`, `kill_agent`,
      `kill_all_agents`; stdout line-reader emitting
      `neko-agent://line/{procId}` Tauri events; kill-all on app exit
      (FR-009). Register in `lib.rs`; add required shell/process capabilities
      to `capabilities/default.json` (narrowest scope that works).
      `cargo check` clean.

## Phase 2: Foundational (Blocking Prerequisites)

- [x] T201 Verify current ACP wire contract against the public schema +
      Gemini CLI docs (method names, `session/update` payload shapes,
      permission request/response, cancel, stop reasons). Record findings +
      protocol version pin in `drivers/acp/PROTOCOL-NOTES.md`. **Do not code
      the client from memory.**
- [x] T202 `drivers/acp/client.ts`: JSON-RPC 2.0 correlation layer over the
      Tauri transport (requests, responses, notifications, agent→client
      requests); timeout + malformed-frame handling (edge case: protocol
      error terminates the process). Unit tests with fake transport.
- [x] T203 `drivers/acp/driver.ts`: `initialize` → `session/new` →
      `session/prompt` lifecycle; map `session/update` streams to
      `DriverEvent`s; `session/cancel`; stdin-close termination. Golden-fixture
      tests from at least one REAL recorded Gemini CLI ACP transcript
      (record via a throwaway script; commit the NDJSON fixture).
- [x] T204 `App.tsx` seam: mode check before store/auth init (early-return
      altitude, per audit § C); lazy-load `NekoChillApp`; entering the mode
      must fire zero cloud init effects (FR-002) — assert via a vitest that
      mocks the init modules and via manual devtools network check.

## Phase 3: User Story 1 — Enter mode + streaming turn (P1) 🎯 MVP

- [x] T301 `neko-agent-store.ts` + `AgentPicker`: consume `detect_agents`
      (Gemini CLI first, `neko acp` binary name reserved), not-found and
      empty states with install guidance (edge case; Vietnamese-first copy).
- [x] T302 `neko-session-store.ts`: session CRUD, DriverEvent→ContentBlock
      streaming append (immer, mirrors cloud store's block discipline without
      importing it), turn lifecycle state, cancel wiring (FR-005, FR-007).
- [x] T303 `NekoChillApp` + `NekoTranscript` + `NekoComposer`: sidebar session
      list, transcript over shared `components/common` markdown stack with
      `@tanstack/react-virtual` above 50 blocks (edge case: long transcripts),
      composer with Enter-to-send, cancel button while streaming.
- [~] T304 (code wired end-to-end; manual GUI pass on Windows pending — requested on #886) Wire T301–T303 end-to-end against real Gemini CLI on Windows;
      acceptance scenarios US1-1…US1-5; fix until green.

**Checkpoint**: MVP demoable — fresh install → prompt → streamed answer → cancel.

## Phase 4: User Story 2 — Permission gating (P2)

- [x] T401 Driver: map `session/request_permission` to a `permission-request`
      DriverEvent carrying action kind, target, and offered options; store
      pauses the turn on it (FR-006).
- [x] T402 `PermissionCard`: explicit approve/deny surface in the transcript
      (action, target, agent identity); decision recorded as a block;
      keyboard accessible; Vietnamese-first copy.
- [x] T403 Fail-closed paths: deny resolution reaches the agent; app-quit
      with a pending request kills the process (never approves); vitest for
      both + manual US2 scenarios against Gemini CLI.

## Phase 5: User Story 3 — Local persistence + restore (P3)

- [x] T501 `persistence.ts`: session index + per-session transcript via
      tauri plugin-store; debounced incremental appends (plan § Architecture 5);
      versioned schema with a `v` field for future migration.
- [x] T502 Restore flow: hydrate session list + transcripts on mode entry;
      new prompt on a restored session spawns a fresh agent process (spec
      US3-2); vitest round-trip fidelity test (FR-008).
- [x] T503 (locality asserted via storage mocks; live network check rides the T304 manual pass) Verify locality: no network calls during a full record/restore
      cycle; nothing written outside app storage (US3-3, SC-004).

## Phase 6: Polish & Cross-Cutting

- [x] T601 Idle reaping (30 min, skip sessions with active turns) + orphan
      audit: 10× open/work/quit cycles on Windows, `tasklist` clean (SC-006).
- [x] T602 Error surfaces: agent crash mid-turn, malformed frames, version
      mismatch from `initialize` pin — each renders an honest, actionable
      state (edge cases; plan § Complexity).
- [~] T603 (gates green + README section shipped; screenshots pending the manual GUI pass) Full gate + evidence: `npx vitest run`, `npx tsc --noEmit`,
      `npm run build:embed`, `cargo check`; screenshots for the PR body
      (AGENTS.md frontend-evidence rule); update `wiii-desktop/README.md`
      with the mode section.
- [~] T604 (driver golden-tested vs real neko-core v0.24.0 fixture; Gemini CLI wire-level handshake fixture recorded; formal on-screen cross-run pending) Cross-acceptance with the partner team when `neko acp` ships:
      detection entry, one full US1+US2 run against neko-core; file issues
      for any protocol drift (do not patch around it silently).

## Phase 7: Runtime Integrity Follow-up (#908)

- [x] T701 Add a versioned append-only session event log and a strict
      persistence-before-dispatch barrier for Wiii-controlled model facts;
      migrate v1 transcripts without loss (FR-011).
- [x] T702 Replace the unowned live-driver map with `RuntimeScope` and
      `RuntimeRegistry`; clean up partial initialization and mode-exit resources
      idempotently (FR-012).
- [x] T703 Assign provider instance identity, declare driver capabilities, gate
      operations by capability, and ignore stale-provider events (FR-013).
- [x] T704 Make provider preparation and control changes transactional; cover
      replacement failure, commit, rollback, and rollback-failed paths (FR-014).

## Dependencies

- Phase 2 blocks 3; T302 blocks T303; Phase 4–5 depend on Phase 3; Phase 6 last.
- T103 (Rust transport) can proceed in parallel with T201–T202 (TS protocol).
- External: `neko acp` (partner team) is NOT a dependency for any phase except
  T604 — Gemini CLI is the acceptance reference throughout (spec Assumptions).
