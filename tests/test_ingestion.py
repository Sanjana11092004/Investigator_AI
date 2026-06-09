"""Tests for the ingestion pipeline — runs against PostgreSQL test DB."""
import json
import os
import tempfile

import pytest
import pandas as pd

from src.ingestion.deduplication import compute_file_hash, is_already_ingested, register_document
from src.ingestion.clinical_trials_ingestor import ClinicalTrialsIngestor
from src.ingestion.sdtm_ingestor import SDTMIngestor
from src.ingestion.ingestion_orchestrator import IngestionOrchestrator


class TestDeduplication:

    def test_hash_consistency(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("test content 12345")
        assert compute_file_hash(str(f)) == compute_file_hash(str(f))

    def test_different_files_different_hashes(self, tmp_path):
        f1 = tmp_path / "a.txt"
        f2 = tmp_path / "b.txt"
        f1.write_text("content A")
        f2.write_text("content B")
        assert compute_file_hash(str(f1)) != compute_file_hash(str(f2))

    def test_not_ingested_initially(self, db_session):
        assert not is_already_ingested(db_session, "abc123deadbeef00000000000000abcd")

    def test_register_and_detect(self, db_session, tmp_path):
        f = tmp_path / "dummy.csv"
        f.write_text("col1,col2\n1,2\n")
        h = compute_file_hash(str(f))
        register_document(
            db_session, "dummy.csv", str(f), h,
            "sdtm", f.stat().st_size, record_count=1,
        )
        assert is_already_ingested(db_session, h)


class TestClinicalTrialsIngestor:

    def test_ingest_valid_json(self, db_session, tmp_path):
        study_data = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT99999001",
                    "briefTitle": "Test Hypertension Study",
                },
                "statusModule": {"overallStatus": "COMPLETED"},
                "descriptionModule": {"briefSummary": "A test study."},
                "conditionsModule": {"conditions": ["Hypertension"]},
                "designModule": {
                    "phases": ["PHASE3"],
                    "studyType": "INTERVENTIONAL",
                    "enrollmentInfo": {"count": 200},
                },
                "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Test Pharma", "class": "INDUSTRY"}},
                "eligibilityModule": {"minimumAge": "18 Years", "maximumAge": "80 Years", "sex": "ALL"},
                "armsInterventionsModule": {
                    "interventions": [{"name": "DrugX", "type": "DRUG", "description": "Test drug"}]
                },
            }
        }
        f = tmp_path / "study.json"
        f.write_text(json.dumps(study_data))

        ingestor = ClinicalTrialsIngestor(db_session)
        result = ingestor.ingest(str(f))

        assert result["success"] is True
        assert result["records"] == 1

    def test_skips_duplicate(self, db_session, tmp_path):
        data = {"nct_id": "NCT88888001", "title": "Dup Test"}
        f = tmp_path / "dup.json"
        f.write_text(json.dumps(data))

        ingestor = ClinicalTrialsIngestor(db_session)
        r1 = ingestor.ingest(str(f))
        r2 = ingestor.ingest(str(f))

        assert r1["success"] is True
        assert "Already ingested" in r2["message"]

    def test_handles_invalid_json(self, db_session, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("NOT VALID JSON {{{{")
        ingestor = ClinicalTrialsIngestor(db_session)
        result = ingestor.ingest(str(f))
        assert result["success"] is False


class TestSDTMIngestor:

    def test_ingest_dm(self, db_session, tmp_path):
        df = pd.DataFrame([{
            "USUBJID":   "SDTM-TEST-DM-001",
            "SUBJID":    "DM-001",
            "STUDYID":   "PHVIGIL2024",
            "DOMAIN":    "DM",
            "AGE":       "45",
            "AGEU":      "YEARS",
            "SEX":       "F",
            "RACE":      "ASIAN",
            "ETHNIC":    "NOT HISPANIC OR LATINO",
            "COUNTRY":   "IND",
            "SITEID":    "SITE-03",
            "ARM":       "Placebo",
            "ARMCD":     "PLCBO",
            "ACTARM":    "Placebo",
            "ACTARMCD":  "PLCBO",
            "DIAGNOSIS": "Type 2 Diabetes",
            "DIAGCD":    "T2DM",
            "BMI":       "26.5",
            "BMICAT":    "OVERWEIGHT",
            "SMOKESTAT": "NEVER",
            "ALCOHOLUSE":"SOCIAL",
            "EDUCATION": "BACHELOR",
            "DMDTC":     "2024-01-15",
            "DMDY":      "1",
        }])
        f = tmp_path / "DM.csv"
        df.to_csv(str(f), index=False)

        ingestor = SDTMIngestor(db_session)
        result = ingestor.ingest(str(f))

        assert result["success"] is True
        assert result["records"] == 1

    def test_ingest_ae_links_to_patient(self, db_session, tmp_path, sample_patient):
        ae_df = pd.DataFrame([{
            "USUBJID":  sample_patient.usubjid,
            "STUDYID":  "PHVIGIL2024",
            "DOMAIN":   "AE",
            "AESEQ":    "1",
            "AETERM":   "Nausea",
            "AEDECOD":  "NAUSEA",
            "AEBODSYS": "Gastrointestinal disorders",
            "AEMEDDRA": "10028813",
            "AESEV":    "MILD",
            "AEGRADE":  "1",
            "AESERFL":  "N",
            "AESDTH":   "N",
            "AESHOSP":  "N",
            "AESLIFE":  "N",
            "AEREL":    "POSSIBLY RELATED",
            "AEOUT":    "RECOVERED/RESOLVED",
            "AEDUR":    "5",
            "AEDY":     "30",
        }])
        f = tmp_path / "AE.csv"
        ae_df.to_csv(str(f), index=False)

        ingestor = SDTMIngestor(db_session)
        result = ingestor.ingest(str(f))

        assert result["success"] is True
        assert result["records"] == 1

    def test_ae_skips_unknown_patient(self, db_session, tmp_path):
        ae_df = pd.DataFrame([{
            "USUBJID":  "NOBODY-DOESNT-EXIST-9999",
            "STUDYID":  "PHVIGIL2024",
            "AETERM":   "Headache",
            "AEDECOD":  "HEADACHE",
            "AESERFL":  "N",
        }])
        f = tmp_path / "AE.csv"
        ae_df.to_csv(str(f), index=False)

        ingestor = SDTMIngestor(db_session)
        result = ingestor.ingest(str(f))
        assert result["success"] is True
        assert result["records"] == 0

    def test_ingest_lb(self, db_session, tmp_path, sample_patient):
        lb_df = pd.DataFrame([{
            "USUBJID":  sample_patient.usubjid,
            "STUDYID":  "PHVIGIL2024",
            "DOMAIN":   "LB",
            "LBSEQ":    "1",
            "VISIT":    "WEEK 4",
            "VISITNUM": "3",
            "LBDTC":    "2024-03-01",
            "LBDY":     "43",
            "LBTESTCD": "ALT",
            "LBTEST":   "Alanine Aminotransferase",
            "LBSTRESN": "45.0",
            "LBSTRESU": "U/L",
            "LBNRLO":   "7.0",
            "LBNRHI":   "56.0",
            "LBNRIND":  "NORMAL",
            "LBCLSIG":  "N",
        }])
        f = tmp_path / "LB.csv"
        lb_df.to_csv(str(f), index=False)

        ingestor = SDTMIngestor(db_session)
        result = ingestor.ingest(str(f))
        assert result["success"] is True
        assert result["records"] == 1

    def test_ingest_cm(self, db_session, tmp_path, sample_patient):
        cm_df = pd.DataFrame([{
            "USUBJID":  sample_patient.usubjid,
            "STUDYID":  "PHVIGIL2024",
            "DOMAIN":   "CM",
            "CMSEQ":    "1",
            "CMTRT":    "Lisinopril",
            "CMDECOD":  "LISINOPRIL",
            "CMCAT":    "ACE INHIBITORS",
            "CMROUTE":  "ORAL",
            "CMDOSE":   "10 mg",
            "CMDOSFRQ": "ONCE DAILY",
            "CMSTDTC":  "2023-12-01",
            "CMENDO":   "",
            "CMONGO":   "Y",
            "CMDY":     "-45",
            "CMREAS":   "Hypertension",
        }])
        f = tmp_path / "CM.csv"
        cm_df.to_csv(str(f), index=False)

        ingestor = SDTMIngestor(db_session)
        result = ingestor.ingest(str(f))
        assert result["success"] is True
        assert result["records"] == 1

    def test_ingest_mh(self, db_session, tmp_path, sample_patient):
        mh_df = pd.DataFrame([{
            "USUBJID":  sample_patient.usubjid,
            "STUDYID":  "PHVIGIL2024",
            "DOMAIN":   "MH",
            "MHSEQ":    "1",
            "MHTERM":   "Chronic Kidney Disease",
            "MHDECOD":  "CKD",
            "MHBODSYS": "Renal and urinary disorders",
            "MHMEDDRA": "10064848",
            "MHCAT":    "MEDICAL HISTORY",
            "MHSTDTC":  "2018-06-01",
            "MHENDTC":  "",
            "MHONGO":   "Y",
            "MHDY":     "-1680",
            "MHSEV":    "MODERATE",
        }])
        f = tmp_path / "MH.csv"
        mh_df.to_csv(str(f), index=False)

        ingestor = SDTMIngestor(db_session)
        result = ingestor.ingest(str(f))
        assert result["success"] is True
        assert result["records"] == 1

    def test_skips_duplicate_file(self, db_session, tmp_path):
        """Re-ingesting same file content must be skipped."""
        df = pd.DataFrame([{
            "USUBJID": "DEDUP-DM-001", "STUDYID": "PHVIGIL2024",
            "AGE": "30", "SEX": "M",
        }])
        content = df.to_csv(index=False).encode()
        f = tmp_path / "DM.csv"
        f.write_bytes(content)

        ingestor = SDTMIngestor(db_session)
        r1 = ingestor.ingest(str(f))
        r2 = ingestor.ingest(str(f))

        assert r1["success"] is True
        assert "Already ingested" in r2["message"]


class TestOrchestrator:

    def test_routes_dm_csv(self, db_session, tmp_path):
        df = pd.DataFrame([{
            "USUBJID": "ORCH-DM-001", "STUDYID": "PHVIGIL2024",
            "AGE": "30", "SEX": "M",
        }])
        f = tmp_path / "DM.csv"
        df.to_csv(str(f), index=False)

        orch = IngestionOrchestrator(db_session)
        result = orch.ingest_file(str(f))
        assert result["success"] is True

    def test_returns_error_for_unsupported_type(self, db_session, tmp_path):
        f = tmp_path / "unknown.xlsx"
        f.write_bytes(b"fake excel content")
        orch = IngestionOrchestrator(db_session)
        result = orch.ingest_file(str(f))
        assert result["success"] is False
        assert "No ingestor" in result["message"]

    def test_file_not_found(self, db_session):
        orch = IngestionOrchestrator(db_session)
        result = orch.ingest_file("/path/that/does/not/exist/AE.csv")
        assert result["success"] is False