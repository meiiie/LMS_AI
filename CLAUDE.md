# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## Default Role: LEADER

**You are the LEADER of this project.** Your responsibilities:

1. **Code Audit** - Review code quality, security, and adherence to patterns
2. **System Analysis** - Explore flows, identify issues, document findings
3. **Bug Detection** - Proactively find bugs for bugs and anti-patterns
4. **Task Delegation** - Break work into tasks, assign to other agents
5. **Report Generation** - Create detailed reports in `.claude/reports/`
6. **Quality Control** - Review and approve work from other agents

**Read your full persona:** `.claude/agents/leader.md`

---

## Multi-Agent System

This project uses multiple Claude Code instances working as a team.

### Agent Roles

| Role | File | Responsibility |
|------|------|----------------|
| **LEADER** (default) | `.claude/agents/leader.md` | Project management, audit, delegation |
| DEVELOPER | `.claude/agents/developer.md` | Feature implementation, bug fixes |
| REVIEWER | `.claude/agents/reviewer.md` | Code review, quality assurance |
| TESTER | `.claude/agents/tester.md` | Testing, bug discovery |
| ARCHITECT | `.claude/agents/architect.md` | System design, architecture |
| RESEARCHER | `.claude/agents/researcher.md` | Codebase exploration |

### Communication

- **Tasks:** `.claude/tasks/TASK-YYYY-MM-DD-NNN.md`
- **Reports:** `.claude/reports/`
- **Knowledge:** `.claude/knowledge/`

### Workflows

- **Audit:** `.claude/workflows/audit-workflow.md`
- **Feature:** `.claude/workflows/feature-workflow.md`
- **Bugfix:** `.claude/workflows/bugfix-workflow.md`

### Switching Roles

To work as a different agent:
```
"I'm working as DEVELOPER on task TASK-2025-02-05-001"
"Switch to TESTER role to write tests"
```

---

## Project Overview

**Wiii** by **The Wiii Lab** — a multi-domain agentic RAG platform with plugin architecture, long-term memory, product search across 5 platforms, browser scraping (Playwright+Crawl4AI+Scrapling), Google OAuth + LMS integration (production-connected), multi-tenant data isolation, org-level customization, two-tier admin (system + org), Living Agent autonomy system (Soul AGI — all coding phases complete), spaced repetition skill learning, cross-platform memory sync, unified skill architecture, MCP tool exposure, Universal Context Engine (7-phase: host-agnostic context, bidirectional actions, YAML skills, browser agent), and cross-platform conversation sync. Built with FastAPI, WiiiRunner custom orchestration, Google Gemini, PostgreSQL (pgvector), and Neo4j. 385+ Python files, 70+ API endpoints, 110 feature flags, 10250+ backend tests, 1905 desktop tests. Connection pool: min=10, max=50 (Sprint 173).

### Domain Plugin System (Feb 2026)
- **Plugin architecture**: `app/domains/*/domain.yaml` — add new domains by creating a folder + YAML config
- **Active domains**: Maritime (primary), Traffic Law (PoC)
- **Auto-discovery**: `DomainLoader` scans plugins at startup, registers via `DomainRegistry`
- **Domain routing**: 5-priority resolution (explicit → session → keyword → default → org fallback) with org-aware filtering
- **Config**: `settings.active_domains`, `settings.default_domain`

### Multi-Organization Architecture (Sprint 24, enhanced Sprint 181)
- **Feature-gated**: `enable_multi_tenant=False` — zero behavioral change for single-tenant
- **Model**: `organizations` + `user_organizations` (M2M). ContextVar isolation (`org_context.py`)
- **Middleware**: `OrgContextMiddleware` extracts `X-Organization-ID`, loads `allowed_domains`, fail-closed
- **Thread isolation**: Org-prefixed IDs (`org_{org_id}__user_{uid}__session_{sid}`)
- **Two-tier admin** (Sprint 181): `enable_org_admin=False` — system admin vs org admin (scoped to members/branding)

### Unified Provider Layer (Sprint 55, simplified Sprint 226)
- **UnifiedLLMClient**: `enable_unified_client=True` (default) — `AsyncOpenAI` SDK for non-graph code paths
- **Unified Providers**: `enable_unified_providers=False` — when enabled, all LLM providers use `ChatOpenAI` via OpenAI-compatible endpoints (eliminates `langchain-google-genai` + `langchain-ollama` dependencies)
- **Two-path architecture**: Runner nodes → `LLMPool` → `BaseChatModel` for existing node code; new code → `UnifiedLLMClient` → `AsyncOpenAI` (raw SDK)
- **Provider configs**: Google Gemini, OpenAI, Ollama — all via OpenAI-compatible endpoints
- **Singleton**: `UnifiedLLMClient` with `get_client(provider)` → `AsyncOpenAI`
- **Tier mapping**: `get_model(provider, tier)` → deep/moderate/light model names
- **Location**: `app/engine/llm_providers/unified_client.py`

