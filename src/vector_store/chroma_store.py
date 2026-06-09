"""
ChromaDB vector store wrapper.
Provides add, query, and delete operations with metadata filtering.
"""
from functools import lru_cache
from typing import List, Dict, Any, Optional

import chromadb
from chromadb.config import Settings as ChromaSettings
from loguru import logger

from src.config.settings import settings


class VectorStore:
    """
    Wraps ChromaDB for persistent vector storage.
    
    All PDF narrative chunks are stored here with metadata
    for filtering by source, page, and document type.
    """

    def __init__(self):
        self.client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"ChromaDB initialized: {self.collection.count()} documents in collection"
        )

    def add(
        self,
        documents: List[str],
        embeddings: List[List[float]],
        metadatas: List[Dict[str, Any]],
        ids: List[str],
    ) -> None:
        """
        Add documents and their embeddings to the vector store.
        
        Args:
            documents: Text content of each chunk.
            embeddings: Pre-computed embeddings for each chunk.
            metadatas: Metadata dict for each chunk (source, page, etc.).
            ids: Unique ID for each chunk (used for deduplication).
        """
        # Filter out already-existing IDs to support incremental ingestion
        existing = set(self.collection.get(ids=ids)["ids"])
        new_indices = [i for i, id_ in enumerate(ids) if id_ not in existing]

        if not new_indices:
            logger.debug("All chunks already in vector store, skipping.")
            return

        self.collection.add(
            documents=[documents[i] for i in new_indices],
            embeddings=[embeddings[i] for i in new_indices],
            metadatas=[metadatas[i] for i in new_indices],
            ids=[ids[i] for i in new_indices],
        )
        logger.info(f"Added {len(new_indices)} new chunks to vector store")

    def query(
        self,
        query_embedding: List[float],
        n_results: int = None,
        where: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Semantic similarity search.
        
        Args:
            query_embedding: Embedding of the query.
            n_results: Number of results to return.
            where: ChromaDB metadata filter (e.g., {"doc_type": "narrative_pdf"}).
        
        Returns:
            ChromaDB result dict with documents, distances, metadatas, ids.
        """
        n_results = n_results or settings.vector_top_k

        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": min(n_results, max(1, self.collection.count())),
            "include": ["documents", "distances", "metadatas"],
        }
        if where:
            kwargs["where"] = where

        return self.collection.query(**kwargs)

    def get_document_count(self) -> int:
        """Return total number of chunks in the store."""
        return self.collection.count()

    def delete_by_source(self, file_name: str) -> None:
        """
        Delete all chunks from a specific source file.
        Used when re-ingesting a document.
        """
        self.collection.delete(where={"source": file_name})
        logger.info(f"Deleted all chunks from source: {file_name}")


@lru_cache(maxsize=1)
def get_vector_store() -> VectorStore:
    """Singleton vector store — initialized once."""
    return VectorStore()