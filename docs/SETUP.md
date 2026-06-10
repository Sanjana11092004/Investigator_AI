# 🛠️ Setup Guide

Step-by-step instructions to run **Investigator AI** locally on Windows
(macOS/Linux are analogous — swap the venv activation path).

---

## 1. Prerequisites

| Requirement | Notes |
|---|---|
| **Python 3.12** | The pinned ML stack (`numpy 1.26.4`, `torch`, `spaCy 3.8.2`, `chromadb 0.5.15`) has wheels for 3.12. 3.13/3.14 are **not** supported by these pins. |
| **PostgreSQL 14+** | Tested on PostgreSQL 18. Must be running on `localhost:5432`. |
| **Groq API key** | Free at <https://console.groq.com>. Used for the LLM (query classification + answer synthesis). |
| ~3 GB disk | Mostly PyTorch (pulled in transitively by `sentence-transformers`). |

---

## 2. Create the virtual environment & install dependencies

```powershell
cd Investigator_AI
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m spacy download en_core_web_sm
```

> **Why `torch` downloads** even though it isn't in your list: `sentence-transformers`
> (the local embedding library) is built on PyTorch, so pip pulls it in
> automatically. It's a transitive dependency, not an error.

> **scispaCy** is optional and commented out in `requirements.txt` (its `nmslib`
> dependency doesn't build on modern Python). The entity extractor automatically
> falls back to `en_core_web_sm` + rule-based patterns.

---

## 3. Configure environment variables

Copy `.env.template` → `.env` and fill in:

```env
GROQ_API_KEY=<your-groq-key>
GROQ_MODEL=llama-3.1-8b-instant          # or llama-3.3-70b-versatile for higher quality
GROQ_MAX_TOKENS=1536
GROQ_TEMPERATURE=0.1

POSTGRES_PASSWORD=<your-postgres-password>
DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/investigator_ai
TEST_DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/investigator_ai_test

CHROMA_PERSIST_DIR=./chroma_db
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
CHUNK_SIZE=512
CHUNK_OVERLAP=64
VECTOR_TOP_K=5
SQL_MAX_ROWS=20
MEMORY_WINDOW_SIZE=10
```

`.env` is gitignored — never commit it.

---

## 4. Create the databases & schema

```powershell
$PG = "C:\Program Files\PostgreSQL\18\bin\psql.exe"
& $PG -U postgres -c "CREATE DATABASE investigator_ai;"
& $PG -U postgres -c "CREATE DATABASE investigator_ai_test;"

# Build all tables from the Alembic migration
.\venv\Scripts\python.exe -m alembic upgrade head
```

This creates 10 tables: `patients`, `adverse_events`, `lab_results`,
`concomitant_medications`, `medical_histories`, `clinical_studies`,
`ingested_documents`, `investigation_sessions`, `audit_trail`, `alembic_version`.

---

## 5. Load the clinical dataset

Place the data under `data/` (gitignored):

```
data/sdtm/{DM,AE,LB,CM,MH}.csv
data/clinical_trials/clinicaltrials_hepatotoxicity.json
data/narratives/patient_narrative_001.pdf
```

Then bulk-ingest (DM must load before AE/LB/CM/MH — the orchestrator handles ordering):

```powershell
.\venv\Scripts\python.exe -m scripts.ingest_all
```

Expected result: **250 patients · 566 adverse events · 16,979 lab results ·
722 medications · 585 medical histories · 416 studies · 731 PDF chunks**.

---

## 6. Run

**Terminal 1 — API backend:**
```powershell
.\venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000
# http://localhost:8000   (Swagger docs: /docs)
```

**Terminal 2 — Streamlit UI:**
```powershell
.\venv\Scripts\streamlit.exe run src/ui/streamlit_app.py --server.port 8501
# http://localhost:8501
```

---

## 7. Run the tests

```powershell
.\venv\Scripts\python.exe -m pytest -q     # 65 passed
```

Tests run against `investigator_ai_test` (created/dropped automatically per session).
LLM calls are mocked, so no live Groq key is needed for tests.

---

## 8. Troubleshooting

| Symptom | Cause / Fix |
|---|---|
| `429 ... tokens per day` on chat | Groq **daily** quota hit. Switch `GROQ_MODEL` (8B ≈ 500k/day, 70B = 100k/day) or wait for reset. |
| Follow-up questions slow (~30s) | Groq **per-minute** token limit — space questions out, or switch to 70B (2× the limit). See [PIPELINES.md](./PIPELINES.md). |
| `413 Request too large` | Evidence too big for the model tier — already mitigated by `SQL_MAX_ROWS` + evidence caps. |
| `spaCy model not found` | Run `python -m spacy download en_core_web_sm`. |
| Backend "offline" in UI | Start the API (step 6) before the UI; the UI calls it server-side. |
