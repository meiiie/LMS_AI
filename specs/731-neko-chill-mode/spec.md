# Feature Specification: Neko Chill Mode — No-Login Local-Agent Surface (ACP)

**Feature Branch**: `731-neko-chill-mode`
**Created**: 2026-08-12
**Status**: Draft
**Issue**: #886
**Input**: User description: "Neko Chill mode - no-login local-agent surface (ACP) in wiii-desktop"

Neko Chill turns the Wiii desktop app into a **superapp**: alongside the existing
authenticated Wiii cloud experience, a second shell-level mode works entirely
offline-from-Wiii — no account, no backend — and drives **local coding agents**
that speak the Agent Client Protocol (ACP, JSON-RPC over stdio), launched as
sidecar processes. First-class agent: `neko-core` (its `neko acp` server is owned
by a partner team). Reference agent for acceptance: **Gemini CLI**, which ships
ACP support today, so this feature does not block on the partner team.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Enter the mode and run a streaming turn (Priority: P1)

A user installs Wiii desktop, opens it for the first time, and — without
signing in to anything — chooses "Neko Chill". The mode lists local coding
agents detected on the machine. The user picks one, types a prompt, and watches
the agent work live: reasoning, tool activity (file reads, commands, searches),
and the final markdown answer stream into the transcript as they happen. The
user can stop a running turn at any moment.

**Why this priority**: This is the mode's reason to exist — a working
local-agent cockpit with zero account friction. Everything else builds on it.

**Independent Test**: On a machine with Gemini CLI installed and no Wiii
account configured, enter the mode, run one prompt end-to-end, cancel a second
prompt mid-turn.

**Acceptance Scenarios**:

1. **Given** a fresh install with no stored credentials, **When** the app
   starts, **Then** the user can enter Neko Chill mode without any login and
   without any Wiii backend/network initialization firing.
2. **Given** the mode is open and Gemini CLI is installed, **When** the user
   opens the agent picker, **Then** the detected agent is listed with its
   version; an undetected agent shows an actionable "not found" state, never a
   silent empty list.
3. **Given** an active session, **When** the user sends a prompt, **Then**
   reasoning, tool activity, and answer content render incrementally while the
   turn runs (no buffer-then-dump), and the transcript shows a clear
   turn-finished state.
4. **Given** a turn is running, **When** the user cancels, **Then** streaming
   stops promptly, the partial transcript is preserved, and the session accepts
   the next prompt.
5. **Given** the user switches back to the Wiii cloud mode, **When** they use
   chat as before, **Then** nothing about the authenticated experience has
   changed.

---

### User Story 2 - Explicit permission gating (Priority: P2)

While an agent works, it may ask to do something sensitive — write a file, run
a command. The user sees each request as an explicit approval surface with
enough context to decide (what action, on what target, requested by which
agent), and the agent proceeds only on approval.

**Why this priority**: Constitution IV (safe tools, fail-closed) and the neko
identity (approval-gated by default). A local-agent surface without gating is a
security regression, not a feature.

**Independent Test**: Drive a prompt that makes the reference agent request a
file write; approve once, deny once, verify both outcomes.

**Acceptance Scenarios**:

1. **Given** an agent emits a permission request, **When** it renders, **Then**
   the turn is visibly paused on the request, and the surface shows the action,
   its target, and the offered options.
2. **Given** a rendered request, **When** the user denies it, **Then** the
   denial reaches the agent, nothing is auto-approved, and the transcript
   records the decision.
3. **Given** a rendered request, **When** the user quits the app instead of
   answering, **Then** the agent process is terminated — an unanswered request
   never falls through to approval.

---

### User Story 3 - Sessions survive restarts, locally (Priority: P3)

A user closes the app mid-project. Reopening it, Neko Chill lists their
previous sessions with titles and timestamps; opening one shows the full
transcript. All of this lives on the machine — no cloud account involved.

**Why this priority**: Continuity makes the mode a daily tool rather than a
demo; local-first storage is the mode's identity, but P1+P2 are useful without
it.

**Independent Test**: Run a session, quit, relaunch, reopen the session,
verify transcript fidelity; verify nothing was written outside local app
storage.

**Acceptance Scenarios**:

1. **Given** a completed session, **When** the app restarts, **Then** the
   session appears in the mode's session list and its transcript renders
   fully from local storage.
2. **Given** a restored session, **When** the user sends a new prompt, **Then**
   a fresh agent process serves it (v0 does not require native agent-side
   session resume) and new turns append to the same transcript.
3. **Given** any Neko Chill activity, **When** storage is inspected, **Then**
   session data exists only in local app storage and is absent from Wiii cloud
   state.

---

### Edge Cases

- Agent binary exits or crashes mid-turn → the transcript shows an honest
  error state; the session offers restart; no zombie processes remain.
- Agent process emits malformed JSON-RPC → the driver surfaces a protocol
  error and terminates that process; the app never hangs on a parse.
- The user opens the mode with zero ACP agents installed → an empty state
  explains what ACP agents are and how to install one (Gemini CLI, neko-core).
- Very long transcripts (thousands of blocks) → rendering stays responsive
  (virtualization), and persistence writes stay incremental, not full rewrites.
- App quit while agent processes run → all sidecar processes are terminated
  (no orphans on Windows/macOS/Linux).
