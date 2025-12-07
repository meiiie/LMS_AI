# Semantic Memory Architecture

**Maritime AI Service - Semantic Memory System**

*Consolidated documentation from v0.3 → v0.5 evolution*  
*Updated for Project Restructure (CHỈ THỊ KỸ THUẬT SỐ 25)*

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Module Structure](#module-structure)
4. [Core Components](#core-components)
5. [API Reference](#api-reference)
6. [Database Schema](#database-schema)
7. [Configuration](#configuration)
8. [Usage Examples](#usage-examples)
9. [Version History](#version-history)
10. [Migration Guide](#migration-guide)

---

## Overview

The Semantic Memory System provides intelligent memory capabilities for the Maritime AI Service, enabling the system to:

- **Remember user context** across conversations
- **Extract and store facts** from interactions
- **Retrieve relevant information** based on semantic similarity
- **Build user profiles** over time
- **Provide personalized responses** based on learned preferences

### Key Features

- 🧠 **Semantic Understanding**: Uses embeddings for context-aware retrieval
- 📊 **Fact Extraction**: Automatically extracts structured information from conversations
- 🔍 **Similarity Search**: Vector-based search for relevant context
- 👤 **User Profiling**: Builds comprehensive user profiles over time
- 🔄 **Real-time Processing**: Processes conversations as they happen
- 📈 **Prioritized Insights**: Ranks information by relevance and recency

---

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Maritime AI Service                      │
├─────────────────────────────────────────────────────────────┤
│  UnifiedAgent  │  ChatService  │  API Endpoints            │
├─────────────────────────────────────────────────────────────┤
│                 SemanticMemoryEngine                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────┐   │
│  │ContextRetriever│FactExtractor│ SemanticMemoryEngine │   │
│  │             │ │             │ │     (Facade)        │   │
│  └─────────────┘ └─────────────┘ └─────────────────────┘   │
├─────────────────────────────────────────────────────────────┤
│  SemanticMemoryRepository  │  GeminiEmbedding             │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL Database       │  Google Gemini API           │
└─────────────────────────────────────────────────────────────┘
```

### Data Flow

1. **Conversation Input** → UnifiedAgent receives user message
2. **Context Retrieval** → ContextRetriever retrieves relevant user context
3. **Response Generation** → UnifiedAgent generates response with context
4. **Fact Extraction** → FactExtractor analyzes conversation for new facts
5. **Storage** → Facts saved to PostgreSQL with embeddings
6. **Profile Update** → User profile updated with new insights

---

## Module Structure

*As of Project Restructure (v2.0):*

```
app/engine/semantic_memory/
├── __init__.py              # Module exports
├── core.py                  # SemanticMemoryEngine (Facade) ~580 lines
├── context.py               # ContextRetriever (retrieval) ~242 lines
└── extraction.py            # FactExtractor (extraction & saving) ~397 lines

# Backward compatibility
app/engine/semantic_memory.py  # Imports from core.py
```

### Component Responsibilities

| Component | Responsibility | Key Methods |
|-----------|----------------|-------------|
| **SemanticMemoryEngine** | Main facade, backward compatibility | `retrieve_context()`, `extract_user_facts()` |
| **ContextRetriever** | Context and insights retrieval | `retrieve_context()`, `retrieve_insights_prioritized()` |
| **FactExtractor** | Fact extraction and storage | `extract_and_store_facts()`, `store_user_fact_upsert()` |

---

## Core Components

### 1. SemanticMemoryEngine (Facade)

**Location**: `app/engine/semantic_memory/core.py`

Main entry point that maintains backward compatibility while delegating to specialized modules.

```python
from app.engine.semantic_memory import SemanticMemoryEngine

engine = SemanticMemoryEngine()
context = await engine.retrieve_context(user_id, query)
```

### 2. ContextRetriever

**Location**: `app/engine/semantic_memory/context.py`

Handles context retrieval and insight prioritization.

**Key Features**:
- Semantic similarity search
- Insight prioritization by type and recency
- Context summarization
- User profile building

### 3. FactExtractor

**Location**: `app/engine/semantic_memory/extraction.py`

Extracts and stores facts from conversations.

**Key Features**:
- LLM-powered fact extraction
- Structured fact categorization
- Confidence scoring
- Embedding generation and storage

---

## API Reference

### SemanticMemoryEngine Methods

#### `retrieve_context(user_id, query, max_facts=10, similarity_threshold=0.7)`

Retrieves relevant context for a user query.

**Parameters**:
- `user_id` (str): User identifier
- `query` (str): Search query
- `search_limit` (int): Maximum facts to retrieve
- `similarity_threshold` (float): Minimum similarity score

**Returns**: `SemanticContext` with context data

#### `extract_user_facts(user_id, message)`

Extracts facts from a message using LLM.

**Parameters**:
- `user_id` (str): User identifier
- `message` (str): Message to analyze

**Returns**: `UserFactExtraction` with extracted facts

#### `store_user_fact_upsert(user_id, fact_content, fact_type, confidence)`

Stores or updates a user fact using upsert logic.

**Parameters**:
- `user_id` (str): User identifier
- `fact_content` (str): Fact content
- `fact_type` (str): Type of fact
- `confidence` (float): Confidence score

**Returns**: `bool` indicating success

---

## Database Schema

### semantic_memories Table

```sql
CREATE TABLE semantic_memories (
    id SERIAL PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(768),
    memory_type VARCHAR(50) NOT NULL,
    importance FLOAT DEFAULT 0.5,
    metadata JSONB,
    session_id VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_semantic_memories_user_id ON semantic_memories(user_id);
CREATE INDEX idx_semantic_memories_type ON semantic_memories(memory_type);
CREATE INDEX idx_semantic_memories_embedding ON semantic_memories 
    USING ivfflat (embedding vector_cosine_ops);
```

### Fact Types (v0.4+)

Only 6 essential types allowed:
- `name` - User's name
- `role` - Sinh viên/Giáo viên/Thuyền trưởng
- `level` - Năm 3, Đại phó, Sĩ quan...
- `goal` - Learning goals
- `preference` - Learning preferences/style
- `weakness` - Areas needing improvement

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/maritime_ai

# Google Gemini API
GOOGLE_API_KEY=your_gemini_api_key

# Semantic Memory Settings
EMBEDDING_MODEL=models/gemini-embedding-001
EMBEDDING_DIMENSIONS=768
SEMANTIC_MEMORY_ENABLED=true
SUMMARIZATION_TOKEN_THRESHOLD=2000
```

---

## Usage Examples

### Basic Usage

```python
from app.engine.semantic_memory import SemanticMemoryEngine

# Initialize
engine = SemanticMemoryEngine()

# Retrieve context for user query
context = await engine.retrieve_context(
    user_id="user123",
    query="What are my learning goals?"
)

# Store interaction
await engine.store_interaction(
    user_id="user123",
    message="I want to learn about COLREGs",
    response="I'll help you learn about COLREGs...",
    extract_facts=True
)
```

### Advanced Usage

```python
# Get prioritized insights
insights = await engine.retrieve_insights_prioritized(
    user_id="user123",
    query="learning progress",
    limit=5
)

# Store fact directly
await engine.store_user_fact_upsert(
    user_id="user123",
    fact_content="User is a maritime student",
    fact_type="role",
    confidence=0.9
)
```

---

## Version History

### v2.0 (Current) - Project Restructure
**Date**: December 2025

**Major Changes**:
- 🔄 **Modular Architecture**: Split monolithic `semantic_memory.py` (1,298 lines) into specialized modules
- 🏗️ **Facade Pattern**: `SemanticMemoryEngine` now acts as facade for `ContextRetriever` and `FactExtractor`
- 🔗 **Backward Compatibility**: Both import paths work
- 📁 **File Organization**: New structure in `app/engine/semantic_memory/` directory

### v0.5 - Insight Memory Engine
**Date**: November 2025

**Features Added**:
- ✨ **Behavioral Insights**: From atomic facts to behavioral understanding
- 🎯 **Category Prioritization**: knowledge_gap and learning_style prioritized
- 📊 **Memory Consolidation**: LLM-based consolidation at 40/50 threshold
- 🔍 **Contradiction Detection**: Detects and handles contradicting facts

### v0.4 - Managed Memory List
**Date**: October 2025

**Features Added**:
- 🚀 **Memory Capping**: Maximum 50 facts per user
- 📈 **Upsert Logic**: True deduplication by fact_type
- 🔒 **Fact Type Validation**: Only 6 essential types allowed
- 📝 **Memory API**: GET /api/v1/memories/{user_id}

### v0.3 - Foundation
**Date**: September 2025

**Initial Features**:
- 🧠 **Vector Embeddings**: Gemini Embedding API with MRL
- 📊 **pgvector**: Vector similarity search on Supabase
- 🔍 **Hybrid Context**: Semantic search + sliding window
- 💾 **Cross-Session**: Memory persistence across sessions

---

## Migration Guide

### From v0.5 to v2.0 (Project Restructure)

**Code Changes**: None required! Backward compatibility maintained.

**Import Options**:
```python
# Both work identically:
from app.engine.semantic_memory import SemanticMemoryEngine  # Old style
from app.engine.semantic_memory.core import SemanticMemoryEngine  # New style
```

---

*Last Updated: December 2025*  
*Version: 2.0 (Project Restructure)*
