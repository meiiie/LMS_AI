# Changelog

All notable changes to Wiii are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses date-based versions (`YYYY.MM.DD`) rather than semantic versioning, because Wiii ships a monorepo with multiple deployable surfaces (backend API, desktop app, iframe embed, LMS integration) whose compatibility windows don't align to a single semver axis.

Release lines:

- **Unreleased** — work merged to `main` but not yet deployed to production.
- **Dated entries** — dated on the day of the production deployment. Each entry lists the scope that changed (backend / desktop / embed / infra / docs).

## [Unreleased]

### Added

- `CODE_OF_CONDUCT.md` adopting Contributor Covenant v2.1 with Wiii-specific expectations.
- `.github/dependabot.yml` — weekly grouped version updates for pip, npm, cargo, github-actions, docker (Monday 08:00 Asia/Ho_Chi_Minh).
- `SUPPORT.md` — routing help requests away from the issue tracker.
- `.gitattributes` — line-ending, binary, and generated-file handling for a mixed Python/TypeScript/Rust monorepo.
- `.github/ISSUE_TEMPLATE/agent_finding.yml` — dedicated form for issues filed by AI agents (provenance, agent, model, confidence, suggested owner).
- `docs/operations/WIII_BRANCH_PROTECTION.md` — required branch protection rules for `main`, documented so maintainers can reconcile the GitHub settings with policy.

### Changed

- Default local backend URL in the desktop/web app flipped from `:8000` to `:8080` so browser clients reach the backend through nginx (the FastAPI port is internal-only in Docker Compose).
- Embed iframe now fetches admin context after JWT auth, so the Hệ Quản Trị / Quản Lý Tổ Chức sidebar icons appear for platform admins inside embeds (previously only the desktop shell triggered this).
- Web search now applies Vietnamese-aware relevance scoring with a finance-site bias; queries like "giá dầu hôm nay" no longer return trending-feed noise.
- Magic-link email flow ships a dev fallback that logs the verify URL and returns it as `dev_verify_url` when `RESEND_API_KEY` is a `CHANGE_ME_` placeholder, unblocking local sign-in without Resend configured.

### Fixed

- Gemini 2.5+ OpenAI-compat rejected `extra_body={"google":{"thinking_config":{...}}}`. Wiii now sends `reasoning_effort` (low|medium|high) instead, derived from `thinking_budget`.
- LangChain `bind_tools` leaked internal kwargs (`ls_structured_output_format`, `ls_provider`, …) into `AsyncOpenAI.chat.completions.create()`. `WiiiChatModel` now strips them before the SDK call.
- `tool_choice="<tool-name>"` was rejected by the Gemini compat endpoint. `WiiiChatModel` normalises bare tool names to `{type: "function", function: {name: "…"}}` and maps the LangChain aliases `"any"` / `"tool"` → `"required"`.
- CRAG now falls back to a web-search-derived answer when hybrid retrieval returns 0 documents, instead of returning a static "knowledge base does not cover this" message.
- Streaming narration dedup rejects chunks with ≥40-char substring overlap or ≥80% prefix overlap with the previous chunk, fixing a visible repeat in the thinking block.
- Developer Mode (API-key login) now writes `settings.user_id = "api-client"` so ownership-checked endpoints (`/memories/{user_id}`, `/insights/{user_id}`) match the backend's enforced identity under `ENVIRONMENT=production`.

### Infrastructure & Governance

- Classified the remaining 18 unclassified feature flags into tiers (FOUNDATIONAL / PRODUCTION_SUPPORTED / EXPERIMENTAL / DORMANT), unblocking `test_feature_tiers`.
- Consolidated operational governance under `docs/operations/` (GitHub governance, branch protection, multi-agent maintainer protocol, documentation governance, product release, and production auth runbooks).
- `.coderabbit.yaml` shipped with path-specific review instructions for auth, RAG, multi-agent, living agent, MCP, Alembic, GitHub automation, and operations docs.
- Removed legacy `.claude/reports/` and `.Codex/reports/` tracked trees from git; durable findings were promoted into `docs/operations/`.
- Removed the remaining tracked `.claude/` legacy coordination tree and `.Codex` scratch sample; `CLAUDE.md` is now a thin compatibility redirect to `AGENTS.md`.
- Updated the desktop Tauri Rust stack to `tauri 2.11.1` for Dependabot alert #27; the remaining transitive `glib` advisory is tracked in #280 because `gtk v0.18.2` still requires `glib ^0.18`.

---

## Seed Entry — Before 2026-04-24

Prior changes are recorded in commit history. Starting from the 2026-04-24 governance checkpoint, every user-visible change lands here before it can be merged to `main`; current operational truth lives in `docs/operations/`.
