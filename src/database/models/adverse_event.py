"""Adverse Events — SDTM AE domain. Matches your AE sheet exactly (20 columns)."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Integer, Text
from sqlalchemy.orm import relationship

from src.database.models.base import Base, GUID


class AdverseEvent(Base):
    __tablename__ = "adverse_events"

    id         = Column(GUID(), primary_key=True, default=uuid.uuid4)
    patient_id = Column(GUID(), ForeignKey("patients.id"), nullable=False, index=True)

    # SDTM identifiers
    usubjid   = Column(String(100), index=True)
    studyid   = Column(String(50),  index=True)
    domain    = Column(String(10),  default="AE")
    aeseq     = Column(Integer)

    # Event terms
    aeterm    = Column(String(500), index=True)  # verbatim term e.g. "Hepatotoxicity"
    aedecod   = Column(String(500), index=True)  # MedDRA preferred term code e.g. HEPATOTOX
    aebodsys  = Column(String(500), index=True)  # System Organ Class e.g. "Renal disorders"
    aemeddra  = Column(String(50))               # numeric MedDRA code

    # Timing
    aestdtc   = Column(String(50))   # AE start date
    aeendtc   = Column(String(50))   # AE end date
    aedur     = Column(Integer)      # duration in days (1–45)
    aedy      = Column(Integer)      # study day of AE onset

    # Severity  — NOTE: your sheet uses AEGRADE (numeric) + AESEV (label)
    aesev     = Column(String(50),  index=True)  # MILD / MODERATE / SEVERE / LIFE-THREATENING
    aegrade   = Column(Integer,     index=True)  # 1 / 2 / 3 / 4

    # Outcome & causality
    aeout     = Column(String(100))              # RECOVERED/RESOLVED, FATAL, etc.
    aerel     = Column(String(100), index=True)  # UNRELATED / POSSIBLY RELATED / etc.

    # Seriousness flags  — your sheet uses AESERFL not AESER
    aeserfl   = Column(String(10),  index=True)  # Y/N serious AE flag (Grade≥3 or FATAL or random 7%)
    aesdth    = Column(String(10))               # Y/N death flag (Y only when AEOUT=FATAL)
    aeshosp   = Column(String(10))               # Y/N hospitalisation required
    aeslife   = Column(String(10))               # Y/N life-threatening (Y when AESEV=LIFE-THREATENING)

    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="adverse_events")