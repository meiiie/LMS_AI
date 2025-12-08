"""
Gemini Optimized Embeddings for Semantic Memory v0.3
CHỈ THỊ KỸ THUẬT SỐ 06

Features:
1. Force 768 dimensions (Matryoshka Representation Learning)
2. Auto L2 Normalization
3. Correct Task Type handling (RETRIEVAL_QUERY vs RETRIEVAL_DOCUMENT)

Requirements: 1.1, 1.2, 1.3, 1.4, 1.5
"""
import logging
from typing import List, Optional

import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


class GeminiOptimizedEmbeddings:
    """
    Wrapper tối ưu cho Maritime AI Semantic Memory.
    
    Implements:
    - Gemini embedding-001 model with MRL (Matryoshka Representation Learning)
    - Force 768 dimensions for optimal storage/performance balance
    - Manual L2 Normalization (required for non-3072 dimensions)
    - Correct task_type handling for retrieval optimization
    
    Usage:
        embeddings = GeminiOptimizedEmbeddings()
        
        # For storing documents
        doc_vectors = embeddings.embed_documents(["text1", "text2"])
        
        # For search queries
        query_vector = embeddings.embed_query("search text")
    """
    
    # Model configuration from CHỈ THỊ KỸ THUẬT SỐ 06
    MODEL_NAME = "models/gemini-embedding-001"
    OUTPUT_DIMENSIONS = 768  # MRL optimized dimensions
    
    # Task types for Gemini API
    TASK_TYPE_DOCUMENT = "RETRIEVAL_DOCUMENT"
    TASK_TYPE_QUERY = "RETRIEVAL_QUERY"
    TASK_TYPE_SIMILARITY = "SEMANTIC_SIMILARITY"
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        dimensions: Optional[int] = None
    ):
        """
        Initialize Gemini Optimized Embeddings.
        
        Args:
            api_key: Google API key (defaults to settings.google_api_key)
            model_name: Embedding model name (defaults to gemini-embedding-001)
            dimensions: Output dimensions (defaults to 768 for MRL)
        """
        self._api_key = api_key or settings.google_api_key
        self._model_name = model_name or self.MODEL_NAME
        self._dimensions = dimensions or settings.embedding_dimensions or self.OUTPUT_DIMENSIONS
        self._client = None
        
        if not self._api_key:
            logger.warning("Google API key not configured. Embeddings will fail.")
    
    @property
    def client(self):
        """Lazy initialization of Google GenAI client."""
        if self._client is None:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
                logger.info(f"Initialized Gemini client with model: {self._model_name}")
            except ImportError as e:
                error_msg = (
                    "google-genai package not installed. "
                    "Run: pip install google-genai>=0.3.0 "
                    "This is required for Semantic Memory embeddings."
                )
                logger.error(error_msg)
                raise ImportError(error_msg) from e
            except Exception as e:
                logger.error(f"Failed to initialize Gemini client: {e}")
                raise
        return self._client
    
    def _normalize(self, vector: List[float]) -> List[float]:
        """
        Apply L2 normalization to vector.
        
        Required for MRL dimensions other than 3072.
        Formula: normed_vector = vector / ||vector||
        
        Args:
            vector: Input embedding vector
            
        Returns:
            L2 normalized vector with unit length
            
        Requirements: 1.4, 1.5
        """
        arr = np.array(vector, dtype=np.float32)
        norm = np.linalg.norm(arr)
        
        if norm > 0:
            normalized = (arr / norm).tolist()
            return normalized
        else:
            logger.warning("Zero vector encountered during normalization")
            return vector
    
    def _embed_content(
        self,
        text: str,
        task_type: str
    ) -> List[float]:
        """
        Internal method to embed content with specified task type.
        
        Args:
            text: Text to embed
            task_type: RETRIEVAL_DOCUMENT, RETRIEVAL_QUERY, or SEMANTIC_SIMILARITY
            
        Returns:
            Normalized embedding vector (768 dimensions)
        """
        try:
            from google.genai import types
            
            response = self.client.models.embed_content(
                model=self._model_name,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=self._dimensions
                )
            )
            
            # Extract embedding values
            embedding = response.embeddings[0].values
            
            # Apply L2 normalization (required for 768 dimensions)
            normalized = self._normalize(embedding)
            
            return normalized
            
        except Exception as e:
            logger.error(f"Embedding failed for task_type={task_type}: {e}")
            raise
    
    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed multiple documents for storage.
        
        Uses RETRIEVAL_DOCUMENT task type for optimal retrieval performance.
        
        Args:
            texts: List of document texts to embed
            
        Returns:
            List of normalized embedding vectors (768 dimensions each)
            
        Requirements: 1.1, 1.3
        """
        if not texts:
            return []
        
        results = []
        for i, text in enumerate(texts):
            try:
                embedding = self._embed_content(text, self.TASK_TYPE_DOCUMENT)
                results.append(embedding)
                
                if (i + 1) % 10 == 0:
                    logger.debug(f"Embedded {i + 1}/{len(texts)} documents")
                    
            except Exception as e:
                logger.error(f"Failed to embed document {i}: {e}")
                # Return zero vector as fallback
                results.append([0.0] * self._dimensions)
        
        logger.info(f"Embedded {len(results)} documents with {self._dimensions} dimensions")
        return results
    
    def embed_query(self, text: str) -> List[float]:
        """
        Embed a search query.
        
        Uses RETRIEVAL_QUERY task type for optimal search performance.
        
        Args:
            text: Query text to embed
            
        Returns:
            Normalized embedding vector (768 dimensions)
            
        Requirements: 1.1, 1.2
        """
        embedding = self._embed_content(text, self.TASK_TYPE_QUERY)
        logger.debug(f"Embedded query with {len(embedding)} dimensions")
        return embedding
    
    async def aembed_query(self, text: str) -> List[float]:
        """
        Async version of embed_query for compatibility with async code.
        
        Note: Currently wraps sync method. Google GenAI SDK supports async
        but we keep sync for simplicity and compatibility.
        
        Args:
            text: Query text to embed
            
        Returns:
            Normalized embedding vector (768 dimensions)
        """
        return self.embed_query(text)
    
    def embed_for_similarity(self, text: str) -> List[float]:
        """
        Embed text for semantic similarity comparison.
        
        Uses SEMANTIC_SIMILARITY task type.
        
        Args:
            text: Text to embed
            
        Returns:
            Normalized embedding vector (768 dimensions)
        """
        return self._embed_content(text, self.TASK_TYPE_SIMILARITY)
    
    @property
    def dimensions(self) -> int:
        """Get the output dimensions."""
        return self._dimensions
    
    def verify_dimensions(self, vector: List[float]) -> bool:
        """
        Verify that a vector has the expected dimensions.
        
        Args:
            vector: Embedding vector to verify
            
        Returns:
            True if dimensions match, False otherwise
        """
        return len(vector) == self._dimensions
    
    def verify_normalization(self, vector: List[float], tolerance: float = 1e-5) -> bool:
        """
        Verify that a vector is L2 normalized (unit length).
        
        Args:
            vector: Embedding vector to verify
            tolerance: Acceptable deviation from 1.0
            
        Returns:
            True if vector is normalized, False otherwise
        """
        norm = np.linalg.norm(np.array(vector))
        return abs(norm - 1.0) < tolerance


# Factory function for easy instantiation
def get_embeddings() -> GeminiOptimizedEmbeddings:
    """
    Get a configured GeminiOptimizedEmbeddings instance.
    
    Returns:
        Configured embeddings instance
    """
    return GeminiOptimizedEmbeddings()
