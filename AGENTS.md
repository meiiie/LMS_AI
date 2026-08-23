# AGENTS.md

Status: Active

Owner: Project leadership

Last updated: 2026-08-24

Applies to: Codex, Claude Code, CodeRabbit, and other AI-assisted engineering agents working in this repository.

This file is the repository-level instruction source for Wiii. Codex also reads `AGENTS.md` files during GitHub code review, so keep the `## Review guidelines` section current and specific.

## Repository Context

Wiii is an open-source durable AI workbench for conversations, local and cloud agents, project files, tools, memory, artifacts, and permission-aware integrations. It combines a FastAPI backend, WiiiRunner orchestration, PostgreSQL/pgvector, optional Neo4j graph context, ACP/MCP and host integrations, and a Tauri v2 desktop client. LMS is one Wiii Connect adapter, not the product boundary. LangGraph is no longer an active runtime dependency; remaining LangGraph references should be treated as historical, compatibility, or cleanup-tracking context unless a specific file proves otherwise.

Primary areas:

- `maritime-ai-service/`: FastAPI backend, auth, organization context, multi-agent orchestration, RAG, memory, integrations, deployment assets, tests.
- `wiii-desktop/`: Tauri v2 desktop app, React 18, TypeScript, Neko Chill ACP workspace, Zustand stores, SSE V3 streaming UI, embed app, frontend tests.
- `docs/`: repository-level architecture, operations, governance, plans, and assets.
- `.github/`: issue templates, PR template, CODEOWNERS, GitHub Actions, Dependabot, and review automation.

## Wiii + Neko Brand Memory

The approved identity is persistent repository truth, not a temporary chat
decision. Before changing any product mark, mascot, app icon, companion motion,
or Neko-facing voice, read:

- `docs/assets/brand/neko-family-v1/README.md`
- `docs/assets/brand/neko-family-v1/BRAND_SYSTEM.md`
- `docs/research/neko-motion-lab/README.md` for motion work

Wiii is the product and Neko is its companion. Neko Peek is the primary logo,
app icon, avatar, and ready/listening pose. Mochi, Nap, and Tilt are supporting
poses of the same Neko, never separate agents. Preserve the approved
warm-ivory body, cocoa-graphite protective tail, capsule eyes, compact
silhouette, and calm professional cuteness. Do not add a mouth, nose, whiskers,
paws, fur, blush, pupils, eyebrows, costumes, or provider-specific recolors.
Do not redesign or replace the approved family without explicit project-owner
approval.

Motion must be state-driven, brief, interruptible, and reduced-motion safe.
Do not ship perpetual bobbing or decorative attention loops. Error states stay
visually calm and communicate failure through adjacent UI text, never a sad or
angry face. Grok or other companion products may inform interaction research,
but their character designs and branded motion must not be copied.

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

## Product Entry And Release Truth

- The public product name remains **Wiii** until project leadership approves a
  rename. `Workbench`, `ADE`, `Neko Chill`, and `Wiii Service` describe
  surfaces or capabilities; they must not silently replace the product name.
- Desktop is local-first. A local project or agent session must not require a
  Wiii Service account. Wiii Service gates only managed capabilities such as
  sync, organization, managed Knowledge/Memory, policy, audit, and remote runs.
- Hosted web may require Wiii Service because it has no local process or
  filesystem authority. Do not project that constraint onto desktop UX.
- `VERSION` is coordinated source metadata, not proof of publication. A stable
  release exists only when the governed tag, dated changelog, verified
  artifacts, trust checks, provenance, and GitHub Release all agree.
- Never reuse the same public artifact identity for different bytes. Candidate
  filenames include the channel and source commit; stable filenames include
  the immutable SemVer and explicit platform trust state where relevant.
- Keep internal executable/bundle identifiers stable for upgrade compatibility
  unless a migration plan is approved. Public titles and package names follow
  `docs/releases/WIII_RELEASE_STANDARD.md` and machine checks in
  `tools/release/`.

## Agent and Tool UX Direction

- Prefer Odysseus-style tool experiences: tool calls should feel like coherent timeline steps with explicit pending, completed, skipped, blocked, warning, and no-source states instead of raw internal output.
- Fix tool behavior at the contract, routing, event, metadata, source-binding, and UI-rendering layers before changing prompts. Prompt changes are acceptable only after the runtime contract is sound.
- Preserve natural user intent while normalizing tool arguments into stable backend contracts before dispatch, policy denial, skipped fanout events, SSE emission, and store persistence.
- Keep source evidence attached to the exact tool call when identity is available, preserve citations across empty or partial source events, and avoid showing unsupported or unsafe source URLs.
- For live data paths such as weather, web search, news, legal, maritime, and external app/MCP tools, verify that answers are grounded in tool evidence and do not silently use memory or stale assumptions.
- Treat duplicate or policy-denied tool calls as first-class events with clear reasons; do not silently drop them or let them render as generic failures.
- For tool UX, provider-routing, memory-sensitive, or multi-step agent work, build task-specific harnesses/evals rather than relying only on manual spot checks. Use fan-out-and-synthesize, adversarial verification, generate-and-filter, tournament, and loop-until-done patterns when the work is broad, flaky, subjective, or prone to goal drift.
- Use lightweight harnesses for normal changes and reserve high-token multi-agent workflows for research, security analysis, code review, migrations/refactors, root-cause investigation, triage at scale, evals, memory/rule mining, or hard-to-reproduce regressions.
- Quarantine untrusted external content from high-privilege actions: agents/tools that read web, user, or third-party data must not directly execute destructive or privileged actions without an explicit policy/approval boundary.
- Mine repeated human corrections and review comments into durable rules, tests, or harness checks so future agents do not need the same correction again.

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
