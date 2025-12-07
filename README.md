# Maritime AI Tutor Service

<div align="center">

![Maritime AI Tutor Banner](assets/banner_AI_LMS.jpeg)

[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangChain](https://img.shields.io/badge/LangChain-1.1.2-1c3c3c?style=flat-square&logo=chainlink&logoColor=white)](https://langchain.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0.4-purple?style=flat-square)](https://langchain.com)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.28-008cc1?style=flat-square&logo=neo4j&logoColor=white)](https://neo4j.com)
[![Neon](https://img.shields.io/badge/Neon-pgvector-00E599?style=flat-square&logo=postgresql&logoColor=white)](https://neon.tech)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash-4285F4?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev)
[![License](https://img.shields.io/badge/License-Proprietary-red?style=flat-square)](LICENSE)

**AI-Powered Maritime Education Platform with Agentic RAG, Semantic Memory & Long-term Personalization**

*Backend AI Service cho hệ thống LMS Hàng hải*

[Architecture](#architecture) • [Quick Start](#quick-start) • [API Reference](#api-reference) • [Deployment](#deployment)

</div>

---

## Overview

Maritime AI Tutor Service là một **Backend AI microservice** được thiết kế để tích hợp với hệ thống LMS (Learning Management System) hàng hải. Hệ thống cung cấp:

- **Intelligent Tutoring**: AI Tutor với role-based prompting (Student/Teacher/Admin)
- **Hybrid Search v0.5**: Kết hợp Dense Search (pgvector) + Sparse Search (Neo4j Full-text) với RRF Reranking
- **GraphRAG Knowledge Retrieval**: Truy vấn kiến thức từ SOLAS, COLREGs, MARPOL
- **Semantic Memory v0.3**: Ghi nhớ ngữ cảnh cross-session với pgvector + Gemini embeddings
- **Guardian Agent v0.8.1**: LLM-based Content Moderation với Gemini 2.5 Flash - Custom Pronoun Validation, Contextual Filtering
- **Content Guardrails**: Bảo vệ nội dung với PII masking và prompt injection detection

---

## Features

### Multi-Agent Architecture (v0.5.3)

| Agent | Function | Trigger Keywords (EN + VN) |
|-------|----------|----------------------------|
| **Chat Agent** | General conversation | No maritime keywords |
| **RAG Agent** | Knowledge Graph queries | `solas`, `colregs`, `marpol`, `rule`, `luật`, `quy định`, `tàu`, `nhường đường`, `cắt hướng`... (70 keywords) |
| **Tutor Agent** | Structured teaching | `teach`, `learn`, `quiz`, `dạy`, `học`, `giải thích`... |

### Dynamic Persona System (v0.7.4)

Hệ thống persona được cấu hình qua file YAML, hỗ trợ cá nhân hóa theo role và user.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         PERSONA CONFIGURATION                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   app/prompts/                                                               │
│   ├── tutor.yaml      → Student Role (Captain AI - Mentor)                  │
│   └── assistant.yaml  → Teacher/Admin Role (Maritime Pro Assistant)         │
│                                                                              │
│   YAML Structure:                                                            │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ profile:                                                             │   │
│   │   name: "Captain AI"                                                 │   │
│   │   role: "Senior Maritime Mentor"                                     │   │
│   │   backstory: "Bạn là Thuyền phó 1 đã về hưu..."                     │   │
│   │                                                                      │   │
│   │ style:                                                               │   │
│   │   tone: ["Ấm áp", "Hài hước nghề biển"]                             │   │
│   │   addressing_rules: ["Thầy/Cô", "Anh/Chị"]  # For assistant.yaml    │   │
│   │                                                                      │   │
│   │ thought_process:                                                     │   │
│   │   1_analyze: "User đang hỏi kiến thức hay chia sẻ cảm xúc?"         │   │
│   │   2_empathy: "Nếu user mệt -> Đồng cảm trước"                       │   │
│   │                                                                      │   │
│   │ directives:                                                          │   │
│   │   dos: ["Gọi tên user ({{user_name}}) khi nhấn mạnh"]               │   │
│   │   donts: ["KHÔNG bắt đầu bằng 'Chào bạn'"]                          │   │
│   │                                                                      │   │
│   │ few_shot_examples:                                                   │   │
│   │   - context: "User than mệt"                                         │   │
│   │     user: "Học COLREGs chán quá"                                     │   │
│   │     ai: "Ha ha, bệnh chung của dân đi biển rồi! 🌊"                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   Template Variables:                                                        │
│   • {{user_name}} → Replaced with actual name from Memory                   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Role-Based Prompting

```
┌─────────────────────────────────────────────────────────────┐
│  Student Role → tutor.yaml (Captain AI)                     │
│  • Persona: Thuyền phó 1 về hưu, truyền lửa nghề           │
│  • Tone: Ấm áp, hài hước, như người anh đi trước           │
│  • Style: Socratic method, ví dụ thực tế trên boong tàu    │
├─────────────────────────────────────────────────────────────┤
│  Teacher/Admin Role → assistant.yaml (Maritime Pro)         │
│  • Persona: Cán bộ hỗ trợ học thuật                        │
│  • Tone: Lịch sự, tôn trọng, kính ngữ phù hợp              │
│  • Style: Xưng hô đúng mực (Thầy/Cô, Anh/Chị)              │
└─────────────────────────────────────────────────────────────┘
```

### Hybrid Search v0.5.2 (Dense + Sparse + RRF + Title Boosting)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           HYBRID SEARCH PIPELINE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Query: "Rule 15 crossing situation"                                        │
│                     │                                                        │
│         ┌──────────┴──────────┐                                             │
│         ▼                     ▼                                             │
│   ┌───────────────┐    ┌───────────────┐                                    │
│   │ Dense Search  │    │ Sparse Search │                                    │
│   │ (pgvector)    │    │ (Neo4j FTS)   │                                    │
│   │               │    │               │                                    │
│   │ Semantic      │    │ Keyword       │                                    │
│   │ Similarity    │    │ Matching      │                                    │
│   │ (Cosine)      │    │ (BM25-like)   │                                    │
│   └───────┬───────┘    └───────┬───────┘                                    │
│           │                    │                                             │
│           └────────┬───────────┘                                             │
│                    ▼                                                         │
│           ┌───────────────────┐                                             │
│           │   RRF Reranker    │                                             │
│           │   (k=60)          │                                             │
│           │                   │                                             │
│           │ + Title Boosting  │  ← NEW in v0.5.2                            │
│           │ + Sparse Priority │  ← Strong Boost x3.0                        │
│           └─────────┬─────────┘                                             │
│                     ▼                                                        │
│           ┌───────────────────┐                                             │
│           │  Merged Results   │                                             │
│           │  (Top-K by RRF)   │                                             │
│           └───────────────────┘                                             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Dense Search (pgvector)**: Semantic similarity với Gemini embeddings (768 dims, L2 normalized)
- **Sparse Search (Neo4j Full-text)**: Keyword matching với BM25-like scoring
- **RRF Reranker**: Reciprocal Rank Fusion (k=60) - boost documents xuất hiện ở cả 2 nguồn
- **Title Match Boosting v2**: Strong Boost x3.0 cho số hiệu (Rule 15, 19...) và proper nouns (COLREGs, SOLAS, MARPOL)
- **Sparse Priority Boost**: 1.5x boost cho exact keyword matches (sparse score > 15.0)
- **Top-1 Citation Accuracy**: 100% - Rule đúng luôn ở vị trí #1
- **Graceful Degradation**: Fallback về Sparse-only nếu Dense không khả dụng

### Test Results (04/12/2024)

```
✅ RAG Agent Response:
   Query: "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng"
   Agent: rag
   Sources: 5 (Top-1: COLREGs Rule 15 - Crossing Situation)
   Suggestions: 3 context-aware questions
   
✅ Agent Routing (v0.5.3 HOTFIX):
   - 70 keywords (15 EN + 55 VN) cho intent classification
   - Phrase-level matching: "nhường đường", "cắt hướng", "đăng ký tàu"
   - 9/9 test cases passed (100% accuracy)
```

### Semantic Memory v0.4 (Managed Memory List - CHỈ THỊ 23)

- **pgvector + Gemini Embeddings**: Vector similarity search (768 dimensions)
- **User Facts Extraction**: Tự động trích xuất thông tin người dùng (tên, sở thích, mục tiêu)
- **Cross-Session Persistence**: Ghi nhớ ngữ cảnh qua nhiều phiên chat
- **Memory Capping**: Giới hạn 50 facts/user, xóa FIFO khi đầy
- **True Deduplication**: Upsert thay vì Append (1 fact per type)
- **Fact Type Validation**: 6 loại cho phép (name, role, level, goal, preference, weakness)
- **Memory API**: `GET /api/v1/memories/{user_id}` - Lấy danh sách facts

### Deep Reasoning v0.8.3 (CHỈ THỊ 21 & 22)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         DEEP REASONING FLOW                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   User Message                                                               │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                    CONVERSATION ANALYZER                             │   │
│   │  • Detect incomplete explanations                                    │   │
│   │  • Identify proactive continuation opportunities                     │   │
│   │  • Track conversation context                                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                    THINKING PROCESS                                  │   │
│   │  <thinking>                                                          │   │
│   │    Người dùng hỏi về Rule 15...                                      │   │
│   │    Mình cần giải thích rõ ràng với ví dụ thực tế...                  │   │
│   │  </thinking>                                                         │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                    PROACTIVE CONTINUATION                            │   │
│   │  • If user interrupts → Offer to continue previous topic             │   │
│   │  • "Bạn có muốn quay lại với Rule 15 không?"                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                    MEMORY ISOLATION                                  │   │
│   │  • Blocked messages excluded from context                            │   │
│   │  • Only clean history sent to LLM                                    │   │
│   │  • Context window: 50 messages (configurable)                        │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Thinking Tags**: AI sử dụng `<thinking>` để suy nghĩ trước khi trả lời
- **Proactive Continuation**: AI chủ động hỏi user muốn nghe tiếp khi bị ngắt
- **Memory Isolation**: Tin nhắn bị block không xuất hiện trong context
- **Context Window**: 50 messages (tăng từ 10), configurable qua `CONTEXT_WINDOW_SIZE`
- **ConversationAnalyzer**: Phát hiện giải thích chưa hoàn thành

### Guardian Agent v0.8.1 (LLM Content Moderation)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         GUARDIAN AGENT FLOW                                  │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   User Message                                                               │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐                   │
│   │ Quick Check │ ──▶ │ LLM Validate│ ──▶ │  Decision   │                   │
│   │ (Skip LLM?) │     │ (Gemini)    │     │             │                   │
│   └─────────────┘     └─────────────┘     └─────────────┘                   │
│         │                    │                   │                           │
│         │ Simple greeting    │ Contextual        │ ALLOW → Continue         │
│         │ → Skip LLM         │ analysis          │ BLOCK → Reject           │
│         │ → ALLOW            │                   │ FLAG  → Log & Continue   │
│         │                    │                   │                           │
│         └────────────────────┴───────────────────┘                           │
│                                                                              │
│   Features:                                                                  │
│   • Custom Pronoun Validation: "Gọi tôi là công chúa" → ALLOW               │
│   • Contextual Filtering: "cướp biển" in maritime → ALLOW                   │
│   • Inappropriate Detection: "mày/tao" → BLOCK                              │
│   • Caching: 1h TTL for repeated messages                                   │
│   • Fallback: Rule-based Guardrails when LLM unavailable                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **LLM-based Validation**: Sử dụng Gemini 2.5 Flash thay vì hardcoded patterns
- **Custom Pronoun Support**: Validate và lưu custom pronouns ("công chúa", "thuyền trưởng")
- **Contextual Understanding**: Hiểu ngữ cảnh hàng hải (piracy, cướp biển)
- **Performance Optimized**: Skip LLM cho greetings, cache decisions
- **Graceful Fallback**: Tự động dùng rule-based khi LLM không khả dụng

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LMS FRONTEND                                    │
│                         (Angular - Port 4200)                               │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ HTTP/REST
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MARITIME AI SERVICE                                  │
│                        (FastAPI - Port 8000)                                │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                          API Layer (v1)                                │  │
│  │  POST /chat  │  GET /health  │  Rate Limit (30/min)  │  Auth (API Key) │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        Service Layer                                   │  │
│  │  ChatService: Guardian → Guardrails → Intent → Agent Routing → Response│  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        Engine Layer (LangGraph)                       │  │
│  │  Orchestrator │ Chat Agent │ RAG Agent │ Tutor Agent │ Semantic Memory │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      Repository Layer                                  │  │
│  │  ChatHistory │ SemanticMemory │ DenseSearch │ SparseSearch │ Neo4j     │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      Hybrid Search Service                             │  │
│  │  Dense (pgvector) + Sparse (Neo4j FTS) → RRF Reranker → Merged Results │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │                         │                         │
          ▼                         ▼                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   PostgreSQL    │     │     Neo4j       │     │  Google Gemini  │
│   (Neon)        │     │  Knowledge      │     │  2.5 Flash      │
│   + pgvector    │     │  Graph + FTS    │     │  + Embeddings   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

---

## Project Structure

```
maritime-ai-service/
├── app/
│   ├── api/v1/                      # API endpoints (chat, health, knowledge)
│   ├── core/                        # Config, security, rate_limit
│   ├── engine/
│   │   ├── agents/chat_agent.py     # Chat Agent
│   │   ├── tools/rag_tool.py        # RAG Agent with Neo4j
│   │   ├── tools/tutor_agent.py     # Tutor Agent
│   │   ├── graph.py                 # LangGraph Orchestrator
│   │   ├── guardrails.py            # Input/Output validation (rule-based)
│   │   ├── guardian_agent.py        # LLM Content Moderation (Gemini 2.5 Flash)
│   │   ├── semantic_memory.py       # Semantic Memory v0.3
│   │   ├── gemini_embedding.py      # Gemini Embeddings (768 dims, L2 norm)
│   │   ├── rrf_reranker.py          # RRF Reranker (k=60)
│   │   └── pdf_processor.py         # PDF extraction for ingestion
│   ├── models/                      # Pydantic & SQLAlchemy models
│   ├── repositories/
│   │   ├── dense_search_repository.py   # pgvector similarity search
│   │   ├── sparse_search_repository.py  # Neo4j full-text search
│   │   ├── neo4j_knowledge_repository.py
│   │   ├── semantic_memory_repository.py
│   │   └── chat_history_repository.py
│   └── services/
│       ├── chat_service.py          # Main integration service
│       ├── hybrid_search_service.py # Dense + Sparse + RRF
│       └── ingestion_service.py     # PDF ingestion pipeline
├── alembic/                         # Database migrations
├── assets/                          # Static assets (images)
├── scripts/
│   ├── import_colregs.py            # Import COLREGs to Neo4j
│   ├── reingest_with_embeddings.py  # Re-ingest with pgvector embeddings
│   ├── verify_all_systems.py        # System health verification
│   ├── test_hybrid_search.py        # Test hybrid search
│   └── create_*.sql                 # Database setup scripts
├── tests/
│   ├── property/                    # Property-based tests (Hypothesis)
│   ├── unit/                        # Unit tests
│   └── integration/                 # Integration tests
├── docs/                            # Documentation
├── docker-compose.yml               # Local development stack
├── requirements.txt                 # Python dependencies
└── render.yaml                      # Render.com deployment
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Neo4j (local or Aura)
- PostgreSQL with pgvector (local or Neon)
- Google Gemini API Key

### 1. Clone & Setup

```bash
git clone <repository-url>
cd maritime-ai-service

python -m venv .venv
.venv\Scripts\activate  # Windows

pip install -r requirements.txt
```

### 2. Configure Environment

```bash
copy .env.example .env
```

Edit `.env`:
```env
# LLM Provider
LLM_PROVIDER=google
GOOGLE_API_KEY=your_gemini_api_key
GOOGLE_MODEL=gemini-2.5-flash

# Database (Neon Serverless Postgres)
DATABASE_URL=postgresql+asyncpg://user:pass@host/db?ssl=require

# Neo4j
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4j_secret

# Semantic Memory
SEMANTIC_MEMORY_ENABLED=true
```

### 3. Start Infrastructure

```bash
docker-compose up -d
```

### 4. Import Knowledge Base

```bash
python scripts/import_colregs.py
```

### 5. Run Server

```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Access API

- **Swagger UI**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

---

## API Reference

### POST /api/v1/chat

**Request:**
```json
{
  "user_id": "student_12345",
  "message": "Giải thích quy tắc 15 COLREGs",
  "role": "student",
  "session_id": "session_abc123"
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "answer": "Theo Điều 15 COLREGs...",
    "sources": [{"title": "COLREGs Rule 15", "content": "..."}],
    "suggested_questions": ["Tàu nào phải nhường đường?"]
  },
  "metadata": {
    "agent_type": "rag",
    "processing_time": 1.25
  }
}
```

### Authentication

```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "X-API-Key: your_lms_api_key" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user1", "message": "Hello", "role": "student"}'
```

---

## Knowledge Ingestion API (Admin Only)

API cho phép Admin upload tài liệu PDF vào Neo4j Knowledge Graph để hỗ trợ RAG queries.

### POST /api/v1/knowledge/ingest

Upload PDF document để xử lý và lưu vào Knowledge Graph.

**Request (multipart/form-data):**
```bash
curl -X POST http://localhost:8000/api/v1/knowledge/ingest \
  -F "file=@colregs.pdf" \
  -F "category=COLREGs" \
  -F "role=admin"
```

**Response:**
```json
{
  "status": "accepted",
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Document 'colregs.pdf' accepted for processing."
}
```

### GET /api/v1/knowledge/jobs/{job_id}

Kiểm tra trạng thái xử lý document.

**Response:**
```json
{
  "job_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "progress": 100,
  "nodes_created": 45,
  "error_message": null,
  "filename": "colregs.pdf",
  "category": "COLREGs"
}
```

### GET /api/v1/knowledge/list

Lấy danh sách documents đã upload.

**Response:**
```json
{
  "documents": [
    {
      "id": "doc_123",
      "filename": "colregs.pdf",
      "category": "COLREGs",
      "nodes_count": 45,
      "uploaded_by": "admin"
    }
  ],
  "page": 1,
  "limit": 20
}
```

### GET /api/v1/knowledge/stats

Lấy thống kê Knowledge Base.

**Response:**
```json
{
  "total_documents": 5,
  "total_nodes": 230,
  "categories": {
    "COLREGs": 120,
    "SOLAS": 80,
    "MARPOL": 30
  },
  "recent_uploads": [...]
}
```

### DELETE /api/v1/knowledge/{document_id}

Xóa document và tất cả Knowledge nodes liên quan (Admin only).

**Request:**
```bash
curl -X DELETE http://localhost:8000/api/v1/knowledge/doc_123 \
  -F "role=admin"
```

**Response:**
```json
{
  "status": "deleted",
  "document_id": "doc_123",
  "nodes_deleted": 45
}
```

---

## Chat History Management API

API cho phép quản lý lịch sử chat của người dùng.

### DELETE /api/v1/history/{user_id}

Xóa toàn bộ lịch sử chat của một user.

**Access Control:**
- `admin`: Có thể xóa lịch sử của bất kỳ user nào
- `student`/`teacher`: Chỉ có thể xóa lịch sử của chính mình

**Request:**
```bash
curl -X DELETE http://localhost:8000/api/v1/history/student_123 \
  -H "X-API-Key: your_api_key" \
  -H "Content-Type: application/json" \
  -d '{"role": "admin", "requesting_user_id": "admin_user"}'
```

**Response (Success):**
```json
{
  "status": "deleted",
  "user_id": "student_123",
  "messages_deleted": 15,
  "deleted_by": "admin_user"
}
```

**Response (Permission Denied - 403):**
```json
{
  "error": "permission_denied",
  "message": "Permission denied. Users can only delete their own chat history."
}
```

---

## Chat History Retrieval API (Phase 2)

API cho phép lấy lịch sử chat với phân trang, hỗ trợ đồng bộ đa thiết bị.

### GET /api/v1/history/{user_id}

Lấy lịch sử chat của một user với phân trang.

**Query Parameters:**
- `limit`: Số tin nhắn trả về (default: 20, max: 100)
- `offset`: Vị trí bắt đầu (default: 0)

**Request:**
```bash
curl -X GET "https://maritime-ai-chatbot.onrender.com/api/v1/history/student_123?limit=20&offset=0" \
  -H "X-API-Key: your_api_key"
```

**Response:**
```json
{
  "data": [
    {
      "role": "user",
      "content": "Quy tắc 5 là gì?",
      "timestamp": "2025-12-05T10:00:00Z"
    },
    {
      "role": "assistant",
      "content": "Quy tắc 5 COLREGs quy định về...",
      "timestamp": "2025-12-05T10:00:05Z"
    }
  ],
  "pagination": {
    "total": 150,
    "limit": 20,
    "offset": 0
  }
}
```

---

### Constraints

- **File Type**: Chỉ chấp nhận PDF (.pdf)
- **Max Size**: 50MB
- **Role**: Chỉ Admin mới có quyền ingest/delete
- **Duplicate Detection**: Tự động phát hiện file trùng lặp qua content hash

---

## Hybrid Search Details

### How It Works

1. **Query Processing**: User query được xử lý song song bởi 2 search engines
2. **Dense Search (Semantic)**: 
   - Gemini embedding (768 dims, L2 normalized)
   - pgvector cosine similarity search
   - Trả về top-K results với similarity scores (0-1)
3. **Sparse Search (Keyword)**:
   - Neo4j Full-text index với BM25-like scoring
   - Exact keyword matching
   - Trả về top-K results với relevance scores
4. **RRF Reranking**:
   - Reciprocal Rank Fusion với k=60
   - Formula: `RRF(d) = Σ 1/(k + rank(d))`
   - Documents xuất hiện ở cả 2 nguồn được boost
5. **Result Merging**: Top results được merge và trả về

### Example Output

```
Query: 'restricted visibility navigation'
Results: 3, Method: hybrid

1. COLREGs Rule 19 - Conduct in Restricted Visibility
   RRF: 0.0164, Dense: 0.75, Sparse: 14.63  ← Appears in BOTH (boosted)

2. COLREGs Rule 6 - Safe Speed
   RRF: 0.0161, Dense: 0.66, Sparse: 4.43   ← Appears in BOTH (boosted)

3. [Semantic Match Only]
   RRF: 0.0079, Dense: 0.65, Sparse: None   ← Dense only (no boost)
```

### Graceful Degradation

- Nếu Dense Search không khả dụng → Fallback về Sparse-only
- Nếu Sparse Search không khả dụng → Fallback về Dense-only
- Nếu cả 2 không khả dụng → Return empty results với error message

---

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run property-based tests
pytest tests/property/ -v
```

---

## Deployment

### Render.com (Production)

```bash
# Deploy via render.yaml
# Environment variables set in Render Dashboard
```

### Docker

```bash
docker build -t maritime-ai-service:latest .
docker run -d -p 8000:8000 maritime-ai-service:latest
```

---

## Tech Stack

| Category | Technology |
|----------|------------|
| **Framework** | FastAPI 0.109 |
| **AI/LLM** | LangChain 1.1.x + LangGraph 1.0.x |
| **Agent Pattern** | Manual ReAct (bind_tools + loop) |
| **LLM Provider** | Google Gemini 2.5 Flash |
| **Embeddings** | Gemini text-embedding-004 (768 dims) |
| **Graph Database** | Neo4j 5.28 + Full-text Search |
| **Vector Database** | PostgreSQL + pgvector (Neon) |
| **Search** | Hybrid Search (Dense + Sparse + RRF) |
| **Memory** | Semantic Memory v0.3 |
| **Testing** | Pytest + Hypothesis |

---

## Database Connection Pooling (v0.8.0 - Neon Migration)

Migrated from Supabase to Neon Serverless Postgres (CHỈ THỊ KỸ THUẬT SỐ 19).

### Why Neon?

- **No MaxClients Error**: Neon Pooled Connection handles connections better
- **Serverless**: Auto-scales, sleeps when idle (saves compute hours)
- **Free Tier**: 100 compute hours/month (vs Supabase connection limits)

### Shared Engine Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    SHARED DATABASE ENGINE                    │
│                    (app/core/database.py)                   │
│                                                              │
│   pool_size=5, max_overflow=5, pool_timeout=30s             │
│   Total Max Connections: 10 (Neon allows more)              │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
┌───────────────┐    ┌───────────────┐    ┌───────────────┐
│ ChatHistory   │    │ SemanticMemory│    │ LearningProfile│
│ Repository    │    │ Repository    │    │ Repository    │
└───────────────┘    └───────────────┘    └───────────────┘

┌─────────────────────────────────────────────────────────────┐
│              DENSE SEARCH (asyncpg)                          │
│              min_size=1, max_size=2                          │
│              Total: 2 connections                            │
└─────────────────────────────────────────────────────────────┘

TOTAL CONNECTIONS: 12 (increased from 4, Neon handles it)
```

### Connection Settings

| Component | pool_size | max_overflow | Total |
|-----------|-----------|--------------|-------|
| Shared SQLAlchemy Engine | 5 | 5 | 10 |
| DenseSearchRepository (asyncpg) | 1 | 1 | 2 |
| **TOTAL** | | | **12** |

### Health Check Strategy (Protect Neon Free Tier)

| Endpoint | Purpose | DB Access |
|----------|---------|-----------|
| `GET /api/v1/health` | Cronjob/Render ping | ❌ No (shallow) |
| `GET /api/v1/health/db` | Admin debug | ✅ Yes (deep) |

**Important**: Configure UptimeRobot/Cron-job to ping `/api/v1/health` (NOT `/api/v1/health/db`) to avoid waking up Neon unnecessarily.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v0.8.4 | 2025-12-07 | **MANAGED MEMORY LIST**: CHỈ THỊ SỐ 23 - Memory Capping (50 facts/user), True Deduplication (Upsert), Memory API `GET /api/v1/memories/{user_id}`, Fact Type Validation (6 types only) |
| v0.8.3 | 2025-12-07 | **DEEP REASONING**: CHỈ THỊ SỐ 21 & 22 - `<thinking>` tags for reasoning, Proactive Continuation (AI hỏi user muốn nghe tiếp), Memory Isolation (blocked content không vào context), Context Window 50 messages, ConversationAnalyzer |
| v0.8.2 | 2025-12-07 | **MEMORY ISOLATION**: CHỈ THỊ SỐ 22 - Blocked content filtering from context window, `is_blocked` column in chat_history |
| v0.8.1 | 2025-12-07 | **GUARDIAN AGENT**: LLM-based Content Moderation (Gemini 2.5 Flash), Custom Pronoun Validation ("gọi tôi là công chúa"), Contextual Content Filtering, Caching & Fallback |
| v0.8.0 | 2025-12-07 | **NEON MIGRATION**: CHỈ THỊ SỐ 19 - Migrate from Supabase to Neon Serverless Postgres, Optimized Health Check (shallow/deep), Code cleanup |
| v0.7.5 | 2025-12-07 | **AI QUALITY**: Fix "À," repetition pattern, SessionState tracking, Explicit anti-repetition instructions |
| v0.7.4 | 2025-12-05 | **PERSONA SYSTEM**: Dynamic YAML Persona - Full support for tutor.yaml/assistant.yaml structure, Template variable `{{user_name}}` replacement from Memory |
| v0.7.3 | 2025-12-05 | **WIRING**: CHỈ THỊ SỐ 17 - Tích hợp PromptLoader & MemorySummarizer vào ChatService |
| v0.7.2 | 2025-12-05 | **HUMANIZATION**: CHỈ THỊ SỐ 16 - YAML Persona Config, Memory Summarizer, Natural conversation style |
| v0.7.1 | 2025-12-05 | **CRITICAL FIX**: google-genai SDK - Fix Semantic Memory embedding failure (No module named 'google.genai') |
| v0.7.0 | 2025-12-05 | **MAJOR UPGRADE**: LangChain 1.1.x + LangGraph 1.0.x - Manual ReAct pattern với bind_tools(), loại bỏ deprecated create_react_agent |
| v0.6.3 | 2025-12-05 | **CRITICAL FIX**: Shared Database Engine - Fix MaxClientsInSessionMode error (now resolved with Neon) |
| v0.6.2 | 2025-12-05 | GET /api/v1/history/{user_id} - Paginated history retrieval for multi-device sync (Phase 2) |
| v0.6.1 | 2025-12-04 | Chat History Management API - DELETE /api/v1/history/{user_id} with role-based access control |
| v0.6.0 | 2025-12-04 | Tech Debt Cleanup - pypdf migration (from PyPDF2), Knowledge API error handling, Pydantic v2 compliance, circular import fix |
| v0.5.3 | 2025-12-04 | Intent Classifier HOTFIX - 70 Vietnamese keywords, Aggressive Routing, 100% classification accuracy |
| v0.5.2 | 2025-12-04 | Title Match Boosting v2 - Strong Boost x3.0 cho số hiệu, Top-1 Citation Accuracy 100% |
| v0.5.1 | 2025-12-04 | Project cleanup, removed redundant test scripts, security fix (.env.production.example) |
| v0.5.0 | 2025-12-04 | Hybrid Search v0.5 - Dense (pgvector) + Sparse (Neo4j FTS) + RRF Reranking (k=60) |
| v0.4.0 | 2025-12-03 | Knowledge Ingestion API - Admin PDF upload to Neo4j |
| v0.3.0 | 2025-12-02 | Semantic Memory v0.3, Cross-session persistence with pgvector |
| v0.2.1 | 2025-12-01 | Memory Lite, Chat History, Learning Profile |
| v0.2.0 | 2025-11-30 | Role-based prompting, Multi-agent architecture |
| v0.1.0 | 2025-11-28 | Initial release with RAG |

---

## Van de da biet va Cong viec tuong lai

### Da giai quyet (v0.8.3 - Deep Reasoning)
- **Thinking Tags**: AI su dung `<thinking>` tags de suy nghi truoc khi tra loi
- **Proactive Continuation**: AI hoi user "Ban co muon nghe tiep khong?" khi bi ngat
- **Memory Isolation**: Blocked content khong duoc dua vao context window
- **Context Window 50**: Tang tu 10 len 50 messages, configurable qua CONTEXT_WINDOW_SIZE
- **ConversationAnalyzer**: Phat hien giai thich chua hoan thanh va co hoi tiep tuc

### Da giai quyet (v0.8.2 - Memory Isolation)
- **Blocked Content Filtering**: Tin nhan bi block khong xuat hien trong context
- **Database Schema**: Them `is_blocked` va `block_reason` columns vao chat_history
- **Privacy Protection**: Noi dung doc hai khong anh huong den AI responses

### Da giai quyet (v0.8.1 - Guardian Agent)
- **LLM Content Moderation**: Thay the hardcoded patterns bang Gemini 2.5 Flash
- **Custom Pronoun Validation**: Ho tro "goi toi la cong chua", "goi toi la thuyen truong"
- **Contextual Filtering**: "cuop bien" trong ngu canh hang hai duoc ALLOW, "may/tao" bi BLOCK
- **Performance Optimization**: Skip LLM cho greetings, Cache decisions (1h TTL)
- **Fallback Mechanism**: Tu dong dung rule-based Guardrails khi LLM khong kha dung

### Da giai quyet (v0.5.2a)
- **Agent Routing**: Cau hoi tieng Viet da duoc dinh tuyen dung den RAG Agent
- **Do chinh xac trich dan**: Do chinh xac Top-1 tang tu 20% len 100%

### Da giai quyet (v0.7.4)
- **Dynamic YAML Persona**: PromptLoader ho tro day du cau truc YAML moi (profile, style, thought_process, directives)
- **Template Variable**: `{{user_name}}` duoc thay the bang ten that tu Memory
- **Role-Based Persona**: Student dung tutor.yaml (Captain AI), Teacher/Admin dung assistant.yaml (Maritime Pro Assistant)
- **Tools Instruction**: Tu dong them huong dan su dung tools vao system prompt
- **Addressing Rules**: Ho tro quy tac xung ho cho Teacher/Admin (Thay/Co, Anh/Chi)

### Da giai quyet (v0.7.3)
- **Wiring & Activation**: Tich hop PromptLoader va MemorySummarizer vao ChatService
- **Background Memory Summarization**: Nen ky uc chay ngam sau khi tra loi user
- **Production Ready**: Tat ca module Humanization da duoc kich hoat

### Da giai quyet (v0.7.2)
- **YAML Persona Config**: Tach biet persona ra file YAML (tutor.yaml, assistant.yaml)
- **Memory Summarizer**: Nen ky uc theo dot (Tiered Memory Architecture)
- **Natural Conversation**: Cai thien System Prompt - AI tu nhien hon, it may moc
- **Empathy First**: AI chia se cam xuc truoc khi tra loi (user than met/doi)

### Da giai quyet (v0.7.1)
- **google-genai SDK Missing**: Them `google-genai>=0.3.0` vao requirements.txt
- **Semantic Memory Embedding**: Fix loi "No module named 'google.genai'" khien bot khong nho ten user
- **httpx Version**: Cap nhat httpx>=0.28.1 (yeu cau boi google-genai)
- **Sources Missing in API Response**: Fix loi mat nguon trich dan khi dung Unified Agent

### Da giai quyet (v0.7.0)
- **LangChain/LangGraph Upgrade**: Nang cap tu 0.1.x len 1.1.x (LangChain) va 1.0.x (LangGraph)
- **Manual ReAct Pattern**: Su dung `model.bind_tools()` + manual loop thay vi deprecated `create_react_agent`
- **SystemMessage Support**: Them SystemMessage cho system prompt trong ReAct loop
- **Gemini Response Handling**: Cai thien xu ly response format cua Gemini (list vs string)

### Da giai quyet (v0.8.0 - Neon Migration)
- **MaxClientsInSessionMode**: KHAC PHUC VINH VIEN - Chuyen tu Supabase sang Neon Serverless Postgres
- **Health Check Optimization**: Shallow check (no DB) cho Cronjob, Deep check cho Admin
- **Code Cleanup**: Xoa tat ca references den Supabase trong Python code
- **Connection Pool**: Tang pool_size tu 2 len 5 (Neon cho phep nhieu hon)

### Da giai quyet (v0.7.5 - AI Quality)
- **"À," Repetition Pattern**: AI khong con lap lai "À," o dau cau
- **SessionState Tracking**: Cache tren RAM de theo doi patterns da dung
- **Explicit Anti-Repetition**: Them chi dan cu the vao system prompt

### Da giai quyet (v0.6.3)
- **MaxClientsInSessionMode**: Da khac phuc tam thoi (nay da chuyen sang Neon v0.8.0)
- **Shared Database Engine**: Tat ca repositories su dung singleton engine pattern
- **Toi uu Connection Pool**: Giam tu 11 ket noi xuong 4 ket noi

### Da giai quyet (v0.6.0)
- **Migration thu vien PDF**: Chuyen tu PyPDF2 sang pypdf de ho tro tieng Viet tot hon
- **Knowledge API Endpoints**: `/stats` va `/list` tra ve ket qua rong thay vi loi 500
- **Tuan thu Pydantic v2**: Config su dung pattern `model_config = SettingsConfigDict()`
- **Sua loi Circular Import**: Khac phuc circular import giua rag_tool.py va chat_service.py

### Dang thuc hien
- **Vietnamese Text Chunking**: Phat hien ranh gioi cau cho PDF tieng Viet

### Du kien
- Kiem tra bo nho cross-session
- Phan tich learning profile
- Ho tro da ngon ngu (EN/VN)

---

## Giay phep

Phan mem doc quyen duoc phat trien cho Maritime Education LMS.

---

## Dong gop

Du an nay duoc phat trien boi HoLiLiHu AI LMS tu Nhom Lab VMU. De dong gop:

1. Fork repository
2. Tao feature branch
3. Thuc hien thay doi
4. Them tests
5. Gui pull request

---

*Duoc xay dung boi HoLiLiHu AI LMS - Nhom Lab VMU*
