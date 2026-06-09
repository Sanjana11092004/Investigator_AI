"""Medical History — SDTM MH domain. Matches your MH sheet exactly (14 columns)."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.database.models.base import Base


class MedicalHistory(Base):
    __tablename__ = "medical_histories"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)

    # SDTM identifiers
    usubjid   = Column(String(100), index=True)
    studyid   = Column(String(50),  index=True)
    domain    = Column(String(10),  default="MH")
    mhseq     = Column(Integer)

    # Condition
    mhterm    = Column(String(500), index=True)  # full name e.g. "Coronary Artery Disease"
    mhdecod   = Column(String(500), index=True)  # coded e.g. CAD, AUD, CHEPB
    mhbodsys  = Column(String(500))              # organ class e.g. "Cardiac disorders"
    mhmeddra  = Column(String(50))               # numeric MedDRA code
    mhcat     = Column(String(200))              # always MEDICAL HISTORY

    # Timing
    mhstdtc   = Column(String(50))               # diagnosis date (2005 – 30 days before enrolment)
    mhendtc   = Column(String(50))               # resolution date (empty if ongoing)
    mhongo    = Column(String(10))               # Y/N ongoing flag (~60% Y)
    mhdy      = Column(Integer)                  # study day of onset (large negative e.g. -2480)

    # Severity
    mhsev     = Column(String(50))               # MILD / MODERATE / SEVERE

    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="medical_histories")