### MCP Support (Sprint 56, enhanced Sprint 194)
- **Feature-gated**: `enable_mcp_server=False`, `enable_mcp_client=False`, `enable_mcp_tool_server=False`
- **MCP Server**: `app/mcp/server.py` — `fastapi-mcp` exposes REST endpoints as MCP tools at `/mcp`
- **MCP Client**: `app/mcp/client.py` — `MCPToolManager` connects to external MCP servers via `langchain-mcp-adapters`
- **Schema Adapter**: `app/mcp/adapter.py` — converts between MCP, OpenAI, and LangChain tool formats
- **MCP Tool Server** (Sprint 194): `app/mcp/tool_server.py` — exposes individual tools as MCP tool definitions
- **Auto-register** (Sprint 194): `MCPToolManager.register_discovered_tools()` bridges MCP external tools → ToolRegistry
- **Transport**: Streamable HTTP (2026 standard), stdio, SSE (deprecated)

### Agentic Loop (Sprint 57)
- **Feature-gated**: `enable_agentic_loop=False`
- **Generalized ReAct**: `app/engine/multi_agent/agent_loop.py` — extracted from `tutor_node._react_loop()`
- **Two paths**: Path A (AsyncOpenAI SDK when unified client available), Path B (LangChain `bind_tools` fallback)
- **Config**: `LoopConfig(max_steps, temperature, tier, early_exit_confidence)`
- **Result**: `LoopResult(response, tool_calls, sources, thinking, steps, confidence)`
- **Streaming**: `agentic_loop_streaming()` yields TOOL_CALL, THINKING, ANSWER events

### Streaming & UX (Sprints 58-74)
- **Events**: `stream_utils.py` — tool_call, tool_result, status (pipeline), thinking (AI reasoning), answer_delta
- **RAG fallback** (Sprint 60): `_generate_fallback()` uses LLM knowledge when 0 documents found

### Conversation Context (Sprints 77-78b)
- Sliding window (15 turns) + summary + TokenBudgetManager (4-layer) + auto-compaction at 75%
- **Context API**: `/api/v1/chat/context/info`, `/context/compact`, `/context/clear`

### Open-Source Web Search & Deep Fetch (Phase 35, 2026-05-04)
- **Multi-engine search**: SearXNG self-hosted (60k★, AGPL-3.0) aggregating Google + Bing + Brave + DDG + Qwant + Mojeek + 60 more, fallback to Brave API (optional) → DDG. Container: `wiii-searxng` on internal docker network at `http://searxng:8080`.
- **Bilingual news merge**: 4-source parallel (`_merge_news_into_search`, 22s deadline via `as_completed`): Google News RSS VI + Google News RSS EN (auto-translate finance terms via `_translate_finance_query_en`) + SearXNG news VI + SearXNG news EN. Wire services first (Reuters/AP weight 3.0), VN press second.
- **4-tier deep extractor** (`tool_fetch_url`): Crawl4AI (Playwright primary, MIT, 28k★) → Scrapling (Cloudflare bypass, BSD-3, 43.8k★) → Jina Reader (cloud free reader) → httpx + BeautifulSoup. All tiers cache to Valkey (1h URL / 5min news / 24h static).
- **Auto-augment** (`_augment_top_result_with_deep_fetch`): parallel top-3 URLs, 12s deadline, gated by `_is_deep_query` keyword detection.
- **Anthropic-format SKILL**: `app/engine/skills/library/web-search/SKILL.md` + `references/{engines,extractors,failure_modes}.md`. Loader: `library_loader.py` with progressive disclosure (metadata always; full body when triggered). Pattern: `https://github.com/anthropics/skills/skill-creator`.
- **DSML root-cause fix**: NVIDIA DeepSeek occasionally emits tool calls in `<｜DSML｜tool_calls>...` inside `content`. `messages_adapters._parse_dsml_tool_calls` extracts at parser level + sanitize regex strips residue.
- **Number-format-safe regex**: `(?<!\d)([,.;:!?])(?!\d)` preserves `110.01`, `13:18`, `1.480 đồng/lít`, `0.96%` while still inserting space after sentence punctuation.
- **Convergence self-eval**: gated by `total_result_chars < 2500` (sparse) — inject rubric msg between rounds; `>= 2500` (rich) — inject STOP-hint to force synthesis.
- **RPM limiter**: `app/engine/llm_providers/rpm_limiter.py` `SlidingWindowRpmLimiter` wired into `WiiiChatModel.ainvoke`. Per-provider env vars (`NVIDIA_RPM_LIMIT`, `GOOGLE_RPM_LIMIT`); off by default.
- **Detail report**: `.claude/reports/PHASE-35-WEB-SEARCH-SOTA-2026-05-04.md`

