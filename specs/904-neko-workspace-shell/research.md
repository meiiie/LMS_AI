# Research: Neko Chill Workspace Shell

## Sources and license boundary

- Current Neko Chill/Wiii source and real ACP fixtures in `wiii-desktop`.
- Neko Core v0.24.0 source and `docs/process/ACP.md` (partner-owned reference;
  no edits from this workspace).
- Agent Client Protocol v1 schema and official documentation.
- `thinkany-ai/dscode` at commit
  `9f8559c5552e4e191e34c14af4c9314170b949b9` (MIT), cloned outside the Wiii
  repository under the ignored umbrella `references/` directory.
- Waku source/docs (GPL-3.0), read-only outside Wiii. Only interaction and
  architecture facts may be retained; no code or line translation.
- User-provided Codex Desktop screenshot as the target information hierarchy,
  not a pixel-copy target.

## Findings

### Current Neko Chill

- `createDriverForAgent` resolves `session/new.cwd` to the user's home
  directory. Session metadata does not record a workspace.
- Persistence indexes only id, agent, title, and timestamps. Sidebar order is
  creation-time and flat.
- The ACP driver currently discards every update other than text, thought,
  tool, and plan content. Initial modes/models are also discarded.
- Thinking chunks are rendered as plain pre-wrapped text, so provider emphasis
  markers remain literal.
- Restored transcripts are local logs; Neko Core does not advertise ACP
  session load/resume, so a subsequent prompt starts a new agent runtime.

### Neko Core v0.24.0

- Stable ACP v1 supports `initialize`, `session/new`, `session/prompt`,
  `session/cancel`, `session/close`, and `session/set_mode`.
- Four modes are returned from session creation: default, accept-edits, plan,
  and auto.
- Model and provider are config-first. `neko profiles` prints the resolved
  named profiles with provider/model and marks the active profile. Launching
  `neko acp --profile <id>` selects one profile without rewriting config.
- Neko ACP does not advertise model switching, commands, session list/load, or
  resume. The UI must not claim those capabilities.

### Gemini CLI ACP fixture

- Session creation reports modes and a legacy model catalog/current model.
- `session/set_model` changes the live model.
- `available_commands_update` reports command name/description pairs after
  session creation.

### Current ACP v1

- Stable session config options describe select/boolean controls and semantic
  categories such as mode, model, model_config, and thought_level.
- `session/set_config_option` returns the full updated option set.
- `available_commands_update` is stable. `session_info_update` can update title
  and updatedAt.
- The dedicated model API was never stabilized and was removed from current
  protocol artifacts in June 2026. Compatibility with Gemini therefore stays
  feature-detected and isolated inside the ACP driver.

### Dscode and Codex Desktop

- Project/workspace is the parent entity; conversations are children.
- Dense 30-34px navigation rows expose far more history than chat cards.
- Search spans project/session metadata and preview text.
- Composer controls carry workspace, model, permission/sandbox, and effort;
  a context card exposes tokens/model/cost separately from the transcript.
- Session persistence separates transcript source-of-truth from a searchable
  metadata index.

### Waku behavior lessons

- Session owns provider-reported commands and control state.
- Slash completion merges provider-reported commands with client/workspace
  commands, then filters at the caret.
- Model/mode controls are capability-aware and transport-specific operations
  stay inside drivers.
- Workspace changes invalidate workspace-scoped caches and never borrow state
  from another selected session.

## Decisions

1. Workspace is mandatory for new sessions; legacy sessions remain readable
   and require attachment before another prompt.
2. One normalized `DriverConfigOption` represents legacy and stable controls.
   The ACP driver privately remembers how each option is written.
3. Stable config options take precedence over equivalent legacy mode/model
   fields. Gemini compatibility remains supported when stable options are
   absent.
4. Neko model choice is a launch profile, not an in-session toggle. Discovery
   runs read-only in the selected project so project-local config is reflected.
5. The first delivery adds a compact session inspector, not a file explorer or
   diff panel. Those require separate runtime contracts and evidence.
6. Search stays in memory over the already-local session index/transcripts;
   no SQLite dependency is introduced for the current scale.
