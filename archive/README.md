# Archive - Legacy Components

**Last Updated:** 2025-12-18

This directory contains archived legacy code that has been replaced by newer implementations.
Files are kept for reference and potential rollback if needed.

---

## 📁 Archived Files

### 1. Neo4j/Text-based Ingestion (Replaced by Multimodal RAG)

| File | Original Location | Replaced By | Reason |
|------|-------------------|-------------|--------|
| `ingestion_service_legacy.py` | `app/services/ingestion_service.py` | `multimodal_ingestion_service.py` | Vision-based extraction |
| `pdf_processor_legacy.py` | `app/engine/pdf_processor.py` | `vision_extractor.py` + `chunking_service.py` | Gemini Vision + Semantic Chunking |
| `ingestion_job_legacy.py` | `app/models/ingestion_job.py` | N/A (inline in multimodal service) | Simplified job tracking |
| `test_ingestion_properties_legacy.py` | `tests/property/test_ingestion_properties.py` | N/A | Tests for legacy ingestion |

### 2. Legacy Agent Architecture (Replaced by UnifiedAgent)

| File | Original Location | Replaced By | Reason |
|------|-------------------|-------------|--------|
| `chat_agent.py` | `app/engine/agents/chat_agent.py` | `unified_agent.py` | ReAct pattern consolidation |
| `graph.py` | `app/engine/graph.py` | `unified_agent.py` | Simplified orchestration |
| `test_orchestrator_properties.py` | `tests/property/test_orchestrator_properties.py` | N/A | Tests for legacy orchestrator |

### 3. Semantic Memory Backup

| File | Original Location | Replaced By | Reason |
|------|-------------------|-------------|--------|
| `semantic_memory_original_backup.py` | `app/engine/semantic_memory.py` | `semantic_memory/` module | Modular architecture |

### 4. Legacy Scripts

| File | Original Location | Replaced By | Reason |
|------|-------------------|-------------|--------|
| `ingest_local_chunking_legacy.py` | `scripts/ingest_local_chunking.py` | `reingest_multimodal.py` | Uses pdf2image (needs Poppler) instead of PyMuPDF |

---

## 🔄 Migration References

### Sparse Search Migration (Neo4j → PostgreSQL)
- **Spec:** `.kiro/specs/sparse-search-migration/`
- **Date:** 2025-12
- **Summary:** Neo4j Full-text Index replaced by PostgreSQL tsvector
- **Note:** `neo4j_knowledge_repository.py` kept for future Learning Graph

### Multimodal RAG Vision (CHỈ THỊ 26)
- **Spec:** `.kiro/specs/multimodal-rag-vision/`
- **Date:** 2025-12
- **Summary:** Text-based PDF extraction replaced by Gemini Vision

### Semantic Chunking
- **Spec:** `.kiro/specs/semantic-chunking/`
- **Date:** 2025-12
- **Summary:** Basic text splitting replaced by maritime-specific semantic chunking

### Gemini 2.5 Flash Content Block Fix (2025-12-18)
- **Summary:** Fixed `'list' object has no attribute 'strip'` errors
- **Solution:** `extract_thinking_from_response()` utility in `output_processor.py`
- **Affected:** 16 files, 25 locations across engine and services

---

## ⚠️ Restoration (if needed)

To restore any archived file:

1. Copy file back to original location
2. Update imports in dependent files
3. Run tests to verify functionality
4. Update this README

**Example:**
```bash
# Restore ingestion_service
cp archive/ingestion_service_legacy.py app/services/ingestion_service.py
```

---

## 📊 Current Architecture (v2.8)

```
Current RAG Pipeline:
PDF → PyMuPDF → Supabase Storage → Gemini Vision → Semantic Chunking → Neon pgvector

Current Search:
Query → Dense (pgvector) + Sparse (tsvector) → RRF Reranking → Results

Current Agent:
UnifiedAgent (ReAct) → Guardian Agent → RAG Tool → Response

Current LLM:
LLM Singleton Pool (3 shared instances) → extract_thinking_from_response() → Response
```

---

*Maintained by AI Assistant - Last audit: 2025-12-18*
