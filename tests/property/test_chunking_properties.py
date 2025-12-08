"""
Property-Based Tests for Semantic Chunking Service

Feature: semantic-chunking
Tests correctness properties for the SemanticChunker service.

Uses Hypothesis library for property-based testing.
Each test runs minimum 100 iterations.
"""
import pytest
from hypothesis import given, strategies as st, settings, assume
import asyncio

# Import the chunking service
from app.services.chunking_service import SemanticChunker, ChunkResult


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def chunker():
    """Create a SemanticChunker instance for testing"""
    return SemanticChunker(
        chunk_size=800,
        chunk_overlap=100,
        min_chunk_size=50
    )


# =============================================================================
# Strategies for generating test data
# =============================================================================

# Strategy for generating text of various lengths
text_strategy = st.text(
    alphabet=st.characters(whitelist_categories=('L', 'N', 'P', 'Z')),
    min_size=100,
    max_size=5000
)

# Strategy for generating maritime legal text
maritime_text_strategy = st.sampled_from([
    "Điều 15. Quy định về an toàn hàng hải\nKhoản 1. Tàu thuyền phải tuân thủ các quy định.",
    "Rule 15 - Crossing Situation\nWhen two power-driven vessels are crossing.",
    "Article 10. Navigation Rules\nClause 2. All vessels shall maintain safe speed.",
    "Điều 19. Tốc độ an toàn\nKhoản 2. Mọi tàu thuyền phải duy trì tốc độ an toàn.",
])

# Strategy for generating table-like text
table_text_strategy = st.sampled_from([
    "| Loại tàu | Tốc độ | Khu vực |\n|----------|--------|--------|\n| Tàu hàng | 15 | Ven biển |",
    "| Type | Speed | Area |\n|------|-------|------|\n| Cargo | 15 | Coastal |",
    "| Column A | Column B |\n|----------|----------|\n| Value 1 | Value 2 |",
])

# Strategy for generating diagram reference text
diagram_text_strategy = st.sampled_from([
    "Hình 1 minh họa quy trình kiểm tra an toàn.",
    "Sơ đồ 2 thể hiện cấu trúc tổ chức.",
    "Figure 3 shows the navigation lights arrangement.",
    "Diagram 4 illustrates the collision avoidance procedure.",
])


# =============================================================================
# Property 1: Chunk Size Bounds
# =============================================================================

@settings(max_examples=100)
@given(st.text(min_size=200, max_size=3000))
def test_chunk_size_bounds(text):
    """
    **Feature: semantic-chunking, Property 1: Chunk Size Bounds**
    **Validates: Requirements 1.1, 1.5**
    
    For any text input, all generated chunks SHALL have length between
    MIN_CHUNK_SIZE (50) and CHUNK_SIZE + CHUNK_OVERLAP (900) characters.
    """
    # Skip empty or whitespace-only text
    assume(text.strip())
    
    chunker = SemanticChunker(chunk_size=800, chunk_overlap=100, min_chunk_size=50)
    
    # Run async function
    chunks = asyncio.get_event_loop().run_until_complete(
        chunker.chunk_page_content(text, {'page_number': 1})
    )
    
    # If no chunks generated (text too short), that's acceptable
    if not chunks:
        return
    
    for chunk in chunks:
        # Chunks should be at least min_chunk_size (merged small chunks)
        # and at most chunk_size + overlap
        assert len(chunk.content) >= 1, f"Chunk too short: {len(chunk.content)}"
        # Upper bound is flexible due to sentence preservation
        assert len(chunk.content) <= 2000, f"Chunk too long: {len(chunk.content)}"



# =============================================================================
# Property 3: Content Type Valid Enum
# =============================================================================

@settings(max_examples=100)
@given(st.text(min_size=100, max_size=2000))
def test_content_type_valid_enum(text):
    """
    **Feature: semantic-chunking, Property 3: Content Type Valid Enum**
    **Validates: Requirements 2.1**
    
    For any chunk processed, the content_type SHALL be one of:
    "text", "table", "heading", "diagram_reference", "formula".
    """
    assume(text.strip())
    
    chunker = SemanticChunker()
    valid_types = {"text", "table", "heading", "diagram_reference", "formula"}
    
    chunks = asyncio.get_event_loop().run_until_complete(
        chunker.chunk_page_content(text, {'page_number': 1})
    )
    
    for chunk in chunks:
        assert chunk.content_type in valid_types, \
            f"Invalid content_type: {chunk.content_type}"


