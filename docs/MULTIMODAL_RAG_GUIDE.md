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
│ 1. RASTERIZE    │  PyMuPDF (150 DPI)
│ PDF → Images    │  No external deps (replaces pdf2image+Poppler)
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

## 6. Semantic Chunking

### Tổng quan

Semantic Chunking chia nhỏ nội dung trang thành các chunks có ngữ nghĩa, thay vì 1 page = 1 chunk như trước.

**Lợi ích:**
- Tìm kiếm chính xác hơn (focused chunks)
- Trích dẫn cụ thể hơn (Điều, Khoản, Điểm)
- Confidence scoring cho quality filtering

### Content Types

| Type | Mô tả | Ví dụ |
|------|-------|-------|
| `text` | Văn bản thông thường | Đoạn văn, mô tả |
| `heading` | Tiêu đề, điều khoản | Điều 15, Khoản 2, Rule 19 |
| `table` | Bảng biểu | Bảng tốc độ, bảng đèn hiệu |
| `diagram_reference` | Tham chiếu hình vẽ | Hình 1, Sơ đồ 2 |
| `formula` | Công thức | Tính toán khoảng cách |

### Document Hierarchy

Hệ thống tự động extract cấu trúc văn bản pháp luật hàng hải:

```json
{
  "section_hierarchy": {
    "article": "15",      // Điều 15
    "clause": "2",        // Khoản 2
    "point": "a",         // Điểm a
    "rule": "19"          // Rule 19 (COLREGs)
  }
}
```

### Confidence Scoring

| Điều kiện | Score |
|-----------|-------|
| Chunk 200-600 chars | 1.0 |
| Chunk < 50 chars | 0.6 |
| Chunk > 1000 chars | 0.7 |
| Structured content (heading, table) | +20% boost |

### Configuration

```python
# app/core/config.py
chunk_size: int = 800        # Target chunk size
chunk_overlap: int = 100     # Overlap between chunks
min_chunk_size: int = 50     # Minimum chunk size
dpi_optimized: int = 100     # DPI for PDF conversion
```

### Re-ingestion với Chunking

```bash
# Re-ingest với semantic chunking
python scripts/reingest_with_chunking.py \
    --pdf data/COLREGs.pdf \
    --document-id colregs_2024 \
    --truncate-first

# Kiểm tra kết quả
SELECT content_type, COUNT(*) 
FROM knowledge_embeddings 
WHERE document_id = 'colregs_2024' 
GROUP BY content_type;
```

### Search với Content Type Filter

```python
# Chỉ tìm trong headings (điều khoản)
results = await dense_repo.search(
    query_embedding=embedding,
    limit=10,
    content_types=["heading"],
    min_confidence=0.8
)
```

---

## 7. Database Schema

### Migration

```sql
-- Migration 002: Multimodal columns
ALTER TABLE knowledge_embeddings
ADD COLUMN image_url TEXT,
ADD COLUMN page_number INTEGER,
ADD COLUMN chunk_index INTEGER DEFAULT 0,
ADD COLUMN document_id VARCHAR(255);

-- Migration 003: Semantic chunking columns
ALTER TABLE knowledge_embeddings
ADD COLUMN content_type VARCHAR(50) DEFAULT 'text',
ADD COLUMN confidence_score FLOAT DEFAULT 1.0;

-- Indexes
CREATE INDEX idx_knowledge_embeddings_page ON knowledge_embeddings(page_number);
CREATE INDEX idx_knowledge_embeddings_document ON knowledge_embeddings(document_id, page_number);
CREATE INDEX idx_knowledge_chunks_ordering ON knowledge_embeddings(document_id, page_number, chunk_index);
CREATE INDEX idx_knowledge_chunks_content_type ON knowledge_embeddings(content_type);
CREATE INDEX idx_knowledge_chunks_confidence ON knowledge_embeddings(confidence_score);
```

### Chạy Migration

```bash
cd maritime-ai-service
alembic upgrade head
```

### Schema hiện tại

| Column | Type | Description |
|--------|------|-------------|
| id | UUID | Primary key |
| node_id | VARCHAR(255) | Unique identifier |
| content | TEXT | Chunk content |
| embedding | VECTOR(768) | Gemini embedding |
| document_id | VARCHAR(255) | Parent document |
| page_number | INTEGER | Page number |
| chunk_index | INTEGER | Chunk index within page |
| image_url | TEXT | Supabase image URL |
| content_type | VARCHAR(50) | text/table/heading/etc |
| confidence_score | FLOAT | Quality score 0.0-1.0 |
| metadata | JSONB | Additional metadata |

---

## 8. Troubleshooting

### Lỗi PDF Processing

**Note**: Từ v2.7.1, hệ thống sử dụng **PyMuPDF** thay vì pdf2image+Poppler.
PyMuPDF không cần external dependencies, hoạt động trên mọi platform.

Nếu gặp lỗi với PyMuPDF:
```
Error: No module named 'fitz'
```

**Giải pháp:**
```bash
pip install pymupdf
```

**Legacy (pdf2image - không còn cần thiết):**
Nếu vẫn muốn dùng pdf2image (fallback):
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

## 9. Performance Tips

### Batch Processing
- Xử lý PDF theo batch 10 pages để tránh memory overflow
- Resume capability cho phép tiếp tục từ page cuối nếu bị gián đoạn

### Caching
- Embeddings được cache trong database
- Image URLs là public, có thể cache ở CDN

### Rate Limiting
- Vision API: 10 requests/minute
- Supabase Storage: Theo plan (Free tier: 1GB storage)

### Semantic Chunking Performance
- Chunk size 800 chars tối ưu cho maritime documents
- Overlap 100 chars đảm bảo context continuity
- Confidence filtering (>0.8) giảm noise trong search results

---

*CHỈ THỊ KỸ THUẬT SỐ 26 + Semantic Chunking - Version 2.0*
*Last Updated: December 2025*
