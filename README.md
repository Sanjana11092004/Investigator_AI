<div align="center">

# 🔬 Investigator AI Assistant with Memory

**A conversational, memory-aware RAG platform for clinical research & pharmacovigilance investigations.**

Upload clinical study documents, then interrogate them in plain English — the assistant
retrieves grounded evidence, remembers the investigation context, and answers multi-turn
follow-up questions.

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.39-FF4B4B?logo=streamlit&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-18-4169E1?logo=postgresql&logoColor=white)
![ChromaDB](https://img.shields.io/badge/Vector%20DB-ChromaDB-FF6F61)
![Groq](https://img.shields.io/badge/LLM-Groq%20Llama%203.x-F55036)
![Tests](https://img.shields.io/badge/tests-65%20passing-brightgreen)
![Code style](https://img.shields.io/badge/code%20style-black-000000)

</div>

---

## 📑 Table of Contents

- [Overview](#-overview)
- [Key Features](#-key-features)
- [Example Conversation](#-example-conversation)
- [Query Capabilities](#-query-capabilities)
- [Architecture](#️-architecture)
- [Tech Stack](#-tech-stack)
- [Getting Started](#-getting-started)
- [Usage](#-usage)
- [API Reference](#-api-reference)
- [Project Structure](#-project-structure)
- [Testing](#-testing)
- [Documentation](#-documentation)
- [Troubleshooting](#-troubleshooting)
- [License](#-license)

---

## 🎯 Overview

**Investigator AI** lets analysts upload clinical-trial reports, adverse-event datasets,
and medical narratives, then *talk to the data*. It combines **structured retrieval**
(SQL over PostgreSQL) with **semantic retrieval** (vector search over document
embeddings in ChromaDB), and synthesizes answers with a Groq-hosted Llama model —
while persisting the conversation so follow-up questions don't need to repeat context.

It implements the full document-intelligence loop: **upload → extract → chunk + embed →
vector store → conversational RAG with memory → answers with cited evidence**.

---

## ✨ Key Features

- **📥 Multi-format ingestion** — SDTM domains (DM / AE / LB / CM / MH), ClinicalTrials.gov
  JSON, and narrative PDFs, with MD5 content-based **deduplication**.
- **🔀 Hybrid RAG** — an LLM **query classifier** routes each question to SQL retrieval,
  vector retrieval, or **both**, then synthesizes a grounded, source-cited answer.
- **📊 Analytical & statistical queries** — exact `COUNT / AVG / MIN / MAX`, percentages,
  group-by ("most common…"), and arg-max ("which patient has the highest AST") computed
  **directly in SQL** — not guessed by the LLM.
- **🧩 Query decomposition** — cross-entity questions like *"average ALT among patients
  with serious adverse events"* are broken into cohort → metric sub-queries and answered exactly.
- **📚 Cross-study reasoning** — keyword-matched study retrieval with summaries for
  *"summarize / compare studies about X"*.
- **🧠 Conversational memory** — short-term window + long-term PostgreSQL sessions; the
  active study/patient context is auto-extracted and reused for follow-ups.
- **🔒 Per-session document scoping** — uploaded files are scoped to their session and
  retrieved first; one investigation's docs never leak into another's answers.
- **🗂️ Unified JSON store** — a `FileNormalizer` + exporter normalize every source into one
  metadata-rich JSON schema (`document_id, study_id, patient_id, section, entity_tags, …`).
- **🛡️ RAG safety** — prompt-injection resistance (evidence is data, not instructions),
  off-topic refusal, no PDF/CSV evidence mixing, and empty/malformed-input guards.
- **🏷️ Clinical entity extraction** — spaCy + rule-based extraction of patients, drugs,
  adverse events, studies, lab tests, diagnoses, and outcomes.
- **📝 Full audit trail** — every query, retrieval strategy, response, latency, and token count logged.
- **💬 Modern UI + REST API** — a Streamlit chat front-end backed by a documented FastAPI
  service (OpenAPI at `/docs`).

---

## 💡 Example Conversation

```
You ▸ Show all serious adverse events
AI  ▸ 14 serious adverse events found  [SQL · adverse_events]
      | Patient | Event          | Severity         | Grade | Serious | Outcome           |
      | SUBJ-0005 | Rash         | LIFE-THREATENING | 4     | Y       | FATAL             |
      | SUBJ-0007 | Hepatotoxicity| SEVERE          | 3     | Y       | RECOVERED         | ...

You ▸ Which of them had liver toxicity?         ← follow-up, no IDs repeated
AI  ▸ 7 patients with hepatotoxicity …  [SQL · adverse_events]

You ▸ Show only the ones above age 60           ← context carried forward
AI  ▸ Patients > 60 …  [SQL · patients]
```

The assistant remembers the prior study/patient context and continues the
investigation without the user re-stating it.

---

## 🔎 Query Capabilities

| Category | Example | How it's answered |
|----------|---------|-------------------|
| **Direct retrieval** | "Show demographics for SUBJ-0007" | SQL field lookup |
| **Aggregation** | "How many serious adverse events?" · "What % of patients are female?" | SQL `COUNT` + ratios |
| **Statistics** | "Mean ALT value?" · "Which patient has the highest AST?" | SQL `AVG` / `MAX` + arg-max |
| **Ranking / group-by** | "Top 5 most common adverse events" · "Most common diagnosis" | SQL `GROUP BY … ORDER BY` |
| **Cross-entity decomposition** | "Average ALT among patients with serious AEs" | cohort sub-query → metric |
| **Cross-study reasoning** | "Summarize studies about hepatotoxicity" | keyword study retrieval → LLM synthesis |
| **Document-grounded QA** | "What is the patient ID in the uploaded report?" | session-scoped vector search |
| **Multi-turn memory** | "…and which of them were fatal?" | session context carried forward |

> ℹ️ *Per-arm efficacy comparisons aren't available — the source ClinicalTrials JSON
> contains no per-arm outcome data. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).*

---

## 🏗️ Architecture

```
              ┌──────────────────────────────┐
              │          Streamlit UI         │   chat · upload · sessions · metrics
              └───────────────┬──────────────┘
                              │ HTTP
              ┌───────────────▼──────────────┐
              │           FastAPI API         │   /chat /ingest /sessions /audit /stats /health
              └───────────────┬──────────────┘
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
 ┌──────▼──────┐      ┌───────▼───────┐     ┌────────▼────────┐
 │ RAG Pipeline │      │  Ingestion    │     │     Memory      │
 │ classify →   │      │  Orchestrator │     │ short + long    │
 │ retrieve →   │      │ SDTM/JSON/PDF │     │ (ContextManager)│
 │ synthesize   │      └───────┬───────┘     └────────┬────────┘
 └──┬───────┬───┘              │                      │
    │       │          ┌───────▼────────┐    ┌─────────▼────────┐
 ┌──▼──┐ ┌──▼───┐      │   PostgreSQL   │◄───┤  sessions/audit  │
 │ SQL │ │Vector│      │ (structured)   │    └──────────────────┘
 │retr.│ │retr. │      └────────────────┘
 └──┬──┘ └──┬───┘
    │   ┌───▼──────┐    ┌──────────────┐
    │   │ ChromaDB │◄───┤  Embeddings  │  sentence-transformers all-MiniLM-L6-v2 (CPU)
    │   └──────────┘    └──────────────┘
 ┌──▼────────┐
 │ Groq LLM  │  Llama 3.x — query classification + answer synthesis
 └───────────┘
```

Detailed write-ups: **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** ·
**[docs/PIPELINES.md](docs/PIPELINES.md)** · **[docs/DATA_PROCESSING.md](docs/DATA_PROCESSING.md)**.

---

## 🧰 Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Streamlit |
| **Backend** | FastAPI · Uvicorn · Pydantic v2 |
| **LLM** | Groq — `llama-3.1-8b-instant` / `llama-3.3-70b-versatile` |
| **Embeddings** | sentence-transformers `all-MiniLM-L6-v2` (local, CPU, free) |
| **Vector store** | ChromaDB (persistent, cosine) |
| **Relational DB** | PostgreSQL · SQLAlchemy 2 · Alembic |
| **NLP** | spaCy `en_core_web_sm` (scispaCy optional) |
| **Document parsing** | PyMuPDF · pandas |
| **Testing** | pytest · pytest-asyncio · pytest-cov |

Full list with versions & rationale: **[docs/TECH_STACK.md](docs/TECH_STACK.md)**.

---

## 🚀 Getting Started

### Prerequisites
- **Python 3.12** (the pinned ML stack targets 3.12)
- **PostgreSQL 14+** running on `localhost:5432`
- A free **Groq API key** — <https://console.groq.com>

### 1 · Install
```bash
py -3.12 -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\venv\Scripts\python.exe -m spacy download en_core_web_sm
```

### 2 · Configure
```bash
cp .env.template .env      # then edit:
#   GROQ_API_KEY=...
#   DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/investigator_ai
#   TEST_DATABASE_URL=postgresql://postgres:<pw>@localhost:5432/investigator_ai_test
```

### 3 · Create the database
```bash
psql -U postgres -c "CREATE DATABASE investigator_ai;"
psql -U postgres -c "CREATE DATABASE investigator_ai_test;"
.\venv\Scripts\python.exe -m alembic upgrade head
```

### 4 · Load data & run
```bash
# place data under data/{sdtm,clinical_trials,narratives}/ then:
.\venv\Scripts\python.exe -m scripts.ingest_all

# two terminals:
.\venv\Scripts\python.exe -m uvicorn src.api.main:app --port 8000
.\venv\Scripts\streamlit.exe run src/ui/streamlit_app.py --server.port 8501
```

📖 Full guide incl. troubleshooting: **[docs/SETUP.md](docs/SETUP.md)**

---

## 🖥️ Usage

1. Open **http://localhost:8501** and click **New Investigation**.
2. Ask questions in natural language — e.g. *"Show all serious adverse events"*,
   *"Which patients had liver toxicity?"*, *"Show only patients above age 60"*.
3. Each answer shows the **retrieval strategy**, **evidence sources**, **extracted
   entities**, latency, and token usage.
4. Upload more files (CSV / JSON / PDF) from the sidebar; duplicates are skipped automatically.

---

## 🔌 API Reference

Base URL: `http://localhost:8000` — interactive docs at `/docs`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET`  | `/health` | Service health check |
| `GET`  | `/stats` | Dataset row counts + active model |
| `POST` | `/chat` | Ask a question (RAG + memory). Body: `{question, session_id?}` |
| `POST` | `/ingest/upload` | Upload & ingest a CSV / JSON / PDF file |
| `GET`  | `/ingest/documents` | List ingested documents |
| `GET`  | `/sessions` | List investigation sessions |
| `POST` | `/sessions` | Create a session |
| `GET`  | `/sessions/{id}` | Get a session (incl. conversation history) |
| `DELETE` | `/sessions/{id}` | Archive a session |
| `GET`  | `/audit` | Audit trail (optionally `?session_id=`) |

---

## 📁 Project Structure

```
src/
├── api/                FastAPI app, routers (chat, ingest, sessions, audit, stats), schemas
├── config/             Pydantic settings (env-driven)
├── database/           SQLAlchemy models + connection
├── ingestion/          SDTM / ClinicalTrials JSON / PDF ingestors + orchestrator + dedup
├── embeddings/         sentence-transformers embedder, chunker, disk cache
├── vector_store/       ChromaDB wrapper
├── entity_extraction/  spaCy + rule-based clinical NER
├── llm/                Groq client + prompt templates
├── memory/             short-term, long-term, context manager
├── rag/                query classifier, SQL retriever (analytics + decomposition), vector retriever, pipeline
├── json_store/         FileNormalizer + unified JSON-store exporter
└── ui/                 Streamlit chat application
scripts/                init_db, ingest_all, build_json_store
alembic/                database migrations
docs/                   setup · architecture · pipelines · data processing · tech stack · json store
tests/                  pytest suite (PostgreSQL-backed, mocked LLM)
```

---

## 🧪 Testing

```bash
.\venv\Scripts\python.exe -m pytest -q        # 65 passed
```

Tests run against a dedicated `investigator_ai_test` database (auto created/dropped per
session). LLM calls are mocked, so **no live Groq key is required** to run the suite.

---

## 📚 Documentation

| Document | Contents |
|----------|----------|
| **[docs/SETUP.md](docs/SETUP.md)** | Full installation & run guide + troubleshooting |
| **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** | Component map, end-to-end flows, memory, hybrid RAG |
| **[docs/PIPELINES.md](docs/PIPELINES.md)** | The five pipelines explained |
| **[docs/DATA_PROCESSING.md](docs/DATA_PROCESSING.md)** | How each source is parsed & stored; schema |
| **[docs/TECH_STACK.md](docs/TECH_STACK.md)** | Every dependency, version, and rationale |
| **[docs/JSON_STORE.md](docs/JSON_STORE.md)** | Unified JSON representation layer + metadata schema |
| **[HOW_TO_CHECK.md](HOW_TO_CHECK.md)** | Requirement-by-requirement verification guide |

---

## 🔒 Notes on Limits

The free Groq tier rate-limits **tokens-per-minute** and **tokens-per-day**. Each question
makes two model calls (classify + synthesize), so rapid-fire follow-ups may be throttled
briefly. See [docs/PIPELINES.md](docs/PIPELINES.md#a-note-on-groq-rate-limits-why-follow-ups-can-be-slow)
for the exact limits and mitigations (model choice, query spacing, paid tier).

> ⚕️ **For research & demonstration only — not for clinical decision-making.**
> The bundled dataset is synthetic.

---

## 📄 License

See the repository's license. Built with FastAPI, Streamlit, ChromaDB, sentence-transformers,
spaCy, SQLAlchemy, and Groq.
