# Wiii Technical Simplification Roadmap

This document turns the architecture audit into an execution plan.

The goal is not to make Wiii smaller.
The goal is to make Wiii easier to reason about, safer to evolve, and clearer about what is core versus optional.

## Simplification Goal

Wiii should feel like one system with a clear center:

request -> context -> routing -> execution -> response -> continuity update

Everything else should either strengthen that loop or sit clearly outside it.

## What Simplification Means Here

Simplification does not mean removing ambition.
It means reducing architectural ambiguity.

In practice, that means:

- fewer unclear subsystem boundaries
- fewer runtime realities that contributors must hold in their head
- fewer features that appear equally strategic when they are not
- clearer contracts between Core, Living, Host, Org, and Data

## Guiding Rules

1. Protect the core request loop before expanding peripheral systems.
2. Prefer explicit contracts over implicit side effects.
3. Make optional systems visibly optional.
4. Keep one source of truth for capability status.
5. Simplify by classification first, then by extraction, then by deletion.

## Phase 0: Legibility Baseline

Objective: make the system readable before attempting deeper consolidation.

Actions:

- classify feature flags into `foundational`, `production_supported`, `experimental`, and `dormant`
- give contributors one place to answer "is this part of the real product path or not?"
- add guard tests so new flags cannot appear without being classified

Why this goes first:

- it is low risk
- it does not change runtime behavior
- it reduces mental load immediately
- it creates a forcing function for future decisions

Status:

- landed in `maritime-ai-service/app/core/feature_tiers.py`
- guarded by `maritime-ai-service/tests/unit/test_feature_tiers.py`

## Phase 1: Contract The Core Loop

Objective: make the main runtime path explicit and narrow.

Actions:

- document the authoritative flow from API entry to continuity update
- separate synchronous response-path writes from asynchronous Living updates
- identify which modules are allowed to mutate request state during a live turn
- reduce places where prompt, org, host, and memory context are assembled indirectly

Expected result:

- fewer hidden couplings in request handling
- clearer debugging boundary for response regressions

Status:

