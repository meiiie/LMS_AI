# Changelog

All notable changes to Maritime AI Tutor Service.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

### Fixed (2025-12-18)
- **Gemini 2.5 Flash Content Block Handling**:
  - Fixed `'list' object has no attribute 'strip'` errors across 16 files (25 locations)
  - Root cause: Gemini 2.5 Flash returns `response.content` as list of content blocks when `thinking_enabled=True`
  - Solution: Implemented `extract_thinking_from_response()` utility for consistent content extraction
  - Affected agents: RetrievalGrader, AnswerVerifier, QueryAnalyzer, QueryRewriter, RAGAgent
  - Affected memory: MemorySummarizer, MemoryConsolidator, MemoryCompression, InsightExtractor
  - Affected services: GuardianAgent, ContextEnricher, HydeService, Supervisor, TutorNode
  - Result: LLM grading/verification now works correctly with 88% confidence scores

- **SOTA Repository Error Fixes**:
  - Fixed `'NoneType' object is not iterable` in `update_fact()` (Root cause: `_merge_insight()` passing `embedding=None`)
  - Solution: Added explicit `update_metadata_only()` API following Single Responsibility Principle
  - Added validation to `update_fact()` requiring non-None embedding
  - Fixed Neo4j defunct connection errors with Aura-optimized settings:
    - `max_connection_lifetime=3000` (50 mins < Aura's 60 min timeout)
    - `liveness_check_timeout=300` (5 minutes)
  - Added `neo4j_retry` decorator with exponential backoff for transient failures

### Added
- **Contextual RAG (Anthropic-style)**:
  - `ContextEnricher` class for LLM-based chunk context generation
  - ~49% improvement in retrieval accuracy (per Anthropic research)
  - Configurable via `CONTEXTUAL_RAG_ENABLED` and `CONTEXTUAL_RAG_BATCH_SIZE`
  - Database migration for `contextual_content` column
- **Reasoning Trace (Explainability Layer)**:
  - `ReasoningTracer` class for step-by-step AI reasoning transparency
  - `ReasoningStep` and `ReasoningTrace` models in API response
  - Shows query analysis, retrieval, grading, rewriting, generation steps
  - Per-step timing, confidence scores, and details
  - Integrated into `CorrectiveRAG` pipeline
- **Document Knowledge Graph (Entity Extraction)**:
  - `KGBuilderAgentNode` - new agent in multi-agent system
  - Uses SOTA `with_structured_output()` for guaranteed JSON
  - Extracts ARTICLE, REGULATION, VESSEL_TYPE, MANEUVER, EQUIPMENT entities
  - Extracts REFERENCES, APPLIES_TO, REQUIRES, DEFINES, PART_OF relations
  - Neo4j integration with `create_entity`, `create_entity_relation` methods
  - Configurable via `ENTITY_EXTRACTION_ENABLED` and `ENTITY_EXTRACTION_BATCH_SIZE`
- **GraphRAG Service (Microsoft-style)**:
  - `GraphRAGService` combining HybridSearch with Neo4j entity context
  - Entity-enhanced retrieval with `GraphEnhancedResult`
  - Auto entity extraction during PDF ingestion pipeline
  - Graph context for LLM prompts (`search_with_graph_context`)
  - **RAGAgent Integration**: Automatic GraphRAG usage with entity context in LLM prompts
  - `RAGResponse.entity_context` and `related_entities` fields for API exposure
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

- **Model Configuration Refactoring**:
  - Replaced 12 hardcoded `model="gemini-2.0-flash"` with `settings.google_model`.
  - Files updated: `agentic_rag/` (4), `multi_agent/` (3), memory engines (3), `semantic_memory/` (2).
  - All components now use centralized model config from `.env`.
  - Added configurable thresholds: `similarity_threshold`, `fact_similarity_threshold`, `memory_duplicate_threshold`.
  - Added rate limit configs: `chat_rate_limit`, `default_history_limit`, `max_history_limit`.

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
