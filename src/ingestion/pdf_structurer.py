"""PDF Structurer — turns an unstructured narrative PDF into a structured,
exactly-queryable JSON document (the "json-converter" stage for this project).

Pipeline:  PDF text  ->  large chunks  ->  per-chunk LLM extraction  ->
           merge patients BY IDENTIFIER  ->  one structured JSON per document.

Why: factual / aggregate questions ("how many patients", "which patients are on
drug X") are answered EXACTLY from this structured store instead of approximately
from a handful of retrieved narrative chunks. Patients split across pages (chunk
overlap, a narrative cut mid-page) are reunited by patient_id, so the count is
correct no matter how the text was chunked.

Output is written to  <json_store_dir>/documents/<source>.json  and is kept
SEPARATE from the SDTM patient cohort (it never touches the SQL Patient table).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz  # PyMuPDF
from loguru import logger

from src.config.settings import settings
from src.llm.groq_client import GroqClient


# Identifier keys the LLM might use, in priority order.
_PATIENT_ID_KEYS = ("patient_id", "subject_id", "subjid", "usubjid", "id")


class PDFStructurer:
    """Extracts a structured clinical JSON from a narrative PDF."""

    def __init__(self, groq: Optional[GroqClient] = None) -> None:
        self._groq = groq or GroqClient()

    # ──────────────────────────────────────────────────────────────────────
    def structure(self, file_path: str, source_name: Optional[str] = None) -> Dict[str, Any]:
        """Extract → normalize → merge. Returns the structured document dict.

        Best-effort per chunk: a chunk that fails extraction is skipped (logged),
        not fatal, so a single bad page never loses the whole document. Raises
        only if NOTHING could be extracted.
        """
        source = source_name or Path(file_path).name
        text = self._extract_text(file_path)
        chunks = self._chunk(text)
        total = len(chunks)
        logger.info(f"structurer: {source} -> {total} extraction chunk(s)")

        partials: List[Dict[str, Any]] = []
        failed = 0
        for i, chunk in enumerate(chunks):
            try:
                part = self._groq.normalize_chunk(chunk)
                if part:
                    partials.append(part)
                logger.info(f"structurer: extracted chunk {i + 1}/{total}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning(f"structurer: chunk {i + 1}/{total} failed: {exc}")

        if not partials:
            raise RuntimeError(f"No chunk produced structured data for {source}")

        merged = self._merge(partials)
        patients = merged.get("patients", [])

        # Completeness backfill: if the document has clear per-record headers
        # (e.g. "PAT-1 | <date>"), every such ID MUST appear. Add a stub for any
        # the LLM missed/dropped, so the patient_count is always correct even when
        # some extraction calls failed or under-reported.
        present = {self._patient_key(p) for p in patients if self._patient_key(p)}
        for rid in self._record_ids(text):
            if rid.upper() not in present:
                patients.append({"patient_id": rid, "summary": None})
                present.add(rid.upper())

        result = {
            "source": source,
            "patient_count": len(patients),
            "patient_ids": [self._patient_key(p) for p in patients if self._patient_key(p)],
            "study_id": merged.get("study_id"),
            "study_title": merged.get("study_title"),
            "patients": patients,
            "chunks_total": total,
            "chunks_failed": failed,
        }
        logger.info(
            f"structurer: {source} -> {result['patient_count']} patients "
            f"({failed}/{total} chunks failed)"
        )
        return result

    def structure_and_save(self, file_path: str, source_name: Optional[str] = None) -> Dict[str, Any]:
        """Run structuring and persist to <json_store>/documents/<source>.json."""
        result = self.structure(file_path, source_name)
        self.save(result)
        return result

    # ──────────────────────────────────────────────────────────────────────
    # Persistence
    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _doc_dir() -> Path:
        d = Path(settings.json_store_dir) / "documents"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def _json_path(cls, source: str) -> Path:
        # strip extension, keep a filesystem-safe stem
        stem = Path(source).stem
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", stem)
        return cls._doc_dir() / f"{safe}.json"

    @classmethod
    def save(cls, result: Dict[str, Any]) -> Path:
        path = cls._json_path(result["source"])
        path.write_text(
            json.dumps(result, indent=2, default=str, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"structurer: wrote {path}")
        return path

    @classmethod
    def load(cls, source: str) -> Optional[Dict[str, Any]]:
        """Load the structured JSON for a document source, or None if absent."""
        path = cls._json_path(source)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None

    # ──────────────────────────────────────────────────────────────────────
    # Structured-record retrieval for the RAG pipeline
    # ──────────────────────────────────────────────────────────────────────
    _QUERY_ID_RE = re.compile(r'\b(?:PAT|SUBJ|SUBJECT|PATIENT)[-_ ]?\d+\b', re.I)

    @staticmethod
    def _norm_id(s: Any) -> str:
        return re.sub(r'[^a-z0-9]', '', str(s).lower())

    @classmethod
    def patient_evidence_for_query(cls, source: str, query: str, limit: int = 6) -> List[Dict[str, Any]]:
        """Return exact, structured evidence blocks for any patient IDs named in the
        query (e.g. 'medications for PAT-7'). This makes per-patient lookups exact —
        the structured record always carries fields (meds, AEs) that the handful of
        semantically-retrieved narrative chunks may miss."""
        data = cls.load(source)
        if not data:
            return []
        q_ids = {cls._norm_id(m) for m in cls._QUERY_ID_RE.findall(query)}
        if not q_ids:
            return []
        out: List[Dict[str, Any]] = []
        for p in data.get("patients", []):
            pid = p.get("patient_id")
            if pid and cls._norm_id(pid) in q_ids:
                out.append({
                    "content": cls._format_patient(p),
                    "source": f"{source} (structured record)",
                    "type": "vector",
                })
                if len(out) >= limit:
                    break
        return out

    @staticmethod
    def _format_patient(p: Dict[str, Any]) -> str:
        lines = [f"**Structured record for patient {p.get('patient_id')}** "
                 f"(exact, from document extraction):"]
        for key in ("age", "sex", "diagnosis"):
            val = p.get(key)
            if val not in (None, "", [], {}):
                lines.append(f"- {key}: {val}")
        if p.get("medications"):
            lines.append(f"- medications: {', '.join(map(str, p['medications']))}")
        if p.get("adverse_events"):
            lines.append(f"- adverse_events: {', '.join(map(str, p['adverse_events']))}")
        if p.get("summary"):
            lines.append(f"- summary: {p['summary']}")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────
    # Extraction + chunking
    # ──────────────────────────────────────────────────────────────────────
    @staticmethod
    def _extract_text(file_path: str) -> str:
        doc = fitz.open(file_path)
        pages = [page.get_text("text") for page in doc]
        doc.close()
        return "\n".join(pages)

    # A per-record header line: a line that STARTS with a patient/subject ID,
    # e.g. "PAT-1 | 4 January 2024" or "SUBJ-0001 ...". Used to split the document
    # on record boundaries so a patient is never cut across two extraction calls.
    _RECORD_HEADER_RE = re.compile(
        r'(?im)^[ \t]*(?:PAT|SUBJ|SUBJECT|PATIENT)[-_ ]?\d+\b.*$'
    )

    @classmethod
    def _chunk(cls, text: str) -> List[str]:
        """Split into extraction chunks. Prefer per-record boundaries (whole
        patients), falling back to paragraph packing for documents without clear
        record headers. Either way, pack up to `extraction_chunk_size` so each LLM
        call sees complete records and the number of calls stays low."""
        size = settings.extraction_chunk_size
        text = (text or "").strip()
        if not text:
            return []
        records = cls._split_records(text)
        parts = records if records else re.split(r"\n\s*\n", text)
        return cls._pack(parts, size)

    @classmethod
    def _split_records(cls, text: str) -> List[str]:
        """Slice text into [preamble, record1, record2, ...] on record headers.
        Returns [] when there aren't enough headers to be a record-style doc."""
        starts = [m.start() for m in cls._RECORD_HEADER_RE.finditer(text)]
        if len(starts) < 3:
            return []
        sections: List[str] = []
        if starts[0] > 0:
            sections.append(text[: starts[0]])          # preamble / cover (study meta)
        for i, s in enumerate(starts):
            e = starts[i + 1] if i + 1 < len(starts) else len(text)
            sections.append(text[s:e])
        return [s.strip() for s in sections if s.strip()]

    @staticmethod
    def _pack(parts: List[str], size: int) -> List[str]:
        """Greedily concatenate whole parts up to `size` chars (no part is split)."""
        chunks: List[str] = []
        cur = ""
        for p in parts:
            if len(cur) + len(p) > size and cur:
                chunks.append(cur.strip())
                cur = p
            else:
                cur += ("\n\n" + p) if cur else p
        if cur.strip():
            chunks.append(cur.strip())
        return chunks

    @classmethod
    def _record_ids(cls, text: str) -> List[str]:
        """Distinct record IDs from header lines (preserves first-seen order)."""
        seen, out = set(), []
        for m in cls._RECORD_HEADER_RE.finditer(text):
            tok = re.match(r'[ \t]*((?:PAT|SUBJ|SUBJECT|PATIENT)[-_ ]?\d+)',
                           m.group(0), re.I)
            if tok:
                rid = tok.group(1).strip()
                if rid.upper() not in seen:
                    seen.add(rid.upper())
                    out.append(rid)
        return out

    # ──────────────────────────────────────────────────────────────────────
    # Merge (patients by identifier; document-level lists unioned)
    # ──────────────────────────────────────────────────────────────────────
    @classmethod
    def _merge(cls, partials: List[Dict[str, Any]]) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        patients_by_id: Dict[str, Dict[str, Any]] = {}
        anonymous: List[Dict[str, Any]] = []

        for part in partials:
            if not isinstance(part, dict):
                continue
            for key, value in part.items():
                if value in (None, "", [], {}):
                    continue
                if key == "patients" and isinstance(value, list):
                    for patient in value:
                        if not isinstance(patient, dict):
                            continue
                        pid = cls._patient_key(patient)
                        if pid is None:
                            anonymous.append(patient)
                        elif pid in patients_by_id:
                            cls._merge_into(patients_by_id[pid], patient)
                        else:
                            patients_by_id[pid] = dict(patient)
                    continue
                existing = merged.get(key)
                if existing is None:
                    merged[key] = value
                elif isinstance(existing, list) and isinstance(value, list):
                    for item in value:
                        if item not in existing:
                            existing.append(item)
                # scalar conflict -> earliest chunk wins

        patients = list(patients_by_id.values()) + anonymous
        if patients:
            merged["patients"] = patients
        return merged

    @classmethod
    def _patient_key(cls, patient: Dict[str, Any]) -> Optional[str]:
        lowered = {str(k).strip().lower(): v for k, v in patient.items()}
        for key in _PATIENT_ID_KEYS:
            value = lowered.get(key)
            if value not in (None, "", [], {}):
                return str(value).strip().upper()
        return None

    @staticmethod
    def _merge_into(target: Dict[str, Any], extra: Dict[str, Any]) -> None:
        for key, value in extra.items():
            if value in (None, "", [], {}):
                continue
            existing = target.get(key)
            if existing is None:
                target[key] = value
            elif isinstance(existing, list) and isinstance(value, list):
                for item in value:
                    if item not in existing:
                        existing.append(item)
            elif isinstance(existing, dict) and isinstance(value, dict):
                for k2, v2 in value.items():
                    existing.setdefault(k2, v2)
            # scalar conflict -> first chunk wins