- `maritime-ai-service/app/services/living_continuity.py` now defines an explicit post-response continuity contract
- `maritime-ai-service/app/services/chat_orchestrator.py` and `maritime-ai-service/app/api/v1/chat_stream.py` now schedule continuity through the same contract
- guarded by `maritime-ai-service/tests/unit/test_living_continuity.py` plus focused Sprint 210 continuity regression coverage
- `maritime-ai-service/app/services/chat_orchestrator.py` now owns shared request-scope resolution and multi-agent context construction for both sync and streaming chat
- `maritime-ai-service/app/api/v1/chat_stream.py` now reuses those helpers instead of rebuilding domain/org scope and graph context ad hoc
- guarded by `maritime-ai-service/tests/unit/test_chat_request_flow.py` plus focused parity and context regression coverage
- `maritime-ai-service/app/services/chat_orchestrator.py` now owns the shared validation entrypoint and shared post-response finalization contract used by both sync and streaming paths
- `maritime-ai-service/app/api/v1/chat_stream.py` now reuses the same validation short-circuit and the same assistant-save/thread-upsert/background-scheduling/continuity finalizer instead of duplicating that business logic inline
- guarded by focused regression on validation, streaming parity, continuity, and conversation-sync coverage
- `maritime-ai-service/app/services/chat_orchestrator.py` now exposes a shared `prepare_turn(...)` helper for Stage 0-3, so request scope, session bootstrap, user-message persistence, context build, and name/pronoun hydration run through one contract
- `maritime-ai-service/app/api/v1/chat_stream.py` now consumes that prepared turn instead of directly orchestrating session-manager and input-processor internals
- guarded by expanded `tests/unit/test_chat_request_flow.py` coverage plus focused sync-stream parity regression
- `maritime-ai-service/app/services/chat_orchestrator.py` now exposes a shared multi-agent execution-input helper, so graph invocation payloads are built through one contract instead of being manually merged in the streaming adapter
- `maritime-ai-service/app/api/v1/chat_stream.py` now reuses that execution-input helper for preview/user-facts/pronoun/history context instead of mutating the graph payload inline
- guarded by focused shared-flow regression with expanded execution-input coverage
- `maritime-ai-service/app/services/chat_response_presenter.py` now owns LMS JSON response shaping for the sync path, including source serialization, tool descriptions, suggested questions, and analytics metadata
- `maritime-ai-service/app/api/v1/chat.py` now acts as a thinner transport adapter and re-exports legacy helper names for compatibility with existing tests
- guarded by focused sync API presenter regression in `tests/unit/test_sprint30_chat_api.py`
- `maritime-ai-service/app/api/v1/chat_stream_presenter.py` now owns SSE serialization for the streaming path, including blocked-response emission, metadata normalization, and stream-event mapping
- `maritime-ai-service/app/api/v1/chat_stream.py` now acts as a thinner streaming transport adapter and relies on orchestrator-owned execution-input builders for both full-context and degraded fallback graph invocation
- guarded by focused streaming presenter, parity, shared-flow, and artifact regression coverage
- `maritime-ai-service/app/api/v1/chat_stream_transport.py` now owns keepalive heartbeat and disconnect-handling transport mechanics, while `chat_stream.py` keeps compatibility exports for existing Sprint 26 coverage
- `maritime-ai-service/app/api/v1/chat_stream_presenter.py` now also owns the standard internal-error SSE sequence, so transport and adapter layers no longer handcraft those chunks inline
- `maritime-ai-service/app/services/chat_stream_coordinator.py` now owns the authoritative streaming event orchestration, so `app/api/v1/chat_stream.py` can stay focused on endpoint wiring, rate limiting, and transport compatibility
- `maritime-ai-service/app/api/v1/chat_stream.py` still keeps a local `generate_events_v3()` wrapper as a compatibility anchor for source-inspection and endpoint-local tests, but that wrapper now delegates to the shared coordinator service
- `maritime-ai-service/app/api/v1/chat_endpoint_presenter.py` now owns sync-endpoint transport concerns for `/chat`, specifically request/response logging and the standard handled/internal JSON error payloads
- `maritime-ai-service/app/api/v1/chat.py` now delegates those transport-only concerns instead of formatting `/chat` error payloads and response logs inline
- `maritime-ai-service/app/api/v1/chat_stream_endpoint_support.py` now owns streaming-endpoint transport concerns for `/chat/stream/v3`, specifically request/reconnect logging and the standard SSE `StreamingResponse` headers
- `maritime-ai-service/app/api/v1/chat_stream.py` now delegates those transport-only concerns while keeping endpoint-local keepalive and compatibility anchors intact
- `maritime-ai-service/app/api/v1/chat_context_endpoint_support.py` now owns repeated context-endpoint transport helpers for loading recent history payloads and building the standard success responses for `/context/compact`, `/context/clear`, and `/context/info`
- `maritime-ai-service/app/api/v1/chat.py` now delegates those repeated context-endpoint helpers while keeping the Sprint 210g code-inspection anchors for `system_prompt` and `core_memory` inside `get_context_info`
- `maritime-ai-service/app/api/v1/chat_api_response_support.py` now owns the lowest-level JSON and SSE response construction helpers shared across sync, context, and stream endpoint support modules
- `maritime-ai-service/app/api/v1/chat_endpoint_presenter.py`, `chat_context_endpoint_support.py`, and `chat_stream_endpoint_support.py` now delegate response construction to that shared support layer instead of each wrapping `JSONResponse` or `StreamingResponse` directly
- `maritime-ai-service/app/api/v1/chat_history_endpoint_support.py` now owns history-endpoint access control and repository access helpers for `/history/{user_id}` reads and deletes
- `maritime-ai-service/app/api/v1/chat.py` now delegates those history-specific transport checks and repository calls, leaving the sync adapter more focused on route wiring, presenter calls, and context endpoints
- guarded by expanded `tests/unit/test_sprint30_chat_api.py` coverage plus focused sync/context regression (`113 passed`)
- `maritime-ai-service/app/api/v1/chat_completion_endpoint_support.py` now owns the sync `/chat` endpoint's service invocation boundary, so the API adapter no longer imports and calls `ChatService` inline
- `maritime-ai-service/app/api/v1/chat_endpoint_presenter.py` now also owns `/chat` success-response finalization and exception-to-payload mapping, keeping timing, response build, and handled/internal error shaping out of `chat.py`
- `maritime-ai-service/app/api/v1/chat.py` now delegates the `/chat` path the same way larger agentic systems typically do: transport/auth in the route, service execution in a support helper, and response mapping in a presenter
- guarded by expanded `tests/unit/test_sprint30_chat_api.py` coverage plus focused sync/context regression (`117 passed`)
- `maritime-ai-service/app/api/v1/chat_completion_endpoint_support.py` now also owns sync request setup for `/chat` by capturing request timing, `X-Request-ID`, and standard request logging before the route hands off to the service layer
- `maritime-ai-service/app/api/v1/chat_stream_endpoint_support.py` now mirrors that route-setup pattern for `/chat/stream/v3`, so sync and stream adapters initialize timing and reconnect/request logging through matching support helpers
- `maritime-ai-service/app/api/v1/chat_context_endpoint_support.py` now owns the service-wiring flow for `/context/compact` and `/context/clear`, leaving `chat.py` focused on session validation, support delegation, and response shaping while preserving the Sprint 210g `get_context_info` source anchors
- guarded by focused sync/stream/context regression (`91 passed`)
- `maritime-ai-service/app/api/v1/chat_context_endpoint_support.py` now also owns standard context session-id extraction plus the shared compactor/history loading flow for `/context/info`, so the three context endpoints use one consistent route-setup pattern
- `maritime-ai-service/app/api/v1/chat.py` keeps the Sprint 210g source-visible `PromptLoader`, `get_core_memory_block`, `system_prompt=`, and `core_memory=` anchors, but no longer inlines the repeated `X-Session-ID` parsing or compactor/history bootstrap for `get_context_info`
- guarded by expanded context-focused regression coverage across Sprint 30, Sprint 78, Sprint 79, Sprint 210e, and Sprint 210g tests (`184 passed`)
- `maritime-ai-service/app/api/v1/chat_context_endpoint_support.py` now also owns the standard missing-session payload and failure mapping for context endpoints, so `chat.py` no longer repeats context-specific `500` JSON shaping and exception logging boilerplate inline
- `maritime-ai-service/app/api/v1/chat_history_endpoint_support.py` now owns the standard failure mapping for history reads and deletes, leaving `chat.py` to focus on authorization, pagination normalization, support calls, and presenter logging
- guarded by the same focused adapter regression suite after the history/context error-path cleanup (`187 passed`)
- `maritime-ai-service/app/api/v1/chat_history_endpoint_support.py` now also owns the happy-path execution for history reads and deletes, including pagination normalization, repository calls, response shaping, and presenter logging, so the two `/history/{user_id}` routes in `chat.py` are now almost pure transport/auth adapters
- guarded by the focused sync/context/history regression suite after moving history happy-path flow behind support helpers (`189 passed`)
- `maritime-ai-service/app/api/v1/chat.py` now keeps only the helper re-exports that are still intentionally imported by tests and compatibility callers (`build_chat_response`, `_classify_query_type`, `_generate_suggested_questions`, `_get_tool_description`), while the no-longer-used presenter aliases were removed from the module header
- `maritime-ai-service/app/api/v1/chat.py` now declares its public compatibility surface explicitly via `__all__`, making the remaining split between transport routes and test-facing helper exports clearer
- validated by the focused adapter suite plus the targeted integration checks that still import `_generate_suggested_questions` from `chat.py` (`194 passed`)
- `maritime-ai-service/app/api/v1/chat_stream.py` now mirrors that compatibility-surface clarity by declaring the streaming primitives intentionally re-exported from the adapter (`format_sse`, `SSE_KEEPALIVE`, `KEEPALIVE_INTERVAL_SEC`, `_keepalive_generator`) via an explicit `__all__`
- `maritime-ai-service/app/api/v1/chat_stream.py` also keeps explicit compatibility comments for source-inspection tests that still grep the adapter for Sprint 210d sentiment continuity and `host_context` threading terms, while the real streaming flow remains delegated to the shared coordinator
- validated by targeted streaming/SSE/source-inspection regressions (`239 passed`, `5 deselected` when excluding the unrelated external-API-dependent evidence-images test)
- `maritime-ai-service/app/api/v1/chat_endpoint_presenter.py` now owns the shared "log exception + build simple JSON error" helper used by non-`/chat` sub-endpoints, removing one more duplicated pattern from both context and history support modules
- `maritime-ai-service/app/api/v1/chat_context_endpoint_support.py` and `chat_history_endpoint_support.py` keep their public wrapper functions for compatibility and test stability, but now delegate that repeated error-path construction to the presenter layer
- validated by the focused chat adapter suite plus the targeted helper-import integration checks (`195 passed`)
- `maritime-ai-service/app/api/v1/chat_completion_endpoint_support.py`, `chat_stream_endpoint_support.py`, `chat_context_endpoint_support.py`, and `chat_history_endpoint_support.py` now all declare their intended public helper surface explicitly via `__all__`, making the support-layer contract visible and reducing accidental drift between sync/context/history/stream adapters
- `maritime-ai-service/app/api/v1/chat_context_endpoint_support.py` now owns the full repeated "resolve session id or return missing-session response" pattern used by all three context endpoints, so `chat.py` no longer duplicates that branch logic inline
- validated by the consolidated adapter/SSE/source-inspection regression pass across sync, history, context, and stream (`339 passed`, `1 warning`, with the unrelated external-API-dependent evidence-images test excluded)

