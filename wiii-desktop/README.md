# Wiii Desktop

Wiii Desktop is the native Wiii Workbench: a Tauri v2 application for durable
AI conversations, local and cloud agents, project files, tools, memory, and
live artifacts. The interface is Vietnamese-first and uses the approved Neko
companion identity.

## Product planes

| Plane | Purpose |
| --- | --- |
| **Wiii ADE** | Human-facing Project, Task, Run, code, review, evidence and artifact experience |
| **Neko Chill** | Provider-neutral agent fabric for Neko Core, Gemini CLI, Codex and future harnesses; owns local execution rather than product work |
| **Wiii Service** | Optional managed/data plane for remote runners, retrieval, memory, organizations, connected tools, policy, audit and synchronization |
| **Hosted web** | The same Workbench contracts with remote runtimes; browser builds never advertise local process or filesystem authority |
| **Embed** | A constrained Wiii surface for explicit external hosts and adapters |
| **Neko Motion Lab** | Isolated preview of mascot states, transitions, and reduced-motion behavior |

The current 1.x shell still renders a local/managed surface switch for backward
compatibility. It is a transitional UI, not the long-term architecture: a run
will compose its provider, environment and optional Wiii Service capabilities
independently. See
[`WIII_ADE_AND_NEKO_AGENT_FABRIC.md`](../docs/architecture/WIII_ADE_AND_NEKO_AGENT_FABRIC.md).

The Workbench owns the visible transcript and stores each provider session ID.
ACP runtimes reconnect with `session/resume`; Codex reconnects with
`thread/resume`. Failed recovery is surfaced instead of silently creating a
different session. Interrupted mutations remain `unknown outcome` and are
never replayed automatically.

Wiii Knowledge is independent from the selected runtime. When enabled, its
retrieved evidence and citation metadata cross the same durability barrier as
the user prompt before any model can observe them. A RAG outage degrades that
connection without disabling local files or agents.

## Key capabilities

- SSE V3 streaming with ordered answer, reasoning, status, tool, source, and
  preview events.
- Persistent conversations and explicit model, provider, profile, reasoning,
  and mode controls.
- Side-by-side workspace for project files, edit activity, code, Markdown,
  HTML previews, diagrams, and generated artifacts.
- Permission cards and preview/apply boundaries for side effects and host
  mutations.
- Wiii Connect surfaces for ACP, MCP, documents, embeds, OAuth applications,
  and host capabilities.
- Organization-aware authentication, settings, feature controls, and admin
  views through Wiii Service.
- Frameless native window, tray, splash screen, Neko-branded NSIS installer,
  and light/dark/system themes.

## Stack

| Technology | Role |
| --- | --- |
| Tauri 2 + Rust | Native shell, sidecars, secure IPC, tray, and installer |
| React 18 + TypeScript | Application UI and typed product contracts |
| Vite 8 | Development and production builds |
| Zustand + Immer | Local state and persistence boundaries |
| Vitest 4 + Playwright | Unit, component, contract, and browser verification |
| Motion 12 + Rive 4 | State-driven interaction and companion animation |

## Quick start

Prerequisites: Node.js 18+, Rust, and the
[Tauri v2 prerequisites](https://v2.tauri.app/start/prerequisites/).

```bash
cd wiii-desktop
npm install

# Frontend only
npm run dev

# Full desktop app
npm run tauri -- dev
```

Useful preview routes:

- `http://localhost:1420/?preview=neko-motion` — Neko Motion Lab
- `http://localhost:1420/splashscreen.html` — splash surface

## Build

```bash
# Web frontend
npm run build

# Standalone embed
npm run build:embed

# Hosted web
npm run build:web

# Windows NSIS installer
npm run tauri build -- --bundles nsis
```

The Windows installer is written to
`src-tauri/target/release/bundle/nsis/`. Build output is generated and must not
be committed.

For a distributable release, keep `package.json`, `tauri.conf.json`,
`Cargo.toml`, `APP_VERSION`, web metadata, splash copy, and installer artwork on
the same version; synchronize the canonical Neko assets before building; then
record SHA-256 and verify Authenticode. Local builds are unsigned unless a
maintainer provides an authorized Windows code-signing certificate.

## Verify

Start with focused checks for the path you changed, then broaden when the risk
requires it:

```bash
npx vitest run
npx tsc --noEmit
npm run build:embed
```

Brand and motion checks:

```bash
python ../docs/assets/brand/neko-family-v1/scripts/verify_neko_family.py
python scripts/probe-neko-motion-lab.py
```

## Repository map

```text
wiii-desktop/
|-- src/
|   |-- components/          Cloud workbench, shared UI, artifacts, settings
|   |-- neko-chill/          Local ACP workspace, runtime, persistence, files
|   |-- workbench/           Host, capability, account, knowledge, and surface contracts
|   |-- neko-motion-lab/     Mascot state and motion research surface
|   |-- pointy-host/         Explicit host-control bridge
|   |-- stores/              Persisted and ephemeral application state
|   `-- __tests__/           Unit, component, and contract tests
|-- src-tauri/               Rust shell, commands, sidecars, icons, NSIS config
|-- public/                  PWA, splash, social card, and public brand assets
|-- playwright/              Browser and runtime-ledger verification
`-- scripts/                 Build, smoke, brand sync, and visual probes
```

Canonical brand sources are in
[`../docs/assets/brand/neko-family-v1/`](../docs/assets/brand/neko-family-v1/).
Never redraw or independently edit generated favicon, OS icon, tray, or
installer derivatives.

## Safety contracts

- Never render raw internal tool JSON as the final answer.
- Keep source references visible for document-grounded answers.
- Never expose local process or filesystem controls on a hosted-web host.
- Keep provider login and billing ownership explicit; Wiii never stores Codex
  tokens and does not offer third-party Claude subscription login.
- Fail closed when permission is unanswered.
- Keep mutating host actions behind preview and explicit approval.
- Preserve session IDs and recovery state; do not convert resume failure into a
  new invisible conversation.
- Keep Neko motion state-driven, brief, interruptible, and reduced-motion safe.

See the repository [`AGENTS.md`](../AGENTS.md) and desktop
[`AGENTS.md`](AGENTS.md) before changing high-risk runtime or UX paths.
