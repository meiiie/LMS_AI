"""
Multimodal Ingestion Service for Vision-based RAG

CHỈ THỊ KỸ THUẬT SỐ 26: Multimodal RAG Pipeline
Full pipeline: PDF → Images → Supabase → Vision → Embeddings → Database

**Feature: multimodal-rag-vision**
**Validates: Requirements 2.1, 7.1, 7.4, 7.5**
"""
import logging
import os
import json
from typing import List, Optional
from dataclasses import dataclass, field
from pathlib import Path

from pdf2image import convert_from_path
from PIL import Image

from app.core.config import settings
from app.core.database import get_shared_session_factory
from app.services.supabase_storage import SupabaseStorageClient, get_storage_client
from app.services.chunking_service import SemanticChunker, get_semantic_chunker, ChunkResult
from app.engine.vision_extractor import VisionExtractor, get_vision_extractor
from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class IngestionResult:
    """Result of PDF ingestion"""
    document_id: str
    total_pages: int
    successful_pages: int
    failed_pages: int
    errors: List[str] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_pages == 0:
            return 0.0
        return (self.successful_pages / self.total_pages) * 100


@dataclass
class PageResult:
    """Result of single page processing"""
    page_number: int
    success: bool
    image_url: Optional[str] = None
    text_length: int = 0
    total_chunks: int = 0  # Number of semantic chunks created
    error: Optional[str] = None


