# 📊 BÁO CÁO KỸ THUẬT TUẦN 3 - MARITIME AI CHATBOT
## Dành cho Chuyên gia Đánh giá

**Ngày báo cáo:** 28/11/2025  
**Phiên bản:** 0.1.0  
**Trạng thái:** ✅ PRODUCTION READY

---

## 1. TỔNG QUAN DỰ ÁN

### 1.1 Mục tiêu
Xây dựng AI Tutor Microservice cho hệ thống LMS Hàng Hải, hỗ trợ sinh viên học tập quy tắc COLREGs (Quy tắc phòng ngừa va chạm tàu thuyền trên biển).

### 1.2 Kiến trúc hệ thống
```
┌─────────────────────────────────────────────────────────────────┐
│                        LMS CORE                                  │
│                    (Frontend + Backend)                          │
└─────────────────────────────┬───────────────────────────────────┘
                              │ REST API (JSON)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   MARITIME AI SERVICE                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐  │
│  │   FastAPI   │  │  LangGraph  │  │    Role-Based Prompting │  │
│  │   Gateway   │──│  Orchestrator│──│  (Student/Teacher/Admin)│  │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘  │
│         │                │                      │                │
│  ┌──────▼──────┐  ┌──────▼──────┐  ┌───────────▼───────────┐   │
│  │   Guardrails │  │  RAG Tool   │  │    Tutor Agent        │   │
│  │   (Safety)   │  │  (Knowledge)│  │    (Pedagogy)         │   │
│  └──────────────┘  └──────────────┘  └──────────────────────┘   │
└─────────────────────────────┬───────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│   Supabase    │    │   Neo4j Aura  │    │   OpenRouter  │
│  PostgreSQL   │    │ Knowledge Graph│    │   (Grok 4.1)  │
│  (Chat History)│    │   (COLREGs)   │    │   LLM API     │
└───────────────┘    └───────────────┘    └───────────────┘
```

---

## 2. CÔNG NGHỆ SỬ DỤNG

### 2.1 Backend Stack
| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| Framework | FastAPI | 0.104+ | REST API Gateway |
| AI Orchestration | LangGraph | 0.2+ | Multi-agent workflow |
| LLM Provider | OpenRouter | - | Grok 4.1 Fast (Free tier) |
| Database | Supabase PostgreSQL | 15+ | Chat history, user data |
| Knowledge Graph | Neo4j Aura | 5.x | COLREGs knowledge base |
| Rate Limiting | SlowAPI | 0.1+ | API protection |

### 2.2 Cloud Infrastructure
| Service | Provider | Tier | Purpose |
|---------|----------|------|---------|
| Hosting | Render | Free | API deployment |
| Database | Supabase | Free | PostgreSQL managed |
| Graph DB | Neo4j Aura | Free | Knowledge graph |
| LLM | OpenRouter | Free | AI inference |

---

## 3. API SPECIFICATION

### 3.1 Endpoints

#### POST /api/v1/chat
**Mô tả:** Chat completion endpoint cho LMS

**Request:**
```json
{
  "user_id": "string (required)",
  "message": "string (required, 1-10000 chars)",
  "role": "student | teacher | admin (required)",
  "session_id": "string (optional)",
  "context": {
    "course_id": "string (optional)",
    "lesson_id": "string (optional)"
  }
}
```

**Response:**
```json
{
  "status": "success | error",
  "data": {
    "answer": "string (Markdown format)",
    "sources": [
      {
        "title": "string",
        "content": "string"
      }
    ],
    "suggested_questions": ["string", "string", "string"]
  },
  "metadata": {
    "processing_time": 1.25,
    "model": "maritime-rag-v1",
    "agent_type": "tutor | rag | chat"
  }
}
```

#### GET /health
**Response:**
```json
{
  "status": "ok",
  "database": "connected | disconnected"
}
```

### 3.2 Authentication
- Header: `X-API-Key`
- Value: Configured via environment variable `LMS_API_KEY`

### 3.3 Rate Limiting
- 100 requests/minute per IP
- 429 Too Many Requests when exceeded

---

## 4. ROLE-BASED PROMPTING

### 4.1 Student Role (Tutor Mode)
```
Persona: Gia sư thân thiện, kiên nhẫn
Approach: Socratic method - hỏi ngược để kích thích tư duy
Features:
- Giải thích từng bước
- Đưa ví dụ thực tế
- Câu hỏi kiểm tra hiểu biết
- Khuyến khích học tập
```

### 4.2 Teacher/Admin Role (Assistant Mode)
```
Persona: Trợ lý chuyên nghiệp
Approach: Direct answers với citations
Features:
- Trả lời trực tiếp, đầy đủ
- Trích dẫn nguồn chính xác
- Hỗ trợ soạn bài giảng
- Phân tích chuyên sâu
```

---

## 5. SECURITY MEASURES

### 5.1 Input Validation
- Pydantic schema validation
- Message length limits (1-10000 chars)
- Whitespace-only rejection
- SQL injection prevention

