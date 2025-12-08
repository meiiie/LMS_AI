"""
Local Ingestion Script with Semantic Chunking (No Supabase)
Ingests PDF directly using Gemini Vision without uploading to Supabase.

Run: python scripts/ingest_local_chunking.py --pdf data/VanBanGoc_95.2015.QH13.P1.pdf --document-id luat_hang_hai_2015

Features: semantic-chunking
"""
import asyncio
import argparse
import base64
import io
import json
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import os

load_dotenv()

# Add parent to path for imports
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from pdf2image import convert_from_path
import google.generativeai as genai
from PIL import Image
import asyncpg

from app.services.chunking_service import SemanticChunker
from app.engine.gemini_embedding import GeminiOptimizedEmbeddings


def get_asyncpg_url() -> str:
    """Convert SQLAlchemy URL to asyncpg URL"""
    url = os.getenv("DATABASE_URL", "")
    # Remove +asyncpg suffix if present
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    return url


async def extract_text_with_gemini(image: Image.Image, page_num: int) -> str:
    """Extract text from image using Gemini Vision"""
    # Convert PIL Image to bytes
    img_byte_arr = io.BytesIO()
    image.save(img_byte_arr, format='JPEG', quality=85)
    img_bytes = img_byte_arr.getvalue()
    
    # Configure Gemini
    genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    model = genai.GenerativeModel("gemini-2.0-flash")
    
    prompt = """Trích xuất TOÀN BỘ văn bản từ hình ảnh này.
    Giữ nguyên cấu trúc: tiêu đề, điều khoản, bảng biểu.
    Nếu có bảng, format dạng markdown table.
    Chỉ trả về văn bản, không thêm giải thích."""
    
    response = model.generate_content([
        prompt,
        {"mime_type": "image/jpeg", "data": img_bytes}
    ])
    
    return response.text if response.text else ""


async def main():
    parser = argparse.ArgumentParser(description="Local PDF Ingestion with Semantic Chunking")
    parser.add_argument("--pdf", required=True, help="Path to PDF file")
    parser.add_argument("--document-id", required=True, help="Document ID")
    parser.add_argument("--max-pages", type=int, default=None, help="Max pages to process")
    parser.add_argument("--truncate", action="store_true", help="Truncate existing data first")
    args = parser.parse_args()
    
    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"❌ PDF not found: {pdf_path}")
        return
    
    print("=" * 70)
    print("🔄 LOCAL INGESTION WITH SEMANTIC CHUNKING")
    print("=" * 70)
    print(f"📄 PDF: {pdf_path}")
    print(f"🆔 Document ID: {args.document_id}")
    print(f"📅 Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Initialize services
    chunker = SemanticChunker()
    embedder = GeminiOptimizedEmbeddings()
    
    # Create asyncpg connection pool
    db_url = get_asyncpg_url()
    pool = await asyncpg.create_pool(db_url, min_size=1, max_size=2)
    
    # Truncate if requested
    if args.truncate:
        print("🗑️ Truncating existing data...")
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM knowledge_embeddings WHERE document_id = $1",
                args.document_id
            )
        print("   ✅ Deleted existing data")
    
    # Convert PDF to images
    print("📄 Converting PDF to images...")
    images = convert_from_path(str(pdf_path), dpi=150)
    total_pages = len(images)
    print(f"   Converted {total_pages} pages")
    
    if args.max_pages:
        images = images[:args.max_pages]
        print(f"   Processing first {len(images)} pages")
    
    # Process each page
    successful_pages = 0
    total_chunks = 0
    
    for page_num, image in enumerate(images, 1):
        print(f"\n📄 Processing page {page_num}/{len(images)}...")
        
        try:
            # Extract text with Gemini Vision
            print(f"   🔍 Extracting text with Gemini Vision...")
            text = await extract_text_with_gemini(image, page_num)
            
            if not text or len(text.strip()) < 50:
                print(f"   ⚠️ Page {page_num}: No meaningful text extracted")
                continue
            
            print(f"   📝 Extracted {len(text)} characters")
            
            # Chunk the text
            print(f"   ✂️ Chunking text...")
            page_metadata = {
                "document_id": args.document_id,
                "page_number": page_num,
                "source": str(pdf_path.name)
            }
            chunks = await chunker.chunk_page_content(text, page_metadata)
            print(f"   📦 Created {len(chunks)} chunks")
            
            # Store each chunk
            for chunk_idx, chunk in enumerate(chunks):
                # Generate embedding (sync method)
                embedding = embedder.embed_query(chunk.content)
                
                # Get section_hierarchy from metadata
                section_hierarchy = chunk.metadata.get('section_hierarchy', {})
                
                # Build metadata with section_hierarchy
                metadata = {
                    "section_hierarchy": section_hierarchy,
                    "source": str(pdf_path.name)
                }
                
                # Convert embedding to pgvector format
                embedding_str = "[" + ",".join(str(x) for x in embedding) + "]"
                metadata_json = json.dumps(metadata)
                
                # Store in database using asyncpg directly
                # Schema: id (UUID auto), content, embedding (float[]), metadata, source, chunk_index, 
                #         image_url, page_number, document_id, content_type, confidence_score
                async with pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO knowledge_embeddings (
                            content, embedding, document_id, page_number, 
                            chunk_index, content_type, confidence_score, image_url, metadata, source
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10)
                        """,
                        chunk.content[:2000],
                        embedding,  # Pass as Python list, asyncpg handles array conversion
                        args.document_id,
                        page_num,
                        chunk_idx,
                        chunk.content_type,
                        chunk.confidence_score,
                        None,  # No image_url
                        metadata_json,
                        str(pdf_path.name)
                    )
            
            successful_pages += 1
            total_chunks += len(chunks)
            print(f"   ✅ Page {page_num} completed: {len(chunks)} chunks stored")
            
        except Exception as e:
            print(f"   ❌ Page {page_num} failed: {e}")
            continue
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 INGESTION RESULTS")
    print("=" * 70)
    print(f"Document ID:      {args.document_id}")
    print(f"Total Pages:      {len(images)}")
    print(f"Successful:       {successful_pages}")
    print(f"Total Chunks:     {total_chunks}")
    print(f"Avg Chunks/Page:  {total_chunks/successful_pages:.1f}" if successful_pages > 0 else "N/A")
    print()
    print("✅ Ingestion completed!")
    print()
    print("📝 Next steps:")
    print("   1. Test search: python scripts/test_semantic_chunking_api.py --verbose")
    print("   2. Verify in DB: SELECT content_type, COUNT(*) FROM knowledge_embeddings GROUP BY content_type")
    
    # Close pool
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
