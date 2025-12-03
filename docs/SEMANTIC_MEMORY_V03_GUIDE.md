# Semantic Memory v0.3 - Migration Guide

## CHỈ THỊ KỸ THUẬT SỐ 06

**Branch:** `feature/semantic-memory-v0.3`
**Status:** Development Complete

---

## Overview

Semantic Memory v0.3 nâng cấp hệ thống memory từ Sliding Window (v0.2) lên Vector Embeddings với:
- **Gemini Embedding API** với Matryoshka Representation Learning (MRL)
- **pgvector** trên Supabase cho vector similarity search
- **Hybrid Context**: Kết hợp semantic search + sliding window

---

## New Environment Variables

Thêm vào `.env`:

```env
# Semantic Memory v0.3
EMBEDDING_MODEL=models/gemini-embedding-001
EMBEDDING_DIMENSIONS=768
SEMANTIC_MEMORY_ENABLED=true
SUMMARIZATION_TOKEN_THRESHOLD=2000
```

---

## Database Setup

### 1. Enable pgvector Extension

Chạy trong Supabase SQL Editor:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

### 2. Create semantic_memories Table

Chạy script: `scripts/create_semantic_memory_tables.sql`

Hoặc manually:

```sql
CREATE TABLE semantic_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768) NOT NULL,
    memory_type VARCHAR(50) NOT NULL DEFAULT 'message',
    importance FLOAT DEFAULT 0.5,
    metadata JSONB DEFAULT '{}',
    session_id VARCHAR(255),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- HNSW index for fast similarity search
CREATE INDEX idx_semantic_memories_embedding 
ON semantic_memories 
USING hnsw (embedding vector_cosine_ops);

-- RLS policies
ALTER TABLE semantic_memories ENABLE ROW LEVEL SECURITY;
```

---

## New Dependencies

Đã thêm vào `requirements.txt`:

```
google-genai==0.1.0
numpy>=1.24.0
scikit-learn>=1.3.0
```

Cài đặt:

```bash
pip install -r requirements.txt
```

---

## Architecture

### Components

```
┌─────────────────────────────────────────────────────────────┐
│                    ChatService                               │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              SemanticMemoryEngine                    │    │
│  │  ┌─────────────────┐  ┌─────────────────────────┐   │    │
│  │  │ GeminiOptimized │  │ SemanticMemory          │   │    │
│  │  │ Embeddings      │  │ Repository              │   │    │
│  │  │ (MRL 768-dim)   │  │ (pgvector)              │   │    │
│  │  └─────────────────┘  └─────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────┘    │
│                           │                                  │
│                           ▼                                  │
│  ┌─────────────────────────────────────────────────────┐    │
│  │              Sliding Window (Fallback)               │    │
│  │              ChatHistoryRepository                   │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Query Processing:**
   - User message → Embed với `RETRIEVAL_QUERY`
   - Vector search trong pgvector (cosine similarity)
   - Retrieve top-5 relevant memories + user facts
   - Combine với sliding window (hybrid)

2. **Storage:**
   - Message + Response → Embed với `RETRIEVAL_DOCUMENT`
   - L2 Normalize vectors
   - Store trong semantic_memories table
   - Extract user facts với LLM

3. **Summarization:**
   - Check token count (threshold: 2000)
   - Generate summary với Gemini Flash
   - Store summary, archive original messages

---

## Key Classes

### GeminiOptimizedEmbeddings

```python
from app.engine.gemini_embedding import GeminiOptimizedEmbeddings

embeddings = GeminiOptimizedEmbeddings()

# Embed documents (for storage)
doc_vectors = embeddings.embed_documents(["text1", "text2"])

# Embed query (for search)
query_vector = embeddings.embed_query("search text")
```

**Features:**
- Force 768 dimensions (MRL)
- Auto L2 normalization
- Correct task_type handling

### SemanticMemoryRepository

```python
from app.repositories.semantic_memory_repository import SemanticMemoryRepository

repo = SemanticMemoryRepository()

# Save memory
repo.save_memory(SemanticMemoryCreate(...))

# Search similar
results = repo.search_similar(
    user_id="user123",
    query_embedding=query_vector,
    limit=5,
    threshold=0.7
)

# Get user facts
facts = repo.get_user_facts(user_id="user123")
```

### SemanticMemoryEngine

```python
from app.engine.semantic_memory import SemanticMemoryEngine

engine = SemanticMemoryEngine()

# Retrieve context
context = await engine.retrieve_context(
    user_id="user123",
    query="What is COLREGs Rule 15?"
)

# Store interaction
await engine.store_interaction(
    user_id="user123",
    message="User message",
    response="AI response",
    session_id="session123"
)

# Check and summarize
summary = await engine.check_and_summarize(
    user_id="user123",
    session_id="session123"
)
```

---

## Backward Compatibility

### Fallback Mechanism

Nếu Semantic Memory không available:
1. `SEMANTIC_MEMORY_ENABLED=false` trong .env
2. pgvector extension không có
3. Database connection failed

→ Tự động fallback về Sliding Window (10 messages)

### Hybrid Approach

Khi cả hai available:
- Semantic context (relevant memories + user facts)
- + Sliding window (recent 10 messages)
- = Combined context cho LLM

---

## Memory Types

| Type | Description | Importance |
|------|-------------|------------|
| `message` | Regular conversation | 0.5 |
| `summary` | Conversation summary | 0.9 |
| `user_fact` | Extracted user info | 0.8 |

---

## User Facts Extraction

Tự động extract từ messages:

| Fact Type | Example |
|-----------|---------|
| `name` | "Tôi là Minh" → name: "Minh" |
| `goal` | "Tôi muốn học COLREGs" → goal: "học COLREGs" |
| `background` | "Tôi là thuyền trưởng" → background: "thuyền trưởng" |
| `weak_area` | "Tôi chưa hiểu quy tắc 15" → weak_area: "quy tắc 15" |
| `interest` | "Tôi quan tâm an toàn hàng hải" → interest: "an toàn hàng hải" |

---

## Testing

```bash
# Run all tests
pytest tests/property/ -v

# Verify imports
python -c "from app.engine.semantic_memory import SemanticMemoryEngine; print('OK')"
```

---

## Deployment Checklist

- [ ] Enable pgvector extension in Supabase
- [ ] Run `scripts/create_semantic_memory_tables.sql`
- [ ] Update `.env` with new variables
- [ ] Install new dependencies
- [ ] Verify with `pytest tests/property/`
- [ ] Test semantic search functionality

---

## Troubleshooting

### pgvector not available

```
Error: extension "vector" is not available
```

**Solution:** Contact Supabase support to enable pgvector extension.

### Embedding API errors

```
Error: Failed to initialize Gemini client
```

**Solution:** Check `GOOGLE_API_KEY` in `.env`

### Fallback to sliding window

```
Warning: Semantic Memory v0.3 not available, falling back to sliding window
```

**Solution:** Check database connection and pgvector setup.

---

## Contact

- **AI Backend Team** - Kiro & Co.
- **Spec Reference:** CHỈ THỊ KỸ THUẬT SỐ 06
