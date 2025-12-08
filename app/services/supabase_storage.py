"""
Supabase Storage Client for Multimodal RAG

CHỈ THỊ KỸ THUẬT SỐ 26: Hybrid Infrastructure
Handles image upload/download to Supabase Storage bucket for Evidence Images.

**Feature: multimodal-rag-vision**
**Validates: Requirements 2.2, 2.3, 4.3**
"""
import io
import logging
import time
from typing import Optional
from dataclasses import dataclass

from supabase import create_client, Client
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class UploadResult:
    """Result of image upload operation"""
    success: bool
    public_url: Optional[str] = None
    path: Optional[str] = None
    error: Optional[str] = None


class SupabaseStorageClient:
    """
    Client for Supabase Storage operations.
    
    Handles image upload/download for the Multimodal RAG pipeline.
    Images are stored in the 'maritime-docs' bucket with public access.
    
    Path structure: {document_id}/page_{number}.jpg
    """
    
    BUCKET_NAME = "maritime-docs"
    MAX_RETRIES = 3
    RETRY_DELAY = 1.0  # seconds
    
    def __init__(
        self,
        url: Optional[str] = None,
        key: Optional[str] = None,
        bucket: Optional[str] = None
    ):
        """
        Initialize Supabase Storage client.
        
        Args:
            url: Supabase project URL (defaults to settings)
            key: Supabase API key (defaults to settings)
            bucket: Storage bucket name (defaults to settings)
        """
        self.url = url or settings.supabase_url
        self.key = key or settings.supabase_key
        self.bucket = bucket or settings.supabase_storage_bucket or self.BUCKET_NAME
        
        self._client: Optional[Client] = None
        
    @property
    def client(self) -> Client:
        """Lazy initialization of Supabase client"""
        if self._client is None:
            if not self.url or not self.key:
                raise ValueError(
                    "Supabase URL and Key are required. "
                    "Set SUPABASE_URL and SUPABASE_KEY environment variables."
                )
            self._client = create_client(self.url, self.key)
        return self._client
    
    def _build_path(self, document_id: str, page_number: int) -> str:
        """
        Build storage path for an image.
        
        Path structure: {document_id}/page_{number}.jpg
        
        **Property 9: Storage Folder Structure**
        """
        return f"{document_id}/page_{page_number}.jpg"
    
    async def upload_image(
        self,
        image_data: bytes,
        document_id: str,
        page_number: int,
        content_type: str = "image/jpeg"
    ) -> UploadResult:
        """
        Upload image to Supabase Storage with retry logic.
        
        Args:
            image_data: Image bytes to upload
            document_id: Document identifier
            page_number: Page number in the document
            content_type: MIME type of the image
            
        Returns:
            UploadResult with success status and public URL
            
        **Property 7: Upload Returns Valid Public URL**
        """
        path = self._build_path(document_id, page_number)
        
        for attempt in range(self.MAX_RETRIES):
            try:
                # Upload to Supabase Storage
                response = self.client.storage.from_(self.bucket).upload(
                    path=path,
                    file=image_data,
                    file_options={
                        "content-type": content_type,
                        "upsert": "true"  # Overwrite if exists
                    }
                )
                
                # Get public URL
                public_url = self.get_public_url(path)
                
                logger.info(f"Uploaded image to {path}, URL: {public_url}")
                
                return UploadResult(
                    success=True,
                    public_url=public_url,
                    path=path
                )
                
            except Exception as e:
                logger.warning(
                    f"Upload attempt {attempt + 1}/{self.MAX_RETRIES} failed: {e}"
                )
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(self.RETRY_DELAY * (attempt + 1))  # Exponential backoff
                else:
                    logger.error(f"Failed to upload image after {self.MAX_RETRIES} attempts")
                    return UploadResult(
                        success=False,
                        error=str(e)
                    )
        
        return UploadResult(success=False, error="Max retries exceeded")
    
    async def upload_pil_image(
        self,
        image: Image.Image,
        document_id: str,
        page_number: int,
        quality: int = 85
    ) -> UploadResult:
        """
        Upload PIL Image to Supabase Storage.
        
        Args:
            image: PIL Image object
            document_id: Document identifier
            page_number: Page number in the document
            quality: JPEG quality (1-100)
            
        Returns:
            UploadResult with success status and public URL
        """
        # Convert PIL Image to bytes
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        image_data = buffer.getvalue()
        
        return await self.upload_image(
            image_data=image_data,
            document_id=document_id,
            page_number=page_number
        )
    
    def get_public_url(self, path: str) -> str:
        """
        Get public URL for a stored file.
        
        Args:
            path: Storage path of the file
            
        Returns:
            Public URL string
        """
        response = self.client.storage.from_(self.bucket).get_public_url(path)
        return response
    
    async def delete_image(self, path: str) -> bool:
        """
        Delete image from storage.
        
        Args:
            path: Storage path of the file
            
        Returns:
            True if deletion was successful
        """
        try:
            self.client.storage.from_(self.bucket).remove([path])
            logger.info(f"Deleted image: {path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete image {path}: {e}")
            return False
    
    async def delete_document_images(self, document_id: str) -> int:
        """
        Delete all images for a document.
        
        Args:
            document_id: Document identifier
            
        Returns:
            Number of images deleted
        """
        try:
            # List all files in the document folder
            files = self.client.storage.from_(self.bucket).list(document_id)
            
            if not files:
                return 0
            
            # Build paths for deletion
            paths = [f"{document_id}/{f['name']}" for f in files]
            
            # Delete all files
            self.client.storage.from_(self.bucket).remove(paths)
            
            logger.info(f"Deleted {len(paths)} images for document {document_id}")
            return len(paths)
            
        except Exception as e:
            logger.error(f"Failed to delete document images {document_id}: {e}")
            return 0
    
    async def check_health(self) -> bool:
        """
        Check if Supabase Storage is accessible.
        
        Returns:
            True if storage is healthy
        """
        try:
            # Try to list bucket contents (empty list is OK)
            self.client.storage.from_(self.bucket).list(limit=1)
            return True
        except Exception as e:
            logger.error(f"Supabase Storage health check failed: {e}")
            return False


# Singleton instance
_storage_client: Optional[SupabaseStorageClient] = None


def get_storage_client() -> SupabaseStorageClient:
    """Get or create singleton SupabaseStorageClient instance"""
    global _storage_client
    if _storage_client is None:
        _storage_client = SupabaseStorageClient()
    return _storage_client
