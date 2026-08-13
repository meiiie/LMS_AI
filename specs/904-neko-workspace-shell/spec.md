# Feature Specification: Neko Chill Workspace Shell

**Feature Branch**: `codex/904-neko-workspace-shell`
**Created**: 2026-08-13
**Status**: Implemented
**Issue**: #904
**Input**: User request to evolve Neko Chill from a flat chat into a Codex-class local desktop-agent workspace with project/session management, honest model controls, and slash commands.

## User Scenarios & Testing

### User Story 1 - Work inside an explicit project (Priority: P1)

A user chooses a project folder, chooses a local ACP agent, and starts a
session whose tools are scoped to that exact folder. Returning later, the user
finds the session grouped beneath the project and can search a large local
history by session, project, agent, path, or transcript preview.

**Why this priority**: The current implementation silently uses the user's
home directory and has no project entity. That is both a safety problem and
the primary reason the shell does not feel like a desktop coding agent.

**Independent Test**: Create sessions in two temporary folders, verify the
ACP `session/new.cwd` values, restart the app, and find both sessions under
their respective projects through search.

**Acceptance Scenarios**:

1. **Given** the new-session view, **When** the user has not selected a folder,
   **Then** no agent session can start and the UI explains that a project is
   required.
2. **Given** a selected absolute folder, **When** a session starts, **Then**
   that exact folder is passed to ACP and persisted with the session.
3. **Given** sessions from several folders, **When** the sidebar renders,
   **Then** projects are the primary groups, sessions are ordered by recent
   activity, and the full list is scrollable rather than silently truncated.
4. **Given** a search term matching a title, agent, project name/path, or
   transcript content, **When** the user searches, **Then** every matching
   local session remains reachable with keyboard and pointer.
5. **Given** a pre-feature session without workspace metadata, **When** the
   app hydrates, **Then** the transcript remains intact in a clearly labeled
   legacy group and the user can attach a folder before the next prompt.

---

### User Story 2 - Control the agent through real capabilities (Priority: P2)

The composer shows the active permission mode, model/profile, and slash
commands when the chosen agent actually exposes them. The user can switch a
reported mode or model and autocomplete a reported command without learning
which ACP dialect the agent uses.

**Why this priority**: A static agent-name chip hides important runtime state.
Capability-backed controls are the difference between a chat box and an agent
cockpit, but controls that the backend cannot honor would be worse than none.

**Independent Test**: Replay the real Neko Core and Gemini fixtures. Neko
offers its four modes and a launch-time profile/model; Gemini offers its model
catalog and reported slash commands. Assert the corresponding ACP requests.

**Acceptance Scenarios**:

1. **Given** Neko Core reports modes, **When** the user changes mode, **Then**
   the driver sends `session/set_mode` and the selected value updates only
   after success.
2. **Given** Gemini reports its legacy model catalog, **When** the user changes
   model, **Then** the driver sends `session/set_model` for that live session.
3. **Given** an ACP agent reports stable session config options, **When** a
   categorized option changes, **Then** the driver uses
   `session/set_config_option` and replaces the option set from the response.
4. **Given** Neko Core does not advertise in-session model switching, **When**
   the session is active, **Then** the UI shows the model selected through the
   launch profile and explains that changing it requires a new session.
5. **Given** Gemini sends `available_commands_update`, **When** the user types
   `/`, **Then** a keyboard-accessible palette filters those commands and
   inserts the selected command into the prompt.
6. **Given** an agent reports no commands, **When** the user types `/`, **Then**
   only genuine Neko Chill client commands appear; the UI never invents agent
   commands.

---

### User Story 3 - Understand session state at a glance (Priority: P3)

While a session is open, the user can see its title, project, agent, runtime
status, active controls, and command availability in the header/composer and a
compact inspector. Provider reasoning reads as status text rather than leaking
literal Markdown markers.

**Why this priority**: Rich navigation without clear active context still
creates wrong-project and wrong-model mistakes.

**Independent Test**: Render sessions at desktop and narrow widths, drive
session-info and streaming fixtures, and verify the same facts remain
accessible with the inspector open or closed.

**Acceptance Scenarios**:

1. **Given** a live session, **When** it opens, **Then** the title, project,
   agent, status, mode, and model/profile are visible without inspecting logs.
2. **Given** an agent sends `session_info_update`, **When** it contains a
   title or timestamp, **Then** local session metadata and navigation update.
3. **Given** a reasoning chunk such as `**Inspecting files**`, **When** it
   renders, **Then** the visible status is `Inspecting files`, not raw marker
   characters.
4. **Given** a narrow window, **When** the inspector cannot fit beside the
   transcript, **Then** it becomes an overlay/toggle and never squeezes the
   composer below its usable width.

### Edge Cases

- A folder dialog is cancelled: preserve the current selection and start no
  process.
