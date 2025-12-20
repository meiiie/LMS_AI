# Maritime AI Service - System Architecture

**Version:** 3.1 (2025-12-20)  
**Purpose:** LMS Integration Preparation  
**Status:** Production Ready - Phase 2.4a SOTA Optimizations Applied

---

## Table of Contents

1. [High-Level Architecture](#high-level-architecture)
2. [Project Structure](#project-structure)
3. [Core Components Deep Dive](#core-components-deep-dive)
4. [Data Flow Diagrams](#data-flow-diagrams)
5. [SOTA Comparison](#sota-comparison)
6. [Integration Points for LMS](#integration-points-for-lms)
7. [Improvement Recommendations](#improvement-recommendations)

---

## High-Level Architecture

```mermaid
graph TB
    subgraph "Frontend Layer"
        LMS[LMS Frontend]
        Chatbot[Chatbot UI]
    end
    
    subgraph "API Layer"
        API[FastAPI v0.115.4]
        Chat["/api/v1/chat"]
        Stream["/api/v1/chat-stream"]
        Admin["/api/v1/admin"]
    end
    
    subgraph "Service Layer"
        ChatSvc[ChatService]
        GraphRAG[GraphRAGService]
        HybridSearch[HybridSearchService]
        Ingestion[MultimodalIngestionService]
    end
    
    subgraph "Engine Layer - Core AI"
        UA[UnifiedAgent<br>ReAct Pattern]
        CRAG[CorrectiveRAG<br>Self-Correction]
        MAG[Multi-Agent Graph<br>LangGraph]
    end
    
    subgraph "Specialized Agents"
        Supervisor[SupervisorAgent]
        RAG[RAGAgent]
        Tutor[TutorAgent]
        Memory[MemoryAgent]
        Grader[GraderAgent]
        KG[KGBuilderAgent]
    end
    
    subgraph "Data Layer"
        Neon[(Neon PostgreSQL<br>+ pgvector)]
        Neo4j[(Neo4j AuraDB<br>Knowledge Graph)]
        Supabase[(Supabase Storage<br>PDF Images)]
    end
    
    subgraph "External Services"
        Gemini[Google Gemini<br>3.0 Flash + Embedding]
    end
    
    LMS --> API
    Chatbot --> API
    API --> ChatSvc
    ChatSvc --> UA
    ChatSvc --> MAG
    UA --> CRAG
    MAG --> Supervisor
    Supervisor --> RAG
    Supervisor --> Tutor
    Supervisor --> Memory
    RAG --> Grader
    RAG --> GraphRAG
    GraphRAG --> HybridSearch
    GraphRAG --> Neo4j
    HybridSearch --> Neon
    Ingestion --> Supabase
    Ingestion --> KG
    KG --> Neo4j
```

---

## Project Structure

```
maritime-ai-service/
├── app/
│   ├── main.py                 # FastAPI app entry (9.5KB)
│   ├── api/v1/                 # REST endpoints
│   │   ├── chat.py             # Main chat endpoint (17KB)
│   │   ├── chat_stream.py      # SSE streaming (7KB)
│   │   ├── health.py           # Health checks (15KB)
│   │   ├── admin.py            # Admin operations
│   │   ├── knowledge.py        # Knowledge management
│   │   ├── memories.py         # Memory API
│   │   └── sources.py          # Source retrieval
│   │
│   ├── core/                   # Configuration
│   │   ├── config.py           # Settings (12KB, 220+ configs)
│   │   ├── database.py         # DB connection pooling
│   │   ├── security.py         # Auth/Security
│   │   └── rate_limit.py       # Rate limiting
│   │
│   ├── engine/                 # Core AI Logic
│   │   ├── unified_agent.py    # ReAct Agent (26KB)
│   │   ├── agentic_rag/        # Corrective RAG pipeline
│   │   ├── multi_agent/        # LangGraph multi-agent
│   │   ├── tools/              # LangChain tools
│   │   ├── memory_*.py         # Memory subsystem (5 files)
│   │   └── [10+ other engines]
│   │
│   ├── services/               # Business Logic
│   │   ├── chat_service.py     # Main orchestrator (58KB)
│   │   ├── graph_rag_service.py# GraphRAG (NEW)
│   │   ├── hybrid_search_service.py
│   │   └── multimodal_ingestion_service.py (38KB)
│   │
│   ├── repositories/           # Data Access Layer
│   │   ├── semantic_memory_repository.py (45KB)
│   │   ├── neo4j_knowledge_repository.py (35KB)
│   │   ├── dense_search_repository.py (20KB)
│   │   └── [4 more repositories]
│   │
│   ├── models/                 # Pydantic Schemas
│   │   ├── schemas.py          # API models (26KB)
│   │   └── [domain models]
│   │
│   └── prompts/                # YAML prompt configs
│
├── scripts/                    # Utility scripts
└── docs/                       # Documentation
```

---

## Core Components Deep Dive

### 1. Chat Processing Pipeline

```mermaid
sequenceDiagram
    participant User
    participant API as FastAPI
    participant ChatSvc as ChatService
    participant Guardian as GuardianAgent
    participant UA as UnifiedAgent
    participant CRAG as CorrectiveRAG
    participant Search as HybridSearch
    participant LLM as Gemini 2.5
    
    User->>API: POST /api/v1/chat
    API->>ChatSvc: process_message()
    ChatSvc->>Guardian: check_message()
    Guardian-->>ChatSvc: SafetyResult
    
    alt Message Blocked
        ChatSvc-->>User: Safety Warning
    else Message Safe
        ChatSvc->>UA: process(message)
        UA->>UA: ReAct Loop (max 5 iterations)
        UA->>CRAG: retrieve + verify
        CRAG->>Search: hybrid_search()
        Search-->>CRAG: sources[]
        CRAG->>LLM: generate_answer()
        LLM-->>CRAG: answer
        CRAG->>CRAG: verify_answer()
        CRAG-->>UA: CorrectiveRAGResult
        UA-->>ChatSvc: response
        ChatSvc-->>User: JSON Response
    end
```

### 2. Multi-Agent System (LangGraph)

```mermaid
stateDiagram-v2
    [*] --> Supervisor
    Supervisor --> RAG: knowledge_query
    Supervisor --> Tutor: teaching_request
    Supervisor --> Memory: context_needed
    Supervisor --> Direct: simple_greeting
    
    RAG --> Grader
    Tutor --> Grader
    Memory --> Grader
    
    Grader --> Synthesizer: score >= 7.0
    Grader --> RAG: score < 7.0 (rewrite)
    
    Direct --> Synthesizer
    Synthesizer --> [*]
```

| Agent | Responsibility | Key Features |
|-------|---------------|--------------|
| **Supervisor** | Routing + Synthesis | LLM-based intent classification |
| **RAGAgent** | Knowledge retrieval | GraphRAG integration |
| **TutorAgent** | Teaching/explanation | Pedagogical approach |
| **MemoryAgent** | User context | Cross-session memory |
| **GraderAgent** | Quality control | Score-based re-routing |
| **KGBuilderAgent** | Entity extraction | Neo4j storage |

### 3. Search Architecture

```mermaid
graph LR
    subgraph "Query Processing"
        Q[User Query]
        QA[QueryAnalyzer]
        QR[QueryRewriter]
    end
    
    subgraph "GraphRAGService"
        GRS[search_with_graph_context]
        KGE[Entity Extraction]
    end
    
    subgraph "HybridSearchService"
        Dense[Dense Search<br>pgvector]
        Sparse[Sparse Search<br>tsvector]
        RRF[RRF Reranker]
    end
    
    subgraph "Entity Context"
        Neo4j[(Neo4j)]
        EC[Entity Context]
    end
    
    Q --> QA
    QA --> QR
    QR --> GRS
    GRS --> KGE
    GRS --> Dense
    GRS --> Sparse
    Dense --> RRF
    Sparse --> RRF
    KGE --> Neo4j
    Neo4j --> EC
    RRF --> |Chunks|GRS
    EC --> |Entities|GRS
```

| Search Type | Technology | Purpose |
|------------|------------|---------|
| Dense | pgvector (HNSW) | Semantic similarity |
| Sparse | PostgreSQL tsvector | Keyword matching |
| RRF | Custom reranker | Result fusion |
| Graph | Neo4j | Entity relationships |

### 4. Memory Subsystem

```mermaid
graph TB
    subgraph "Memory Components"
        MM[MemoryManager<br>Deduplication]
        MC[MemoryCompression<br>Summarization]
        MS[MemorySummarizer]
        SMR[SemanticMemoryRepository<br>45KB, pgvector]
    end
    
    subgraph "Memory Types"
        FACT[User Facts<br>name, job, preferences]
        CONV[Conversation<br>Context + History]
        INSIGHT[Insights<br>Learning patterns]
    end
    
    MM --> SMR
    MC --> SMR
    MS --> SMR
    
    SMR --> FACT
    SMR --> CONV
    SMR --> INSIGHT
```

| Component | Purpose | Key Feature |
|-----------|---------|-------------|
| MemoryManager | "Check before Write" | LLM-based deduplication |
| MemoryCompression | Long-term storage | Summarization |
| SemanticMemoryRepository | CRUD + Search | Cross-session persistence |

### 5. Ingestion Pipeline

```mermaid
graph LR
    PDF[PDF Upload] --> PyMuPDF[PyMuPDF<br>Page Images]
    PyMuPDF --> Upload[Supabase Storage]
    Upload --> Vision{Page Analysis}
    Vision -->|Complex| VisionAPI[Gemini Vision]
    Vision -->|Simple| Direct[Direct Extract]
    VisionAPI --> Chunk[Semantic Chunking]
    Direct --> Chunk
    Chunk --> Context[Context Enrichment<br>Contextual RAG]
    Context --> Embed[Gemini Embedding]
    Embed --> Store[(Neon pgvector)]
    
    Chunk --> KG[KGBuilderAgent]
    KG --> Neo4j[(Neo4j)]
```

---

## SOTA Comparison

| Feature | Our Implementation | SOTA 2025 | Status |
|---------|-------------------|-----------|--------|
| **RAG Architecture** | Corrective RAG + Multi-Agent | Agentic RAG with self-correction | ✅ SOTA |
| **GraphRAG** | Entity extraction + Neo4j context | Microsoft GraphRAG pattern | ✅ SOTA |
| **Hybrid Search** | Dense + Sparse + RRF | Hybrid with reranking | ✅ SOTA |
| **Multi-Agent** | LangGraph Supervisor pattern | Hierarchical agents | ✅ SOTA |
| **Memory** | Cross-session + Deduplication | Long-term memory | ✅ SOTA |
| **Embeddings** | Gemini gemini-embedding-001 (768d) | SOTA embeddings | ✅ SOTA |
| **Chunking** | Semantic + Maritime patterns | Adaptive chunking | ✅ SOTA |
| **Context Enrichment** | Anthropic-style contextual | Contextual RAG | ✅ SOTA |
| **Multimodal** | Vision API for PDFs | Multimodal RAG | ✅ SOTA |
| **Quality Control** | Grader + Verification | Answer verification | ✅ SOTA |

---

## Integration Points for LMS

### API Endpoints for LMS

| Endpoint | Method | Purpose | LMS Integration |
|----------|--------|---------|-----------------|
| `/api/v1/chat` | POST | Main chat | Primary integration |
| `/api/v1/chat-stream` | POST | SSE streaming | Real-time responses |
| `/api/v1/memories` | GET/POST | User memory | Learning profile |
| `/api/v1/insights` | GET | Learning insights | Analytics |
| `/api/v1/sources` | GET | Source citations | Evidence links |

### Authentication & Security

```python
# Current: API Key + User ID/Session ID
headers = {
    "X-API-Key": "your-api-key",
    "X-User-ID": "student-123",
    "X-Session-ID": "session-abc"
}
```

### Recommended LMS Integration Flow

```mermaid
sequenceDiagram
    participant LMS
    participant Gateway as API Gateway
    participant Auth as Auth Service
    participant Maritime as Maritime AI
    participant DB as LMS Database
    
    LMS->>Gateway: Chat Request + JWT
    Gateway->>Auth: Validate JWT
    Auth-->>Gateway: User Context
    Gateway->>Maritime: Forward + X-User-ID
    Maritime-->>Gateway: AI Response
    Gateway->>DB: Log Interaction
    Gateway-->>LMS: Response + Sources
```

---

## Improvement Recommendations

### High Priority (LMS Integration)

| Area | Current | Recommendation | Impact |
|------|---------|----------------|--------|
| **Auth** | API Key | OAuth2/JWT integration | 🔴 Critical |
| **Rate Limiting** | Per-endpoint | Per-user quotas | 🟡 Medium |
| **Analytics Events** | Minimal | Full event logging | 🔴 Critical |
| **Webhook Support** | None | Async notifications | 🟡 Medium |

### Medium Priority (Performance)

| Area | Current | Recommendation | Impact |
|------|---------|----------------|--------|
| **Entity Extraction** | Per-page | Batch processing | 🟡 Medium |
| **Neo4j Writes** | Sequential | Batch writes | 🟡 Medium |
| **Response Caching** | None | Redis cache | 🟢 Low |

### Future Enhancements

| Feature | Description | SOTA Reference |
|---------|-------------|----------------|
| **Feedback Loop** | User ratings → model improvement | Continuous learning |
| **Multi-hop Queries** | Graph traversal for complex Q&A | GraphRAG advanced |
| **Voice Interface** | Speech-to-text integration | Multimodal |
| **Proactive Learning** | Push notifications | Phase 9 planned |

---

## Technology Stack Summary

| Layer | Technology | Version |
|-------|------------|---------|
| **Framework** | FastAPI | 0.115.4 |
| **LLM** | Google Gemini | 3.0 Flash Preview |
| **Embeddings** | Gemini | gemini-embedding-001 |
| **Orchestration** | LangGraph | 0.2.x |
| **Vector DB** | Neon PostgreSQL + pgvector | 0.7.x |
| **Graph DB** | Neo4j AuraDB | 5.x |
| **Storage** | Supabase Storage | - |
| **PDF Processing** | PyMuPDF | 1.24.x |

---

## File Size Analysis (Top 10)

| File | Size | Purpose |
|------|------|---------|
| `chat_service.py` | 58KB | Main orchestrator |
| `semantic_memory_repository.py` | 45KB | Memory CRUD |
| `multimodal_ingestion_service.py` | 38KB | PDF pipeline |
| `neo4j_knowledge_repository.py` | 35KB | Graph operations |
| `rag_agent.py` | 27KB | RAG logic |
| `unified_agent.py` | 26KB | ReAct agent |
| `schemas.py` | 27KB | API models |
| `rrf_reranker.py` | 22KB | Search reranking |
| `dense_search_repository.py` | 21KB | Vector search |
| `conversation_analyzer.py` | 16KB | Context analysis |

---

**Document Generated:** 2025-12-14  
**Total Components Analyzed:** 70+ files  
**Architecture Pattern:** Hybrid Agentic-GraphRAG with Multi-Agent Orchestration
