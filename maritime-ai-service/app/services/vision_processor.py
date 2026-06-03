"""
Vision Processor - Page-level text extraction and storage pipeline.

Handles hybrid text/vision extraction, semantic chunking, embedding generation,
database storage, and entity extraction for GraphRAG.

Split from multimodal_ingestion_service.py for single-responsibility.

**Feature: multimodal-rag-vision, hybrid-text-vision, semantic-chunking, document-kg**
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import List, Optional, TYPE_CHECKING
from datetime import datetime, timezone

if TYPE_CHECKING:
    import fitz
    from app.engine.bounding_box_extractor import BoundingBoxExtractor
    from app.engine.context_enricher import ContextEnricher
    from app.engine.embedding_runtime import EmbeddingBackendProtocol
    from app.engine.multi_agent.agents.kg_builder_agent import KGBuilderAgentNode
    from app.engine.page_analyzer import PageAnalyzer
    from app.engine.vision_extractor import VisionExtractor
    from app.repositories.neo4j_knowledge_repository import Neo4jKnowledgeRepository
    from app.services.chunking_service import SemanticChunker
    from app.services.object_storage import ObjectStorageClient

from PIL import Image

from app.core.config import settings
from app.core.database import get_shared_session_factory
from app.repositories.knowledge_search_org_scope import (
    log_knowledge_search_scope_blocked,
    resolve_knowledge_search_org_scope,
)
from app.services.vision_processor_runtime_bindings import (
    ChunkResult,
    PageResult,
    _analyze_image_with_vision,
    _fetch_image_as_base64,
)

logger = logging.getLogger(__name__)


class VisionProcessor:
    """
    Handles page-level text extraction and storage pipeline.

    Responsibilities:
    - Hybrid detection (direct PyMuPDF vs Vision API extraction)
    - Image upload to object storage (MinIO/S3)
    - Semantic chunking
    - Contextual RAG enrichment
    - Embedding generation and database storage
    - Entity extraction for GraphRAG

    **Feature: semantic-chunking, hybrid-text-vision, contextual-rag, document-kg**
    """

    def __init__(
        self,
        storage: ObjectStorageClient,
        vision: VisionExtractor,
        embeddings: EmbeddingBackendProtocol,
        chunker: SemanticChunker,
        page_analyzer: PageAnalyzer,
        bbox_extractor: BoundingBoxExtractor,
        context_enricher: ContextEnricher,
        kg_builder: KGBuilderAgentNode,
        neo4j: Neo4jKnowledgeRepository,
        entity_extraction_enabled: bool,
        hybrid_detection_enabled: bool,
        force_vision_mode: bool,
        min_text_length: int
    ):
        """
        Initialize VisionProcessor with all required services.

        Args:
            storage: Object storage client
            vision: Vision extraction service
            embeddings: Embedding generation service
            chunker: Semantic chunking service
            page_analyzer: Page analyzer for hybrid detection
            bbox_extractor: Bounding box extractor
            context_enricher: Context enricher for contextual RAG
            kg_builder: KG Builder Agent for entity extraction
            neo4j: Neo4j repository for storing entities
            entity_extraction_enabled: Whether to extract entities
            hybrid_detection_enabled: Whether hybrid detection is enabled
            force_vision_mode: Whether to force vision mode
            min_text_length: Minimum text length for direct extraction
        """
        self.storage = storage
        self.vision = vision
        self.embeddings = embeddings
        self.chunker = chunker
        self.page_analyzer = page_analyzer
        self.bbox_extractor = bbox_extractor
        self.context_enricher = context_enricher
        self.kg_builder = kg_builder
        self.neo4j = neo4j
        self.entity_extraction_enabled = entity_extraction_enabled
        self.hybrid_detection_enabled = hybrid_detection_enabled
        self.force_vision_mode = force_vision_mode
        self.min_text_length = min_text_length

    def extract_direct(self, page: "fitz.Page") -> str:
        """
        Extract text directly from PDF page using PyMuPDF.

        This is the "free" extraction method that doesn't use Vision API.

        Args:
            page: PyMuPDF page object

        Returns:
            Extracted text content

        **Feature: hybrid-text-vision**
        **Property 9: Direct Extraction Text Quality**
        **Validates: Requirements 5.1, 5.2**
        """
        try:
            # Extract text with layout preservation
            text = page.get_text("text")

            # Clean up excessive whitespace while preserving structure
            lines = text.split('\n')
            cleaned_lines = []
            for line in lines:
                stripped = line.strip()
                if stripped:
                    cleaned_lines.append(stripped)
                elif cleaned_lines and cleaned_lines[-1]:
                    # Preserve paragraph breaks (empty line after content)
                    cleaned_lines.append('')

            return '\n'.join(cleaned_lines)

        except Exception as e:
            logger.error("Direct extraction failed: %s", e)
            return ""

    async def process_page(
        self,
        image: Image.Image,
        document_id: str,
        page_number: int,
        pdf_page: Optional["fitz.Page"] = None,
        domain_id: Optional[str] = None,
        organization_id: Optional[str] = None,
        source_name: Optional[str] = None
    ):
        """
        Process a single page through the pipeline with semantic chunking.

        Steps:
        1. Upload image to object storage
        2. Analyze page for hybrid detection (if enabled)
        3. Extract text using Vision OR Direct method
        4. Apply semantic chunking
        5. Generate embedding per chunk
        6. Store chunks in database

        **Feature: semantic-chunking, hybrid-text-vision**
        **Validates: Requirements 1.1, 1.4, 7.1, 7.2**
        """
        domain_id = domain_id or settings.default_domain
        extraction_method = "vision"
        was_fallback = False

        # Step 1: Upload to object storage
        upload_result = await self.storage.upload_pil_image(
            image=image,
            document_id=document_id,
            page_number=page_number
        )

        if not upload_result.success:
            return PageResult(
                page_number=page_number,
                success=False,
                error=f"Upload failed: {upload_result.error}"
            )

        image_url = upload_result.public_url

        # Step 2: Hybrid detection - decide extraction method
        text = None

        if self.hybrid_detection_enabled and pdf_page is not None and not self.force_vision_mode:
            # Analyze page to determine best extraction method
            analysis = self.page_analyzer.analyze_page(pdf_page, page_number)

            if not self.page_analyzer.should_use_vision(analysis):
                # Try direct extraction first
                extraction_method = "direct"
                text = self.extract_direct(pdf_page)

                # Fallback to vision if direct extraction is too short
                if len(text.strip()) < self.min_text_length:
                    logger.info(
                        "Page %d: Direct extraction too short "
                        "(%d chars), falling back to Vision",
                        page_number, len(text),
                    )
                    text = None
                    extraction_method = "vision"
                    was_fallback = True
                else:
                    logger.info(
                        "Page %d: Using direct extraction "
                        "(%d chars, reasons: %s)",
                        page_number, len(text), analysis.detection_reasons,
                    )

        # Step 3: Extract text using Vision (if not already extracted)
        if text is None:
            extraction_method = "vision"
            extraction_result = await self.vision.extract_from_image(image)

            if not extraction_result.success:
                return PageResult(
                    page_number=page_number,
                    success=False,
                    image_url=image_url,
                    error=f"Extraction failed: {extraction_result.error}",
                    extraction_method=extraction_method,
                    was_fallback=was_fallback
                )

            text = extraction_result.text

            # Validate extraction
            if not self.vision.validate_extraction(extraction_result):
                logger.warning("Page %d extraction may be incomplete", page_number)

        # Step 4: Apply semantic chunking
        page_metadata = {
            'document_id': document_id,
            'page_number': page_number,
            'image_url': image_url,
            'processing_timestamp': datetime.now(timezone.utc).isoformat(),
            'source_type': 'pdf',
            'extraction_method': extraction_method,  # Feature: hybrid-text-vision
            'published_date': None,  # Temporal metadata — filled via API or post-ingestion
            'source_name': source_name or document_id,  # Temporal metadata — filename fallback
        }

        try:
            chunks = await self.chunker.chunk_page_content(text, page_metadata)
            logger.info("Page %d: Created %d semantic chunks", page_number, len(chunks))
        except Exception as e:
            logger.warning("Chunking failed, falling back to single chunk: %s", e)
            # Fallback: store entire page as one chunk
            chunks = [ChunkResult(
                chunk_index=0,
                content=text,
                content_type='text',
                confidence_score=1.0,
                metadata=page_metadata
            )]

        # Step 4.5: Contextual RAG - Enrich chunks with LLM-generated context
        # Feature: contextual-rag (Anthropic-style Context Enrichment)
        if settings.contextual_rag_enabled and len(chunks) > 0:
            try:
                # Get total pages from metadata or estimate
                total_pages_in_doc = page_metadata.get('total_pages', 1)

                chunks = await self.context_enricher.enrich_chunks(
                    chunks=chunks,
                    document_id=document_id,
                    document_title=document_id,  # Use document_id as title
                    total_pages=total_pages_in_doc,
                    batch_size=settings.contextual_rag_batch_size
                )
                logger.info("Page %d: Contextual enrichment complete", page_number)
            except Exception as ctx_err:
                logger.warning("Context enrichment failed, continuing without: %s", ctx_err)

        # Step 4.7: Visual description generation (Sprint 179+)
        # For pages with visual content (tables, diagrams), generate a descriptive chunk
        if settings.enable_visual_rag and extraction_method == "vision":
            has_visual = any(
                c.content_type in ("table", "diagram_reference", "formula")
                for c in chunks
            )
            if has_visual and image_url:
                try:
                    img_b64 = await _fetch_image_as_base64(image_url)
                    if img_b64:
                        visual_desc = await _analyze_image_with_vision(
                            img_b64,
                            query=f"Mô tả nội dung trang {page_number} của tài liệu {document_id}",
                        )
                        if visual_desc:
                            desc_metadata = dict(page_metadata)
                            desc_metadata["visual_description"] = True
                            chunks.append(ChunkResult(
                                chunk_index=len(chunks),
                                content=f"[Mô tả hình ảnh trang {page_number}]: {visual_desc}",
                                content_type="visual_description",
                                confidence_score=0.85,
                                metadata=desc_metadata,
                            ))
                            logger.info("Page %d: Generated visual description chunk", page_number)
                except Exception as vis_err:
                    logger.warning("Visual description generation failed for page %d: %s", page_number, vis_err)

        # Step 5 & 6: Generate embedding and store each chunk
        # Feature: source-highlight-citation - Extract bounding boxes for each chunk
        successful_chunks = 0
        for chunk in chunks:
            try:
                # Generate embedding for chunk
                # Use contextual_content if available (better retrieval), fallback to original
                text_to_embed = chunk.contextual_content or chunk.content
                embedding = await self.embeddings.aembed_query(text_to_embed)

                # Extract bounding boxes for this chunk (Feature: source-highlight-citation)
                bounding_boxes = None
                if pdf_page is not None:
                    try:
                        boxes = self.bbox_extractor.extract_text_with_boxes(
                            page=pdf_page,
                            text_content=chunk.content
                        )
                        if boxes:
                            bounding_boxes = [box.to_dict() for box in boxes]
                    except Exception as bbox_err:
                        logger.debug("Bounding box extraction failed for chunk %d: %s", chunk.chunk_index, bbox_err)

                # Store chunk in database
                await self.store_chunk_in_database(
                    document_id=document_id,
                    page_number=page_number,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    contextual_content=chunk.contextual_content,  # Feature: contextual-rag
                    embedding=embedding,
                    image_url=image_url,
                    content_type=chunk.content_type,
                    confidence_score=chunk.confidence_score,
                    metadata=chunk.metadata,
                    bounding_boxes=bounding_boxes,  # Feature: source-highlight-citation
                    domain_id=domain_id,
                    organization_id=organization_id
                )
                successful_chunks += 1

            except Exception as e:
                logger.error("Failed to process chunk %d on page %d: %s", chunk.chunk_index, page_number, e)
                continue

        # Step 6.5: Entity Extraction for GraphRAG (Feature: document-kg)
        # Extract entities from page text and store in Neo4j
        if self.entity_extraction_enabled and successful_chunks > 0:
            try:
                await self.extract_and_store_entities(
                    text=text,
                    document_id=document_id,
                    page_number=page_number,
                    organization_id=organization_id,
                )
            except Exception as e:
                logger.warning("Entity extraction failed for page %d: %s", page_number, e)

        if successful_chunks == 0:
            return PageResult(
                page_number=page_number,
                success=False,
                image_url=image_url,
                error="All chunks failed to process",
                extraction_method=extraction_method,
                was_fallback=was_fallback
            )

        return PageResult(
            page_number=page_number,
            success=True,
            image_url=image_url,
            text_length=len(text),
            total_chunks=successful_chunks,
            extraction_method=extraction_method,
            was_fallback=was_fallback
        )

    async def store_chunk_in_database(
        self,
        document_id: str,
        page_number: int,
        chunk_index: int,
        content: str,
        contextual_content: Optional[str],  # Feature: contextual-rag
        embedding: List[float],
        image_url: str,
        content_type: str = 'text',
        confidence_score: float = 1.0,
        metadata: Optional[dict] = None,
        bounding_boxes: Optional[List[dict]] = None,  # Feature: source-highlight-citation
        domain_id: Optional[str] = None,
        organization_id: Optional[str] = None
    ):
        """
        Store a semantic chunk in Neon database.

        **Feature: semantic-chunking**
        **Property 10: Chunk Index Sequential**
        **Property 13: Database Round-Trip Consistency**
        **Validates: Requirements 2.5, 3.5, 5.5**
        """
        domain_id = domain_id or settings.default_domain
        from sqlalchemy import text as sql_text

        org_scope = resolve_knowledge_search_org_scope(organization_id, write=True)
        if not org_scope.write_allowed or not org_scope.org_id:
            log_knowledge_search_scope_blocked(
                logger,
                "vision_store_chunk",
                org_scope,
                node_id=document_id,
            )
            raise RuntimeError("Organization context required for knowledge ingestion")
        organization_id = org_scope.org_id

        session_factory = get_shared_session_factory()

        from app.services.embedding_space_guard import stamp_embedding_metadata

        # Convert metadata to JSON string
        metadata_json = json.dumps(
            stamp_embedding_metadata(metadata),
            ensure_ascii=False,
        )

        # Convert bounding_boxes to JSON string (Feature: source-highlight-citation)
        bounding_boxes_json = json.dumps(bounding_boxes) if bounding_boxes else None

        with session_factory() as session:
            # Check if record exists (by document_id, page_number, chunk_index)
            result = session.execute(
                sql_text("""
                    SELECT id FROM knowledge_embeddings
                    WHERE document_id = :doc_id
                    AND page_number = :page_num
                    AND chunk_index = :chunk_idx
                    AND organization_id = :org_id
                """),
                {
                    "doc_id": document_id,
                    "page_num": page_number,
                    "chunk_idx": chunk_index,
                    "org_id": organization_id,
                }
            ).fetchone()

            if result:
                # Update existing record
                session.execute(
                    sql_text("""
                        UPDATE knowledge_embeddings
                        SET content = :content,
                            contextual_content = :contextual_content,
                            embedding = :embedding,
                            image_url = :image_url,
                            content_type = :content_type,
                            confidence_score = :confidence_score,
                            metadata = :metadata,
                            bounding_boxes = :bounding_boxes,
                            domain_id = :domain_id,
                            organization_id = :org_id,
                            updated_at = NOW()
                        WHERE document_id = :doc_id
                        AND page_number = :page_num
                        AND chunk_index = :chunk_idx
                        AND organization_id = :org_id
                    """),
                    {
                        "content": content,
                        "contextual_content": contextual_content,
                        "embedding": embedding,
                        "image_url": image_url,
                        "content_type": content_type,
                        "confidence_score": confidence_score,
                        "metadata": metadata_json,
                        "bounding_boxes": bounding_boxes_json,
                        "domain_id": domain_id,
                        "org_id": organization_id,
                        "doc_id": document_id,
                        "page_num": page_number,
                        "chunk_idx": chunk_index
                    }
                )
            else:
                # Insert new record
                session.execute(
                    sql_text("""
                        INSERT INTO knowledge_embeddings
                        (id, content, contextual_content, embedding, document_id, page_number, chunk_index,
                         image_url, content_type, confidence_score, metadata, source, bounding_boxes, domain_id,
                         organization_id)
                        VALUES (:id, :content, :contextual_content, :embedding, :doc_id, :page_num, :chunk_idx,
                                :image_url, :content_type, :confidence_score, :metadata, :source, :bounding_boxes,
                                :domain_id, :org_id)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "content": content,
                        "contextual_content": contextual_content,
                        "embedding": embedding,
                        "doc_id": document_id,
                        "page_num": page_number,
                        "chunk_idx": chunk_index,
                        "image_url": image_url,
                        "content_type": content_type,
                        "confidence_score": confidence_score,
                        "metadata": metadata_json,
                        "source": f"{document_id}_page_{page_number}_chunk_{chunk_index}",
                        "bounding_boxes": bounding_boxes_json,
                        "domain_id": domain_id,
                        "org_id": organization_id
                    }
                )

            session.commit()

        logger.debug("Stored chunk %d of page %d in database", chunk_index, page_number)

    async def extract_and_store_entities(
        self,
        text: str,
        document_id: str,
        page_number: int,
        organization_id: Optional[str] = None,
    ):
        """
        Extract entities from page text and store in Neo4j.

        **Feature: document-kg**
        **CHI THI KY THUAT SO 29: Automated Knowledge Graph Construction**

        Args:
            text: Page text content
            document_id: Document ID
            page_number: Page number
            organization_id: Org ID for multi-tenant isolation
        """
        if not self.kg_builder.is_available():
            return

        if not self.neo4j.is_available():
            logger.debug("Neo4j not available, skipping entity storage")
            return

        # Extract entities using KG Builder Agent
        source = f"{document_id}_page_{page_number}"
        extraction = await self.kg_builder.extract(text, source)

        if not extraction.entities:
            return

        # Store entities in Neo4j
        entity_count = 0
        for entity in extraction.entities:
            success = await self.neo4j.create_entity(
                entity_id=entity.id,
                entity_type=entity.entity_type,
                name=entity.name,
                name_vi=entity.name_vi,
                description=entity.description,
                document_id=document_id,
                chunk_id=source,
                organization_id=organization_id,
            )
            if success:
                entity_count += 1

        # Store relations
        relation_count = 0
        for relation in extraction.relations:
            success = await self.neo4j.create_entity_relation(
                source_id=relation.source_id,
                target_id=relation.target_id,
                relation_type=relation.relation_type,
                description=relation.description,
                organization_id=organization_id,
            )
            if success:
                relation_count += 1

        logger.info(
            "[GraphRAG] Page %d: Extracted %d entities, "
            "%d relations",
            page_number, entity_count, relation_count,
        )
