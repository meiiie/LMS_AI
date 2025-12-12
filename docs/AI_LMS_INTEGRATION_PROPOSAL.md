# AI-LMS INTEGRATION PROPOSAL
## Maritime AI Tutor x LMS Backend Integration

**Ngày:** 12/12/2025  
**Từ:** Team Backend AI  
**Đến:** Team LMS Backend  
**Version:** 1.0 Draft  

---

## MỤC LỤC

1. [Executive Summary](#1-executive-summary)
2. [Current State](#2-current-state)
3. [Integration Options](#3-integration-options)
4. [Recommended Architecture](#4-recommended-architecture)
5. [API Contract](#5-api-contract)
6. [Data Ownership](#6-data-ownership)
7. [Knowledge Graph Strategy](#7-knowledge-graph-strategy)
8. [Security & Compliance](#8-security--compliance)
9. [Discussion Points](#9-discussion-points)
10. [Next Steps](#10-next-steps)

---

## 1. EXECUTIVE SUMMARY

### Mục Tiêu
Thiết lập quy trình tích hợp giữa **AI Backend (Maritime AI Tutor)** và **LMS Backend (Spring Boot)** để:
- AI có đủ context về user để cá nhân hóa trải nghiệm
- Tuân thủ GDPR và best practices về data ownership
- Hỗ trợ mở rộng trong tương lai (Knowledge Graph, Multi-Agent)

### Quyết Định Cần Thống Nhất
| # | Vấn Đề | Options | Đề Xuất |
|---|--------|---------|---------|
| 1 | User Identity | UUID từ LMS / Generate mới | UUID từ LMS |
| 2 | User Context | LMS gửi / AI query về | LMS gửi mỗi request |
| 3 | PII Handling | AI lưu / Không lưu | Chỉ cached name (TTL) |
| 4 | Process Attribution | Single / Multi-agent | Future-ready Multi |
| 5 | Knowledge Graph | User / Document / Cả hai | Document trước |

---

## 2. CURRENT STATE

### 2.1. Hiện Tại - AI Backend

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         CURRENT AI ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LMS Frontend (Angular)                                                       │
│        │                                                                     │
│        │ JWT Token                                                          │
│        ▼                                                                     │
│  LMS Backend (Spring Boot)                                                    │
│        │                                                                     │
│        │ API Key + user_id                                                  │
│        ▼                                                                     │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                     AI BACKEND (FastAPI)                                ││
│  │                                                                         ││
│  │  POST /api/v1/chat                                                      ││
│  │  {                                                                      ││
│  │    "user_id": "550e8400-...",  ← Chỉ có user_id                         ││
│  │    "message": "Điều 15 là gì?",                                         ││
│  │    "role": "student"                                                    ││
│  │  }                                                                      ││
│  │                                                                         ││
│  │  AI Database (Neon PostgreSQL):                                         ││
│  │  ┌─────────────────────────────────────────────┐                       ││
│  │  │ semantic_memories                            │                       ││
│  │  │ ─────────────────                            │                       ││
│  │  │ user_id: "550e8400-..."                      │                       ││
│  │  │ content: "User thích học qua ví dụ"          │ ← AI tự extract       ││
│  │  │ memory_type: "insight"                       │                       ││
│  │  └─────────────────────────────────────────────┘                       ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 2.2. Limitations Hiện Tại

| # | Limitation | Impact |
|---|------------|--------|
| 1 | AI không biết tên user | Không thể gọi "Em Minh ơi..." |
| 2 | AI không biết course hiện tại | Không suggest đúng context |
| 3 | AI không biết progress | Không biết user đã học gì |
| 4 | Không có process_id | Không phân biệt được agent nào |

---

## 3. INTEGRATION OPTIONS

### Option A: Federated Identity (Simple)

```
┌──────────────┐            ┌──────────────┐
│  LMS DB      │            │  AI DB       │
│  ──────────  │            │  ──────────  │
│  users       │◀─ user_id ─│  memories    │
│  courses     │   (UUID)   │  insights    │
│  progress    │            │  facts       │
└──────────────┘            └──────────────┘
```

**Pros:** Simple, GDPR compliant, clear ownership  
**Cons:** AI không có context về user

### Option B: Data Replication

```
┌──────────────┐   sync    ┌──────────────┐
│  LMS DB      │ ───────▶  │  AI DB       │
│  ──────────  │           │  ──────────  │
│  users       │           │  user_cache  │  ← Replicated
│  courses     │           │  memories    │
└──────────────┘           └──────────────┘
```

**Pros:** AI có full context  
**Cons:** Sync complexity, GDPR risk, data inconsistency

### Option C: Context Injection (⭐ Recommended)

```
┌──────────────┐            ┌──────────────┐
│  LMS Backend │   request  │  AI Backend  │
│  ──────────  │ ─────────▶ │  ──────────  │
│              │  + context │              │
└──────────────┘            └──────────────┘
```

**Pros:** Real-time context, no sync, GDPR compliant  
**Cons:** Larger payload per request

---

## 4. RECOMMENDED ARCHITECTURE

### 4.1. High-Level Design

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    RECOMMENDED INTEGRATION ARCHITECTURE                      │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         LMS SYSTEM                                       ││
│  │                                                                          ││
│  │  [Angular Frontend] ──JWT──▶ [Spring Boot Backend]                      ││
│  │                                    │                                     ││
│  │                                    │ 1. Lookup user info                ││
│  │                                    │ 2. Get current course/module       ││
│  │                                    │ 3. Build context object            ││
│  │                                    │                                     ││
│  └────────────────────────────────────┼─────────────────────────────────────┘│
│                                       │                                      │
│                                       │ API Key + user_id + user_context    │
│                                       ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                     AI BACKEND (FastAPI)                                 ││
│  │                                                                          ││
│  │  1. Receive context from LMS                                             ││
│  │  2. Merge with AI memories                                               ││
│  │  3. Generate personalized response                                       ││
│  │  4. Extract & store new insights (background)                            ││
│  │  5. (Optional) Callback to LMS with events                               ││
│  │                                                                          ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 4.2. Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           REQUEST FLOW                                       │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Step 1: User sends message via Angular                                       │
│  ──────────────────────────────────────                                      │
│  POST /api/chat                                                              │
│  { "message": "Điều 15 là gì?" }                                             │
│                                                                              │
│  Step 2: LMS Backend enriches request                                         │
│  ────────────────────────────────────                                        │
│  → Lookup user from JWT                                                      │
│  → Get current course enrollment                                             │
│  → Get learning progress                                                     │
│  → Build AI request                                                          │
│                                                                              │
│  Step 3: LMS calls AI Backend                                                 │
│  ───────────────────────────────                                             │
│  POST /api/v1/chat                                                           │
│  {                                                                           │
│    "user_id": "550e8400-e29b-41d4-a716-446655440000",                        │
│    "user_context": {                                                         │
│      "display_name": "Minh",                                                 │
│      "role": "student",                                                      │
│      "level": "Sinh viên năm 3",                                             │
│      "current_course_id": "colregs_2024",                                    │
│      "current_course_name": "COLREGs - Quy tắc phòng ngừa đâm va",           │
│      "current_module_id": "rule_13_15",                                      │
│      "progress_percent": 45,                                                 │
│      "completed_modules": ["rule_1_3", "rule_4_10"]                          │
│    },                                                                        │
│    "message": "Điều 15 là gì?",                                              │
│    "session_id": "session-uuid"                                              │
│  }                                                                           │
│                                                                              │
│  Step 4: AI processes with full context                                       │
│  ──────────────────────────────────────                                      │
│  → Retrieve AI memories for user_id                                         │
│  → Merge with user_context                                                   │
│  → Generate personalized response                                            │
│  → "Em Minh ơi, Điều 15 quy định về tình huống cắt hướng..."                │
│                                                                              │
│  Step 5: AI extracts insights (background)                                    │
│  ─────────────────────────────────────────                                   │
│  → "User đang học module rule_13_15"                                         │
│  → "User hỏi về Điều 15" → knowledge_gap?                                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 5. API CONTRACT

### 5.1. LMS → AI: Chat Request

```http
POST /api/v1/chat
X-API-Key: {lms_api_key}
Content-Type: application/json

{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_context": {
    "display_name": "Minh",
    "email": "minh@example.com",           // Optional, cho notification
    "role": "student",                     // student | teacher | admin
    "level": "Sinh viên năm 3",
    "organization": "Đại học Hàng hải",
    
    // Course context
    "current_course_id": "colregs_2024",
    "current_course_name": "COLREGs - Quy tắc phòng ngừa đâm va",
    "current_module_id": "rule_13_15",     // ← Có thể dùng làm process_id
    "current_module_name": "Rule 13-15: Overtaking & Crossing",
    
    // Progress
    "progress_percent": 45,
    "completed_modules": ["rule_1_3", "rule_4_10"],
    "quiz_scores": {
      "rule_1_3": 85,
      "rule_4_10": 72
    }
  },
  "message": "Điều 15 là gì?",
  "session_id": "session-uuid",
  "stream": true                           // SSE streaming
}
```

### 5.2. AI → LMS: Response

```json
{
  "success": true,
  "data": {
    "answer": "Em Minh ơi, **Điều 15 COLREGs** quy định về **tình huống cắt hướng**...",
    "sources": [...],
    "metadata": {
      "topics_accessed": ["Rule 15", "Crossing Situation"],
      "confidence_score": 0.92,
      "query_type": "factual",
      "processing_time": 2.3
    }
  }
}
```

### 5.3. AI → LMS: Event Callback (Optional)

```http
POST {lms_callback_url}/api/v1/ai-events
X-Callback-Secret: {shared_secret}
Content-Type: application/json

{
  "user_id": "550e8400-...",
  "event_type": "knowledge_gap_detected",
  "data": {
    "topic": "Rule 15 - Crossing Situation",
    "gap_type": "conceptual",
    "confidence": 0.9,
    "suggested_action": "review_module",
    "module_id": "rule_13_15"
  },
  "timestamp": "2025-12-12T23:00:00Z"
}
```

**Event Types:**
| Event | Description | LMS Action |
|-------|-------------|------------|
| `knowledge_gap_detected` | AI phát hiện lỗ hổng | Suggest review module |
| `goal_evolution` | User đổi mục tiêu học | Update learning path |
| `module_completed_confidence` | AI nghĩ user đã hiểu module | Suggest quiz |
| `stuck_detected` | User hỏi lặp lại topic | Trigger support |

---

## 6. DATA OWNERSHIP

### 6.1. Clear Boundaries

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           DATA OWNERSHIP                                     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  LMS OWNS (Source of Truth):                                                 │
│  ─────────────────────────────                                               │
│  ✓ Users (identity, email, password hash)                                    │
│  ✓ Courses & Modules (curriculum structure)                                  │
│  ✓ Enrollments & Progress                                                    │
│  ✓ Quiz results & Grades                                                     │
│  ✓ Certificates                                                              │
│  ✓ Forum posts, Comments                                                     │
│                                                                              │
│  AI OWNS:                                                                    │
│  ─────────                                                                   │
│  ✓ Semantic Memories (insights, facts)                                       │
│  ✓ Conversation Summaries                                                    │
│  ✓ Learning Style Insights                                                   │
│  ✓ Knowledge Gap Analysis                                                    │
│  ✓ Knowledge Embeddings (documents)                                          │
│                                                                              │
│  SHARED:                                                                     │
│  ───────                                                                     │
│  ◐ Knowledge Graph                                                           │
│    - LMS provides: Curriculum structure, module relationships               │
│    - AI provides: Topic relationships, concept links                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 6.2. GDPR Data Handling

| Data Type | AI Storage | Retention | Deletion |
|-----------|------------|-----------|----------|
| `user_id` | ✓ Store | Indefinite | On user request |
| `display_name` | ✓ Cached | 24h TTL | Auto-expire |
| `email` | ✗ Don't store | - | - |
| `insights` | ✓ Store | 1 year | On user request |
| `conversation` | ✓ Summarized | 30 days raw | Auto-delete |

### 6.3. Data Deletion API

```http
DELETE /api/v1/users/{user_id}/data
X-API-Key: {admin_api_key}

Response:
{
  "deleted": {
    "memories": 45,
    "insights": 12,
    "facts": 8,
    "summaries": 3
  },
  "status": "completed",
  "timestamp": "2025-12-12T23:00:00Z"
}
```

---

## 7. KNOWLEDGE GRAPH STRATEGY

### 7.1. Phased Approach

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    KNOWLEDGE GRAPH ROADMAP                                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 1: DOCUMENT KNOWLEDGE GRAPH (Q1 2025)                                 │
│  ───────────────────────────────────────────                                 │
│  Owner: AI Team                                                              │
│  Purpose: Better RAG, related topics suggestion                              │
│                                                                              │
│  ┌─────────────┐     relates_to     ┌─────────────┐                         │
│  │  COLREGs    │──────────────────▶│   SOLAS     │                         │
│  │   (doc)     │                    │   (doc)     │                         │
│  └──────┬──────┘                    └─────────────┘                         │
│         │ contains                                                           │
│         ▼                                                                    │
│  ┌─────────────┐     prerequisite   ┌─────────────┐                         │
│  │  Rule 15    │◀──────────────────│  Rule 13    │                         │
│  │ (section)   │                    │ (section)   │                         │
│  └─────────────┘                    └─────────────┘                         │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 2: CURRICULUM INTEGRATION (Q2 2025)                                   │
│  ──────────────────────────────────────────                                  │
│  Owner: LMS + AI Team                                                        │
│  Purpose: Map documents to courses/modules                                   │
│                                                                              │
│  ┌─────────────┐     used_in        ┌─────────────┐                         │
│  │  Rule 15    │──────────────────▶│ Module 5    │                         │
│  │ (AI doc)    │                    │ (LMS)       │                         │
│  └─────────────┘                    └─────────────┘                         │
│                                                                              │
│  LMS provides:                                                               │
│  - Curriculum structure API                                                  │
│  - Module → Topic mapping                                                    │
│                                                                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  PHASE 3: USER LEARNING GRAPH (Q3 2025)                                      │
│  ──────────────────────────────────────                                      │
│  Owner: AI Team (with LMS data)                                              │
│  Purpose: Personalized learning paths                                        │
│                                                                              │
│  ┌─────────────┐      studied       ┌─────────────┐                         │
│  │  User 123   │──────────────────▶│  Rule 15    │                         │
│  │             │     (progress: 50%)│ (section)   │                         │
│  └──────┬──────┘                    └─────────────┘                         │
│         │                                                                    │
│         │ weak_at                                                            │
│         ▼                                                                    │
│  ┌─────────────┐                                                            │
│  │Crossing     │                                                            │
│  │Situations   │                                                            │
│  └─────────────┘                                                            │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 7.2. LMS Input Needed for Knowledge Graph

| Data | Source | Format | Frequency |
|------|--------|--------|-----------|
| Course list | LMS | JSON API | On change |
| Module structure | LMS | JSON API | On change |
| Prerequisites | LMS | JSON API | On change |
| Learning objectives | LMS | JSON API | On change |
| User progress | LMS | Request payload | Real-time |

---

## 8. SECURITY & COMPLIANCE

### 8.1. Authentication

| Layer | Method |
|-------|--------|
| Frontend → LMS | JWT Token |
| LMS → AI | API Key + IP Whitelist |
| AI → LMS Callback | Shared Secret + HMAC |

### 8.2. API Key Management

```yaml
# AI Backend config
api_keys:
  lms_production:
    key: "sk_live_..."
    permissions: ["chat", "stream", "memories"]
    rate_limit: 1000/min
    ip_whitelist: ["10.0.0.0/8"]
    
  lms_staging:
    key: "sk_test_..."
    permissions: ["chat", "stream"]
    rate_limit: 100/min
```

### 8.3. Data in Transit

- HTTPS/TLS 1.3 required
- Certificate pinning (optional)
- Request signing for callbacks

---

## 9. DISCUSSION POINTS

### 9.1. Cần Quyết Định

| # | Question | Options | AI Team Recommendation |
|---|----------|---------|------------------------|
| 1 | User ID format? | UUID v4 / LMS internal ID | UUID v4 |
| 2 | Include email in context? | Yes / No | No (privacy) |
| 3 | Callback URL? | Push / Pull | Push (real-time) |
| 4 | Module ID as process_id? | Yes / No | Yes |
| 5 | Knowledge Graph Phase 2 timeline? | Q2 / Q3 2025 | Q2 2025 |

### 9.2. Open Questions

1. **Quiz Integration**: AI có thể suggest quiz khi detect user đã hiểu topic?
2. **Progress Sync**: LMS có API để AI query progress? Hay chỉ nhận passive qua context?
3. **Multi-language**: User context có field `language`? AI cần respond đúng ngôn ngữ?
4. **Offline Mode**: Nếu LMS → AI connection fail, có fallback?

---

## 10. NEXT STEPS

### Immediate (This Week)

| # | Action | Owner | Deadline |
|---|--------|-------|----------|
| 1 | Review this document | LMS Team | 15/12/2025 |
| 2 | Schedule sync meeting | Both | 16/12/2025 |
| 3 | Feedback & questions | LMS Team | 17/12/2025 |

### Short-term (2 Weeks)

| # | Action | Owner |
|---|--------|-------|
| 4 | Finalize API contract | Both |
| 5 | Update AI Backend code | AI Team |
| 6 | Update LMS Backend code | LMS Team |
| 7 | Integration testing | Both |

### Medium-term (Q1 2025)

| # | Action | Owner |
|---|--------|-------|
| 8 | Document Knowledge Graph | AI Team |
| 9 | Curriculum API | LMS Team |
| 10 | Event callbacks | Both |

---

## APPENDIX

### A. Glossary

| Term | Definition |
|------|------------|
| Entity | User hoặc object được track (MemoriLabs concept) |
| Process | Agent hoặc module xử lý interaction |
| Insight | AI-extracted behavioral understanding |
| Fact | Atomic piece of user information |
| Knowledge Graph | Graph database linking concepts |

### B. References

- [MemoriLabs Documentation](https://memorilabs.ai/docs/)
- [Maritime AI Tutor README](../README.md)
- [Memory Architecture](./MEMORY_ARCHITECTURE_FOR_LMS.md)
- [MemoriLabs Research](./MEMORILABS_RESEARCH_20251212.md)

---

*Document prepared by AI Backend Team*  
*For discussion with LMS Backend Team*
