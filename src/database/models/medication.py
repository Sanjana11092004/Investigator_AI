"""Concomitant Medications — SDTM CM domain. Matches your CM sheet exactly (15 columns)."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.database.models.base import Base


class ConcomitantMedication(Base):
    __tablename__ = "concomitant_medications"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)

    # SDTM identifiers
    usubjid   = Column(String(100), index=True)
    studyid   = Column(String(50),  index=True)
    domain    = Column(String(10),  default="CM")
    cmseq     = Column(Integer)

    # Drug identity
    cmtrt     = Column(String(500), index=True)   # verbatim e.g. "Metformin"
    cmdecod   = Column(String(500), index=True)   # standardised uppercase e.g. METFORMIN
    cmcat     = Column(String(200))               # drug class e.g. ANTIDIABETICS

    # Administration
    cmroute   = Column(String(100))               # ORAL / IV / SUBCUTANEOUS / INHALED / IM
    cmdose    = Column(String(100))               # e.g. "40 mg", "175 mg/m2"
    cmdosfrq  = Column(String(100))               # ONCE DAILY / TWICE DAILY / EVERY 3 WEEKS / etc.

    # Timing
    cmstdtc   = Column(String(50))                # start date (can be before enrolment)
    cmendtc   = Column(String(50))                # end date (empty if ongoing)
    cmongo    = Column(String(10))                # Y/N ongoing flag (~55% Y)
    cmdy      = Column(Integer)                   # study day of start (negative = before enrolment)

    # Indication
    cmreas    = Column(Text)                      # reason / indication e.g. "Type 2 Diabetes"

    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="medications")