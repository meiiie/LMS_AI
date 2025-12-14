# Contextual RAG Architecture

**Feature:** `contextual-rag`  
**Reference:** Anthropic Contextual Retrieval (2024)  
**Status:** ✅ Production Ready

---

## Overview

Contextual RAG implements Anthropic's Contextual Retrieval approach, which enriches document chunks with LLM-generated context before embedding. This technique improves retrieval accuracy by approximately 49% compared to traditional chunking.

## How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Document Ingestion Pipeline                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  PDF → Vision Extract → Semantic Chunk → Context Enrich → Embed     │
│                                              ▲                       │
│                                              │                       │
│                                         [LLM Call]                   │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

### Before (Traditional)

```
Chunk: "Tàu phải nhường đường khi tình huống cắt hướng xảy ra..."
                    ↓
              [Embedding]
```

### After (Contextual RAG)

```
Chunk: "[Context: Đây là Điều 15 COLREGs về tình huống cắt hướng, 
         quy định trách nhiệm của tàu phải nhường đường]
        
        Tàu phải nhường đường khi tình huống cắt hướng xảy ra..."
                    ↓
              [Better Embedding]
```

---

## Components

### 1. ContextEnricher Class

**Location:** `app/engine/context_enricher.py`

```python
class ContextEnricher:
    """Enrich chunks with document context using LLM (Anthropic style)"""
    
    async def generate_context(chunk, document_title, page_number, total_pages):
        """Generate context for a single chunk"""
        
    async def enrich_chunks(chunks, document_id, ...):
        """Batch enrich multiple chunks"""
```

### 2. ChunkResult Extension

**Location:** `app/services/chunking_service.py`

```python
@dataclass
class ChunkResult:
    chunk_index: int
    content: str
    content_type: str = "text"
    confidence_score: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    contextual_content: Optional[str] = None  # NEW: LLM-enriched content
```

### 3. Database Schema

```sql
ALTER TABLE knowledge_embeddings 
ADD COLUMN contextual_content TEXT DEFAULT NULL;
```

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `CONTEXTUAL_RAG_ENABLED` | `true` | Enable/disable context enrichment |
| `CONTEXTUAL_RAG_BATCH_SIZE` | `5` | Chunks to process concurrently |

---

## Integration Points

### Ingestion Service

```python
# app/services/multimodal_ingestion_service.py

# After chunking
if settings.contextual_rag_enabled:
    chunks = await self.context_enricher.enrich_chunks(
        chunks=chunks,
        document_id=document_id,
        document_title=document_id,
        total_pages=total_pages,
        batch_size=settings.contextual_rag_batch_size
    )

# When embedding
text_to_embed = chunk.contextual_content or chunk.content
```

---

## Prompt Template

```
Bạn đang hỗ trợ hệ thống RAG tạo context cho các đoạn văn bản pháp luật hàng hải.

<document>
Tài liệu: {document_title}
Trang: {page_number}/{total_pages}
</document>

<chunk>
{chunk_content}
</chunk>

Viết MỘT đoạn context ngắn (50-80 từ) mô tả chunk này để cải thiện retrieval:
1. Chunk này thuộc phần/chương/điều/khoản nào của tài liệu?
2. Nội dung chính và mục đích của quy định này là gì?
3. Liên quan đến khái niệm/quy tắc hàng hải nào (nếu có)?

QUAN TRỌNG: Chỉ trả về đoạn context, không có tiêu đề, bullet points hay định dạng khác.
```

---

## Cost Analysis

| Document Size | Est. Chunks | Est. Cost |
|---------------|-------------|-----------|
| 10 pages | ~30 | ~$0.01 |
| 100 pages | ~300 | ~$0.09 |
| 500 pages | ~1500 | ~$0.45 |

**Trade-off:** Small cost increase for significant retrieval improvement.

---

## Fallback Behavior

If context generation fails for any chunk:
1. `contextual_content` remains `None`
2. Embedding uses original `content` instead
3. System continues without interruption

---

## Related Documentation

- [Agentic RAG](agentic-rag.md) - Self-correcting retrieval
- [Multimodal RAG](../../../README.md) - Vision-based extraction
- [Anthropic Research](https://www.anthropic.com/news/contextual-retrieval) - Original technique
