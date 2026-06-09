"""
Disk-based embedding cache using diskcache.
Prevents re-embedding the same text chunks across restarts.
"""
import hashlib
from typing import Optional, List

import diskcache
from src.config.settings import settings


class EmbeddingCache:
    """
    Persistent disk cache for embeddings.
    Key: MD5 hash of text. Value: embedding vector.
    """

    def __init__(self):
        self._cache = diskcache.Cache(settings.embedding_cache_dir)

    def _key(self, text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    def get(self, text: str) -> Optional[List[float]]:
        """Return cached embedding or None."""
        return self._cache.get(self._key(text))

    def set(self, text: str, embedding: List[float]) -> None:
        """Store embedding in cache."""
        self._cache.set(self._key(text), embedding)

    def clear(self) -> None:
        """Clear all cached embeddings."""
        self._cache.clear()