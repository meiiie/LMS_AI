"""
Quick test script for PDF extraction and chunking.
"""
import sys
sys.path.insert(0, '.')

from app.engine.pdf_processor import PDFProcessor

def main():
    pdf_path = "data/VanBanGoc_95.2015.QH13.P1.pdf"
    
    print(f"Testing PDF extraction: {pdf_path}")
    print("=" * 60)
    
    processor = PDFProcessor(chunk_size=800, chunk_overlap=100)
    
    # Step 1: Extract text
    print("\n[1] Extracting text...")
    try:
        text = processor.extract_text(pdf_path)
        print(f"✓ Extracted {len(text)} characters")
        print(f"\nFirst 500 chars:\n{text[:500]}...")
    except Exception as e:
        print(f"✗ Error: {e}")
        return
    
    # Step 2: Detect structure
    print("\n[2] Detecting document structure...")
    structure = processor.detect_structure(text)
    print(f"✓ Title: {structure.title}")
    print(f"✓ Total pages: {structure.total_pages}")
    print(f"✓ Total chars: {structure.total_chars}")
    print(f"✓ Sections found: {len(structure.sections)}")
    
    # Step 3: Chunk text
    print("\n[3] Chunking text...")
    chunks = processor.chunk_text(text)
    print(f"✓ Created {len(chunks)} chunks")
    
    # Show first 3 chunks
    print("\nFirst 3 chunks:")
    for i, chunk in enumerate(chunks[:3]):
        title = processor.generate_title(chunk)
        print(f"\n--- Chunk {i} (chars {chunk.start_char}-{chunk.end_char}) ---")
        print(f"Title: {title}")
        print(f"Content preview: {chunk.content[:200]}...")
    
    # Step 4: Compute hash
    print("\n[4] Computing content hash...")
    with open(pdf_path, "rb") as f:
        content = f.read()
    hash_value = PDFProcessor.compute_hash(content)
    print(f"✓ SHA-256: {hash_value}")
    
    print("\n" + "=" * 60)
    print("PDF extraction test completed successfully!")

if __name__ == "__main__":
    main()
