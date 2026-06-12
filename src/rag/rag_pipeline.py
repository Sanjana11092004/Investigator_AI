"""
Main RAG Pipeline — orchestrates SQL + Vector retrieval and LLM synthesis.
This is the core of the system.
"""
import time
import json
from typing import Dict, Any, List, Tuple

from sqlalchemy.orm import Session
from loguru import logger

from src.rag.query_classifier import QueryClassifier
from src.rag.sql_retriever import SQLRetriever
from src.catalog.catalog_retriever import CatalogRetriever
from src.llm.groq_client import GroqClient
from src.llm.prompt_templates import SYSTEM_PROMPT, RAG_PROMPT
from src.entity_extraction.extractor import EntityExtractor
from src.database.models.audit import AuditEntry


class RAGPipeline:
    """
    Full RAG pipeline: classify → retrieve → synthesize → respond.
    
    Supports hybrid retrieval (SQL + vector), conversation context,
    entity extraction, and audit logging.
    """

    def __init__(self, db: Session):
        self.db = db
        self.classifier = QueryClassifier()
        self.sql_retriever = SQLRetriever(db)
        # Catalog lookup (SQLite FTS); kept as `vector_retriever` attribute name
        # so the retrieval logic below is unchanged — it's the same interface.
        self.vector_retriever = CatalogRetriever()
        self.llm = GroqClient()
        self.entity_extractor = EntityExtractor()

    def query(
        self,
        question: str,
        conversation_history: List[Dict[str, str]],
        session_context: Dict[str, Any],
        session_id: str = None,
    ) -> Dict[str, Any]:
        """
        Process a user question through the full RAG pipeline.
        
        Args:
            question: User's natural language question.
            conversation_history: List of prior {role, content} messages.
            session_context: Current investigation context dict.
            session_id: For audit logging.
        
        Returns:
            Dict with: answer, sources, entities, retrieval_type, tokens_used, latency_ms
        """
        start_time = time.time()

        # 1. Classify query
        classification = self.classifier.classify(question, session_context)
        logger.info(f"CLASSIFICATION: {classification}")
        strategy = classification.get("strategy", "hybrid")

        # 1b. If the user explicitly named an indexed document (e.g.
        # "how many patients are in patient_narrative_001"), the question is ABOUT
        # that document. Answer it from the document via vector search scoped to
        # that file, and skip SQL entirely — otherwise a structured 'patients'
        # table count (0, because the doc name isn't a patient) would contradict
        # the document's own content (5 patients). This keeps "count" and
        # "summarize" of the same document consistent.
        named_doc = self.vector_retriever.find_named_document(question)
        if named_doc:
            strategy = "vector"
            classification["strategy"] = "vector"
            logger.info(f"Query names document '{named_doc}' → vector-only, scoped to that file")

        logger.info(f"Query strategy: {strategy}")

        # If THIS session uploaded its own document(s), the question is about that
        # upload — answer from it and NOT from the shared SDTM/demo database. We
        # treat it exactly like a named-document query: skip SQL, scope retrieval
        # to the session. (The DB cohort leaking into uploaded-file answers was the
        # reported bug.)
        session_has_docs = bool(session_id) and self.vector_retriever.has_session_docs(session_id)
        session_sources = (self.vector_retriever.session_document_sources(session_id)
                           if session_has_docs and not named_doc else [])
        doc_scoped = bool(named_doc) or bool(session_sources)
        if doc_scoped:
            strategy = "vector"   # reported retrieval type; SQL is intentionally skipped

        # 2. Retrieve from appropriate sources
        sql_results = []
        vector_results = []

        if strategy in ["sql", "hybrid"] and not doc_scoped:
            sql_results = self.sql_retriever.retrieve(classification, question)
            logger.info(f"SQL RESULTS: {len(sql_results)}")

        # Vector (PDF narrative) retrieval, in priority order:
        #  • named document      → scope to that file.
        #  • session's own upload → scope to the session's file(s).
        #  • vector/hybrid        → semantic search at the normal relevance floor.
        #  • sql with NO rows     → narrative fallback, but only STRONGLY relevant
        #    chunks (≥0.45) so unrelated PDF content isn't blended into a structured
        #    answer; sql WITH rows → do not pull the PDF.
        if named_doc:
            # Scope retrieval to the named document.
            vector_results = self.vector_retriever.retrieve(
                question, metadata_filter={"source": named_doc}, session_id=session_id)
            vector_results = self._document_evidence([named_doc], question) + vector_results
            logger.info(f"VECTOR RESULTS (named doc {named_doc}): {len(vector_results)}")
        elif session_sources:
            # This session uploaded its OWN file(s): answer from them, scoped to the
            # session (SQL was skipped above), so the shared DB cohort can't leak in.
            vector_results = self.vector_retriever.retrieve(question, session_id=session_id)
            vector_results = self._document_evidence(session_sources, question) + vector_results
            logger.info(f"VECTOR RESULTS (session docs {session_sources}): {len(vector_results)}")
        elif strategy in ["vector", "hybrid"]:
            vector_results = self.vector_retriever.retrieve(question, session_id=session_id)
            logger.info(f"VECTOR RESULTS: {len(vector_results)}")
        elif not sql_results:
            vector_results = self.vector_retriever.retrieve(
                question, min_similarity=0.45, session_id=session_id)
            logger.info(f"VECTOR FALLBACK RESULTS: {len(vector_results)}")

        # Document evidence leads when the query is scoped to a document.
        all_results = (vector_results + sql_results) if doc_scoped else (sql_results + vector_results)

        # 3. Format evidence for LLM
        evidence_text = self._format_evidence(all_results)

        # 4. Format conversation history (last 3 turns keeps follow-up context
        #    while keeping the request small enough to avoid per-minute throttling)
        history_text = self._format_history(conversation_history[-6:])

        # 5. Build context summary
        context_summary = self._build_context_summary(session_context)

        # 6. Call LLM
        system = SYSTEM_PROMPT.format(context_summary=context_summary)
        user_prompt = RAG_PROMPT.format(
            evidence=evidence_text or "No specific data retrieved. Answer based on general clinical knowledge.",
            history=history_text or "No prior conversation.",
            question=question,
        )

        response_text, tokens = self.llm.chat(
            messages=[{"role": "user", "content": user_prompt}],
            system_prompt=system,
        )

        # 7. Extract entities from response
        entities = self.entity_extractor.extract(question + " " + response_text)

        latency = round((time.time() - start_time) * 1000, 1)

        # 8. Log to audit trail
        sources = [r.get("source", "unknown") for r in all_results]
        self._log_audit(
            session_id=session_id,
            query=question,
            retrieval_type=strategy,
            sources=sources,
            response=response_text,
            entities=entities,
            latency=latency,
            tokens=tokens,
        )

        return {
            "answer": response_text,
            "sources": list(set(sources)),
            "entities": entities,
            "retrieval_type": strategy,
            "sql_results_count": len(sql_results),
            "vector_results_count": len(vector_results),
            "tokens_used": tokens,
            "latency_ms": latency,
        }

    # Keep the evidence block small enough to fit comfortably inside the LLM
    # request budget (also conserves the daily token quota). Free-tier models
    # reject oversized requests, so we cap per-source and total length.
    MAX_SOURCE_CHARS = 6000
    MAX_EVIDENCE_CHARS = 14000

    def _document_evidence(self, sources: List[str], question: str) -> List[Dict[str, Any]]:
        """Authoritative, exact evidence for the given document source(s):
        document-level facts (true patient count, page count) plus structured
        records for any patient IDs named in the question. Prepended ahead of the
        semantically-retrieved chunks so counts/lookups don't depend on which few
        chunks search happened to surface."""
        out: List[Dict[str, Any]] = []
        try:
            from src.ingestion.pdf_structurer import PDFStructurer
        except Exception:  # noqa: BLE001
            PDFStructurer = None
        for src in sources:
            facts = self.vector_retriever.document_facts(src)
            if facts:
                out.append(facts)
            if PDFStructurer is not None:
                try:
                    out.extend(PDFStructurer.patient_evidence_for_query(src, question))
                except Exception as e:  # noqa: BLE001
                    logger.warning(f"structured patient lookup failed (non-fatal) for {src}: {e}")
        return out

    def _format_evidence(self, results: List[Dict[str, Any]]) -> str:
        """Format retrieved results into a readable (size-bounded) evidence block."""
        if not results:
            return ""

        parts = []
        total = 0
        for i, r in enumerate(results, 1):
            source_type = r.get("type", "unknown").upper()
            source = r.get("source", "unknown")
            content = r.get("content", "")
            if len(content) > self.MAX_SOURCE_CHARS:
                content = content[: self.MAX_SOURCE_CHARS] + "\n… (additional rows truncated)"

            header = (f"[{source_type} Source {i} — {source}, page {r['page']}]"
                      if r.get("page") else f"[{source_type} Source {i} — {source}]")
            block = f"{header}\n{content}"
            parts.append(block)
            total += len(block)
            if total >= self.MAX_EVIDENCE_CHARS:
                break

        text = "\n\n---\n\n".join(parts)
        if len(text) > self.MAX_EVIDENCE_CHARS:
            text = text[: self.MAX_EVIDENCE_CHARS] + "\n… (evidence truncated to fit context)"
        return text

    def _format_history(self, history: List[Dict[str, str]]) -> str:
        """Format conversation history for injection into prompt."""
        if not history:
            return ""
        lines = []
        for msg in history:
            role = "User" if msg["role"] == "user" else "Assistant"
            lines.append(f"{role}: {msg['content'][:300]}")  # truncate long messages
        return "\n".join(lines)

    def _build_context_summary(self, context: Dict[str, Any]) -> str:
        """Build a human-readable context summary for the system prompt."""
        if not context:
            return "No active investigation context."

        parts = []
        if context.get("active_study_id"):
            parts.append(f"Active Study: {context['active_study_id']}")
        if context.get("active_patient_id"):
            parts.append(f"Active Patient: {context['active_patient_id']}")
        if context.get("investigation_context"):
            for k, v in context["investigation_context"].items():
                if v:
                    parts.append(f"{k}: {v}")

        return " | ".join(parts) if parts else "General investigation — no specific context yet."

    def _log_audit(
        self,
        session_id: str,
        query: str,
        retrieval_type: str,
        sources: List[str],
        response: str,
        entities: Dict,
        latency: float,
        tokens: Dict,
    ) -> None:
        """Write an audit entry to the database."""
        try:
            entry = AuditEntry(
                session_id=str(session_id) if session_id else None,
                action_type="query",
                user_query=query,
                retrieval_type=retrieval_type,
                retrieved_sources=sources,
                llm_response=response[:2000],  # truncate
                entities_extracted=entities,
                latency_ms=latency,
                tokens_used=tokens,
            )
            self.db.add(entry)
            self.db.commit()
        except Exception as e:
            logger.warning(f"Audit log failed (non-critical): {e}")
            self.db.rollback()