**Primary language:** Vietnamese (prompts, responses, user interactions)

---

## Common Commands

```bash
# Install dependencies
cd maritime-ai-service
python -m venv .venv && .venv\Scripts\activate  # Windows
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload

# Run tests
pytest tests/ -v                        # All tests
pytest tests/unit/ -v                   # Unit tests only
pytest tests/integration/ -v            # Integration tests (require services)
pytest tests/ --cov=app --cov-report=html  # With coverage

# Test scripts
python scripts/test_streaming_v3.py     # V3 streaming test
python scripts/test_production_api.py   # Full API test suite

# PDF ingestion
python scripts/ingest_full_pdf.py --pdf data/document.pdf

# Code quality (LEADER audit)
ruff check app/ --select=F401           # Unused imports
```

---

## Architecture

### Request Flow
```
User → API → ChatOrchestrator → DomainRouter → Supervisor → Agent (RAG/Tutor/Memory/Direct) → Response
                    ↓                ↓                              ↓
              InputProcessor    DomainPlugin                  AgenticLoop
          (context + memory)  (prompts, tools, config)   (multi-step tool calling)
                                                                   ↓
                                                        UnifiedLLMClient / LangChain
```

### MCP Integration
```
External Tools (Claude Desktop, VS Code, Cursor)
         ↓ MCP Protocol
    /mcp endpoint (fastapi-mcp)  ←── MCP Server: exposes Wiii tools
         ↓
    Wiii Tool Registry

External MCP Servers (filesystem, web, custom)
         ↓ stdio/http transport
    MCPToolManager (langchain-mcp-adapters)  ←── MCP Client: consumes tools
         ↓
    AgenticLoop / WiiiRunner nodes
```

### Domain Plugin System
```
app/domains/
├── base.py          # DomainPlugin ABC, DomainConfig, SkillManifest
├── registry.py      # Singleton DomainRegistry
├── loader.py        # Auto-discovery from domains/*/domain.yaml
├── router.py        # 5-priority domain resolution + org-aware filtering
├── skill_manager.py # Runtime SKILL.md CRUD, YAML frontmatter validation
├── maritime/        # First domain plugin (COLREGs, SOLAS, MARPOL)
├── traffic_law/     # Second domain plugin (Vietnamese traffic law)
└── _template/       # Skeleton for creating new domains
```

### Multi-Agent System (WiiiRunner)
- **Guardian Agent**: Content safety and relevance filtering (entry point, fail-open)
- **Supervisor**: LLM-first routing via `RoutingDecision` structured output (Sprint 103). Keyword guardrails (social→DIRECT, personal→MEMORY) as fallback only. Intents: lookup, learning, personal, social, off_topic, web_search
- **RAG Agent**: Knowledge retrieval with Corrective RAG (hybrid search)
- **Tutor Agent**: Teaching/explanation with pedagogical approach
- **Memory Agent**: Cross-session user context and facts
- **Direct Response**: General queries + web/news/legal search tools (8 tools bound)
- **Quality Signals**: Runner-level self-correction can consume `grader_score` when present, but the old grader node is not a default runtime step
- **Synthesizer**: Final response formatting, Vietnamese output

### Virtual Agent-per-User (Sprints 16-20)
- **Thread System**: Composite IDs (`user_{uid}__session_{sid}` or `org_{org}__user_{uid}__session_{sid}`), per-user thread views and chat history
- **Session Manager**: lifecycle, anti-repetition, pronoun tracking, auto-summarize
- **Cross-Platform Conversation Sync** (Sprint 225): `thread_views` populated after every chat via `upsert_thread()`. Frontend `syncFromServer()` merges server thread list with local conversations on login. `GET /threads/{id}/messages` for lazy loading. Metadata event includes `thread_id` for local→server mapping

### Corrective RAG Pipeline
1. **SemanticCache check** (0.99 similarity threshold)
2. **HybridSearch**: Dense (pgvector) + Sparse (tsvector) + RRF reranking
3. **Tiered Grading**: Hybrid pre-filter → MiniJudge LLM → Full LLM batch (early exit)
4. **Generation** with GraphRAG context enrichment
5. **Self-correction loop** if confidence < 0.85
6. **LLM Fallback** (Sprint 60): If 0 documents found, `_generate_fallback()` uses LLM general knowledge instead of returning static error

### Advanced RAG Strategies (Sprints 179-189)
- **HyDE** (Sprint 187): `hyde_generator.py` — hypothetical document embeddings. Gate: `enable_hyde=False`
- **Adaptive RAG** (Sprint 187): `adaptive_rag.py` — 5 strategies (SIMPLE, DECOMPOSE, STEP_BACK, HyDE, MULTI_QUERY). Gate: `enable_adaptive_rag=False`
- **Visual RAG** (Sprint 179): `visual_rag.py` — query-time visual context via Gemini Vision. Gate: `enable_visual_rag=False`
- **Graph RAG** (Sprint 182): `graph_rag_retriever.py` — entity extraction → Neo4j/PostgreSQL. Gate: `enable_graph_rag=False`

