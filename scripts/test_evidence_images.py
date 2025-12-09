"""Test evidence images in API response"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

API_URL = "https://maritime-ai-chatbot.onrender.com"
API_KEY = "secret_key_cho_team_lms"

r = httpx.post(
    f"{API_URL}/api/v1/chat",
    json={
        "message": "Bộ luật hàng hải Việt Nam 2015",
        "session_id": "test_multimodal_123",
        "user_id": "test_user",
        "role": "student"
    },
    headers={"X-API-Key": API_KEY},
    timeout=60
)

data = r.json()
sources = data.get("data", {}).get("sources", [])
evidence = data.get("data", {}).get("evidence_images", [])

print(f"Sources: {len(sources)}")
print(f"Evidence Images: {len(evidence)}")

for i, s in enumerate(sources[:3]):
    title = s.get("title", "N/A")[:50]
    print(f"  {i+1}. {title}")
    if "image_url" in s and s["image_url"]:
        print(f"     Image: {s['image_url'][:60]}...")

if evidence:
    print("\nEvidence Images:")
    for img in evidence:
        print(f"  - Page {img.get('page_number')}: {img.get('url', '')[:50]}...")
