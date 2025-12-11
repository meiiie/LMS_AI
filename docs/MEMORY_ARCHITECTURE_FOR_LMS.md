# MEMORY ARCHITECTURE - Huong Dan LMS Team

**Ngay:** 12/12/2025  
**Tu:** Team Backend AI  
**Den:** Team LMS Backend + Frontend  
**Chu de:** Cau truc Memory System de xay dung UI hien thi ky uc nguoi dung

---

## 1. TONG QUAN KIEN TRUC

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SEMANTIC MEMORY SYSTEM v0.5                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐          │
│   │   FACTS     │     │  INSIGHTS   │     │  MEMORIES   │          │
│   │ (User Info) │     │ (Behavioral)│     │ (Messages)  │          │
│   └──────┬──────┘     └──────┬──────┘     └──────┬──────┘          │
│          │                   │                   │                  │
│          └───────────────────┼───────────────────┘                  │
│                              ▼                                      │
│                    ┌─────────────────┐                              │
│                    │  PostgreSQL     │                              │
│                    │  (pgvector)     │                              │
│                    │  semantic_      │                              │
│                    │  memories table │                              │
│                    └─────────────────┘                              │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. LOAI DU LIEU

### 2.1. User Facts (6 loai chinh)

| Fact Type | Description | Vi du |
|-----------|-------------|-------|
| `name` | Ten nguoi dung | "Minh", "Nam" |
| `role` | Vai tro/Nghe nghiep | "Sinh vien", "Thuyen truong" |
| `level` | Cap do | "Nam 3", "Si quan hang 2" |
| `goal` | Muc tieu hoc tap | "Thi bang thuyen truong" |
| `preference` | So thich hoc tap | "Thich hoc qua vi du thuc te" |
| `weakness` | Diem yeu | "Con yeu ve Rule 15" |

### 2.2. Insights (5 categories)

| Category | Description | Vi du |
|----------|-------------|-------|
| `learning_style` | Phong cach hoc | "Hoc tot hon voi hinh anh" |
| `knowledge_gap` | Lo hong kien thuc | "Chua hieu ro ve MARPOL Annex VI" |
| `goal_evolution` | Thay doi muc tieu | "Truoc muon lam thuyen pho, nay muon lam thuyen truong" |
| `habit` | Thoi quen | "Thuong hoc vao buoi toi" |
| `preference` | So thich | "Thich cau hoi thuc hanh hon ly thuyet" |

---

## 3. API ENDPOINTS

### 3.1. GET /api/v1/memories/{user_id}

**Request:**
```http
GET /api/v1/memories/{user_id}
X-API-Key: {api_key}
```

**Response:**
```json
{
  "data": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "type": "name",
      "value": "Nguyen Van Minh",
      "created_at": "2025-12-10T10:30:00Z"
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440001",
      "type": "role",
      "value": "Sinh vien nam 3 Hang hai",
      "created_at": "2025-12-10T10:31:00Z"
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440002",
      "type": "weakness",
      "value": "Con yeu ve COLREGs Rule 15-18",
      "created_at": "2025-12-11T14:20:00Z"
    }
  ],
  "total": 3
}
```

### 3.2. API MOI CAN IMPLEMENT (De xuat)

**GET /api/v1/insights/{user_id}** - Lay insights

```json
{
  "data": [
    {
      "id": "uuid",
      "category": "knowledge_gap",
      "content": "Nguoi dung gap kho khan voi Rule 15 ve tinh huong cat huong",
      "sub_topic": "COLREGs Rule 15",
      "confidence": 0.85,
      "created_at": "2025-12-11T10:00:00Z",
      "updated_at": "2025-12-11T14:30:00Z",
      "evolution_notes": [
        "Ban dau hoi sai ve tau nao nhuong duong",
        "Sau khi giai thich, da hieu 70%"
      ]
    }
  ],
  "total": 1
}
```

---

## 4. UI DESIGN SUGGESTIONS

### 4.1. User Profile Card

```
┌─────────────────────────────────────────────────┐
│  👤 Ho So Nguoi Dung                            │
├─────────────────────────────────────────────────┤
│  Ten:        Nguyen Van Minh                    │
│  Vai tro:    Sinh vien nam 3 Hang hai           │
│  Muc tieu:   Thi bang thuyen truong hang 3      │
│  Diem yeu:   COLREGs Rule 15-18                 │
└─────────────────────────────────────────────────┘
```

