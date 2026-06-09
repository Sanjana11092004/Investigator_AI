# 🏗️ Architecture & End-to-End Flow

Investigator AI is a **conversational, memory-aware RAG system** for clinical
research / pharmacovigilance. It combines **structured retrieval** (SQL over
PostgreSQL) with **semantic retrieval** (vector search over PDF narratives in
ChromaDB), and synthesizes grounded answers with a Groq-hosted Llama model.

---

## Component map

```
                         ┌─────────────────────────────┐
                         │       Streamlit UI           │  src/ui/streamlit_app.py
                         │  chat · upload · sessions    │
                         └──────────────┬──────────────┘
                                        │ HTTP (requests)
                         ┌──────────────▼──────────────┐
                         │         FastAPI API          │  src/api
                         │ /chat /ingest /sessions      │
                         │ /audit /stats /health        │
                         └──────────────┬──────────────┘
              ┌─────────────────────────┼──────────────────────────┐
              │                         │                           │
     ┌────────▼────────┐      ┌─────────▼─────────┐       ┌─────────▼────────┐
     │  RAG Pipeline   │      │    Ingestion      │       │      Memory      │
     │ classify →      │      │   Orchestrator    │       │ short + long term│
     │ retrieve →      │      │ SDTM / JSON / PDF │       │ (ContextManager) │
     │ synthesize      │      └─────────┬─────────┘       └─────────┬────────┘
     └───┬─────────┬───┘                │                           │
         │         │          ┌─────────▼──────────┐      ┌──────────▼─────────┐
    ┌────▼───┐ ┌───▼────┐     │     PostgreSQL     │◄─────┤  sessions / audit  │
    │  SQL   │ │ Vector │     │ (structured data)  │      └────────────────────┘
    │ retr.  │ │ retr.  │     └────────────────────┘
    └───┬────┘ └───┬────┘
        │      ┌───▼────────┐    ┌──────────────┐
        │      │  ChromaDB  │◄───┤  Embeddings  │  sentence-transformers
        │      │ (vectors)  │    │  + chunker   │  all-MiniLM-L6-v2 (CPU)
        │      └────────────┘    └──────────────┘
   ┌────▼────────┐
   │  Groq LLM   │  classification + answer synthesis
   └─────────────┘
```

---

## The two end-to-end flows

### A. Ingestion flow (loading data)
```
File ──▶ Orchestrator picks ingestor by extension
     ──▶ MD5 hash → skip if already ingested (dedup)
     ──▶ Parse:
           • CSV  → pandas → SQLAlchemy models → PostgreSQL
           • JSON → ClinicalTrials.gov v2 parser → clinical_studies
           • PDF  → PyMuPDF text → chunk → embed → ChromaDB
     ──▶ Register file in `ingested_documents`
```
Maps to problem-statement steps 1–4 (Upload → Extract → Chunk+Embed → Vector store).
Details in [PIPELINES.md](./PIPELINES.md) and [DATA_PROCESSING.md](./DATA_PROCESSING.md).

### B. Query flow (asking a question)
```
User question (+ session_id)
  │
  ▼ 1. Load session context + recent history          (Memory)
  ▼ 2. Classify query → strategy (sql|vector|hybrid),  (QueryClassifier, LLM)
       target tables, filters (study/patient/age/...)
  ▼ 3. Retrieve evidence:
        • SQL retriever  → structured rows from Postgres
        • Vector retriever → semantic chunks from ChromaDB
  ▼ 4. Build prompt: system + evidence + history + question
  ▼ 5. Groq LLM synthesizes a grounded answer
  ▼ 6. Extract clinical entities from Q + A            (EntityExtractor)
  ▼ 7. Update session context from entities            (Memory)
  ▼ 8. Log everything to audit_trail                   (Audit)
  ▼
Answer + sources + entities + retrieval-type + latency + tokens
```
Maps to problem-statement steps 5–6 (Conversational AI with memory → UI output).

---

## How memory makes follow-ups work

The headline feature ("remembers the previous study context and continues without
repeating information") is implemented in two layers:

- **Short-term memory** (`src/memory/short_term.py`): an in-process sliding window
  of the last *N* turns.
- **Long-term memory** (`src/memory/long_term.py`): every turn + the active
  study/patient context is persisted to the `investigation_sessions` table in
  PostgreSQL, so a session survives restarts.

After each answer, extracted entities update the session's `active_study_id` /
`active_patient_id`. On the next question, the classifier **injects that context**
into the query — so *"What adverse events did this patient have?"* resolves to the
patient from the previous turn.

> **Design safeguard:** the active patient is only pinned when a turn refers to a
> *single* subject (a list query of many patients does not pin one), and a value is
> only treated as a study id if it looks like one — this prevents a patient id such
> as `SUBJ-0007` from poisoning later queries. See `auto_update_context_from_entities`.

---

## Hybrid retrieval — why two retrievers?

Clinical questions split into two shapes:

| Question shape | Best source | Strategy |
|---|---|---|
| "serious AEs", "patients > 60", "ALT values" | structured tables | **sql** |
| "describe the narrative", "summarize the case" | free-text PDF | **vector** |
| "grade-3 AEs with narrative context" | both | **hybrid** |

An LLM **query classifier** decides per-question. If its output is unparseable, it
falls back to a rule-based classifier and defaults to **hybrid** (run both) so no
evidence source is missed.
