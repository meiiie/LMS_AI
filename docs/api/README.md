# Maritime AI Service - API Documentation

> **Version:** 1.0.0  
> **Base URL:** `https://your-domain.com/api/v1`  
> **Last Updated:** 2025-12-14

---

## Table of Contents

1. [Overview](#overview)
2. [Authentication](#authentication)
3. [Endpoints](#endpoints)
4. [Response Formats](#response-formats)
5. [Error Handling](#error-handling)
6. [Rate Limiting](#rate-limiting)
7. [Integration Examples](#integration-examples)

---

## Overview

The Maritime AI Service provides a conversational AI tutor for maritime education. It supports:

- **Agentic RAG**: Intelligent knowledge retrieval with citations
- **Semantic Memory**: Remembers user facts and learning preferences
- **Multimodal Documents**: PDF ingestion with image extraction
- **Streaming Responses**: Real-time SSE for chat

### Architecture

```
LMS Backend → Maritime AI Service → Response
     ↓              ↓                  ↓
  API Key       AI Processing      Citations + Sources
```

---

## Authentication

All API requests require authentication via headers:

| Header | Required | Description |
|--------|----------|-------------|
| `X-API-Key` | ✅ Yes | Server API key (contact AI team) |
| `X-User-ID` | ✅ Yes | Unique user identifier from LMS |
| `X-Role` | ⚠️ Recommended | `student`, `teacher`, or `admin` |
| `X-Session-ID` | Optional | Thread/session ID for continuity |

### Example Headers

```http
POST /api/v1/chat HTTP/1.1
Host: maritime-ai.example.com
Content-Type: application/json
X-API-Key: sk_live_abc123...
X-User-ID: user_12345
X-Role: student
```

### Role-Based Behavior

| Role | AI Persona | Language Style |
|------|------------|----------------|
| `student` | Tutor (Gia sư) | Encouraging, detailed explanations |
| `teacher` | Assistant (Trợ lý) | Professional, concise |
| `admin` | Assistant | Professional, full access |

---

## Endpoints

### Chat

#### POST /api/v1/chat

Main chat endpoint for synchronous responses.

**Request:**

```json
{
  "message": "Giải thích Rule 15 COLREGs",
  "user_id": "user_12345",
  "role": "student",
  "thread_id": "optional-uuid-for-conversation-continuity",
  "user_context": {
    "display_name": "Nguyễn Văn A",
    "current_module_id": "module_123",
    "current_course_name": "Luật Hàng hải Quốc tế",
    "language": "vi"
  }
}
```

**Response:**

```json
{
  "response_id": "uuid",
  "message": "**Rule 15 - Tình huống Cắt hướng**\n\nKhi hai tàu cắt hướng nhau...",
  "agent_type": "rag",
  "sources": [
    {
      "node_id": "colregs_rule15_001",
      "title": "Rule 15 - Crossing Situation",
      "content_snippet": "When two power-driven vessels are crossing...",
      "page_number": 12,
      "document_id": "colregs_2024",
      "image_url": "https://storage.supabase.co/...",
      "bounding_boxes": [
        {"x": 10, "y": 20, "width": 80, "height": 15}
      ]
    }
  ],
  "metadata": {
    "session_id": "uuid",
    "user_name": "Nguyễn Văn A",
    "unified_agent": true,
    "tools_used": ["tool_maritime_search"]
  }
}
```

---

#### POST /api/v1/chat/stream

Streaming endpoint using Server-Sent Events (SSE).

**Request:** Same as `/chat`

**Response (SSE Events):**

```
event: thinking
data: {"content": "Đang phân tích câu hỏi về Rule 15..."}

event: answer
data: {"content": "**Rule 15 - Tình huống Cắt hướng**\n\n"}

event: answer
data: {"content": "Khi hai tàu cắt hướng nhau sao cho có nguy cơ va chạm..."}

event: sources
data: {"sources": [...]}

event: metadata
data: {"analytics": {"topics_accessed": ["colregs"], "confidence_score": 0.92}}

event: done
data: {}
```

---

### History

#### GET /api/v1/chat/history/{user_id}

Get conversation history for a user.

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 50 | Max messages to return |
| `thread_id` | string | null | Filter by specific thread |

**Response:**

```json
{
  "user_id": "user_12345",
  "messages": [
    {
      "role": "user",
      "content": "Rule 15 là gì?",
      "timestamp": "2025-12-14T10:30:00Z"
    },
    {
      "role": "assistant", 
      "content": "Rule 15 quy định về...",
      "timestamp": "2025-12-14T10:30:05Z"
    }
  ],
  "total_count": 2
}
```

---

#### DELETE /api/v1/chat/history/{user_id}

Clear history for a user. **Admin only.**

---

### Memories

#### GET /api/v1/memories/{user_id}

Get stored facts about a user.

**Response:**

```json
{
  "user_id": "user_12345",
  "facts": [
    {
      "id": "fact_001",
      "content": "Tên: Nguyễn Văn A",
      "fact_type": "name",
      "confidence": 0.95,
      "created_at": "2025-12-14T10:00:00Z"
    },
    {
      "id": "fact_002",
      "content": "Sinh viên năm 3, chuyên ngành Điều khiển tàu",
      "fact_type": "education",
      "confidence": 0.90
    }
  ]
}
```

---

#### DELETE /api/v1/memories/{user_id}/{memory_id}

Delete a specific memory. **User can delete own memories.**

---

### Insights

#### GET /api/v1/insights/{user_id}

Get behavioral insights about a user's learning.

**Response:**

```json
{
  "user_id": "user_12345",
  "insights": [
    {
      "category": "knowledge_gap",
      "content": "User frequently confuses Rule 13 and Rule 15",
      "confidence": 0.85
    },
    {
      "category": "learning_style",
      "content": "Prefers examples over theoretical explanations",
      "confidence": 0.80
    }
  ]
}
```

**Insight Categories:**
- `knowledge_gap`: Topics user struggles with
- `learning_style`: How user prefers to learn
- `goal_evolution`: User's changing learning goals
- `habit`: Consistent user behaviors
- `preference`: User preferences

---

### Documents (Admin)

#### POST /api/v1/admin/documents

Upload a PDF document. **Admin only.**

**Request:** `multipart/form-data`

| Field | Type | Description |
|-------|------|-------------|
| `file` | file | PDF file |
| `title` | string | Document title |
| `category` | string | `colregs`, `solas`, `marpol`, etc. |

**Response:**

```json
{
  "document_id": "doc_12345",
  "status": "processing",
  "message": "Document queued for ingestion"
}
```

---

#### GET /api/v1/admin/documents

List all documents.

---

#### GET /api/v1/admin/documents/{document_id}

Get ingestion status.

**Response:**

```json
{
  "document_id": "doc_12345",
  "title": "COLREGs 2024",
  "status": "completed",
  "pages_processed": 45,
  "chunks_created": 128,
  "created_at": "2025-12-14T09:00:00Z",
  "completed_at": "2025-12-14T09:05:00Z"
}
```

---

#### DELETE /api/v1/admin/documents/{document_id}

Delete a document. **Admin only.**

---

### Sources

#### GET /api/v1/sources/{node_id}

Get detailed source information with bounding boxes for PDF highlighting.

**Response:**

```json
{
  "node_id": "colregs_rule15_001",
  "title": "Rule 15 - Crossing Situation",
  "content": "Full text of the source...",
  "document_id": "colregs_2024",
  "page_number": 12,
  "image_url": "https://storage.supabase.co/...",
  "bounding_boxes": [
    {
      "x": 10.5,
      "y": 20.3,
      "width": 80.0,
      "height": 15.2
    }
  ]
}
```

**Bounding Box Format:**
- Coordinates are **percentages** (0-100) of page dimensions
- Use for highlighting in PDF viewer

---

### Health

#### GET /api/v1/health

Basic health check.

```json
{"status": "healthy", "timestamp": "2025-12-14T10:00:00Z"}
```

---

#### GET /api/v1/health/deep

Detailed health check with component status.

```json
{
  "status": "healthy",
  "components": {
    "database": "healthy",
    "neo4j": "healthy",
    "semantic_memory": "healthy",
    "unified_agent": "healthy"
  }
}
```

---

## Response Formats

### Success Response

```json
{
  "response_id": "uuid",
  "message": "AI response text",
  "agent_type": "rag|chat|tutor",
  "sources": [...],
  "metadata": {...}
}
```

### Error Response

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Message cannot be empty",
    "details": {...}
  }
}
```

---

## Error Handling

| HTTP Status | Code | Description |
|-------------|------|-------------|
| 400 | `VALIDATION_ERROR` | Invalid request body |
| 401 | `UNAUTHORIZED` | Missing or invalid API key |
| 403 | `FORBIDDEN` | Insufficient permissions |
| 404 | `NOT_FOUND` | Resource not found |
| 429 | `RATE_LIMITED` | Too many requests |
| 500 | `INTERNAL_ERROR` | Server error |

---

## Rate Limiting

| Endpoint | Limit |
|----------|-------|
| `/chat` | 30 requests/minute per user |
| `/chat/stream` | 30 requests/minute per user |
| `/admin/*` | 60 requests/minute |

Headers returned:
- `X-RateLimit-Limit`: Max requests
- `X-RateLimit-Remaining`: Requests left
- `X-RateLimit-Reset`: Reset timestamp

---

## Integration Examples

### Angular/TypeScript

```typescript
// ai-chat.service.ts
import { Injectable } from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Observable } from 'rxjs';

interface ChatRequest {
  message: string;
  user_id: string;
  role: 'student' | 'teacher' | 'admin';
  thread_id?: string;
}

interface ChatResponse {
  response_id: string;
  message: string;
  sources: Source[];
}

@Injectable({ providedIn: 'root' })
export class AIChatService {
  private baseUrl = 'https://maritime-ai.example.com/api/v1';
  
  constructor(private http: HttpClient) {}
  
  sendMessage(request: ChatRequest): Observable<ChatResponse> {
    const headers = new HttpHeaders({
      'X-API-Key': environment.aiApiKey,
      'X-User-ID': request.user_id,
      'X-Role': request.role
    });
    
    return this.http.post<ChatResponse>(
      `${this.baseUrl}/chat`,
      request,
      { headers }
    );
  }
}
```

### Python

```python
import requests

class MaritimeAIClient:
    def __init__(self, api_key: str, base_url: str = "https://maritime-ai.example.com/api/v1"):
        self.base_url = base_url
        self.headers = {"X-API-Key": api_key}
    
    def chat(self, message: str, user_id: str, role: str = "student") -> dict:
        self.headers.update({
            "X-User-ID": user_id,
            "X-Role": role
        })
        
        response = requests.post(
            f"{self.base_url}/chat",
            json={"message": message, "user_id": user_id, "role": role},
            headers=self.headers
        )
        return response.json()

# Usage
client = MaritimeAIClient("sk_live_abc123...")
response = client.chat("Rule 15 là gì?", "user_123")
print(response["message"])
```

### cURL

```bash
curl -X POST https://maritime-ai.example.com/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "X-API-Key: sk_live_abc123..." \
  -H "X-User-ID: user_123" \
  -H "X-Role: student" \
  -d '{
    "message": "Giải thích Rule 15 COLREGs",
    "user_id": "user_123",
    "role": "student"
  }'
```

---

## Contact

For API keys and support, contact the AI Team.

---

*Documentation generated 2025-12-14*
