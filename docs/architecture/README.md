# 📐 Architecture Documentation

**Version:** 3.0 (SOTA 2025 - Dec 2025)  
**Status:** Production Ready after Phase 2.4a Optimizations

This folder contains detailed architecture documentation for Maritime AI Tutor Service.

---

## 📋 Contents

| Document | Description | Last Updated |
|----------|-------------|--------------|
| [SYSTEM_FLOW.md](SYSTEM_FLOW.md) | **⭐ START HERE** - Complete system flow with Mermaid diagrams | 2025-12-20 |
| [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) | High-level architecture & component deep dive | 2025-12-14 |
| [FOLDER_MAP.md](FOLDER_MAP.md) | Complete folder structure mapping | 2025-12-14 |
| [contextual-rag.md](contextual-rag.md) | Anthropic-style Context Enrichment | 2025-12-10 |
| [tool-registry.md](tool-registry.md) | Tool Registry Pattern | 2025-12-10 |

---

## 🚀 Quick Start

**For Developers:** Start with [SYSTEM_FLOW.md](SYSTEM_FLOW.md) - Contains 6 interactive Mermaid diagrams:

1. **High-Level Architecture** - System layers overview
2. **Request Processing Flow** - Complete request lifecycle
3. **Corrective RAG Pipeline** - SOTA 2025 with Phase 2.4a optimizations
4. **Multi-Agent Graph** - LangGraph state machine
5. **Memory Flow** - Personalization & pronoun handling
6. **Tiered Grading** - Early exit optimization

---

## 🏗️ Architecture Highlights

### Core Patterns
- **Multi-Agent System** - LangGraph Supervisor with specialized agents
- **Corrective RAG** - Self-correction with confidence-based iteration
- **Tiered Grading** - Early exit saves 19s (Phase 2.4a)
- **Semantic Cache** - 2hr TTL, 0.1ms lookup

### Performance (Dec 2025)
| Metric | Cold Path | Warm Cache |
|--------|-----------|------------|
| RAG Query | 85-90s | 45s |
| Simple Chat | 4-5s | 4-5s |
| Memory Query | 6-8s | 6-8s |

---

## 🔗 Quick Links

- [Main README](../../README.md)
- [CHANGELOG](../../CHANGELOG.md)
- [API Documentation](../api/)

---

## 📁 Related Folders

| Folder | Purpose |
|--------|---------|
| `app/engine/` | Core AI logic (UnifiedAgent, CRAG, Multi-Agent) |
| `app/services/` | Business logic orchestration |
| `app/prompts/` | YAML prompt configurations |
