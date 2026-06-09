# 📊 Data Processing

How each kind of source document is parsed, transformed, and stored.

---

## The dataset

| Source | File(s) | Goes to | Rows/chunks |
|---|---|---|---|
| **SDTM Demographics** | `sdtm/DM.csv` | `patients` | 250 |
| **SDTM Adverse Events** | `sdtm/AE.csv` | `adverse_events` | 566 |
| **SDTM Lab Results** | `sdtm/LB.csv` | `lab_results` | 16,979 |
| **SDTM Concomitant Meds** | `sdtm/CM.csv` | `concomitant_medications` | 722 |
| **SDTM Medical History** | `sdtm/MH.csv` | `medical_histories` | 585 |
| **ClinicalTrials.gov** | `clinical_trials/clinicaltrials_hepatotoxicity.json` | `clinical_studies` | 416 |
| **Patient narrative** | `narratives/patient_narrative_001.pdf` | ChromaDB (vectors) | 731 chunks |

> Study id in the SDTM data is **`PHVIGIL2024`**; patients are **`SUBJ-0001 … SUBJ-0250`**.
> (`ABC-101` in the problem statement is only a placeholder — it isn't in this dataset.)

---

## 1. SDTM CSVs → PostgreSQL
**Code:** `src/ingestion/sdtm_ingestor.py`

1. The domain is detected from the filename (`DM`, `AE`, `LB`, `CM`, `MH`).
2. `pandas.read_csv(dtype=str, keep_default_na=False)` reads everything as strings;
   columns are upper-cased and blank strings are converted to `NA`.
3. Per-row, values are coerced with `_safe_str / _safe_float / _safe_int` (None-safe).
4. **DM** rows create `Patient` records keyed by `usubjid` (duplicates skipped).
5. **AE/LB/CM/MH** rows look up the parent patient by `usubjid`; rows with no known
   patient are skipped (referential integrity). Each becomes its domain model row.
6. The whole file commits in one transaction; the file is registered in
   `ingested_documents`.

SDTM is the CDISC standard for clinical-trial tabular data — column names like
`AETERM` (verbatim term), `AEDECOD` (coded term), `AESERFL` (serious flag),
`AEGRADE`, `LBTESTCD`/`LBSTRESN` (lab code/value), etc. are preserved on the models.

---

## 2. ClinicalTrials.gov JSON → PostgreSQL
**Code:** `src/ingestion/clinical_trials_ingestor.py`

1. The file may be a single study, a list, or the API-v2 wrapper `{ "studies": [...] }`.
2. `_parse_study` reads the **`protocolSection`** modules (identification, status,
   description, conditions, design, sponsor, eligibility, arms/interventions) with a
   `_safe_get` nested-dict helper, and also tolerates older flat keys.
3. Each study → a `ClinicalStudy` row: `nct_id` (unique), title, status, phase,
   conditions, sponsor, enrollment, dates (kept as strings — formats vary), and the
   full original JSON in `raw_json`.
4. Existing `nct_id`s are updated (upsert); new ones inserted; the batch commits once.

---

## 3. Narrative PDF → ChromaDB (vectors)
**Code:** `src/ingestion/pdf_ingestor.py` + `src/embeddings/` + `src/vector_store/`

```
PyMuPDF (fitz) extracts text per page
   → chunk_text(): sentence-aware sliding window (CHUNK_SIZE chars, CHUNK_OVERLAP),
     chunks < 50 chars dropped
   → Embedder.embed_documents(): all-MiniLM-L6-v2, normalized, disk-cached
   → VectorStore.add(): ChromaDB persistent collection (cosine), id = hash_page_chunk
```
Each chunk stores metadata `{source, file_hash, page, chunk_index, doc_type}` so
vector answers can cite the document and page.

---

## 4. Deduplication
**Code:** `src/ingestion/deduplication.py`

Every file's **MD5 hash** is recorded in `ingested_documents`. Before ingesting,
`is_already_ingested` checks for a completed row with that hash; if found, the file is
skipped. This is content-based, so renamed copies are still detected as duplicates.

---

## 5. Database schema (10 tables)

```
clinical_studies ─1──┐ (optional study_id FK)
                     │
patients ─1───────*──┤  adverse_events
         ─1───────*──┤  lab_results
         ─1───────*──┤  concomitant_medications
         ─1───────*──┘  medical_histories

ingested_documents      (file registry / dedup)
investigation_sessions  (long-term memory: history + active context)
audit_trail             (every query logged)
```
All ids are UUIDs; JSON columns (`conversation_history`, `investigation_context`,
`retrieved_sources`, `tokens_used`, study `interventions`/`outcomes`, …) use
PostgreSQL `JSON`. Migration: `alembic/versions/001_initial_schema.py`.

---

## 6. Exporting / sharing the data
A restore-ready dump is produced with:
```powershell
pg_dump -U postgres -d investigator_ai --no-owner --no-privileges --clean --if-exists -f investigator_ai_dump.sql
```
Restore: `createdb investigator_ai` then `psql -d investigator_ai -f investigator_ai_dump.sql`.
(The dump is large because each study keeps its full `raw_json`; it is **not**
committed to git.)
