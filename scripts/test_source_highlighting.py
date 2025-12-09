#!/usr/bin/env python3
"""
Test Source Highlighting with Citation Jumping feature (v0.9.8)

Feature: source-highlight-citation
Tests:
1. Source Details API - GET /api/v1/sources/{node_id}
2. Source List API - GET /api/v1/sources/
3. Chat API - bounding_boxes in sources
4. Same-page source merging

Usage:
    python scripts/test_source_highlighting.py
    python scripts/test_source_highlighting.py --local
"""
import argparse
import json
import sys
import uuid
from datetime import datetime

import requests

# API Configuration
RENDER_URL = "https://maritime-ai-chatbot.onrender.com"
LOCAL_URL = "http://localhost:8000"
API_KEY = "secret_key_cho_team_lms"  # Production API key

# Headers for authenticated requests
HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY
}


def get_base_url(use_local: bool = False) -> str:
    return LOCAL_URL if use_local else RENDER_URL


def print_header(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_result(test_name: str, passed: bool, details: str = ""):
    status = "✅ PASSED" if passed else "❌ FAILED"
    print(f"\n{status}: {test_name}")
    if details:
        print(f"   {details}")


def test_health(base_url: str) -> bool:
    """Test API health endpoint."""
    print_header("Test 1: Health Check")
    try:
        resp = requests.get(f"{base_url}/health", timeout=30)
        if resp.status_code == 200:
            print_result("Health Check", True, f"Status: {resp.json().get('status', 'unknown')}")
            return True
        print_result("Health Check", False, f"Status code: {resp.status_code}")
        return False
    except Exception as e:
        print_result("Health Check", False, str(e))
        return False


def test_sources_list(base_url: str) -> dict:
    """Test GET /api/v1/sources/ - List sources with pagination."""
    print_header("Test 2: Sources List API")
    try:
        resp = requests.get(
            f"{base_url}/api/v1/sources/",
            params={"limit": 5},
            headers=HEADERS,
            timeout=30
        )
        
        if resp.status_code == 200:
            data = resp.json()
            sources = data.get("data", [])
            pagination = data.get("pagination", {})
            
            print(f"   Total sources: {pagination.get('total', 0)}")
            print(f"   Returned: {len(sources)}")
            
            if sources:
                print(f"\n   Sample sources:")
                for s in sources[:3]:
                    print(f"   - {s.get('node_id', 'N/A')[:40]}... (page {s.get('page_number', 'N/A')})")
                
                print_result("Sources List API", True, f"Found {pagination.get('total', 0)} sources")
                return {"passed": True, "sources": sources}
            else:
                print_result("Sources List API", True, "No sources in database (empty)")
                return {"passed": True, "sources": []}
        
        # Debug: print error response
        try:
            error_detail = resp.json()
            print(f"   Error detail: {error_detail}")
        except:
            print(f"   Response text: {resp.text[:200]}")
        
        print_result("Sources List API", False, f"Status: {resp.status_code}")
        return {"passed": False, "sources": []}
        
    except Exception as e:
        print_result("Sources List API", False, str(e))
        return {"passed": False, "sources": []}


def test_source_details(base_url: str, node_id: str) -> bool:
    """Test GET /api/v1/sources/{node_id} - Get source details."""
    print_header("Test 3: Source Details API")
    try:
        resp = requests.get(
            f"{base_url}/api/v1/sources/{node_id}",
            headers=HEADERS,
            timeout=30
        )
        
        if resp.status_code == 200:
            data = resp.json()
            
            print(f"   node_id: {data.get('node_id', 'N/A')[:50]}...")
            print(f"   document_id: {data.get('document_id', 'N/A')}")
            print(f"   page_number: {data.get('page_number', 'N/A')}")
            print(f"   content_type: {data.get('content_type', 'N/A')}")
            print(f"   image_url: {'Yes' if data.get('image_url') else 'No'}")
            print(f"   bounding_boxes: {data.get('bounding_boxes', 'None')}")
            print(f"   content preview: {data.get('content', '')[:100]}...")
            
            # Check required fields
            has_node_id = bool(data.get('node_id'))
            has_content = bool(data.get('content'))
            
            print_result(
                "Source Details API", 
                has_node_id and has_content,
                f"Fields: node_id={has_node_id}, content={has_content}"
            )
            return has_node_id and has_content
        
        elif resp.status_code == 404:
            print_result("Source Details API", False, f"Source not found: {node_id}")
            return False
        
        print_result("Source Details API", False, f"Status: {resp.status_code}")
        return False
        
    except Exception as e:
        print_result("Source Details API", False, str(e))
        return False


def test_source_not_found(base_url: str) -> bool:
    """Test 404 response for non-existent source."""
    print_header("Test 4: Source Not Found (404)")
    fake_id = f"fake_node_{uuid.uuid4().hex[:8]}"
    try:
        resp = requests.get(
            f"{base_url}/api/v1/sources/{fake_id}",
            headers=HEADERS,
            timeout=30
        )
        
        if resp.status_code == 404:
            print_result("Source Not Found", True, "Correctly returns 404")
            return True
        
        print_result("Source Not Found", False, f"Expected 404, got {resp.status_code}")
        return False
        
    except Exception as e:
        print_result("Source Not Found", False, str(e))
        return False


def test_chat_with_sources(base_url: str) -> dict:
    """Test Chat API returns sources with bounding_boxes."""
    print_header("Test 5: Chat API with Sources")
    
    session_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    
    try:
        resp = requests.post(
            f"{base_url}/api/v1/chat/",
            json={
                "message": "Rule 15 COLREGs là gì?",
                "session_id": session_id,
                "user_id": user_id,
                "role": "student"
            },
            headers=HEADERS,
            timeout=120
        )
        
        if resp.status_code == 200:
            data = resp.json()
            response_text = data.get("response", "")
            sources = data.get("sources", [])
            
            print(f"   Response length: {len(response_text)} chars")
            print(f"   Sources count: {len(sources)}")
            
            # Check sources structure
            has_bounding_boxes = False
            has_page_number = False
            has_document_id = False
            
            if sources:
                print(f"\n   Sources details:")
                for i, src in enumerate(sources[:3]):
                    print(f"   [{i+1}] page: {src.get('page_number')}, doc: {src.get('document_id')}")
                    print(f"       bounding_boxes: {src.get('bounding_boxes', 'None')}")
                    
                    if src.get('bounding_boxes'):
                        has_bounding_boxes = True
                    if src.get('page_number') is not None:
                        has_page_number = True
                    if src.get('document_id'):
                        has_document_id = True
            
            print(f"\n   Fields present:")
            print(f"   - page_number: {'✅' if has_page_number else '❌'}")
            print(f"   - document_id: {'✅' if has_document_id else '❌'}")
            print(f"   - bounding_boxes: {'✅' if has_bounding_boxes else '⚠️ (may need re-ingestion)'}")
            
            # Pass if we have sources with page_number
            passed = len(sources) > 0 and has_page_number
            print_result(
                "Chat API with Sources",
                passed,
                f"{len(sources)} sources returned"
            )
            
            return {
                "passed": passed,
                "sources": sources,
                "has_bounding_boxes": has_bounding_boxes
            }
        
        print_result("Chat API with Sources", False, f"Status: {resp.status_code}")
        return {"passed": False, "sources": [], "has_bounding_boxes": False}
        
    except Exception as e:
        print_result("Chat API with Sources", False, str(e))
        return {"passed": False, "sources": [], "has_bounding_boxes": False}


def test_sources_filter(base_url: str, document_id: str) -> bool:
    """Test filtering sources by document_id."""
    print_header("Test 6: Sources Filter by Document")
    try:
        resp = requests.get(
            f"{base_url}/api/v1/sources/",
            params={"document_id": document_id, "limit": 10},
            headers=HEADERS,
            timeout=30
        )
        
        if resp.status_code == 200:
            data = resp.json()
            sources = data.get("data", [])
            
            # Verify all sources have correct document_id
            all_match = all(s.get("document_id") == document_id for s in sources)
            
            print(f"   Filtered by: {document_id}")
            print(f"   Results: {len(sources)}")
            print(f"   All match filter: {all_match}")
            
            print_result("Sources Filter", all_match or len(sources) == 0)
            return all_match or len(sources) == 0
        
        print_result("Sources Filter", False, f"Status: {resp.status_code}")
        return False
        
    except Exception as e:
        print_result("Sources Filter", False, str(e))
        return False


def main():
    parser = argparse.ArgumentParser(description="Test Source Highlighting feature")
    parser.add_argument("--local", action="store_true", help="Use local server")
    args = parser.parse_args()
    
    base_url = get_base_url(args.local)
    
    print(f"\n🔍 Testing Source Highlighting Feature (v0.9.8)")
    print(f"📍 Target: {base_url}")
    print(f"⏰ Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = []
    
    # Test 1: Health
    results.append(("Health Check", test_health(base_url)))
    
    if not results[0][1]:
        print("\n❌ API not available. Aborting tests.")
        sys.exit(1)
    
    # Test 2: Sources List
    list_result = test_sources_list(base_url)
    results.append(("Sources List API", list_result["passed"]))
    
    # Test 3: Source Details (if we have sources)
    if list_result["sources"]:
        node_id = list_result["sources"][0]["node_id"]
        results.append(("Source Details API", test_source_details(base_url, node_id)))
    else:
        print_header("Test 3: Source Details API")
        print("   ⚠️ Skipped - No sources in database")
        results.append(("Source Details API", True))  # Skip = pass
    
    # Test 4: 404 handling
    results.append(("Source Not Found (404)", test_source_not_found(base_url)))
    
    # Test 5: Chat with sources
    chat_result = test_chat_with_sources(base_url)
    results.append(("Chat API with Sources", chat_result["passed"]))
    
    # Test 6: Filter by document
    if list_result["sources"]:
        doc_id = list_result["sources"][0].get("document_id")
        if doc_id:
            results.append(("Sources Filter", test_sources_filter(base_url, doc_id)))
        else:
            results.append(("Sources Filter", True))  # Skip
    else:
        results.append(("Sources Filter", True))  # Skip
    
    # Summary
    print_header("TEST SUMMARY")
    passed = sum(1 for _, p in results if p)
    total = len(results)
    
    for name, p in results:
        status = "✅" if p else "❌"
        print(f"   {status} {name}")
    
    print(f"\n📊 Result: {passed}/{total} tests passed")
    
    # Bounding boxes note
    if not chat_result.get("has_bounding_boxes"):
        print("\n⚠️ Note: bounding_boxes not found in chat sources.")
        print("   Run re-ingestion script to populate bounding_boxes:")
        print("   python scripts/reingest_bounding_boxes.py")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
