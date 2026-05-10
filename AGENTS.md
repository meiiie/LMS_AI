# AGENTS.md

Status: Active

Owner: Project leadership

Last updated: 2026-04-27

Applies to: Codex, Claude Code, CodeRabbit, and other AI-assisted engineering agents working in this repository.

This file is the repository-level instruction source for Wiii. Codex also reads `AGENTS.md` files during GitHub code review, so keep the `## Review guidelines` section current and specific.

## Repository Context

Wiii is a production-oriented multi-domain agentic RAG platform with a FastAPI backend, WiiiRunner orchestration, PostgreSQL/pgvector, optional Neo4j graph context, LMS integration, and a Tauri v2 desktop client. LangGraph is no longer an active runtime dependency; remaining LangGraph references should be treated as historical, compatibility, or cleanup-tracking context unless a specific file proves otherwise.

Primary areas:

- `maritime-ai-service/`: FastAPI backend, auth, organization context, multi-agent orchestration, RAG, memory, LMS integration, deployment assets, tests.
- `wiii-desktop/`: Tauri v2 desktop app, React 18, TypeScript, Zustand stores, SSE V3 streaming UI, embed app, frontend tests.
- `docs/`: repository-level architecture, operations, governance, plans, and assets.
- `.github/`: issue templates, PR template, CODEOWNERS, GitHub Actions, Dependabot, and review automation.

Legacy local agent folders such as `.claude/` and `.Codex/` are not canonical and must not be committed. Canonical governance, architecture, and cleanup truth lives in `AGENTS.md`, `docs/`, `.github/`, `.agents/skills/`, and active GitHub issues.

## Operating Rules

- Follow `docs/operations/WIII_GITHUB_GOVERNANCE.md` for issue, branch, PR, review, and merge workflow.
- Use `docs/operations/WIII_SPEC_KIT_WORKFLOW.md` and `.specify/memory/constitution.md` for architecture-sensitive, ambiguous, multi-agent, or multi-phase work.
- Use `codex/` for Codex-authored branches unless a maintainer explicitly requests a different prefix.
- Open or link an issue for non-trivial work before opening a PR.
- Keep changes scoped. Do not mix cleanup, docs, runtime behavior, migrations, and UI refactors unless the issue explicitly requires it.
- Never commit secrets, tokens, real private data, `.env*` files, local caches, dependency folders, logs, screenshots from temporary runs, or generated build output.
- Do not hand-edit hashed or generated assets such as `wiii-desktop/dist*`, coverage output, or dependency lock artifacts unless the task is specifically about those artifacts.
- Preserve Vietnamese-first user-facing copy in UI, prompts, and error messages unless the surrounding product surface is intentionally English.
- For frontend-visible changes, include screenshots or a clear reason why visual evidence is not applicable.
- For backend, auth, memory, tenant isolation, migration, provider/runtime, MCP, or deployment changes, include explicit risk and rollback notes.

## Verification Commands

Choose the smallest meaningful verification set for the changed paths and report exact commands plus results in the PR.

Backend:

```bash
cd maritime-ai-service
set PYTHONIOENCODING=utf-8 && pytest tests/unit/ -p no:capture --tb=short -q
ruff check app/ --select=E9,F63,F7
```

Desktop:

```bash
cd wiii-desktop
npx vitest run
npx tsc --noEmit
npm run build:embed
```

Repository hygiene:

```bash
git diff --check
git status --short
```

## Review guidelines

- Treat auth, JWT, OAuth, LMS token exchange, organization context, tenant isolation, semantic memory, long-term memory, MCP/tool execution, provider routing, migrations, and GitHub automation as high-risk surfaces.
- Flag P0/P1 issues when a change can expose private data, cross tenant boundaries, bypass authorization, corrupt persistent memory, break streaming contracts, weaken deployment safety, or make rollback unclear.
- For `maritime-ai-service/app/auth/**`, verify identity linking, verified-email gates, refresh token behavior, timing-safe secret comparisons, audit logging, and backwards compatibility for desktop and LMS flows.
- For `maritime-ai-service/app/core/**`, verify configuration defaults, feature flags, org middleware, rate limiting, fail-closed behavior, and production safety.
- For `maritime-ai-service/app/engine/**`, verify routing correctness, source propagation, memory/tool boundaries, streaming parity, structured output robustness, and fallback behavior.
- For `maritime-ai-service/app/repositories/**` and RAG paths, verify tenant/org filtering, query safety, citation integrity, confidence thresholds, and no accidental broad data reads.
- For `maritime-ai-service/alembic/**`, require a migration safety story: compatibility with running services, rollback or recovery notes, no destructive operation without explicit justification, and backfill plan when data shape changes.
- For `wiii-desktop/src/**`, verify SSE V3 event handling, persisted Zustand state, auth refresh, Tauri HTTP/fetch fallback parity, accessibility, responsive behavior, and no accidental loss of conversation state.
- For embed changes, verify `npm run build:embed` when practical and ensure production still uses CI-built immutable images rather than committed `dist-embed/` output.
- For `.github/**`, verify workflow permissions, trigger paths, required checks, token exposure, concurrency, and whether a governance change can block emergency recovery.
- For docs/governance changes, verify they match current repository truth and do not introduce stale sprint-report language, vague ownership, or unverifiable process.
- Do not treat CodeRabbit or Codex Review as replacements for human ownership. Automated findings must be resolved, deferred with rationale, or explicitly marked not applicable before merge.
- Prefer narrow, actionable review comments with file and line references. Avoid broad style commentary unless it creates correctness, security, maintainability, accessibility, or operational risk.

<!-- SPECKIT START -->
For Wiii Spec Kit workflow context, read `.specify/memory/constitution.md`
and `docs/operations/WIII_SPEC_KIT_WORKFLOW.md`. When a Spec Kit feature is
active, also read that feature's `specs/<feature>/plan.md` and
`specs/<feature>/tasks.md`.
<!-- SPECKIT END -->
