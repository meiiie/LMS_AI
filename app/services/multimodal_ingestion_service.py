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
from typing import List, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from pathlib import Path

if TYPE_CHECKING:
    import fitz

from PIL import Image
import io

# Try PyMuPDF first (no external dependencies), fallback to pdf2image
try:
    import fitz  # PyMuPDF
    USE_PYMUPDF = True
except ImportError:
    from pdf2image import convert_from_path
    USE_PYMUPDF = False

from app.core.config import settings
from app.core.database import get_shared_session_factory
from app.services.supabase_storage import SupabaseStorageClient, get_storage_client
from app.services.chunking_service import SemanticChunker, get_semantic_chunker, ChunkResult
from app.engine.vision_extractor import VisionExtractor, get_vision_extractor
from app.engine.gemini_embedding import GeminiOptimizedEmbeddings
from app.engine.page_analyzer import PageAnalyzer, PageAnalysisResult, get_page_analyzer
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
    
    # Hybrid Text/Vision Detection tracking (Feature: hybrid-text-vision)
    vision_pages: int = 0      # Pages processed via Gemini Vision
    direct_pages: int = 0      # Pages processed via PyMuPDF direct extraction
    fallback_pages: int = 0    # Pages that fell back from direct to vision
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate percentage"""
        if self.total_pages == 0:
            return 0.0
        return (self.successful_pages / self.total_pages) * 100
    
    @property
    def api_savings_percent(self) -> float:
        """
        Calculate estimated API cost savings from hybrid detection.
        
        **Feature: hybrid-text-vision**
        **Property 8: Savings Calculation**
        """
        if self.total_pages == 0:
            return 0.0
        return (self.direct_pages / self.total_pages) * 100


@dataclass
class PageResult:
    """Result of single page processing"""
    page_number: int
    success: bool
    image_url: Optional[str] = None
    text_length: int = 0
    total_chunks: int = 0  # Number of semantic chunks created
    error: Optional[str] = None
    extraction_method: str = "vision"  # "direct" or "vision" (Feature: hybrid-text-vision)
    was_fallback: bool = False  # True if fell back from direct to vision


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
        chunker: Optional[SemanticChunker] = None,
        page_analyzer: Optional[PageAnalyzer] = None
    ):
        """
        Initialize Multimodal Ingestion Service.
        
        Args:
            storage_client: Supabase Storage client
            vision_extractor: Vision extraction service
            embedding_service: Embedding generation service
            chunker: Semantic chunking service
            page_analyzer: Page analyzer for hybrid detection (Feature: hybrid-text-vision)
        """
        self.storage = storage_client or get_storage_client()
        self.vision = vision_extractor or get_vision_extractor()
        self.embeddings = embedding_service or GeminiOptimizedEmbeddings()
        self.chunker = chunker or get_semantic_chunker()
        self.page_analyzer = page_analyzer or get_page_analyzer()
        
        # Hybrid detection settings from config
        self.hybrid_detection_enabled = settings.hybrid_detection_enabled
        self.force_vision_mode = settings.force_vision_mode
        self.min_text_length = settings.min_text_length_for_direct
        
        logger.info(
            f"MultimodalIngestionService initialized: "
            f"hybrid_detection={self.hybrid_detection_enabled}, "
            f"force_vision={self.force_vision_mode}"
        )
    
    def _get_progress_file(self, document_id: str) -> Path:
        """Get path to progress tracking file (cross-platform)"""
        import tempfile
        temp_dir = Path(tempfile.gettempdir())
        return temp_dir / f"{document_id}{self.PROGRESS_FILE_SUFFIX}"
    
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
    
    def get_pdf_page_count(self, pdf_path: str) -> int:
        """Get total page count without loading images into memory."""
        doc = fitz.open(pdf_path)
        total = len(doc)
        doc.close()
        return total
    
    def convert_single_page(
        self,
        pdf_path: str,
        page_num: int,
        dpi: int = DEFAULT_DPI
    ) -> Optional[Image.Image]:
        """
        Convert a single PDF page to image.
        
        Memory-efficient: only one page in memory at a time.
        
        Args:
            pdf_path: Path to PDF file
            page_num: Page number (0-indexed)
            dpi: Resolution for conversion
            
        Returns:
            PIL Image object or None on error
        """
        try:
            doc = fitz.open(pdf_path)
            if page_num >= len(doc):
                doc.close()
                return None
            
            zoom = dpi / 72
            matrix = fitz.Matrix(zoom, zoom)
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=matrix)
            img_data = pix.tobytes("jpeg")
            img = Image.open(io.BytesIO(img_data))
            
            # Clean up PyMuPDF objects
            del pix
            doc.close()
            
            return img
        except Exception as e:
            logger.error(f"Failed to convert page {page_num}: {e}")
            return None
    
    def convert_pdf_to_images(
        self,
        pdf_path: str,
        dpi: int = DEFAULT_DPI,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None
    ) -> tuple[List[Image.Image], int]:
        """
        Convert PDF pages to high-quality images.
        
        MEMORY OPTIMIZED: Converts pages one at a time to reduce peak memory usage.
        
        Args:
            pdf_path: Path to PDF file
            dpi: Resolution for conversion (default 150 for memory efficiency)
            start_page: Start from this page (0-indexed, optional)
            end_page: End at this page (0-indexed, exclusive, optional)
            
        Returns:
            Tuple of (List of PIL Image objects, total_pages in PDF)
            
        **Property 6: PDF Page Count Equals Image Count**
        **Feature: hybrid-text-vision (optimized batch conversion)**
        """
        if USE_PYMUPDF:
            # Get total pages first
            total_pages = self.get_pdf_page_count(pdf_path)
            
            # Determine page range
            actual_start = start_page if start_page is not None else 0
            actual_end = end_page if end_page is not None else total_pages
            actual_end = min(actual_end, total_pages)
            
            logger.info(f"Converting pages {actual_start + 1}-{actual_end} of {total_pages} at {dpi} DPI")
            
            # Convert pages one at a time to minimize memory
            images = []
            for page_num in range(actual_start, actual_end):
                img = self.convert_single_page(pdf_path, page_num, dpi)
                if img is not None:
                    images.append(img)
                else:
                    # Append None placeholder to maintain index alignment
                    images.append(None)
            
            logger.info(f"Converted {len([i for i in images if i])} pages to images (PyMuPDF)")
            return images, total_pages
        else:
            # Fallback to pdf2image (requires Poppler)
            # Note: pdf2image uses 1-indexed pages
            first_page = (start_page + 1) if start_page is not None else None
            last_page = end_page if end_page is not None else None
            
            images = convert_from_path(
                pdf_path,
                dpi=dpi,
                fmt='jpeg',
                first_page=first_page,
                last_page=last_page
            )
            
            # Get total pages separately
            total_pages = self.get_pdf_page_count(pdf_path)
            
            logger.info(f"Converted {len(images)} pages to images (pdf2image)")
            return images, total_pages
    
    async def ingest_pdf(
        self,
        pdf_path: str,
        document_id: str,
        resume: bool = True,
        max_pages: Optional[int] = None,
        start_page: Optional[int] = None,
        end_page: Optional[int] = None
    ) -> IngestionResult:
        """
        Full ingestion pipeline: PDF → Images → Vision → Database.
        
        Args:
            pdf_path: Path to PDF file
            document_id: Unique identifier for the document
            resume: Whether to resume from last successful page
            max_pages: Maximum pages to process (for testing)
            start_page: Start from this page (1-indexed, for batch processing)
            end_page: Stop at this page (1-indexed, inclusive)
            
        Returns:
            IngestionResult with summary statistics
            
        **Property 13: Ingestion Logs Progress**
        **Property 14: Ingestion Summary Contains Counts**
        **Feature: hybrid-text-vision (batch processing support)**
        """
        logger.info(f"Starting multimodal ingestion for document: {document_id}")
        
        # Determine page range for batch processing BEFORE converting
        # start_page and end_page are 1-indexed from API
        batch_start = 0  # 0-indexed for internal use
        batch_end = None  # Will be set after knowing total_pages
        
        if start_page is not None and start_page > 0:
            batch_start = start_page - 1  # Convert to 0-indexed
            logger.info(f"Batch processing: starting from page {start_page}")
        
        if end_page is not None and end_page > 0:
            batch_end = end_page  # Will be capped to total_pages later
            logger.info(f"Batch processing: ending at page {end_page}")
        
        # Check for resume point (only if not using explicit start_page)
        if start_page is None and resume:
            resume_page = self._load_progress(document_id)
            if resume_page > 0:
                batch_start = resume_page
                logger.info(f"Resuming from page {resume_page + 1}")
        
        # Convert ONLY the pages we need (optimized for batch processing)
        try:
            images, total_pages = self.convert_pdf_to_images(
                pdf_path,
                start_page=batch_start,
                end_page=batch_end
            )
        except Exception as e:
            logger.error(f"Failed to convert PDF: {e}")
            return IngestionResult(
                document_id=document_id,
                total_pages=0,
                successful_pages=0,
                failed_pages=0,
                errors=[f"PDF conversion failed: {e}"]
            )
        
        # Finalize batch_end after knowing total_pages
        if batch_end is None:
            batch_end = total_pages
        else:
            batch_end = min(batch_end, total_pages)
        
        # Limit pages if max_pages is set (for testing)
        pages_to_process = batch_end - batch_start
        if max_pages is not None and max_pages > 0:
            pages_to_process = min(max_pages, pages_to_process)
            batch_end = batch_start + pages_to_process
            logger.info(f"Limiting to {pages_to_process} pages (test mode)")
        
        successful_pages = 0
        failed_pages = 0
        errors = []
        
        # Hybrid detection tracking (Feature: hybrid-text-vision)
        vision_pages = 0
        direct_pages = 0
        fallback_pages = 0
        
        logger.info(f"Processing pages {batch_start + 1} to {batch_end} of {total_pages}")
        
        # Open PDF for hybrid detection (need page objects)
        pdf_doc = None
        if self.hybrid_detection_enabled and USE_PYMUPDF:
            try:
                pdf_doc = fitz.open(pdf_path)
            except Exception as e:
                logger.warning(f"Could not open PDF for hybrid detection: {e}")
        
        # Process each page in the batch
        # Note: images list now only contains pages from batch_start to batch_end
        # So enumerate index 0 = page batch_start, index 1 = page batch_start+1, etc.
        for idx in range(len(images)):
            # Get image and immediately remove from list to free memory
            image = images[idx]
            images[idx] = None  # Free memory immediately
            
            # Calculate actual page number (0-indexed)
            page_num = batch_start + idx
            
            # Log progress
            logger.info(f"Processing page {page_num + 1} of {total_pages} (batch: {batch_start + 1}-{batch_end})")
            
            # Get PDF page for hybrid detection
            pdf_page = None
            if pdf_doc is not None:
                try:
                    pdf_page = pdf_doc.load_page(page_num)
                except Exception as e:
                    logger.warning(f"Could not load PDF page {page_num}: {e}")
            
            try:
                result = await self._process_page(
                    image=image,
                    document_id=document_id,
                    page_number=page_num + 1,  # 1-indexed
                    pdf_page=pdf_page
                )
                
                if result.success:
                    successful_pages += 1
                    self._save_progress(document_id, page_num + 1)
                    
                    # Track extraction method (Feature: hybrid-text-vision)
                    if result.extraction_method == "vision":
                        vision_pages += 1
                    else:
                        direct_pages += 1
                    
                    if result.was_fallback:
                        fallback_pages += 1
                else:
                    failed_pages += 1
                    if result.error:
                        errors.append(f"Page {page_num + 1}: {result.error}")
                        
            except Exception as e:
                failed_pages += 1
                errors.append(f"Page {page_num + 1}: {str(e)}")
                logger.error(f"Failed to process page {page_num + 1}: {e}")
            finally:
                # Explicitly close and free image memory
                if image is not None:
                    try:
                        image.close()
                    except:
                        pass
                    del image
                
                # Force garbage collection after each page to prevent memory buildup
                import gc
                gc.collect()
        
        # Close PDF document
        if pdf_doc is not None:
            pdf_doc.close()
        
        # Clear progress file on completion
        self._clear_progress(document_id)
        
        # Log summary with hybrid detection stats
        result = IngestionResult(
            document_id=document_id,
            total_pages=total_pages,
            successful_pages=successful_pages,
            failed_pages=failed_pages,
            errors=errors,
            vision_pages=vision_pages,
            direct_pages=direct_pages,
            fallback_pages=fallback_pages
        )
        
        logger.info(
            f"Ingestion complete: {successful_pages}/{total_pages} pages successful "
            f"({result.success_rate:.1f}%)"
        )
        
        # Log hybrid detection savings (Feature: hybrid-text-vision)
        if self.hybrid_detection_enabled:
            logger.info(
                f"Hybrid detection: vision={vision_pages}, direct={direct_pages}, "
                f"fallback={fallback_pages}, API savings={result.api_savings_percent:.1f}%"
            )
        
        return result
    
    def _extract_direct(self, page: "fitz.Page") -> str:
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
            logger.error(f"Direct extraction failed: {e}")
            return ""
    
    async def _process_page(
        self,
        image: Image.Image,
        document_id: str,
        page_number: int,
        pdf_page: Optional["fitz.Page"] = None
    ) -> PageResult:
        """
        Process a single page through the pipeline with semantic chunking.
        
        Steps:
        1. Upload image to Supabase
        2. Analyze page for hybrid detection (if enabled)
        3. Extract text using Vision OR Direct method
        4. Apply semantic chunking
        5. Generate embedding per chunk
        6. Store chunks in database
        
        **Feature: semantic-chunking, hybrid-text-vision**
        **Validates: Requirements 1.1, 1.4, 7.1, 7.2**
        """
        extraction_method = "vision"
        was_fallback = False
        
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
        
        # Step 2: Hybrid detection - decide extraction method
        text = None
        
        if self.hybrid_detection_enabled and pdf_page is not None and not self.force_vision_mode:
            # Analyze page to determine best extraction method
            analysis = self.page_analyzer.analyze_page(pdf_page, page_number)
            
            if not self.page_analyzer.should_use_vision(analysis):
                # Try direct extraction first
                extraction_method = "direct"
                text = self._extract_direct(pdf_page)
                
                # Fallback to vision if direct extraction is too short
                if len(text.strip()) < self.min_text_length:
                    logger.info(
                        f"Page {page_number}: Direct extraction too short "
                        f"({len(text)} chars), falling back to Vision"
                    )
                    text = None
                    extraction_method = "vision"
                    was_fallback = True
                else:
                    logger.info(
                        f"Page {page_number}: Using direct extraction "
                        f"({len(text)} chars, reasons: {analysis.detection_reasons})"
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
                logger.warning(f"Page {page_number} extraction may be incomplete")
        
        # Step 4: Apply semantic chunking
        page_metadata = {
            'document_id': document_id,
            'page_number': page_number,
            'image_url': image_url,
            'processing_timestamp': datetime.utcnow().isoformat(),
            'source_type': 'pdf',
            'extraction_method': extraction_method  # Feature: hybrid-text-vision
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
