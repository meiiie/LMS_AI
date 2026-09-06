# Wiii

<p align="center">
  <img src="docs/assets/brand/neko-family-v1/social/wiii-readme-banner.png" alt="Wiii — a durable AI workbench for people and agents" width="100%" />
</p>

<p align="center">
  <a href="https://github.com/meiiie/wiii/actions/workflows/test-backend.yml"><img src="https://github.com/meiiie/wiii/actions/workflows/test-backend.yml/badge.svg" alt="Backend tests" /></a>
  <a href="https://github.com/meiiie/wiii/actions/workflows/test-desktop.yml"><img src="https://github.com/meiiie/wiii/actions/workflows/test-desktop.yml/badge.svg" alt="Desktop tests" /></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/meiiie/wiii" alt="AGPL-3.0-only license" /></a>
</p>

Wiii is an open-source Agentic Development Environment for durable projects,
tasks, local and cloud agents, code, tools, memory, artifacts, evidence and
permission-aware integrations. It is built by **The Wiii Lab** and designed to
stay useful across different models, runtimes, knowledge domains, and host
applications.

Vietnamese is the primary product language today. The architecture itself is
provider- and domain-extensible.

## What Wiii brings together

- **Durable work** — conversations, provider sessions, files, artifacts, and
  recovery state survive process replacement and app restarts.
- **Composable runtimes** — use Neko Core, Gemini CLI, Codex App Server, or a
  managed Wiii Service without changing the Workbench interaction model.
- **Files + live artifacts** — inspect project files, follow edits, and open
  code, Markdown, HTML previews, diagrams, and generated visual work beside the
  conversation.
- **Permission-aware tools** — tool calls and host mutations remain visible,
  reviewable, and gated before side effects.
- **Connected context** — RAG, semantic memory, MCP, embeds, documents, browser
  surfaces, and external applications meet behind explicit contracts.
- **Organization controls** — authentication, tenant context, feature policy,
  audit paths, and deployment controls support managed environments.

LMS support remains an important Wiii Connect adapter. It is one integration,
not the product boundary.

## Product map

| Layer | Responsibility |
| --- | --- |
| **Wiii ADE** | Project, Task, Run, code, review, evidence and human decisions |
| **Neko Chill** | Provider-neutral agent fabric and local execution lifecycle |
| **Wiii Service** | Optional managed/data plane for cloud, sync, Knowledge, Memory, policy and audit |
| **Wiii Core** | API, orchestration, streaming, providers, tools, and retrieval |
| **Wiii Living** | continuity, memory, identity, goals, and long-running agent state |
| **Wiii Host** | desktop, embed, browser, LMS, and future host applications |
| **Wiii Connect** | ACP, MCP, documents, OAuth apps, and capability contracts |
| **Wiii Org** | identity, tenancy, policy, admin, and audit controls |
| **Wiii Data** | PostgreSQL/pgvector, optional graph context, caches, and object storage |

The repository contains two primary runtime surfaces:

- [`maritime-ai-service/`](maritime-ai-service/) — FastAPI backend,
  orchestration, RAG, memory, integrations, deployment assets, and tests.
- [`wiii-desktop/`](wiii-desktop/) — the shared React Workbench plus its Tauri
  desktop host, hosted-web target, local runtimes, artifacts, and embeds.

Shared architecture, governance, research, and brand sources live in
[`docs/`](docs/).

The work/execution boundary is documented in
[Wiii ADE and Neko Agent Fabric](docs/architecture/WIII_ADE_AND_NEKO_AGENT_FABRIC.md).

## Quick start

### Desktop distribution status

Wiii does not yet have a public stable desktop release. `VERSION` identifies
the coordinated release target in source; it does not mean a matching tag or
download has been published. Maintainer-triggered workflow artifacts are
unsigned evaluation candidates, not stable packages.

