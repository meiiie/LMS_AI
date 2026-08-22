# Feature Specification: Wiii ADE and Neko Control Foundation

**Feature Branch**: `codex/939-feat-wiii-ade-neko-control`
**Created**: 2026-08-23
**Status**: In progress
**Issue**: #939
**Input**: Establish Wiii ADE as the owner of work and Neko Chill as the
provider-neutral execution fabric before a larger product-shell redesign.

## User Scenarios & Testing

### User Story 1 - Keep work identity above conversations (Priority: P1)

A person can describe one durable task and attempt it through multiple runs or
agent sessions without duplicating the task. Restarting, resuming, forking, or
changing a provider does not silently create a different unit of work.

**Why this priority**: A task-first ADE cannot be built while chat sessions are
the highest-level product entity.

**Independent Test**: Build an in-memory project graph containing one task,
two runs, and three provider sessions; validate it, then prove that invalid
cross-project or missing references fail with stable diagnostics.

**Acceptance Scenarios**:

1. **Given** one task with two independent implementations, **When** Wiii
   records two runs, **Then** both runs retain the same task identity while
   their environments and provider sessions remain independent.
2. **Given** a provider session resumes after process replacement, **When** its
   provider session identifier changes or is recovered, **Then** its task and
   run identities remain unchanged.
3. **Given** a run references an environment from another project, **When**
   Wiii validates the graph, **Then** the graph is rejected instead of being
   repaired by inference.

---

### User Story 2 - Discover and launch providers through one boundary (Priority: P1)

A person sees the local harnesses that Neko can actually operate. Wiii uses one
provider registry for product metadata and launch behavior, while the control
client hides Tauri command details from React stores and provider drivers.

**Why this priority**: Adding OpenCode or Claude to the current duplicated
catalog/detection/factory paths would multiply product-truth drift.

**Independent Test**: Feed detected Neko Core, Gemini CLI, and Codex binaries
through the registry; verify their integration level, launch arguments,
account owner, and fail-closed handling of unknown providers.

**Acceptance Scenarios**:

1. **Given** a detected provider, **When** Neko resolves its definition, **Then**
   the UI label, integration level, launch protocol, and auth owner come from
   the same registry entry.
2. **Given** an unsupported provider identifier, **When** a launch is
   requested, **Then** Neko rejects it before spawning a process.
3. **Given** a browser host without Tauri authority, **When** provider
   discovery runs, **Then** the control client returns no local providers and
   does not pretend that a local process exists.

---

### User Story 3 - Preserve the contract a session actually observed (Priority: P2)

A person can inspect which provider version, integration and capabilities a
historical agent session started with even after the provider is upgraded.

**Why this priority**: Durable sessions cannot be debugged if current provider
capabilities overwrite historical execution truth.

**Independent Test**: Attach a fake driver with a negotiated capability set,
persist the runtime-attached event, reload it, and compare the capability
snapshot byte-for-byte while also loading a legacy event without the field.

**Acceptance Scenarios**:

1. **Given** a provider attaches successfully, **When** the runtime event is
   committed, **Then** it contains a versioned, JSON-safe capability snapshot.
2. **Given** an older stored event without a capability snapshot, **When** Wiii
   restores it, **Then** restoration succeeds and unavailable capabilities
   remain unavailable rather than guessed.
3. **Given** a provider emits a proprietary capability, **When** Neko
   normalizes the session, **Then** common UI uses the normalized capability
   set while bounded provider extensions remain available for provider-native
   views.

### Edge Cases

- A provider executable is found but its version probe is empty.
- ACP reports resume but no models or commands; unsupported controls remain
  hidden.
- A provider updates during a live session; the session keeps its start
  snapshot and a later session receives the newer snapshot.
- A protocol request uses an unknown version, method, or provider identifier;
  it fails before side effects.
- Legacy local sessions contain `agentId` values that are no longer installed;
  transcript recovery remains possible while relaunch is unavailable.
- Provider extension data is non-JSON, oversized, or secret-like; it is not
  admitted into the durable snapshot.

## Requirements

### Functional Requirements

