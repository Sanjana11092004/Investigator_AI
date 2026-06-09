"""
Embedding model wrapper using sentence-transformers.
Completely free and runs locally on CPU.
Results are cached to avoid re-embedding the same text.
"""
from typing import List
from functools import lru_cache

from sentence_transformers import SentenceTransformer
from loguru import logger

from src.config.settings import settings
from src.embeddings.cache import EmbeddingCache


class Embedder:
    """
    Wraps sentence-transformers for embedding generation.
    Uses disk cache to avoid re-embedding identical text.
    """

    def __init__(self, model_name: str = None):
        self.model_name = model_name or settings.embedding_model
        logger.info(f"Loading embedding model: {self.model_name}")
        self.model = SentenceTransformer(self.model_name)
        self.cache = EmbeddingCache()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """
        Embed a list of documents.
        Uses cache to skip already-embedded texts.
        
        Args:
            texts: List of text strings to embed.
        
        Returns:
            List of embedding vectors (each is a list of floats).
        """
        results = []
        uncached_indices = []
        uncached_texts = []

        # Check cache first
        for i, text in enumerate(texts):
            cached = self.cache.get(text)
            if cached is not None:
                results.append(cached)
            else:
                results.append(None)  # placeholder
                uncached_indices.append(i)
                uncached_texts.append(text)

        # Batch embed uncached texts
        if uncached_texts:
            logger.debug(f"Embedding {len(uncached_texts)} new texts (cache miss)")
            embeddings = self.model.encode(
                uncached_texts,
                batch_size=32,
                show_progress_bar=len(uncached_texts) > 100,
                normalize_embeddings=True,
            ).tolist()

            for i, (idx, text) in enumerate(zip(uncached_indices, uncached_texts)):
                results[idx] = embeddings[i]
                self.cache.set(text, embeddings[i])

        return results

    def embed_query(self, query: str) -> List[float]:
        """
        Embed a single query string.
        
        Args:
            query: The query text.
        
        Returns:
            Embedding vector.
        """
        cached = self.cache.get(query)
        if cached is not None:
            return cached
        embedding = self.model.encode(
            query, normalize_embeddings=True
        ).tolist()
        self.cache.set(query, embedding)
        return embedding


@lru_cache(maxsize=1)
def get_embedder() -> Embedder:
    """Singleton embedder — loaded once, reused everywhere."""
    return Embedder()