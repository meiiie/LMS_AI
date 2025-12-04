"""Test list_documents directly."""
import sys
sys.path.insert(0, ".")
import asyncio
from app.services.ingestion_service import get_ingestion_service

async def main():
    service = get_ingestion_service()
    print("Testing list_documents...")
    
    # Check repo
    repo = service._get_repo()
    print(f"Repo available: {repo is not None}")
    if repo:
        print(f"Repo is_available: {repo.is_available()}")
    
    # Call list_documents
    docs = await service.list_documents(page=1, limit=20)
    print(f"Documents returned: {len(docs)}")
    for doc in docs:
        print(f"  - {doc}")

if __name__ == "__main__":
    asyncio.run(main())
