# MEMORY ARCHITECTURE CHI TIET - Maritime AI Tutor

**Ngay:** 12/12/2025  
**Version:** Semantic Memory v0.5 + Insight Engine  
**Tu:** Team Backend AI  

---

## 1. TONG QUAN KIEN TRUC

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SEMANTIC MEMORY SYSTEM v0.5                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                        LAYER 1: DATA TYPES                              ││
│  ├───────────────┬───────────────┬───────────────┬───────────────┐        ││
│  │     FACTS     │   INSIGHTS    │   MESSAGES    │   SUMMARIES   │        ││
│  │  (6 loai)     │  (5 loai)     │ (chat history)│ (nen session) │        ││
│  │  MAX: 50      │  MAX: 50      │ Unlimited     │ Per session   │        ││
│  └───────────────┴───────────────┴───────────────┴───────────────┘        ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                       LAYER 2: PROCESSING                               ││
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐         ││
│  │  │InsightExtractor │  │InsightValidator │  │MemoryConsolidator│        ││
│  │  │  (LLM-based)    │  │  (Check dups)   │  │  (Nen 40→30)     │        ││
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘         ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                       LAYER 3: STORAGE                                  ││
│  │                  PostgreSQL + pgvector (768-dim)                        ││
│  │                     semantic_memories table                              ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. CAC LOAI DU LIEU

### 2.1. User Facts (6 loai) - `memory_type = 'user_fact'`

Thong tin co ban ve nguoi dung, duoc trich xuat tu hoi thoai.

| Fact Type | Mo ta | Vi du |
|-----------|-------|-------|
| `name` | Ten nguoi dung | "Minh", "Nam" |
| `role` | Vai tro/Nghe nghiep | "Sinh vien", "Thuyen truong" |
| `level` | Cap do | "Nam 3", "Si quan hang 2" |
| `goal` | Muc tieu hoc tap | "Thi bang thuyen truong" |
| `preference` | So thich hoc tap | "Thich hoc qua vi du" |
| `weakness` | Diem yeu | "Con yeu ve Rule 15" |

**Gioi han:** MAX_USER_FACTS = **50** per user

### 2.2. Insights (5 loai) - `memory_type = 'insight'`

Nhan dinh hanh vi, duoc AI trich xuat tu hanh vi hoc tap.

| Category | Mo ta | Vi du |
|----------|-------|-------|
| `learning_style` | Phong cach hoc | "User thich hoc qua vi du thuc te hon la ly thuyet" |
| `knowledge_gap` | Lo hong kien thuc | "User nham lan giua Rule 13 va Rule 15" |
| `goal_evolution` | Thay doi muc tieu | "Truoc hoc co ban, nay chuan bi thi bang" |
| `habit` | Thoi quen | "User thuong hoc vao buoi toi" |
| `preference` | So thich chu de | "User quan tam emergency procedures hon" |

**Gioi han:** MAX_INSIGHTS = **50** per user

### 2.3. Messages - `memory_type = 'message'`

Lich su hoi thoai, luu theo session.

### 2.4. Summaries - `memory_type = 'summary'`

Ban tom tat khi session vuot token threshold.

---

## 3. CONFIGURATION

```python
# app/engine/semantic_memory/core.py

MAX_USER_FACTS = 50           # Gioi han facts per user
MAX_INSIGHTS = 50             # Gioi han insights per user
CONSOLIDATION_THRESHOLD = 40  # Bat dau nen khi dat 40 insights
TARGET_COUNT = 30             # Muc tieu sau khi nen: 30 insights
PRESERVE_DAYS = 7             # Giu insights truy cap trong 7 ngay
SIMILARITY_THRESHOLD = 0.7    # Nguong tuong tu cho vector search

# SOTA Thresholds (12/12/2025)
DUPLICATE_SIMILARITY_THRESHOLD = 0.85  # Cosine similarity cho insight duplicates
FACT_SIMILARITY_THRESHOLD = 0.90       # Cosine similarity cho fact duplicates
```

