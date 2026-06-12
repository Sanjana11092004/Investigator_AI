"""Catalog lookup — scoped full-text retrieval over the SQLite FTS catalog.

Drop-in replacement for the old vector retriever: same method names
(retrieve / has_session_docs / session_document_sources / document_facts /
find_named_document) so the RAG pipeline is unchanged, but retrieval is bm25
keyword search over SQLite instead of vector similarity over ChromaDB.
"""
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from src.catalog.catalog_store import get_catalog_store
from src.config.settings import settings


# Common words dropped from the FTS query so ranking keys off meaningful terms.
_STOP = {
    "the", "a", "an", "and", "or", "of", "for", "to", "in", "on", "is", "are",
    "was", "were", "how", "many", "what", "which", "who", "show", "list", "get",
    "give", "tell", "me", "all", "any", "this", "that", "these", "those", "with",
    "from", "about", "have", "has", "had", "does", "do", "did", "can", "will",
    "there", "their", "they", "them", "please", "summarize", "summary", "describe",
}


class CatalogRetriever:
    """Keyword full-text retrieval, scoped by named document / session."""

    # ── content retrieval ─────────────────────────────────────────────────
    def retrieve(
        self,
        query: str,
        n_results: int = None,
        metadata_filter: Dict[str, Any] = None,
        min_similarity: float = 0.0,   # kept for interface compatibility (unused: FTS ranks)
        session_id: str = None,
    ) -> List[Dict[str, Any]]:
        n_results = n_results or settings.vector_top_k
        store = get_catalog_store()
        if store.get_document_count() == 0:
            logger.info("Catalog is empty — no narrative documents indexed yet")
            return []

        source = (metadata_filter or {}).get("source")
        # Session scoping: a session's own uploads are searched in isolation;
        # otherwise fall back to the shared/global corpus.
        sid = None
        if source is None and session_id:
            sid = session_id if store.has_docs_for(session_id) else "global"

        match = self._fts_query(query)
        rows = store.search(match, n_results, source=source, session_id=sid)
        results = [
            {"content": r["content"], "source": r["source"],
             "page": r.get("page", "?"), "type": "catalog"}
            for r in rows
        ]
        logger.debug(f"Catalog retriever: {len(results)} chunks "
                     f"(match={'yes' if match else 'scope-only'}, source={source}, session={sid})")
        return results

    @staticmethod
    def _fts_query(text: str) -> Optional[str]:
        """Build an FTS5 MATCH string from a question: meaningful terms OR-ed
        together (quoted so punctuation never breaks FTS syntax). Returns None
        when nothing meaningful remains (caller then does a scope-only fetch)."""
        terms = re.findall(r"[a-z0-9]+", (text or "").lower())
        seen, keep = set(), []
        for t in terms:
            if (len(t) >= 3 or t.isdigit()) and t not in _STOP and t not in seen:
                seen.add(t)
                keep.append(t)
        keep = keep[:12]
        if not keep:
            return None
        return " OR ".join(f'"{t}"' for t in keep)

    # ── session helpers ───────────────────────────────────────────────────
    def has_session_docs(self, session_id: str) -> bool:
        if not session_id:
            return False
        try:
            return get_catalog_store().has_docs_for(session_id)
        except Exception:
            return False

    def session_document_sources(self, session_id: str) -> List[str]:
        if not session_id:
            return []
        try:
            return get_catalog_store().sources_for_session(session_id)
        except Exception:
            return []

    # ── named-document detection ──────────────────────────────────────────
    @staticmethod
    def _normalize_name(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", (s or "").lower())

    def find_named_document(self, query: str) -> Optional[str]:
        """If the query explicitly names an indexed document, return its source
        filename. Only identifier-like names (with a digit, '_' or '-') match, so
        plain words never accidentally scope to a document."""
        try:
            sources = get_catalog_store().list_sources()
        except Exception:
            return None
        if not sources:
            return None
        norm_q = self._normalize_name(query)
        best, best_len = None, 0
        for src in sources:
            base = src.rsplit(".", 1)[0]
            if not any(ch.isdigit() or ch in "_-" for ch in base):
                continue
            norm_b = self._normalize_name(base)
            if len(norm_b) >= 6 and norm_b in norm_q and len(norm_b) > best_len:
                best, best_len = src, len(norm_b)
        return best

    # ── authoritative document facts ──────────────────────────────────────
    def document_facts(self, source: str) -> Optional[Dict[str, Any]]:
        """Authoritative document-level facts (true patient count, page count).
        Prefers the structured extraction (exact, merged-by-ID), falling back to a
        regex scan of all chunks when the document hasn't been structured yet."""
        facts: List[str] = []
        total = None

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

        data = get_catalog_store().get_all_for_source(source)
        docs = data.get("documents") or []
        metas = data.get("metadatas") or []
        if not docs and total is None:
            return None

        if total is None:
            full = "\n".join(docs)
            ids = {i.upper() for i in re.findall(r"\b(?:PAT|SUBJ)-?\d+\b", full, re.I)}
            m = re.search(r"total\s+(?:records|patients)[:\s]+(\d+)", full, re.I)
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
        return {"content": content, "source": f"{source} (document index)", "type": "catalog"}