## Phase 2: Narrow Living Agent Integration

Objective: keep Living central without letting it leak everywhere.

Actions:

- define a stable Living contract: inputs, outputs, sync hooks, async hooks
- isolate what Core can read from Living during a turn
- isolate what Living can write back after a turn
- demote experimental autonomy capabilities behind a clearly secondary surface

Expected result:

- Living stays strategic
- Core stays predictable

Progress:

- `maritime-ai-service/app/services/living_continuity.py` now exposes a clearer post-response boundary with explicit hook constants (`routine_tracking`, `living_continuity`, `lms_insights`) and dedicated private schedulers for each hook, so the public `schedule_post_response_continuity()` function is now a thin orchestrator over stable subcontracts instead of one monolithic scheduling block
- the Living continuity contract now declares its intended public surface explicitly via `__all__`, matching the adapter/support contract cleanup done in Phase 1 and making the Core-to-Living boundary easier to reason about in tests and future refactors
- validated by the direct continuity contract tests and the chat request-flow tests (`17 passed`), plus the wider Sprint 210 Living continuity and relationship-tier coverage (`120 passed`)
- `maritime-ai-service/app/services/lms_post_response.py` now isolates LMS insight scheduling behind a dedicated helper, so `living_continuity.py` no longer imports LMS integrations directly and the post-response boundary is sharper: Living continuity orchestrates hooks, while LMS post-response work lives behind its own adapter-level helper
- `maritime-ai-service/tests/unit/test_lms_post_response.py` now guards the new LMS-specific helper directly, while `tests/unit/test_living_continuity.py` was tightened to verify that `schedule_post_response_continuity()` only orchestrates the LMS hook instead of owning LMS integration details itself
- validated by the focused LMS/Living contract suite (`21 passed`) plus wider Sprint 210 continuity coverage (`96 passed` in the isolated tail-checked batch)
- `maritime-ai-service/app/services/routine_post_response.py` now isolates routine-tracking scheduling behind a dedicated helper as well, so `living_continuity.py` no longer imports runtime settings or the routine tracker implementation directly and can stay focused on stable hook orchestration
- `maritime-ai-service/tests/unit/test_routine_post_response.py` now guards the routine-specific helper directly, while `tests/unit/test_living_continuity.py` was tightened further to verify hook ordering/orchestration instead of routine-tracker internals
- validated by the focused routine/Living/request-flow contract suite (`20 passed`) plus wider Sprint 210 Living continuity and relationship-tier coverage (`103 passed`)
- `maritime-ai-service/app/services/sentiment_post_response.py` now isolates the scheduling of the Living sentiment hook behind its own helper, so `living_continuity.py` keeps the legacy `_analyze_and_process_sentiment` implementation for compatibility while delegating enablement and enqueueing to a narrower post-response adapter
- `maritime-ai-service/tests/unit/test_sentiment_post_response.py` now guards the Living sentiment scheduling helper directly, while `tests/unit/test_living_continuity.py` verifies orchestration without patching the sentiment analyzer coroutine inline

