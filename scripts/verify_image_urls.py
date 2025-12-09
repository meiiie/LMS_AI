#!/usr/bin/env python
"""
Verify image_url data in Neon database.
Quick script to check if multimodal ingestion stored image URLs correctly.
"""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text
from app.core.database import get_shared_session_factory

def main():
    print("=" * 60)
    print("🔍 Verifying image_url in Neon Database")
    print("=" * 60)
    
    session_factory = get_shared_session_factory()
    
    with session_factory() as session:
        # Count total records
        result = session.execute(text(
            "SELECT COUNT(*) FROM knowledge_embeddings"
        ))
        total = result.scalar()
        print(f"\n📊 Total records: {total}")
        
        # Count records with image_url
        result = session.execute(text(
            "SELECT COUNT(*) FROM knowledge_embeddings WHERE image_url IS NOT NULL"
        ))
        with_image = result.scalar()
        print(f"📷 Records with image_url: {with_image}")
        
        # Show sample records with image_url
        if with_image > 0:
            print(f"\n✅ SUCCESS: Found {with_image} records with image_url!")
            print("\n📋 Sample records:")
            result = session.execute(text("""
                SELECT id, document_id, page_number, chunk_index, 
                       LEFT(content, 80) as content_preview, image_url
                FROM knowledge_embeddings 
                WHERE image_url IS NOT NULL 
                ORDER BY document_id, page_number, chunk_index
                LIMIT 10
            """))
            
            for row in result:
                print(f"  - ID: {row.id}")
                print(f"    Doc: {row.document_id}, Page: {row.page_number}, Chunk: {row.chunk_index}")
                print(f"    Content: {row.content_preview}...")
                print(f"    Image: {row.image_url}")
                print()
        else:
            print("\n⚠️ WARNING: No records with image_url found!")
            print("   You may need to run multimodal re-ingestion.")
        
        # Check document_id distribution
        print("\n📁 Documents in database:")
        result = session.execute(text("""
            SELECT document_id, COUNT(*) as count,
                   SUM(CASE WHEN image_url IS NOT NULL THEN 1 ELSE 0 END) as with_image
            FROM knowledge_embeddings 
            GROUP BY document_id
            ORDER BY count DESC
            LIMIT 10
        """))
        
        for row in result:
            print(f"  - {row.document_id}: {row.count} chunks, {row.with_image} with images")

if __name__ == "__main__":
    main()
