# 🗺️ Maritime AI System Flow Diagram

**Version:** 3.0 (SOTA 2025 - Post Phase 2.4a)  
**Updated:** 2025-12-20  
**Team Board:** Complete system flow for developers

---

## 📊 High-Level Architecture

```mermaid
flowchart TB
    subgraph Client["🖥️ Client Layer"]
        A[LMS Frontend] --> B[/api/v1/chat/]
    end
    
    subgraph API["🔌 API Layer"]
        B --> C[ChatController]
        C --> D[ChatService]
    end
    
    subgraph Orchestrator["⚙️ Orchestration Layer"]
        D --> E[ChatOrchestrator]
        E --> F[InputProcessor]
        E --> G[OutputProcessor]
        E --> H[BackgroundTaskRunner]
    end
    
    subgraph Agents["🤖 Multi-Agent System (LangGraph)"]
        E --> I{Supervisor}
        I --> |rag| J[RAGAgent]
        I --> |tutor| K[TutorAgent]
        I --> |memory| L[MemoryAgent]
        I --> |direct| M[DirectResponse]
        J --> N[Grader]
        K --> N
        L --> N
        N --> O[Synthesizer]
        M --> O
    end
    
    subgraph Knowledge["📚 Knowledge Layer"]
        K --> P[CorrectiveRAG]
        P --> Q[HybridSearch]
        Q --> R[(Neo4j GraphRAG)]
        Q --> S[(PostgreSQL Vectors)]
        P --> T[SemanticCache]
    end
    
    subgraph Memory["🧠 Memory Layer"]
        F --> U[SemanticMemory]
        U --> V[FactExtractor]
        U --> W[InsightEngine]
        H --> U
    end
```

---

## 🔄 Complete Request Processing Flow

```mermaid
sequenceDiagram
    autonumber
    participant U as 👤 User
    participant API as 🔌 API
    participant O as ⚙️ Orchestrator
    participant I as 📥 InputProcessor
    participant S as 🎯 Supervisor
    participant T as 👨‍🏫 TutorAgent
    participant CRAG as 🔍 CorrectiveRAG
    participant G as ✅ Grader
    participant Syn as 📝 Synthesizer
    participant BG as 🔄 Background

    U->>API: POST {message, user_id, role}
    API->>O: process(request)
    
    rect rgb(230, 245, 255)
        Note over O,I: STAGE 1: Input Processing (~0.5s)
        O->>I: validate(request)
        I->>I: Guardian check
        O->>I: build_context()
        I->>I: Retrieve memories + history
    end
    
    rect rgb(255, 245, 230)
        Note over O,S: STAGE 2: Routing (~4-6s)
        O->>S: route(query)
        S->>S: Analyze intent
        S-->>T: tutor_agent
    end
    
    rect rgb(255, 230, 230)
        Note over T,CRAG: STAGE 3: CRAG Pipeline (~40-60s)
        T->>CRAG: tool_maritime_search()
        CRAG->>CRAG: Check SemanticCache
        alt Cache HIT (similarity ≥ 0.99)
            CRAG->>CRAG: ThinkingAdapter (5s)
        else Cache MISS
            CRAG->>CRAG: HybridSearch (1s)
            CRAG->>CRAG: Tiered Grading (3-20s)
            CRAG->>CRAG: Generate Answer (20-35s)
        end
        CRAG-->>T: sources + answer
    end
    
    rect rgb(230, 255, 230)
        Note over G,Syn: STAGE 4: Quality & Synthesis (~8-15s)
        T-->>G: response
        G->>G: Score quality
        G-->>Syn: approved
        Syn->>Syn: Format final response
    end
    
    rect rgb(245, 230, 255)
        Note over O,BG: STAGE 5: Background (~async)
        O->>BG: schedule_all()
        BG->>BG: Extract facts
        BG->>BG: Generate insights
        BG->>BG: Summarize history
    end
    
    O-->>API: InternalChatResponse
    API-->>U: JSON Response
```

---

## 🎯 Corrective RAG Pipeline (SOTA 2025)

