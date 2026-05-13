# Knowledge Base Ingestion — Production Checklist

## Maritime PDFs to Ingest

| Document | Pages | Priority |
|----------|-------|----------|
| COLREGs (Quy tắc phòng ngừa va chạm) | ~50 | HIGH |
| SOLAS (Công ước an toàn sinh mạng) | ~400 | HIGH |
| MARPOL (Công ước chống ô nhiễm biển) | ~200 | HIGH |
| STCW (Tiêu chuẩn huấn luyện thuyền viên) | ~150 | MEDIUM |
| ISM Code (Quản lý an toàn quốc tế) | ~30 | MEDIUM |

## Steps

1. Upload PDFs to `/opt/wiii/data/pdfs/` on server
2. Verify app liveness: `curl localhost:8000/api/v1/health/live`
3. Run: `API_KEY=your-key bash scripts/deploy/ingest-production.sh --dry-run`
4. Verify file list looks correct
5. Run: `API_KEY=your-key bash scripts/deploy/ingest-production.sh`
6. Check stats: `curl localhost:8000/api/v1/knowledge/stats -H "X-API-Key: your-key"`
7. Test RAG: Ask a maritime question → should cite ingested documents

## Fast Seed For Empty KB

If production stats show `total_chunks=0`, seed the small COLREGs teaching
corpus first so source-backed RAG is not silently empty while larger PDFs are
being prepared:

```bash
cd maritime-ai-service
WIII_BASE_URL=https://wiii.holilihu.online \
WIII_ADMIN_JWT=<platform-admin-jwt> \
python scripts/seed_maritime_text_kb.py
```

The seed is idempotent. It writes `document_id=maritime-colregs-teaching-seed-v1`
through `POST /api/v1/knowledge/ingest-text`, then prints before/after stats
without printing credentials. Use `--dry-run` to inspect the target and payload
size without writing.

## Alternative: Admin UI Upload

The Org Admin panel has drag-drop PDF upload at:
`wiii.holilihu.online` → Admin → Knowledge → Upload Documents

This uses the same API endpoint (`/knowledge/ingest-multimodal`) under the hood.

## Embedding Model

- **Production model**: Gemini `models/gemini-embedding-001` (768 dimensions)
- **Benchmark candidate**: Gemini `gemini-embedding-2-preview` (evaluate before any migration or reindex)
- **Chunking**: Recursive, 800 chars, 100 overlap
- **Index**: pgvector HNSW (`m=16, ef_construction=64`)
- **Cost**: FREE (Gemini embedding API)