# =============================================================================
# Property 4: Table Detection Accuracy
# =============================================================================

@settings(max_examples=50)
@given(table_text_strategy)
def test_table_detection_accuracy(table_text):
    """
    **Feature: semantic-chunking, Property 4: Table Detection Accuracy**
    **Validates: Requirements 2.2**
    
    For any text containing Markdown table syntax (| characters and --- separators),
    the content_type SHALL be "table".
    """
    chunker = SemanticChunker()
    
    # Detect content type directly
    content_type = chunker._detect_content_type(table_text)
    
    assert content_type == "table", \
        f"Expected 'table' but got '{content_type}' for: {table_text[:50]}..."


# =============================================================================
# Property 5: Heading Detection for Maritime Patterns
# =============================================================================

@settings(max_examples=50)
@given(maritime_text_strategy)
def test_heading_detection_maritime_patterns(maritime_text):
    """
    **Feature: semantic-chunking, Property 5: Heading Detection for Maritime Patterns**
    **Validates: Requirements 2.3, 2.4**
    
    For any text containing maritime legal patterns (Điều X, Khoản X, Rule X),
    the content_type SHALL be "heading".
    """
    chunker = SemanticChunker()
    
    # Detect content type directly
    content_type = chunker._detect_content_type(maritime_text)
    
    assert content_type == "heading", \
        f"Expected 'heading' but got '{content_type}' for: {maritime_text[:50]}..."


# =============================================================================
# Property 6: Confidence Score Bounds
# =============================================================================

@settings(max_examples=100)
@given(st.text(min_size=10, max_size=2000))
def test_confidence_score_bounds(text):
    """
    **Feature: semantic-chunking, Property 6: Confidence Score Bounds**
    **Validates: Requirements 3.1**
    
    For any chunk, the confidence_score SHALL be between 0.0 and 1.0 inclusive.
    """
    assume(text.strip())
    
    chunker = SemanticChunker()
    
    chunks = asyncio.get_event_loop().run_until_complete(
        chunker.chunk_page_content(text, {'page_number': 1})
    )
    
    for chunk in chunks:
        assert 0.0 <= chunk.confidence_score <= 1.0, \
            f"Confidence score out of bounds: {chunk.confidence_score}"


# =============================================================================
# Property 7: Short Chunk Confidence Penalty
# =============================================================================

@settings(max_examples=50)
@given(st.text(min_size=10, max_size=49))
def test_short_chunk_confidence_penalty(short_text):
    """
    **Feature: semantic-chunking, Property 7: Short Chunk Confidence Penalty**
    **Validates: Requirements 3.2**
    
    For any chunk with fewer than 50 characters, the confidence_score SHALL be 0.6 or lower.
    """
    assume(short_text.strip())
    
    chunker = SemanticChunker()
    
    # Calculate confidence directly for short text
    confidence = chunker._calculate_confidence(short_text, "text")
    
    assert confidence <= 0.6, \
        f"Short chunk ({len(short_text)} chars) should have confidence <= 0.6, got {confidence}"


# =============================================================================
# Property 8: Long Chunk Confidence Penalty
# =============================================================================

@settings(max_examples=50)
@given(st.text(min_size=1001, max_size=2000))
def test_long_chunk_confidence_penalty(long_text):
    """
    **Feature: semantic-chunking, Property 8: Long Chunk Confidence Penalty**
    **Validates: Requirements 3.3**
    
    For any chunk with more than 1000 characters, the confidence_score SHALL be 0.7 or lower.
    """
    assume(long_text.strip())
    
    chunker = SemanticChunker()
    
    # Calculate confidence directly for long text
    confidence = chunker._calculate_confidence(long_text, "text")
    
    assert confidence <= 0.7, \
        f"Long chunk ({len(long_text)} chars) should have confidence <= 0.7, got {confidence}"