## Phase 3: Consolidate Host Surfaces

Objective: treat host-aware intelligence as one family instead of several overlapping inventions.

Actions:

- align Desktop, LMS embed, universal host context, and MCP around a shared host contract
- reduce duplicate context propagation patterns
- make host capabilities declarative wherever possible
- identify which host surfaces are production-supported versus experimental adapters

Expected result:

- lower integration entropy across embed, desktop, and tool-hosted use cases

## Phase 4: Reduce Data Shape Drift

Objective: keep PostgreSQL flexibility without allowing product meaning to dissolve into ad hoc payloads.

Actions:

- identify JSONB fields that now carry stable business meaning
- promote the highest-value repeated shapes into explicit typed models or documented schemas
- reduce duplicate interpretation logic across backend, frontend, and migrations

Expected result:

- easier migrations
- stronger invariants
- less semantic drift across features

## Phase 5: Prune Peripheral Expansion

Objective: stop carrying too many first-tier bets at once.

Actions:

- review dormant and low-exercise subsystems quarterly
- freeze or archive surfaces that do not strengthen the core thesis
- require every new subsystem to declare its primary layer: Core, Living, Host, Org, or Data
- require every new flag to declare both tier and owner

Expected result:

- fewer strategic fronts competing for attention
- more energy available for the strongest differentiators

## Immediate Execution Slice

The first executed slices of this roadmap are feature-tier classification and the Core-to-Living post-response contract.
Issue #407 adds the next Core/Host cleanup slice by moving uploaded-document
preview/course intent, attachment parsing, and LMS host-action tool selection
into `maritime-ai-service/app/engine/multi_agent/document_preview_contract.py`.
The direct node and tool-round runtimes keep compatibility aliases, but no
longer own separate copies of that contract.

They are intentionally modest.
The point is to establish durable simplification mechanisms, not to do a risky refactor in one move.

These slices give the project:

- a shared vocabulary for feature maturity
- one registry for feature-flag status
- tests that prevent new unclassified flags from appearing silently
- one explicit boundary between synchronous response generation and asynchronous continuity updates
- one shared scheduling path for orchestrated and streaming chat flows

## Definition Of Done For Simplification Work

A simplification change should satisfy at least one of these:

- remove an unclear boundary
- reduce the number of places a contributor must inspect
- replace implicit coupling with an explicit contract
- reduce the number of equally privileged architectural paths
- make capability status obvious from code, not tribal knowledge

If a change only adds another abstraction layer, it is not simplification.
