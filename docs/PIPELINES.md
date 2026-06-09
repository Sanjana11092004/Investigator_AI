# 🔁 Pipelines

The system is built from five pipelines. Each is small, testable, and has a
clear single responsibility.

---

## 1. Ingestion pipeline
**Code:** `src/ingestion/`

```
ingest_file(path, original_filename)
  └─ IngestionOrchestrator routes by extension/name:
       .json → ClinicalTrialsIngestor
       .csv  → SDTMIngestor   (DM / AE / LB / CM / MH)
       .pdf  → PDFIngestor
  └─ each ingestor:
       1. compute_file_hash (MD5)            ── deduplication.py
       2. is_already_ingested?  → skip       (ingested_documents.status == completed)
       3. parse + persist (see DATA_PROCESSING.md)
       4. register_document(...)             ── records file, type, count, status
```

- **Deduplication** is content-based (MD5 of bytes), so re-uploading the same file
  is skipped regardless of filename.
- **Uploads** register under the *original* filename (not the server's temp file).
- **Ordering:** `ingest_directory` processes `*.json → DM.csv → LB/AE/CM/MH → *.pdf`
  so patient rows exist before domains that foreign-key to them.

**Endpoints:** `POST /ingest/upload`, `GET /ingest/documents`.

---

## 2. RAG query pipeline
**Code:** `src/rag/rag_pipeline.py`

```
RAGPipeline.query(question, history, session_context, session_id)
  1. classify          → QueryClassifier (LLM, JSON out)  → {strategy, sql_entities, filters, search_terms}
  2. retrieve
       if strategy in (sql, hybrid):   SQLRetriever.retrieve(...)
       if strategy in (vector, hybrid): VectorRetriever.retrieve(...)
  3. _format_evidence  → size-capped evidence block (MAX_EVIDENCE_CHARS)
  4. _format_history   → last 3 turns, truncated
  5. LLM synthesis     → GroqClient.chat(system=SYSTEM_PROMPT, user=RAG_PROMPT)
  6. EntityExtractor.extract(question + answer)
  7. _log_audit(...)   → audit_trail
  return {answer, sources, entities, retrieval_type, tokens_used, latency_ms}
```

### Query classifier (`src/rag/query_classifier.py`)
- Calls the LLM with a few-shot prompt to produce strict JSON.
- Extracts a patient id from the raw text via regex **before** the LLM call (highest
  confidence), and merges session context (active study/patient) into the filters.
- Reorders `sql_entities` by clinical priority and drops `studies` unless the query
  is explicitly about trial design/sponsor/NCT.
- On invalid JSON → rule-based fallback, strategy forced to **hybrid**.

### SQL retriever (`src/rag/sql_retriever.py`)
- Per-table query builders for AE / patients / labs / meds / medical-history / studies.
- Filters: `study_id`, `patient_id`, `serious_only` (`aeserfl='Y'`), `severity`,
  `age_filter` (`> / >= / < / <= / between`), AE `grade` (parsed from text).
- Keyword search matches **both** the coded value (`aedecod`) and the human term
  (`aeterm`) — so "liver toxicity" finds `Hepatotoxicity`.
- Built-in count shortcuts for "how many patients/studies/adverse events".

### Vector retriever (`src/rag/vector_retriever.py`)
- Embeds the query, queries ChromaDB (cosine), converts distance→similarity,
  drops results below a 0.3 similarity floor, returns chunks with source + page.

---

## 3. Memory pipeline
**Code:** `src/memory/`

```
ContextManager(db, session_id)
  ├─ ShortTermMemory   (deque, last N turns, in-process)
  └─ LongTermMemory    (investigation_sessions table)
       create/load/list/archive sessions
       append_message, get_history(last_n)
       update_context(study_id, patient_id, extra)
       auto_update_context_from_entities(...)   ← single-patient pinning safeguard
```
Each chat turn writes to both layers; context is read back in on the next turn and
injected into the classifier. See [ARCHITECTURE.md](./ARCHITECTURE.md) §memory.

---

## 4. Embedding pipeline
**Code:** `src/embeddings/`, `src/vector_store/`

```
PDF text ──▶ chunk_text (sentence-aware sliding window, CHUNK_SIZE/OVERLAP)
         ──▶ Embedder.embed_documents (sentence-transformers all-MiniLM-L6-v2)
                 │  disk-cached by text hash (diskcache) — no re-embedding
         ──▶ VectorStore.add (ChromaDB persistent, cosine, dedup by chunk id)
```
Queries use `embed_query` (also cached). The model runs locally on CPU — free, no
external embedding API.

---

## 5. Audit pipeline
**Code:** `src/database/models/audit.py`, `src/api/routers/audit.py`

Every chat query writes an `audit_trail` row: session, timestamp, query, retrieval
type, sources, (truncated) LLM response, extracted entities, latency, token usage,
and any error. Exposed read-only via `GET /audit?session_id=...`. Audit failures are
non-fatal (logged + rolled back) so they never break a user response.

---

## A note on Groq rate limits (why follow-ups can be slow)
Each question makes **two** LLM calls (classify + synthesize) ≈ 4–5k tokens. Groq's
free tier caps **tokens-per-minute** (8B = 6,000 TPM; 70B = 12,000 TPM), so several
questions fired within the same minute get throttled (the client retries with backoff
until they succeed — they're slow, not failing). The per-**day** quota is large
(8B ≈ 500k/day ≈ ~100 questions). Mitigations: space questions out, use 70B, reduce
tokens (already trimmed via `SQL_MAX_ROWS`, evidence caps, history trim), or use a
paid Groq tier.
