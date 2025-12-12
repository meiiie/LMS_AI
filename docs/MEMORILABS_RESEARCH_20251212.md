# MemoriLabs Research Report - So Sánh Với Hệ Thống Hiện Tại

**Date:** 12/12/2025  
**Source:** [MemoriLabs Docs](https://memorilabs.ai/docs/), [GitHub](https://github.com/MemoriLabs/Memori)

---

## 1. TỔNG QUAN MEMORILABS

MemoriLabs là **SQL-native Memory Layer** cho LLMs, AI Agents & Multi-Agent Systems.

### Core Philosophy
- **Zero Latency**: Background processing (Advanced Augmentation)
- **SQL-native**: Dùng database có sẵn (PostgreSQL, Neon, Supabase...)
- **LLM Agnostic**: OpenAI, Gemini, Anthropic, Bedrock
- **Framework Agnostic**: LangChain, Pydantic AI

---

## 2. KIẾN TRÚC MEMORILABS

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MEMORILABS ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                        CORE ABSTRACTIONS                                ││
│  ├─────────────┬─────────────┬─────────────┬─────────────┐                ││
│  │   ENTITY    │   PROCESS   │   SESSION   │   FACTS     │                ││
│  │  (user)     │  (agent)    │ (workflow)  │ (memories)  │                ││
│  └─────────────┴─────────────┴─────────────┴─────────────┘                ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                      SEMANTIC TRIPLES (NER)                             ││
│  │             Subject ──── Predicate ──── Object                          ││
│  │            (entity)     (relation)      (value)                         ││
│  │                                                                         ││
│  │  Example: "User" ─── "likes" ─── "blue color"                           ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                      KNOWLEDGE GRAPH                                    ││
│  │                 (memori_knowledge_graph table)                          ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                    │                                         │
│                                    ▼                                         │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                      VECTOR SEARCH (FAISS)                              ││
│  │              768-dim embeddings + Semantic Search                       ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. BẢNG SO SÁNH CHI TIẾT

| Feature | MemoriLabs | Maritime AI Tutor | Gap |
|---------|------------|-------------------|-----|
| **Memory Types** | Facts, Attributes, Events, Skills | Facts, Insights | ⚠️ Thiếu Events, Skills |
| **Entity/Process** | Rõ ràng (entity_id, process_id) | user_id only | ⚠️ Thiếu process tracking |
| **Semantic Triples** | ✅ Subject-Predicate-Object | ❌ Không có | 🔴 Gap |
| **Knowledge Graph** | ✅ memori_knowledge_graph | ❌ Không có | 🔴 Gap |
| **Vector Dim** | 768 (sentence transformer) | 768 (Gemini) | ✅ Tương đương |
| **Vector DB** | FAISS (in-memory) | pgvector | ✅ Tương đương |
| **Duplicate Detection** | ✅ Automatic dedupe | ✅ 0.85/0.90 cosine | ✅ SOTA |
| **Session Grouping** | ✅ Auto session | ✅ session_id | ✅ Có |
| **Background Processing** | ✅ Async augmentation | ❌ Sync | ⚠️ Gap |
| **LLM Intercept** | ✅ Automatic via register() | ❌ Manual | ⚠️ Gap |
| **Insight Categories** | Facts, Attributes only | 5 categories | ✅ Chúng ta tốt hơn |
| **Consolidation** | ❌ Không thấy | ✅ LLM 40→30 | ✅ Chúng ta tốt hơn |

---

## 4. ĐIỂM NỔI BẬT CỦA MEMORILABS

### 4.1. Semantic Triples (Subject-Predicate-Object)
```
"My favorite color is blue"
    ↓ NER Extraction
Subject: "User"
Predicate: "favorite color"  
Object: "blue"
```
→ **Lợi ích:** Cấu trúc hóa facts, dễ query, dễ dedupe

### 4.2. Attribution Model
```python
mem.attribution(entity_id="user_123", process_id="tutor_agent")
```
- **Entity**: User, Customer, Student...
- **Process**: AI Agent, Chatbot, Tutor...
→ **Lợi ích:** Một user có thể interact với nhiều agents, mỗi agent nhớ context riêng

### 4.3. Advanced Augmentation (Background)
```
LLM Response → (async) → Extract Facts → Dedupe → Store
```
→ **Lợi ích:** Zero latency impact on user experience

### 4.4. Automatic LLM Intercept
```python
mem = Memori().llm.register(client)
# Tất cả calls tự động được track
```
→ **Lợi ích:** DX tuyệt vời, không cần sửa code

---

## 5. ĐIỂM CHÚNG TA TỐT HƠN

### 5.1. Insight Categories (5 vs 2)
```
Maritime AI: learning_style, knowledge_gap, goal_evolution, habit, preference
MemoriLabs: facts, attributes only
```
→ **Chúng ta tốt hơn** cho educational use cases

### 5.2. LLM Consolidation
```
Maritime AI: 40 → 30 insights via LLM
MemoriLabs: Không thấy consolidation
```
→ **Chúng ta tốt hơn** về memory management

### 5.3. Duplicate Detection SOTA
```
Maritime AI: 0.85 cosine (insight), 0.90 (fact)
MemoriLabs: Automatic dedupe (không rõ threshold)
```
→ **Tương đương hoặc tốt hơn**

---

## 6. GỢI Ý CẢI TIẾN

| Priority | Feature | Effort | Impact |
|----------|---------|--------|--------|
| 🔴 High | **Semantic Triples** | Medium | Cấu trúc facts tốt hơn |
| 🟡 Medium | **Process Attribution** | Low | Multi-agent support |
| 🟡 Medium | **Background Extraction** | Medium | Better UX |
| 🟢 Low | **Knowledge Graph** | High | Long-term relationships |

### 6.1. Semantic Triples Implementation
```python
# Thay vì lưu:
"User thích học qua ví dụ thực tế"

# Lưu:
{
  "subject": "user_123",
  "predicate": "learning_style",
  "object": "practical examples",
  "confidence": 0.9
}
```

### 6.2. Process Attribution
```python
# Current
user_id = "123"

# Proposed
entity_id = "123"  # User
process_id = "tutor_agent"  # Which agent/feature
```

---

## 7. KẾT LUẬN

| Aspect | MemoriLabs | Maritime AI |
|--------|------------|-------------|
| **Architecture** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ |
| **DX (Developer Experience)** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ |
| **Educational Features** | ⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Memory Management** | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **SOTA Compliance** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ |

**Kết luận:** 
- MemoriLabs có **kiến trúc tốt hơn** (Semantic Triples, Knowledge Graph, Attribution)
- Maritime AI Tutor có **features giáo dục tốt hơn** (Insight categories, Consolidation)
- Có thể học từ MemoriLabs: **Semantic Triples** và **Process Attribution**
