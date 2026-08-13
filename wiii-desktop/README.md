# Wiii Desktop

<div align="center">

![Tauri v2](https://img.shields.io/badge/Tauri-v2-24C8D8?logo=tauri&logoColor=white)
![React 18](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=black)
![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?logo=typescript&logoColor=white)
![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-3.4-06B6D4?logo=tailwindcss&logoColor=white)
![Vitest](https://img.shields.io/badge/Vitest-1857_tests-6E9F18?logo=vitest&logoColor=white)

**Cross-platform desktop client for the Wiii Soul AGI Platform.**

*by The Wiii Lab -- March 2026*

</div>

---

## Features

- **Real-time AI Chat** -- SSE V3 streaming with token-by-token response, thinking lifecycle, tool call cards
- **Rich Thinking Display** -- Thinking blocks, reasoning timeline, multi-phase thinking chain, action text
- **Living Avatar** -- Emotion-driven avatar with Rive integration, manga indicators, micro-reactions, mood themes
- **Living Agent Dashboard** -- 5-tab dashboard (Overview, Skills, Goals, Journal, Reflections) with 4D mood indicator, heartbeat monitor, goal tracking, reflections viewer
- **Soul Bridge Monitor** -- 3-tab dashboard (Overview, Events, Config) for monitoring connected SubSouls via Soul Bridge with 30s auto-refresh, peer cards, event timeline
- **Product Card Carousel** -- Real-time SSE preview cards, horizontal snap-scroll, LLM-curated results
- **Google OAuth Authentication** -- Desktop deep link flow with JWT refresh tokens, PKCE S256
- **Multi-Organization Workspace** -- Workspace switcher with org-level branding, permissions, feature gating
- **Two-Tier Admin** -- System admin (7-tab panel) + Org admin (4-tab panel) with role-based visibility
- **Full-Page Views** -- Admin, Org Manager, and Settings as full-page layouts (not modals)
- **Knowledge Visualization** -- Mermaid diagrams rendered inline for knowledge graph display
- **Conversation Persistence** -- Auto-save via Tauri plugin-store with debounced writes
- **Frameless Window** -- Custom title bar with drag regions, splash screen, native installer (NSIS)
- **Dark / Light / System Theme** -- Three theme modes with Tailwind CSS class strategy
- **Keyboard Shortcuts** -- Ctrl+Enter to send, command palette, configurable bindings
- **Context Panel** -- Token budget visualization, conversation compaction controls
- **Screenshot Blocks** -- Inline browser screenshot rendering from product search
- **Embed Mode** -- Standalone embed build for web integration (`EmbedApp.tsx`)
- **Neko Chill Mode** -- No-login local-agent surface: drive ACP agents (neko-core, Gemini CLI) as Tauri sidecars with streaming transcript, fail-closed permission gating, and locally persisted sessions (`src/neko-chill/`)

---

## Neko Chill Mode

A second shell-level mode (issue #886, spec `specs/731-neko-chill-mode/`) that
works entirely without a Wiii account: the desktop app becomes a client for
**local coding agents** speaking the Agent Client Protocol (ACP, JSON-RPC over
stdio), launched as sidecar processes from `src-tauri`.

- **Entry**: the `ModeGate` in `App.tsx` mounts `NekoChillApp` INSTEAD of the
  cloud app — auth/org/backend init can never run while the mode is active.
- **Agents**: neko-core (`neko acp`, v0.24.0+) and Gemini CLI
  (`gemini --experimental-acp`) are detected automatically.
- **Safety**: every agent side effect surfaces as an explicit approval card;
  unanswered requests fail closed; agent processes are killed on app exit and
  reaped after 30 idle minutes.
- **Persistence**: sessions and transcripts live in local app storage only
  (tauri plugin-store); restored sessions respawn a fresh agent process on the
  next prompt.
- **Architecture**: provider-agnostic `DriverEvent` contract
  (`src/neko-chill/drivers/types.ts`) — the ACP driver is golden-tested
  against recorded real-agent sessions
  (`src/__tests__/neko-chill/fixtures/`); a future Wiii-cloud driver
  implements the same contract.

---

## Tech Stack

| Technology | Version | Purpose |
|---|---|---|
| Tauri | v2 | Cross-platform desktop shell (Rust backend) |
| React | 18 | UI framework |
| TypeScript | 5.x | Type safety |
| Vite | 5.x | Build tool and dev server |
| Tailwind CSS | 3.4 | Utility-first styling |
| Zustand | 4.5 | State management (15 stores) |
| Immer | 11.x | Immutable state updates |
| Vitest | 1.6 | Testing framework (1857 tests) |
| Lucide React | 0.400 | Icon library |
| Motion | 12.x | Animation library |
| React Markdown | 9.x | Markdown rendering with GFM and syntax highlighting |
| Shiki | 1.x | Code syntax highlighting (IBM Plex Mono, dual-theme) |
| Rive (WebGL2) | 4.27 | Avatar animation runtime |

### Tauri Plugins (Rust)

| Plugin | Purpose |
|---|---|
| `tauri-plugin-store` | Persistent key-value storage |
| `tauri-plugin-http` | CORS-free HTTP requests |
| `tauri-plugin-dialog` | Native file/message dialogs |
| `tauri-plugin-shell` | System shell and URL opening |
| `tauri-plugin-notification` | Desktop notifications |

---

## Project Structure

```
wiii-desktop/
+-- src/
|   +-- api/                     # 17 API modules
|   |   +-- client.ts            # HTTP client (Tauri plugin-http / fetch fallback)
|   |   +-- sse.ts               # SSE parser for /chat/stream/v3
|   |   +-- chat.ts, organizations.ts, users.ts, admin.ts, living-agent.ts, soul-bridge.ts, ...
|   |   +-- types.ts             # Shared API types
|   |
|   +-- components/
|   |   +-- auth/                # Authentication UI (LoginScreen)
|   |   +-- chat/                # Chat experience (15+ components)
|   |   |   +-- ChatView.tsx, ChatInput.tsx, MessageBubble.tsx
|   |   |   +-- ThinkingBlock.tsx, ThinkingFlow.tsx, ThinkingTimeline.tsx
|   |   |   +-- PreviewGroup.tsx, ProductPreviewCard.tsx  # Product card carousel
|   |   |   +-- WelcomeScreen.tsx, ScreenshotBlock.tsx, SourceCitation.tsx
|   |   +-- layout/              # Application shell (9 components)
|   |   |   +-- AppShell.tsx, TitleBar.tsx, Sidebar.tsx
|   |   |   +-- PreviewPanel.tsx  # Product preview side panel
|   |   |   +-- FullPageView.tsx  # Shared full-page layout
|   |   +-- admin/               # System admin panel (7 tabs)
|   |   +-- org-admin/           # Org admin panel (4 tabs)
|   |   +-- settings/            # Settings (full-page, 4 tabs)
|   |   +-- living-agent/        # Living Agent dashboard (7 components)
|   |   |   +-- LivingAgentPanel.tsx, MoodIndicator.tsx, SkillTree.tsx
|   |   |   +-- JournalView.tsx, HeartbeatStatus.tsx, GoalsView.tsx, ReflectionsView.tsx
|   |   +-- soul-bridge/         # Soul Bridge monitor (3 components)
|   |   |   +-- SoulBridgePanel.tsx, PeerCard.tsx, EventTimeline.tsx
|   |   +-- common/              # Shared components (12+)
|   |       +-- MarkdownRenderer.tsx, MermaidDiagram.tsx, PermissionGate.tsx
|   |       +-- CommandPalette.tsx, ErrorBoundary.tsx, ...
|   |
|   +-- stores/                  # 15 Zustand stores
|   |   +-- settings-store.ts    # Server URL, API key, theme, user preferences
|   |   +-- chat-store.ts        # Conversations, messages, streaming state (largest)
|   |   +-- auth-store.ts        # JWT tokens, OAuth flow, login state
|   |   +-- org-store.ts         # Organizations, permissions, workspace, branding
|   |   +-- admin-store.ts       # System admin data (dashboard, flags, analytics, audit)
|   |   +-- org-admin-store.ts   # Org admin data (members, settings)
|   |   +-- ui-store.ts          # Sidebar, modals, layout, activeView routing
|   |   +-- connection-store.ts, domain-store.ts, avatar-store.ts
|   |   +-- character-store.ts, context-store.ts, living-agent-store.ts
|   |
|   +-- hooks/                   # Custom React hooks
|   |   +-- useSSEStream.ts      # SSE V3 stream consumption with StreamBuffer
|   |   +-- useAutoScroll.ts, useKeyboardShortcuts.ts
|   |
|   +-- lib/                     # Utility modules (28+)
|   |   +-- avatar/              # Avatar engine (18 modules)
|   |   +-- embed-auth.ts, embed-bridge.ts, secure-token-storage.ts
|   |   +-- org-branding.ts, storage.ts, stream-buffer.ts, theme.ts, ...
|   |
|   +-- __tests__/               # 67 test files, 1857 Vitest tests
|   +-- EmbedApp.tsx             # Standalone embed build
|
+-- src-tauri/                   # Rust backend
|   +-- src/lib.rs, commands/    # Tauri app setup and IPC commands
|   +-- capabilities/            # Tauri v2 capability permissions
|   +-- tauri.conf.json          # Tauri configuration
|
+-- docs/                        # Desktop-local design and asset specs
+-- scripts/                     # Utility scripts (embed build, screenshots)
+-- vite.config.ts, tailwind.config.ts, tsconfig.json
```

### Local Conventions

- Keep desktop-specific documentation in `wiii-desktop/docs/`.
- Keep one-off screenshot automation in `wiii-desktop/scripts/screenshots/`.
- Temporary screenshot output should go to `../docs/assets/screenshots/tmp/`, not the app root.
- Treat `dist-embed/` as generated embed output for `/embed/`.
- Refresh `dist-embed/` only via `npm run build:embed` or `./scripts/build-web.sh`; never hand-edit hashed assets.
- `dist-embed/` is gitignored and not part of the production deployment contract.
- Production deployment uses CI-built images that already contain embed assets.
- Keep `dist-embed/` only as a local verification artifact.

---

## Quick Start

### Prerequisites

- [Node.js](https://nodejs.org/) >= 18
- [Rust](https://rustup.rs/) (for Tauri builds)
- [Tauri CLI prerequisites](https://v2.tauri.app/start/prerequisites/)

### Install Dependencies

```bash
cd wiii-desktop
npm install
```

### Development (Web Only)

Starts the Vite dev server at `http://localhost:1420` -- useful for rapid UI iteration without the Rust backend:

```bash
npm run dev
```

### Development (Full Tauri App)

Launches the complete desktop application with Rust backend, splash screen, and native features:

```bash
npx tauri dev
```

### Build for Production

Produces an NSIS installer for Windows:

```bash
npx tauri build
```

The installer is output to `src-tauri/target/release/bundle/nsis/`.

### Build the Embed Bundle

Builds the standalone iframe app served at `/embed/`:

```bash
npm run build:embed
```

For web deployment workflows, use:

```bash
./scripts/build-web.sh
```

That script builds both `dist/` and `dist-embed/`. It copies only `dist/` into `maritime-ai-service/nginx/html/`; production uses CI-built images that already contain `/embed/` assets.

### Run Tests

```bash
npx vitest run          # All 1857 tests
npx vitest run --ui     # Interactive test UI
npx vitest run --coverage  # With coverage report
```

---

## Architecture

### State Management

15 Zustand stores manage application state, with Tauri plugin-store providing persistent storage:

| Store | Key Responsibilities |
|---|---|
| `settings-store` | Server URL, API key, theme, streaming version, user display preferences |
| `chat-store` | Conversations, messages, streaming state, content blocks (largest store) |
| `auth-store` | JWT access/refresh tokens, OAuth flow state, login/logout |
| `org-store` | Organizations list, active workspace, permissions, org branding config |
| `admin-store` | System admin dashboard, feature flags, analytics, audit events |
| `org-admin-store` | Org-level member management, settings |
| `ui-store` | Sidebar visibility, modal states, layout preferences, activeView routing |
| `connection-store` | Backend connectivity status, health check results |
| `domain-store` | Available domain plugins, active domain selection |
| `avatar-store` | Avatar emotion state, animation triggers, expression config |
| `character-store` | AI character traits, personality blocks |
| `context-store` | Token budget info, utilization percentage, compaction state |
| `living-agent-store` | Living Agent soul status, 4D emotional state, skills, goals, reflections, journal, heartbeat |

Persistence strategy:
- **Immediate persist**: Conversation create/delete/rename, stream finalize, stream error
- **Debounced persist** (2s): Message additions during active streaming
- **Storage adapter**: `lib/storage.ts` uses `@tauri-apps/plugin-store` in Tauri, falls back to `localStorage` in browser

### Streaming (SSE V3)

The app consumes Server-Sent Events from the `/chat/stream/v3` endpoint:

| Event | Purpose |
|---|---|
| `status` | Pipeline progress -- node transitions (e.g., "Routing", "Searching knowledge base") |
| `thinking_start` / `thinking_end` | Thinking block lifecycle |
| `thinking_delta` | AI reasoning content -- rendered in ThinkingBlock with markdown |
| `tool_call` / `tool_result` | Tool invocation and result events -- displayed as inline cards |
| `action_text` | Phase transition text between thinking phases |
| `answer_delta` | Token-by-token response text -- streamed into AnswerBlock |
| `preview` | Product preview card data -- real-time during search |
| `curated_products` | LLM-selected top products after search completion |
| `done` | Stream completion with metadata (sources, timing) |
| `error` | Stream error with message |

The `useSSEStream` hook manages the SSE connection lifecycle, while `StreamBuffer` handles token buffering and ordered delivery.

### View Routing

Full-page views managed via `ui-store.activeView`:

| View | Component | Description |
|---|---|---|
| `chat` | `ChatView` | Default chat interface |
| `admin` | `AdminPanel` | 7-tab system admin (dashboard, flags, analytics, audit, GDPR, users, orgs) |
| `org-admin` | `OrgManagerPanel` | 4-tab org admin (members, settings, branding, permissions) |
| `settings` | `SettingsView` | 4-tab settings (connection, user, preferences, soul) |

### Authentication

Three authentication modes, resolved in order:

1. **Google OAuth** -- Desktop deep link flow (`com.wiii-lab.wiii-desktop://oauth/callback`). JWT access + refresh token pair stored in `secure-token-storage.ts`.
2. **LMS Token Exchange** -- HMAC-signed backend-to-backend flow for LMS integration.
3. **API Key** -- Header-based authentication (`X-API-Key`) for development and testing.

### Avatar System

Living, expressive character powered by a multi-layer animation engine:

- **Face geometry** -- Procedural SVG face with blob shapes and simplex noise
- **Emotion engine** -- Maps AI states (thinking, answering, idle) to emotional expressions
- **Manga indicators** -- Sweat drops, sparkles, emphasis marks for expressive reactions
- **Micro-reactions** -- Subtle animations (blinks, eye moisture, gaze tracking)
- **Rive integration** -- Hardware-accelerated WebGL2 animation
- **Mood themes** -- Dynamic color palette changes based on emotional state

---

## Testing

```bash
npx vitest run                              # All 1857 tests
npx vitest run src/__tests__/chat-store*    # Specific test file
npx vitest run src/__tests__/admin*         # Admin panel tests
npx vitest run --coverage                   # With coverage report
npx vitest run --ui                         # Interactive browser UI
```

**1857 tests** across **67 test files** -- all passing (as of Mar 1, 2026).

Test coverage areas:
- Store logic (chat, auth, org, settings, context, memory, avatar, living-agent, admin, org-admin)
- SSE streaming, stream buffer, preview card rendering
- Thinking block lifecycle, multi-phase thinking flow
- Avatar emotion engine, animation system
- Living Agent types, store, and API module structure
- Organization UI consistency, admin panels
- Authentication flows (OAuth, embed auth, identity SSOT)
- Product carousel, screenshot rendering
- Conversation persistence, grouping, settings persistence

---

## Configuration

### Tauri Configuration (`src-tauri/tauri.conf.json`)

| Setting | Value |
|---|---|
| Product name | `Wiii` |
| Identifier | `com.wiii-lab.wiii-desktop` |
| Window size | 1200 x 800 (min 800 x 600) |
| Decorations | `false` (frameless, custom title bar) |
| Bundle target | NSIS (Windows installer) |
| Installer languages | Vietnamese, English |
| Copyright | Copyright 2026 The Wiii Lab |

### Environment Variables

| Variable | Purpose |
|---|---|
| `VITE_API_URL` | Backend server URL (default: `http://localhost:8000`) |
| `VITE_API_KEY` | API key for authentication |

---

## Scripts

| Script | Command | Description |
|---|---|---|
| `npm run dev` | `vite` | Start Vite dev server at localhost:1420 |
| `npm run build` | `tsc && vite build` | TypeScript check + production build |
| `npm run preview` | `vite preview` | Preview production build locally |
| `npm run test` | `vitest` | Run tests in watch mode |
| `npm run test:ui` | `vitest --ui` | Interactive test UI in browser |
| `npm run lint` | `eslint src/ --ext .ts,.tsx` | Lint TypeScript source |
| `npx tauri dev` | -- | Full Tauri app development |
| `npx tauri build` | -- | Build production installer |

---

## License

Proprietary -- All rights reserved.

*Wiii by The Wiii Lab*
