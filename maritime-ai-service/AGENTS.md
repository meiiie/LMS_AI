# AGENTS.md - Backend

Status: Active

Owner: Backend maintainers

Applies to: `maritime-ai-service/**`

This file narrows the repository-level guidance for backend work. Read the root
`AGENTS.md` first, then use this file for backend-specific navigation,
boundaries, and verification.

## Backend Mental Model

The backend owns Wiii Core, Wiii Org, Wiii Data, and most cross-surface runtime
contracts.

The safest way to read backend behavior is by runtime lane:

| Lane | Primary paths | What to protect |
|---|---|---|
| Chat transport | `app/api/v1/chat*.py`, `app/services/chat_*` | sync/stream parity, auth, session state, SSE shape |
| Agent runtime | `app/engine/multi_agent/**` | routing, tool loop, provider behavior, source propagation |
| RAG and memory | `app/repositories/**`, `app/services/**memory**`, ingestion paths | tenant filters, citations, provenance, durable state |
| Host and LMS | `app/engine/context/**`, `app/engine/tools/lms_tools.py`, document context API | preview before mutation, approval tokens, host capability checks |
| Voice and media | `app/api/v1/voice.py`, voice requirements/config | server-side secrets, feature flags, graceful fallback |
| Config and deploy | `app/core/config/**`, Docker, nginx, deploy scripts | production defaults, fail-closed behavior, rollback clarity |

## High-Risk Surfaces

Treat these as high-risk and keep changes narrow:

- auth, JWT, OAuth, refresh tokens, LMS token exchange
- organization and tenant filtering
- memory writes and retrieval query scope
- provider selection and model routing
- native tool calling and host actions
- SSE event names, ordering, and finalization
- production Docker, nginx, and deploy scripts
- secret handling and runtime settings persistence

For high-risk work, include rollback notes in the PR body.

## Runtime Contracts

Backend changes should preserve these contracts unless the PR explicitly changes
them:

- A chat turn must not expose raw provider tool-call JSON to the user.
- Tool calls must either execute through the tool loop or fail visibly.
- LMS mutating actions must require preview plus approval evidence.
- Source-backed answers must preserve source references and citations.
- Streaming and non-streaming paths should produce compatible final answers.
- Voice and media features must degrade gracefully when provider config is absent.
- Tenant/org context must be applied before retrieval, memory, or host action work.

## Where To Start

Use these entry points before editing:

- Chat request setup: `app/services/chat_orchestrator.py`
- SSE coordination: `app/services/chat_stream_coordinator.py`
- Direct/runtime tool loop: `app/engine/multi_agent/direct_tool_rounds_runtime.py`
- Native OpenAI-compatible stream handling: `app/engine/multi_agent/openai_stream_runtime.py`
- Tool registry and inventory: `app/engine/tools/registry.py`
- Host action helpers: `app/engine/context/action_tools.py`
- LMS tools: `app/engine/tools/lms_tools.py`
- Settings: `app/core/config/_settings*.py`

## Verification

Choose the smallest meaningful test set for the changed paths.

Common backend checks:

```powershell
cd maritime-ai-service
python -m pytest tests/unit/test_openai_stream_runtime.py tests/unit/test_direct_tool_rounds_runtime.py -q --tb=short
python -m pytest tests/unit/test_chat_stream_coordinator.py tests/unit/test_chat_request_flow.py -q --tb=short
python -m ruff check app/ tests/unit/ --select=E9,F63,F7
```

For config, auth, memory, LMS, or deploy changes, add focused tests and explicit
risk notes. Do not rely on manual localhost testing alone.

## Editing Guidance

- Prefer typed helper modules for stable contracts instead of spreading JSON
  shape assumptions across runtime and API code.
- Keep provider-specific quirks near provider adapters or stream parsers.
- Avoid adding broad feature flags without a tier, owner, and test.
- Do not commit `.env*`, local logs, generated output, or provider secrets.
- Do not mix deployment changes with chat/runtime behavior unless the issue
  explicitly requires it.
