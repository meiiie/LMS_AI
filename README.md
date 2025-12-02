# Maritime AI Tutor Service

<div align="center">

![Maritime AI Tutor Banner](assets/banner_AI_LMS.jpeg)

[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangChain](https://img.shields.io/badge/LangChain-0.1.9-1c3c3c?style=flat-square&logo=chainlink&logoColor=white)](https://langchain.com)
[![Neo4j](https://img.shields.io/badge/Neo4j-5.17-008cc1?style=flat-square&logo=neo4j&logoColor=white)](https://neo4j.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![License](https://img.shields.io/badge/License-Proprietary-red?style=flat-square)](LICENSE)

**AI-Powered Maritime Education Platform with Agentic RAG & Long-term Memory**

*Intelligent tutoring system for maritime professionals, featuring GraphRAG knowledge retrieval, role-based personalization, and adaptive learning.*

[Features](#features) • [Architecture](#architecture) • [Quick Start](#quick-start) • [API Reference](#api-reference) • [Deployment](#deployment)

</div>

---

## Overview

Maritime AI Tutor Service là một microservice AI thông minh được thiết kế để tích hợp với hệ thống LMS (Learning Management System) hàng hải. Hệ thống cung cấp khả năng:

- **Intelligent Tutoring**: AI Tutor với role-based prompting (Student/Teacher/Admin)
- **GraphRAG Knowledge Retrieval**: Truy vấn kiến thức từ SOLAS, COLREGs, MARPOL
- **Long-term Memory**: Ghi nhớ ngữ cảnh hội thoại và cá nhân hóa học tập
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

### Memory & Personalization

- **Sliding Window Context**: Last 10 messages for context
- **Learning Profile**: Tracks weak_areas, strong_areas, learning_style
- **Session Management**: Persistent chat history with Supabase/PostgreSQL

---

## Architecture

### System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LMS FRONTEND                                    │
│                    (Angular/React - Port 4200/3000)                         │
└─────────────────────────────────┬───────────────────────────────────────────┘
                                  │ HTTP/REST
                                  ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         MARITIME AI SERVICE                                  │
│                        (FastAPI - Port 8000)                                │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                          API Layer (v1)                                │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │  │
│  │  │ POST /chat  │  │ GET /health │  │ Rate Limit  │  │ Auth (API   │   │  │
│  │  │             │  │             │  │ (30/min)    │  │ Key/JWT)    │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘   │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        Service Layer                                   │  │
│  │  ┌─────────────────────────────────────────────────────────────────┐  │  │
│  │  │                      ChatService                                 │  │  │
│  │  │  • Input Validation (Guardrails)                                │  │  │
│  │  │  • Session Management (Memory Lite)                             │  │  │
│  │  │  • Intent Classification                                        │  │  │
│  │  │  • Agent Routing                                                │  │  │
│  │  │  • Output Validation                                            │  │  │
│  │  └─────────────────────────────────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                        Engine Layer (LangGraph)                       │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐   │  │
│  │  │ Orchestrator│  │ Chat Agent  │  │ RAG Agent   │  │ Tutor Agent │   │  │
│  │  │ (Intent     │  │ (General    │  │ (Knowledge  │  │ (Teaching   │   │  │
│  │  │ Classifier) │  │ Conversation│  │ Retrieval)  │  │ Sessions)   │   │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘  └─────────────┘   │  │
│  │  ┌─────────────┐  ┌─────────────┐                                     │  │
│  │  │ Guardrails  │  │ Memory      │                                     │  │
│  │  │ (PII/Inject)│  │ Engine      │                                     │  │
│  │  └─────────────┘  └─────────────┘                                     │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
│                                    │                                         │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                      Repository Layer                                  │  │
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐        │  │
│  │  │ ChatHistory     │  │ LearningProfile │  │ KnowledgeGraph  │        │  │
│  │  │ Repository      │  │ Repository      │  │ Repository      │        │  │
│  │  └─────────────────┘  └─────────────────┘  └─────────────────┘        │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │                         │                         │
          ▼                         ▼                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   PostgreSQL    │     │     Neo4j       │     │  Google Gemini  │
│   (Supabase)    │     │  Knowledge      │     │  / OpenAI       │
│                 │     │  Graph          │     │                 │
│ • chat_history  │     │                 │     │ • gemini-2.5    │
│ • learning_     │     │ • SOLAS         │     │ • gpt-4o-mini   │
│   profile       │     │ • COLREGs       │     │                 │
│ • chat_sessions │     │ • MARPOL        │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
    Port: 5432              Port: 7687              External API
```

### Data Flow

```
┌──────────┐    ┌───────────┐    ┌────────────┐    ┌───────────┐    ┌──────────┐
│   LMS    │───▶│ Guardrails│───▶│ Orchestrator│───▶│   Agent   │───▶│ Response │
│ Request  │    │ (Input)   │    │ (Intent)   │    │ (Process) │    │ (Output) │
└──────────┘    └───────────┘    └────────────┘    └───────────┘    └──────────┘
                     │                 │                 │
                     ▼                 ▼                 ▼
              ┌───────────┐    ┌────────────┐    ┌───────────┐
              │ PII Mask  │    │ GENERAL    │    │ Chat Agent│
              │ Injection │    │ KNOWLEDGE  │    │ RAG Agent │
              │ Detection │    │ TEACHING   │    │ Tutor     │
              └───────────┘    └────────────┘    └───────────┘
```

---

## Project Structure

```
maritime-ai-service/
├── app/
│   ├── api/
│   │   ├── v1/
│   │   │   ├── chat.py              # POST /api/v1/chat endpoint
│   │   │   ├── health.py            # Health check endpoints
│   │   │   └── __init__.py          # Router aggregation
│   │   └── deps.py                  # Dependencies (Auth, Rate Limit)
│   │
│   ├── core/
│   │   ├── config.py                # Pydantic Settings (env vars)
│   │   ├── rate_limit.py            # SlowAPI rate limiting
│   │   └── security.py              # JWT/API Key authentication
│   │
│   ├── engine/
│   │   ├── agents/
│   │   │   └── chat_agent.py        # Chat Agent with Memory
│   │   ├── tools/
│   │   │   ├── rag_tool.py          # RAG Agent with Neo4j
│   │   │   └── tutor_agent.py       # Tutor Agent with Assessment
│   │   ├── graph.py                 # LangGraph Orchestrator
│   │   ├── guardrails.py            # Input/Output validation
│   │   └── memory.py                # Memori Engine
│   │
│   ├── models/
│   │   ├── database.py              # SQLAlchemy ORM models
│   │   ├── knowledge_graph.py       # Knowledge Graph domain models
│   │   ├── learning_profile.py      # Learning Profile models
│   │   ├── memory.py                # Memory domain models
│   │   └── schemas.py               # Pydantic API schemas
│   │
│   ├── repositories/
│   │   ├── chat_history_repository.py    # Chat history CRUD
│   │   ├── knowledge_graph_repository.py # In-memory KG (fallback)
│   │   ├── learning_profile_repository.py # Learning profile CRUD
│   │   └── neo4j_knowledge_repository.py  # Neo4j KG implementation
│   │
│   ├── services/
│   │   └── chat_service.py          # Main integration service
│   │
│   └── main.py                      # FastAPI application factory
│
├── alembic/                         # Database migrations
├── assets/                          # Static assets (images, etc.)
├── scripts/
│   └── create_memory_tables.sql     # Supabase schema script
├── tests/
│   ├── property/                    # Property-based tests (Hypothesis)
│   ├── unit/                        # Unit tests
│   └── integration/                 # Integration tests
│
├── docker-compose.yml               # Local development stack
├── requirements.txt                 # Python dependencies
├── pyproject.toml                   # Project configuration
└── render.yaml                      # Render.com deployment config
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Neo4j (local or Aura)
- PostgreSQL (local or Supabase)
- Google Gemini API Key (or OpenAI)

### 1. Clone & Setup Environment

```bash
# Clone repository
git clone <repository-url>
cd maritime-ai-service

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

```bash
# Copy example env file
copy .env.example .env
```

Edit `.env` with your credentials:

```env
# Application
APP_NAME=Maritime AI Tutor
ENVIRONMENT=development
DEBUG=true

# LLM Provider (Primary: Google Gemini)
LLM_PROVIDER=google
GOOGLE_API_KEY=your_gemini_api_key
GOOGLE_MODEL=gemini-2.5-flash

# Database - Local Docker
POSTGRES_HOST=localhost
POSTGRES_PORT=5433
POSTGRES_USER=maritime
POSTGRES_PASSWORD=maritime_secret
POSTGRES_DB=maritime_ai

# OR Database - Supabase (Production)
# DATABASE_URL=postgresql://user:pass@host:5432/db

# Neo4j - Local Docker
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=neo4j_secret

# OR Neo4j Aura (Production)
# NEO4J_URI=neo4j+s://xxxxx.databases.neo4j.io
# NEO4J_USERNAME=neo4j
# NEO4J_PASSWORD=your_aura_password

# Security
LMS_API_KEY=your_lms_api_key
```

### 3. Start Infrastructure (Docker)

```bash
# Start PostgreSQL, Neo4j, ChromaDB
docker-compose up -d

# Verify services
docker-compose ps
```

### 4. Run Database Migrations

```bash
# Apply Alembic migrations
alembic upgrade head

# OR run SQL script for Supabase
# Execute scripts/create_memory_tables.sql in Supabase SQL Editor
```

### 5. Import Knowledge Base (Optional)

```bash
# Import COLREGs to Neo4j
python import_colregs.py
```

### 6. Start Development Server

```bash
# Run FastAPI with hot reload
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 7. Access API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **Health Check**: http://localhost:8000/health

---

## API Reference

### Main Endpoint: POST /api/v1/chat

**Request:**
```json
{
  "user_id": "student_12345",
  "message": "Giải thích quy tắc 15 COLREGs về tình huống cắt hướng",
  "role": "student",
  "session_id": "session_abc123",
  "context": {
    "course_id": "COLREGs_101"
  }
}
```

**Response:**
```json
{
  "status": "success",
  "data": {
    "answer": "Theo Điều 15 COLREGs, khi hai tàu máy đi cắt hướng nhau...",
    "sources": [
      {
        "title": "COLREGs Rule 15 - Crossing Situation",
        "content": "When two power-driven vessels are crossing..."
      }
    ],
    "suggested_questions": [
      "Tàu nào phải nhường đường trong tình huống cắt hướng?",
      "Quy tắc 16 về hành động của tàu nhường đường là gì?",
      "Khi nào áp dụng quy tắc cắt hướng?"
    ]
  },
  "metadata": {
    "processing_time": 1.25,
    "model": "maritime-rag-v1",
    "agent_type": "rag"
  }
}
```

### Authentication

```bash
# Using API Key (recommended for LMS)
curl -X POST http://localhost:8000/api/v1/chat \
  -H "X-API-Key: your_lms_api_key" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user1", "message": "Hello", "role": "student"}'

# Using JWT Token
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Authorization: Bearer your_jwt_token" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user1", "message": "Hello", "role": "student"}'
```

### Health Check

```bash
# Simple health check
curl http://localhost:8000/health
# Response: {"status": "ok", "database": "connected"}

# Detailed health check
curl http://localhost:8000/api/v1/health
# Response: {"status": "healthy", "components": {...}}
```

---

## Testing

### Run All Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run property-based tests only
pytest tests/property/ -v

# Run specific test file
pytest tests/property/test_guardrails_properties.py -v
```

### Property-Based Tests (Hypothesis)

The project uses **Hypothesis** for property-based testing:

```python
# Example: Guardrails validation
@given(st.text(min_size=1, max_size=1000))
def test_validate_input_always_returns_result(message):
    """For any message, validation always returns a ValidationResult."""
    result = guardrails.validate_input(message)
    assert isinstance(result, ValidationResult)
```

---

## Deployment

### Render.com (Recommended)

```yaml
# render.yaml
services:
  - type: web
    name: maritime-ai-service
    env: python
    buildCommand: pip install -r requirements.txt
    startCommand: gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
    envVars:
      - key: ENVIRONMENT
        value: production
      - key: GOOGLE_API_KEY
        sync: false
      - key: DATABASE_URL
        fromDatabase:
          name: maritime-db
          property: connectionString
```

### Docker Production

```bash
# Build image
docker build -t maritime-ai-service:latest .

# Run container
docker run -d \
  --name maritime-ai \
  -p 8000:8000 \
  -e ENVIRONMENT=production \
  -e GOOGLE_API_KEY=your_key \
  -e DATABASE_URL=your_db_url \
  maritime-ai-service:latest
```

---

## Configuration Reference

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_NAME` | Application name | Maritime AI Tutor |
| `ENVIRONMENT` | development/staging/production | development |
| `DEBUG` | Enable debug mode | false |
| `LLM_PROVIDER` | google/openai/openrouter | google |
| `GOOGLE_API_KEY` | Google Gemini API key | - |
| `GOOGLE_MODEL` | Gemini model name | gemini-2.5-flash |
| `OPENAI_API_KEY` | OpenAI API key (fallback) | - |
| `DATABASE_URL` | PostgreSQL connection URL | - |
| `NEO4J_URI` | Neo4j connection URI | bolt://localhost:7687 |
| `LMS_API_KEY` | API key for LMS authentication | - |
| `RATE_LIMIT_REQUESTS` | Max requests per window | 100 |
| `RATE_LIMIT_WINDOW_SECONDS` | Rate limit window | 60 |

---

## Tech Stack

| Category | Technology | Version |
|----------|------------|---------|
| **Framework** | FastAPI | 0.109.2 |
| **AI/LLM** | LangChain | 0.1.9 |
| **Orchestration** | LangGraph | 0.0.24 |
| **LLM Provider** | Google Gemini | gemini-2.5-flash |
| **Graph Database** | Neo4j | 5.17 |
| **SQL Database** | PostgreSQL | 15 |
| **ORM** | SQLAlchemy | 2.0.27 |
| **Validation** | Pydantic | 2.6.1 |
| **Testing** | Pytest + Hypothesis | 7.4.4 / 6.92.0 |
| **Rate Limiting** | SlowAPI | 0.1.9 |

---

## License

This project is proprietary software developed for Maritime LMS integration.

---

## Team

- **AI Backend Team** - Core development
- **LMS Team** - Integration & Frontend

---

<div align="center">

**Built for Maritime Education**

*Empowering maritime professionals with AI-driven learning*

[![Made with FastAPI](https://img.shields.io/badge/Made%20with-FastAPI-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Powered by LangChain](https://img.shields.io/badge/Powered%20by-LangChain-1c3c3c?style=flat-square)](https://langchain.com)

</div>
