# Feature Specification: Desktop ADE Activation

**Feature Branch**: `codex/949-feat-desktop-ade-activation`  
**Created**: 2026-08-24  
**Status**: In progress  
**Issue**: #949  
**Input**: Make the existing `Project -> Task -> Run -> AgentSession`
foundation visible and durable in Wiii Desktop while preserving Neko Chill as
the manual Agent Fabric surface.

## User Scenarios & Testing

### User Story 1 - Start from work, not a conversation (Priority: P1)

A desktop user opens Wiii and sees projects and work. They can create a task by
choosing a local project, describing the desired outcome, optionally recording
acceptance criteria, and selecting an agent. Wiii persists the work identity
before asking Neko to execute it.

**Why this priority**: The runtime already understands Task, Run and provider
session identity, but the product still teaches users that a chat session is
the highest-level object.

**Independent Test**: Create a task from a local folder, simulate a delayed or
failed agent launch, reload the product state and prove the Project, Workspace,
Task, Spec, Environment and Run remain valid and discoverable.

**Acceptance Scenarios**:

1. **Given** local Wiii has no tasks, **When** the user opens it, **Then** the
   primary action is `Công việc mới`, not `Phiên mới`.
2. **Given** a selected folder and valid goal, **When** the user starts work,
   **Then** Wiii durably stores Project, Workspace, Task, Spec, Environment and
   Run before Neko dispatch can begin.
3. **Given** dispatch fails after the work record is committed, **When** Wiii
   reloads, **Then** the task remains visible and its run reports a truthful
   failed or uncertain state rather than disappearing.

---

### User Story 2 - Bind Neko execution to Wiii work (Priority: P1)

An ADE-created run starts an existing Neko provider session with explicit Task,
Run and Environment identities. A manual Neko session still works and receives
the legacy compatibility identities.

**Why this priority**: A task-shaped screen without a real execution binding
would create a second source of truth and leave the architecture session-first.

**Independent Test**: Start one session from a Wiii task and one from the Neko
manual launcher; assert that native session records use the real ADE binding for
the first and stable legacy-local identities for the second.

**Acceptance Scenarios**:

1. **Given** a committed Run, **When** Neko starts its provider, **Then** the
   control request contains that Run's Task and Environment IDs.
2. **Given** a provider attaches successfully, **When** Wiii records the
   binding, **Then** one AgentSession belongs to that Run without changing the
   Task identity.
3. **Given** the user opens Neko Chill directly, **When** they create a manual
   session, **Then** the current launcher and durable transcript continue to
   work without requiring a Wiii task.

---

### User Story 3 - Keep product navigation and context concepts separate (Priority: P2)

A user can move between Wiii work and Neko Chill without treating Wiii Service,
local execution and Wiii Knowledge as competing product modes. Knowledge is an
optional context capability attached to agent work.

**Why this priority**: Mixing product space, execution location and context in
one dropdown makes the desktop architecture appear fragmented.

**Independent Test**: Inspect the local navigation and session inspector;
verify Wiii work and Neko Chill are navigation destinations, Service is an
optional connection, and Knowledge appears only as context.

**Acceptance Scenarios**:

1. **Given** the user is in Neko Chill, **When** they open the product switcher,
   **Then** they can return to Wiii work and can optionally open Wiii Service.
2. **Given** Wiii Knowledge is available, **When** the user configures a run or
   inspects a session, **Then** Knowledge is presented as context rather than a
   workspace/mode.
3. **Given** a task-bound session, **When** the user opens it, **Then** Task and
   Run lifecycle facts are shown outside the conversation transcript.

### Edge Cases

- A persisted ADE snapshot is malformed, has an unsupported version, or fails
  graph validation: loading fails visibly and Wiii does not overwrite it.
- Two attempts target the same folder and title: each attempt has a distinct
  Run; the existing Task is not silently guessed or merged.
- The provider is unavailable after the work records commit: the Run becomes
  failed without deleting Task/Spec/Environment records.
- Provider dispatch has an uncertain native outcome: the Run becomes
  `unknown_outcome` and Wiii does not auto-retry.
- Existing Neko session snapshots lack an execution binding: they hydrate as
  legacy sessions and remain usable.