```mermaid
flowchart TB
    subgraph Input["📥 Input"]
        A[Query] --> B{SemanticCache}
    end
    
    subgraph CacheCheck["⚡ Cache Check"]
        B --> |HIT ≥0.99| C[ThinkingAdapter]
        B --> |MISS| D[QueryAnalyzer]
    end
    
    subgraph Retrieval["🔍 Retrieval"]
        D --> E[HybridSearchService]
        E --> F[DenseSearch<br/>Gemini Embeddings]
        E --> G[SparseSearch<br/>PostgreSQL FTS]
        F --> H[RRF Reranker]
        G --> H
        H --> I[Top 10 Documents]
    end
    
    subgraph Grading["🎯 Tiered Grading (Phase 2.4a)"]
        I --> J[Hybrid Pre-filter]
        J --> K[MiniJudge LLM<br/>Parallel 10 docs]
        K --> L{≥2 Relevant?}
        L --> |YES| M[✅ EARLY EXIT<br/>Skip LLM Batch]
        L --> |NO| N[LLM Batch Grading<br/>~19s]
        M --> O[Graded Documents]
        N --> O
    end
    
    subgraph Generation["📝 Generation"]
        O --> P[GraphRAG Context]
        P --> Q[RAGAgent<br/>Gemini Flash]
        Q --> R[Native Thinking]
    end
    
    subgraph Reflection["🔄 Self-Correction"]
        R --> S{Confidence?}
        S --> |HIGH ≥0.85| T[Skip Verification]
        S --> |MEDIUM| U[Quick Verify]
        S --> |LOW| V[Full Verify + Rewrite]
        T --> W[Final Answer]
        U --> W
        V --> |retry| D
    end
    
    subgraph Output["📤 Output"]
        W --> X[Cache Response]
        X --> Y[Return Result]
        C --> Y
    end
    
    style M fill:#90EE90
    style L fill:#FFE4B5
    style C fill:#87CEEB
```

---

## 🏗️ Multi-Agent Graph (LangGraph)

```mermaid
stateDiagram-v2
    [*] --> Supervisor
    
    Supervisor --> DirectResponse: greeting/simple
    Supervisor --> MemoryAgent: personal question
    Supervisor --> TutorAgent: learning/teaching
    Supervisor --> RAGAgent: knowledge query
    
    DirectResponse --> Synthesizer
    
    MemoryAgent --> GraderAgent
    TutorAgent --> GraderAgent
    RAGAgent --> GraderAgent
    
    GraderAgent --> Synthesizer: passed
    GraderAgent --> TutorAgent: retry (if failed)
    
    Synthesizer --> [*]
    
    note right of Supervisor
        Routes based on intent:
        - Greeting → Direct
        - "Bạn nhớ tên tôi?" → Memory
        - "Giải thích Điều X" → Tutor
    end note
    
    note right of TutorAgent
        ReAct Loop:
        1. Think → Act → Observe
        2. Call tool_maritime_search
        3. Early exit on high confidence
    end note
    
    note right of GraderAgent
        Quality Control:
        - Score 1-10
        - Pass threshold: 6+
        - Vietnamese quality check
    end note
```

---

## 🧠 Memory & Personalization Flow

```mermaid
flowchart LR
    subgraph Input["📥 Request"]
        A[User Message] --> B[InputProcessor]
    end
    
    subgraph Retrieval["🔍 Memory Retrieval"]
        B --> C[SemanticMemory]
        C --> D[user_facts]
        C --> E[insights]
        C --> F[conversation_summary]
        C --> G[pronoun_style]
    end
    
    subgraph Pronoun["🗣️ Pronoun Adaptation"]
        G --> H{User style?}
        H --> |mình/cậu| I["AI: mình/cậu"]
        H --> |em/anh| J["AI: anh/em"]
        H --> |default| K["AI: tôi/bạn"]
    end
    
    subgraph Output["📤 Personalization"]
        D --> L[PromptLoader]
        E --> L
        I --> L
        J --> L
        K --> L
        L --> M[Dynamic System Prompt]
        M --> N[Agent Response]
    end
```

---

## ⚡ Tiered Document Grading (Phase 2.4a SOTA)

