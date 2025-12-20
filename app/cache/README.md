# Cache Layer

Semantic caching system for CRAG pipeline latency optimization.

---

## Structure

```
app/cache/
├── cache_manager.py      # Main cache manager
├── semantic_cache.py     # Query-based semantic cache
├── models.py             # Cache data models
├── invalidation.py       # Cache invalidation logic
└── __init__.py
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Semantic Cache** | 2hr TTL, cosine similarity ≥0.99 |
| **ThinkingAdapter** | Adapts cached responses with fresh thinking |
| **TTL Invalidation** | Automatic expiry after 2 hours |

---

## Usage

```python
from app.cache.cache_manager import get_cache_manager

cache = get_cache_manager()
result = await cache.get_cached_response(query, user_id)
if result:
    # Cache hit - 45s latency
    return result
```

---

## Performance

| Scenario | Latency |
|----------|---------|
| Cache Hit | ~45s (ThinkingAdapter) |
| Cache Miss | ~85-90s (Full CRAG) |

---

## Related

- [CorrectiveRAG](../engine/agentic_rag/README.md) - Uses cache
- [Services Layer](../services/README.md) - Orchestration