### 5.2 Content Safety (Guardrails)
- Off-topic detection
- Harmful content filtering
- Maritime domain enforcement
- Prompt injection protection

### 5.3 API Security
- API Key authentication
- Rate limiting (SlowAPI)
- CORS configuration
- Error message sanitization

---

## 6. TESTING COVERAGE

### 6.1 Property-Based Tests (Hypothesis)
| Test File | Properties | Status |
|-----------|------------|--------|
| test_serialization_properties.py | Round-trip JSON | ✅ Pass |
| test_guardrails_properties.py | Safety filtering | ✅ Pass |
| test_rate_limit_properties.py | Rate limiting | ✅ Pass |
| test_health_properties.py | Health check | ✅ Pass |
| test_tutor_properties.py | Tutor responses | ✅ Pass |
| test_orchestrator_properties.py | Agent routing | ✅ Pass |
| test_memory_properties.py | Memory management | ✅ Pass |
| test_knowledge_graph_properties.py | Graph queries | ✅ Pass |
| test_learning_profile_properties.py | Profile updates | ✅ Pass |

### 6.2 Test Execution
```bash
pytest tests/property/ -v --hypothesis-show-statistics
```

---

## 7. DEPLOYMENT

### 7.1 Production URL
- **Base URL:** https://maritime-ai-chatbot.onrender.com
- **Swagger UI:** https://maritime-ai-chatbot.onrender.com/docs
- **Health Check:** https://maritime-ai-chatbot.onrender.com/health

### 7.2 Environment Variables
```env
APP_NAME=Maritime AI Tutor
APP_VERSION=0.1.0
DEBUG=false
ENVIRONMENT=production
API_V1_PREFIX=/api/v1
LMS_API_KEY=<secret>
NEO4J_URI=neo4j+s://<instance>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<secret>
DATABASE_URL=postgresql://<connection_string>
OPENAI_API_KEY=<openrouter_key>
OPENAI_BASE_URL=https://openrouter.ai/api/v1
OPENAI_MODEL=x-ai/grok-4.1-fast:free
```

### 7.3 CI/CD Pipeline
- GitHub repository: https://github.com/meiiie/LMS_AI
- Auto-deploy on push to `main` branch
- Render handles build and deployment

---

## 8. PERFORMANCE METRICS

### 8.1 Response Times (Observed)
| Metric | Value | Target |
|--------|-------|--------|
| Cold Start | ~20-30s | <60s |
| Warm Response | ~2-5s | <10s |
| Health Check | <100ms | <500ms |

### 8.2 Scalability
- Render free tier: 512MB RAM, shared CPU
- Auto-sleep after 15 min inactivity
- Horizontal scaling available (paid tier)

---

## 9. KNOWN LIMITATIONS

### 9.1 Free Tier Constraints
1. **Cold Start:** ~30s delay after inactivity
2. **Rate Limits:** OpenRouter free tier limits
3. **Database:** Supabase free tier (500MB)
4. **Neo4j:** Aura free tier (limited nodes)

### 9.2 Future Improvements
1. Implement chat history persistence
2. Add learning profile tracking
3. Expand COLREGs knowledge base
4. Add Vietnamese language support for AI responses
5. Implement caching layer (Redis)

---

## 10. COMPLIANCE

### 10.1 CHỈ THỊ KỸ THUẬT SỐ 03
| Requirement | Status |
|-------------|--------|
| POST /api/v1/chat endpoint | ✅ Implemented |
| GET /health endpoint | ✅ Implemented |
| JSON request/response format | ✅ Compliant |
| Role-based prompting | ✅ Implemented |
| Error handling | ✅ Implemented |
| API documentation | ✅ Swagger UI |

### 10.2 Code Quality
- Clean Architecture pattern
- Type hints throughout
- Pydantic validation
- Comprehensive error handling
- Property-based testing

---

## 11. SOURCE CODE STRUCTURE

```
maritime-ai-service/
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── chat.py          # Chat endpoint
│   │       └── health.py        # Health endpoint
│   ├── core/
│   │   ├── config.py            # Settings
│   │   ├── security.py          # Auth
│   │   └── rate_limit.py        # Rate limiting
│   ├── engine/
│   │   ├── agents/
│   │   │   └── chat_agent.py    # LangGraph orchestrator
│   │   ├── tools/
│   │   │   ├── rag_tool.py      # RAG retrieval
│   │   │   └── tutor_agent.py   # Tutor logic
│   │   ├── guardrails.py        # Safety filters
│   │   └── memory.py            # Memory management
│   ├── models/
│   │   ├── schemas.py           # Pydantic models
│   │   └── database.py          # SQLAlchemy models
│   ├── repositories/
│   │   ├── chat_history_repository.py
│   │   ├── knowledge_graph_repository.py
│   │   └── learning_profile_repository.py
│   ├── services/
│   │   └── chat_service.py      # Business logic
│   └── main.py                  # FastAPI app
├── tests/
│   └── property/                # Property-based tests
├── requirements.txt
├── render.yaml                  # Render config
└── README.md
```

---

**Prepared by:** AI Development Team  
**Review Status:** Ready for Expert Evaluation
