# Authoritative Request Flow Contract

This document is the authoritative description of the backend request flow for chat.

Scope:

- API entry through user-visible response generation
- post-response scheduling through continuity update
- sync `/api/v1/chat` and streaming `/api/v1/chat/stream/v3` parity expectations

If runtime behavior changes, this file should be updated in the same change.

## Core Principle

Wiii has one authoritative request shape:

request -> session -> validation -> context -> execution -> output -> post-response scheduling -> continuity update

The API layer is transport.
The services layer is orchestration.
The execution layer is agent behavior.
The continuity layer is asynchronous follow-up.

## Authoritative Entry Points

Synchronous JSON path:

- `app/api/v1/chat.py::chat_completion`
- `app/services/chat_service.py::ChatService.process_message`
- `app/services/chat_orchestrator.py::ChatOrchestrator.process`

Streaming SSE path:

- `app/api/v1/chat_stream.py::chat_stream_v3`

Shared post-response continuity path:

- `app/services/living_continuity.py::schedule_post_response_continuity`

## Stage Ownership

### Stage 0: API Entry

Owner:

- `app/api/v1/chat.py`
- `app/api/v1/chat_stream.py`

Responsibilities:

- auth and rate-limit enforcement
- transport-specific request and response handling
- delegate business flow to the services layer

Non-responsibilities:

- no direct memory loading
- no prompt assembly
- no Living side effects beyond scheduling through the contract modules

### Stage 1: Session Normalization

Owner:

- `app/services/chat_orchestrator.py`
- `app/services/session_manager.py`

Responsibilities:

- normalize `thread_id` and `session_id`
- load or create `SessionContext`
- hydrate stable session state needed for this turn

Allowed live-turn mutation:

- session creation or lookup
- session state updates required for this turn

### Stage 2: Input Validation

Owner:

- `app/services/input_processor.py::validate`

Responsibilities:

- Guardian or Guardrails validation
- blocked-response short-circuiting
- blocked message logging when required

Rule:

- validation may stop the request, but it must not assemble prompt context

### Stage 3: Context Assembly

Owner:

- `app/services/input_processor.py::build_context`

Responsibilities:

- conversation history loading
- semantic memory and fact loading
- LMS page-aware and host context extraction from request payload
- conversation analysis and mood hints
- organization-scoped context threading

Rule:

- request-scoped context must be assembled here before execution whenever possible
- new memory, history, org, host, or page-context fetches should not be added ad hoc in API formatters

### Stage 4: Execution

Owner:

- `app/services/chat_orchestrator.py`
- `app/engine/multi_agent/graph.py`

Responsibilities:

- choose Multi-Agent or fallback execution path
- apply domain, org, and host-aware execution overlays inside the execution layer
- generate the authoritative answer payload plus execution metadata

Rule:

- prompt and execution state mutation belongs here, not in the API serializer or continuity scheduler

### Stage 5: Output Formatting

Owner:

- `app/services/output_processor.py`
- final API serialization in `app/api/v1/chat.py`

Responsibilities:

- validate response shape
- normalize sources and metadata
- serialize transport-specific response payloads

Rule:

- output formatting may reshape the response, but it must not fetch new request context

### Stage 6: Post-Response Scheduling

Owner:

- `app/services/background_tasks.py::BackgroundTaskRunner.schedule_all`
- `app/services/living_continuity.py::schedule_post_response_continuity`

Responsibilities:

- enqueue background persistence and summarization work
- enqueue Living continuity hooks
- enqueue LMS insight push when enabled and allowed by caller
- emit one stable continuity summary log for the finalized turn

Rule:

- this stage schedules asynchronous work only
- it must not block the user-visible response path on Living processing
- the finalized turn log should include transport type, org/domain scope,
  requested LMS-insight policy, and the scheduled hook summary

### Stage 7: Continuity Update

Owner:

- `app/services/living_continuity.py::_analyze_and_process_sentiment`
- related Living subsystems called from that contract

Responsibilities:

- routine tracking
- sentiment analysis
- emotion engine update
- episodic memory write
- optional LMS insight push

Rule:

- new post-response hooks should be attached here through the contract, not scattered across API or orchestration code

## Mutation Contract

During a live turn, direct state mutation is only allowed in these categories:

- session normalization and session-state upkeep
- blocked-message persistence required by validation
- chat history persistence for the current turn
- thread index upkeep for conversation discovery
- enqueueing background and continuity work

Everything else should either:

- stay inside request-local context assembly, or
- be deferred into post-response scheduling

## Sync and Streaming Parity

The streaming path may emit intermediate events, but it should preserve the same logical ordering:

1. session setup
2. validation and context assembly parity
3. execution
4. output emission
5. background scheduling
6. continuity scheduling

Streaming-specific transport behavior does not create a separate business contract.

### Streaming Lifecycle Observability

`/api/v1/chat/stream/v3` emits additive `chat_lifecycle` SSE events so clients
and acceptance harnesses can observe the live turn without parsing display copy
or waiting for terminal metadata.

Lifecycle payloads use schema `wiii.chat_runtime_lifecycle.v1` and include:

- `chat.accepted`
- `turn.prepared`
- `path.selected`
- `capability.checked`
- `finalization.completed` or `finalization.failed`
- `chat.done`
- `chat.error`

Rules:

- lifecycle events are observational only and must not drive LMS mutation
- lifecycle payloads must stay privacy-safe; do not include prompt text,
  raw document content, full user identifiers, secrets, or provider tokens
- path and capability state should be emitted from typed runtime state, not
  inferred from Vietnamese status labels
- existing `status`, `thinking`, `answer`, `metadata`, and `done` consumers must
  keep working when a client ignores `chat_lifecycle`

Policy note:

- sync `/api/v1/chat` and streaming `/api/v1/chat/stream/v3` both use the
	shared continuity contract with LMS post-response insights enabled by
	default
- callers may opt out explicitly through `include_lms_insights=False`, but
	transport alone is not a valid reason to disable LMS insight scheduling

## Change Rules

When adding a new chat capability, decide first which layer owns it:

- API transport
- session
- validation
- context assembly
- execution
- output formatting
- background scheduling
- continuity update

If the capability changes stage ordering, mutation rights, or introduces a new post-response hook, update this file in the same pull request.
