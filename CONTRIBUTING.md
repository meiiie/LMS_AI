# Contributing to Wiii

Wiii is an open AI workbench spanning a FastAPI runtime, a React/Tauri desktop
application, local ACP agents, memory, tools, artifacts, and governed external
adapters. Contributions should preserve those boundaries and keep failures
inspectable.

Wiii uses a dual-licensing model. Before a contribution to the core can be
merged, its licensing authority must satisfy
[CONTRIBUTOR-LICENSE-POLICY.md](CONTRIBUTOR-LICENSE-POLICY.md). Apache SDK
contributions are accepted only inside the explicit `sdk/` boundary.

## Before coding

1. Read [AGENTS.md](AGENTS.md), the
   [project mental model](docs/WIII_PROJECT_MENTAL_MODEL.md), and the relevant
   subsystem guide.
2. Search open and closed issues.
3. Open or claim a focused issue for non-trivial work. Record scope,
   acceptance, risk, verification, and rollback.
4. Create a branch from current `main`:
   - people: `<kind>/<issue>-<slug>`;
   - coding agents: `codex/<issue>-<kind>-<slug>`.

Typical kinds are `feat`, `fix`, `docs`, `refactor`, `test`, `ci`, and `chore`.
Do not mix unrelated cleanup into a product change.

## Development setup

Prerequisites:

- Python 3.11+
- Node.js 22
- Rust stable and the Tauri v2 platform prerequisites
- Docker with Compose for local services

Backend:

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

Desktop:

```powershell
cd wiii-desktop
npm ci
npm run tauri -- dev
```

Use the equivalent activation/copy commands on macOS or Linux. Configure only
your own credentials and never commit `.env`, certificates, tokens, session
stores, or local database files.

## Engineering rules

- Put authorization, ownership, approval, and tenant enforcement on the server;
  UI gating is not a security boundary.
- Record a mutation before execution. An interrupted unconfirmed mutation is
  `unknown_outcome` and must not be replayed automatically.
- Keep provider secrets and backend-owned selectors out of model-facing tool
  schemas, logs, and evidence.
- Preserve ordered event/session semantics across desktop, HTTP, SSE, ACP, and
  provider boundaries.
- Treat LMS and other external systems as Wiii Connect adapters, not special
  global architecture.
- Add migrations for persisted schema changes and document rollout/rollback.
- Prefer focused changes and existing abstractions over speculative layers.

## Verification

Run the smallest focused tests while iterating, then the owning surface's full
gate before requesting review.

```powershell
# Repository contracts and versions
python tools/wiii_self_harness/run_wiii_self_harness.py --profile pr
python tools/release/wiii_release.py check

# Backend
cd maritime-ai-service
pytest tests/unit/ -p no:capture --tb=short -q
ruff check app/ --select=E9,F63,F7

# Desktop
cd ../wiii-desktop
npm test -- --run
npx tsc --noEmit
npm run build:embed
cargo check --manifest-path src-tauri/Cargo.toml
```

Add focused security/adversarial tests for auth, tenancy, memory, external
actions, migrations, and filesystem behavior. UI changes require a screenshot
or recording. Live external claims require a guarded runtime evidence artifact;
a mock proves a contract, not provider availability.

## Commits and pull requests

Use a concise Conventional Commit title, for example:

```text
feat(neko): add durable workspace file replay
fix(connect): block reuse of consumed approval
docs(release): define signed stable channel
```

The pull request must link its issue, declare scope/non-scope, list exact
verification results, identify risks and rollback, and remain within the
[reviewability gate](docs/operations/WIII_GITHUB_GOVERNANCE.md). Keep generated
build output out of Git.

Changes to `VERSION`, release workflow, signing, package/bundle identifiers, or
public artifacts must follow the
[Wiii Release Standard](docs/releases/WIII_RELEASE_STANDARD.md).

## Review and merge

Resolve required checks and review findings. Do not self-approve protected work
or bypass branch protection merely to finish faster. Squash merge is preferred
when it preserves a clear issue-linked history.

For help choosing an issue type or support channel, see [SUPPORT.md](SUPPORT.md).