- Browser-hosted Wiii has no local process authority: this slice does not expose
  local task execution there.

## Requirements

### Functional Requirements

- **FR-001**: Desktop local bootstrap MUST open a Wiii-owned work surface that
  presents Projects and Tasks before Neko session transcripts.
- **FR-002**: Wiii MUST provide a `Công việc mới` journey that captures a local
  folder, goal, acceptance criteria, provider and launch profile.
- **FR-003**: The work repository MUST persist a versioned `AdeGraph` through
  the strict storage boundary and reject malformed, unsupported or invalid
  snapshots without repairing or overwriting them.
- **FR-004**: Creating work MUST commit Project, Workspace, Task, Spec,
  Environment and Run records before any provider process side effect.
- **FR-005**: Every ADE-created Neko session MUST persist an explicit
  `{ taskId, runId, environmentId }` execution binding before provider dispatch.
- **FR-006**: Neko's driver factory MUST pass an explicit execution binding to
  Neko Control when available; only manual/legacy sessions MAY synthesize
  `legacy-local` identities.
- **FR-007**: After provider attachment, Wiii MUST record one AgentSession for
  the Run using provider-native identity when observed and MUST transition the
  Run truthfully.
- **FR-008**: Provider launch failure MUST transition the committed Run to
  `failed`; uncertain native outcomes MUST transition it to `unknown_outcome`.
- **FR-009**: Invalid run transitions and invalid graph references MUST fail
  without mutating durable work state.
- **FR-010**: Existing Neko session snapshots without execution binding MUST
  remain readable and continue to use the compatibility lifecycle path.
- **FR-011**: Neko Chill's manual `Phiên mới` launcher MUST remain available as
  an execution-level tool, not Wiii's primary home action.
- **FR-012**: Product navigation MUST distinguish Wiii work, Neko Chill and the
  optional Wiii Service connection.
- **FR-013**: Wiii Knowledge MUST be removed from the product-space switcher and
  exposed as an optional context control.
- **FR-014**: Task/Run state MUST be visible outside the transcript; raw
  provider reasoning and lifecycle facts MUST NOT become ordinary messages.
- **FR-015**: This feature MUST NOT claim worktree isolation, standalone daemon
  continuity, editor/LSP, Attention Inbox, cloud handoff, OpenCode or Claude.
- **FR-016**: Desktop and Neko visual language, Vietnamese-first copy, keyboard
  access and reduced-motion behavior MUST be preserved.

### Key Entities

- **AdeWorkSnapshot**: Versioned local product-state envelope containing one
  validated `AdeGraph` and update timestamp.
- **TaskDraft**: User input used to create the durable Project/Task/Run chain.
- **NekoExecutionBinding**: Existing Neko Control identity tuple containing
  Task, Run and Environment IDs.
- **NekoSession**: Visible provider session and transcript, optionally bound to
  Wiii work.

## Success Criteria

### Measurable Outcomes

- **SC-001**: On a fresh desktop state, the primary local CTA reads
  `Công việc mới`; the Neko manual launcher remains reachable in one action.
- **SC-002**: Tests prove provider dispatch is not invoked until a complete,
  valid ADE graph has been committed.
- **SC-003**: A task-created native start contains the exact persisted Task,
  Run and Environment IDs; a manual start retains compatibility IDs.
- **SC-004**: Valid snapshots round-trip exactly, while malformed/version-skewed
  snapshots fail closed without a save operation.
- **SC-005**: Existing Neko persistence fixtures hydrate without migration loss.
- **SC-006**: Focused Vitest, TypeScript, native Rust/Tauri gate, desktop build
  and visual browser evidence pass or are reported with exact failure detail.

## Assumptions

- One local folder maps to one project/workspace in this slice; explicit
  multi-root project management is a follow-up.
- A new task creates exactly one initial Run with `single` strategy and a
  `local_workspace` Environment.
- Worktree isolation is not implied by `local_workspace`; the UI states this
  honestly.
- Wiii Service and backend schemas are unchanged.
- The Rust runtime remains in-process. Closing Wiii can still stop execution;
  standalone background execution is separate work.
