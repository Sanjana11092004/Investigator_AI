# 🗂️ Unified JSON Store (normalized representation layer)

This layer implements the **unified JSON-based internal representation** and
**metadata-first** design: every ingested source — SDTM CSVs, ClinicalTrials
JSON, and narrative PDF chunks — is normalized into one standardized JSON record
schema under `json_store/`.

> **Design note:** this is the *representation* layer, not the query engine.
> Queries still run on the **hybrid SQL + vector engine** (PostgreSQL for exact
> tabular analytics, ChromaDB for semantic document search), because an
> LLM-over-JSON engine cannot reliably aggregate thousands of rows. The
> `json_store/` mirrors that data in a consistent, inspectable, metadata-rich form.

## Pipeline (matches the target workflow)

```
Upload / ingestion folder
        ↓
FileNormalizer            csv/xls/xlsx → tabular ; json → structured_json ; pdf/doc/docx → document
        ↓
Ingestion                 tabular → PostgreSQL ; document → chunks → ChromaDB
        ↓
JSONStoreExporter         → json_store/*.json  (unified records + rich metadata)
        ↓
Query engine (hybrid)     intent classify → SQL analytics / vector search / decomposition
        ↓
Groq                      → grounded natural-language answer
```

## Build it

```bash
python -m scripts.build_json_store
```

Produces (gitignored, regenerate any time):

```
json_store/
├── index.json            # metadata-only catalog of ALL documents (no content)
├── demographics.json     # 250 patient records
├── adverse_events.json   # 566
├── labs.json             # 16,979
├── medications.json      # 722
├── medical_history.json  # 585
├── studies.json          # 416 ClinicalTrials studies
└── narratives.json       # 731 PDF chunks (read back from ChromaDB)
```
(≈ 20,249 documents total.)

## Record schema

Every record in every file follows one schema:

```json
{
  "document_id": "patient::SUBJ-0001",
  "source_file": "DM.csv",
  "study_id": "PHVIGIL2024",
  "patient_id": "SUBJ-0001",
  "section_name": "demographics",
  "page_number": null,
  "entity_tags": ["COPD", "Placebo", "M", "WHITE", "OVERWEIGHT"],
  "timestamps": { "ingested_at": "2026-…Z", "record_date": "2020-09-14" },
  "relationships": [ { "type": "enrolled_in", "target": "study::PHVIGIL2024" } ],
  "content": { "...": "the original normalized fields" }
}
```

| Field | Meaning |
|-------|---------|
| `document_id` | stable unique id (`<type>::<key>`) |
| `source_file` | originating file |
| `study_id` / `patient_id` | foreign keys for metadata filtering |
| `section_name` | demographics / adverse_events / labs / medications / medical_history / studies / narrative |
| `page_number` | for PDF chunks |
| `entity_tags` | salient entities (diagnosis, AE term, lab code, drug, conditions…) |
| `timestamps` | ingestion time + the record's own date |
| `relationships` | typed links (`enrolled_in`, `experienced_by`, `measured_for`, `scoped_to_session`, …) |
| `content` | the full normalized fields |

## Metadata-first retrieval
`index.json` is a content-free catalog you can scan/filter by `source_file`,
`session_id`, `patient_id`, `study_id`, `section_name`, `page_number`, or
`entity_tags` **before** touching the heavy content — the metadata-first pattern.
The live engine applies the same filters (e.g. per-session document scoping on
the vector store, `study_id`/`patient_id` filters on SQL).
