# Maritime AI Tutor Service

AI Microservice for Maritime LMS - Agentic RAG with Long-term Memory

## Architecture

- **Clean Architecture** with separation of concerns
- **LangGraph** for Agent Orchestration
- **Memori (GibsonAI)** for Long-term Memory
- **Neo4j GraphRAG** for Maritime Knowledge Base

## Project Structure

```
maritime-ai-service/
├── app/
│   ├── api/                # FastAPI Routes
│   │   ├── v1/
│   │   │   └── chat.py     # Chat endpoint
│   │   └── deps.py         # Dependencies
│   ├── core/               # Core configs
│   │   ├── config.py       # Environment settings
│   │   └── security.py     # Auth middleware
│   ├── engine/             # AI Logic
│   │   ├── graph.py        # LangGraph Orchestrator
│   │   ├── memory.py       # Memori Engine
│   │   └── tools/          # Agent Tools
│   ├── models/             # Pydantic & SQLAlchemy
│   ├── repositories/       # Data Access Layer
│   ├── services/           # Business Logic
│   └── main.py             # App Entry
├── tests/
│   ├── unit/
│   ├── property/           # Hypothesis tests
│   └── integration/
├── data/                   # Seed data (PDFs)
└── docker-compose.yml
```

## Quick Start

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# Install dependencies
pip install -r requirements.txt

# Run tests
pytest

# Start server
uvicorn app.main:app --reload
```

## API Endpoints

- `POST /api/v1/chat/completion` - Main chat endpoint
- `GET /api/v1/health` - Health check

## Testing

Property-based tests using Hypothesis ensure correctness across all inputs.
