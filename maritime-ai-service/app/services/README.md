# Services Layer

Business logic orchestration layer that coordinates between API and Engine layers.

---

## Overview

The Services layer follows **Clean Architecture** principles with specialized processors and orchestrators. After the refactoring (2025-12-14), this layer uses:

- **Facade Pattern**: `chat_service.py` as thin entry point
- **Pipeline Pattern**: `chat_orchestrator.py` for staged processing
- **Processor Pattern**: Specialized input/output handlers
- **Singleton Pattern**: Lazy initialization with dependency injection

---

## Folder Structure

```
app/services/
├── chat_service.py              # 🎯 FACADE - Main entry point (310 lines)
├── REQUEST_FLOW_CONTRACT.md     # 🧭 Authoritative request flow and mutation contract
├── chat_orchestrator.py         # 🔄 PIPELINE - authoritative request orchestration
├── session_manager.py           # 📦 Session & state management
├── input_processor.py           # 🛡️ Validation, Guardian, context
├── output_processor.py          # 📤 Response formatting
├── thinking_post_processor.py   # 🧠 Centralized thinking extraction (CHỈ THỊ SỐ 29 v8)
├── background_tasks.py          # ⏳ Async task runner
├── living_continuity.py         # 🔗 Core-to-Living post-response contract
├── routine_post_response.py     # 🔁 Routine-tracking post-response helper
├── sentiment_post_response.py   # 💓 Living sentiment post-response helper
├── lms_post_response.py         # 🎓 LMS post-response helper
├── chat_context_builder.py      # Context assembly
├── chat_response_builder.py     # Response assembly
├── multimodal_ingestion_service.py  # PDF ingestion pipeline
├── hybrid_search_service.py     # Dense + Sparse search
├── graph_rag_service.py         # GraphRAG with Neo4j
├── chunking_service.py          # Document chunking
├── learning_graph_service.py    # Learning path management
├── object_storage.py            # Object storage (MinIO / S3-compatible)
├── event_callback_service.py    # LMS webhooks (pending)
└── README.md                    # This file
```

---

## Architecture

Authoritative request contract:

- `REQUEST_FLOW_CONTRACT.md` is the source of truth for the chat request path
- update it whenever stage ordering, mutation rights, or post-response hooks change

### Pipeline Flow (ChatOrchestrator)

```
┌──────────────────────────────────────────────────────────────────┐
│                    CHAT PROCESSING PIPELINE                       │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│   ChatRequest                                                     │
│        │                                                          │
│        ▼                                                          │
│   ┌─────────────────┐                                            │
│   │ STAGE 1: SESSION│  SessionManager.get_or_create()            │
│   │   Management    │  → SessionContext, SessionState            │
│   └────────┬────────┘                                            │
│            ▼                                                      │
│   ┌─────────────────┐                                            │
│   │ STAGE 2: INPUT  │  InputProcessor.validate()                 │
│   │   Validation    │  → Guardian Agent / Guardrails             │
│   └────────┬────────┘                                            │
│            ▼                                                      │
│   ┌─────────────────┐                                            │
│   │ STAGE 3: CONTEXT│  InputProcessor.build_context()            │
│   │   Building      │  → Memory, History, Insights, LMS          │
│   └────────┬────────┘                                            │
│            ▼                                                      │
│   ┌─────────────────┐                                            │
│   │ STAGE 4: AGENT  │  WiiiRunner.run()                           │
│   │   Processing    │  → Supervisor routes to specialized agents  │
│   └────────┬────────┘                                            │
│            ▼                                                      │
│   ┌─────────────────┐                                            │
│   │ STAGE 5: OUTPUT │  OutputProcessor.validate_and_format()     │
│   │   Formatting    │  → Source merging, validation              │
│   └────────┬────────┘                                            │
│            ▼                                                      │
│   ┌─────────────────┐                                            │
│   │ STAGE 6: POST-  │  post_turn_lifecycle scheduling           │
│   │   RESPONSE      │  + living_continuity.schedule_post_...     │
│   │   Scheduling    │  → Background + continuity hooks           │
│   └────────┬────────┘                                            │
│            ▼                                                      │
│   ┌─────────────────┐                                            │
│   │ STAGE 7:        │  living_continuity worker paths            │
│   │   CONTINUITY    │  → sentiment, routine, episodic memory,    │
│   │   UPDATE        │    optional LMS insight execution          │
│   └────────┬────────┘                                            │
│            ▼                                                      │
│   InternalChatResponse                                            │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Core Services

### ChatService (Facade)

**File:** `chat_service.py` (~310 lines)  
**Pattern:** Facade  
**Purpose:** Main entry point, wires dependencies, delegates to orchestrator

```python
class ChatService:
    async def process_message(request: ChatRequest) -> InternalChatResponse:
        return await self._orchestrator.process(request)
