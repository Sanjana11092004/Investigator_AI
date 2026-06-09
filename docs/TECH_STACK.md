# 🧰 Tech Stack & Libraries

Every dependency, what it's used for, and why it was chosen. Versions are pinned in
`requirements.txt`.

---

## Runtime

| Component | Library / Version | Used for |
|---|---|---|
| Language | **Python 3.12** | Pinned ML stack (numpy 1.26 / torch / spaCy 3.8) has wheels for 3.12, not 3.13/3.14. |
| Web API | **FastAPI 0.115** + **Uvicorn 0.30** | REST endpoints (`/chat`, `/ingest`, `/sessions`, `/audit`, `/stats`), auto OpenAPI docs at `/docs`. |
| Validation | **Pydantic 2.9** + **pydantic-settings 2.5** | Request/response schemas; env-driven config (`src/config/settings.py`). |
| UI | **Streamlit 1.39** | Conversational chat front-end (`src/ui/streamlit_app.py`). |

## LLM & RAG

| Component | Library / Version | Used for |
|---|---|---|
| LLM | **groq 0.11** → `llama-3.1-8b-instant` / `llama-3.3-70b-versatile` | Query classification + grounded answer synthesis. |
| RAG framework | **langchain 0.3** (+ community, groq, text-splitters) | Available in the stack; the core RAG is a purpose-built SQL+vector pipeline for transparency. |
| Embeddings | **sentence-transformers 3.2** (`all-MiniLM-L6-v2`) | Local, free, CPU text embeddings (384-dim). Pulls in **torch** transitively. |
| Embedding cache | **diskcache 5.6** | Avoids re-embedding identical text across runs. |
| Vector DB | **chromadb 0.5** | Persistent cosine vector store for PDF narrative chunks. |

## Clinical NLP

| Component | Library / Version | Used for |
|---|---|---|
| NER | **spaCy 3.8** (`en_core_web_sm`) | Entity extraction (drugs/diseases) + rule-based clinical patterns. |
| (optional) | **scispaCy** *(commented out)* | Biomedical NER; skipped because its `nmslib` dep doesn't build on modern Python. Code falls back gracefully. |

## Data layer

| Component | Library / Version | Used for |
|---|---|---|
| ORM | **SQLAlchemy 2.0** | Models + queries (`src/database/`). |
| DB driver | **psycopg2-binary 2.9** | PostgreSQL connectivity. |
| Migrations | **alembic 1.13** | Schema versioning (`alembic/versions/001_initial_schema.py`). |
| Database | **PostgreSQL 18** | Structured clinical data, sessions, audit. |
| Tabular parsing | **pandas 2.2** + **numpy 1.26** | Reading/cleaning SDTM CSVs. |
| PDF | **PyMuPDF 1.24** (`fitz`) | Fast, robust PDF text extraction. |

## Utilities & tooling

| Component | Library / Version | Used for |
|---|---|---|
| Logging | **loguru 0.7** | Structured logs across the app. |
| HTTP | **httpx / requests** | UI ↔ API calls. |
| Uploads | **python-multipart 0.0.12** | File upload handling in FastAPI. |
| Tests | **pytest 8.3** + **pytest-asyncio** + **pytest-cov** | Test suite (65 tests, real Postgres test DB, mocked LLM). |
| Formatting | **black 24.10** + **isort 5.13** | Code style. |

---

## Why these choices

- **Local embeddings (sentence-transformers) over an embedding API** → zero cost,
  no per-token billing, fully offline for the vector side.
- **Groq for the LLM** → very fast inference and a usable free tier; only the
  generation step needs the network.
- **PostgreSQL + ChromaDB (hybrid)** → structured clinical questions are answered
  precisely with SQL; open-ended narrative questions use semantic search. Neither
  alone covers both. See [ARCHITECTURE.md](./ARCHITECTURE.md).
- **Custom RAG pipeline** (rather than a generic chain) → full control and visibility
  over classification, filters, evidence formatting, and audit logging.
