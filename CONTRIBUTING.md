# Contributing to Wiii

Thank you for your interest in contributing to Wiii! This guide will help you get started.

Wiii uses a dual-licensing model. Before a contribution to the core can be
merged, its licensing authority must satisfy
[CONTRIBUTOR-LICENSE-POLICY.md](CONTRIBUTOR-LICENSE-POLICY.md). Apache SDK
contributions are accepted only inside the explicit `sdk/` boundary.

## Development Setup

### Prerequisites

- Python 3.11+
- Node.js 20+ (for desktop app)
- Docker & Docker Compose (for databases)
- Rust toolchain (for Tauri desktop builds)

### Backend Setup

```bash
cd maritime-ai-service
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Configure your API keys

# Start database services
docker compose up -d postgres neo4j minio

# Run the server
uvicorn app.main:app --reload
```

### Desktop Setup

```bash
cd wiii-desktop
npm install
npm run dev          # Vite dev server
npx tauri dev        # Full Tauri app
```

## Branch Naming

| Prefix | Use |
|--------|-----|
| `feature/` | New features (`feature/add-voice-input`) |
| `fix/` | Bug fixes (`fix/streaming-disconnect`) |
| `docs/` | Documentation (`docs/api-guide`) |
| `refactor/` | Code refactoring (`refactor/memory-store`) |
| `test/` | Test additions (`test/grader-edge-cases`) |

## Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]
```

**Types**: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`

**Examples**:
```
feat(memory): add importance-aware eviction
fix(streaming): prevent duplicate answer events
docs(api): update authentication guide
test(rag): add corrective RAG edge cases
```

## Pull Request Process

1. **Fork** the repository and create your branch from `main`
2. **Write tests** for any new functionality
3. **Run the test suite** and ensure all tests pass:
   ```bash
   # Backend (must pass 10059+ tests)
   cd maritime-ai-service
   pytest tests/unit/ -v -p no:capture --tb=short

   # Desktop (must pass 1860+ tests)
   cd wiii-desktop
   npx vitest run
   ```
4. **Lint your code**:
   ```bash
   ruff check app/ --select=F401,F841
   ```
5. **Open a PR** with a clear description of the changes
6. **Respond to review feedback** promptly

## Code Style

### Python (Backend)

- **Formatter/Linter**: ruff (configured in `pyproject.toml`)
- **Type hints**: Use throughout, especially for function signatures
- **Async**: Use `async/await` for all I/O operations
- **Imports**: Group as stdlib → third-party → local, sorted alphabetically
- **Docstrings**: For public APIs; skip for obvious internal functions

### TypeScript (Desktop)

- **Framework**: React 18 with functional components and hooks
- **State**: Zustand stores (no Redux, no Context API for global state)
- **Styling**: Tailwind CSS utility classes
- **Testing**: Vitest + jsdom

### General

- **Language**: Vietnamese-first for all user-facing text (UI, prompts, error messages)
- **Config**: Use Pydantic Settings + `.env` — never hardcode secrets
- **Feature flags**: Gate new features behind settings flags in `app/core/config.py`
- **Lazy imports**: Use inside function bodies for optional dependencies

## Testing Requirements

- All PRs must include tests for new functionality
- Backend test count must not decrease (currently 10059+)
- Desktop test count must not decrease (currently 1860+)
- Windows compatibility: use `-p no:capture` and `PYTHONIOENCODING=utf-8`

## Architecture Guidelines

- **Domain plugins**: New domains go in `app/domains/` with a `domain.yaml`
- **LLM calls**: Use `get_llm_deep/moderate/light()` from `app.engine.llm_pool`
- **Database access**: Via repository pattern in `app/repositories/`
- **Error handling**: Use typed exceptions from `app/core/exceptions.py`
- **Security**: Never expose `str(e)` in HTTP responses; use `hmac.compare_digest` for secrets

## Getting Help

- Open an [issue](https://github.com/meiiie/wiii/issues) for bugs or feature requests
- Check existing issues before creating new ones
- Use issue templates for consistent reporting
