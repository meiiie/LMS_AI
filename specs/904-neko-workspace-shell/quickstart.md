# Quickstart: Neko Chill Workspace Shell Acceptance

1. Install Neko Core v0.24.0+ and Gemini CLI with ACP support.
2. Start `wiii-desktop` through Tauri and enter Neko Chill before login.
3. Choose a temporary project folder. Confirm no Start action is enabled before
   a folder is selected.
4. Choose Neko Core, inspect its discovered profiles, select a non-default
   profile, and start a session.
5. Verify the project appears in the sidebar and the composer/inspector show
   its path plus the selected provider/model.
6. Change Neko mode and drive one permission request; approve/deny explicitly.
7. Open a Gemini session in another folder, change a reported model, type `/`,
   select a reported command with the keyboard, and send it.
8. Restart the app. Verify both project groups and transcripts return; attach a
   folder to any seeded legacy session before prompting.
9. Search by project path, session title, agent name, and transcript phrase.
10. Narrow the window and verify the inspector toggles without clipping the
    composer. Quit and confirm no agent process remains.

## Acceptance evidence (2026-08-13)

- Native Windows: Neko Core 0.24.1 launched in the exact selected `wiii`
  workspace with profile `chatgpt` / `gpt-5.6-luna` and four reported modes.
- Native Windows: Gemini CLI 0.38.1 reported two controls, eight models, and
  20 slash commands; changing to `gemini-2.5-flash-lite` updated both composer
  and inspector after the ACP request succeeded.
- Browser visual probe: four seeded sessions remained reachable in three
  project groups; Ctrl+K search and agent slash insertion passed at 1495px and
  the inspector became an overlay at 960px; no browser console errors.
- Automated gates: Neko Chill 41/41, TypeScript, desktop build, embed build,
  Rust parser test, and Cargo check passed. The full Vitest run passed
  2,617/2,618 with the known order/load timeout in `knowledge-viz`; that file
  then passed 23/23 in isolation.