```mermaid
flowchart TB
    A[10 Documents] --> B[Tier 1: Hybrid Pre-filter]
    
    subgraph Tier1["⚡ Tier 1: Fast Filter (0ms)"]
        B --> C{Aggregate Score}
        C --> |HIGH ≥0.8| D[✅ Auto PASS]
        C --> |LOW ≤0.3| E[❌ Auto FAIL]
        C --> |UNCERTAIN| F[→ Tier 2]
    end
    
    subgraph Tier2["🤖 Tier 2: MiniJudge LLM (3-4s)"]
        F --> G[Parallel LLM Calls<br/>10 docs × LIGHT tier]
        G --> H{Results}
        H --> |RELEVANT ≥2| I[✨ EARLY EXIT]
        H --> |RELEVANT <2| J[→ Tier 3]
    end
    
    subgraph Tier3["🔬 Tier 3: LLM Batch (19s)"]
        J --> K[Full LLM Grading<br/>Batch of 3 docs]
        K --> L[Detailed Scores]
    end
    
    D --> M[Grading Result]
    E --> M
    I --> M
    L --> M
    
    style I fill:#90EE90,stroke:#228B22
    style D fill:#90EE90,stroke:#228B22
    style E fill:#FFB6C1,stroke:#DC143C
```

**Latency Savings:**
| Path | Previous | After 2.4a | Savings |
|------|----------|------------|---------|
| Tier 2 Early Exit | 23s | 3-4s | **~19s** |
| Full Tier 3 | 23s | 23s | 0s |

---

## 📊 Component Status (Dec 2025)

| Component | Status | Latency | Notes |
|-----------|--------|---------|-------|
| ChatOrchestrator | ✅ Active | - | Main pipeline |
| InputProcessor | ✅ Active | ~0.5s | Context + memory |
| Supervisor | ✅ Active | 4-6s | LangGraph routing |
| TutorAgent | ✅ Active | Variable | ReAct + CRAG |
| CorrectiveRAG | ✅ Optimized | 40-60s | Phase 2.4a |
| SemanticCache | ✅ Active | 0.1ms | 2hr TTL |
| Tiered Grading | ✅ SOTA | 3-20s | Early exit |
| ThinkingAdapter | ✅ Active | 5s | Cache adaptation |
| PromptLoader | ✅ Active | - | YAML injection |

---

## 🔗 Key Files Reference

| Layer | File | Purpose |
|-------|------|---------|
| API | `app/api/v1/chat.py` | Endpoint controller |
| Service | `app/services/chat_orchestrator.py` | Main orchestration |
| Service | `app/services/input_processor.py` | Context building |
| Service | `app/services/hybrid_search_service.py` | Dense + Sparse search |
| Agent | `app/engine/multi_agent/graph.py` | LangGraph workflow |
| Agent | `app/engine/multi_agent/agents/tutor_node.py` | Teaching agent |
| RAG | `app/engine/agentic_rag/corrective_rag.py` | CRAG pipeline |
| RAG | `app/engine/agentic_rag/retrieval_grader.py` | Tiered grading |
| RAG | `app/engine/agentic_rag/rag_agent.py` | RAG generation |
| Cache | `app/cache/semantic_cache.py` | Query caching |
| Config | `app/prompts/prompt_loader.py` | YAML loader |
| Config | `app/prompts/agents/tutor.yaml` | Tutor persona |

---

## 📈 Performance Benchmarks (Dec 2025)

| Scenario | Cold Path | Warm Cache | Target |
|----------|-----------|------------|--------|
| RAG Query | 85-90s | 45s | 60-65s |
| Simple Chat | 4-5s | 4-5s | <5s |
| Memory Query | 6-8s | 6-8s | <10s |

**Key Optimizations Applied:**
- ✅ Phase 2.4a: Early Exit saves 19s (60%+ queries)
- ✅ Semantic Cache: 2hr TTL, 0.1ms lookup
- ✅ ThinkingAdapter: 5s for cache hits
- ✅ Parallel MiniJudge: 10 docs in 3-4s
- ✅ Confidence-based iteration: Skip unnecessary loops
