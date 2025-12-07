# Semantic Memory v0.4 - Managed Memory List

## CHỈ THỊ KỸ THUẬT SỐ 23

**Status:** Production Ready
**Previous Version:** v0.3 (Cross-Session Persistence)

---

## What's New in v0.4

### 1. Memory Capping (50 facts/user)
- Maximum 50 USER_FACT entries per user
- FIFO eviction: oldest facts deleted when cap exceeded
- Prevents database bloat and AI context pollution

### 2. True Deduplication (Upsert)
- One fact per fact_type per user
- New facts UPDATE existing facts of same type
- No more duplicate "name" entries

### 3. Fact Type Validation
- Only 6 essential types allowed:
  - `name` - User's name
  - `role` - Sinh viên/Giáo viên/Thuyền trưởng
  - `level` - Năm 3, Đại phó, Sĩ quan...
  - `goal` - Learning goals
  - `preference` - Learning preferences/style
  - `weakness` - Areas needing improvement

### 4. Memory Management API
- `GET /api/v1/memories/{user_id}` - List all facts for user
- Returns JSON array with id, type, value, created_at

---

## Backward Compatibility

### Deprecated Fact Types (Mapped)
| Old Type | New Type |
|----------|----------|
| `background` | `role` |
| `weak_area` | `weakness` |
| `interest` | `preference` |
| `learning_style` | `preference` |

### Ignored Fact Types
- `strong_area` - Not stored (not essential)

---

## API Reference

### GET /api/v1/memories/{user_id}

**Request:**
```bash
curl -X GET "https://api.example.com/api/v1/memories/user123" \
  -H "X-API-Key: your_api_key"
```

**Response:**
```json
{
  "data": [
    {"id": "uuid-1", "type": "name", "value": "Minh", "created_at": "2025-12-07T10:00:00Z"},
    {"id": "uuid-2", "type": "goal", "value": "Học COLREGs", "created_at": "2025-12-07T09:00:00Z"}
  ],
  "total": 2
}
```

---

## Code Changes

### SemanticMemoryEngine

```python
# New constants
MAX_USER_FACTS = 50  # Memory cap

# New methods
async def store_user_fact_upsert(user_id, fact_content, fact_type, confidence, session_id)
async def _enforce_memory_cap(user_id) -> int
def _validate_fact_type(fact_type) -> Optional[str]
```

### SemanticMemoryRepository

```python
# New methods
def find_fact_by_type(user_id, fact_type) -> Optional[SemanticMemorySearchResult]
def update_fact(fact_id, content, embedding, metadata) -> bool
def delete_oldest_facts(user_id, count) -> int
def get_all_user_facts(user_id) -> List[SemanticMemorySearchResult]
```

---

## Migration from v0.3

No database migration required. Changes are backward compatible:
- Existing facts remain unchanged
- New facts use upsert logic
- Memory cap enforced on new inserts only

---

## Testing

```bash
# Verify new methods
python -c "
from app.engine.semantic_memory import SemanticMemoryEngine
e = SemanticMemoryEngine()
print('MAX_USER_FACTS:', e.MAX_USER_FACTS)
print('validate name:', e._validate_fact_type('name'))
print('validate background:', e._validate_fact_type('background'))  # -> role
"

# Test API endpoint
curl -X GET "http://localhost:8000/api/v1/memories/test_user" \
  -H "X-API-Key: your_key"
```

---

## Contact

- **AI Backend Team** - Kiro & Co.
- **Spec Reference:** CHỈ THỊ KỸ THUẬT SỐ 23
