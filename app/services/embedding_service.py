"""
Embedding Service - Vertex AI Text Embeddings

Generates vector embeddings for products to enable semantic search.
Uses Google Cloud Vertex AI text-embedding-004 model.
"""
from typing import Optional, List, Dict, Any
from app.config import settings
import logging

logger = logging.getLogger(__name__)

_embedding_service: Optional["EmbeddingService"] = None


class EmbeddingService:
    """
    Service for generating text embeddings using Vertex AI.
    """

    def __init__(self):
        if not settings.ENABLE_EMBEDDINGS:
            raise ValueError("Embeddings are disabled. Set ENABLE_EMBEDDINGS=true")

        if not settings.GCP_PROJECT_ID:
            raise ValueError("GCP_PROJECT_ID is required for embeddings")

        try:
            from google.cloud import aiplatform

            aiplatform.init(
                project=settings.GCP_PROJECT_ID,
                location=settings.GCP_REGION
            )

            self.model_name = "text-embedding-004"
            self._initialized = True
            logger.info(f"Embedding service initialized with model: {self.model_name}")

        except Exception as e:
            logger.error(f"Failed to initialize embedding service: {e}")
            raise

    def prepare_product_text(self, product: Dict[str, Any]) -> str:
        """
        Prepare product data as text for embedding generation.

        Combines relevant product fields into a searchable text representation.
        """
        parts = []

        # Product name (most important)
        if product.get('name'):
            parts.append(product['name'])

        # Description (if available)
        if product.get('description'):
            # Strip HTML tags for cleaner text
            import re
            description = re.sub(r'<[^>]+>', '', product['description'])
            parts.append(description[:500])  # Limit description length

        if product.get('short_description'):
            import re
            short_desc = re.sub(r'<[^>]+>', '', product['short_description'])
            parts.append(short_desc)

        # Categories
        categories = product.get('categories', [])
        if categories:
            cat_names = [c.get('name', '') for c in categories if c.get('name')]
            if cat_names:
                parts.append(f"Categories: {', '.join(cat_names)}")

        # Tags
        tags = product.get('tags', [])
        if tags:
            tag_names = [t.get('name', '') for t in tags if t.get('name')]
            if tag_names:
                parts.append(f"Tags: {', '.join(tag_names)}")

        # SKU
        if product.get('sku'):
            parts.append(f"SKU: {product['sku']}")

        # Attributes
        attributes = product.get('attributes', [])
        for attr in attributes:
            if attr.get('name') and attr.get('options'):
                parts.append(f"{attr['name']}: {', '.join(attr['options'])}")

        return ' | '.join(parts)

    def generate_embedding(self, text: str) -> List[float]:
        """
        Generate embedding vector for text.

        Args:
            text: Text to embed

        Returns:
            768-dimensional embedding vector
        """
        if not text:
            return None

        try:
            from vertexai.language_models import TextEmbeddingModel

            model = TextEmbeddingModel.from_pretrained(self.model_name)
            embeddings = model.get_embeddings([text])

            if embeddings and len(embeddings) > 0:
                return embeddings[0].values

            return None

        except Exception as e:
            logger.error(f"Failed to generate embedding: {e}")
            raise

    def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for multiple texts in batch.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        if not texts:
            return []

        try:
            from vertexai.language_models import TextEmbeddingModel

            model = TextEmbeddingModel.from_pretrained(self.model_name)

            # Vertex AI supports batches up to 250
            batch_size = 250
            all_embeddings = []

            for i in range(0, len(texts), batch_size):
                batch = texts[i:i + batch_size]
                embeddings = model.get_embeddings(batch)
                all_embeddings.extend([e.values for e in embeddings])

            return all_embeddings

        except Exception as e:
            logger.error(f"Failed to generate batch embeddings: {e}")
            raise


def get_embedding_service() -> EmbeddingService:
    """
    Get or create the singleton EmbeddingService instance.
    """
    global _embedding_service

    if not settings.ENABLE_EMBEDDINGS:
        raise ValueError("Embeddings are disabled")

    if _embedding_service is None:
        _embedding_service = EmbeddingService()

    return _embedding_service
