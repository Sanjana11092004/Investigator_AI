"""
SDTM Data Ingestor — matched to actual sheet column names.
DM: 26 cols | LB: 16 cols | AE: 20 cols | CM: 15 cols | MH: 14 cols
"""
import os
from pathlib import Path
from typing import Dict, Any

import pandas as pd
from sqlalchemy.orm import Session
from loguru import logger

from src.database.models.patient import Patient
from src.database.models.adverse_event import AdverseEvent
from src.database.models.lab_result import LabResult
from src.database.models.medication import ConcomitantMedication
from src.database.models.medical_history import MedicalHistory
from src.ingestion.base_ingestor import BaseIngestor
from src.ingestion.deduplication import (
    compute_file_hash,
    is_already_ingested,
    register_document,
)


def _safe_str(val) -> str:
    if pd.isna(val):
        return ""
    return str(val).strip()


def _safe_float(val):
    if pd.isna(val):
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(val):
    if pd.isna(val):
        return None
    try:
        return int(float(val))
    except (ValueError, TypeError):
        return None


class SDTMIngestor(BaseIngestor):
    """
    Ingests SDTM CSV files — one domain per file.
    File names must be: DM.csv, LB.csv, AE.csv, CM.csv, MH.csv
    """

    DOMAIN_MAP = {
        "DM": "_ingest_dm",
        "LB": "_ingest_lb",
        "AE": "_ingest_ae",
        "CM": "_ingest_cm",
        "MH": "_ingest_mh",
    }

    def can_handle(self, file_path: str) -> bool:
        name = Path(file_path).stem.upper()
        return file_path.endswith(".csv") and name in self.DOMAIN_MAP

    def ingest(self, file_path: str, **kwargs) -> Dict[str, Any]:
        domain = Path(
            kwargs.get(
                "original_filename",
                file_path
            )
        ).stem.upper()
        file_hash = compute_file_hash(file_path)

        if is_already_ingested(self.db, file_hash):
            return {"success": True, "records": 0, "message": "Already ingested. Skipped."}

        try:
            df = pd.read_csv(file_path, dtype=str, keep_default_na=False)
            df.columns = [c.strip().upper() for c in df.columns]
            df = df.replace("", pd.NA)
        except Exception as e:
            logger.error(f"Failed to read CSV {file_path}: {e}")
            register_document(
                self.db, Path(file_path).name, file_path, file_hash,
                "sdtm", os.path.getsize(file_path), status="failed", error_message=str(e)
            )
            return {"success": False, "records": 0, "message": str(e)}

        method = getattr(self, self.DOMAIN_MAP[domain])

        try:
            count = method(df)
            self.db.commit()
        except Exception as e:
            self.db.rollback()
            logger.error(f"SDTM {domain} ingest failed: {e}")
            register_document(
                self.db, Path(file_path).name, file_path, file_hash,
                "sdtm", os.path.getsize(file_path), status="failed", error_message=str(e)
            )
            return {"success": False, "records": 0, "message": str(e)}

        register_document(
            self.db,
            Path(file_path).name,
            file_path,
            file_hash,
            "sdtm",
            os.path.getsize(file_path),
            record_count=count,
        )

        logger.info(f"SDTM {domain}: {count} records ingested from {Path(file_path).name}")
        return {"success": True, "records": count, "message": f"Ingested {count} {domain} records"}

    # ──────────────────────────────────────────────────────────────────────
    # DM — Demographics (500 rows, 26 columns)
    # ──────────────────────────────────────────────────────────────────────
    def _ingest_dm(self, df: pd.DataFrame) -> int:
        count = 0
        for _, row in df.iterrows():
            usubjid = _safe_str(row.get("USUBJID", ""))
            if not usubjid:
                continue

            if self.db.query(Patient).filter(Patient.usubjid == usubjid).first():
                continue  # skip duplicates

            patient = Patient(
                usubjid     = usubjid,
                subjid      = _safe_str(row.get("SUBJID")),
                studyid     = _safe_str(row.get("STUDYID")),
                domain      = _safe_str(row.get("DOMAIN", "DM")),
                rfstdtc     = _safe_str(row.get("RFSTDTC")),
                rfendtc     = _safe_str(row.get("RFENDTC")),
                dmdtc       = _safe_str(row.get("DMDTC")),
                dmdy        = _safe_int(row.get("DMDY")),
                siteid      = _safe_str(row.get("SITEID")),
                country     = _safe_str(row.get("COUNTRY")),
                age         = _safe_float(row.get("AGE")),
                ageu        = _safe_str(row.get("AGEU")),
                sex         = _safe_str(row.get("SEX")),
                race        = _safe_str(row.get("RACE")),
                ethnic      = _safe_str(row.get("ETHNIC")),
                armcd       = _safe_str(row.get("ARMCD")),
                arm         = _safe_str(row.get("ARM")),
                actarmcd    = _safe_str(row.get("ACTARMCD")),
                actarm      = _safe_str(row.get("ACTARM")),
                diagnosis   = _safe_str(row.get("DIAGNOSIS")),
                diagcd      = _safe_str(row.get("DIAGCD")),
                bmi         = _safe_float(row.get("BMI")),
                bmicat      = _safe_str(row.get("BMICAT")),
                smokestat   = _safe_str(row.get("SMOKESTAT")),
                alcoholuse  = _safe_str(row.get("ALCOHOLUSE")),
                education   = _safe_str(row.get("EDUCATION")),
                dthfl       = _safe_str(row.get("DTHFL")),
                dthdtc      = _safe_str(row.get("DTHDTC")),
            )
            self.db.add(patient)
            count += 1
        return count

    # ──────────────────────────────────────────────────────────────────────
    # Shared helper: look up patient UUID
    # ──────────────────────────────────────────────────────────────────────
    def _get_patient_id(self, usubjid: str):
        p = self.db.query(Patient).filter(Patient.usubjid == usubjid).first()
        return p.id if p else None

    # ──────────────────────────────────────────────────────────────────────
    # AE — Adverse Events (~1,100 rows, 20 columns)
    # ──────────────────────────────────────────────────────────────────────
    def _ingest_ae(self, df: pd.DataFrame) -> int:
        count = 0
        for _, row in df.iterrows():
            usubjid    = _safe_str(row.get("USUBJID", ""))
            patient_id = self._get_patient_id(usubjid)
            if not patient_id:
                logger.warning(f"No patient for USUBJID={usubjid}, skipping AE row")
                continue

            ae = AdverseEvent(
                patient_id = patient_id,
                usubjid    = usubjid,
                studyid    = _safe_str(row.get("STUDYID")),
                domain     = _safe_str(row.get("DOMAIN", "AE")),
                aeseq      = _safe_int(row.get("AESEQ")),
                aeterm     = _safe_str(row.get("AETERM")),
                aedecod    = _safe_str(row.get("AEDECOD")),
                aebodsys   = _safe_str(row.get("AEBODSYS")),
                aemeddra   = _safe_str(row.get("AEMEDDRA")),
                aestdtc    = _safe_str(row.get("AESTDTC")),
                aeendtc    = _safe_str(row.get("AEENDTC")),
                aedur      = _safe_int(row.get("AEDUR")),
                aedy       = _safe_int(row.get("AEDY")),
                aesev      = _safe_str(row.get("AESEV")),
                aegrade    = _safe_int(row.get("AEGRADE")),
                aeout      = _safe_str(row.get("AEOUT")),
                aerel      = _safe_str(row.get("AEREL")),
                aeserfl    = _safe_str(row.get("AESERFL")),
                aesdth     = _safe_str(row.get("AESDTH")),
                aeshosp    = _safe_str(row.get("AESHOSP")),
                aeslife    = _safe_str(row.get("AESLIFE")),
            )
            self.db.add(ae)
            count += 1
        return count

    # ──────────────────────────────────────────────────────────────────────
    # LB — Lab Results (~34,000 rows, 16 columns)
    # ──────────────────────────────────────────────────────────────────────
    def _ingest_lb(self, df: pd.DataFrame) -> int:
        count = 0
        for _, row in df.iterrows():
            usubjid    = _safe_str(row.get("USUBJID", ""))
            patient_id = self._get_patient_id(usubjid)
            if not patient_id:
                continue

            lb = LabResult(
                patient_id = patient_id,
                usubjid    = usubjid,
                studyid    = _safe_str(row.get("STUDYID")),
                domain     = _safe_str(row.get("DOMAIN", "LB")),
                lbseq      = _safe_int(row.get("LBSEQ")),
                visit      = _safe_str(row.get("VISIT")),
                visitnum   = _safe_float(row.get("VISITNUM")),
                lbdtc      = _safe_str(row.get("LBDTC")),
                lbdy       = _safe_int(row.get("LBDY")),
                lbtestcd   = _safe_str(row.get("LBTESTCD")),
                lbtest     = _safe_str(row.get("LBTEST")),
                lbstresn   = _safe_float(row.get("LBSTRESN")),
                lbstresu   = _safe_str(row.get("LBSTRESU")),
                lbnrlo     = _safe_float(row.get("LBNRLO")),
                lbnrhi     = _safe_float(row.get("LBNRHI")),
                lbnrind    = _safe_str(row.get("LBNRIND")),
                lbclsig    = _safe_str(row.get("LBCLSIG")),
            )
            self.db.add(lb)
            count += 1
        return count

    # ──────────────────────────────────────────────────────────────────────
    # CM — Concomitant Medications (~1,400 rows, 15 columns)
    # ──────────────────────────────────────────────────────────────────────
    def _ingest_cm(self, df: pd.DataFrame) -> int:
        count = 0
        for _, row in df.iterrows():
            usubjid    = _safe_str(row.get("USUBJID", ""))
            patient_id = self._get_patient_id(usubjid)
            if not patient_id:
                continue

            cm = ConcomitantMedication(
                patient_id = patient_id,
                usubjid    = usubjid,
                studyid    = _safe_str(row.get("STUDYID")),
                domain     = _safe_str(row.get("DOMAIN", "CM")),
                cmseq      = _safe_int(row.get("CMSEQ")),
                cmtrt      = _safe_str(row.get("CMTRT")),
                cmdecod    = _safe_str(row.get("CMDECOD")),
                cmcat      = _safe_str(row.get("CMCAT")),
                cmroute    = _safe_str(row.get("CMROUTE")),
                cmdose     = _safe_str(row.get("CMDOSE")),
                cmdosfrq   = _safe_str(row.get("CMDOSFRQ")),
                cmstdtc    = _safe_str(row.get("CMSTDTC")),
                cmendtc    = _safe_str(row.get("CMENDTC")),
                cmongo     = _safe_str(row.get("CMONGO")),
                cmdy       = _safe_int(row.get("CMDY")),
                cmreas     = _safe_str(row.get("CMREAS")),
            )
            self.db.add(cm)
            count += 1
        return count

    # ──────────────────────────────────────────────────────────────────────
    # MH — Medical History (~1,100 rows, 14 columns)
    # ──────────────────────────────────────────────────────────────────────
    def _ingest_mh(self, df: pd.DataFrame) -> int:
        count = 0
        for _, row in df.iterrows():
            usubjid    = _safe_str(row.get("USUBJID", ""))
            patient_id = self._get_patient_id(usubjid)
            if not patient_id:
                continue

            mh = MedicalHistory(
                patient_id = patient_id,
                usubjid    = usubjid,
                studyid    = _safe_str(row.get("STUDYID")),
                domain     = _safe_str(row.get("DOMAIN", "MH")),
                mhseq      = _safe_int(row.get("MHSEQ")),
                mhterm     = _safe_str(row.get("MHTERM")),
                mhdecod    = _safe_str(row.get("MHDECOD")),
                mhbodsys   = _safe_str(row.get("MHBODSYS")),
                mhmeddra   = _safe_str(row.get("MHMEDDRA")),
                mhcat      = _safe_str(row.get("MHCAT")),
                mhstdtc    = _safe_str(row.get("MHSTDTC")),
                mhendtc    = _safe_str(row.get("MHENDTC")),
                mhongo     = _safe_str(row.get("MHONGO")),
                mhdy       = _safe_int(row.get("MHDY")),
                mhsev      = _safe_str(row.get("MHSEV")),
            )
            self.db.add(mh)
            count += 1
        return count