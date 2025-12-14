"""
Test script for Contextual RAG feature

Run: python -m scripts.test_contextual_rag
"""
import asyncio
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.context_enricher import ContextEnricher, get_context_enricher
from app.services.chunking_service import ChunkResult
from app.core.config import settings


async def test_context_enricher():
    """Test the ContextEnricher class"""
    print("=" * 60)
    print("Testing Contextual RAG (Anthropic-style Context Enrichment)")
    print("=" * 60)
    
    # Check config
    print(f"\n📋 Config:")
    print(f"   - contextual_rag_enabled: {settings.contextual_rag_enabled}")
    print(f"   - contextual_rag_batch_size: {settings.contextual_rag_batch_size}")
    
    if not settings.contextual_rag_enabled:
        print("\n⚠️  Contextual RAG is disabled in config!")
        print("   Set CONTEXTUAL_RAG_ENABLED=true to enable")
        return
    
    # Create enricher
    enricher = get_context_enricher()
    print(f"\n✅ ContextEnricher created")
    
    # Test sample - maritime content
    sample_chunk = """
    Điều 15 - Tình huống cắt hướng
    Khi hai tàu máy đi cắt hướng nhau có nguy cơ va chạm, tàu nào 
    nhìn thấy tàu kia ở bên mạn phải của mình phải nhường đường 
    và nếu hoàn cảnh cho phép, tránh cắt hướng phía trước mũi tàu kia.
    """
    
    print(f"\n📝 Sample Chunk (Điều 15 COLREGs):")
    print(f"   {sample_chunk.strip()[:100]}...")
    
    # Generate context
    print(f"\n🔄 Generating context using LLM...")
    try:
        result = await enricher.generate_context(
            chunk_content=sample_chunk,
            document_title="COLREGs - Quy tắc phòng ngừa va chạm tàu thuyền",
            page_number=15,
            total_pages=38
        )
        
        if result.success:
            print(f"\n✅ Context generated successfully!")
            print(f"\n📌 Generated Context:")
            print(f"   {result.context_only}")
            print(f"\n📄 Full Contextual Content:")
            print(f"   {result.contextual_content[:300]}...")
        else:
            print(f"\n❌ Context generation failed: {result.error}")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    # Test batch enrichment
    print(f"\n{'=' * 60}")
    print("Testing Batch Enrichment")
    print("=" * 60)
    
    chunks = [
        ChunkResult(
            chunk_index=0,
            content="Điều 15 quy định về tình huống cắt hướng giữa hai tàu máy.",
            content_type="text",
            metadata={"page_number": 15}
        ),
        ChunkResult(
            chunk_index=1,
            content="Tàu nhường đường phải tránh cắt hướng phía trước mũi tàu được nhường.",
            content_type="text",
            metadata={"page_number": 15}
        )
    ]
    
    print(f"\n📝 Testing batch of {len(chunks)} chunks...")
    
    try:
        enriched = await enricher.enrich_chunks(
            chunks=chunks,
            document_id="colregs_test",
            document_title="COLREGs",
            total_pages=38,
            batch_size=2
        )
        
        for i, chunk in enumerate(enriched):
            has_context = chunk.contextual_content is not None
            print(f"\n   Chunk {i}: {'✅ enriched' if has_context else '❌ no context'}")
            if has_context:
                print(f"   Preview: {chunk.contextual_content[:150]}...")
                
    except Exception as e:
        print(f"\n❌ Batch enrichment error: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"\n{'=' * 60}")
    print("Test Complete!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_context_enricher())
