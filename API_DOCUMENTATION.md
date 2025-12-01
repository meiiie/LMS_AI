# 📚 MARITIME AI CHATBOT - API DOCUMENTATION
## Version 0.2.0 | Memory & Personalization

---

## Base URL
```
Production: https://maritime-ai-chatbot.onrender.com
```

## Authentication
All API requests require an API key in the header:
```
X-API-Key: secret_key_cho_team_lms
```

---

## Endpoints

### 1. Chat Completion
Send a message and receive AI response with memory context.

**Endpoint:** `POST /api/v1/chat`

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

**Response (200 OK):**
```json
{
  "status": "success",
  "data": {
    "answer": "string (markdown formatted)",
    "sources": [
      {
        "title": "string",
        "content": "string"
      }
    ],
    "suggested_questions": ["string"]
  },
  "metadata": {
    "processing_time": "number (seconds)",
    "model": "string",
    "agent_type": "string"
  }
}
```

---

### 2. Health Check
Check API and component status.

**Endpoint:** `GET /api/v1/health`

**Response (200 OK):**
```json
{
  "status": "healthy",
  "components": {
    "api": "healthy",
    "memory": "healthy | degraded",
    "knowledge_graph": "healthy | degraded"
  },
  "version": "0.2.0"
}
```

---

### 3. Root Health
Simple health check.

**Endpoint:** `GET /health`

**Response (200 OK):**
```json
{
  "status": "healthy"
}
```

---

## Error Responses

### 400 Bad Request
```json
{
  "error": "validation_error",
  "message": "Request validation failed",
  "details": [{"field": "string", "message": "string", "code": "string"}]
}
```

### 401 Unauthorized
```json
{
  "error": "unauthorized",
  "message": "Invalid or missing API key"
}
```

### 429 Rate Limited
```json
{
  "error": "rate_limited",
  "message": "Rate limit exceeded",
  "retry_after": 60
}
```

### 500 Internal Server Error
```json
{
  "error": "internal_error",
  "message": "An unexpected error occurred"
}
```

---

## Rate Limits
- **Per API Key:** 100 requests/minute
- **Per User:** 30 requests/minute

---

## Memory Behavior

| Feature | Description |
|---------|-------------|
| History Window | 10 most recent messages |
| User Recognition | Remembers user name if introduced |
| Session Tracking | Automatic per user_id |
| Profile Tracking | Weak/strong areas, message count |

---

## OpenAPI Spec
Interactive documentation available at:
```
https://maritime-ai-chatbot.onrender.com/docs
```

---

**Last Updated:** 01/12/2025
