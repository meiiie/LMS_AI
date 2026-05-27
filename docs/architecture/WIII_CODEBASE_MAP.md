# Wiii Codebase Map

Status: Active

Owner: Architecture Maintainers (CODEOWNERS; track drift through `area:docs` GitHub issues)

Last updated: 2026-05-22

This is the short navigational map for humans and coding agents working in the
Wiii repository. It complements `AGENTS.md`, the operation docs, and deeper
architecture references.

## One Sentence

Wiii is a multi-surface agentic AI platform with a FastAPI backend, a React/Tauri
desktop and embed frontend, organization-aware data boundaries, retrieval and
memory, LMS host actions, visual artifacts, voice, and an emerging Wiii Connect
capability boundary.

## Top-Level Folders

| Path | Purpose | Notes |
|---|---|---|
| `maritime-ai-service/` | FastAPI backend, orchestration, RAG, tools, memory, LMS, deploy assets | Highest-risk runtime surface |
| `wiii-desktop/` | React 18, Tauri v2, embed app, chat UX, Pointy, voice controls | User-visible behavior and stream rendering |
| `docs/` | Architecture, operations, integration, release, governance | Durable knowledge belongs here |
| `docs/architecture/wiii-connect/` | Wiii Connect blueprint and connection/capability contracts | Incubation docs before any standalone repo extraction |
| `specs/` | Spec Kit artifacts for architecture-sensitive work | Use for multi-phase or contract changes |
| `.github/` | GitHub Actions, templates, CodeRabbit, CODEOWNERS | Merge safety and review automation |
| `.agents/skills/` | Repo-local Codex skills | Skills should be focused and loaded on demand |
| `memory/` | Historical handoffs and field notes | Useful context, not canonical governance |
| `scripts/` | Repository-level helper scripts | Avoid adding one-off local probes here |
| `chaos/`, `loadtest/` | Stress and load tooling | Run only when task requires it |

## Product Layer Model

| Layer | Meaning | Main code areas |
|---|---|---|
| Core | Decide and execute the current turn | chat services, multi-agent runtime, tool loop |
| Living | Maintain continuity and identity over time | memory, emotion, reflection, post-turn hooks |
| Host | Understand where Wiii is operating | desktop, embed, LMS, Pointy, host actions |
| Connect | Decide which connected capabilities can be used now | tool policy, host capabilities, future Wiii Connect contracts |
| Org | Enforce ownership and tenant boundaries | auth, org middleware, settings, repositories |
| Data | Preserve durable state and retrieval substrate | PostgreSQL, pgvector, repositories, migrations |

## Main Runtime Flow

The normal chat turn should be read in this order:

1. FastAPI route receives request and auth context.
2. `ChatOrchestrator` prepares the turn.
3. Context, org, host, history, document, and memory state are assembled.
4. Connection and capability status gates which tools can be visible.
5. Multi-agent runtime chooses direct, RAG, tool, visual, LMS, or other lanes.
6. Tools and retrieval execute with tenant, host, and capability constraints.
7. Backend emits sync response or SSE V3 events.
8. Frontend assembles visible answer, previews, sources, and artifacts.
9. Post-turn hooks update continuity outside the critical response path.

## Backend Navigation

