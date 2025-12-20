# Maritime AI Tutor Service

<div align="center">

![Maritime AI Tutor Banner](assets/banner_AI_LMS.jpeg)

[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2-purple?style=flat-square)](https://langchain.com)
[![Gemini](https://img.shields.io/badge/Gemini-3.0_Flash-4285F4?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev)
[![Neon](https://img.shields.io/badge/Neon-pgvector-00E599?style=flat-square&logo=postgresql&logoColor=white)](https://neon.tech)

**AI-Powered Maritime Education Platform with Agentic RAG & LMS Integration**

[Quick Start](#-quick-start) • [API Reference](#-api-reference) • [Architecture](docs/architecture/SYSTEM_FLOW.md) • [Changelog](CHANGELOG.md)

</div>

---

## 🚀 Quick Start

```bash
# Clone & install
git clone <repo-url>
cd maritime-ai-service
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys (GOOGLE_API_KEY, DATABASE_URL, etc.)

# Run
uvicorn app.main:app --reload
```

**API Base:** `http://localhost:8000/api/v1`

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| **Agentic RAG** | Self-correcting RAG with grading & verification |
| **Multi-Agent System** | Supervisor + RAG/Tutor/Memory/Grader agents |
| **Semantic Cache** | 2hr TTL, ~45s response for cache hits |
| **Phase 2.4a SOTA** | Early exit grading saves 19s per query |
| **Hybrid Search** | Dense (pgvector) + Sparse (tsvector) + RRF |
| **Memory System** | Cross-session facts, insights, learning patterns |
| **Streaming API** | Server-Sent Events for real-time UX |
| **Multimodal RAG** | Vision-based PDF understanding |

---

## 📁 Project Structure

```
maritime-ai-service/
├── app/
│   ├── api/v1/          # REST endpoints (chat, admin, health)
│   ├── cache/           # Semantic cache system
│   ├── core/            # Config, database, security
│   ├── engine/          # AI logic (agents, RAG, memory)
│   ├── models/          # Pydantic schemas
│   ├── prompts/         # YAML prompt configs
│   ├── repositories/    # Data access layer
│   └── services/        # Business logic orchestration
├── docs/architecture/   # System diagrams & flows
├── scripts/             # Utility & test scripts
└── tests/               # Test suites
```

> 📚 See [FOLDER_MAP.md](docs/architecture/FOLDER_MAP.md) for detailed file mapping

---

## 🔌 API Reference

### Chat Endpoint

```http
POST /api/v1/chat
Content-Type: application/json
X-API-Key: {api_key}

{
  "message": "Giải thích Điều 15 COLREGs",
  "user_id": "student-123",
  "role": "student"
}
```

### Response

```json
{
  "data": {
    "answer": "Điều 15 quy định về tình huống cắt hướng...",
    "sources": [
      {
        "title": "Rule 15 - Crossing Situation",
        "page_number": 15,
        "bounding_boxes": [{"x0": 10, "y0": 45, "x1": 90, "y1": 52}]
      }
    ],
    "reasoning_trace": {
      "steps": ["routing", "retrieval", "grading", "generation"]
    }
  }
}
```

### Other Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/chat` | POST | Main chat |
| `/api/v1/chat-stream` | POST | SSE streaming |
| `/api/v1/admin/documents` | POST/GET | Document management |
| `/api/v1/health` | GET | Service health |
| `/api/v1/sources/{id}` | GET | Source details |

---

## 🏗️ Architecture

See [docs/architecture/SYSTEM_FLOW.md](docs/architecture/SYSTEM_FLOW.md) for complete Mermaid diagrams.

### High-Level Flow

```
User → API → ChatOrchestrator → Supervisor → TutorAgent → CorrectiveRAG → Response
                                    ↓
                              [RAG/Memory/Direct]
```

### Performance (Dec 2025)

| Scenario | Latency | Notes |
|----------|---------|-------|
| Cold Path | 85-90s | With Phase 2.4a optimizations |
| Warm Cache | 45s | Semantic cache hit |
| Simple Chat | 4-5s | Direct response |

---

## ⚙️ Configuration

Key environment variables:

```env
# Required
GOOGLE_API_KEY=your-gemini-api-key
DATABASE_URL=postgresql://...

# Optional
NEO4J_URI=neo4j+s://...
SUPABASE_URL=https://...
```

See [.env.example](.env.example) for full list.

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [SYSTEM_FLOW.md](docs/architecture/SYSTEM_FLOW.md) | System flow diagrams (Mermaid) |
| [SYSTEM_ARCHITECTURE.md](docs/architecture/SYSTEM_ARCHITECTURE.md) | Component deep dive |
| [FOLDER_MAP.md](docs/architecture/FOLDER_MAP.md) | Complete file mapping |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [ROADMAP.md](ROADMAP.md) | Future plans |

---

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run production API tests
python scripts/test_production_api.py
```

---

## 📝 License

Proprietary - All rights reserved.

---

*Last Updated: 2025-12-20 | Version 2.0.0*
