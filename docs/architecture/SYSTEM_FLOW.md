# 🗺️ Maritime AI System Flow Diagram

**Version:** 2.0 (SOTA 2025)  
**Updated:** 2025-12-20  
**Team Board:** Complete system flow for developers

---

## 📊 High-Level Architecture

```mermaid
flowchart TB
    subgraph Client["Client Layer"]
        A[LMS Frontend] --> B[/api/v1/chat/]
    end
    
    subgraph API["API Layer"]
        B --> C[ChatController]
        C --> D[ChatService]
    end
    
    subgraph Orchestrator["Orchestration Layer"]
        D --> E[ChatOrchestrator]
        E --> F[InputProcessor]
        E --> G[OutputProcessor]
        E --> H[BackgroundTaskRunner]
    end
    
    subgraph Agents["Multi-Agent System"]
        E --> I{Supervisor}
        I --> |rag| J[RAGAgent]
        I --> |tutor| K[TutorAgent]
        I --> |memory| L[MemoryAgent]
        I --> |direct| M[DirectResponse]
    end
    
    subgraph Knowledge["Knowledge Layer"]
        J --> N[CorrectiveRAG]
        N --> O[HybridSearch]
        O --> P[(Neo4j)]
        O --> Q[(PostgreSQL)]
    end
    
    subgraph Memory["Memory Layer"]
        F --> R[SemanticMemory]
        R --> S[FactExtractor]
        R --> T[InsightEngine]
        H --> R
    end
```

---

## 🔄 Request Processing Flow

```mermaid
sequenceDiagram
    participant U as User
    participant API as /api/v1/chat
    participant O as Orchestrator
    participant I as InputProcessor
    participant S as Supervisor
    participant T as TutorAgent
    participant R as RAGAgent
    participant Out as OutputProcessor
    participant BG as BackgroundTasks
    
    U->>API: POST {message, user_id, role}
    API->>O: process(request)
    
    rect rgb(230, 245, 255)
        Note over O,I: STAGE 1: Input Processing
        O->>I: validate(request)
        I->>I: Guardian/Guardrails check
        O->>I: build_context(request)
        I->>I: Retrieve memories, history, facts
    end
    
    rect rgb(255, 245, 230)
        Note over O,T: STAGE 2: Agent Processing
        O->>S: route(query)
        S-->>T: tutor_agent
        T->>R: tool_maritime_search()
        R->>R: CorrectiveRAG pipeline
        R-->>T: sources + answer
        T-->>O: final_response
    end
    
    rect rgb(230, 255, 230)
        Note over O,BG: STAGE 3: Output & Background
        O->>Out: format_response()
        O->>BG: schedule_all()
        BG->>BG: Store facts, insights
    end
    
    O-->>API: InternalChatResponse
    API-->>U: JSON Response
```

---

## 🧠 Memory & Personalization Flow

```mermaid
flowchart LR
    subgraph Input["Request Context"]
        A[User Message] --> B[InputProcessor]
        B --> C{Build Context}
    end
    
    subgraph Retrieval["Memory Retrieval"]
        C --> D[SemanticMemory]
        D --> E[user_facts]
        D --> F[insights]
        D --> G[conversation_summary]
    end
    
    subgraph Pronoun["Pronoun Adaptation"]
        C --> H[detect_pronoun_style]
        H --> I{User style?}
        I --> |mình/cậu| J["AI: mình/cậu"]
        I --> |em/anh| K["AI: anh/em"]
        I --> |default| L["AI: tôi/bạn"]
    end
    
    subgraph Output["Response Personalization"]
        E --> M[PromptLoader]
        F --> M
        L --> M
        M --> N[Dynamic System Prompt]
        N --> O[Agent Response]
    end
```

---

## 📝 Pronoun Handling (CHỈ THỊ SỐ 20)

```mermaid
flowchart TD
    A[User Message] --> B{detect_pronoun_style}
    
    B --> |"mình, tớ"| C["VALID_PRONOUN_PAIRS['mình']"]
    C --> D["user_called: 'cậu'<br/>ai_self: 'mình'"]
    
    B --> |"em + context"| E["VALID_PRONOUN_PAIRS['em']"]
    E --> F["user_called: 'em'<br/>ai_self: 'anh'"]
    
    B --> |"anh, chị"| G["VALID_PRONOUN_PAIRS['anh/chị']"]
    G --> H["user_called: 'anh/chị'<br/>ai_self: 'em'"]
    
    B --> |"tôi, default"| I["Default"]
    I --> J["user_called: 'bạn'<br/>ai_self: 'tôi'"]
    
    D --> K[SessionState.pronoun_style]
    F --> K
    H --> K
    J --> K
    
    K --> L[PromptLoader.build_system_prompt]
    L --> M[get_pronoun_instruction]
    M --> N[Injected into System Prompt]
```

### Default Pronouns
- **Mặc định:** AI xưng "tôi", gọi user là "bạn"
- **Thay đổi khi:** User dùng cách xưng hô khác (mình/cậu, em/anh...)
- **Nguồn:** Semantic Memory + Session State

---

## 🎯 YAML Prompt Injection Flow (TO BE IMPLEMENTED)

```mermaid
flowchart TD
    subgraph Config["YAML Configuration"]
        A[_shared.yaml] --> B[Thinking rules]
        A --> C[Tool calling rules]
        D[tutor.yaml] --> E[Persona]
        D --> F[Variations]
        D --> G[Empathy patterns]
        D --> H[Few-shot examples]
    end
    
    subgraph Loader["PromptLoader"]
        I[get_prompt_loader] --> J[build_system_prompt]
        J --> K[Merge shared + agent config]
        J --> L[get_random_opening]
        J --> M[detect_empathy_needed]
    end
    
    subgraph Agent["TutorAgentNode"]
        N[__init__] --> I
        O[_build_system_prompt] --> J
        O --> P[Add tool instructions]
        O --> Q[Final System Prompt]
    end
    
    E --> K
    F --> L
    G --> M
    H --> K
```

---

## 📊 Component Status

| Component | Status | Notes |
|-----------|--------|-------|
| ChatOrchestrator | ✅ Active | Main pipeline |
| InputProcessor | ✅ Active | Context building |
| TutorAgentNode | ⚠️ TO FIX | Hardcoded prompt |
| RAGAgent | ⚠️ TO FIX | Inline prompt |
| PromptLoader | ✅ Loaded | Not injected |
| unified_agent | ⚠️ Deprecated | Keep 2 weeks |

---

## 🔗 Key Files Reference

| Layer | File | Purpose |
|-------|------|---------|
| API | `app/api/v1/chat.py` | Endpoint controller |
| Service | `app/services/chat_orchestrator.py` | Main orchestration |
| Service | `app/services/input_processor.py` | Context building |
| Agent | `app/engine/multi_agent/agents/tutor_node.py` | Teaching agent |
| Agent | `app/engine/agentic_rag/rag_agent.py` | RAG pipeline |
| Config | `app/prompts/prompt_loader.py` | YAML loader |
| Config | `app/prompts/agents/tutor.yaml` | Tutor persona |