```

**Key Features:**
- Initializes all dependencies on startup
- Lazy initialization of optional components
- Backward compatible API

---

### ChatOrchestrator (Pipeline)

**File:** `chat_orchestrator.py` (~320 lines)  
**Pattern:** Pipeline / Orchestrator  
**Purpose:** Coordinates the authoritative request pipeline and finalization seam

Contract note:

- the authoritative stage contract lives in `REQUEST_FLOW_CONTRACT.md`
- post-response continuity scheduling now shares one contract with the streaming path

```python
class ChatOrchestrator:
    async def process(request, background_save) -> InternalChatResponse:
        # Stage 1: Session
        # Stage 2: Validate
        # Stage 3: Context
        # Stage 4: Agent
        # Stage 5: Output
        # Stage 6: Post-response scheduling
        # Stage 7: Continuity update (via shared contract)
```

---

### SessionManager

**File:** `session_manager.py` (~230 lines)  
**Pattern:** Singleton Service  
**Purpose:** Session CRUD and anti-repetition state

**Data Classes:**
- `SessionState`: Tracks phrases, name usage, pronoun style
- `SessionContext`: Complete session info for request

---

### InputProcessor

**File:** `input_processor.py` (~380 lines)  
**Pattern:** Processor Service  
**Purpose:** Validation, Guardian, pronoun detection, context building

**Key Methods:**
- `validate()`: Guardian Agent / Guardrails
- `build_context()`: Memory, history, insights retrieval
- `extract_user_name()`: Vietnamese/English patterns
- `validate_pronoun_request()`: Custom pronoun validation

---

### OutputProcessor

**File:** `output_processor.py` (~220 lines)  
**Pattern:** Processor Service  
**Purpose:** Response formatting, validation, source merging

**Key Methods:**
- `validate_and_format()`: Output validation + formatting
- `merge_same_page_sources()`: Combine same-page citations
- `format_sources()`: Raw dict → Source objects
- `create_blocked_response()`: Blocked content response

---

### BackgroundTaskRunner

**File:** `background_tasks.py` (~260 lines)  
**Pattern:** Task Runner  
**Purpose:** Centralized async task management

**Tasks Managed:**
- Save chat messages
- Store semantic memory interactions
- Extract behavioral insights
- Update learning profile
- Memory summarization

### Living Continuity Contract

**File:** `living_continuity.py`
**Purpose:** Centralized scheduling boundary for post-response continuity work

**Hooks Managed:**
- routine tracking
- sentiment and emotion continuity
- episodic memory write
- optional LMS insight push

**Supporting helpers:** `routine_post_response.py`, `sentiment_post_response.py`, `lms_post_response.py`
- isolates routine-tracking scheduling from the broader Living continuity contract
- isolates Living sentiment scheduling from the broader Living continuity contract while preserving the existing sentiment-analysis compatibility symbol
- isolates LMS insight scheduling from the broader Living continuity contract
- lets Core/Living orchestration depend on narrow post-response adapters instead of integration details

---

## Other Services

### HybridSearchService

Dense + Sparse search with RRF reranking.

```python
await hybrid_search.search(query, limit=5)
# Returns: Combined results from pgvector + tsvector
```

### MultimodalIngestionService

PDF ingestion pipeline: Rasterize → Upload → Vision → Chunk → Index

```python
await ingestion_service.ingest_document(pdf_path)
```

### GraphRAGService

Knowledge Graph integration with Neo4j.

---

## Dependencies

```
chat_service.py (Facade)
    ├── chat_orchestrator.py
    │       ├── session_manager.py
    │       ├── input_processor.py
    │       ├── output_processor.py
    │       └── background_tasks.py
    ├── chat_context_builder.py
    └── chat_response_builder.py
```

---

## Usage

```python
from app.services.chat_service import get_chat_service

chat_service = get_chat_service()
response = await chat_service.process_message(request)
```

---

## SOTA Compliance (2025-12-14)

| Pattern | Status | Implementation |
|---------|--------|----------------|
| Clean Architecture | ✅ | Separated concerns into processors |
| Facade Pattern | ✅ | ChatService as thin entry point |
| Pipeline Pattern | ✅ | 7-stage request contract |
| Dependency Injection | ✅ | init_*() functions |
| Singleton Services | ✅ | get_*() functions |

---

## Audit Status

| File | Status | Notes |
|------|--------|-------|
| `chat_service.py` | ✅ Refactored | 1263 → 310 lines |
| `chat_orchestrator.py` | ✅ NEW | Pipeline orchestration |
| `session_manager.py` | ✅ NEW | Session management |
| `input_processor.py` | ✅ NEW | Input processing |
| `output_processor.py` | ✅ NEW | Output processing |
| `background_tasks.py` | ✅ NEW | Async tasks |
| `event_callback_service.py` | ⚠️ PENDING | Awaiting LMS integration |

---

*Last Updated: 2025-12-16 (CHỈ THỊ SỐ 29 v8 - Centralized Thinking)*