---

## 4. LUONG HOAT DONG CHI TIET

### 4.1. Flow Tong Quat

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  User hoi   │────▶│ Trich xuat  │────▶│  Validate   │────▶│   Luu DB    │
│   cau hoi   │     │   Insights  │     │  & Merge    │     │             │
└─────────────┘     └─────────────┘     └─────────────┘     └─────────────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ Kiem tra    │ Neu insights >= 40
                    │  threshold  │─────────────────────────▶ Consolidation
                    │  (>= 40?)   │                            (40 → 30)
                    └─────────────┘
```

### 4.2. Flow Chi Tiet Moi Message

```
User gui message: "Toi van chua hieu Rule 15 ve cat huong"
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 1: INSIGHT EXTRACTION (InsightExtractor)                           │
│  ─────────────────────────────────────────────                           │
│  LLM phan tich message va trich xuat insights:                           │
│                                                                          │
│  Input: "Toi van chua hieu Rule 15 ve cat huong"                         │
│  Output: [{                                                              │
│    "category": "knowledge_gap",                                          │
│    "content": "User con lo hong kien thuc ve Rule 15 COLREGs",           │
│    "sub_topic": "Rule 15 - Crossing Situation",                          │
│    "confidence": 0.9                                                     │
│  }]                                                                      │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 2: VALIDATION (InsightValidator)                                   │
│  ─────────────────────────────────────                                   │
│  Kiem tra insight hop le:                                                │
│  - Content >= 20 ky tu? ✓                                                │
│  - Category hop le? ✓                                                    │
│  - SOTA: Embedding cosine similarity >= 0.85? → Merge hoac Update        │
│                                                                          │
│  Xu ly duplicate (SOTA - Embedding-based):                               │
│  - Tinh cosine similarity giua embeddings (768-dim)                      │
│  - Neu similarity >= 0.85 → update content, tang confidence              │
│  - Ghi lai evolution_notes: ["Updated from new question on 2025-12-12"]  │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 3: CHECK CONSOLIDATION THRESHOLD                                   │
│  ─────────────────────────────────────                                   │
│  Dem so insights hien tai: 42                                            │
│  CONSOLIDATION_THRESHOLD = 40                                            │
│                                                                          │
│  42 >= 40? → YES → Trigger consolidation                                 │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼ (Neu can)
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 4: CONSOLIDATION (MemoryConsolidator)                              │
│  ──────────────────────────────────────────                              │
│  LLM gop cac insights tuong tu:                                          │
│                                                                          │
│  Truoc: 42 insights                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ #1 [knowledge_gap] User chua hieu Rule 15                           │ │
│  │ #2 [knowledge_gap] User nham Rule 15 va Rule 13                     │ │
│  │ #3 [knowledge_gap] User khong biet tau nao phai nhuong duong        │ │
│  │ #4 [learning_style] User thich hoc qua vi du                        │ │
│  │ ... (38 insights khac)                                              │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  Sau: 30 insights                                                        │
│  ┌─────────────────────────────────────────────────────────────────────┐ │
│  │ #1 [knowledge_gap] User con lo hong nghiem trong ve COLREGs,        │ │
│  │    dac biet Rule 13-15 ve tinh huong crossing va overtaking.        │ │
│  │    Evolution: ["Merged from #1, #2, #3 on 2025-12-12"]              │ │
│  │                                                                     │ │
│  │ #2 [learning_style] User thich hoc qua vi du thuc te...             │ │
│  │ ... (28 insights khac)                                              │ │
│  └─────────────────────────────────────────────────────────────────────┘ │
│                                                                          │
│  Nguyen tac consolidation:                                               │
│  1. Merge insights cung category va topic                                │
│  2. Uu tien giu insights moi nhat (created_at)                           │
│  3. Uu tien knowledge_gap va learning_style (PRIORITY_CATEGORIES)        │
│  4. Giu insights duoc truy cap gan day (last_accessed trong 7 ngay)      │
└──────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  STEP 5: LUU VAO DATABASE                                                │
│  ────────────────────────                                                │
│  INSERT vao semantic_memories table voi:                                 │
│  - user_id: "user-123"                                                   │
│  - content: "User con lo hong kien thuc ve Rule 15..."                   │
│  - memory_type: "insight"                                                │
│  - embedding: [768-dim vector]                                           │
│  - metadata: {                                                           │
│      "insight_category": "knowledge_gap",                                │
│      "sub_topic": "Rule 15",                                             │
│      "confidence": 0.9,                                                  │
│      "evolution_notes": [...]                                            │
│    }                                                                     │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 5. CO CHE NEN MEMORY (CONSOLIDATION)

