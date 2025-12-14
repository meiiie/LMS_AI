# Models - Pydantic Schemas & Data Models

> Data transfer objects, API schemas, and domain models.

**Location:** `app/models/`  
**Pattern:** Pydantic Models (SOTA 2024)

---

## 📁 Files (6 total)

| File | Lines | Classes | Purpose |
|------|-------|---------|---------|
| `schemas.py` | 623 | 45 | API Request/Response |
| `semantic_memory.py` | 567 | 35 | Memory models |
| `knowledge_graph.py` | ~200 | 10 | KG entities |
| `learning_profile.py` | ~170 | 8 | Learning state |
| `database.py` | ~130 | 5 | SQLAlchemy base |
| `__init__.py` | 2 | - | Package exports |

---

## 🔗 Usage

| File | Used By |
|------|---------|
| `schemas.py` | chat.py, chat_stream.py, health.py, main.py, services |
| `semantic_memory.py` | semantic_memory/, memory_*, insight_* |
| `knowledge_graph.py` | neo4j_repository, rag_agent |
| `learning_profile.py` | chat_service, learning_repo, tutor_agent |
| `database.py` | chat_history_repository |

---

## ⚠️ Audit Findings (2025-12-14)

| Check | Status |
|-------|--------|
| Dead code | ✅ None |
| Legacy patterns | ✅ None |
| SOTA compliance | ✅ Pydantic v2 |
| All files used | ✅ 6/6 |

---

## 📊 Key Models

### schemas.py
- `ChatRequest`, `ChatResponse` - API contracts
- `UserContext`, `UserRole` - LMS integration
- `SourceInfo`, `ReasoningTrace` - Transparency
- `ToolUsageInfo` - Agent introspection

### semantic_memory.py
- `SemanticMemory`, `UserFact` - Memory storage
- `SemanticTriple` - Subject-Predicate-Object
- `Insight` - Behavioral analysis
- `MemoryType`, `FactType` - Enums

---

## 📝 Related

- [Engine (consumers)](../engine/README.md)
- [Services (consumers)](../services/README.md)
- [API (request/response)](../api/README.md)