When the governed release gates pass, stable packages will be published on the
[Wiii Releases page](https://github.com/meiiie/wiii/releases) with this matrix:

| Platform | Package |
| --- | --- |
| Windows x64 | NSIS setup `.exe` |
| Debian/Ubuntu x64 | `.deb` |
| Other supported Linux x64 | portable `.AppImage` |
| macOS Apple Silicon | ARM64 `.dmg` |
| macOS Intel | x64 `.dmg` |

Do not treat a CI artifact or a locally built installer as a stable release.
Published packages must include an adjacent `.sha256` file. Official Windows
releases may be explicitly unsigned; their filenames and manifests disclose
`unsigned` instead of claiming Authenticode publisher identity. Signed Windows
builds require certificate verification. macOS packages are currently ad-hoc signed
but not Apple-notarized, so their filenames explicitly include `unnotarized`;
see the [release standard](docs/releases/WIII_RELEASE_STANDARD.md) for the exact
trust contract.

### Desktop workbench

Prerequisites: Node.js 18+, Rust, and the
[Tauri v2 prerequisites](https://v2.tauri.app/start/prerequisites/).

```bash
cd wiii-desktop
npm install
npm run tauri -- dev
```

For frontend-only iteration:

```bash
cd wiii-desktop
npm run dev
```

### Backend

```bash
cd maritime-ai-service
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
docker compose up -d postgres neo4j minio valkey
alembic upgrade head
uvicorn app.main:app --reload
```

Use `copy .env.example .env` instead of `cp` in Command Prompt. Configure only
your own development secrets; never commit `.env` files.

## Build and verify

```bash
# Desktop
cd wiii-desktop
npx vitest run
npx tsc --noEmit
npm run build:embed
# Package for the host operating system:
npm run tauri -- build --bundles nsis
# Linux: npm run tauri -- build --bundles deb,appimage
# macOS: npm run tauri -- build --bundles dmg

# Backend
cd ../maritime-ai-service
pytest tests/unit/ -p no:capture --tb=short -q
ruff check app/ --select=E9,F63,F7
```

Tauri packages are generated under
`wiii-desktop/src-tauri/target/<target?>/release/bundle/`. Generated `dist*`,
target, coverage, and local screenshot output must stay out of source control.

## Documentation

- [Project mental model](docs/WIII_PROJECT_MENTAL_MODEL.md)
- [Codebase map](docs/architecture/WIII_CODEBASE_MAP.md)
- [Workbench identity and durable ACP boundary](docs/architecture/WIII_WORKBENCH_IDENTITY_AND_ACP.md)
- [Unified Workbench and host boundary](docs/architecture/WIII_UNIFIED_WORKBENCH.md)
- [Wiii Connect architecture](docs/architecture/wiii-connect/README.md)
- [Desktop engineering guide](wiii-desktop/README.md)
- [Backend engineering guide](maritime-ai-service/README.md)
- [Release standard](docs/releases/WIII_RELEASE_STANDARD.md)
- [Neko brand system](docs/assets/brand/neko-family-v1/README.md)

Wiii is active product and research engineering. Contracts that affect
persistence, permissions, integrations, or user data should be treated as
versioned interfaces, not informal implementation details.

## Contributing and security

Read [`AGENTS.md`](AGENTS.md), the issue templates, and
[`docs/operations/WIII_GITHUB_GOVERNANCE.md`](docs/operations/WIII_GITHUB_GOVERNANCE.md)
before broad changes. Open a focused issue, document risk and rollback for
high-impact paths, and include visual evidence for user-facing work.

Please report security-sensitive issues privately to the maintainers rather
than publishing credentials, private data, or exploit details in a public
issue.

## License

Wiii's core product is available under **AGPL-3.0-only** or a separate
commercial agreement. Independently implemented code under `sdk/` is
**Apache-2.0**. The Wiii name and branding are not granted by either code
license. See [LICENSING.md](LICENSING.md),
[COMMERCIAL-LICENSE.md](COMMERCIAL-LICENSE.md), and
[TRADEMARKS.md](TRADEMARKS.md).
