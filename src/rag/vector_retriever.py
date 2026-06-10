"""
Vector RAG Retriever.
Performs semantic search over PDF narrative chunks in ChromaDB.
"""
from typing import List, Dict, Any

from loguru import logger

from src.vector_store.chroma_store import get_vector_store
from src.embeddings.embedder import get_embedder
from src.config.settings import settings


class VectorRetriever:
    """
    Semantic search over PDF narrative documents.
    Returns relevant text chunks with source metadata.
    """

    def retrieve(
        self,
        query: str,
        n_results: int = None,
        metadata_filter: Dict[str, Any] = None,
        min_similarity: float = 0.3,
        session_id: str = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant narrative chunks for a query.

        Args:
            query: User's natural language question.
            n_results: Number of results to return.
            metadata_filter: ChromaDB metadata filter dict.
            min_similarity: Drop chunks below this cosine similarity. Pass a
                higher value (e.g. 0.45) when vector is only a fallback for a
                structured query, so unrelated PDF content isn't mixed in.

        Returns:
            List of result dicts with content, source, page, distance.
        """
        n_results = n_results or settings.vector_top_k
        embedder = get_embedder()
        vector_store = get_vector_store()

        if vector_store.get_document_count() == 0:
            logger.info("Vector store is empty — no PDF documents indexed yet")
            return []

        # Per-session document scoping: if this session has uploaded its own
        # documents, search ONLY those (isolation). Otherwise fall back to the
        # shared/bundled corpus tagged 'global'. This stops one investigation's
        # uploads from leaking into another's answers.
        where = metadata_filter
        if where is None and session_id:
            if vector_store.has_docs_for(session_id):
                where = {"session_id": session_id}
            else:
                where = {"session_id": "global"}

        query_embedding = embedder.embed_query(query)
        raw = vector_store.query(
            query_embedding=query_embedding,
            n_results=n_results,
            where=where,
        )

        results = []
        documents = raw.get("documents", [[]])[0]
        metadatas = raw.get("metadatas", [[]])[0]
        distances = raw.get("distances", [[]])[0]

        for doc, meta, dist in zip(documents, metadatas, distances):
            # Distance in cosine space: 0 = identical, 2 = opposite
            # Convert to similarity score 0-1
            similarity = 1 - (dist / 2)

            if similarity < min_similarity:  # Skip low-relevance results
                continue

            results.append({
                "content": doc,
                "source": meta.get("source", "unknown"),
                "page": meta.get("page", "?"),
                "type": "vector",
                "similarity": round(similarity, 3),
            })

        logger.debug(f"Vector retriever: {len(results)} relevant chunks for query")
        return results