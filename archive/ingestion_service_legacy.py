"""
ARCHIVED: Legacy Ingestion Service for Neo4j Knowledge Graph

This file has been archived as part of the sparse-search-migration.
Neo4j has been replaced by PostgreSQL (Neon) for all search functionality.

Original location: app/services/ingestion_service.py
Archived date: 2025-12-09
Reason: Neo4j-based ingestion replaced by MultimodalIngestionService (PostgreSQL + Supabase)

See: .kiro/specs/sparse-search-migration/design.md for migration details.
"""

# Original content below for reference
# =====================================

"""
Ingestion Service for Knowledge Ingestion feature.

Handles PDF upload, processing, and Neo4j storage.
Integrates with Hybrid Search for embedding storage.

Feature: knowledge-ingestion, hybrid-search
Requirements: 1.1, 4.1, 5.1, 5.2, 6.1, 6.2, 6.3
"""

import logging
import os
import tempfile
from datetime import datetime
from typing import Dict, List, Optional
from uuid import uuid4

# NOTE: These imports would fail now as dependencies have been removed
# from app.engine.pdf_processor import PDFProcessor
# from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
# from app.models.ingestion_job import JobStatus
# from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository
# from app.repositories.dense_search_repository import DenseSearchRepository

logger = logging.getLogger(__name__)


# In-memory job storage (for MVP - can be replaced with PostgreSQL later)
_jobs: Dict[str, dict] = {}


class IngestionService:
    """
    ARCHIVED: Service for managing document ingestion into Neo4j Knowledge Graph.
    
    This has been replaced by MultimodalIngestionService which uses:
    - PyMuPDF for PDF processing
    - Supabase Storage for images
    - Gemini Vision for text extraction
    - Neon PostgreSQL for storage
    
    **Feature: knowledge-ingestion**
    **Validates: Requirements 1.1, 4.1, 5.1, 5.2, 6.1, 6.2, 6.3**
    """
    pass  # Implementation archived - see original file in git history
