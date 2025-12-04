"""Check Neo4j Document nodes."""
import sys
sys.path.insert(0, ".")
from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository

repo = Neo4jKnowledgeRepository()
if repo.is_available():
    with repo._driver.session() as session:
        # Check Document nodes
        result = session.run("MATCH (d:Document) RETURN count(d) as count")
        doc_count = result.single()["count"]
        print(f"Document nodes: {doc_count}")
        
        # Check Knowledge nodes
        result = session.run("MATCH (k:Knowledge) RETURN count(k) as count")
        k_count = result.single()["count"]
        print(f"Knowledge nodes: {k_count}")
        
        # List documents
        print("\nDocuments:")
        result = session.run("MATCH (d:Document) RETURN d.id as id, d.filename as filename LIMIT 5")
        for r in result:
            print(f"  - {r['id']}: {r['filename']}")
        
        # Check if Knowledge nodes have document_id
        print("\nKnowledge nodes with document_id:")
        result = session.run("MATCH (k:Knowledge) WHERE k.document_id IS NOT NULL RETURN count(k) as count")
        print(f"  With document_id: {result.single()['count']}")
        
        result = session.run("MATCH (k:Knowledge) WHERE k.document_id IS NULL RETURN count(k) as count")
        print(f"  Without document_id: {result.single()['count']}")
else:
    print("Neo4j not available")
