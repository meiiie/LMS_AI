"""
Test script for Entity Extractor

Run: python -m scripts.test_entity_extractor
"""
import asyncio
import json
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.entity_extractor import (
    EntityExtractor, 
    get_entity_extractor,
    DocumentEntityType,
    DocumentRelationType
)


async def test_single_chunk_extraction():
    """Test extraction from a single chunk"""
    print("=" * 60)
    print("Testing Entity Extraction from Chunk")
    print("=" * 60)
    
    # Sample maritime content (COLREGs Rule 15)
    sample_chunk = """
    Điều 15 - Tình huống cắt hướng
    
    Khi hai tàu máy đi cắt hướng nhau có nguy cơ va chạm, tàu nào 
    nhìn thấy tàu kia ở bên mạn phải của mình phải nhường đường 
    và nếu hoàn cảnh cho phép, tránh cắt hướng phía trước mũi tàu kia.
    
    Quy tắc này áp dụng cho các tàu máy chạy trên biển và phải tuân thủ
    theo Điều 7 (Nguy cơ va chạm) và Điều 8 (Hành động tránh va).
    """
    
    extractor = get_entity_extractor()
    print("\n✅ EntityExtractor created")
    
    print("\n📝 Sample Chunk (Điều 15 COLREGs):")
    print(f"   {sample_chunk[:150]}...")
    
    print("\n🔄 Extracting entities using LLM...")
    
    result = await extractor.extract_from_chunk(
        chunk_content=sample_chunk,
        chunk_id="test_chunk_1",
        document_title="COLREGs - Quy tắc phòng ngừa đâm va trên biển",
        page_number=15
    )
    
    if result.success:
        print("\n✅ Extraction successful!")
        
        print(f"\n📌 Extracted Entities ({len(result.entities)}):")
        for entity in result.entities:
            print(f"   • [{entity.type.value}] {entity.name}")
            if entity.name_vi:
                print(f"     Vietnamese: {entity.name_vi}")
            if entity.description:
                print(f"     Description: {entity.description[:80]}...")
        
        print(f"\n🔗 Extracted Relations ({len(result.relations)}):")
        for rel in result.relations:
            print(f"   • {rel.source_id} --[{rel.type.value}]--> {rel.target_id}")
            if rel.description:
                print(f"     {rel.description}")
    else:
        print(f"\n❌ Extraction failed: {result.error}")
    
    return result.success


async def test_document_extraction():
    """Test extraction from multiple chunks"""
    print("\n" + "=" * 60)
    print("Testing Document-Level Extraction")
    print("=" * 60)
    
    # Simulate multiple chunks from a document
    chunks = [
        {
            "content": """
            Phần B - QUY TẮC HÀNH TRÌNH VÀ ĐIỀU ĐỘNG
            
            Phần này quy định về các quy tắc lái tàu và điều động khi các tàu
            tiến gần nhau có nguy cơ va chạm. Bao gồm các tình huống:
            - Tầm nhìn xa tốt (Tiểu mục I)
            - Tầm nhìn xa hạn chế (Tiểu mục II)
            """,
            "chunk_id": "chunk_001",
            "page_number": 5
        },
        {
            "content": """
            Điều 13 - Tàu vượt
            
            Mặc dù có những quy định trong các điều từ Điều 4 đến Điều 18,
            bất kỳ tàu nào vượt tàu khác đều phải nhường đường cho tàu bị vượt.
            
            Tàu vượt là tàu tiến đến từ hướng quá 22,5 độ sau chính ngang của
            tàu kia, nghĩa là ở vị trí mà về đêm chỉ nhìn thấy đèn lái sau.
            """,
            "chunk_id": "chunk_002", 
            "page_number": 12
        }
    ]
    
    extractor = EntityExtractor()
    
    print(f"\n📝 Processing {len(chunks)} chunks...")
    
    entities, relations = await extractor.extract_from_document(
        chunks=chunks,
        document_id="colregs_vn",
        document_title="COLREGs - Bản dịch tiếng Việt"
    )
    
    print(f"\n✅ Document extraction complete!")
    print(f"   Total entities: {len(entities)}")
    print(f"   Total relations: {len(relations)}")
    
    if entities:
        print(f"\n📌 All Entities:")
        for entity in entities:
            print(f"   • [{entity.type.value}] {entity.id}: {entity.name}")
    
    if relations:
        print(f"\n🔗 All Relations:")
        for rel in relations:
            print(f"   • {rel.source_id} --[{rel.type.value}]--> {rel.target_id}")
    
    return len(entities) > 0


async def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Entity Extractor Test Suite")
    print("=" * 60)
    
    # Test 1: Single chunk
    test1 = await test_single_chunk_extraction()
    
    # Test 2: Document level
    test2 = await test_document_extraction()
    
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)
    print(f"   Single chunk extraction: {'✅ PASS' if test1 else '❌ FAIL'}")
    print(f"   Document extraction: {'✅ PASS' if test2 else '❌ FAIL'}")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
