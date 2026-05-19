# Wiii

![Wiii AI platform banner showing document citations, LMS preview, voice, and simulation workflows](docs/assets/brand/wiii-readme-banner-2026-05-19.png)

Wiii is a monorepo for an AI platform that combines a FastAPI backend, a Tauri desktop client, iframe/embed delivery, multi-agent orchestration, retrieval and memory pipelines, LMS integrations, and multi-tenant organization support.

This repository is optimized for ongoing product engineering, not as a minimal sample. Start here for the repository shape, the current deployment model, the main architecture documents, and the fastest local entry points.

## Monorepo Layout

- `maritime-ai-service/`: FastAPI backend, orchestration, integrations, data access, deployment assets, tests
- `wiii-desktop/`: Tauri desktop app, React frontend, embed app, frontend scripts, desktop-local docs
- `docs/`: repository-level documentation, plans, diagrams, screenshots, and doc indexes
- `Documents/`: supporting reference material and vendor research
- `tools/`: utilities, fixtures, and one-off helpers

Agent instructions now start from `AGENTS.md`, `.agents/skills/`, GitHub issues/PRs, and `docs/operations/`. Legacy local scratch folders such as `.claude/` and `.Codex/` are intentionally ignored and should not be committed.

## Architecture At A Glance

Primary runtime flow:

1. Client request enters the backend through REST, SSE, WebSocket, or LMS/embed integration.
2. Middleware applies request correlation, organization context, auth, and rate limiting.
3. `ChatOrchestrator` resolves session state, domain context, and request normalization.
4. The WiiiRunner multi-agent pipeline routes work to RAG, tutor, memory, direct-response, Code Studio, product search, or other feature-gated tool paths.
5. Retrieval, tools, LMS data, semantic memory, and optional browser or MCP integrations contribute context.
6. The response is synthesized back to JSON or SSE V3 events for the desktop app and embed clients.

Core subsystems:

- FastAPI API layer with organization-aware middleware and auth
- WiiiRunner multi-agent orchestration with RAG, tutor, memory, direct-response, and feature-gated tool paths
- Retrieval stack built on PostgreSQL, pgvector, sparse search, and optional Neo4j graph context
- LMS bridge with HMAC token exchange, webhook ingestion, and dashboard/data pull tools
- Tauri desktop client with Zustand state, SSE V3 streaming, full-page admin surfaces, and embed mode
- Production delivery via immutable app and nginx images published to GHCR

## Quick Start

### Backend

```bash
cd maritime-ai-service
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
docker compose up -d postgres neo4j minio valkey
alembic upgrade head
uvicorn app.main:app --reload
```

### Desktop

```bash
cd wiii-desktop
npm install
npm run dev
```

### Full Desktop App

```bash
cd wiii-desktop
npx tauri dev
```

### Embed Bundle For Local Verification

```bash
cd wiii-desktop
npm run build:embed
```

`wiii-desktop/dist-embed/` is now generated, gitignored output. It remains useful for local verification, but it is no longer part of the production deployment contract.

## Build And Test

### Backend

```bash
cd maritime-ai-service
set PYTHONIOENCODING=utf-8 && pytest tests/unit/ -p no:capture --tb=short -q
```

### Desktop

```bash
cd wiii-desktop
npx vitest run
npx tsc --noEmit
```

## Deployment Model

Production now uses CI-built immutable images for both the backend app and nginx layer.

Current deployment flow:

1. Push to `main` triggers `.github/workflows/build-production-images.yml`.
2. CI builds `wiii-desktop/dist-embed/` and `wiii-desktop/dist-pointy/` as build artifacts.
3. CI builds and publishes:
   - `ghcr.io/meiiie/wiii-app:*` (legacy `ghcr.io/meiiie/lms-ai-app:*` is still pushed for one release window)
   - `ghcr.io/meiiie/wiii-nginx:*` (legacy `ghcr.io/meiiie/lms-ai-nginx:*` is still pushed for one release window)
4. The app image serves embed assets from `/app-embed`.
5. The nginx image serves embed assets from `/usr/share/nginx/embed` and the Pointy host bridge from `/usr/share/nginx/pointy`.
6. Production deploy pulls tagged images instead of rebuilding frontend assets on the host.

Operational consequence:

- production no longer depends on `wiii-desktop/dist-embed/` being committed or present in the server checkout
- rollback is image-tag based rather than “rebuild on host” based
- `/embed/` and `/pointy/wiii-pointy.umd.js` verification belongs in post-deploy smoke testing
- Pointy Voice uses the backend ElevenLabs proxy at `/api/v1/voice/*`; raw ElevenLabs keys stay in production secrets or encrypted runtime settings, never in frontend storage

Current release controls:

- `docs/operations/WIII_PRODUCT_RELEASE_RUNBOOK.md`

## Documentation Map

Repository-level entry points:

- `docs/README.md`: documentation layout and top-level doc map
- `maritime-ai-service/docs/architecture/SYSTEM_ARCHITECTURE.md`: authoritative architecture overview and component deep dive
- `maritime-ai-service/docs/architecture/SYSTEM_FLOW.md`: detailed technical request and streaming flow
- `maritime-ai-service/docs/integration/WIII_LMS_INTEGRATION.md`: LMS contract and integration architecture
- `maritime-ai-service/scripts/deploy/README.md`: production deployment runbook
- `maritime-ai-service/README.md`: backend technical entry point
- `wiii-desktop/README.md`: desktop technical entry point

## Repository Conventions

- Keep durable, shared documentation in `docs/`, not at the repository root.
- Keep screenshots and documentation assets under `docs/assets/`.
- Keep desktop-only docs under `wiii-desktop/docs/`.
- Keep generated build outputs out of git unless they are intentional release artifacts.
- Do not hand-edit hashed files inside build output directories.

## License

See `LICENSE` for repository licensing terms.
