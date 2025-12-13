# Changelog

All notable changes to Maritime AI Tutor Service.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Added
- Phase 9: Proactive Learning (planned)
- Phase 12: Scheduled Tasks (planned)

---

## [1.0.0] - 2025-12-13

### Added

#### Phase 7: Agentic RAG
- `QueryAnalyzer` - Analyze query complexity
- `RetrievalGrader` - Grade document relevance
- `QueryRewriter` - Improve failed queries
- `AnswerVerifier` - Detect hallucinations
- `CorrectiveRAG` - Self-correcting RAG orchestrator

#### Phase 8: Multi-Agent System
- `SupervisorAgent` - Route queries to specialists
- `RAGAgentNode` - Knowledge retrieval specialist
- `TutorAgentNode` - Teaching specialist
- `MemoryAgentNode` - User context specialist
- `GraderAgentNode` - Quality control specialist
- `LangGraph` workflow integration

#### Phase 10: Explicit Memory Control
- `tool_remember` - User can say "Remember that..."
- `tool_forget` - User can say "Forget..."
- `tool_list_memories` - User can see stored memories
- `tool_clear_all_memories` - Factory reset

#### Phase 11: Memory Compression
- `MemoryCompressionEngine` - 70-90% token savings
- Intelligent summarization
- Fact deduplication

### Refactoring
- **Tool Registry (`app/engine/tools/`)**:
  - Implemented SOTA 2025 **Tool Registry Pattern** for modular tool management.
  - Extracted 7 tools from `unified_agent.py` into separate modules (`rag_tools.py`, `memory_tools.py`).
  - Added **Category-based Loading** (RAG, Memory, Control).
  - Reduced `unified_agent.py` size by ~400 lines (40%).

- **Agent Registry (`app/engine/agents/`)**:
  - Implemented **Agent Registry Pattern** (similar to Tool Registry).
  - Created `AgentConfig` dataclass with CrewAI-inspired fields (role, goal, tools).
  - Added `AgentTracer` for observability and request tracing.
  - 5 pre-defined agent configs (RAG, Tutor, Memory, Grader, Supervisor).

- **Persona YAML Refactor (`app/prompts/`)**:
  - Implemented CrewAI-aligned YAML structure with `extends` inheritance.
  - Created `base/_shared.yaml` for common rules (tool_calling, reasoning).
  - Refactored personas to `agents/` folder: `tutor.yaml`, `assistant.yaml`, `rag.yaml`, `memory.yaml`.
  - Reduced lines: ~589 → ~350 (40% reduction).
  - Updated `prompt_loader.py` with inheritance support.

- **Project Restructure (Audit & Cleanup)**:
  - Moved `RAGAgent` from `tools/rag_tool.py` → `agentic_rag/rag_agent.py`.
  - Moved `TutorAgent` from `tools/tutor_agent.py` → `engine/tutor/tutor_agent.py`.
  - Renamed multi-agent wrappers: `rag_agent.py` → `rag_node.py`, `tutor_agent.py` → `tutor_node.py`.
  - Deleted legacy YAML files from `prompts/` root.
  - Updated all affected imports (chat_service, health, graph).

- **Database Models Cleanup**:
  - Removed 3 unused legacy SQLAlchemy models from `database.py`: `MemoriStoreModel`, `LearningProfileModel`, `ConversationSessionModel`.
  - Reduced `database.py` from 282 → ~170 lines (40%).

- **ChatService Refactoring**:
  - Extracted `ChatContextBuilder` module for context building logic.
  - Extracted `ChatResponseBuilder` module for response formatting.
  - Delegated `_merge_same_page_sources` to `ChatResponseBuilder` (-58 lines).
  - Reduced `chat_service.py` from 59 KB → 56.7 KB.

- **Unified Agent**:
  - Updated to use dynamic tool importing from registry.
  - Improved code organization and maintainability.

### Features
- **Phase 11: Semantic User Memory**:
  - Implemented `SemanticMemory` engine with Vector Store integration.
- Updated `config.py` with new feature flags

### Changed
- Updated `unified_agent.py` with new memory tools
- Updated `chat_service.py` with Multi-Agent integration
- Updated `config.py` with new feature flags

### Removed
- `app/engine/agents/` - Legacy ChatAgent (deprecated)

---

## [0.9.0] - 2025-12-01

### Added
- Knowledge Graph v1.0 (Hybrid Neon + Neo4j)
- Thread-based Sessions
- Admin Document API
- Streaming API (SSE)
- Source Highlighting with bounding boxes

---

## [0.8.0] - 2025-11-15

### Added
- Semantic Memory v0.5
- Insight Engine
- Guardian Agent v0.8.1
- Multimodal RAG v1.0

---

## [0.7.0] - 2025-11-01

### Added
- Hybrid Search v0.6 (Dense + Sparse + RRF)
- Unified Agent with ReAct pattern
- Role-based prompting

---

## [0.6.0] - 2025-10-15

### Added
- Basic RAG with pgvector
- TutorAgent for teaching sessions
- Learning profile tracking

---

## [0.5.0] - 2025-10-01

### Added
- Initial release
- Basic chat functionality
- Maritime knowledge base integration
