# Semantic Memory v0.5 - Insight Memory Engine

## CHỈ THỊ KỸ THUẬT SỐ 23 CẢI TIẾN

### Overview

Nâng cấp từ "Atomic Facts" (dữ liệu đơn lẻ) sang "Behavioral Insights" (sự thấu hiểu hành vi). Hệ thống mới biến AI từ "Thư ký" thành "Người Thầy (Mentor)" thực thụ.

### Key Changes from v0.4

| Feature | v0.4 (Managed Memory) | v0.5 (Insight Engine) |
|---------|----------------------|----------------------|
| Data Type | Atomic Facts (name, role, goal) | Behavioral Insights (learning patterns, knowledge gaps) |
| Extraction | Simple fact extraction | LLM-based behavioral analysis |
| Validation | Basic type checking | Behavioral content validation |
| Deduplication | By fact_type | Semantic similarity + contradiction detection |
| Memory Management | FIFO eviction | LLM consolidation + FIFO fallback |
| Retrieval | By recency | Category-prioritized (knowledge_gap, learning_style first) |

### Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INSIGHT MEMORY ENGINE v0.5                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   User Message                                                               │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                    INSIGHT EXTRACTOR                                 │   │
│   │  • Behavioral-focused extraction prompt                              │   │
│   │  • 5 Categories: learning_style, knowledge_gap, goal_evolution,      │   │
│   │                  habit, preference                                   │   │
│   │  • Quality validation (min 20 chars, complete sentence)              │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                    INSIGHT VALIDATOR                                 │   │
│   │  • Check for behavioral content (not atomic facts)                   │   │
│   │  • Detect duplicates → Merge                                         │   │
│   │  • Detect contradictions → Evolution note                            │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                    MEMORY CONSOLIDATOR                               │   │
│   │  • Trigger at 40/50 memories                                         │   │
│   │  • LLM rewrite to merge duplicates                                   │   │
│   │  • Target: 30 core items                                             │   │
│   │  • FIFO fallback when LLM fails                                      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Insight Categories

1. **learning_style** - Phong cách học tập
   - Ví dụ: "User thích học qua ví dụ thực tế hơn là đọc lý thuyết khô khan"
   - Ví dụ: "User có xu hướng đặt câu hỏi sâu về nguyên lý"

2. **knowledge_gap** - Lỗ hổng kiến thức
   - Ví dụ: "User còn nhầm lẫn giữa Rule 13 và Rule 15 trong COLREGs"
   - Ví dụ: "User chưa hiểu rõ khái niệm 'give-way vessel'"

3. **goal_evolution** - Sự thay đổi mục tiêu
   - Ví dụ: "User đã chuyển từ học cơ bản sang chuẩn bị thi bằng thuyền trưởng"

4. **habit** - Thói quen học tập
   - Ví dụ: "User thường học vào buổi tối và thích ôn bài nhiều lần"

5. **preference** - Sở thích cá nhân
   - Ví dụ: "User thích các chủ đề liên quan đến navigation hơn engine room"

### Database Schema Updates

```sql
-- Run this migration script
-- scripts/upgrade_semantic_memory_v05.sql

ALTER TABLE semantic_memories 
ADD COLUMN IF NOT EXISTS insight_category VARCHAR(50),
ADD COLUMN IF NOT EXISTS sub_topic VARCHAR(100),
ADD COLUMN IF NOT EXISTS last_accessed TIMESTAMP DEFAULT NOW(),
ADD COLUMN IF NOT EXISTS evolution_notes JSONB DEFAULT '[]';

-- Indexes for efficient queries
CREATE INDEX IF NOT EXISTS idx_semantic_memories_last_accessed 
ON semantic_memories(user_id, last_accessed DESC);

CREATE INDEX IF NOT EXISTS idx_semantic_memories_category 
ON semantic_memories(user_id, insight_category);
```

### Usage Examples

#### Extract Insights from Message
```python
from app.engine.semantic_memory import get_semantic_memory_engine

engine = get_semantic_memory_engine()

# Extract and store behavioral insights
insights = await engine.extract_and_store_insights(
    user_id="user123",
    message="Tôi thấy học qua ví dụ thực tế dễ hiểu hơn nhiều",
    conversation_history=["Previous message 1", "Previous message 2"],
    session_id="session123"
)

print(f"Extracted {len(insights)} insights")
for insight in insights:
    print(f"  [{insight.category.value}] {insight.content}")
```

#### Retrieve Prioritized Insights
```python
# Get insights with category prioritization
# (knowledge_gap and learning_style are prioritized)
insights = await engine.retrieve_insights_prioritized(
    user_id="user123",
    query="học tập",
    limit=10
)
```

#### Manual Consolidation
```python
# Check and consolidate if needed
await engine._check_and_consolidate("user123")
```

### Memory Limits

| Parameter | Value | Description |
|-----------|-------|-------------|
| MAX_INSIGHTS | 50 | Hard limit per user |
| CONSOLIDATION_THRESHOLD | 40 | Trigger consolidation |
| TARGET_COUNT | 30 | Target after consolidation |
| PRESERVE_DAYS | 7 | Preserve recently accessed |
| MIN_INSIGHT_LENGTH | 20 | Minimum content length |

### Testing

Run the test suite:
```bash
cd maritime-ai-service
.\.venv\Scripts\python.exe scripts/test_insight_engine.py
```

Expected output:
```
INSIGHT MEMORY ENGINE v0.5 - TEST SUITE
============================================================
  InsightExtractor: ✅ PASS
  InsightValidator: ✅ PASS
  MemoryConsolidator: ✅ PASS
  SemanticMemoryEngine: ✅ PASS
  DatabaseSchema: ✅ PASS

Total: 5/5 tests passed
```

### Migration from v0.4

1. Run database migration:
   ```bash
   psql -d your_database -f scripts/upgrade_semantic_memory_v05.sql
   ```

2. Existing USER_FACT entries will continue to work (backward compatible)

3. New insights will be stored with INSIGHT memory_type

### Files Changed

- `app/models/semantic_memory.py` - Added InsightCategory enum and Insight model
- `app/engine/insight_extractor.py` - NEW: Extract behavioral insights
- `app/engine/insight_validator.py` - NEW: Validate and detect duplicates
- `app/engine/memory_consolidator.py` - NEW: LLM-based consolidation
- `app/engine/semantic_memory.py` - Enhanced with Insight Engine methods
- `app/repositories/semantic_memory_repository.py` - Added v0.5 methods
- `app/services/chat_service.py` - Integrated Insight Engine
- `scripts/upgrade_semantic_memory_v05.sql` - Database migration
- `scripts/test_insight_engine.py` - Test suite