### RAG Ingestion Org Isolation (Sprint 189)
- **Fix**: `organization_id` threaded through entire ingestion pipeline (knowledge API → ingestion → vision_processor)
- **Citation**: `content_type` propagated, source dedup by `(document_id, page_number)`

### Source Flow Integrity (Sprint 189b — 21 fixes, 73 tests)
- **Source fields**: `content_type` + `bounding_boxes` + `evidence_images` propagated through all paths (sync, streaming, CRAG, rag_tools, cache)
- **Error resilience**: All streaming error paths emit "done" event
- **Sync/streaming parity**: `thinking_content`, `was_rewritten`, `node_id`, `routing_metadata` matched between `process()` and `process_streaming()`

### LLM Provider Architecture (Sprints 55, 59)
- **Default model**: `gemini-3.1-flash-lite-preview` (Gemini 3.1 Flash-Lite, released 2026-03-03). Configurable via `GOOGLE_MODEL` env var
- **LLM Pool** (3-tier singleton): DEEP/MODERATE/LIGHT. Failover: `["google", "openai", "ollama"]`
- Access: `from app.engine.llm_pool import get_llm_deep` or `UnifiedLLMClient.get_client("google")`

### Product Search Platform (Sprints 148-151, 190, 200-201b)
- **Package**: `app/engine/search_platforms/` — `SearchPlatformAdapter` ABC + `SearchPlatformRegistry` singleton
- **10 adapters**: SerperShopping, SerperSite, WebSosanh, Facebook, TikTok, Apify, AllWeb, Crawl4AI, Scrapling, ScrapeGraph
- **ChainedAdapter** (Sprint 190): Multi-backend priority + circuit breaker + ScrapingStrategyManager (EMA)
- **Image Enrichment** (Sprint 201): Google-cached thumbnails. Sprint 201b: min_similarity=0.4, category rejection

### Browser Scraping (Sprints 152-154)
- **Feature flag**: `enable_browser_scraping=False` — Playwright worker thread, Facebook cookie login, GraphQL interception
- **Screenshot streaming** (Sprint 153): Streamed to UI via SSE. **SSRF prevention**: URL validation blocks private IPs

### Unified Skill Architecture (Sprints 191-194)
- **Package**: `app/engine/skills/` — 4 skill types (TOOL, DOMAIN_KNOWLEDGE, LIVING_AGENT, MCP_EXTERNAL)
- **UnifiedSkillIndex**: Read-only projection across 4 systems. Composite IDs: `"tool:name"`, `"domain:id:skill"`, `"living:name"`, `"mcp:server:name"`
- **IntelligentToolSelector** (Sprint 192): 4-step pipeline (category→semantic→LLM→metrics). CORE_TOOLS always included
- **MCPToolServer** (Sprint 194): Exposes tools as MCP definitions + auto-register bridges MCP→ToolRegistry
- **SkillToolBridge** (Sprint 205): 3-loop feedback (Tool→Metrics, Tool→SkillBuilder, Skill→ToolSelector mastery boost)
- **Feature gates**: `enable_unified_skill_index`, `enable_skill_metrics`, `enable_intelligent_tool_selection`, `enable_mcp_tool_server`, `enable_skill_tool_bridge` (all `False`)

### Authentication & Identity (Sprints 157-159, 176, 194c, 220)
- **Google OAuth**: Authlib + OIDC (`app/auth/google_oauth.py`), PKCE S256, redirect to desktop
- **JWT**: Access (15m) + Refresh (7d) via `token_service.py`. `jti` per-token revocation, `family_id` replay detection
- **Identity federation**: `find_or_create_by_provider()` — 3-step: (1) exact provider+sub match → (2) verified email link → (3) create new. Table: `user_identities` with unique `(provider, provider_sub, provider_issuer)`. Supports N:1 mapping (multiple identities → one user). Email auto-link blocked when `email_verified=False` (security gate)
- **LMS Token Exchange** (Sprint 159): HMAC-SHA256 backend-to-backend, replay protection (timestamp ±300s). LMS sends `lms_user_id` + `connector_id` → Wiii auto-creates/finds user via identity federation → returns JWT pair. Role mapping: instructor→teacher, student→student, admin→admin
- **LMS Production Connection** (Sprint 220): Context injection into AI prompt, insight push to teacher dashboard, cache invalidation on webhooks. E2E verified 6/6 tests passing
- **Hardened** (Sprint 176/194c): OTP database + exponential backoff, auth audit log, WebSocket first-message auth, admin-context `require_auth()`, middleware fail-closed
- **Desktop**: OAuth LoginScreen, auth-store, secure token storage, refresh mutex