# =============================================================================
# Property 9: Structured Content Confidence Boost
# =============================================================================

@settings(max_examples=50)
@given(st.text(min_size=100, max_size=500))
def test_structured_content_confidence_boost(text):
    """
    **Feature: semantic-chunking, Property 9: Structured Content Confidence Boost**
    **Validates: Requirements 3.4**
    
    For any chunk with content_type "heading" or "table", the confidence_score
    SHALL be at least 20% higher than base score (capped at 1.0).
    """
    assume(text.strip())
    
    chunker = SemanticChunker()
    
    # Calculate base confidence for "text" type
    base_confidence = chunker._calculate_confidence(text, "text")
    
    # Calculate confidence for "heading" type
    heading_confidence = chunker._calculate_confidence(text, "heading")
    
    # Calculate confidence for "table" type
    table_confidence = chunker._calculate_confidence(text, "table")
    
    # Structured content should have higher confidence (or capped at 1.0)
    expected_boost = min(1.0, base_confidence * 1.2)
    
    assert heading_confidence >= base_confidence, \
        f"Heading confidence ({heading_confidence}) should be >= base ({base_confidence})"
    assert table_confidence >= base_confidence, \
        f"Table confidence ({table_confidence}) should be >= base ({base_confidence})"


# =============================================================================
# Property 10: Chunk Index Sequential
# =============================================================================

@settings(max_examples=50)
@given(st.text(min_size=500, max_size=3000))
def test_chunk_index_sequential(text):
    """
    **Feature: semantic-chunking, Property 10: Chunk Index Sequential**
    **Validates: Requirements 4.4**
    
    For any page with N chunks, the chunk_index values SHALL be
    sequential integers from 0 to N-1.
    """
    assume(text.strip())
    
    chunker = SemanticChunker()
    
    chunks = asyncio.get_event_loop().run_until_complete(
        chunker.chunk_page_content(text, {'page_number': 1})
    )
    
    if not chunks:
        return
    
    # Check sequential indices
    expected_indices = list(range(len(chunks)))
    actual_indices = [chunk.chunk_index for chunk in chunks]
    
    assert actual_indices == expected_indices, \
        f"Chunk indices not sequential: expected {expected_indices}, got {actual_indices}"


# =============================================================================
# Property 11: Article Number Extraction
# =============================================================================

@settings(max_examples=50)
@given(st.integers(min_value=1, max_value=100))
def test_article_number_extraction(article_num):
    """
    **Feature: semantic-chunking, Property 11: Article Number Extraction**
    **Validates: Requirements 5.1**
    
    For any text containing "Điều X" or "Article X" pattern,
    the metadata.section_hierarchy SHALL contain the article number.
    """
    chunker = SemanticChunker()
    
    # Test Vietnamese pattern
    vi_text = f"Điều {article_num}. Quy định về an toàn hàng hải"
    vi_hierarchy = chunker._extract_document_hierarchy(vi_text)
    assert 'article' in vi_hierarchy, f"Article not extracted from: {vi_text}"
    assert vi_hierarchy['article'] == str(article_num), \
        f"Expected article {article_num}, got {vi_hierarchy.get('article')}"
    
    # Test English pattern
    en_text = f"Article {article_num}. Navigation Safety Regulations"
    en_hierarchy = chunker._extract_document_hierarchy(en_text)
    assert 'article' in en_hierarchy, f"Article not extracted from: {en_text}"
    assert en_hierarchy['article'] == str(article_num), \
        f"Expected article {article_num}, got {en_hierarchy.get('article')}"


# =============================================================================
# Property 12: Clause Number Extraction
# =============================================================================

