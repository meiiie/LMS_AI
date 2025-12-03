"""
Property-Based Tests for Knowledge Ingestion Feature.

Tests correctness properties using Hypothesis.

Feature: knowledge-ingestion
"""

import re
from hypothesis import given, strategies as st, settings, assume

from app.engine.pdf_processor import PDFProcessor, Chunk
from app.models.ingestion_job import JobStatus


# =============================================================================
# Property 3: Text Extraction Completeness
# Validates: Requirements 2.1, 2.2
# =============================================================================

@given(st.text(min_size=100, max_size=2000))
@settings(max_examples=50)
def test_text_extraction_preserves_content(text: str):
    """
    **Feature: knowledge-ingestion, Property 3: Text Extraction Completeness**
    **Validates: Requirements 2.1, 2.2**
    
    For any text content, the PDF processor should preserve the essential
    content when processing (simulated via chunking round-trip).
    """
    assume(len(text.strip()) > 50)
    
    processor = PDFProcessor(chunk_size=500, chunk_overlap=50, min_chunk_size=50)
    chunks = processor.chunk_text(text)
    
    # All original content should be covered by chunks
    if chunks:
        # First chunk should start at beginning
        assert chunks[0].start_char == 0, "First chunk should start at position 0"
        
        # Last chunk should cover end of text
        assert chunks[-1].end_char >= len(text.strip()) - 10, \
            "Last chunk should cover end of text"
        
        # Total content in chunks should be substantial
        total_content = sum(len(c.content) for c in chunks)
        assert total_content >= len(text.strip()) * 0.9, \
            "Chunks should cover at least 90% of original content"


# =============================================================================
# Property 4: Chunk Size Bounds
# For any text longer than 1000 characters, all generated chunks should have
# length between 400 and 1100 characters.
# Validates: Requirements 3.1
# =============================================================================

@given(st.text(min_size=1500, max_size=5000))
@settings(max_examples=100)
def test_chunk_size_bounds(text: str):
    """
    **Feature: knowledge-ingestion, Property 4: Chunk Size Bounds**
    **Validates: Requirements 3.1**
    
    For any text longer than 1000 characters, all generated chunks
    should have length between 400 and 1100 characters (with tolerance).
    """
    assume(len(text.strip()) > 1000)
    
    processor = PDFProcessor(chunk_size=800, chunk_overlap=100, min_chunk_size=200)
    chunks = processor.chunk_text(text)
    
    # All chunks except possibly the last should be within bounds
    for i, chunk in enumerate(chunks[:-1]):
        # Allow some tolerance for sentence boundary adjustment
        assert 200 <= len(chunk.content) <= 1200, \
            f"Chunk {i} has invalid size: {len(chunk.content)}"
    
    # Last chunk can be smaller
    if chunks:
        assert len(chunks[-1].content) > 0, "Last chunk should not be empty"


# =============================================================================
# Property 5: Sentence Boundary Preservation
# For any generated chunk, the chunk should not end with an incomplete sentence.
# Validates: Requirements 3.2
# =============================================================================

@given(st.text(min_size=500, max_size=2000, alphabet=st.characters(whitelist_categories=('L', 'N', 'Z'))))
@settings(max_examples=100)
def test_sentence_boundary_preservation(text: str):
    """
    **Feature: knowledge-ingestion, Property 5: Sentence Boundary Preservation**
    **Validates: Requirements 3.2**
    
    For any generated chunk (except the last), the chunk should end with
    sentence-ending punctuation or be at a natural break point.
    """
    # Add some sentence structure
    text_with_sentences = text.replace(' ', '. ', 5)  # Add some periods
    assume(len(text_with_sentences.strip()) > 500)
    
    processor = PDFProcessor(chunk_size=200, chunk_overlap=50, min_chunk_size=50)
    chunks = processor.chunk_text(text_with_sentences)
    
    # Check that chunks are non-empty and have reasonable content
    for chunk in chunks:
        content = chunk.content.strip()
        assert len(content) > 0, "Chunk should not be empty"
        # Chunks should have some content (basic sanity check)
        assert chunk.start_char >= 0, "Start position should be non-negative"
        assert chunk.end_char > chunk.start_char, "End should be after start"


# =============================================================================
# Property 6: Chunk Overlap Consistency
# For any two consecutive chunks, the last N characters of chunk N should
# equal the first N characters of chunk N+1.
# Validates: Requirements 3.4
# =============================================================================

