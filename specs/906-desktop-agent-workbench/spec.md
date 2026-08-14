# Feature Specification: Desktop Agent Workbench

**Feature Branch**: `codex/906-desktop-agent-workbench`
**Created**: 2026-08-13
**Status**: Implemented — PR #907 in review
**Issue**: #906
**Input**: Repair the unusable desktop window controls and make Neko Chill/Wiii feel like a coherent, discoverable desktop agent workbench.

## User Scenarios & Testing

### User Story 1 - Trust the desktop window (Priority: P1)

A Windows user can minimize, maximize, restore, and close the custom-decorated
Wiii window with the expected native feedback. Closing preserves the existing
close-to-tray behavior.

**Why this priority**: Broken caption controls make every Wiii surface feel
unreliable and can trap the user in a window state.

**Independent Test**: Launch a packaged Tauri build, operate all three caption
buttons, double-click the drag rail, and verify maximize/restore state plus
close-to-tray behavior.

**Acceptance Scenarios**:

1. **Given** the main Tauri window, **When** the user selects minimize,
   **Then** the window minimizes and the request is not rejected by the ACL.
2. **Given** a restored window, **When** the user selects maximize or
   double-clicks the drag rail, **Then** the window maximizes and the control
   changes to an accessible restore action.
3. **Given** a maximized window, **When** the user restores it, **Then** its
   restore state and glyph update even after an external resize.
4. **Given** the main window, **When** the user selects close, **Then** the
   existing Rust close handler hides it to the tray.
5. **Given** a native API error, **When** a caption action fails, **Then** the
   failure is logged rather than swallowed silently.

---

### User Story 2 - Reach any session or command (Priority: P2)

A Neko Chill user presses Ctrl+K and searches one unified command center for
local actions, agent-reported slash commands, and every persisted session.
The Wiii titlebar exposes its existing command palette through the same visual
language.

**Why this priority**: A growing session tree cannot remain the only route to
history, and slash commands should be discoverable before the user remembers
their exact name.

**Independent Test**: Seed sessions across several workspaces and commands,
open Ctrl+K, filter by transcript/project/command, navigate by keyboard, and
execute each result type.

**Acceptance Scenarios**:

1. **Given** Neko Chill, **When** the user presses Ctrl+K or selects the
   titlebar search affordance, **Then** a modal command center opens and focus
   moves to its query field.
2. **Given** hundreds of persisted sessions, **When** a query matches title,
   project, agent, path, model, or transcript text, **Then** every matching
   session remains reachable without truncating the stored collection.
3. **Given** an active agent reports commands, **When** the user chooses one,
   **Then** the exact slash command is inserted into the composer without
   being sent automatically.
4. **Given** keyboard-only navigation, **When** the user uses arrows, Enter,
   or Escape, **Then** selection, execution, and dismissal are predictable.
5. **Given** Wiii cloud mode, **When** the user selects the titlebar command
   affordance, **Then** the existing Wiii command palette opens.

---

### User Story 3 - Keep the workbench calm and contextual (Priority: P3)

The user can hide the project/session tree, opens the session inspector only
when needed, and always sees the current project, agent, status, and honest
model/profile state. A new or empty session explains the next useful action
without adding a dashboard of inert controls.

**Why this priority**: Permanent side panels currently squeeze the transcript
and duplicate context, especially at narrower desktop widths.

**Independent Test**: Exercise new-session, empty-session, active-session, and
narrow-window states while toggling navigation and inspector surfaces.

**Acceptance Scenarios**:

1. **Given** an active session, **When** it opens, **Then** the inspector stays
   closed until requested and the transcript receives the available width.
2. **Given** the session tree, **When** the user hides it, **Then** a stable
   titlebar action restores it and no session state is lost.
3. **Given** an empty session, **When** it renders, **Then** the workbench shows
   concise getting-started guidance and the available `/` and Ctrl+K routes.
4. **Given** a model that can change at runtime, **When** it is idle, **Then**
   the reported selector remains available; a launch-locked model is labeled
   as such and never rendered as an inert fake selector.