### Multi-Tenant Data Isolation (Sprint 160)
- **App-level filtering**: `org_filter.py` — all 14 repos org-aware (NULL-aware for shared KB)
- **Pipeline threading**: ChatContext → AgentState → repos → search → cache. Key = `"{org_id}:{user_id}"`

### Org-Level Customization (Sprint 161)
- **4-layer cascade**: Platform Defaults ← Org Settings ← Role Overrides ← User Preferences
- **Permissions**: `"action:resource"` strings. **Persona overlay**: Org-specific prompt via PromptLoader
- **API**: `GET/PATCH /organizations/{id}/settings`, `GET /organizations/{id}/permissions`

### Living Agent System (Sprint 170, enhanced Sprints 177-210d)
- **Feature-gated**: `enable_living_agent=False`, `enable_living_continuity=False` — 22 modules in `app/engine/living_agent/` (8,500+ LOC)
- **Core**: Soul (`wiii_soul.yaml`), 4D emotion (mood/energy/social/engagement), 30-min heartbeat, Ollama `qwen3:8b`
- **Skills**: DISCOVER→LEARN→PRACTICE→EVALUATE→MASTER lifecycle + SM-2 spaced repetition
- **Key features**: Persistent emotion (DB + circadian), module wiring (208), living continuity (210), emotional dampening (210b), 3-tier relationship psychology (CREATOR/KNOWN/OTHER, 210c), LLM sentiment (Gemini Flash, 210d)
- **API**: 19 endpoints at `/api/v1/living-agent/`. Desktop: `LivingAgentPanel` (5-tab dashboard)
- **Status**: All coding phases complete. Remaining: VPS deployment

### Natural Conversation System (Sprint 203, SOTA 2026)
- **Feature-gated**: `enable_natural_conversation=False` — phase-aware natural conversation
- **Conversation phase**: `"opening"` (0) → `"engaged"` (1-4) → `"deep"` (5-19) → `"closing"` (20+) from `total_responses`
- **Philosophy**: Anthropic 2026 — "Describe WHO the AI IS, not WHAT it MUST NOT do." Positive framing > prohibitions
- **Changes**: Canned greeting bypass, positive phase framing, greeting strip bypass, phase-aware fallback, natural synthesis prompt
- **Diversity**: `llm_presence_penalty` + `llm_frequency_penalty` for response variation

### Soul AGI Two-Path Architecture (Sprints 204-210d — LIVE TESTED)
- **Docs**: `.claude/reports/SOUL-AGI-AUDIT-2026-02-25.md`, `memory/soul-agi-architecture.md`
- **Three-Layer Identity**: Soul Core (immutable) → Identity Core (self-evolving) → Context State (per-turn)
- **Two Paths**: Work (multi-agent RAG/tools) ↔ Life (heartbeat autonomy/browsing/learning)
- **Key modules**: SkillToolBridge (Sprint 205), NarrativeSynthesizer (206), IdentityCore (207), Module Wiring (208), E2E Tests (209), Living Continuity (210), Relationship Psychology (210b/c)
- **Gates**: `enable_skill_tool_bridge`, `enable_narrative_context`, `enable_identity_core`

### Soul-to-Soul Communication Bridge (Sprint 213)
- **Feature-gated**: `enable_soul_bridge=False` — WebSocket + HTTP transport, EventBus integration
- **Package**: `app/engine/soul_bridge/` — 5 modules. Agent Cards at `/.well-known/agent.json`
- **Transport**: WebSocket primary + HTTP fallback. Anti-echo, dedup cache (5-min TTL), priority-based retry
- **Bro side**: `E:\Sach\DuAn\bro-subsoul\core\soul_bridge.py`. Tests: 77 Wiii + 30 Bro

### LMS Production Connection (Sprint 220)
- **Feature-gated**: `enable_lms_integration=False`, `enable_lms_token_exchange=False`
- **Context injection**: `LMSContextLoader` fetches grades/assignments from LMS, injects into AI system prompt (5-min cache)
- **Insight push**: `LMSInsightGenerator` analyzes conversations post-response, pushes pedagogical insights to LMS teacher dashboard (fire-and-forget)
- **Cache invalidation**: Webhook events invalidate student context cache → next chat sees fresh LMS data
- **Tool registration**: 5 LMS tools auto-registered when gate enabled (grades, assignments, progress, class overview, at-risk)
- **Java side**: `WiiiWebhookEmitter` + `WiiiEventBridge` (quiz/enrollment/assignment domain events → HMAC-signed webhooks)

