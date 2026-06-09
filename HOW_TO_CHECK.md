# ✅ Investigator AI — Verification & How-to-Check Guide

This document maps the **project problem statement** to the **actual implementation**,
shows that the system runs in the required order, and explains how to check it yourself.

---

## 1. Does it follow the required end-to-end flow?  → **Yes.**

Each step in the problem statement is implemented and was verified live on
**2026-06-09** against the loaded dataset (250 patients, 416 studies, 731 PDF chunks).

| # | Problem-statement step | Where it lives in the code | Verified |
|---|------------------------|----------------------------|----------|
| 1 | **Document Upload** (trial reports, AE cases, narratives, safety docs) | `src/api/routers/ingest.py` `/ingest/upload` + Streamlit sidebar uploader (`src/ui/streamlit_app.py`) | ✅ CSV/JSON/PDF upload; duplicate files auto-skipped (MD5 hash) |
| 2 | **Data Extraction** (patients, drugs, AEs, study IDs, lab findings, outcomes) | `src/ingestion/*` (SDTM/JSON/PDF ingestors) + `src/entity_extraction/extractor.py` | ✅ Structured rows parsed into Postgres; entities extracted on every answer |
| 3 | **Chunking + Embeddings** | `src/embeddings/chunker.py` + `src/embeddings/embedder.py` (sentence-transformers `all-MiniLM-L6-v2`, local/CPU) | ✅ Narrative PDF → **731 chunks** embedded |
| 4 | **Vector Database Storage** | `src/vector_store/chroma_store.py` (ChromaDB, persistent at `./chroma_db`) | ✅ 731 vectors stored & queryable |
| 5 | **Conversational AI with Memory** | `src/rag/rag_pipeline.py` (classify → retrieve → synthesize) + `src/memory/*` (short + long term) | ✅ Follow-ups work without repeating context (see §4) |
| 6 | **Final Output in Streamlit UI** (answers, evidence, entities, metadata) | `src/ui/streamlit_app.py` | ✅ Shows answer + source badges + retrieval type + latency + tokens |

**Live proof the RAG actually uses both retrieval modes:**
- *"Show all serious adverse events"* → `strategy = sql`, source = `adverse_events table`
- *"Describe the hepatotoxicity case narrative"* → `strategy = vector`, source = `patient_narrative_001.pdf` (answer cites pages 82, 70, 96…)
- The classifier also supports `hybrid` (runs both) when a question needs structured **and** narrative context.

---

## 2. Functional & system requirements

| Requirement | Status |
|---|---|
| Upload investigation documents | ✅ |
| Ask questions conversationally | ✅ |
| Perform follow-up investigations | ✅ (context carried in session) |
| View summarized findings | ✅ (LLM synthesis + evidence) |
| Process unstructured medical documents | ✅ (PDF → text → chunks → vectors) |
| Extract healthcare entities | ✅ (spaCy + clinical rule-based) |
| Store embeddings in vector database | ✅ (ChromaDB) |
| Support conversational memory | ✅ (short-term window + Postgres-backed long-term) |
| Generate context-aware responses | ✅ (verified, see §4) |

---

## 3. Tech stack — suggested vs. actually used

The problem statement lists a **suggested** stack. Here is what was actually used and why
(every functional requirement is still met):

| Component | Suggested | Implemented | Note |
|---|---|---|---|
| Frontend | Streamlit | **Streamlit** | exact match |
| Backend | Python | **Python + FastAPI** | adds a real REST API (`/docs`) |
| NLP | SciSpacy / MedSpaCy | **spaCy `en_core_web_sm` + rule-based clinical patterns** | scispaCy is optional (depends on `nmslib`, which doesn't build on modern Python); the extractor falls back gracefully and the rule-based layer covers patients/drugs/AEs/labs/outcomes |
| RAG framework | LangChain | **Custom hybrid RAG** (langchain libs installed) | a purpose-built SQL+vector classifier/retriever; more transparent than a generic chain |
| Vector DB | FAISS / ChromaDB | **ChromaDB** | one of the two suggested options |
| File processing | PyPDF / python-docx | **PyMuPDF (`fitz`)** | faster, more robust PDF text extraction |
| LLM | (Groq Llama) | **Groq `llama-3.3-70b-versatile`** | current supported model (the older `llama-3.1-70b-versatile` is deprecated) |
| Relational store | — | **PostgreSQL 18 + SQLAlchemy 2 + Alembic** | holds structured SDTM data + sessions + audit |

---

## 4. How to check it yourself

> Both servers are started for you. If they are not running, see §6 to relaunch.

### Open the UI
**http://localhost:8501**  (API backend: **http://localhost:8000**, Swagger docs at **/docs**)

### Demo A — the 3 flagship queries (proves retrieval + memory)
Click **➕ New Investigation**, then ask in order:
1. `Show all serious adverse events`
2. `Which patients had liver toxicity?`
3. `Show only patients above age 60`

### Demo B — context memory (the headline feature)
Start a **New Investigation** and ask:
1. `Show the demographics for patient SUBJ-0007`
2. `What serious adverse events did this patient have?`
   → It answers about **SUBJ-0007** even though you didn't repeat the ID — it remembered.

### Demo C — semantic / narrative RAG (vector DB)
1. `Describe the hepatotoxicity case narrative from the patient report`
   → retrieval type shows **vector**, evidence comes from the narrative **PDF**.

### What to look at under each answer
- **Source badges** — which table / document the evidence came from
- **Retrieval type** — `sql`, `vector`, or `hybrid`
- **Latency** and **token count**
- **Sidebar → 📂 Ingested Documents** — the 7 loaded files
- **Sidebar → 🧭 Active Context** — the remembered study / patient
- **Sidebar → 📁 Upload Data** — drop a CSV/JSON/PDF to ingest more (re-uploading the same file is skipped)

### Run the automated tests
```powershell
.\venv\Scripts\python.exe -m pytest -q      # 64 passed
```

---

## 5. The shareable database dump
- `investigator_ai_dump.sql` (≈83 MB) and `investigator_ai_dump.sql.gz` (≈9 MB)
- Restore on any machine:
  ```powershell
  & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE investigator_ai;"
  & "C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -d investigator_ai -f investigator_ai_dump.sql
  ```
  (Dump was restore-tested into a throwaway DB; row counts matched exactly.)

---

## 6. Relaunch the servers (two terminals in the project folder)
```powershell
# Terminal 1 — backend API
.\venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000

# Terminal 2 — Streamlit UI
.\venv\Scripts\streamlit.exe run src/ui/streamlit_app.py --server.port 8501
```

---

## 7. Data loaded (current state)
| Table | Rows |
|---|---|
| patients | 250 |
| adverse_events | 566 |
| lab_results | 16,979 |
| concomitant_medications | 722 |
| medical_histories | 585 |
| clinical_studies | 416 |
| ingested_documents | 7 |
| ChromaDB narrative chunks | 731 |
