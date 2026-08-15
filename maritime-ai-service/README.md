# Wiii Core service

This directory contains Wiii's FastAPI runtime. It serves chat and streaming,
model/tool orchestration, retrieval, memory, organizations, host actions, Wiii
Connect, and production health controls. LMS functionality is implemented as a
Wiii Connect adapter; it does not define the service architecture.

## Read first

- [System architecture](docs/architecture/SYSTEM_ARCHITECTURE.md)
- [Request and streaming flow](docs/architecture/SYSTEM_FLOW.md)
- [API guide](docs/api/README.md)
- [Wiii Connect LMS adapter](docs/integration/WIII_CONNECT_LMS_ADAPTER.md)
- [Local development](docs/LOCAL_DEV.md)
- [Deployment](scripts/deploy/README.md)

## Local start

```powershell
cd maritime-ai-service
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
docker compose up -d postgres neo4j minio valkey
alembic upgrade head
uvicorn app.main:app --reload
```

Configure your own development credentials in `.env`; never commit that file.
The API normally listens at `http://127.0.0.1:8000`, with v1 routes under
`/api/v1`.

## Ownership map

| Path | Responsibility |
| --- | --- |
| `app/api/v1/` | HTTP, SSE, admin, organization, host, connector, and adapter routes |
| `app/services/` | Request lifecycle, orchestration, model policy, output, and background work |
| `app/engine/runtime/` | Wiii-owned execution contracts and lanes |
| `app/engine/multi_agent/` | Planning, tool rounds, runtime ledgers, document and visual flows |
| `app/engine/wiii_connect/` | External provider/action planning and execution policy |
| `app/engine/semantic_memory/` | Memory lifecycle, retrieval, maintenance, and provenance |
| `app/auth/`, `app/core/` | Identity, authorization, tenant context, settings, middleware |
| `app/repositories/`, `alembic/` | Data access and schema migrations |
| `tests/` | Unit, integration, property, security, and contract tests |

## Verification

During iteration, run the focused test module for the changed contract. Before
merging a backend-wide change:

```powershell
pytest tests/unit/ -p no:capture --tb=short -q
ruff check app/ --select=E9,F63,F7
python -m compileall -q app
```

Changes to live-provider claims must also update or run the appropriate guarded
runtime evidence probe. Test fixtures prove behavior and schema; they do not
prove a real external service accepted a request.