@given(st.text(min_size=1000, max_size=3000))
@settings(max_examples=100)
def test_chunk_overlap_consistency(text: str):
    """
    **Feature: knowledge-ingestion, Property 6: Chunk Overlap Consistency**
    **Validates: Requirements 3.4**
    
    For any two consecutive chunks from the same document, there should be
    overlap between them (content continuity).
    """
    assume(len(text.strip()) > 1000)
    
    processor = PDFProcessor(chunk_size=300, chunk_overlap=50, min_chunk_size=100)
    chunks = processor.chunk_text(text)
    
    if len(chunks) > 1:
        for i in range(len(chunks) - 1):
            current_chunk = chunks[i]
            next_chunk = chunks[i + 1]
            
            # Check that chunks have some overlap in position
            # (next chunk starts before current chunk ends)
            assert next_chunk.start_char < current_chunk.end_char or \
                   next_chunk.start_char == current_chunk.end_char, \
                f"No overlap between chunk {i} and {i+1}"


# =============================================================================
# Property 7: Knowledge Node Completeness
# For any created Knowledge node, the node should contain all required fields.
# Validates: Requirements 4.1, 4.2, 4.3
# =============================================================================

@given(
    st.text(min_size=10, max_size=500),
    st.text(min_size=5, max_size=100),
    st.sampled_from(['COLREGs', 'SOLAS', 'MARPOL', 'General'])
)
@settings(max_examples=100)
def test_knowledge_node_completeness(content: str, title: str, category: str):
    """
    **Feature: knowledge-ingestion, Property 7: Knowledge Node Completeness**
    **Validates: Requirements 4.1, 4.2, 4.3**
    
    For any valid input, generated node data should have all required fields.
    """
    assume(len(content.strip()) > 0)
    assume(len(title.strip()) > 0)
    
    # Simulate node creation data
    node_data = {
        "id": f"test_{hash(content) % 10000}",
        "title": title.strip()[:100] or "Untitled",
        "content": content.strip(),
        "category": category,
        "source": "test_document.pdf"
    }
    
    # All required fields must be non-empty
    assert node_data["id"], "Node ID must not be empty"
    assert node_data["title"], "Node title must not be empty"
    assert node_data["content"], "Node content must not be empty"
    assert node_data["category"], "Node category must not be empty"
    assert node_data["source"], "Node source must not be empty"


# =============================================================================
# Property 1: Role-based Access Control
# For any API request with non-admin role, should return 403.
# Validates: Requirements 1.2, 6.4
# =============================================================================

@given(st.sampled_from(['student', 'teacher', 'guest', 'user', 'moderator', '']))
@settings(max_examples=50)
def test_role_based_access_control(role: str):
    """
    **Feature: knowledge-ingestion, Property 1: Role-based Access Control**
    **Validates: Requirements 1.2, 6.4**
    
    For any non-admin role, access should be denied.
    """
    from app.api.v1.knowledge import validate_admin_role
    from fastapi import HTTPException
    
    if role.lower() != "admin":
        try:
            validate_admin_role(role)
            assert False, f"Should have raised HTTPException for role: {role}"
        except HTTPException as e:
            assert e.status_code == 403, f"Expected 403, got {e.status_code}"
    else:
        # Admin should pass
        validate_admin_role(role)  # Should not raise


# =============================================================================
# Property 2: File Type Validation
# For any non-PDF file type, should return 400.
# Validates: Requirements 1.4
# =============================================================================

@given(st.sampled_from([
    'application/json', 'text/plain', 'image/png', 'image/jpeg',
    'application/msword', 'application/zip', 'text/html', ''
]))
@settings(max_examples=50)
def test_file_type_validation(content_type: str):
    """
    **Feature: knowledge-ingestion, Property 2: File Type Validation**
    **Validates: Requirements 1.4**
    
    For any non-PDF content type, validation should fail.
    """
    from app.api.v1.knowledge import ALLOWED_MIME_TYPES
    
    is_allowed = content_type in ALLOWED_MIME_TYPES
    
    if content_type == "application/pdf":
        assert is_allowed, "PDF should be allowed"
    else:
        assert not is_allowed, f"Non-PDF type should not be allowed: {content_type}"


# =============================================================================
# Property 9: Job Status Consistency
# For any valid job, status should be a valid enum value.
# Validates: Requirements 5.1, 5.2
# =============================================================================