- A persisted project folder no longer exists: keep the transcript visible,
  show an actionable error on restart, and never fall back to home.
- A profile probe fails or emits an unknown line: ignore malformed entries,
  show the agent's default configuration, and do not block session creation.
- A control changes while a turn is streaming: reject/disable the change until
  the turn is idle.
- An agent rejects a control method: keep the previous value and surface the
  protocol error without terminating the transcript.
- Agent and client commands share a name: label their source and prefer the
  explicit client command only when the submitted text exactly matches it.
- Hundreds of sessions: navigation remains one scroll surface with no nested
  scroll traps; search operates on local state only.

## Requirements

### Functional Requirements

- **FR-001**: Every newly created Neko Chill session MUST have an explicit,
  absolute workspace path selected by the user.
- **FR-002**: The selected workspace MUST be the exact `cwd` passed to ACP
  `session/new`; the driver MUST NOT silently substitute home or `/`.
- **FR-003**: Session metadata MUST persist workspace path/name, launch
  profile/model when known, creation time, and last activity time locally.
- **FR-004**: Navigation MUST group sessions by workspace, retain legacy
  sessions, show runtime status, and search all locally available metadata and
  transcript preview text.
- **FR-005**: The provider-neutral driver contract MUST represent session
  config controls, reported commands, and session-info updates without
  exposing ACP wire shapes to the store or UI.
- **FR-006**: ACP legacy mode/model fields and stable config options MUST map
  to one normalized control vocabulary with source-specific writes confined to
  the ACP driver.
- **FR-007**: Control changes MUST be capability-backed, fail without
  optimistic drift, and be disabled while a turn or permission request is
  active.
- **FR-008**: Neko Core profiles MUST be discovered read-only from the detected
  Neko executable for the selected project; selecting one MUST add
  `--profile <id>` to that session's launch arguments without changing Neko's
  global configuration.
- **FR-009**: Slash autocomplete MUST merge a small documented set of
  Neko-Chill-owned commands with commands reported by the active agent, label
  their source, and remain keyboard accessible.
- **FR-010**: `available_commands_update`, `config_option_update`,
  `current_mode_update`, and `session_info_update` MUST update only their
  addressed local session.
- **FR-011**: Existing v1 session indexes/transcripts MUST hydrate without data
  loss; missing new fields MUST receive safe legacy defaults.
- **FR-012**: Reasoning presentation MUST remove only a matching outer pair of
  common emphasis markers; it MUST preserve the underlying text and never run
  reasoning as unsafe HTML.
- **FR-013**: Neko Chill MUST remain pre-auth, local-only, and independent of
  Wiii backend/auth/org stores.
- **FR-014**: Existing permission, cancel, process reaping, and transcript
  persistence behavior MUST remain intact.

### Key Entities

- **WorkspaceRef**: Absolute local path plus display name; owns zero cloud
  identity and groups local sessions.
- **AgentLaunchProfile**: Read-only Neko profile id, provider, model, and
  active/default marker used only when spawning a Neko ACP process.
- **DriverConfigOption**: Normalized select/boolean control with id, label,
  semantic category, current value, choices, and protocol source hidden inside
  the driver implementation.
- **DriverCommand**: Name, description, optional input hint, and source
  (`agent` or `client`).
- **NekoSession**: Existing local transcript plus workspace, timestamps,
  launch profile, runtime controls, commands, and control-update state.

## Success Criteria

### Measurable Outcomes

- **SC-001**: In acceptance runs, 100% of new sessions send the selected
  folder as ACP `cwd`; zero sessions silently use the home directory.
- **SC-002**: A user can locate any seeded session among 200 local sessions by
  project/title search in under 10 seconds.
- **SC-003**: Every rendered model/mode choice corresponds to a reported
  capability or a discovered Neko launch profile; zero inert choices render.
- **SC-004**: Keyboard-only users can open navigation search, select a slash
  command, change a supported control, toggle the inspector, and send/cancel a
  prompt.
- **SC-005**: Existing v1 persistence fixtures hydrate with 100% transcript
  fidelity and gain legacy workspace defaults without migration errors.
- **SC-006**: Targeted Neko Chill tests, TypeScript, embed build, Cargo checks,
  and native Windows visual acceptance pass with no Wiii cloud initialization.

## Assumptions

- Neko Core v0.24.0 intentionally exposes modes but not model/commands through
  ACP; launch profiles are the honest current model-selection seam.
- Gemini CLI's legacy ACP model fields remain a compatibility surface even
  though the dedicated model API was never stabilized in the current ACP v1
  schema; stable config options take precedence when both are present.
- Agent-native resume/load remains out of scope. Reopening a persisted Neko
  transcript starts a new runtime, as documented by #886.
- Dscode's MIT implementation may inform structure and interaction. Waku's
  GPL implementation may inform only behavior and design parameters; no source
  code is copied or line-translated.