### 5.1. Khi nao trigger?

```
insights_count >= 40  →  Trigger consolidation
                         Muc tieu: giam xuong 30
```

### 5.2. LLM Consolidation Process

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     CONSOLIDATION PROMPT (LLM)                          │
├─────────────────────────────────────────────────────────────────────────┤
│ HIEN TAI: 42 insights                                                   │
│ MUC TIEU: Giam xuong 30 insights                                        │
│                                                                         │
│ NGUYEN TAC:                                                             │
│ 1. Merge duplicates: Gop insights tuong tu                              │
│ 2. Update evolution: Ghi nhan su phat trien                             │
│ 3. Keep recent: Uu tien thong tin moi nhat                              │
│ 4. Preserve diversity: Giu da dang categories                           │
│ 5. Remove redundant: Loai bo thong tin khong quan trong                 │
│                                                                         │
│ OUTPUT: JSON array voi 30 insights da consolidate                       │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.3. Vi du Consolidation

**Truoc (3 insights rieng le):**
```
#1 [knowledge_gap] User chua hieu Rule 15 ve cat huong
#2 [knowledge_gap] User nham lan tau nao phai nhuong duong trong crossing
#3 [knowledge_gap] User hoi sai ve Rule 15 nhieu lan
```

**Sau (1 insight consolidated):**
```
#1 [knowledge_gap] User có lỗ hổng nghiêm trọng về Rule 15 COLREGs 
   (Crossing Situation). Đặc biệt chưa hiểu rõ tàu nào phải nhường 
   đường trong tình huống cắt hướng. Đã hỏi sai nhiều lần.
   
   confidence: 0.95
   evolution_notes: ["Merged from #1, #2, #3 on 2025-12-12"]
```

---

## 6. CO CHE NEN SESSION (SUMMARIZATION)

### 6.1. Khi nao trigger?

```
session_tokens >= SUMMARIZATION_TOKEN_THRESHOLD (default: 4000)
                         │
                         ▼
              Summarize session messages
                         │
                         ▼
           Luu summary + Xoa messages cu
```

### 6.2. Summarization Process

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      SESSION SUMMARIZATION                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Session messages (4500 tokens):                                        │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ User: What is Rule 15?                                          │    │
│  │ AI: Rule 15 covers crossing situations...                       │    │
│  │ User: So which vessel gives way?                                │    │
│  │ AI: The vessel which has the other on her starboard side...     │    │
│  │ User: Can you give me an example?                               │    │
│  │ AI: Imagine two vessels approaching at 90 degrees...            │    │
│  │ ... (nhieu messages khac)                                       │    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                              │                                          │
│                              ▼                                          │
│                       LLM Summarization                                 │
│                              │                                          │
│                              ▼                                          │
│  Summary (500 tokens):                                                  │
│  ┌─────────────────────────────────────────────────────────────────┐    │
│  │ User da hoi ve Rule 15 COLREGs (Crossing Situation). Sau khi    │    │
│  │ duoc giai thich, user da hieu tau nao phai nhuong duong trong   │    │
│  │ tinh huong cat huong. User thich hoc qua vi du thuc te. Cuoi    │    │
│  │ session, user muon on tap them ve Rule 13-15.                   │    │
│  │                                                                 │    │
│  │ Key topics: ["Rule 15", "Crossing Situation", "Give-way vessel"]│    │
│  └─────────────────────────────────────────────────────────────────┘    │
│                                                                         │
│  Action:                                                                │
│  1. Luu summary voi memory_type = 'summary'                             │
│  2. Xoa cac messages cu cua session                                     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 7. RETRIEVAL FLOW