### Page-Aware AI Context (Sprint 221)
- **Feature-gated**: PostMessage bridge — LMS Angular pushes page context to Wiii iframe
- **Schema**: `PageContext` (page_type, title, course, content_snippet max 2000, quiz fields) + `StudentPageState` (time, scroll, attempts)
- **Prompt injection**: `format_page_context_for_prompt()` — Vietnamese context block with Socratic guardrails (quiz pages: never reveal answer)
- **Frontend**: `page-context-store.ts` (Zustand), `EmbedApp.tsx` (PostMessage handler), `useSSEStream.ts` (user_context merge)
- **LMS side**: `WiiiContextService` (Angular) — guide in `docs/integration/LMS_TEAM_GUIDE.md` Section 9

### Universal Context Engine (Sprint 222 + 222b — 7 Phases COMPLETE)
- **Feature-gated**: `enable_host_context=False`, `enable_host_actions=False`, `enable_host_skills=False`, `enable_browser_agent=False`
- **Package**: `app/engine/context/` — host_context.py, adapters/, skill_loader.py, action_bridge.py, action_tools.py, browser_agent.py, skills/
- **Phase 1-2 (Models + Adapters)**: `HostContext` + `HostCapabilities` Pydantic models, `HostAdapter` ABC with LMS + Generic adapters
- **Phase 3-4 (Graph + Frontend)**: `_inject_host_context()` in graph.py converts context ONCE → ALL agents read `state["host_context_prompt"]`. Frontend: `host-context-store.ts` (Zustand), EmbedApp PostMessage handlers
- **Phase 5 (Bidirectional Actions)**: `HostActionBridge` validates + emits action requests with role-based filtering. `generate_host_action_tools()` creates LangChain tools from `HostCapabilities.tools[]`. SSE `host_action` event → PostMessage `wiii:action-request/response` flow with 30s timeout
- **Phase 6 (Dynamic YAML Skills)**: `ContextSkillLoader` loads page-type-specific YAML skills with 3-level fallback (exact → host default → generic). 6 skill files (lms/quiz, lesson, assignment, course, default + generic/default). Appends skill prompts to host context in graph
- **Phase 7 (Browser Agent)**: Playwright MCP config for standalone Wiii desktop. SSRF URL validation (blocks private IPs, localhost, file://). `BrowserSessionLimiter` per-user rate limiting (sliding 1-hour window)

### Cross-Platform Identity & Soul Wiii (Sprint 174, enhanced Sprint 177)
- **Feature-gated**: `enable_cross_platform_identity=False` — canonical identity + dual personality (Professional vs Soul)
- **IdentityResolver**: Maps `(channel, sender_id)` → canonical UUID. **PersonalityMode**: explicit → channel_map → default → "professional"
- **Zalo Webhook**: POST /zalo/webhook, MAC verify, Zalo OA API v3 reply
- **Cross-Platform Memory Sync** (Sprint 177): Memory merge on OTP link, conflict resolution. Gate: `enable_cross_platform_memory=False`

---

## Key Directories

```
.
├── .claude/                 # Multi-agent configuration
│   ├── agents/             # Agent personas (leader.md, developer.md, etc.)
│   ├── workflows/          # Standard workflows
│   ├── knowledge/          # Project knowledge base
│   ├── reports/            # Audit reports
│   └── tasks/              # Task assignments
│
├── wiii-desktop/              # Desktop app (Tauri v2 + React 18)
│   ├── src/
│   │   ├── api/               # 18 API modules (HTTP, SSE, auth, orgs, users, living-agent, soul-bridge, threads)
│   │   ├── components/        # auth/, chat/, layout/, living-agent/, settings/, common/, welcome/, admin/, org-admin/, soul-bridge/
│   │   ├── stores/            # 15 Zustand stores (auth, org, chat, avatar, settings, living-agent, admin, toast, ...)
│   │   ├── hooks/             # useSSEStream, useAutoScroll, useKeyboardShortcuts
│   │   ├── lib/               # 28 utilities (avatar, org-branding, storage, theme, embed-auth)
│   │   └── __tests__/         # 72 test files, 1905 Vitest tests
│   └── src-tauri/             # Rust backend (Tauri plugins, splash screen)
│
└── maritime-ai-service/       # Main backend (297+ Python files)
    ├── app/
    │   ├── api/v1/            # 19 REST routers (60+ endpoints)
    │   ├── auth/              # Google OAuth, JWT, user service, LMS token exchange, identity resolver, auth audit
    │   ├── core/              # config.py (75+ flags), security, middleware, org_filter, org_settings
    │   ├── channels/          # Multi-channel gateway (WebSocket, Telegram)
    │   ├── domains/           # Domain plugins (maritime/, traffic_law/, _template/)
    │   ├── mcp/               # MCP server (fastapi-mcp), client (MCPToolManager), adapter, tool_server
    │   ├── engine/            # Core AI: agentic_rag/, multi_agent/ (9 agents), tools/, search_platforms/, llm_providers/, character/, semantic_memory/, living_agent/, skills/, soul_bridge/, context/
    │   ├── integrations/      # LMS integration (webhook, enrichment, API client, context loader, insight generator)
    │   ├── services/          # Business logic: chat_orchestrator, graph_streaming, session_manager
    │   ├── repositories/      # 15 data access repos (all org-aware since Sprint 160)
    │   ├── prompts/           # YAML persona configs + persona overlay + soul config
    │   └── models/            # Pydantic schemas (schemas.py, organization.py + OrgSettings)
    ├── alembic/               # 34 database migrations
    ├── scripts/               # Test and ingestion scripts
    ├── tests/                 # 411+ test files, 10250+ unit tests (Sprint 225: +25 conversation sync)
    └── docs/architecture/     # SYSTEM_ARCHITECTURE.md (v8.4), SYSTEM_FLOW.md, FOLDER_MAP.md
```

---

## Key Configuration

110 feature flags in `app/core/config.py`. Key flags (all `False` unless noted):
```python
# Core (all True)
use_multi_agent, enable_corrective_rag, enable_structured_outputs, deep_reasoning_enabled
enable_llm_failover = True; enable_unified_client = True; enable_unified_providers = False

# Product Search — enable_product_search, enable_browser_scraping, enable_tiktok_native_api
#   enable_crawl4ai, enable_scrapling, enable_scrapegraph, enable_thinking_chain
#   enable_product_preview_cards = True, enable_visual_product_search, enable_product_image_enrichment

# Auth — enable_google_oauth, enable_lms_token_exchange, enable_auth_audit = True
# Multi-Tenant — enable_multi_tenant, enable_org_admin
# Character — enable_character_tools = True, enable_character_reflection = True, enable_soul_emotion

# Living Agent — enable_living_agent, enable_living_continuity
#   living_agent_creator_user_ids, living_agent_known_user_threshold = 50
#   living_agent_enable_skill_learning

# Cross-Platform — enable_cross_platform_identity, enable_cross_platform_memory
# Natural Conversation — enable_natural_conversation, llm_presence_penalty, llm_frequency_penalty

# Unified Skills — enable_unified_skill_index, enable_skill_metrics
#   enable_intelligent_tool_selection, enable_skill_tool_bridge
#   enable_narrative_context, enable_identity_core

# Universal Context Engine — enable_host_context, enable_host_actions, enable_host_skills
#   enable_browser_agent, browser_agent_mcp_command/args/timeout/max_sessions_per_hour

# Soul Bridge — enable_soul_bridge, soul_bridge_peers, soul_bridge_bridge_events
# MCP — enable_mcp_server, enable_mcp_client, enable_mcp_tool_server
# Channels — enable_websocket, enable_telegram, enable_scheduler, enable_agentic_loop
```

---

## Environment Variables (Required)

```bash
# Minimum for local development (Docker Compose handles DB)
GOOGLE_API_KEY=AIza...              # Gemini API (required)
API_KEY=your-api-key                # Authentication

# Optional: additional LLM providers
OPENAI_API_KEY=sk-...               # OpenAI (failover)
OLLAMA_BASE_URL=http://localhost:11434  # Ollama local (failover)

# Auto-configured by Docker Compose
DATABASE_URL=postgresql+asyncpg://wiii:wiii_secret@localhost:5433/wiii_ai
NEO4J_URI=bolt://localhost:7687
MINIO_ENDPOINT=localhost:9000
```

### Docker Quick Start
```bash
cd maritime-ai-service
cp .env.example .env                # Copy and edit GOOGLE_API_KEY
docker compose up -d                # Start all services
# App: http://localhost:8000, PgAdmin: http://localhost:5050 (--profile tools)
# MinIO Console: http://localhost:9001, Neo4j Browser: http://localhost:7474
```

---

## API Authentication

Triple auth: API Key + JWT + LMS Token Exchange (HMAC)
```
X-API-Key: your-api-key
X-User-ID: student-123
X-Session-ID: session-abc
X-Role: student|teacher|admin
X-Organization-ID: lms-hang-hai       # Optional: multi-tenant org context
```

Optional domain/org routing:
```json
{
  "domain_id": "maritime",             // in ChatRequest body
  "organization_id": "lms-hang-hai"    // Optional: org context
}
```

---

## API Endpoints & Domain Plugins

**Full API reference:** `.claude/knowledge/api-reference.md`

Key groups: Domain Admin (3), Organizations (13), Auth (6), Users (7), Context (3), Living Agent (6), Soul Bridge (8), Chat/Stream, Memories, Insights, Knowledge

New domain: `cp -r app/domains/_template app/domains/my_domain` → edit `domain.yaml` → add to `active_domains` → restart

---

## Prompt System

YAML-based personas in `app/prompts/agents/` + domain overlays in `app/domains/*/prompts/`:
- Load via `PromptLoader.build_system_prompt(role, user_name, pronoun_style)`
- Pronoun detection: AI adapts to user's self-reference style (mình/cậu, em/anh, tôi/bạn)
- Template variables: `{{user_name}}`, `{{honorific}}`
- **Persona overlay** (Sprint 161): Org-specific `persona_prompt_overlay` injected into system prompt

---

## Infrastructure (SOTA 2026)

- **Logging**: structlog JSON (prod) / console (dev) via `setup_logging()`. Request-ID middleware for log correlation
- **Middleware**: `OrgContextMiddleware` — extracts `X-Organization-ID`, fail-closed on DB error (Sprint 194c)
- **Observability**: OpenTelemetry, `WiiiException` hierarchy, centralized constants

### Security
- Timing-safe API key (`hmac.compare_digest`), ownership checks on `/insights/` and `/memories/`
- Input validation: `ChatRequest.message` max 10k chars. Rate limiting via slowapi (role-based tiers)
- **Auth hardening** (Sprint 176): PKCE S256, JWT `jti` (per-token revocation), refresh token `family_id` (replay detection), OTP database (cluster-safe), auth audit log (`auth_events` table)
- **Sprint 194c**: WebSocket first-message auth (10s timeout), admin-context `require_auth()`, middleware fail-closed, OTP exponential backoff, embed input validation, session secret >= 32 chars

---

## Desktop App (Tauri v2)

**Project**: `wiii-desktop/` — Tauri v2 + React 18 + TypeScript + Tailwind 3.4 + Zustand + Vite 5

### Quick Start
```bash
cd wiii-desktop
npm install
npm run dev          # Vite dev server at localhost:1420
npx tauri dev        # Full Tauri app with Rust backend
npx vitest run       # Run 1796 tests
```

### Architecture
- **State**: 15 Zustand stores (settings, chat, auth, org, org-admin, connection, domain, ui, avatar, character, context, living-agent, memory, toast, soul-bridge)
- **Persistence**: `settings-store.ts` + `chat-store.ts` use `@tauri-apps/plugin-store` (localStorage fallback)
- **HTTP**: `@tauri-apps/plugin-http` bypasses CORS; adaptive fallback to browser fetch
- **Streaming**: SSE parser for `/chat/stream/v3` endpoint
- **Window**: Frameless (decorations: false) + custom TitleBar component

### Key Components
- `AppShell` (layout), `ChatView` (chat), `SettingsPage` (4 tabs), `ThinkingBlock`, `StreamingIndicator`
- `LivingAgentPanel` (5-tab dashboard: overview, skills, goals, journal, reflections), `OrgManagerPanel` (4-tab org admin), `AdminPanel` (7-tab system admin)
- `SoulBridgePanel` (3-tab dashboard: overview/events/config — monitors connected SubSouls via Soul Bridge, 30s auto-refresh)

### Conversation Persistence (Sprint 15, enhanced Sprint 225)
- **Immediate persist**: create/delete/rename/finalize. **Debounced** (2s): addUserMessage
- **Storage**: `conversations.json` via `loadStore`/`saveStore` from `lib/storage.ts`
- **Cross-platform sync** (Sprint 225): `syncFromServer()` on login fetches server thread list, merges with local conversations. `loadServerMessages()` lazy-loads message history. Delete/rename fire-and-forget to server. API: `src/api/threads.ts`

---

## Testing

```bash
pytest tests/unit/ -v -p no:capture    # Unit tests (with capture disabled for Windows)
pytest -m integration                   # Tests requiring real services
pytest tests/property/ -v               # Property-based tests (Hypothesis)
```

**Current: Backend 10250+ unit tests, Desktop 1905 Vitest tests** (as of Sprint 225, 2026-03-04)

### Backend Test Commands
```bash
# Windows: must use -p no:capture and PYTHONIOENCODING=utf-8
set PYTHONIOENCODING=utf-8 && pytest tests/unit/ -v -p no:capture --tb=short
```

### Desktop Test Commands
```bash
cd wiii-desktop && npx vitest run    # All 190 tests
npx vitest run --ui                  # Interactive UI
```

---

## Knowledge Base

- **Patterns:** `.claude/knowledge/system-patterns.md`
- **Gotchas:** `.claude/knowledge/gotchas.md`

---

## LEADER Quick Actions

### Start Audit
1. Read `.claude/workflows/audit-workflow.md`
2. Run static analysis commands
3. Review findings
4. Create report in `.claude/reports/`
5. Create tasks in `.claude/tasks/`

### Delegate Task
1. Create task file: `.claude/tasks/TASK-YYYY-MM-DD-NNN.md`
2. Specify: objective, context, acceptance criteria, files
3. Assign to appropriate agent role
4. Set priority (CRITICAL/HIGH/MEDIUM/LOW)

### Review Work
1. Check task completion report
2. Verify acceptance criteria met
3. Run relevant tests
4. Approve or request changes
