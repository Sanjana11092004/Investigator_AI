"""
Pytest configuration — uses a real PostgreSQL test database.

Key fixes vs previous version:
  - SessionFactory uses autoflush=True so inserts are visible to subsequent
    queries within the same connection/transaction (fixes age_filter test)
  - All fixtures use db_session.flush() instead of db_session.commit()
    because commit() inside a savepoint transaction doesn't guarantee
    that a subsequent SELECT on the same session will see the new row
"""
import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
load_dotenv(dotenv_path=env_path)

print("TEST_DATABASE_URL =", os.getenv("TEST_DATABASE_URL"))

import pytest

_prod_url = os.environ.get("DATABASE_URL", "")
_test_url  = os.environ.get(
    "TEST_DATABASE_URL",
    _prod_url.rsplit("/", 1)[0] + "/investigator_ai_test" if "/" in _prod_url else ""
)

if not _test_url:
    raise RuntimeError(
        "Set TEST_DATABASE_URL in your .env\n"
        "TEST_DATABASE_URL=postgresql://postgres:pass@localhost:5432/investigator_ai_test"
    )

os.environ["DATABASE_URL"] = _test_url
os.environ.setdefault("GROQ_API_KEY",       "test_key_not_real")
os.environ.setdefault("GROQ_MODEL",          "llama-3.1-70b-versatile")
os.environ.setdefault("CHROMA_PERSIST_DIR",  "./chroma_db_test")
os.environ.setdefault("EMBEDDING_CACHE_DIR", "./embedding_cache_test")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

from src.database.models.base import Base
from src.database.models import (
    IngestedDocument, ClinicalStudy, Patient, AdverseEvent,
    LabResult, ConcomitantMedication, MedicalHistory,
    InvestigationSession, AuditEntry,
)
from src.api.main import app
from src.database.connection import get_db


# ── Session-scoped engine ─────────────────────────────────────────────────

@pytest.fixture(scope="session")
def pg_engine():
    engine = create_engine(_test_url, echo=False)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


# ── Function-scoped session — autoflush=True is the key fix ──────────────

@pytest.fixture(scope="function")
def db_session(pg_engine):
    """
    Each test gets its own connection+transaction, rolled back at the end.
    autoflush=True ensures that after session.add() + session.flush(),
    a subsequent SELECT on the SAME session sees the new row immediately.
    """
    connection  = pg_engine.connect()
    transaction = connection.begin()

    SessionFactory = sessionmaker(
        bind=connection,
        autoflush=True,    # ← THE FIX: flush pending inserts before SELECT
        autocommit=False,
    )
    session = SessionFactory()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ── FastAPI test client ───────────────────────────────────────────────────

@pytest.fixture(scope="function")
def client(db_session):
    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
    app.dependency_overrides.clear()


# ── Data fixtures — use flush() not commit() ─────────────────────────────
# flush() sends the INSERT to the connection immediately so the same
# session can SELECT it back. commit() inside a rolled-back outer
# transaction creates a savepoint release but doesn't guarantee
# the session's identity map is updated for subsequent queries.

@pytest.fixture
def sample_patient(db_session):
    from src.database.models.patient import Patient
    patient = Patient(
        usubjid    = "PHVIGIL2024-TEST-001",
        subjid     = "TEST-001",
        studyid    = "PHVIGIL2024",
        domain     = "DM",
        rfstdtc    = "2024-01-15",
        rfendtc    = "2024-07-15",
        dmdtc      = "2024-01-15",
        dmdy       = 1,
        siteid     = "SITE-01",
        country    = "USA",
        age        = 65.0,
        ageu       = "YEARS",
        sex        = "M",
        race       = "WHITE",
        ethnic     = "NOT HISPANIC OR LATINO",
        armcd      = "TRTA",
        arm        = "Treatment A",
        actarmcd   = "TRTA",
        actarm     = "Treatment A",
        diagnosis  = "Hypertension",
        diagcd     = "HTN",
        bmi        = 27.5,
        bmicat     = "OVERWEIGHT",
        smokestat  = "NEVER",
        alcoholuse = "SOCIAL",
        education  = "BACHELOR",
    )
    db_session.add(patient)
    db_session.flush()          # ← flush not commit
    db_session.refresh(patient)
    return patient


