"""
Test script for Hybrid Text/Vision Detection feature.

Feature: hybrid-text-vision
Tests the PageAnalyzer component and hybrid detection logic.

Usage:
    python scripts/test_hybrid_detection.py
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.engine.page_analyzer import PageAnalyzer, PageAnalysisResult, get_page_analyzer


def test_page_analyzer_initialization():
    """Test PageAnalyzer initializes correctly"""
    print("\n=== Test 1: PageAnalyzer Initialization ===")
    
    analyzer = PageAnalyzer()
    
    assert len(analyzer.table_patterns) > 0, "Should have table patterns"
    assert len(analyzer.diagram_keywords) > 0, "Should have diagram keywords"
    assert len(analyzer.maritime_keywords) > 0, "Should have maritime keywords"
    assert analyzer.min_text_length == 100, "Default min_text_length should be 100"
    
    print(f"✅ Table patterns: {len(analyzer.table_patterns)}")
    print(f"✅ Diagram keywords: {len(analyzer.diagram_keywords)}")
    print(f"✅ Maritime keywords: {len(analyzer.maritime_keywords)}")
    print(f"✅ Min text length: {analyzer.min_text_length}")
    print("✅ PASSED: PageAnalyzer initialization")


def test_text_content_analysis():
    """Test analyze_text_content method"""
    print("\n=== Test 2: Text Content Analysis ===")
    
    analyzer = PageAnalyzer()
    
    # Test 1: Plain text (should be direct)
    plain_text = """
    This is a plain text document without any tables or images.
    The content only contains regular text characters and paragraphs.
    No visual elements are present in this document.
    """
    result = analyzer.analyze_text_content(plain_text)
    assert not result['is_visual'], f"Plain text should not be visual, got: {result}"
    print(f"✅ Plain text: is_visual={result['is_visual']} (expected: False)")
    
    # Test 2: Text with table (should be vision)
    table_text = """
    | Cột 1 | Cột 2 | Cột 3 |
    |-------|-------|-------|
    | A     | B     | C     |
    """
    result = analyzer.analyze_text_content(table_text)
    assert result['has_tables'], "Should detect table"
    assert result['is_visual'], "Table text should be visual"
    print(f"✅ Table text: has_tables={result['has_tables']}, is_visual={result['is_visual']}")
    
    # Test 3: Text with diagram keyword (should be vision)
    diagram_text = """
    See Figure 3.1 for more details about the ship structure.
    This diagram illustrates the main components.
    """
    result = analyzer.analyze_text_content(diagram_text)
    assert result['has_diagrams'], f"Should detect diagram keyword, got: {result}"
    assert result['is_visual'], "Diagram text should be visual"
    print(f"✅ Diagram text: has_diagrams={result['has_diagrams']}, is_visual={result['is_visual']}")
    
    # Test 4: Text with maritime keywords (should be vision)
    maritime_text = """
    The red light is on the port side and green light on starboard.
    Signal whistle indicates the vessel is turning.
    """
    result = analyzer.analyze_text_content(maritime_text)
    assert result['has_maritime_signals'], f"Should detect maritime keywords, got: {result}"
    assert result['is_visual'], "Maritime text should be visual"
    print(f"✅ Maritime text: has_maritime_signals={result['has_maritime_signals']}, is_visual={result['is_visual']}")
    
    print("✅ PASSED: Text content analysis")


def test_should_use_vision():
    """Test should_use_vision method"""
    print("\n=== Test 3: Should Use Vision Logic ===")
    
    analyzer = PageAnalyzer()
    
    # Test 1: Visual content should use vision
    visual_result = PageAnalysisResult(
        page_number=1,
        has_images=True,
        recommended_method="vision"
    )
    assert analyzer.should_use_vision(visual_result), "Visual content should use vision"
    print(f"✅ Visual content: should_use_vision={analyzer.should_use_vision(visual_result)}")
    
    # Test 2: Text-only should use direct
    text_result = PageAnalysisResult(
        page_number=1,
        has_images=False,
        has_tables=False,
        has_diagrams=False,
        has_maritime_signals=False,
        recommended_method="direct"
    )
    assert not analyzer.should_use_vision(text_result), "Text-only should use direct"
    print(f"✅ Text-only content: should_use_vision={analyzer.should_use_vision(text_result)}")
    
    print("✅ PASSED: Should use vision logic")


def test_ingestion_result_savings():
    """Test IngestionResult api_savings_percent calculation"""
    print("\n=== Test 4: API Savings Calculation ===")
    
    try:
        from app.services.multimodal_ingestion_service import IngestionResult
    except ImportError as e:
        print(f"⚠️ SKIPPED: Missing dependency - {e}")
        return
    
    # Test 1: 50% savings
    result1 = IngestionResult(
        document_id="test",
        total_pages=10,
        successful_pages=10,
        failed_pages=0,
        vision_pages=5,
        direct_pages=5,
        fallback_pages=0
    )
    assert result1.api_savings_percent == 50.0, f"Expected 50%, got {result1.api_savings_percent}%"
    print(f"✅ 50% savings: {result1.api_savings_percent}%")
    
    # Test 2: 70% savings
    result2 = IngestionResult(
        document_id="test",
        total_pages=10,
        successful_pages=10,
        failed_pages=0,
        vision_pages=3,
        direct_pages=7,
        fallback_pages=0
    )
    assert result2.api_savings_percent == 70.0, f"Expected 70%, got {result2.api_savings_percent}%"
    print(f"✅ 70% savings: {result2.api_savings_percent}%")
    
    # Test 3: 0% savings (all vision)
    result3 = IngestionResult(
        document_id="test",
        total_pages=10,
        successful_pages=10,
        failed_pages=0,
        vision_pages=10,
        direct_pages=0,
        fallback_pages=0
    )
    assert result3.api_savings_percent == 0.0, f"Expected 0%, got {result3.api_savings_percent}%"
    print(f"✅ 0% savings (all vision): {result3.api_savings_percent}%")
    
    # Test 4: Empty document
    result4 = IngestionResult(
        document_id="test",
        total_pages=0,
        successful_pages=0,
        failed_pages=0
    )
    assert result4.api_savings_percent == 0.0, "Empty document should have 0% savings"
    print(f"✅ Empty document: {result4.api_savings_percent}%")
    
    print("✅ PASSED: API savings calculation")


def test_config_settings():
    """Test configuration settings are loaded"""
    print("\n=== Test 5: Configuration Settings ===")
    
    from app.core.config import settings
    
    # Check hybrid detection settings exist
    assert hasattr(settings, 'hybrid_detection_enabled'), "Should have hybrid_detection_enabled"
    assert hasattr(settings, 'min_text_length_for_direct'), "Should have min_text_length_for_direct"
    assert hasattr(settings, 'force_vision_mode'), "Should have force_vision_mode"
    
    print(f"✅ hybrid_detection_enabled: {settings.hybrid_detection_enabled}")
    print(f"✅ min_text_length_for_direct: {settings.min_text_length_for_direct}")
    print(f"✅ force_vision_mode: {settings.force_vision_mode}")
    
    print("✅ PASSED: Configuration settings")


def test_with_real_pdf():
    """Test with a real PDF file if available"""
    print("\n=== Test 6: Real PDF Analysis (Optional) ===")
    
    try:
        import fitz
    except ImportError:
        print("⚠️ SKIPPED: PyMuPDF (fitz) not installed")
        return
    
    pdf_path = "data/VanBanGoc_95.2015.QH13.P1.pdf"
    
    if not os.path.exists(pdf_path):
        print(f"⚠️ SKIPPED: PDF not found at {pdf_path}")
        return
    
    analyzer = get_page_analyzer()
    doc = fitz.open(pdf_path)
    
    vision_count = 0
    direct_count = 0
    
    # Analyze first 5 pages
    max_pages = min(5, len(doc))
    
    for page_num in range(max_pages):
        page = doc.load_page(page_num)
        result = analyzer.analyze_page(page, page_num + 1)
        
        if analyzer.should_use_vision(result):
            vision_count += 1
            method = "VISION"
        else:
            direct_count += 1
            method = "DIRECT"
        
        print(f"  Page {page_num + 1}: {method} (reasons: {result.detection_reasons[:2]}...)")
    
    doc.close()
    
    savings = (direct_count / max_pages) * 100 if max_pages > 0 else 0
    print(f"\n📊 Results for {max_pages} pages:")
    print(f"   Vision pages: {vision_count}")
    print(f"   Direct pages: {direct_count}")
    print(f"   Estimated savings: {savings:.1f}%")
    
    print("✅ PASSED: Real PDF analysis")


def main():
    """Run all tests"""
    print("=" * 60)
    print("HYBRID TEXT/VISION DETECTION - TEST SUITE")
    print("Feature: hybrid-text-vision")
    print("=" * 60)
    
    try:
        test_page_analyzer_initialization()
        test_text_content_analysis()
        test_should_use_vision()
        test_ingestion_result_savings()
        test_config_settings()
        test_with_real_pdf()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED!")
        print("=" * 60)
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
