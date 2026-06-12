"""SQLite FTS5 catalog store for narrative chunks.

This is the "Index + catalog (sqlite, searchable)" box from the architecture:
narrative chunks (from PDF/doc extraction) are indexed in a single FTS5 table in
the same SQLite database that holds the structured tables. Retrieval is keyword
full-text search (bm25-ranked), scoped by source and/or session — no vector store,
no embeddings, no external service.
"""
from functools import lru_cache
from typing import Any, Dict, List, Optional

from loguru import logger

from src.database.connection import engine

_TABLE = "narrative_chunks"
_COLUMNS = ("chunk_id", "content", "source", "page", "session_id",
            "doc_type", "chunk_index", "file_hash")


class CatalogStore:
    """Full-text catalog of narrative chunks, backed by SQLite FTS5."""

    def __init__(self) -> None:
        self._ensure_table()

    # ── connection helper (shares the ORM engine's SQLite file/pool) ──────
    def _run(self, sql: str, params=None, *, many=False, fetch=False):
        raw = engine.raw_connection()
        try:
            cur = raw.cursor()
            if many:
                cur.executemany(sql, params or [])
            else:
                cur.execute(sql, params or ())
            rows = cur.fetchall() if fetch else None
            raw.commit()
            return rows
        finally:
            raw.close()

    def _ensure_table(self) -> None:
        # page/chunk_index/file_hash/doc_type stored but not full-text indexed;
        # content/source/session_id are searchable + usable as filters.
        self._run(
            f"CREATE VIRTUAL TABLE IF NOT EXISTS {_TABLE} USING fts5("
            "chunk_id UNINDEXED, content, source, page UNINDEXED, session_id, "
            "doc_type UNINDEXED, chunk_index UNINDEXED, file_hash UNINDEXED)"
        )

    # ── writes ────────────────────────────────────────────────────────────
    def add_chunks(self, rows: List[Dict[str, Any]]) -> int:
        """Insert chunk rows (dicts with the _COLUMNS keys). Skips chunk_ids that
        already exist so re-ingestion is incremental. Returns count inserted."""
        if not rows:
            return 0
        ids = [r["chunk_id"] for r in rows]
        existing = self._existing_ids(ids)
        fresh = [r for r in rows if r["chunk_id"] not in existing]
        if not fresh:
            logger.debug("catalog: all chunks already indexed, skipping")
            return 0
        placeholders = ", ".join("?" for _ in _COLUMNS)
        cols = ", ".join(_COLUMNS)
        self._run(
            f"INSERT INTO {_TABLE} ({cols}) VALUES ({placeholders})",
            [[r.get(c) for c in _COLUMNS] for r in fresh],
            many=True,
        )
        logger.info(f"catalog: indexed {len(fresh)} new chunks")
        return len(fresh)

    def _existing_ids(self, ids: List[str]) -> set:
        if not ids:
            return set()
        out = set()
        # chunked IN() to stay under SQLite's parameter limit
        for i in range(0, len(ids), 400):
            batch = ids[i:i + 400]
            q = f"SELECT chunk_id FROM {_TABLE} WHERE chunk_id IN ({','.join('?' for _ in batch)})"
            rows = self._run(q, batch, fetch=True) or []
            out.update(r[0] for r in rows)
        return out

    def delete_by_source(self, source: str) -> None:
        self._run(f"DELETE FROM {_TABLE} WHERE source = ?", (source,))
        logger.info(f"catalog: deleted all chunks from source: {source}")

    # ── reads ─────────────────────────────────────────────────────────────
    def search(self, match_query: Optional[str], n_results: int,
               source: Optional[str] = None,
               session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Full-text search. If match_query is None/empty, returns scoped chunks
        without ranking (useful for 'summarize the document')."""
        filters, params = [], []
        if match_query:
            filters.append(f"{_TABLE} MATCH ?")
            params.append(match_query)
        if source:
            filters.append("source = ?")
            params.append(source)
        if session_id:
            filters.append("session_id = ?")
            params.append(session_id)
        where = (" WHERE " + " AND ".join(filters)) if filters else ""
        order = " ORDER BY rank" if match_query else " ORDER BY chunk_index"
        sql = (f"SELECT content, source, page, chunk_index, file_hash, doc_type"
               f" FROM {_TABLE}{where}{order} LIMIT ?")
        params.append(n_results)
        rows = self._run(sql, params, fetch=True) or []
        return [
            {"content": r[0], "source": r[1], "page": r[2],
             "chunk_index": r[3], "file_hash": r[4], "doc_type": r[5]}
            for r in rows
        ]

    def get_all_for_source(self, source: str) -> Dict[str, Any]:
        """All chunks for one source as {documents, metadatas} (document_facts uses
        this shape)."""
        rows = self._run(
            f"SELECT content, page, chunk_index, file_hash FROM {_TABLE} "
            f"WHERE source = ? ORDER BY chunk_index", (source,), fetch=True) or []
        return {
            "documents": [r[0] for r in rows],
            "metadatas": [{"page": _as_int(r[1]), "chunk_index": r[2],
                           "file_hash": r[3], "source": source} for r in rows],
        }

    def get_document_count(self) -> int:
        rows = self._run(f"SELECT count(*) FROM {_TABLE}", fetch=True)
        return rows[0][0] if rows else 0

    def has_docs_for(self, session_id: str) -> bool:
        if not session_id:
            return False
        rows = self._run(
            f"SELECT 1 FROM {_TABLE} WHERE session_id = ? LIMIT 1",
            (session_id,), fetch=True)
        return bool(rows)

    def sources_for_session(self, session_id: str) -> List[str]:
        if not session_id:
            return []
        rows = self._run(
            f"SELECT DISTINCT source FROM {_TABLE} WHERE session_id = ?",
            (session_id,), fetch=True) or []
        return sorted(r[0] for r in rows if r[0])

    def list_sources(self) -> List[str]:
        rows = self._run(f"SELECT DISTINCT source FROM {_TABLE}", fetch=True) or []
        return sorted(r[0] for r in rows if r[0])

    def all_chunks(self) -> List[Dict[str, Any]]:
        """Every indexed chunk as a dict (used to export narrative envelopes)."""
        cols = ", ".join(_COLUMNS)
        rows = self._run(f"SELECT {cols} FROM {_TABLE} ORDER BY source, chunk_index",
                         fetch=True) or []
        return [dict(zip(_COLUMNS, r)) for r in rows]


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return v


@lru_cache(maxsize=1)
def get_catalog_store() -> CatalogStore:
    """Singleton catalog store."""
    return CatalogStore()
