"""
Stats endpoint — dataset overview counts for the dashboard.
GET /stats — row counts per table.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.database.connection import get_db
from src.database.models.patient import Patient
from src.database.models.adverse_event import AdverseEvent
from src.database.models.lab_result import LabResult
from src.database.models.medication import ConcomitantMedication
from src.database.models.medical_history import MedicalHistory
from src.database.models.study import ClinicalStudy
from src.database.models.document import IngestedDocument
from src.database.models.session import InvestigationSession

router = APIRouter(prefix="/stats", tags=["Stats"])


@router.get("")
def get_stats(db: Session = Depends(get_db)):
    """Return row counts across the core tables for the dashboard overview."""
    return {
        "patients": db.query(Patient).count(),
        "adverse_events": db.query(AdverseEvent).count(),
        "lab_results": db.query(LabResult).count(),
        "medications": db.query(ConcomitantMedication).count(),
        "medical_history": db.query(MedicalHistory).count(),
        "studies": db.query(ClinicalStudy).count(),
        "documents": db.query(IngestedDocument).count(),
        "sessions": db.query(InvestigationSession).count(),
        "model": settings.groq_model,
    }