- Two sessions run concurrently → streams never cross; each session's
  transcript receives only its own events.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The app MUST offer a shell-level mode selection reachable before
  any authentication, and MUST remember the selected mode across launches.
- **FR-002**: Neko Chill mode MUST NOT initialize, call, or depend on Wiii
  cloud auth, org context, or backend APIs; the authenticated mode MUST remain
  behaviorally unchanged.
- **FR-003**: The mode MUST detect installed ACP-capable agents (v0: Gemini
  CLI and `neko acp` once released) and let the user choose one per session.
- **FR-004**: The mode MUST run each agent as a child process speaking ACP
  (JSON-RPC over stdio) and MUST hold the session open across multiple turns.
- **FR-005**: Agent output MUST stream into the transcript incrementally as
  normalized events (reasoning, tool activity, answer content, turn lifecycle,
  errors) rendered with the existing transcript block vocabulary.
- **FR-006**: Permission requests from the agent MUST pause the turn and
  render an explicit approve/deny surface; absence of an answer MUST fail
  closed (deny/terminate), never approve.
- **FR-007**: The user MUST be able to cancel a running turn; cancellation
  MUST reach the agent via the protocol and preserve partial transcript.
- **FR-008**: Sessions (metadata + transcript) MUST persist locally and
  restore after app restart without any network access.
- **FR-009**: All agent processes MUST be terminated on app exit and reaped
  after configurable idle time; no orphan processes.
- **FR-010**: The driver layer MUST be provider-agnostic: the normalized event
  vocabulary MUST NOT leak ACP-specific shapes, so a future "Wiii cloud"
  driver (SSE V3) can implement the same contract without transcript changes.

### Key Entities

- **Mode**: shell-level surface selection (`wiii` | `neko-chill`), persisted
  locally; controls which store family and init path run.
- **Agent**: an installed ACP-capable CLI — id, display name, binary path,
  version, detection state.
- **NekoSession**: one conversation with one agent — id, agent id, title,
  created/updated timestamps, ordered transcript blocks, live/idle state.
- **DriverEvent** (normalized): turn-started, reasoning-delta, activity
  (tool/command/file/search), answer-delta, permission-request,
  turn-finished, error, process-exited.
- **PermissionRequest**: id, action kind, target description, options offered
  by the agent, resolution (approved/denied/unanswered→failed-closed).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a fresh install, a user reaches a usable agent prompt in
  under 60 seconds with zero account/credential steps.
- **SC-002**: First streamed content appears within 2 seconds of the agent
  producing it; cancel visibly stops a turn within 2 seconds.
- **SC-003**: 100% of sensitive-action requests in acceptance runs render an
  explicit approval surface; 0 auto-approvals.
- **SC-004**: Sessions restore across restart with 100% transcript fidelity in
  acceptance runs, with no network traffic.
- **SC-005**: The full existing desktop verification gate (vitest, tsc,
  build:embed) passes unchanged — the authenticated product is provably
  untouched.
- **SC-006**: Zero orphaned agent processes after app exit across 10
  open/work/quit cycles on Windows.

## Assumptions

- Gemini CLI's ACP implementation is the acceptance reference; `neko acp`
  (partner team) will be verified against Zed independently, so the two
  workstreams do not block each other (cross-acceptance pact).
- ACP protocol knowledge comes from the public spec and Gemini CLI docs;
  egoist/waku is an **architecture reference only** — it is GPL-3.0 and no
  code may be copied or line-translated from it (Wiii is MIT).
- The existing `ContentBlock` transcript vocabulary and markdown rendering
  stack are reusable by a parallel store without refactoring the cloud chat
  store (audit 2026-08-12 § C confirms).
- v0 targets desktop platforms only (Windows first, macOS/Linux by CI parity);
  mobile and the Wiii-cloud driver inside the mode are explicit later phases.
- Vietnamese-first user-facing copy applies to the new surface (AGENTS.md).

## Runtime Integrity Follow-up (#908)

DeepSeek Harness and its accompanying paper motivate four runtime invariants,
adapted here only at the boundary Wiii actually owns. ACP agents may retain
hidden in-process context, so this section does **not** claim that Wiii can
reconstruct provider memory without a provider resume contract.

- **FR-011 — Durable model boundary**: Every Wiii-controlled fact that can
  affect a provider request (workspace/profile context, user prompt,
  permission decision, effective session control) MUST enter a versioned,
  monotonically sequenced session event log before dispatch.
- **FR-012 — Owned resources**: Every live runtime resource MUST have one
  explicit owner and an idempotent disposer. Mode exit, close, delete, idle
  reap, failed initialization, and process exit MUST all reach teardown.
- **FR-013 — Provider identity and capabilities**: Every runtime attachment
  MUST receive a fresh provider instance identity and an explicit capability
  set. Consumers MUST resolve the current identity and require the capability
  they use; stale provider events and unsupported operations fail closed.
- **FR-014 — Transactional transitions**: Provider replacement MUST prepare
  before commit, leaving the old provider active when preparation fails.
  Configuration changes MUST either durably commit or restore the prior
  effective value and record a rollback; failed compensation is an explicit
  error state.

Acceptance evidence includes ordering at the storage/driver boundary, v1-to-v2
event-log migration without transcript loss, reverse/idempotent disposal,
replacement failure, capability denial, and configuration rollback tests.
