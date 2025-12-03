"""Check Neo4j data after ingestion."""
import sys
sys.path.insert(0, '.')

from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository

def main():
    repo = Neo4jKnowledgeRepository()
    print(f"Neo4j available: {repo.is_available()}")
    
    if not repo.is_available():
        print("Neo4j not available!")
        return
    
    with repo._driver.session() as session:
        # Count Knowledge nodes
        result = session.run("MATCH (k:Knowledge) RETURN count(k) as count")
        count = result.single()["count"]
        print(f"\nTotal Knowledge nodes: {count}")
        
        # Count Documents
        result = session.run("MATCH (d:Document) RETURN count(d) as count")
        doc_count = result.single()["count"]
        print(f"Total Document nodes: {doc_count}")
        
        # Get sample Knowledge nodes
        print("\nSample Knowledge nodes:")
        result = session.run("""
            MATCH (k:Knowledge) 
            RETURN k.title as title, k.category as category, k.source as source
            LIMIT 5
        """)
        for r in result:
            title = r["title"][:80] if r["title"] else "N/A"
            print(f"  - [{r['category']}] {title}...")
        
        # Get Documents
        print("\nDocuments:")
        result = session.run("""
            MATCH (d:Document) 
            RETURN d.filename as filename, d.category as category, d.nodes_count as nodes
        """)
        for r in result:
            print(f"  - {r['filename']} ({r['category']}) - {r['nodes']} nodes")
        
        # Category breakdown
        print("\nCategory breakdown:")
        result = session.run("""
            MATCH (k:Knowledge)
            RETURN k.category as category, count(k) as count
            ORDER BY count DESC
        """)
        for r in result:
            print(f"  - {r['category']}: {r['count']} nodes")

if __name__ == "__main__":
    main()