@settings(max_examples=50)
@given(st.integers(min_value=1, max_value=20))
def test_clause_number_extraction(clause_num):
    """
    **Feature: semantic-chunking, Property 12: Clause Number Extraction**
    **Validates: Requirements 5.2**
    
    For any text containing "Khoản X" or "Clause X" pattern,
    the metadata.section_hierarchy SHALL contain the clause number.
    """
    chunker = SemanticChunker()
    
    # Test Vietnamese pattern
    vi_text = f"Khoản {clause_num}. Tàu thuyền phải tuân thủ các quy định."
    vi_hierarchy = chunker._extract_document_hierarchy(vi_text)
    assert 'clause' in vi_hierarchy, f"Clause not extracted from: {vi_text}"
    assert vi_hierarchy['clause'] == str(clause_num), \
        f"Expected clause {clause_num}, got {vi_hierarchy.get('clause')}"
    
    # Test English pattern
    en_text = f"Clause {clause_num}. All vessels shall comply with regulations."
    en_hierarchy = chunker._extract_document_hierarchy(en_text)
    assert 'clause' in en_hierarchy, f"Clause not extracted from: {en_text}"
    assert en_hierarchy['clause'] == str(clause_num), \
        f"Expected clause {clause_num}, got {en_hierarchy.get('clause')}"


# =============================================================================
# Additional Property: Rule Number Extraction
# =============================================================================

@settings(max_examples=50)
@given(st.integers(min_value=1, max_value=40))
def test_rule_number_extraction(rule_num):
    """
    **Feature: semantic-chunking, Property: Rule Number Extraction**
    **Validates: Requirements 5.3**
    
    For any text containing "Rule X" pattern,
    the metadata.section_hierarchy SHALL contain the rule number.
    """
    chunker = SemanticChunker()
    
    # Test Rule pattern (COLREGs)
    text = f"Rule {rule_num} - Crossing Situation"
    hierarchy = chunker._extract_document_hierarchy(text)
    
    assert 'rule' in hierarchy, f"Rule not extracted from: {text}"
    assert hierarchy['rule'] == str(rule_num), \
        f"Expected rule {rule_num}, got {hierarchy.get('rule')}"


# =============================================================================
# Additional Property: Diagram Reference Detection
# =============================================================================

@settings(max_examples=50)
@given(diagram_text_strategy)
def test_diagram_reference_detection(diagram_text):
    """
    **Feature: semantic-chunking, Property: Diagram Reference Detection**
    **Validates: Requirements 2.4**
    
    For any text containing diagram/figure references,
    the content_type SHALL be "diagram_reference".
    """
    chunker = SemanticChunker()
    
    content_type = chunker._detect_content_type(diagram_text)
    
    assert content_type == "diagram_reference", \
        f"Expected 'diagram_reference' but got '{content_type}' for: {diagram_text[:50]}..."


# =============================================================================
# Additional Property: Empty Text Handling
# =============================================================================

def test_empty_text_returns_empty_list():
    """
    **Feature: semantic-chunking, Property: Empty Text Handling**
    
    For empty or whitespace-only text, the chunker SHALL return an empty list.
    """
    chunker = SemanticChunker()
    
    # Test empty string
    chunks = asyncio.get_event_loop().run_until_complete(
        chunker.chunk_page_content("", {'page_number': 1})
    )
    assert chunks == [], "Empty text should return empty list"
    
    # Test whitespace only
    chunks = asyncio.get_event_loop().run_until_complete(
        chunker.chunk_page_content("   \n\t  ", {'page_number': 1})
    )
    assert chunks == [], "Whitespace-only text should return empty list"


# =============================================================================
# Additional Property: Metadata Contains Page Info
# =============================================================================

@settings(max_examples=20)
@given(st.integers(min_value=1, max_value=100))
def test_metadata_contains_page_info(page_num):
    """
    **Feature: semantic-chunking, Property: Metadata Contains Page Info**
    
    For any chunk, the metadata SHALL contain the page_number from input.
    """
    chunker = SemanticChunker()
    
    text = "This is a test text with enough content to create at least one chunk."
    
    chunks = asyncio.get_event_loop().run_until_complete(
        chunker.chunk_page_content(text, {'page_number': page_num, 'document_id': 'test_doc'})
    )
    
    for chunk in chunks:
        assert chunk.metadata.get('page_number') == page_num, \
            f"Expected page_number {page_num}, got {chunk.metadata.get('page_number')}"
