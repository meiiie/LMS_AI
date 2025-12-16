# Maritime AI Tutor Service

<div align="center">

![Maritime AI Tutor Banner](assets/banner_AI_LMS.jpeg)

[![Python](https://img.shields.io/badge/Python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.109-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![LangChain](https://img.shields.io/badge/LangChain-1.1.2-1c3c3c?style=flat-square&logo=chainlink&logoColor=white)](https://langchain.com)
[![LangGraph](https://img.shields.io/badge/LangGraph-1.0.4-purple?style=flat-square)](https://langchain.com)
[![Gemini](https://img.shields.io/badge/Gemini-2.5_Flash-4285F4?style=flat-square&logo=google&logoColor=white)](https://ai.google.dev)
[![Neon](https://img.shields.io/badge/Neon-pgvector-00E599?style=flat-square&logo=postgresql&logoColor=white)](https://neon.tech)
[![License](https://img.shields.io/badge/License-Proprietary-red?style=flat-square)](LICENSE)
[![Version](https://img.shields.io/badge/Version-1.0.0-blue?style=flat-square)](CHANGELOG.md)

**AI-Powered Maritime Education Platform with Agentic RAG, Semantic Memory & LMS Integration**

*Backend AI Service cho hệ thống LMS Hàng hải - Production Ready*

[Quick Start](#quick-start) • [API Reference](#api-reference) • [LMS Integration](#lms-integration) • [Changelog](CHANGELOG.md) • [Roadmap](ROADMAP.md)

</div>

---

## What's New in v1.0.0

| Feature | Description |
|---------|-------------|
| **Agentic RAG v1.0** | Self-correcting RAG with query analysis, grading, rewriting |
| **Contextual RAG** | Anthropic-style context enrichment for 49% better retrieval |
| **Reasoning Trace** | Step-by-step AI reasoning visibility for transparency |
| **Document KG** | LLM entity extraction from PDFs into Neo4j graph |
| **Multi-Agent System** | Supervisor + RAG/Tutor/Memory/Grader agents |
| **Memory Control** | User can say "Remember/Forget" to control AI memory |
| **Memory Compression** | 70-90% token savings with intelligent summarization |
| **Knowledge Graph v1.0** | Hybrid Neon + Neo4j architecture (MemoriLabs pattern) |
| **Thread-based Sessions** | Multi-thread support like ChatGPT "New Chat" |
| **Admin Document API** | LMS admin can upload/manage knowledge base |
| **Streaming API** | Real-time SSE response with token streaming |
| **LMS Analytics** | topics_accessed, confidence_score, query_type |
| **Source Highlighting** | Bounding boxes + PDF.js integration |
| **Semantic Memory v0.5** | Insight extraction + behavioral learning |
| **Hybrid Search v0.6** | Dense + Sparse + RRF Reranking |
| **Tool Registry Pattern** | Modular tool management with categories (SOTA 2025) |

> 📋 **Full version history:** See [CHANGELOG.md](CHANGELOG.md) | **Future plans:** See [ROADMAP.md](ROADMAP.md)

---

## Overview

Maritime AI Tutor Service is a **Backend AI microservice** designed for integration with maritime LMS (Learning Management System). Key features include:

- **Agentic RAG v1.0** — Self-correcting RAG with query analysis, grading, and verification
- **Contextual RAG** — Anthropic-style chunk enrichment for ~49% better retrieval accuracy
- **Multi-Agent System** — Supervisor + specialized agents (RAG/Tutor/Memory/Grader)
- **Memory Control** — User can say "Remember/Forget" to explicitly control AI memory
- **Memory Compression** — 70-90% token savings with intelligent summarization (Mem0-style)
- **Intelligent Tutoring** — AI Tutor with role-based prompting (Student/Teacher/Admin)
- **Knowledge Graph v1.0** — Hybrid Neon + Neo4j (STUDIED, WEAK_AT, PREREQUISITE relationships)
- **Role-Specific Knowledge Graphs** — SOTA 2025 multi-role architecture (see below)
- **Hybrid Search v0.6** — Dense Search (pgvector) + Sparse Search (tsvector) + RRF Reranking
- **GraphRAG Knowledge** — SOLAS, COLREGs, MARPOL (PostgreSQL-based, Neo4j reserved for Learning Graph)
- **Semantic Memory v0.5** — Cross-session memory + Insight Engine (behavioral learning)
- **Streaming API** — Server-Sent Events for real-time UX
- **Guardian Agent v0.8.1** — LLM-based Content Moderation with Gemini 2.5 Flash
- **Multimodal RAG v1.0** — Vision-based document understanding with Evidence Images
- **Source Highlighting v0.9.8** — Bounding boxes + Citation jumping for PDF viewer

### SOTA 2025: Role-Specific Knowledge Graphs

Theo nghiên cứu SOTA 2025, các hệ thống LMS hiện đại sử dụng **role-specific knowledge graphs** riêng biệt cho từng loại người dùng:

| Role | Knowledge Graph | Nodes/Relationships | Status |
|------|----------------|---------------------|--------|
| **Student** | Learning Graph | `User→STUDIED→Module`, `User→WEAK_AT→Topic` | ✅ Implemented |
| **Teacher** | Teaching Graph | `Teacher→TEACHES→Module`, `Teacher→CREATED→Quiz` | 🔜 Future |
| **Admin** | System Graph | `Admin→MANAGES→Department`, Analytics | 🔜 Future |

**Current Implementation (Student-focused):**
- 学Learning paths tracking (modules studied/completed)
- Knowledge gap detection (topics user is weak at)
- Prerequisites mapping (module dependencies)

**Future: Teacher Graph Context**
```
Teacher → TEACHES → Module
Teacher → CREATED → Quiz
Teacher → ASSIGNED → Student (for tutoring)
Student → WEAK_AT → Topic (visible to teacher)
```

> 📚 **Research basis:** Educational Knowledge Graphs (EduKG), Tenant-specific Knowledge Graphs (Neo4j pattern), Multi-tenant LMS architectures

---

## LMS Integration

### Architecture Pattern: Smart Orchestrator (Option 1)

```
┌─────────────────────────────────────────────────────────────────────┐
│                        LMS SYSTEM                                    │
│   [Angular Frontend] ──JWT──▶ [Spring Boot Backend]                 │
│                                      │                               │
│                                      │ API Key + user_id            │
└──────────────────────────────────────┼───────────────────────────────┘
                                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     BACKEND AI SERVICE                               │
│   POST /api/v1/chat/       → Full response                          │
│   POST /api/v1/chat/stream → SSE streaming                          │
└─────────────────────────────────────────────────────────────────────┘
```

### Data Ownership

| Data | Owner | Notes |
|------|-------|-------|
| Users, Auth, Logs | LMS | AI chỉ nhận user_id |
| AI Memories | AI | Auto-managed per user_id |
| Knowledge Base | AI | RAG documents, embeddings |

### API Authentication

```http
POST /api/v1/chat/
X-API-Key: {lms_api_key}
Content-Type: application/json

{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Điều 15 là gì?",
  "role": "student",
  "session_id": "session-uuid",
  "thread_id": "new"
}
```

### Thread-based Sessions

| `thread_id` | Behavior |
|-------------|----------|
| `"new"` or `null` | Creates new conversation thread |
| `"uuid..."` | Continues existing thread |

> **Note:** User facts persist across threads. Only chat history is thread-scoped.

### Admin Document API

```bash
# Upload PDF to knowledge base
POST /api/v1/admin/documents

# List all documents
GET /api/v1/admin/documents

# Check ingestion status
GET /api/v1/admin/documents/{job_id}

# Delete document
DELETE /api/v1/admin/documents/{document_id}
```

---

## Streaming API

### Real-time Response (Server-Sent Events)

```http
POST /api/v1/chat/stream
Content-Type: application/json
Accept: text/event-stream
```

### Event Types

| Event | Data | When |
|-------|------|------|
| `thinking` | `{content: "..."}` | AI reasoning |
| `answer` | `{content: "..."}` | Text chunks |
| `sources` | `{sources: [...]}` | After answer |
| `metadata` | `{processing_time, ...}` | End |
| `done` | `{}` | Final |

### Response Stream Example

```
event: thinking
data: {"content": "Đang tra cứu..."}

event: answer
data: {"content": "**Điều 15** quy định về"}

event: answer
data: {"content": " Chủ tàu và trách nhiệm..."}

event: sources
data: {"sources": [{"title": "Điều 15", "bounding_boxes": [...]}]}

event: metadata
data: {"processing_time": 5.2, "confidence_score": 0.9, "query_type": "factual"}

event: done
data: {}
```

### Analytics Metadata (LMS Integration)

| Field | Type | Description |
|-------|------|-------------|
| `topics_accessed` | string[] | Topics từ sources |
| `confidence_score` | float | 0.5-1.0 based on sources |
| `document_ids_used` | string[] | Documents referenced |
| `query_type` | string | factual/conceptual/procedural |

## Multimodal RAG (CHỈ THỊ KỸ THUẬT SỐ 26)

### Vision-based Document Understanding

Hệ thống đã được nâng cấp từ "Đọc văn bản" sang "Hiểu tài liệu" với khả năng:

- **AI "nhìn" thấy trang tài liệu** như con người (bảng biểu, sơ đồ đèn hiệu, hình vẽ tàu bè)
- **Evidence Images**: Hiển thị ảnh trang sách luật gốc cùng câu trả lời
- **Hybrid Infrastructure**: Neon (metadata) + Supabase Storage (images)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    MULTIMODAL INGESTION PIPELINE                             │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   PDF Document                                                               │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│   │ 1. RASTERIZE    │ →  │ 2. UPLOAD       │ →  │ 3. VISION       │         │
│   │ (PyMuPDF)       │    │ (Supabase)      │    │ (Gemini 2.5)    │         │
│   │ PDF → Images    │    │ → public_url    │    │ Image → Text    │         │
│   │ No external deps│    │                 │    │                 │         │
│   └─────────────────┘    └─────────────────┘    └─────────────────┘         │
│                                                        │                     │
│                                                        ▼                     │
│                                              ┌─────────────────┐             │
│                                              │ 4. INDEX        │             │
│                                              │ (Neon pgvector) │             │
│                                              │ Text + image_url│             │
│                                              └─────────────────┘             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Evidence Images in Response

```json
{
  "answer": "Theo Điều 15 COLREGs...",
  "sources": [...],
  "evidence_images": [
    {
      "url": "https://xyz.supabase.co/.../page_15.jpg",
      "page_number": 15,
      "document_id": "colregs_2024"
    }
  ]
}
```

### Environment Variables

```env
# Supabase Storage (CHỈ THỊ 26)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_STORAGE_BUCKET=maritime-docs
```

### PDF Processing (PyMuPDF)

Hệ thống sử dụng **PyMuPDF (fitz)** để chuyển đổi PDF sang images:

- **No External Dependencies**: Không cần cài đặt Poppler hoặc các thư viện hệ thống khác
- **Cross-Platform**: Hoạt động trên Windows, Linux, macOS
- **High Quality**: 150 DPI đủ cho Gemini Vision đọc text
- **Memory Efficient**: Tối ưu cho Render Free Tier

```bash
# Re-ingest với multimodal pipeline
python scripts/reingest_multimodal.py \
    --pdf data/VanBanGoc_95.2015.QH13.P1.pdf \
    --document-id luat_hang_hai_2015 \
    --no-resume

# Test với giới hạn pages (development)
python scripts/reingest_multimodal.py \
    --pdf data/VanBanGoc_95.2015.QH13.P1.pdf \
    --document-id luat_hang_hai_2015 \
    --max-pages 5

# Verify image URLs trong database
python scripts/verify_image_urls.py
```

### Supabase Storage Policies

Để upload images, cần cấu hình Storage Policies trong Supabase Dashboard:

```sql
-- Allow uploads to maritime-docs bucket
CREATE POLICY "Allow uploads to maritime-docs"
ON storage.objects FOR INSERT
TO public
WITH CHECK (bucket_id = 'maritime-docs');

-- Allow updates (for upsert)
CREATE POLICY "Allow updates to maritime-docs"
ON storage.objects FOR UPDATE
TO public
USING (bucket_id = 'maritime-docs')
WITH CHECK (bucket_id = 'maritime-docs');
```

---

## Hybrid Text/Vision Detection v0.9.0 (NEW)

### Cost Optimization for Ingestion Pipeline

Tính năng mới giúp giảm 50-70% API calls cho Gemini Vision bằng cách phân loại thông minh các trang PDF:

- **Text-only pages**: Extract trực tiếp bằng PyMuPDF (miễn phí, nhanh)
- **Visual pages**: Gửi qua Gemini Vision (chính xác cho bảng/hình)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    HYBRID TEXT/VISION DETECTION                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   PDF Page                                                                   │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────┐                                                        │
│   │ PAGE ANALYZER   │  Checks: images, tables, diagrams, maritime keywords   │
│   └────────┬────────┘                                                        │
│            │                                                                 │
│     ┌──────┴──────┐                                                          │
│     │             │                                                          │
│     ▼             ▼                                                          │
│ ┌────────┐   ┌────────┐                                                      │
│ │ TEXT   │   │ VISUAL │                                                      │
│ │ ONLY   │   │CONTENT │                                                      │
│ └───┬────┘   └───┬────┘                                                      │
│     │            │                                                           │
│     ▼            ▼                                                           │
│ ┌────────────┐ ┌────────────┐                                                │
│ │ DIRECT     │ │ VISION     │                                                │
│ │ EXTRACTION │ │ EXTRACTION │                                                │
│ │ (PyMuPDF)  │ │ (Gemini)   │                                                │
│ │ FREE ✓     │ │ PAID $     │                                                │
│ └────────────┘ └────────────┘                                                │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Detection Criteria

| Indicator | Detection Method | Result |
|-----------|------------------|--------|
| Embedded images | `page.get_images()` | → Vision |
| Table patterns | Pipe characters, grid patterns | → Vision |
| Diagram keywords | hình, figure, sơ đồ | → Vision |
| Maritime signals | đèn, tín hiệu, cờ | → Vision |
| Plain text only | No visual indicators | → Direct |

### Configuration

```env
# Hybrid Detection Settings
HYBRID_DETECTION_ENABLED=true
MIN_TEXT_LENGTH_FOR_DIRECT=100
FORCE_VISION_MODE=false
```

### Ingestion Result with Savings

```python
result = await ingestion_service.ingest_pdf(pdf_path, document_id)

print(f"Vision pages: {result.vision_pages}")
print(f"Direct pages: {result.direct_pages}")
print(f"API savings: {result.api_savings_percent:.1f}%")
```

---

## Semantic Chunking v2.7.0

### Intelligent Document Segmentation

Nâng cấp từ "Page-level indexing" sang "Semantic chunk-level indexing" với khả năng:

- **Maritime-Specific Patterns**: Nhận diện cấu trúc Điều, Khoản, Điểm, Rule
- **Content Type Classification**: text, table, heading, diagram_reference, formula
- **Confidence Scoring**: Đánh giá chất lượng chunk (0.6-1.0)
- **Document Hierarchy Extraction**: Tự động trích xuất cấu trúc văn bản pháp luật

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SEMANTIC CHUNKING PIPELINE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   Vision Extracted Text                                                      │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│   │ 1. CHUNK        │ →  │ 2. CLASSIFY     │ →  │ 3. SCORE        │         │
│   │ (800 chars)     │    │ (Content Type)  │    │ (Confidence)    │         │
│   │ overlap=100     │    │ text/table/...  │    │ 0.6 - 1.0       │         │
│   └─────────────────┘    └─────────────────┘    └─────────────────┘         │
│                                                        │                     │
│                                                        ▼                     │
│                                              ┌─────────────────┐             │
│                                              │ 4. EXTRACT      │             │
│                                              │ (Hierarchy)     │             │
│                                              │ Điều/Khoản/Rule │             │
│                                              └─────────────────┘             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Content Types

| Type | Pattern | Example |
|------|---------|---------|
| `heading` | Điều, Khoản, Rule, Chapter | "Điều 15. Tình huống cắt hướng" |
| `table` | Markdown tables, \| separators | Bảng tốc độ tàu thuyền |
| `formula` | Mathematical expressions | "V = D/T" |
| `diagram_reference` | Hình, Figure, Sơ đồ | "Xem Hình 3.1" |
| `text` | Default content | Nội dung văn bản thông thường |

### Database Schema

```sql
-- Enhanced knowledge_embeddings table
ALTER TABLE knowledge_embeddings ADD COLUMN content_type VARCHAR(50) DEFAULT 'text';
ALTER TABLE knowledge_embeddings ADD COLUMN confidence_score FLOAT DEFAULT 1.0;
ALTER TABLE knowledge_embeddings ADD COLUMN chunk_index INTEGER DEFAULT 0;

-- Indexes for performance
CREATE INDEX idx_knowledge_chunks_content_type ON knowledge_embeddings(content_type);
CREATE INDEX idx_knowledge_chunks_confidence ON knowledge_embeddings(confidence_score);
CREATE INDEX idx_knowledge_chunks_ordering ON knowledge_embeddings(document_id, page_number, chunk_index);
```

### Re-ingestion with Chunking

```bash
# Re-ingest documents with semantic chunking
python scripts/reingest_with_chunking.py \
    --pdf data/VanBanGoc_95.2015.QH13.P1.pdf \
    --document-id maritime_law_2024 \
    --truncate-first

# Verify chunking results
psql $DATABASE_URL -c "
SELECT content_type, COUNT(*) as chunks, AVG(confidence_score) as avg_confidence 
FROM knowledge_embeddings 
WHERE document_id = 'maritime_law_2024' 
GROUP BY content_type;
"
```

### Property-Based Tests

```bash
# Run semantic chunking tests (15 tests)
pytest tests/property/test_chunking_properties.py -v

# Test specific properties
pytest tests/property/test_chunking_properties.py::test_chunk_size_bounds -v
pytest tests/property/test_chunking_properties.py::test_confidence_score_bounds -v
```

---

## Source Highlighting with Citation Jumping v0.9.8 (NEW)

### PDF Text Highlighting for Frontend

Tính năng cho phép frontend hiển thị chính xác vị trí text được trích dẫn trong PDF viewer.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    SOURCE HIGHLIGHTING ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   PDF Document                                                               │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────┐                                                        │
│   │ PyMuPDF Extract │  Extract text + bounding boxes                         │
│   │ (fitz)          │  page.get_text("dict") → blocks with bbox              │
│   └────────┬────────┘                                                        │
│            │                                                                 │
│            ▼                                                                 │
│   ┌─────────────────┐                                                        │
│   │ BoundingBox     │  Normalize coords to percentage (0-100)                │
│   │ Normalizer      │  Handle multi-block chunks                             │
│   └────────┬────────┘                                                        │
│            │                                                                 │
│            ▼                                                                 │
│   ┌─────────────────┐                                                        │
│   │ Neon PostgreSQL │  Store in knowledge_embeddings.bounding_boxes          │
│   │ (JSONB column)  │  Format: [{"x0":0,"y0":0,"x1":100,"y1":10}, ...]       │
│   └────────┬────────┘                                                        │
│            │                                                                 │
│            ▼                                                                 │
│   ┌─────────────────┐                                                        │
│   │ Chat API        │  Return sources with bounding_boxes                    │
│   │ /api/v1/chat    │  + Source Details API /api/v1/sources/{node_id}        │
│   └─────────────────┘                                                        │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### API Response with Bounding Boxes

```json
{
  "data": {
    "answer": "Theo Điều 15 COLREGs...",
    "sources": [
      {
        "title": "Rule 15 - Crossing Situation",
        "content": "When two power-driven vessels...",
        "page_number": 15,
        "image_url": "https://supabase.co/.../page_15.jpg",
        "document_id": "colregs_2024",
        "bounding_boxes": [
          {"x0": 10.5, "y0": 45.2, "x1": 90.3, "y1": 52.7}
        ]
      }
    ]
  }
}
```

### Source Details API

```bash
# Get full source details by node_id
GET /api/v1/sources/{node_id}

# Response includes:
# - content: Full text content
# - bounding_boxes: Normalized coordinates (0-100%)
# - page_number, document_id, image_url
# - content_type, confidence_score
```

### Re-ingestion Script

```bash
# Update existing chunks with bounding boxes
python scripts/reingest_bounding_boxes.py \
    --pdf data/COLREGs.pdf \
    --document-id colregs_2024

# Dry run (preview changes)
python scripts/reingest_bounding_boxes.py \
    --pdf data/COLREGs.pdf \
    --document-id colregs_2024 \
    --dry-run --verbose

# Check schema status
python scripts/check_bounding_boxes_schema.py
```

### Database Schema

```sql
-- Migration 006: Add bounding_boxes column
ALTER TABLE knowledge_embeddings 
ADD COLUMN bounding_boxes JSONB DEFAULT NULL;

-- GIN index for JSONB querying
CREATE INDEX idx_knowledge_bounding_boxes 
ON knowledge_embeddings USING GIN(bounding_boxes);
```

### Frontend Integration

Frontend có thể sử dụng bounding_boxes để:
1. **Jump to page**: Sử dụng `page_number` để navigate đến trang PDF
2. **Highlight text**: Sử dụng `bounding_boxes` để vẽ highlight overlay
3. **Show evidence**: Hiển thị `image_url` như preview thumbnail

Coordinates được normalize về percentage (0-100) để responsive trên mọi kích thước màn hình.

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

### Hybrid Search v0.6.0 (Dense + Sparse + RRF + Title Boosting)

**Feature: sparse-search-migration** - Sparse Search đã được migrate từ Neo4j sang PostgreSQL tsvector.

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
│   │ (pgvector)    │    │ (tsvector)    │  ← MIGRATED from Neo4j             │
│   │               │    │               │                                    │
│   │ Semantic      │    │ Keyword       │                                    │
│   │ Similarity    │    │ Matching      │                                    │
│   │ (Cosine)      │    │ (ts_rank)     │                                    │
│   └───────┬───────┘    └───────┬───────┘                                    │
│           │                    │                                             │
│           └────────┬───────────┘                                             │
│                    ▼                                                         │
│           ┌───────────────────┐                                             │
│           │   RRF Reranker    │                                             │
│           │   (k=60)          │                                             │
│           │                   │                                             │
│           │ + Title Boosting  │                                             │
│           │ + Number Boosting │  ← Rule numbers (15, 19...)                 │
│           └─────────┬─────────┘                                             │
│                     ▼                                                        │
│           ┌───────────────────┐                                             │
│           │  Merged Results   │                                             │
│           │  (Top-K by RRF)   │                                             │
│           └───────────────────┘                                             │
│                                                                              │
│   Neo4j: Reserved for future Learning Graph (LMS integration)               │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Dense Search (pgvector)**: Semantic similarity với Gemini embeddings (768 dims, L2 normalized)
- **Sparse Search (PostgreSQL tsvector)**: Keyword matching với ts_rank scoring + Vietnamese support
- **RRF Reranker**: Reciprocal Rank Fusion (k=60) - boost documents xuất hiện ở cả 2 nguồn
- **Number Boosting**: 2.0x boost cho rule numbers (Rule 15, Điều 19...)
- **Vietnamese Support**: Stop words + Maritime synonyms (cảnh giới ↔ lookout, tàu ↔ vessel)
- **Graceful Degradation**: Fallback về Dense-only nếu Sparse không khả dụng

### Sparse Search Migration v0.6.0 (NEW - 09/12/2024)

**Feature: sparse-search-migration** - Migrate Sparse Search từ Neo4j sang PostgreSQL tsvector.

**Mục tiêu:**
- Đơn giản hóa architecture (1 database thay vì 2)
- Giảm chi phí infrastructure
- Neo4j reserved cho future Learning Graph (LMS integration)

**Thay đổi chính:**

| Component | Before | After |
|-----------|--------|-------|
| Sparse Search | Neo4j Full-text Index | PostgreSQL tsvector |
| Scoring | BM25-like | ts_rank |
| Index | Neo4j knowledge_fulltext | GIN idx_knowledge_search_vector |
| Neo4j Role | RAG + Knowledge Graph | Learning Graph only (optional) |

**Database Schema (Migration 004):**
```sql
-- Add tsvector column
ALTER TABLE knowledge_embeddings ADD COLUMN search_vector tsvector;

-- Create GIN index
CREATE INDEX idx_knowledge_search_vector ON knowledge_embeddings USING GIN(search_vector);

-- Auto-generate trigger
CREATE TRIGGER trg_update_search_vector
BEFORE INSERT OR UPDATE ON knowledge_embeddings
FOR EACH ROW EXECUTE FUNCTION update_search_vector();
```

**Test Script:**
```bash
# Run sparse search migration test
python scripts/test_sparse_search.py
```

### Test Results (09/12/2024)

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

### Semantic Memory v0.5 (Insight Memory Engine - CHỈ THỊ 23 CẢI TIẾN)

Nâng cấp từ "Atomic Facts" sang "Behavioral Insights" - biến AI từ "Thư ký" thành "Người Thầy (Mentor)".

- **Behavioral Insight Extraction**: Trích xuất sự thấu hiểu hành vi thay vì dữ liệu đơn lẻ
- **5 Insight Categories**: learning_style, knowledge_gap, goal_evolution, habit, preference
- **LLM-based Consolidation**: Tự động gộp và tinh gọn khi đạt 40/50 memories
- **Category-Prioritized Retrieval**: Ưu tiên knowledge_gap và learning_style
- **SOTA Duplicate Detection (12/12/2025)**: Embedding cosine similarity (0.85 insight, 0.90 fact)
- **Hard Limit Enforcement**: 50 insights/user với FIFO fallback
- **Last Accessed Tracking**: Bảo vệ memories được truy cập trong 7 ngày gần đây

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         INSIGHT MEMORY ENGINE v0.5                           │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   LUỒNG XỬ LÝ (Tích hợp vào ChatService):                                   │
│                                                                              │
│   User Message → API /chat                                                   │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ 1. RETRIEVE: retrieve_insights_prioritized()                         │   │
│   │    → Lấy insights ưu tiên (knowledge_gap, learning_style first)      │   │
│   │    → Format vào semantic_context cho LLM prompt                      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ 2. PROCESS: UnifiedAgent xử lý với context                           │   │
│   │    → AI có thông tin về learning style, knowledge gaps của user      │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│        │                                                                     │
│        ▼                                                                     │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │ 3. STORE (Background): extract_and_store_insights()                  │   │
│   │    → InsightExtractor: Trích xuất behavioral insights từ message     │   │
│   │    → InsightValidator: Validate, detect duplicates/contradictions    │   │
│   │    → MemoryConsolidator: Consolidate nếu > 40 insights               │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│   COMPONENTS:                                                                │
│   • InsightExtractor (app/engine/insight_extractor.py)                      │
│   • InsightValidator (app/engine/insight_validator.py)                      │
│   • MemoryConsolidator (app/engine/memory_consolidator.py)                  │
│   • SemanticMemoryEngine v0.5 (app/engine/semantic_memory.py)               │
│                                                                              │
│   CATEGORIES:                                                                │
│   • learning_style: "User thích học qua ví dụ thực tế"                      │
│   • knowledge_gap: "User nhầm lẫn giữa Rule 13 và Rule 15"                  │
│   • goal_evolution: "User chuyển từ học cơ bản sang thi thuyền trưởng"      │
│   • habit: "User thường học vào buổi tối"                                   │
│   • preference: "User quan tâm đến navigation hơn engine room"              │
│                                                                              │
│   DATABASE SCHEMA (v0.5):                                                    │
│   • insight_category VARCHAR(50) - Category của insight                     │
│   • sub_topic VARCHAR(100) - Sub-topic chi tiết                             │
│   • last_accessed TIMESTAMP - Tracking để bảo vệ recent memories            │
│   • evolution_notes JSONB - Lịch sử thay đổi của insight                    │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **Memory API**: `GET /api/v1/memories/{user_id}` - Lấy danh sách insights
- **Documentation**: `docs/SEMANTIC_MEMORY_V05_GUIDE.md`
- **Migration Script**: `scripts/upgrade_semantic_memory_v05.sql`
- **Test Suite**: `scripts/test_insight_engine.py` (5/5 tests passed)

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
│  │                      Hybrid Search Service v0.6                        │  │
│  │  Dense (pgvector) + Sparse (tsvector) → RRF Reranker → Merged Results  │  │
│  └───────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
          │                         │                         │
          ▼                         ▼                         ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   PostgreSQL    │     │     Neo4j       │     │  Google Gemini  │
│   (Neon)        │     │  (OPTIONAL)     │     │  2.5 Flash      │
│   + pgvector    │     │  Reserved for   │     │  + Embeddings   │
│   + tsvector    │     │  Learning Graph │     │                 │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

---

## Project Structure

```
maritime-ai-service/
├── app/
│   ├── api/v1/                      # API endpoints (chat, health, knowledge, memories, insights)
│   ├── core/                        # Config, security, rate_limit, database
│   ├── engine/
│   │   ├── unified_agent.py         # UnifiedAgent - Main LangGraph agent
│   │   ├── agentic_rag/             # RAG Agent module
│   │   │   └── rag_agent.py         # RAGAgent with Hybrid Search
│   │   ├── tutor/                   # Tutor Agent module (NEW)
│   │   │   └── tutor_agent.py       # TutorAgent for teaching sessions
│   │   ├── agents/                  # Agent Registry (NEW)
│   │   │   ├── config.py            # AgentConfig, CrewAI-inspired fields
│   │   │   ├── base.py              # BaseAgent protocol
│   │   │   └── registry.py          # AgentRegistry + AgentTracer
│   │   ├── tools/                   # Tool Registry
│   │   │   ├── registry.py          # ToolRegistry with categories
│   │   │   ├── rag_tools.py         # RAG search tools
│   │   │   └── memory_tools.py      # Memory management tools
│   │   ├── multi_agent/             # Multi-Agent LangGraph (Optional)
│   │   │   ├── agents/              # Agent nodes (wrappers)
│   │   │   │   ├── rag_node.py      # RAGAgentNode (LangGraph wrapper)
│   │   │   │   ├── tutor_node.py    # TutorAgentNode (LangGraph wrapper)
│   │   │   │   ├── memory_agent.py  # MemoryAgentNode
│   │   │   │   └── grader_agent.py  # GraderAgentNode
│   │   │   ├── supervisor.py        # Supervisor Agent
│   │   │   └── graph.py             # LangGraph workflow
│   │   ├── semantic_memory/         # Semantic Memory v0.5 (Modular)
│   │   │   ├── core.py              # SemanticMemoryEngine (Facade)
│   │   │   ├── context.py           # ContextRetriever
│   │   │   └── extraction.py        # FactExtractor
│   │   ├── guardrails.py            # Input/Output validation (rule-based)
│   │   ├── guardian_agent.py        # LLM Content Moderation (Gemini 2.5 Flash)
│   │   ├── gemini_embedding.py      # Gemini Embeddings (768 dims, L2 norm)
│   │   ├── rrf_reranker.py          # RRF Reranker (k=60)
│   │   └── pdf_processor.py         # PDF extraction for ingestion
│   ├── models/                      # Pydantic & SQLAlchemy models
│   │   ├── schemas.py               # API Request/Response schemas
│   │   ├── database.py              # SQLAlchemy ORM (ChatSession, ChatMessage)
│   │   ├── learning_profile.py      # LearningProfile domain model
│   │   ├── semantic_memory.py       # Memory-related models
│   │   └── knowledge_graph.py       # Knowledge graph models
│   ├── prompts/                     # Persona YAML configs (Refactored)
│   │   ├── base/                    # Shared rules
│   │   │   └── _shared.yaml         # Common directives (tool_calling, reasoning)
│   │   └── agents/                  # Agent-specific personas
│   │       ├── tutor.yaml           # Student role (Captain AI)
│   │       ├── assistant.yaml       # Teacher/Admin role
│   │       ├── rag.yaml             # RAG agent persona
│   │       └── memory.yaml          # Memory agent persona
│   ├── repositories/
│   │   ├── dense_search_repository.py   # pgvector similarity search
│   │   ├── sparse_search_repository.py  # PostgreSQL tsvector search
│   │   ├── neo4j_knowledge_repository.py # Reserved for Learning Graph
│   │   ├── semantic_memory_repository.py
│   │   ├── learning_profile_repository.py
│   │   ├── user_graph_repository.py
│   │   └── chat_history_repository.py
│   └── services/
│       ├── chat_service.py          # Main integration service
│       ├── hybrid_search_service.py # Dense + Sparse + RRF
│       ├── multimodal_ingestion_service.py  # PDF ingestion pipeline
│       ├── learning_graph_service.py
│       └── supabase_storage.py      # Supabase Storage for images
├── alembic/
│   └── versions/                    # Database migrations
├── archive/                         # Archived legacy code
├── assets/                          # Static assets (images, banner)
├── scripts/                         # Utility scripts
├── tests/
│   ├── property/                    # Property-based tests (Hypothesis)
│   ├── unit/                        # Unit tests
│   ├── integration/                 # Integration tests
│   └── e2e/                         # End-to-end tests
├── docs/
│   ├── architecture/                # Architecture documentation
│   │   ├── tool-registry.md         # Tool Registry architecture
│   │   └── README.md
│   └── SEMANTIC_MEMORY_ARCHITECTURE.md
├── docker-compose.yml               # Local development stack
├── requirements.txt                 # Python dependencies
└── render.yaml                      # Render.com deployment
```

---

## Quick Start

### Prerequisites

- Python 3.11+
- Docker & Docker Compose
- Neo4j (local or Aura) - Optional, reserved for Learning Graph
- PostgreSQL with pgvector (local or Neon)
- Google Gemini API Key
- Supabase account (for image storage - CHỈ THỊ 26)

**Note**: PDF processing uses PyMuPDF (no external dependencies like Poppler required).

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

API cho phép Admin upload tài liệu PDF sử dụng Multimodal RAG pipeline (Vision-based).

### POST /api/v1/knowledge/ingest-multimodal

Upload PDF document để xử lý với Gemini Vision và lưu vào PostgreSQL (Neon).

**Pipeline:**
1. PDF → Images (PyMuPDF - no external deps)
2. Images → Supabase Storage (public URLs)
3. Images → Gemini Vision (text extraction)
4. Text → Semantic Chunking (maritime patterns)
5. Chunks + Embeddings + image_url → Neon Database

**Request (multipart/form-data):**
```bash
curl -X POST http://localhost:8000/api/v1/knowledge/ingest-multimodal \
  -F "file=@colregs.pdf" \
  -F "document_id=colregs_2024" \
  -F "role=admin" \
  -F "resume=true"
```

**Response:**
```json
{
  "status": "completed",
  "document_id": "colregs_2024",
  "total_pages": 50,
  "successful_pages": 50,
  "failed_pages": 0,
  "success_rate": 100.0,
  "errors": [],
  "message": "Processed 50/50 pages successfully"
}
```

### GET /api/v1/knowledge/stats

Lấy thống kê knowledge base từ PostgreSQL.

**Response:**
```json
{
  "total_chunks": 1250,
  "total_documents": 5,
  "content_types": {
    "text": 1000,
    "heading": 150,
    "table": 80,
    "diagram_reference": 20
  },
  "avg_confidence": 0.85
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
   - PostgreSQL tsvector với ts_rank scoring (migrated from Neo4j)
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
| **Embeddings** | Gemini gemini-embedding-001 (768 dims) |
| **Graph Database** | Neo4j 5.28 (Optional - Reserved for Learning Graph) |
| **Vector Database** | PostgreSQL + pgvector (Neon) |
| **Search** | Hybrid Search (Dense + Sparse + RRF) |
| **Memory** | Semantic Memory v0.5 (Insight Engine) |
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
| v1.0.1 | 2025-12-16 | **SOTA NATIVE-FIRST THINKING**: CHỈ THỊ SỐ 29 v2 - Native Gemini thinking (zero extra latency), Removed ThinkingGenerator (dead code), SOTA alignment with Claude/Qwen/Gemini 2025 patterns |
| v0.9.7 | 2025-12-10 | **DATABASE SCHEMA FIX & SOTA ARCHITECTURE**: Fix missing columns (is_blocked, block_reason, weak_areas, strong_areas, total_sessions, total_messages), Add SemanticMemoryEngine.is_available(), UUID/String conversion fix, Restore SOTA architecture (remove force search hardcode), Tool calling via YAML config (CHỈ THỊ SỐ 29), Alembic Migration 005 |
| v0.9.1 | 2025-12-09 | **MULTIMODAL RAG ENHANCEMENT**: Replace pdf2image+Poppler with PyMuPDF (no external deps), Add `image_url` to API response (sources), Evidence Images support in chat response, Cross-platform PDF processing |
| v0.9.0 | 2025-12-07 | **PROJECT RESTRUCTURE**: CHỈ THỊ SỐ 25 - Modular Semantic Memory (core.py, context.py, extraction.py), Legacy Code Removal (UnifiedAgent required), Test Organization (e2e/integration/unit/property), Scripts Organization (migrations/data/utils), Documentation Consolidation |
| v0.8.6 | 2025-12-07 | **SYSTEM LOGIC FLOW REPORT**: Báo cáo luồng logic thực sự - Complete System Flow diagram, Component Integration Verification table, Data Flow Verification, Xác minh tất cả components đã được tích hợp đúng cách |
| v0.8.6 | 2025-12-09 | **LEGACY CLEANUP**: Archive legacy ingestion (ingestion_service.py, pdf_processor.py, ingestion_job.py), Update knowledge.py to multimodal-only, Archive legacy tests, Remove pdf2image script, Update README |
| v0.8.5 | 2025-12-07 | **INSIGHT MEMORY ENGINE v0.5**: CHỈ THỊ SỐ 23 CẢI TIẾN - Behavioral Insights thay vì Atomic Facts, 5 Insight Categories (learning_style, knowledge_gap, goal_evolution, habit, preference), InsightExtractor + InsightValidator + MemoryConsolidator, LLM-based Consolidation (40/50 threshold), Category-Prioritized Retrieval, Duplicate/Contradiction Detection, Evolution Notes tracking, Full integration vào ChatService |
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
| v0.5.0 | 2025-12-04 | Hybrid Search v0.5 - Dense (pgvector) + Sparse (Neo4j FTS → PostgreSQL tsvector) + RRF Reranking (k=60) |
| v0.4.0 | 2025-12-03 | Knowledge Ingestion API - Admin PDF upload (now Multimodal RAG) |
| v0.3.0 | 2025-12-02 | Semantic Memory v0.3, Cross-session persistence with pgvector |
| v0.2.1 | 2025-12-01 | Memory Lite, Chat History, Learning Profile |
| v0.2.0 | 2025-11-30 | Role-based prompting, Multi-agent architecture |
| v0.1.0 | 2025-11-28 | Initial release with RAG |

---

## System Logic Flow Report (v0.8.5)

### Báo cáo Luồng Logic Thực Sự - Đã Xác Minh

Dưới đây là luồng xử lý thực tế của hệ thống, đã được xác minh qua code analysis.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         COMPLETE SYSTEM FLOW                                 │
│                    (ChatService → UnifiedAgent → Response)                   │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   [1] API LAYER (app/api/v1/chat.py)                                        │
│       │                                                                      │
│       ▼                                                                      │
│   POST /api/v1/chat                                                          │
│       │ ChatRequest(user_id, message, role, session_id)                     │
│       │                                                                      │
│       ▼                                                                      │
│   [2] CHAT SERVICE (app/services/chat_service.py)                           │
│       │                                                                      │
│       ├──▶ [2.1] GUARDIAN AGENT (LLM Content Moderation)                    │
│       │         ├── validate_message() → ALLOW/BLOCK/FLAG                   │
│       │         ├── validate_pronoun_request() → Custom pronouns            │
│       │         └── Fallback: Rule-based Guardrails                         │
│       │                                                                      │
│       ├──▶ [2.2] SESSION MANAGEMENT                                         │
│       │         ├── get_or_create_session(user_id)                          │
│       │         └── SessionState (anti-repetition, pronoun_style)           │
│       │                                                                      │
│       ├──▶ [2.3] MEMORY RETRIEVAL (Semantic Memory v0.5)                    │
│       │         ├── retrieve_insights_prioritized() → Behavioral Insights   │
│       │         │   └── Categories: knowledge_gap, learning_style (priority)│
│       │         ├── retrieve_context() → User Facts + Memories              │
│       │         └── get_recent_messages() → Sliding Window (50 msgs)        │
│       │                                                                      │
│       ├──▶ [2.4] CONVERSATION ANALYZER (Deep Reasoning)                     │
│       │         ├── analyze() → ConversationContext                         │
│       │         └── should_offer_continuation → Proactive hints             │
│       │                                                                      │
│       ▼                                                                      │
│   [3] UNIFIED AGENT (app/engine/unified_agent.py)                           │
│       │                                                                      │
│       ├──▶ [3.1] PROMPT LOADER (Dynamic Persona)                            │
│       │         ├── tutor.yaml → Student Role (Captain AI)                  │
│       │         ├── assistant.yaml → Teacher/Admin Role                     │
│       │         └── {{user_name}} replacement from Memory                   │
│       │                                                                      │
│       ├──▶ [3.2] BUILD MESSAGES                                             │
│       │         ├── SystemMessage (persona + tools + deep reasoning hints)  │
│       │         ├── Conversation History (last 10 messages)                 │
│       │         └── HumanMessage (current query)                            │
│       │                                                                      │
│       ▼                                                                      │
│   [4] MANUAL REACT LOOP (LangChain 1.x)                                     │
│       │                                                                      │
│       │   ┌─────────────────────────────────────────────────────────────┐   │
│       │   │  ITERATION 1..N (max 5)                                      │   │
│       │   │                                                              │   │
│       │   │  LLM (Gemini 2.5 Flash) with bind_tools()                   │   │
│       │   │       │                                                      │   │
│       │   │       ├── No tool_calls → Return final answer               │   │
│       │   │       │                                                      │   │
│       │   │       └── Has tool_calls → Execute tools:                   │   │
│       │   │                                                              │   │
│       │   │           [TOOL 1] tool_maritime_search(query)              │   │
│       │   │               └── RAGAgent.query() → Hybrid Search (pgvector + tsvector) │
│       │   │               └── Save sources to _last_retrieved_sources   │   │
│       │   │                                                              │   │
│       │   │           [TOOL 2] tool_save_user_info(key, value)          │   │
│       │   │               └── MemoryManager.check_and_save()            │   │
│       │   │               └── Deduplication: IGNORE/UPDATE/INSERT       │   │
│       │   │                                                              │   │
│       │   │           [TOOL 3] tool_get_user_info(key)                  │   │
│       │   │               └── SemanticMemory.retrieve_context()         │   │
│       │   │                                                              │   │
│       │   │       → Append ToolMessage → Continue loop                  │   │
│       │   └─────────────────────────────────────────────────────────────┘   │
│       │                                                                      │
│       ▼                                                                      │
│   [5] POST-PROCESSING (ChatService)                                         │
│       │                                                                      │
│       ├──▶ [5.1] SAVE AI RESPONSE                                           │
│       │         └── chat_history.save_message(session_id, "assistant", msg) │
│       │                                                                      │
│       ├──▶ [5.2] UPDATE SESSION STATE                                       │
│       │         ├── increment_response()                                    │
│       │         └── add_phrase() → Anti-repetition tracking                 │
│       │                                                                      │
│       ├──▶ [5.3] BACKGROUND TASKS (async)                                   │
│       │         ├── extract_and_store_insights() → Insight Engine v0.5      │
│       │         │   ├── InsightExtractor → Extract behavioral insights      │
│       │         │   ├── InsightValidator → Validate, detect duplicates      │
│       │         │   └── MemoryConsolidator → Consolidate if > 40 insights   │
│       │         │                                                            │
│       │         ├── store_interaction() → Legacy fact extraction            │
│       │         └── add_message_async() → Memory Summarizer                 │
│       │                                                                      │
│       ├──▶ [5.4] OUTPUT VALIDATION                                          │
│       │         └── guardrails.validate_output() → Safety check             │
│       │                                                                      │
│       ▼                                                                      │
│   [6] API RESPONSE                                                          │
│       │                                                                      │
│       └── InternalChatResponse                                              │
│           ├── message: AI response text                                     │
│           ├── agent_type: RAG/CHAT/TUTOR                                    │
│           ├── sources: List[Source] from tool_maritime_search               │
│           └── metadata: session_id, tools_used, iterations                  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Component Integration Verification

| Component | File | Status | Integration Point |
|-----------|------|--------|-------------------|
| **GuardianAgent** | `guardian_agent.py` | ✅ Active | ChatService Step 2.1 |
| **ConversationAnalyzer** | `conversation_analyzer.py` | ✅ Active | ChatService Step 2.4 |
| **SemanticMemory v0.5** | `semantic_memory.py` | ✅ Active | ChatService Step 2.3 |
| **InsightExtractor** | `insight_extractor.py` | ✅ Active | Background Task 5.3 |
| **InsightValidator** | `insight_validator.py` | ✅ Active | Background Task 5.3 |
| **MemoryConsolidator** | `memory_consolidator.py` | ✅ Active | Background Task 5.3 |
| **MemoryManager** | `memory_manager.py` | ✅ Active | tool_save_user_info |
| **PromptLoader** | `prompt_loader.py` | ✅ Active | UnifiedAgent Step 3.1 |
| **MemorySummarizer** | `memory_summarizer.py` | ✅ Active | Background Task 5.3 |
| **UnifiedAgent** | `unified_agent.py` | ✅ Active | Main processing engine |
| **RAGAgent** | `tools/rag_tool.py` | ✅ Active | tool_maritime_search |
| **Guardrails** | `guardrails.py` | ✅ Active | Fallback + Output validation |
| **RRFReranker** | `rrf_reranker.py` | ✅ Active | Hybrid Search |

### Data Flow Verification

```
User Message → Guardian (ALLOW) → Session → Memory Retrieval
                                              │
                                              ├── Insights (v0.5)
                                              ├── User Facts
                                              └── Chat History
                                              │
                                              ▼
                                    UnifiedAgent (ReAct)
                                              │
                                              ├── tool_maritime_search
                                              │   └── RAG → Hybrid Search (pgvector + tsvector)
                                              │
                                              ├── tool_save_user_info
                                              │   └── MemoryManager → Dedup
                                              │
                                              └── Final Response
                                              │
                                              ▼
                                    Post-Processing (Background)
                                              │
                                              ├── InsightExtractor
                                              ├── InsightValidator
                                              ├── MemoryConsolidator
                                              └── MemorySummarizer
```

### Kết luận Xác Minh

✅ **Tất cả components đã được tích hợp đúng cách:**
- GuardianAgent được gọi đầu tiên trong ChatService.process_message()
- ConversationAnalyzer được gọi trước khi xử lý với UnifiedAgent
- SemanticMemory v0.5 (Insight Engine) được sử dụng cho cả retrieve và store
- PromptLoader được sử dụng trong UnifiedAgent._build_messages()
- MemoryManager được sử dụng trong tool_save_user_info với deduplication
- Background tasks chạy sau khi response được gửi về user

✅ **Luồng xử lý hoàn chỉnh và nhất quán với thiết kế**

---

## Van de da biet va Cong viec tuong lai

### Da giai quyet (v0.9.7 - Database Schema Fix & SOTA Architecture)
- **Database Schema Fix**: Them cac columns con thieu vao production database
  - `chat_messages`: `is_blocked`, `block_reason`
  - `learning_profile`: `weak_areas`, `strong_areas`, `total_sessions`, `total_messages`
- **SemanticMemoryEngine.is_available()**: Them method kiem tra tinh kha dung
- **UUID/String Conversion**: Fix loi `_convert_user_id()` cho learning_profile_repository
- **SOTA Architecture Restored**: Xoa "force search" logic, su dung YAML persona config thay vi hardcode
- **Tool Calling via YAML**: Them section `tool_calling` vao tutor.yaml va assistant.yaml (CHI THI SO 29)
- **Alembic Migration 005**: Script migration cho schema changes

### Da giai quyet (v0.9.1 - Multimodal RAG Enhancement)
- **PyMuPDF Migration**: Thay the pdf2image+Poppler bang PyMuPDF - khong can external dependencies
- **Evidence Images in API**: Them `image_url` vao sources trong chat response
- **Cross-platform PDF Processing**: Hoat dong tren Windows/Linux/macOS khong can cai them gi
- **Dockerfile Optimization**: Loai bo poppler-utils, giam kich thuoc Docker image
- **Sparse Search Migration**: Migrate Sparse Search tu Neo4j sang PostgreSQL tsvector (Migration 004)
- **Semantic Chunking v2.7.0**: Maritime-specific patterns (Dieu, Khoan, Rule), Content Type Classification

### Da giai quyet (v0.8.5 - Insight Memory Engine)
- **Behavioral Insights**: Chuyen tu "Atomic Facts" sang "Behavioral Insights" - AI hieu user hon
- **5 Insight Categories**: learning_style, knowledge_gap, goal_evolution, habit, preference
- **InsightExtractor**: Trich xuat insights tu message voi LLM prompt chuyen biet
- **InsightValidator**: Validate content, detect duplicates (merge) va contradictions (update)
- **MemoryConsolidator**: LLM-based consolidation khi dat 40/50 insights, target 30 core items
- **Category-Prioritized Retrieval**: Uu tien knowledge_gap va learning_style khi retrieve
- **Evolution Notes**: Theo doi lich su thay doi cua moi insight
- **Full Integration**: Da tich hop vao ChatService - retrieve khi xu ly, store sau response
- **Database Schema v0.5**: 4 columns moi (insight_category, sub_topic, last_accessed, evolution_notes) + 3 indexes

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

### Da giai quyet (v2.7.1 - 09/12/2024)
- **PyMuPDF Migration**: Chuyen tu pdf2image+Poppler sang PyMuPDF (fitz) - khong can external dependencies
- **Cross-Platform PDF Processing**: PyMuPDF hoat dong tren Windows/Linux/macOS ma khong can cai dat them
- **Supabase Storage RLS Fix**: Cau hinh Storage Policies cho phep upload images
- **Evidence Images Pipeline**: image_url duoc luu vao database va tra ve trong API response
- **Verified Integration**: Test xac nhan 62 records co image_url, search tra ve image URLs

### Dang thuc hien
- **Full Multimodal Re-ingestion**: Re-ingest tat ca PDF voi multimodal pipeline de co evidence images day du
- **Production Deployment**: Deploy code moi len Render va chay full re-ingestion

### Du kien
- **Learning Graph Integration**: Tich hop Neo4j cho Learning Graph (LMS integration)
- **Evidence Images UI**: Hien thi anh trang tai lieu trong frontend
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
