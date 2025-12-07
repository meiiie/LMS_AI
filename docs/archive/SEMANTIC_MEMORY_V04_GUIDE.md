# Semantic Memory v0.4 - Managed Memory List

## CHỈ THỊ KỸ THUẬT SỐ 23

**Status:** ✅ Production Verified (2025-12-07)
**Previous Version:** v0.3 (Cross-Session Persistence)
**Production URL:** https://maritime-ai-chatbot.onrender.com

---

## Production Test Results (2025-12-07)

```
✅ Health Check: PASS
✅ Memory API: PASS (GET /api/v1/memories/{user_id})
✅ Fact Extraction: PASS (4 facts extracted from conversation)
✅ Upsert Logic: PASS (preference updated, not duplicated)
✅ Background Task: PASS (facts stored via chat flow)
```

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

### Local Testing
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

### Production Testing
```bash
# Run production test script
python scripts/test_memory_final_check.py

# Expected output:
# ✅ Facts were extracted and stored!
# Extracted Facts:
#   - [goal] ôn lại COLREGs
#   - [role] thuyền trưởng tàu container
#   - [preference] Rule 15 về tình huống cắt hướng
#   - [name] Trần Văn Bình
```

### Test Scripts
- `scripts/test_managed_memory_production.py` - Full production test
- `scripts/test_memory_final_check.py` - Chat + verify facts
- `scripts/test_semantic_memory_direct.py` - Direct engine test

---

## Integration Flow

```
User sends chat message
    ↓
ChatService.process_message()
    ↓
Background Task: _store_semantic_interaction_async()
    ↓
SemanticMemoryEngine.store_interaction(extract_facts=True)
    ↓
_extract_and_store_facts() → LLM extracts facts
    ↓
store_user_fact_upsert() → Validate, Upsert, Cap
    ↓
Facts stored in semantic_memories table (memory_type='user_fact')
```

---

## Contact

- **AI Backend Team** - Kiro & Co.
- **Spec Reference:** CHỈ THỊ KỸ THUẬT SỐ 23
- **Last Updated:** 2025-12-07
