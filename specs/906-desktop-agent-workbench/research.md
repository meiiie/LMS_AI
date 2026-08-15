# Research: Desktop Agent Workbench

**Date**: 2026-08-13
**Scope cutoff**: 2026-08-12, except the user-named official DeepSeek Harness
repository published on 2026-08-13.

## Primary product and platform evidence

### DeepSeek Harness (official, MIT)

Source: <https://github.com/deepseek-ai/deepseek-harness>

- Treats the event/session log as the source of truth: model-visible state is
  logged, and the interface projects that state instead of maintaining a
  second hidden story.
- Requires an explicit workspace before the composer becomes actionable.
- Separates interaction, process, and infrastructure. Human commands can
  change the session without pretending to be another model turn.
- Useful Wiii decision: preserve the current explicit workspace and ACP event
  boundary; improve how those facts are projected rather than adding a second
  orchestration model.

### DeepSeek Reasonix Desktop (community, MIT)

Source: <https://github.com/esengine/DeepSeek-Reasonix>

- Uses native window methods behind a custom titlebar, tracks maximize/restore
  state, reserves a caption-button safe area, and excludes interactive
  controls from the drag rail.
- Uses workspace-first navigation, grouped command search, a quiet welcome
  state, token/context status, and progressive side panels.
- Useful Wiii decision: adopt the interaction principles, not its large
  component architecture. Keep Wiii's existing stores and ACP seam.

### Tauri v2 and Windows app design

Sources:

- <https://v2.tauri.app/learn/window-customization/>
- <https://v2.tauri.app/reference/acl/core-permissions/>
- <https://learn.microsoft.com/en-us/windows/apps/develop/ui/controls/title-bar>
- <https://learn.microsoft.com/en-us/windows/apps/design/basics/titlebar-design>

The current failure is deterministic: `core:default` does not grant every
custom-titlebar operation. Tauri's own example requires explicit close,
minimize, toggle-maximize, and start-dragging permissions. Windows guidance
requires full-bleed caption backplates, distinct hover/pressed/inactive states,
maximize/restore feedback, and a usable drag region.

Decision: add the narrow ACL set, keep close-to-tray in Rust, and synchronize
maximize state through native events. Caption buttons remain at least 44 px
tall and have visible keyboard focus.

## Human-agent interaction evidence

### User-experience principles for workplace agents (2026)

Source: <https://arxiv.org/abs/2607.19941>

Human control is the highest-ranked principle: users need confirmation before
critical decisions and the ability to intervene, override, pause, stop, or
disengage. Reliability, context-aware integration, collaboration, and a
responsive interface follow closely.

Decision: retain the explicit stop control, never auto-run a command selected
from Ctrl+K, expose runtime state, and keep irreversible behavior out of this
UI-only change.

### Interaction, Process, Infrastructure framework

Source: <https://www.microsoft.com/en-us/research/publication/interaction-process-infrastructure-a-unified-framework-for-human-agent-collaboration/>

The framework distinguishes the interaction transcript from a persistent,
editable process and the underlying infrastructure. It recommends overview to
detail navigation and attention orchestration, while warning that permanent
explicit structure creates cognitive overhead.

Decision: keep transcript, activity/status, and runtime controls distinct;
use a command center and on-demand inspector rather than three permanently
busy panels.

### Interruption and blind goal-directedness

Sources:

- <https://openreview.net/forum?id=4ZqYaS2Iz9>
- <https://www.microsoft.com/en-us/research/publication/just-do-it-computer-use-agents-exhibit-blind-goal-directedness/>

Interactive speculative planning treats human interruption as a productive
correction path. Computer-use agents also show an execution-first bias under
ambiguity, which makes explicit status and stop/override affordances necessary.

Decision: make working state and cancel visible, keep commands reviewable in
the composer, and avoid automatic execution from global navigation.

## Accessibility evidence

Sources:

- <https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html>
- <https://www.w3.org/WAI/WCAG22/Techniques/aria/ARIA14>

Icon-only controls need stable accessible names and at least a 24 by 24 CSS-px
target under WCAG 2.2. The workbench uses larger desktop targets, labeled
buttons, dialog semantics, keyboard navigation, and visible focus.

## Rejected directions

- Do not replace Wiii/Neko stores with the reference repositories' plugin or
  state architecture.
- Do not add a dashboard, agent plan schema, token budget, or cost meter when
  the current ACP contracts do not provide those facts.
- Do not expose raw chain-of-thought or invent model selectors.
- Do not make the inspector permanent at narrow widths.
- Do not broaden Tauri permissions beyond the window operations in use.