class MultimodalIngestionService:
    """
    Service for multimodal document ingestion.
    
    Pipeline:
    1. Rasterization: PDF → High-quality images (pdf2image)
    2. Storage: Upload images to Supabase Storage
    3. Vision Extraction: Gemini Vision extracts text from images
    4. Indexing: Store text + embeddings + image_url in Neon
    
    **Property 6: PDF Page Count Equals Image Count**
    **Property 13: Ingestion Logs Progress**
    **Property 14: Ingestion Summary Contains Counts**
    **Property 15: Resume From Last Successful Page**
    """
    
    # Giảm DPI từ 300 xuống 150 để tiết kiệm memory trên Render Free Tier
    # 150 DPI vẫn đủ cho Gemini Vision đọc text
    DEFAULT_DPI = 150
    PROGRESS_FILE_SUFFIX = ".progress.json"
    
    def __init__(
        self,
        storage_client: Optional[SupabaseStorageClient] = None,
        vision_extractor: Optional[VisionExtractor] = None,
        embedding_service: Optional[GeminiOptimizedEmbeddings] = None,
        chunker: Optional[SemanticChunker] = None
    ):
        """
        Initialize Multimodal Ingestion Service.
        
        Args:
            storage_client: Supabase Storage client
            vision_extractor: Vision extraction service
            embedding_service: Embedding generation service
            chunker: Semantic chunking service
        """
        self.storage = storage_client or get_storage_client()
        self.vision = vision_extractor or get_vision_extractor()
        self.embeddings = embedding_service or GeminiOptimizedEmbeddings()
        self.chunker = chunker or get_semantic_chunker()
    
    def _get_progress_file(self, document_id: str) -> Path:
        """Get path to progress tracking file"""
        return Path(f"/tmp/{document_id}{self.PROGRESS_FILE_SUFFIX}")
    
    def _load_progress(self, document_id: str) -> int:
        """
        Load last successful page from progress file.
        
        **Property 15: Resume From Last Successful Page**
        """
        progress_file = self._get_progress_file(document_id)
        if progress_file.exists():
            try:
                with open(progress_file, 'r') as f:
                    data = json.load(f)
                    return data.get('last_successful_page', 0)
            except Exception as e:
                logger.warning(f"Failed to load progress: {e}")
        return 0
    
    def _save_progress(self, document_id: str, page_number: int):
        """Save progress to file for resume capability"""
        progress_file = self._get_progress_file(document_id)
        try:
            with open(progress_file, 'w') as f:
                json.dump({'last_successful_page': page_number}, f)
        except Exception as e:
            logger.warning(f"Failed to save progress: {e}")
    
    def _clear_progress(self, document_id: str):
        """Clear progress file after successful completion"""
        progress_file = self._get_progress_file(document_id)
        if progress_file.exists():
            progress_file.unlink()
    
    def convert_pdf_to_images(
        self,
        pdf_path: str,
        dpi: int = DEFAULT_DPI
    ) -> List[Image.Image]:
        """
        Convert PDF pages to high-quality images.
        
        Args:
            pdf_path: Path to PDF file
            dpi: Resolution for conversion (default 300)
            
        Returns:
            List of PIL Image objects
            
        **Property 6: PDF Page Count Equals Image Count**
        """
        logger.info(f"Converting PDF to images: {pdf_path} at {dpi} DPI")
        
        images = convert_from_path(
            pdf_path,
            dpi=dpi,
            fmt='jpeg'
        )
        
        logger.info(f"Converted {len(images)} pages to images")
        return images
    
    async def ingest_pdf(
        self,
        pdf_path: str,
        document_id: str,
        resume: bool = True
    ) -> IngestionResult:
        """
        Full ingestion pipeline: PDF → Images → Vision → Database.
        
        Args:
            pdf_path: Path to PDF file
            document_id: Unique identifier for the document
            resume: Whether to resume from last successful page
            
        Returns:
            IngestionResult with summary statistics
            
        **Property 13: Ingestion Logs Progress**
        **Property 14: Ingestion Summary Contains Counts**
        """
        logger.info(f"Starting multimodal ingestion for document: {document_id}")
        
        # Convert PDF to images
        try:
            images = self.convert_pdf_to_images(pdf_path)
        except Exception as e:
            logger.error(f"Failed to convert PDF: {e}")
            return IngestionResult(
                document_id=document_id,
                total_pages=0,
                successful_pages=0,
                failed_pages=0,
                errors=[f"PDF conversion failed: {e}"]
            )
        
        total_pages = len(images)
        successful_pages = 0
        failed_pages = 0
        errors = []
        
        # Check for resume point
        start_page = 0
        if resume:
            start_page = self._load_progress(document_id)
            if start_page > 0:
                logger.info(f"Resuming from page {start_page + 1}")
        
        # Process each page
        for page_num, image in enumerate(images):
            # Skip already processed pages
            if page_num < start_page:
                successful_pages += 1
                continue
            
            # Log progress
            logger.info(f"Processing page {page_num + 1} of {total_pages}")
            
            try:
                result = await self._process_page(
                    image=image,
                    document_id=document_id,
                    page_number=page_num + 1  # 1-indexed
                )
                
                if result.success:
                    successful_pages += 1
                    self._save_progress(document_id, page_num + 1)
                else:
                    failed_pages += 1
                    if result.error:
                        errors.append(f"Page {page_num + 1}: {result.error}")
                        
            except Exception as e:
                failed_pages += 1
                errors.append(f"Page {page_num + 1}: {str(e)}")
                logger.error(f"Failed to process page {page_num + 1}: {e}")
        
        # Clear progress file on completion
        self._clear_progress(document_id)
        
        # Log summary
        result = IngestionResult(
            document_id=document_id,
            total_pages=total_pages,
            successful_pages=successful_pages,
            failed_pages=failed_pages,
            errors=errors
        )
        
        logger.info(
            f"Ingestion complete: {successful_pages}/{total_pages} pages successful "
            f"({result.success_rate:.1f}%)"
        )
        
        return result
    
    async def _process_page(
        self,
        image: Image.Image,
        document_id: str,
        page_number: int
    ) -> PageResult:
        """
        Process a single page through the pipeline with semantic chunking.
        
        Steps:
        1. Upload image to Supabase
        2. Extract text using Vision
        3. Apply semantic chunking
        4. Generate embedding per chunk
        5. Store chunks in database
        
        **Feature: semantic-chunking**
        **Validates: Requirements 1.1, 1.4, 7.1, 7.2**
        """
        # Step 1: Upload to Supabase
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
        
        # Step 2: Extract text using Vision
        extraction_result = await self.vision.extract_from_image(image)
        
        if not extraction_result.success:
            return PageResult(
                page_number=page_number,
                success=False,
                image_url=image_url,
                error=f"Extraction failed: {extraction_result.error}"
            )
        
        text = extraction_result.text
        
        # Validate extraction
        if not self.vision.validate_extraction(extraction_result):
            logger.warning(f"Page {page_number} extraction may be incomplete")
        
        # Step 3: Apply semantic chunking
        page_metadata = {
            'document_id': document_id,
            'page_number': page_number,
            'image_url': image_url,
            'processing_timestamp': datetime.utcnow().isoformat(),
            'source_type': 'pdf'
        }
        
        try:
            chunks = await self.chunker.chunk_page_content(text, page_metadata)
            logger.info(f"Page {page_number}: Created {len(chunks)} semantic chunks")
        except Exception as e:
            logger.warning(f"Chunking failed, falling back to single chunk: {e}")
            # Fallback: store entire page as one chunk
            chunks = [ChunkResult(
                chunk_index=0,
                content=text,
                content_type='text',
                confidence_score=1.0,
                metadata=page_metadata
            )]
        
        # Step 4 & 5: Generate embedding and store each chunk
        successful_chunks = 0
        for chunk in chunks:
            try:
                # Generate embedding for chunk
                embedding = await self.embeddings.aembed_query(chunk.content)
                
                # Store chunk in database
                await self._store_chunk_in_database(
                    document_id=document_id,
                    page_number=page_number,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    embedding=embedding,
                    image_url=image_url,
                    content_type=chunk.content_type,
                    confidence_score=chunk.confidence_score,
                    metadata=chunk.metadata
                )
                successful_chunks += 1
                
            except Exception as e:
                logger.error(f"Failed to process chunk {chunk.chunk_index} on page {page_number}: {e}")
                continue
        
        if successful_chunks == 0:
            return PageResult(
                page_number=page_number,
                success=False,
                image_url=image_url,
                error="All chunks failed to process"
            )
        
        return PageResult(
            page_number=page_number,
            success=True,
            image_url=image_url,
            text_length=len(text),
            total_chunks=successful_chunks
        )
    
    async def _store_chunk_in_database(
        self,
        document_id: str,
        page_number: int,
        chunk_index: int,
        content: str,
        embedding: List[float],
        image_url: str,
        content_type: str = 'text',
        confidence_score: float = 1.0,
        metadata: Optional[dict] = None
    ):
        """
        Store a semantic chunk in Neon database.
        
        **Feature: semantic-chunking**
        **Property 10: Chunk Index Sequential**
        **Property 13: Database Round-Trip Consistency**
        **Validates: Requirements 2.5, 3.5, 5.5**
        """
        from sqlalchemy import text as sql_text
        import uuid
        
        session_factory = get_shared_session_factory()
        
        # Convert metadata to JSON string
        metadata_json = json.dumps(metadata) if metadata else '{}'
        
        with session_factory() as session:
            # Check if record exists (by document_id, page_number, chunk_index)
            result = session.execute(
                sql_text("""
                    SELECT id FROM knowledge_embeddings 
                    WHERE document_id = :doc_id 
                    AND page_number = :page_num 
                    AND chunk_index = :chunk_idx
                """),
                {"doc_id": document_id, "page_num": page_number, "chunk_idx": chunk_index}
            ).fetchone()
            
            if result:
                # Update existing record
                session.execute(
                    sql_text("""
                        UPDATE knowledge_embeddings 
                        SET content = :content,
                            embedding = :embedding,
                            image_url = :image_url,
                            content_type = :content_type,
                            confidence_score = :confidence_score,
                            metadata = :metadata,
                            updated_at = NOW()
                        WHERE document_id = :doc_id 
                        AND page_number = :page_num 
                        AND chunk_index = :chunk_idx
                    """),
                    {
                        "content": content,
                        "embedding": embedding,
                        "image_url": image_url,
                        "content_type": content_type,
                        "confidence_score": confidence_score,
                        "metadata": metadata_json,
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
                        (id, content, embedding, document_id, page_number, chunk_index, 
                         image_url, content_type, confidence_score, metadata, source)
                        VALUES (:id, :content, :embedding, :doc_id, :page_num, :chunk_idx,
                                :image_url, :content_type, :confidence_score, :metadata, :source)
                    """),
                    {
                        "id": str(uuid.uuid4()),
                        "content": content,
                        "embedding": embedding,
                        "doc_id": document_id,
                        "page_num": page_number,
                        "chunk_idx": chunk_index,
                        "image_url": image_url,
                        "content_type": content_type,
                        "confidence_score": confidence_score,
                        "metadata": metadata_json,
                        "source": f"{document_id}_page_{page_number}_chunk_{chunk_index}"
                    }
                )
            
            session.commit()
        
        logger.debug(f"Stored chunk {chunk_index} of page {page_number} in database")


# Singleton instance
_ingestion_service: Optional[MultimodalIngestionService] = None


def get_ingestion_service() -> MultimodalIngestionService:
    """Get or create singleton MultimodalIngestionService instance"""
    global _ingestion_service
    if _ingestion_service is None:
        _ingestion_service = MultimodalIngestionService()
    return _ingestion_service
