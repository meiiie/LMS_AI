"""Quick check for ingested data"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.core.database import get_shared_session_factory
from sqlalchemy import text

session_factory = get_shared_session_factory()
with session_factory() as session:
    result = session.execute(text("""
        SELECT id, source, image_url, page_number 
        FROM knowledge_embeddings 
        WHERE document_id = 'colregs_vn_2015_test'
        LIMIT 5
    """))
    rows = result.fetchall()
    print(f"Found {len(rows)} records")
    for row in rows:
        has_img = "YES" if row[2] else "NO"
        print(f"  ID: {str(row[0])[:15]}..., Page: {row[3]}, Image: {has_img}")
        if row[2]:
            print(f"    URL: {str(row[2])[:60]}...")