### 4.2. Learning Insights Panel

```
┌─────────────────────────────────────────────────┐
│  🧠 Nhan dinh tu AI                             │
├─────────────────────────────────────────────────┤
│  📊 Phong cach hoc                              │
│     → Hoc tot hon voi vi du thuc te             │
│     → Thich hinh anh va so do                   │
│                                                  │
│  ⚠️ Lo hong kien thuc                           │
│     → COLREGs Rule 15 (Cat huong)       [70%]   │
│     → MARPOL Annex VI                   [40%]   │
│                                                  │
│  📈 Tien trinh                                  │
│     → Rule 15: 30% → 70% (2 ngay)               │
└─────────────────────────────────────────────────┘
```

### 4.3. Memory Timeline

```
┌─────────────────────────────────────────────────┐
│  📅 Lich su hoc tap                             │
├─────────────────────────────────────────────────┤
│  12/12/2025                                     │
│    10:30  Hoc ve Rule 15 - Cat huong            │
│    14:00  On tap SOLAS Chapter III              │
│                                                  │
│  11/12/2025                                     │
│    09:00  Gioi thieu ban than                   │
│    11:00  Hoi ve COLREGs tong quat              │
└─────────────────────────────────────────────────┘
```

---

## 5. CAU TRUC DU LIEU CHI TIET

### 5.1. Fact Model

```typescript
interface UserFact {
  id: string;           // UUID
  type: FactType;       // "name" | "role" | "level" | "goal" | "preference" | "weakness"
  value: string;        // Extracted value
  createdAt: Date;      // When created
}

enum FactType {
  NAME = "name",
  ROLE = "role",
  LEVEL = "level",
  GOAL = "goal",
  PREFERENCE = "preference",
  WEAKNESS = "weakness"
}
```

### 5.2. Insight Model

```typescript
interface Insight {
  id: string;
  userId: string;
  content: string;                  // Full sentence
  category: InsightCategory;
  subTopic?: string;               // e.g., "Rule 15"
  confidence: number;              // 0.0 - 1.0
  createdAt: Date;
  updatedAt?: Date;
  lastAccessed?: Date;
  evolutionNotes: string[];        // Track changes
}

enum InsightCategory {
  LEARNING_STYLE = "learning_style",
  KNOWLEDGE_GAP = "knowledge_gap",
  GOAL_EVOLUTION = "goal_evolution",
  HABIT = "habit",
  PREFERENCE = "preference"
}
```

---

## 6. AUTO-EXTRACTION FLOW

```
User Message → AI Process → Insight Extraction
                               ↓
                    ┌──────────────────────┐
                    │  InsightExtractor    │
                    │  (LLM-based)         │
                    └──────────┬───────────┘
                               ↓
                    ┌──────────────────────┐
                    │  InsightValidator    │
                    │  - Check duplicates  │
                    │  - Merge similar     │
                    │  - Update evolution  │
                    └──────────┬───────────┘
                               ↓
                    ┌──────────────────────┐
                    │  Store to DB         │
                    │  (Max 50 per user)   │
                    └──────────────────────┘
```

---

## 7. PHAN QUYEN LMS

| Action | Student | Teacher | Admin |
|--------|---------|---------|-------|
| View own memories | Yes | Yes | Yes |
| View student memories | No | Yes | Yes |
| Delete own memories | No | No | Yes |
| Export memories | No | Yes | Yes |

---

## 8. NEXT STEPS

### AI Team can lam:
- [ ] Tao endpoint GET /api/v1/insights/{user_id}
- [ ] Tao endpoint DELETE /api/v1/memories/{user_id}/{memory_id} (admin only)
- [ ] Them filter by date range

### LMS Team can lam:
- [ ] Thiet ke UI hien thi ho so nguoi dung
- [ ] Thiet ke UI hien thi insights
- [ ] Tich hop vao trang quan ly sinh vien

---

## 9. LIEN HE

Neu can them API hoac thong tin chi tiet, vui long lien he Team Backend AI.

---

*Team Backend AI - Maritime AI Tutor Project*