@pytest.fixture
def sample_adverse_event(db_session, sample_patient):
    from src.database.models.adverse_event import AdverseEvent
    ae = AdverseEvent(
        patient_id = sample_patient.id,
        usubjid    = sample_patient.usubjid,
        studyid    = "PHVIGIL2024",
        domain     = "AE",
        aeseq      = 1,
        aeterm     = "Hepatotoxicity",
        aedecod    = "HEPATOTOX",
        aebodsys   = "Hepatobiliary disorders",
        aemeddra   = "10019851",
        aesev      = "SEVERE",
        aegrade    = 3,
        aeserfl    = "Y",
        aesdth     = "N",
        aeshosp    = "Y",
        aeslife    = "N",
        aerel      = "PROBABLY RELATED",
        aeout      = "RECOVERING/RESOLVING",
        aedur      = 14,
        aedy       = 45,
        aestdtc    = "2024-03-01",
        aeendtc    = "2024-03-15",
    )
    db_session.add(ae)
    db_session.flush()          # ← flush not commit
    db_session.refresh(ae)
    return ae


@pytest.fixture
def sample_lab_result(db_session, sample_patient):
    from src.database.models.lab_result import LabResult
    lb = LabResult(
        patient_id = sample_patient.id,
        usubjid    = sample_patient.usubjid,
        studyid    = "PHVIGIL2024",
        domain     = "LB",
        lbseq      = 1,
        visit      = "WEEK 12",
        visitnum   = 5.0,
        lbdtc      = "2024-06-01",
        lbdy       = 85,
        lbtestcd   = "ALT",
        lbtest     = "Alanine Aminotransferase",
        lbstresn   = 95.0,
        lbstresu   = "U/L",
        lbnrlo     = 7.0,
        lbnrhi     = 56.0,
        lbnrind    = "HIGH",
        lbclsig    = "Y",
    )
    db_session.add(lb)
    db_session.flush()          # ← flush not commit
    db_session.refresh(lb)
    return lb


@pytest.fixture
def sample_medication(db_session, sample_patient):
    from src.database.models.medication import ConcomitantMedication
    cm = ConcomitantMedication(
        patient_id = sample_patient.id,
        usubjid    = sample_patient.usubjid,
        studyid    = "PHVIGIL2024",
        domain     = "CM",
        cmseq      = 1,
        cmtrt      = "Metformin",
        cmdecod    = "METFORMIN",
        cmcat      = "ANTIDIABETICS",
        cmroute    = "ORAL",
        cmdose     = "500 mg",
        cmdosfrq   = "TWICE DAILY",
        cmongo     = "Y",
        cmdy       = -45,
        cmreas     = "Type 2 Diabetes",
    )
    db_session.add(cm)
    db_session.flush()          # ← flush not commit
    db_session.refresh(cm)
    return cm


@pytest.fixture
def sample_medical_history(db_session, sample_patient):
    from src.database.models.medical_history import MedicalHistory
    mh = MedicalHistory(
        patient_id = sample_patient.id,
        usubjid    = sample_patient.usubjid,
        studyid    = "PHVIGIL2024",
        domain     = "MH",
        mhseq      = 1,
        mhterm     = "Coronary Artery Disease",
        mhdecod    = "CAD",
        mhbodsys   = "Cardiac disorders",
        mhmeddra   = "10011078",
        mhcat      = "MEDICAL HISTORY",
        mhstdtc    = "2015-03-01",
        mhongo     = "Y",
        mhdy       = -2480,
        mhsev      = "MODERATE",
    )
    db_session.add(mh)
    db_session.flush()          # ← flush not commit
    db_session.refresh(mh)
    return mh