### 7.1. Khi AI can ngu canh?

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        CONTEXT RETRIEVAL                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  User hoi: "Cho toi vi du ve Rule 15"                                   │
│                              │                                          │
│                              ▼                                          │
│  1. Lay User Facts (cao nhat priority)                                  │
│     → name: "Minh", role: "Sinh vien nam 3", weakness: "COLREGs"        │
│                              │                                          │
│                              ▼                                          │
│  2. Vector Search Insights (similarity >= 0.7)                          │
│     → [knowledge_gap] User con lo hong ve Rule 15                       │
│     → [learning_style] User thich hoc qua vi du                         │
│                              │                                          │
│                              ▼                                          │
│  3. Vector Search Previous Summaries                                    │
│     → Summary session truoc ve Rule 13-15                               │
│                              │                                          │
│                              ▼                                          │
│  4. Recent Messages (sliding window 5 messages)                         │
│     → Cac messages gan day trong session hien tai                       │
│                              │                                          │
│                              ▼                                          │
│  5. Assemble Context cho LLM                                            │
│     ┌─────────────────────────────────────────────────────────────┐     │
│     │ === Ho so nguoi dung ===                                    │     │
│     │ - Ten: Minh                                                 │     │
│     │ - Cap do: Sinh vien nam 3                                   │     │
│     │ - Diem yeu: COLREGs                                         │     │
│     │                                                             │     │
│     │ === Nhan dinh AI ===                                        │     │
│     │ - User con lo hong ve Rule 15 (knowledge_gap)               │     │
│     │ - User thich hoc qua vi du (learning_style)                 │     │
│     │                                                             │     │
│     │ === Ngu canh lien quan ===                                  │     │
│     │ - Summary session truoc ve COLREGs Rule 13-15               │     │
│     └─────────────────────────────────────────────────────────────┘     │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 8. DATABASE SCHEMA

```sql
CREATE TABLE semantic_memories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id TEXT NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),           -- Gemini embedding
    memory_type TEXT NOT NULL,       -- 'user_fact', 'insight', 'message', 'summary'
    importance FLOAT DEFAULT 0.5,
    metadata JSONB DEFAULT '{}',
    session_id TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP,
    last_accessed TIMESTAMP          -- For FIFO eviction
);

-- Indexes
CREATE INDEX idx_user_memories ON semantic_memories(user_id, memory_type);
CREATE INDEX idx_embedding ON semantic_memories USING ivfflat (embedding vector_cosine_ops);
```

---

## 9. API ENDPOINTS

| Method | Endpoint | Mo ta |
|--------|----------|-------|
| GET | `/api/v1/memories/{user_id}` | Lay tat ca facts cua user |
| GET | `/api/v1/insights/{user_id}` | Lay tat ca insights cua user |
| DELETE | `/api/v1/memories/{user_id}/{id}` | Xoa memory (admin only) |

---

## 10. SUMMARY

| Item | Value | Mo ta |
|------|-------|-------|
| Max Facts | 50 | Gioi han facts per user |
| Max Insights | 50 | Gioi han insights per user |
| Consolidation Trigger | 40 | Bat dau nen khi dat 40 |
| Consolidation Target | 30 | Giam xuong 30 sau khi nen |
| Preserve Days | 7 | Giu insights truy cap gan day |
| Summarization Threshold | 4000 tokens | Nen session khi dat nguong |

---

*Team Backend AI - Maritime AI Tutor Project*
