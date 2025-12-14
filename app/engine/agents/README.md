# Agents Framework - Base Classes & Registry

> Agent abstractions, configuration, and lifecycle management.

**Location:** `app/engine/agents/`  
**Pattern:** Protocol-based abstraction + Registry (SOTA 2025)  
**Status:** ✅ **INTEGRATED** with `multi_agent/` (2025-12-14)

---

## 🔗 Integration Status

| multi_agent File | Uses from agents/ |
|------------------|-------------------|
| `rag_node.py` | `RAG_AGENT_CONFIG` ✅ |
| `tutor_node.py` | `TUTOR_AGENT_CONFIG` ✅ |
| `memory_agent.py` | `MEMORY_AGENT_CONFIG` ✅ |
| `grader_agent.py` | `GRADER_AGENT_CONFIG` ✅ |
| `kg_builder_agent.py` | `KG_BUILDER_AGENT_CONFIG` ✅ |
| `supervisor.py` | `SUPERVISOR_AGENT_CONFIG` ✅ |
| `graph.py` | `get_agent_registry()`, `AgentTracer` ✅ |

---

## 📁 Files

```
agents/
├── __init__.py       # Exports
├── base.py           # BaseAgent Protocol + AgentMixin (86 lines)
├── config.py         # AgentConfig dataclass (188 lines)
└── registry.py       # AgentRegistry + Tracing (343 lines)
```

---

## 🧩 Pre-defined Configs (6 total)

| Config | ID | Category |
|--------|-----|----------|
| `RAG_AGENT_CONFIG` | `rag_agent` | RETRIEVAL |
| `TUTOR_AGENT_CONFIG` | `tutor_agent` | TEACHING |
| `MEMORY_AGENT_CONFIG` | `memory_agent` | MEMORY |
| `GRADER_AGENT_CONFIG` | `grader_agent` | GRADING |
| `SUPERVISOR_AGENT_CONFIG` | `supervisor` | ROUTING |
| `KG_BUILDER_AGENT_CONFIG` | `kg_builder` | RETRIEVAL |

---

## 📊 Metrics

| File | Lines |
|------|-------|
| `base.py` | 86 |
| `config.py` | 188 |
| `registry.py` | 343 |
| **Total** | **~617** |

---

## 📝 Related

- [Multi-Agent System](../multi_agent/README.md) - Uses configs and tracing
- [Parent: engine](../README.md)