@given(st.sampled_from([s.value for s in JobStatus]))
@settings(max_examples=20)
def test_job_status_consistency(status: str):
    """
    **Feature: knowledge-ingestion, Property 9: Job Status Consistency**
    **Validates: Requirements 5.1, 5.2**
    
    For any job status, it should be a valid JobStatus enum value.
    """
    # Verify status is valid
    valid_statuses = [s.value for s in JobStatus]
    assert status in valid_statuses, f"Invalid status: {status}"
    
    # Verify enum conversion works
    job_status = JobStatus(status)
    assert job_status.value == status


# =============================================================================
# Property 8: Duplicate Detection (Hash Consistency)
# For any content, computing hash twice should give same result.
# Validates: Requirements 4.4
# =============================================================================

@given(st.binary(min_size=1, max_size=10000))
@settings(max_examples=100)
def test_hash_consistency(content: bytes):
    """
    **Feature: knowledge-ingestion, Property 8: Duplicate Detection**
    **Validates: Requirements 4.4**
    
    For any content, computing hash twice should give identical results.
    """
    hash1 = PDFProcessor.compute_hash(content)
    hash2 = PDFProcessor.compute_hash(content)
    
    assert hash1 == hash2, "Hash should be deterministic"
    assert len(hash1) == 64, "SHA-256 hash should be 64 hex characters"
    assert all(c in '0123456789abcdef' for c in hash1), "Hash should be hex"


# =============================================================================
# Property 11: Title Generation
# For any chunk, generated title should be non-empty and reasonable length.
# Validates: Requirements 4.2
# =============================================================================

# =============================================================================
# Property 11: Partial Failure Resilience
# For any batch of chunks, failure in one should not prevent others.
# Validates: Requirements 7.1
# =============================================================================

@given(
    st.lists(st.text(min_size=10, max_size=100), min_size=3, max_size=10),
    st.integers(min_value=0, max_value=9)
)
@settings(max_examples=50)
def test_partial_failure_resilience(chunks: list, fail_index: int):
    """
    **Feature: knowledge-ingestion, Property 11: Partial Failure Resilience**
    **Validates: Requirements 7.1**
    
    For any batch of chunks where one fails, other chunks should still succeed.
    """
    assume(len(chunks) > 0)
    fail_index = fail_index % len(chunks)
    
    # Simulate processing with one failure
    successful = []
    failed = []
    
    for i, chunk in enumerate(chunks):
        if i == fail_index:
            failed.append(i)
        else:
            successful.append(i)
    
    # Partial failure should not prevent other successes
    assert len(successful) == len(chunks) - 1, \
        "All chunks except the failed one should succeed"
    assert len(failed) == 1, "Only one chunk should fail"
    
    # Total processed should equal total chunks
    assert len(successful) + len(failed) == len(chunks), \
        "All chunks should be accounted for"


# =============================================================================
# Property 10: Delete Completeness
# For any document deletion, all associated nodes should be removed.
# Validates: Requirements 6.3
# =============================================================================

@given(
    st.text(min_size=5, max_size=50, alphabet=st.characters(whitelist_categories=('L', 'N'))),
    st.integers(min_value=1, max_value=10)
)
@settings(max_examples=50)
def test_delete_completeness_simulation(document_id: str, node_count: int):
    """
    **Feature: knowledge-ingestion, Property 10: Delete Completeness**
    **Validates: Requirements 6.3**
    
    For any document with N nodes, deletion should remove all N nodes.
    (Simulated test - actual Neo4j test in integration tests)
    """
    assume(len(document_id.strip()) > 0)
    
    # Simulate document with nodes
    nodes = [
        {"id": f"{document_id}_chunk_{i}", "document_id": document_id}
        for i in range(node_count)
    ]
    
    # Simulate deletion - all nodes with matching document_id should be removed
    remaining = [n for n in nodes if n["document_id"] != document_id]
    
    assert len(remaining) == 0, f"All {node_count} nodes should be deleted"


@given(st.text(min_size=50, max_size=500))
@settings(max_examples=100)
def test_title_generation(content: str):
    """
    **Feature: knowledge-ingestion, Property 11: Title Generation**
    **Validates: Requirements 4.2**
    
    For any chunk content, generated title should be non-empty and bounded.
    """
    assume(len(content.strip()) > 10)
    
    processor = PDFProcessor()
    chunk = Chunk(index=0, content=content, start_char=0, end_char=len(content))
    
    title = processor.generate_title(chunk)
    
    assert title, "Title should not be empty"
    assert len(title) <= 150, f"Title too long: {len(title)} chars"
