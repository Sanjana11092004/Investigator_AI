"""
Vector RAG Retriever.
Performs semantic search over PDF narrative chunks in ChromaDB.
"""
import re
from typing import List, Dict, Any, Optional

from loguru import logger

from src.vector_store.chroma_store import get_vector_store
from src.embeddings.embedder import get_embedder
from src.config.settings import settings


class VectorRetriever:
    """
    Semantic search over PDF narrative documents.
    Returns relevant text chunks with source metadata.
    """

    @staticmethod
    def _normalize_name(s: str) -> str:
        """Lowercase and strip every non-alphanumeric char, so 'patient narrative 001',
        'patient_narrative_001' and 'PATIENT-NARRATIVE-001' all compare equal."""
        return re.sub(r'[^a-z0-9]', '', (s or '').lower())

    def find_named_document(self, query: str) -> Optional[str]:
        """If the query explicitly names an indexed document, return that document's
        source filename; otherwise None.

        Only identifier-like names (containing a digit, '_' or '-') are matched, so
        plain words such as 'patients' never accidentally scope to a document.
        Matching is case- and separator-insensitive and picks the longest match.
        """
        try:
            sources = get_vector_store().list_sources()
        except Exception:
            return None
        if not sources:
            return None

        norm_q = self._normalize_name(query)
        best, best_len = None, 0
        for src in sources:
            base = src.rsplit(".", 1)[0]            # drop extension
            # Require an identifier-like name to avoid matching common words.
            if not any(ch.isdigit() or ch in "_-" for ch in base):
                continue
            norm_b = self._normalize_name(base)
            if len(norm_b) >= 6 and norm_b in norm_q and len(norm_b) > best_len:
                best, best_len = src, len(norm_b)
        return best

    def document_facts(self, source: str) -> Optional[Dict[str, Any]]:
        """Authoritative, document-level facts (true patient count, page count) so a
        summary/count can never undercount from the handful of chunks semantic
        search returns.

        Prefers the STRUCTURED extraction (json-converter output) when present —
        that's an exact, merged-by-ID patient count. Falls back to a regex scan of
        all chunks when the document hasn't been structured yet."""
        facts: list[str] = []
        total = None

        # 1. Exact count from the structured per-document JSON, if available.
        try:
            from src.ingestion.pdf_structurer import PDFStructurer
            structured = PDFStructurer.load(source)
        except Exception:
            structured = None
        if structured and structured.get("patient_count"):
            total = structured["patient_count"]
            facts.append(f"Total patients described in this document: **{total}** "
                         f"(exact, from structured extraction)")
            if structured.get("study_id"):
                facts.append(f"Study: {structured['study_id']}")

        # 2. Page count + regex fallback for the patient count, from the chunks.
        data = get_vector_store().get_all_for_source(source)
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        if not docs and total is None:
            return None

        if total is None:
            full = "\n".join(docs)
            ids = {i.upper() for i in re.findall(r'\b(?:PAT|SUBJ)-?\d+\b', full, re.I)}
            m = re.search(r'total\s+(?:records|patients)[:\s]+(\d+)', full, re.I)
            total = int(m.group(1)) if m else (len(ids) or None)
            if total:
                facts.append(f"Total patient records described in this document: **{total}**")

        pages = [me.get("page") for me in metas if isinstance(me.get("page"), int)]
        if pages:
            facts.append(f"Document length: {max(pages)} pages")

        if not facts:
            return None
        content = ("**Document facts (authoritative — use these exact figures):**\n"
                   + "\n".join(f"- {f}" for f in facts))
        return {"content": content, "source": f"{source} (document index)", "type": "vector"}

    def has_session_docs(self, session_id: str) -> bool:
        """True if this session has uploaded its own document(s)."""
        if not session_id:
            return False
        try:
            return get_vector_store().has_docs_for(session_id)
        except Exception:
            return False

    def session_document_sources(self, session_id: str) -> List[str]:
        """Source filenames this session uploaded (for facts/structured lookup)."""
        if not session_id:
            return []
        try:
            return get_vector_store().sources_for_session(session_id)
        except Exception:
            return []

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