# Multimodal RAG Guide

## CHỈ THỊ KỸ THUẬT SỐ 26: Vision-based Document Understanding

Hướng dẫn chi tiết về tính năng Multimodal RAG - cho phép AI "nhìn" thấy trang tài liệu gốc và hiển thị Evidence Images trong câu trả lời.

---

## 1. Tổng quan

### Vấn đề cũ (Text-based RAG)
- `pypdf` làm mất cấu trúc bảng biểu
- Không đọc được sơ đồ đèn hiệu
- Không hiểu hình vẽ tàu bè trong COLREGs
- AI trả lời thiếu chính xác về visual content

### Giải pháp mới (Vision-based RAG)
- AI "nhìn" thấy trang tài liệu như con người
- Bảng biểu được convert sang Markdown Table
- Sơ đồ đèn hiệu được mô tả chi tiết (màu sắc, vị trí)
- Evidence Image hiển thị cùng câu trả lời

---

## 2. Kiến trúc Hybrid Infrastructure

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         HYBRID INFRASTRUCTURE                                │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│   ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐ │
│   │   NEON DATABASE     │  │  SUPABASE STORAGE   │  │   GOOGLE GEMINI     │ │
│   │   (Serverless PG)   │  │  (Object Storage)   │  │   (Vision Model)    │ │
│   │                     │  │                     │  │                     │ │
│   │  • Metadata         │  │  • Page Images      │  │  • Image → Text     │ │
│   │  • Text Description │  │  • JPG/PNG files    │  │  • Table → Markdown │ │
│   │  • Vectors (768d)   │  │  • Public URLs      │  │  • Diagram → Desc   │ │
│   │  • image_url        │  │  • Bucket:          │  │  • Embeddings       │ │
│   │  • page_number      │  │    maritime-docs    │  │                     │ │
│   └─────────────────────┘  └─────────────────────┘  └─────────────────────┘ │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Cấu hình

### Environment Variables

```env
# Supabase Storage
SUPABASE_URL=https://fiaksvcbqjwkmgkbpgxw.supabase.co
SUPABASE_KEY=your-supabase-anon-key
SUPABASE_STORAGE_BUCKET=maritime-docs

# Google Gemini (Vision Model)
GOOGLE_API_KEY=your-google-api-key
GOOGLE_MODEL=gemini-2.5-flash
```

### Supabase Setup

1. Vào Supabase Dashboard → Storage
2. Tạo bucket `maritime-docs`
3. Set bucket policy: Public (để frontend có thể hiển thị ảnh)
4. Cấu hình CORS nếu cần

---

## 4. Ingestion Pipeline

### Quy trình 4 bước

```
PDF Document
     │
     ▼
┌─────────────────┐
│ 1. RASTERIZE    │  pdf2image (300 DPI)
│ PDF → Images    │  Requires: poppler-utils
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 2. UPLOAD       │  Supabase Storage
│ → public_url    │  Path: {doc_id}/page_{n}.jpg
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 3. VISION       │  Gemini 2.5 Flash
│ Image → Text    │  Maritime extraction prompt
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ 4. INDEX        │  Neon pgvector
│ Text + image_url│  768-dim embeddings
└─────────────────┘
```

### Chạy Ingestion

```bash
# 1. Truncate dữ liệu cũ (backup trước)
python scripts/truncate_old_knowledge.py --backup

# 2. Re-ingest với Multimodal pipeline
python scripts/reingest_multimodal.py \
    --pdf data/COLREGs.pdf \
    --document-id colregs_2024
```

### API Endpoint

```bash
curl -X POST http://localhost:8000/api/v1/knowledge/ingest-multimodal \
  -H "Content-Type: multipart/form-data" \
  -F "file=@COLREGs.pdf" \
  -F "document_id=colregs_2024" \
  -F "role=admin"
```

---

## 5. Evidence Images trong Response

### Response Format

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
    "suggested_questions": [...],
    "evidence_images": [
      {
        "url": "https://xyz.supabase.co/storage/v1/object/public/maritime-docs/colregs_2024/page_15.jpg",
        "page_number": 15,
        "document_id": "colregs_2024"
      }
    ]
  }
}
```

### Frontend Integration

```typescript
// Angular component
interface EvidenceImage {
  url: string;
  page_number: number;
  document_id: string;
}

// Display evidence images
<div *ngFor="let img of response.data.evidence_images">
  <img [src]="img.url" [alt]="'Page ' + img.page_number">
  <span>Trang {{ img.page_number }}</span>
</div>
```

---

## 6. Database Schema

### Migration

```sql
-- Thêm cột cho Multimodal RAG
ALTER TABLE knowledge_embeddings
ADD COLUMN image_url TEXT,
ADD COLUMN page_number INTEGER,
ADD COLUMN document_id VARCHAR(255);

-- Indexes
CREATE INDEX idx_knowledge_embeddings_page ON knowledge_embeddings(page_number);
CREATE INDEX idx_knowledge_embeddings_document ON knowledge_embeddings(document_id, page_number);
```

### Chạy Migration

```bash
cd maritime-ai-service
alembic upgrade head
```

---

## 7. Troubleshooting

### Lỗi pdf2image

```
Error: Unable to get page count. Is poppler installed?
```

**Giải pháp:**
- Windows: Cài Poppler và thêm vào PATH
- Linux/Docker: `apt-get install -y poppler-utils`
- macOS: `brew install poppler`

### Lỗi Supabase Upload

```
Error: Upload failed: Bucket not found
```

**Giải pháp:**
1. Kiểm tra bucket `maritime-docs` đã tạo chưa
2. Kiểm tra SUPABASE_URL và SUPABASE_KEY
3. Kiểm tra bucket policy (Public)

### Lỗi Vision Extraction

```
Error: Rate limit exceeded
```

**Giải pháp:**
- VisionExtractor có rate limiting 10 req/min
- Chờ và retry tự động
- Hoặc tăng quota Google API

### Evidence Images không hiển thị

1. Kiểm tra image_url trong database:
   ```sql
   SELECT node_id, image_url FROM knowledge_embeddings WHERE image_url IS NOT NULL LIMIT 5;
   ```
2. Kiểm tra URL có accessible không (mở trong browser)
3. Kiểm tra CORS settings của Supabase bucket

---

## 8. Performance Tips

### Batch Processing
- Xử lý PDF theo batch 10 pages để tránh memory overflow
- Resume capability cho phép tiếp tục từ page cuối nếu bị gián đoạn

### Caching
- Embeddings được cache trong database
- Image URLs là public, có thể cache ở CDN

### Rate Limiting
- Vision API: 10 requests/minute
- Supabase Storage: Theo plan (Free tier: 1GB storage)

---

*CHỈ THỊ KỸ THUẬT SỐ 26 - Version 1.0*
*Last Updated: December 2025*
