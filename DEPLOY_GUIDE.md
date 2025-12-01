# 🚀 HƯỚNG DẪN DEPLOY MARITIME AI CHATBOT LÊN RENDER

**Theo CHỈ THỊ KỸ THUẬT SỐ 04 của Cố vấn Kiến trúc**

---

## 📋 TỔNG QUAN

Kiến trúc **Cloud Native - Stateless Deployment**:
- **FastAPI Server**: Deploy lên Render (Free)
- **PostgreSQL**: Supabase (Free)
- **Neo4j**: Neo4j Aura (Free)

---

## ✅ BƯỚC 1: CHUẨN BỊ CLOUD SERVICES (ĐÃ HOÀN THÀNH)

### 1.1 Neo4j Aura
```
NEO4J_URI=neo4j+s://7f18fe6d.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=1c2E682imyPHN2MSuPjrrGGSPqI8ENI7Ff_VQc_ns5U
```

### 1.2 Supabase
```
SUPABASE_URL=https://fiaksvcbqjwkmgkbpgxw.supabase.co
SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

**⚠️ CẦN LÀM THÊM:**
1. Vào Supabase Dashboard -> Project Settings -> Database
2. Copy **Connection String** (URI format)
3. Vào SQL Editor chạy: `CREATE EXTENSION IF NOT EXISTS vector;`

---

## ✅ BƯỚC 2: CẤU HÌNH CODE (ĐÃ HOÀN THÀNH)

Các file đã được cập nhật:
- ✅ `requirements.txt` - Thêm gunicorn
- ✅ `render.yaml` - Cấu hình Render
- ✅ `app/core/config.py` - Hỗ trợ DATABASE_URL và NEO4J_USERNAME
- ✅ `app/repositories/neo4j_knowledge_repository.py` - Hỗ trợ Neo4j Aura
- ✅ `app/repositories/chat_history_repository.py` - Hỗ trợ Supabase

---

## 🔄 BƯỚC 3: PUSH CODE LÊN GITHUB

```bash
cd maritime-ai-service
git add .
git commit -m "feat: Add cloud deployment support (Render + Supabase + Neo4j Aura)"
git push origin main
```

**GitHub Repo:** https://github.com/meiiie/LMS_AI.git

---

## 🌐 BƯỚC 4: DEPLOY LÊN RENDER

### 4.1 Tạo Web Service
1. Vào [Render Dashboard](https://dashboard.render.com/)
2. Click **New +** -> **Web Service**
3. Kết nối GitHub repo: `meiiie/LMS_AI`
4. Chọn branch: `main`

### 4.2 Cấu hình Build
- **Name:** `maritime-ai-chatbot`
- **Region:** Singapore (gần Việt Nam)
- **Branch:** `main`
- **Root Directory:** `maritime-ai-service`
- **Runtime:** Python 3
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`

### 4.3 Environment Variables (QUAN TRỌNG!)

Vào tab **Environment** và thêm các biến sau:

| Key | Value |
|-----|-------|
| `PYTHON_VERSION` | `3.11` |
| `NEO4J_URI` | `neo4j+s://7f18fe6d.databases.neo4j.io` |
| `NEO4J_USERNAME` | `neo4j` |
| `NEO4J_PASSWORD` | `1c2E682imyPHN2MSuPjrrGGSPqI8ENI7Ff_VQc_ns5U` |
| `DATABASE_URL` | `postgresql://postgres:[YOUR-PASSWORD]@db.fiaksvcbqjwkmgkbpgxw.supabase.co:5432/postgres` |
| `OPENAI_API_KEY` | `sk-or-v1-your-openrouter-key` |
| `OPENAI_BASE_URL` | `https://openrouter.ai/api/v1` |
| `OPENAI_MODEL` | `x-ai/grok-4.1-fast:free` |
| `LMS_API_KEY` | `secret_key_cho_team_lms` |
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |

### 4.4 Deploy
Click **Create Web Service** và đợi deploy hoàn tất.

---

## ✅ BƯỚC 5: KIỂM TRA & BÀN GIAO

### 5.1 Kiểm tra Health
```bash
curl https://maritime-ai-chatbot.onrender.com/health
```

Expected response:
```json
{"status": "ok", "database": "connected"}
```

### 5.2 Kiểm tra Swagger UI
Mở browser: `https://maritime-ai-chatbot.onrender.com/docs`

### 5.3 Test API
```bash
curl -X POST https://maritime-ai-chatbot.onrender.com/api/v1/chat \
  -H "X-API-Key: secret_key_cho_team_lms" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "student_123",
    "message": "Quy tắc 5 COLREGs là gì?",
    "role": "student"
  }'
```

---

## 📝 BÀN GIAO CHO TEAM LMS

Gửi cho team LMS:

```
🚢 MARITIME AI CHATBOT - PRODUCTION API

Base URL: https://maritime-ai-chatbot.onrender.com

Endpoints:
- POST /api/v1/chat - Chat completion
- GET /health - Health check
- GET /docs - Swagger UI

Authentication:
- Header: X-API-Key
- Value: secret_key_cho_team_lms

Example Request:
{
  "user_id": "student_123",
  "message": "Quy tắc 5 COLREGs là gì?",
  "role": "student"
}
```

---

## 🔧 TROUBLESHOOTING

### Lỗi "Connection refused" với Neo4j
- Đợi 60 giây sau khi tạo Neo4j Aura instance
- Kiểm tra NEO4J_URI phải có prefix `neo4j+s://` (không phải `bolt://`)

### Lỗi "Database connection failed"
- Kiểm tra DATABASE_URL format đúng
- Đảm bảo đã chạy `CREATE EXTENSION IF NOT EXISTS vector;` trên Supabase

### Lỗi "Rate limit exceeded"
- Render Free có giới hạn, nếu cần scale thì upgrade plan

---

## 📊 THỐNG KÊ CHI PHÍ

| Service | Plan | Cost |
|---------|------|------|
| Render | Free | $0/month |
| Neo4j Aura | Free | $0/month (200k nodes) |
| Supabase | Free | $0/month (500MB) |
| OpenRouter | Free | $0 (Grok free tier) |
| **TOTAL** | | **$0/month** |

---

**Trạng thái: SẴN SÀNG DEPLOY ✅**
