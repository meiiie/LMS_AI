# Maritime AI Tutor Service

<div align="center">

![Maritime AI Tutor Banner](assets/banner_AI_LMS.jpeg)

[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangChain](https://img.shields.io/badge/LangChain-0.1.9-1c3c3c?style=flat-square&logo=chainlink&logoColor=white)](https://langchain.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.0.24-purple?style=flat-square)](https://langchain.com)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.17-008cc1?style=flat-square&logo=neo4j&logoColor=white)](https://neo4j.com)
[![Supabase](https://img.shields.io/badge/Supabase-pgvector-3ECF8E?style=flat-square&logo=supabase&logoColor=white)](https://supabase.com)
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
- **GraphRAG Knowledge Retrieval**: Truy vấn kiến thức từ SOLAS, COLREGs, MARPOL
- **Semantic Memory v0.3**: Ghi nhớ ngữ cảnh cross-session với pgvector + Gemini embeddings
- **Content Guardrails**: Bảo vệ nội dung với PII masking và prompt injection detection

---

## Features

### Multi-Agent Architecture

| Agent | Function | Trigger Keywords |
|-------|----------|------------------|
| **Chat Agent** | General maritime conversation | General conversation |
| **RAG Agent** | Knowledge Graph queries | `solas`, `colregs`, `marpol`, `rule`, `regulation` |
| **Tutor Agent** | Structured teaching with assessment | `teach`, `learn`, `quiz`, `explain` |

### Role-Based Prompting

```
┌─────────────────────────────────────────────────────────────┐
│  Student Role → AI acts as TUTOR                            │
│  • Tone: Encouraging, supportive, patient                   │
│  • Explains technical terms in detail                       │
│  • Ends with follow-up questions                            │
├─────────────────────────────────────────────────────────────┤
│  Teacher/Admin Role → AI acts as ASSISTANT                  │
│  • Tone: Professional, concise, accurate                    │
│  • Cites exact regulations and codes                        │
│  • No basic term explanations                               │
└─────────────────────────────────────────────────────────────┘
```

### Semantic Memory v0.3 (Cross-Session)

- **pgvector + Gemini Embeddings**: Vector similarity search (768 dimensions)
- **User Facts Extraction**: Tự động trích xuất thông tin người dùng (tên, sở thích, mục tiêu)
- **Cross-Session Persistence**: Ghi nhớ ngữ cảnh qua nhiều phiên chat
- **Deduplication**: Tự động loại bỏ facts trùng lặp, giữ bản mới nhất

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
│  │  ChatService: Guardrails → Intent → Agent Routing → Response          │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        Engine Layer (LangGraph)                       │  │
│  │  Orchestrator │ Chat Agent │ RAG Agent │ Tutor Agent │ Semantic Memory │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      Repository Layer                                  │  │
│  │  ChatHistory │ SemanticMemory │ LearningProfile │ KnowledgeGraph       │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │                         │                         │
          ▼                         ▼                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   PostgreSQL    │     │     Neo4j       │     │  Google Gemini  │
│   (Supabase)    │     │  Knowledge      │     │  2.5 Flash      │
│   + pgvector    │     │  Graph          │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

---

## Project Structure

```
maritime-ai-service/
├── app/
│   ├── api/v1/                      # API endpoints (chat, health)
│   ├── core/                        # Config, security, rate_limit
│   ├── engine/
│   │   ├── agents/chat_agent.py     # Chat Agent
│   │   ├── tools/rag_tool.py        # RAG Agent with Neo4j
│   │   ├── tools/tutor_agent.py     # Tutor Agent
│   │   ├── graph.py                 # LangGraph Orchestrator
│   │   ├── guardrails.py            # Input/Output validation
│   │   ├── semantic_memory.py       # Semantic Memory v0.3
│   │   └── gemini_embedding.py      # Gemini Embeddings
│   ├── models/                      # Pydantic & SQLAlchemy models
│   ├── repositories/                # Data access layer
│   └── services/chat_service.py     # Main integration service
├── alembic/                         # Database migrations
├── assets/                          # Static assets (images)
├── scripts/
│   ├── import_colregs.py            # Import COLREGs to Neo4j
│   ├── create_semantic_memory_tables.sql
│   └── test_*.py                    # Manual test scripts
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
- PostgreSQL with pgvector (local or Supabase)
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

# Database (Supabase)
DATABASE_URL=postgresql://user:pass@host:5432/db

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
| **AI/LLM** | LangChain + LangGraph |
| **LLM Provider** | Google Gemini 2.5 Flash |
| **Graph Database** | Neo4j 5.17 |
| **SQL Database** | PostgreSQL + pgvector |
| **Memory** | Semantic Memory v0.3 |
| **Testing** | Pytest + Hypothesis |

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| v0.3.0 | 2024-12-03 | Semantic Memory v0.3, Cross-session persistence, Code cleanup |
| v0.2.1 | 2024-12-02 | Memory Lite, Chat History, Learning Profile |
| v0.2.0 | 2024-12-01 | Role-based prompting, Multi-agent architecture |
| v0.1.0 | 2024-11-28 | Initial release with RAG |

---

## License

Proprietary software for Maritime LMS integration.

---

<div align="center">

**Built for Maritime Education**

[![Made with FastAPI](https://img.shields.io/badge/Made%20with-FastAPI-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Powered by LangChain](https://img.shields.io/badge/Powered%20by-LangChain-1c3c3c?style=flat-square)](https://langchain.com)

</div>