5. **Given** a narrow window, **When** the inspector opens, **Then** it overlays
   instead of permanently compressing the conversation.

### Edge Cases

- Tauri APIs are unavailable in a browser test or hosted build: render no
  caption chrome and do not throw.
- The window is maximized by a system gesture or taskbar action: synchronize
  the restore state from the native resize event.
- A command result disappears as the active session changes: clamp selection
  and never execute a stale array index.
- Duplicate command names from Neko Chill and the agent: label the source and
  preserve the existing exact client-command precedence on submit.
- A session has no workspace or launch profile: keep it searchable and show
  explicit unknown/legacy labels rather than inferred values.
- Close remains hide-to-tray by product policy; the UI must not claim that it
  fully terminates the process.

## Requirements

### Functional Requirements

- **FR-001**: The Tauri capability MUST grant only the window operations used
  by the custom titlebar: close, minimize, toggle maximize, query maximize,
  and start dragging.
- **FR-002**: The shared titlebar MUST use typed Tauri window APIs, await
  actions, expose accessible names, and report rejected native calls.
- **FR-003**: Maximize/restore presentation MUST reflect native window state
  after both titlebar actions and external resizes.
- **FR-004**: Interactive titlebar controls MUST not become drag regions;
  draggable space MUST remain large enough for normal window movement.
- **FR-005**: Wiii and Neko Chill MUST share caption controls and titlebar
  interaction tokens while retaining their existing app-specific navigation.
- **FR-006**: Neko Ctrl+K MUST open a unified, keyboard-accessible command
  center spanning client actions, agent-reported commands, and all local
  sessions.
- **FR-007**: Session search MUST cover the same local metadata/transcript
  fields as the sidebar search and MUST NOT perform a network request.
- **FR-008**: Selecting an agent command from Ctrl+K MUST insert it into the
  composer for review; it MUST NOT execute or send automatically.
- **FR-009**: The project/session sidebar and session inspector MUST be
  independently toggleable; the inspector MUST default closed.
- **FR-010**: The active-session header and composer MUST retain visible,
  provider-backed project, agent, status, mode, and model/profile context.
- **FR-011**: Empty/new session surfaces MUST use progressive disclosure and
  explain the immediate next action without exposing unavailable controls.
- **FR-012**: Existing ACP, persistence, permissions, cancellation, auth, SSE,
  close-to-tray, and backend contracts MUST remain unchanged.

### Key Entities

- **WindowChromeState**: Whether the app is in Tauri and whether the current
  window is maximized; derived from native state and never persisted.
- **WorkbenchCommand**: A client action, agent command, or persisted session
  destination with a stable id, searchable text, source label, and action.
- **WorkbenchPanelState**: Local UI state for the session tree, inspector, and
  command center; it does not alter session persistence.

## Success Criteria

### Measurable Outcomes

- **SC-001**: All caption operations succeed in packaged Windows acceptance;
  zero permission-denied calls appear for the shared titlebar.
- **SC-002**: A keyboard-only user can open Ctrl+K, reach any seeded session or
  reported command, execute/insert it, and dismiss the palette.
- **SC-003**: A seeded session among 200 local sessions is reachable by query
  in under 10 seconds with no silent list cap.
- **SC-004**: At 1000 px viewport width, the default active-session layout
  keeps the inspector closed and the composer usable; opening the inspector
  does not permanently reflow the central pane.
- **SC-005**: Targeted UI tests, full Vitest, TypeScript, embed build, Tauri
  build/check, and native visual acceptance pass.

## Assumptions

- The official DeepSeek Harness informs event/session/workspace architecture;
  its web UI is not treated as a native desktop reference.
- The MIT-licensed Reasonix Desktop may inform interaction principles only;
  Wiii code is independently implemented.
- Research dated through 2026-08-12 informs the UX decisions. The official
  DeepSeek Harness repository, explicitly requested by the user, is a named
  exception because it was published on 2026-08-13.
- No new runtime capability or provider option is needed for this UI pass.