- **FR-001**: Wiii MUST define `Project`, `Workspace`, `Task`, `Spec`, `Run`,
  `AgentSession`, `Environment`, `Artifact`, `Evidence`, `Approval`, and
  `AttentionItem` as distinct entities with stable identifiers.
- **FR-002**: The canonical hierarchy MUST be `Project -> Task -> Run ->
  AgentSession`; environment and evidence records MUST remain independently
  addressable.
- **FR-003**: Graph validation MUST reject dangling references and
  cross-project task/environment mismatches without guessing repairs.
- **FR-004**: Wiii ADE MUST own project, task, spec, review, evidence and human
  decision state; Neko MUST own execution lifecycle; provider sessions and
  Wiii Service MUST retain their documented authority.
- **FR-005**: Neko Control Protocol MUST be versioned independently from ACP,
  Codex App Server, OpenCode Server and other provider protocols.
- **FR-006**: The first control contract MUST cover initialization, provider
  discovery, session discovery/start/resume/cancel, approval resolution,
  normalized events, errors and provider extensions.
- **FR-007**: Unknown protocol versions, methods, provider IDs and capabilities
  MUST fail closed.
- **FR-008**: The production local runtime path MUST use one provider registry
  for provider identity, integration level, auth owner and launch arguments.
- **FR-009**: The registry MUST support native structured, ACP, structured
  SDK/CLI and PTY integration levels without claiming unimplemented adapters.
- **FR-010**: Every newly attached runtime MUST expose a versioned capability
  snapshot derived from observed driver facts and registry metadata.
- **FR-011**: Capability snapshots MUST preserve common normalized fields and
  MAY preserve bounded JSON-scalar provider extensions; secrets and arbitrary
  raw payloads MUST NOT be persisted.
- **FR-012**: Existing local session events and snapshots without the new
  capability field MUST remain readable.
- **FR-013**: Provider login, tokens, billing, model catalog and opaque
  continuation state MUST remain owned by the provider or documented server.
- **FR-014**: React components and Zustand stores MUST NOT call raw Tauri
  discovery/profile/spawn commands after the control-client bridge is adopted.
- **FR-015**: This feature MUST NOT imply that the in-process bridge is already
  a crash-independent daemon; that migration requires a later issue.

### Key Entities

- **Project**: Long-lived product/repository identity.
- **Workspace**: One or more source roots attached to a project.
- **Task**: A durable unit of desired work, independent from attempts.
- **Spec**: Versioned requirements, constraints and acceptance criteria for a
  task.
- **Run**: One attempt to execute a task in one environment.
- **AgentSession**: One provider-owned conversation/session bound to a run.
- **Environment**: The execution location and isolation contract.
- **Artifact**: A produced diff, log, report, screenshot, package or PR.
- **Evidence**: A verification observation linked to a run and optional
  artifacts.
- **Approval**: A durable human or policy decision about one proposed action.
- **AttentionItem**: A derived or persisted request for human intervention.
- **ProviderDefinition**: Stable registry metadata and launch contract.
- **ProviderCapabilitySnapshot**: Historical provider/version/integration and
  normalized capability facts observed for one session.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Focused tests construct one task with multiple runs/sessions and
  reject every tested dangling or cross-project reference deterministically.
- **SC-002**: Neko Core, Gemini CLI, and Codex discovery plus launch behavior
  resolve through one production registry with no duplicate TypeScript launch
  argument table.
- **SC-003**: A runtime-attached event round-trips a capability snapshot and a
  pre-feature event remains valid.
- **SC-004**: No new provider credential, raw token, cookie, environment value,
  or unbounded provider event appears in persisted test fixtures.
- **SC-005**: Focused Vitest, TypeScript and repository hygiene checks pass;
  broader desktop checks report exact results.

## Assumptions

- Existing local sessions remain the execution record until a later SQLite
  daemon migration; they are not promoted to ADE tasks automatically here.
- The current Rust process table remains the native process owner for this
  slice, behind a replaceable control client.
- ACP v1 and Codex App Server adapters remain intact; ACP v2, OpenCode,
  Claude, PTY, worktrees and remote environments are follow-up work.
- The managed backend and database schemas do not change in this feature.
- The current Workbench UI remains available while the data and control
  contracts are established.