| Need | Start here |
|---|---|
| Sync chat behavior | `maritime-ai-service/app/api/v1/chat.py`, then `maritime-ai-service/app/services/chat_orchestrator.py` |
| Streaming behavior | `maritime-ai-service/app/api/v1/chat_stream.py`, then `maritime-ai-service/app/services/chat_stream_coordinator.py` |
| Direct response node | `maritime-ai-service/app/engine/multi_agent/direct_node_runtime.py` (main direct node)<br>Deterministic fast responses: `direct_node_fast_response_runtime.py`<br>Uploaded-document preview preflight: `direct_node_document_preview_runtime.py`<br>Direct-node tool selection: `direct_node_tool_selection.py`<br>Direct-node LLM preflight: `direct_node_llm_preflight.py`<br>Direct-node execution preparation: `direct_node_execution_prep.py`<br>Direct-node response cleanup: `direct_node_response_cleanup.py`<br>Direct-node visible thinking finalization: `direct_node_visible_thinking_finalization.py`<br>Direct-node exception/source fallback lifecycle: `direct_node_exception_fallbacks.py`<br>Direct-node final state/domain notice: `direct_node_final_state.py`<br>Host UI timeout fallback: `direct_node_host_timeout.py`<br>Deterministic thinking snapshots: `direct_node_thinking_snapshot.py`<br>Fast-path helper modules: `direct_node_*_runtime.py` |
| Direct answer streaming | `maritime-ai-service/app/engine/multi_agent/direct_execution.py` (provider invocation and fallback shell)<br>Visible stream text/thinking helpers: `direct_stream_text_runtime.py`<br>Opening/wait surfaces: `direct_opening_runtime.py`, `direct_wait_surface.py` |
| Direct tool loop | `maritime-ai-service/app/engine/multi_agent/direct_tool_rounds_runtime.py` (main orchestration)<br>Runtime/provider bindings: `direct_runtime_bindings.py`<br>Generic dispatch: `direct_tool_dispatch_runtime.py`<br>Final synthesis helpers: `direct_final_synthesis_runtime.py`<br>Pointy policy: `direct_pointy_runtime.py`<br>Visual turn policy: `direct_visual_tool_policy_runtime.py`<br>Web-search policy: `direct_web_search_policy.py`<br>Document host-action shortcuts: `direct_document_host_action_runtime.py`<br>Uploaded-document preview/course payloads: `direct_document_preview_payloads.py`<br>Uploaded-document course analysis/generic plans: `direct_document_course_analysis.py`<br>Uploaded-document text shaping: `direct_document_preview_text.py`<br>Uploaded-document source refs: `direct_document_source_refs.py`<br>Uploaded-document course plans: `direct_document_course_lms_plan.py`, `direct_document_course_maritime_plans.py` (`direct_document_course_domain_plans.py` is compatibility exports)<br>Message builders: `direct_tool_message_runtime.py`<br>Session-memory fast paths: `direct_session_memory_runtime.py` |
| Native stream/provider quirks | `maritime-ai-service/app/engine/multi_agent/openai_stream_runtime.py` |
| Routing and supervisor behavior | `maritime-ai-service/app/engine/multi_agent/supervisor*.py` |
| Direct prompt assembly | `maritime-ai-service/app/engine/multi_agent/direct_prompts.py` (main assembly)<br>Tool binding: `direct_prompt_tool_binding.py`<br>Tool-context prompt builders: `direct_prompt_tool_context.py`<br>Turn contract and forced-skill prompt helpers: `direct_prompt_turn_contracts.py` |
| Tool registry | `maritime-ai-service/app/engine/tools/registry.py` and `maritime-ai-service/app/engine/multi_agent/tool_collection.py` |
| Tool policy and connection status | `maritime-ai-service/app/engine/multi_agent/tool_policy_session.py`, `maritime-ai-service/app/engine/tools/tool_capability_registry.py`, `docs/architecture/wiii-connect/CONNECTION_CONTRACT_V0.md` |
| LMS host actions | `maritime-ai-service/app/engine/context/action_tools.py`, `maritime-ai-service/app/engine/tools/lms_tools.py` |
| Document context | `maritime-ai-service/app/api/v1/document_context.py`, document runtime helpers |
| Uploaded-document preview/course contract | `maritime-ai-service/app/engine/multi_agent/document_preview_contract.py` |
| Config | `maritime-ai-service/app/core/config/_settings*.py` |
| Voice | `maritime-ai-service/app/api/v1/voice.py` |

## Frontend Navigation

| Need | Start here |
|---|---|
| Chat UI | `wiii-desktop/src/EmbedApp.tsx` |
| User input | `wiii-desktop/src/components/chat/ChatInput.tsx` |
| SSE assembly | `wiii-desktop/src/hooks/useSSEStream.ts` |
| Markdown | `wiii-desktop/src/components/common/MarkdownRenderer.tsx`, `wiii-desktop/src/styles/markdown.css` |
| Preview/apply UI | `wiii-desktop/src/components/layout/PreviewPanel.tsx` |
| Source references | `wiii-desktop/src/lib/source-references.ts` |
| Host bridge | `wiii-desktop/src/lib/embed-bridge.ts`, `wiii-desktop/src/lib/context-bridge.ts` |
| Pointy | `wiii-desktop/src/pointy-host/**` and `wiii-desktop/src/components/chat/PointyModeToggle.tsx` |
| Voice | `wiii-desktop/src/api/voice.ts`, voice mode/toggle components |
| Visual artifacts | `wiii-desktop/src/components/chat/VisualArtifactCard.tsx`, `wiii-desktop/src/components/common/InlineVisualFrame.tsx`; deterministic Code Studio fallback contracts, spec extraction, captions, registry, shell helpers, quality gates, and extracted primitive renderers live in backend `code_studio_scaffold_*` modules |

## Canonical Contracts

Keep these contracts explicit and tested:

- agent turn lifecycle
- native provider stream lifecycle
- tool call dispatch and result handling
- connection and capability snapshots before tool binding
- document context provenance and source references
- host action preview/apply approval
- SSE V3 event names and order
- frontend Markdown repair and rendering
- voice listening/speaking state
- visual artifact sandbox and frame sizing

## Where Not To Put Durable Knowledge

Avoid using these as canonical documentation:

- chat transcripts
- temporary local screenshots
- one-off script output
- stale branch names
- provider-specific debugging notes without date or owner
- untracked local scratch files

Promote durable findings into `docs/`, `specs/`, or an approved path-specific
`AGENTS.md`.
