"""
Unified JSON-store exporter.

Produces a standardized internal JSON representation of every ingested object
(structured SDTM rows, ClinicalTrials studies, and narrative PDF chunks) under
`json_store/`, each record carrying rich, query-able metadata:

    document_id, source_file, study_id, patient_id, section_name,
    page_number, entity_tags, timestamps, relationships, content

This is the "unified JSON representation" / "metadata-first" layer. The SQL +
vector engine remains the query engine; this store is the consistent,
inspectable representation of all sources (and the basis for metadata filtering).
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session
from loguru import logger

from src.database.models.patient import Patient
from src.database.models.adverse_event import AdverseEvent
from src.database.models.lab_result import LabResult
from src.database.models.medication import ConcomitantMedication
from src.database.models.medical_history import MedicalHistory
from src.database.models.study import ClinicalStudy
from src.vector_store.chroma_store import get_vector_store


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cols(obj, exclude) -> Dict[str, Any]:
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in exclude}


class JSONStoreExporter:
    """Export the whole knowledge base into json_store/ as normalized records."""

    def __init__(self, db: Session, out_dir: str = "json_store"):
        self.db = db
        self.out = Path(out_dir)
        self.ingested_at = _now()

    # ── record builder (enforces the unified schema) ──────────────────────
    def _record(self, document_id, source_file, section_name, content,
                study_id=None, patient_id=None, page_number=None,
                entity_tags=None, record_date=None, relationships=None) -> Dict[str, Any]:
        return {
            "document_id": document_id,
            "source_file": source_file,
            "study_id": study_id,
            "patient_id": patient_id,
            "section_name": section_name,
            "page_number": page_number,
            "entity_tags": [t for t in (entity_tags or []) if t],
            "timestamps": {"ingested_at": self.ingested_at, "record_date": record_date},
            "relationships": relationships or [],
            "content": content,
        }

    # ── public API ────────────────────────────────────────────────────────
    def export(self) -> Dict[str, Any]:
        self.out.mkdir(parents=True, exist_ok=True)
        all_records: List[Dict[str, Any]] = []
        counts = {}
        for section, builder in [
            ("demographics", self._patients),
            ("adverse_events", self._adverse_events),
            ("labs", self._labs),
            ("medications", self._medications),
            ("medical_history", self._medical_history),
            ("studies", self._studies),
            ("narratives", self._narratives),
        ]:
            records = builder()
            self._write(section, records)
            counts[section] = len(records)
            all_records.extend(records)
            logger.info(f"json_store: {section}.json — {len(records)} records")

        # metadata-first catalog (everything except the heavy content)
        catalog = [{k: v for k, v in r.items() if k != "content"} for r in all_records]
        self._write("index", catalog)

        return {
            "out_dir": str(self.out.resolve()),
            "total_documents": len(all_records),
            "by_section": counts,
        }

    def _write(self, name: str, records) -> None:
        (self.out / f"{name}.json").write_text(
            json.dumps(records, indent=2, default=str, ensure_ascii=False), encoding="utf-8")

    # ── per-section builders ──────────────────────────────────────────────
    def _patients(self):
        out = []
        for p in self.db.query(Patient).all():
            out.append(self._record(
                document_id=f"patient::{p.usubjid}", source_file="DM.csv",
                section_name="demographics", study_id=p.studyid, patient_id=p.usubjid,
                entity_tags=[p.diagnosis, p.diagcd, p.arm, p.sex, p.race, p.bmicat],
                record_date=p.rfstdtc,
                relationships=[{"type": "enrolled_in", "target": f"study::{p.studyid}"}],
                content=_cols(p, {"id", "study_id", "created_at"}),
            ))
        return out

    def _adverse_events(self):
        out = []
        for ae in self.db.query(AdverseEvent).all():
            out.append(self._record(
                document_id=f"ae::{ae.usubjid}::{ae.aeseq}", source_file="AE.csv",
                section_name="adverse_events", study_id=ae.studyid, patient_id=ae.usubjid,
                entity_tags=[ae.aeterm, ae.aedecod, ae.aebodsys, ae.aesev,
                             ("SERIOUS" if ae.aeserfl == "Y" else None)],
                record_date=ae.aestdtc,
                relationships=[{"type": "experienced_by", "target": f"patient::{ae.usubjid}"}],
                content=_cols(ae, {"id", "patient_id", "study_id", "created_at"}),
            ))
        return out

    def _labs(self):
        out = []
        for lb in self.db.query(LabResult).all():
            out.append(self._record(
                document_id=f"lab::{lb.usubjid}::{lb.lbseq}", source_file="LB.csv",
                section_name="labs", study_id=lb.studyid, patient_id=lb.usubjid,
                entity_tags=[lb.lbtestcd, lb.lbtest, lb.lbnrind],
                record_date=lb.lbdtc,
                relationships=[{"type": "measured_for", "target": f"patient::{lb.usubjid}"}],
                content=_cols(lb, {"id", "patient_id", "study_id", "created_at"}),
            ))
        return out

    def _medications(self):
        out = []
        for m in self.db.query(ConcomitantMedication).all():
            out.append(self._record(
                document_id=f"cm::{m.usubjid}::{m.cmseq}", source_file="CM.csv",
                section_name="medications", study_id=m.studyid, patient_id=m.usubjid,
                entity_tags=[m.cmtrt, m.cmdecod, m.cmcat],
                record_date=m.cmstdtc,
                relationships=[{"type": "administered_to", "target": f"patient::{m.usubjid}"}],
                content=_cols(m, {"id", "patient_id", "study_id", "created_at"}),
            ))
        return out

    def _medical_history(self):
        out = []
        for mh in self.db.query(MedicalHistory).all():
            out.append(self._record(
                document_id=f"mh::{mh.usubjid}::{mh.mhseq}", source_file="MH.csv",
                section_name="medical_history", study_id=mh.studyid, patient_id=mh.usubjid,
                entity_tags=[mh.mhterm, mh.mhdecod, mh.mhbodsys],
                record_date=mh.mhstdtc,
                relationships=[{"type": "history_of", "target": f"patient::{mh.usubjid}"}],
                content=_cols(mh, {"id", "patient_id", "study_id", "created_at"}),
            ))
        return out

    def _studies(self):
        out = []
        for s in self.db.query(ClinicalStudy).all():
            conditions = [c.strip() for c in (s.conditions or "").split(",") if c.strip()]
            out.append(self._record(
                document_id=f"study::{s.nct_id}", source_file="clinicaltrials_hepatotoxicity.json",
                section_name="studies", study_id=s.nct_id,
                entity_tags=conditions[:6] + [s.phase, s.lead_sponsor],
                record_date=s.start_date,
                content=_cols(s, {"id", "created_at", "raw_json"}),
            ))
        return out

    def _narratives(self):
        """Read the PDF narrative chunks back out of the vector store."""
        out = []
        try:
            col = get_vector_store().collection
            data = col.get(include=["documents", "metadatas"])
        except Exception as e:
            logger.warning(f"json_store: could not read vector store: {e}")
            return out
        for cid, text, meta in zip(data.get("ids", []),
                                   data.get("documents", []),
                                   data.get("metadatas", [])):
            meta = meta or {}
            out.append(self._record(
                document_id=f"narrative::{cid}",
                source_file=meta.get("source", "unknown.pdf"),
                section_name="narrative",
                page_number=meta.get("page"),
                entity_tags=[meta.get("doc_type")],
                relationships=[{"type": "scoped_to_session",
                                "target": meta.get("session_id", "global")}],
                content={"text": text, "chunk_index": meta.get("chunk_index"),
                         "file_hash": meta.get("file_hash")},
            ))
        return out
