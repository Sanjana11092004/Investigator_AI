"""Lab Results — SDTM LB domain. Matches your LB sheet exactly (16 columns)."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from src.database.models.base import Base


class LabResult(Base):
    __tablename__ = "lab_results"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    patient_id = Column(UUID(as_uuid=True), ForeignKey("patients.id"), nullable=False, index=True)

    # SDTM identifiers
    usubjid   = Column(String(100), index=True)
    studyid   = Column(String(50),  index=True)
    domain    = Column(String(10),  default="LB")
    lbseq     = Column(Integer)

    # Visit
    visit     = Column(String(100), index=True)   # SCREENING / BASELINE / WEEK 4 / … / END OF STUDY
    visitnum  = Column(Float,       index=True)   # 1–7
    lbdtc     = Column(String(50))                # sample collection date
    lbdy      = Column(Integer)                   # study day of collection

    # Test identity
    lbtestcd  = Column(String(50),  index=True)   # short code e.g. ALT, HBA1C, CD4
    lbtest    = Column(String(500), index=True)   # full name e.g. "Alanine Aminotransferase"

    # Results — your sheet stores the numeric result only
    lbstresn  = Column(Float,       index=True)   # numeric result
    lbstresu  = Column(String(100))               # unit e.g. U/L, mg/dL

    # Reference range
    lbnrlo    = Column(Float)                     # normal range lower bound
    lbnrhi    = Column(Float)                     # normal range upper bound
    lbnrind   = Column(String(50),  index=True)   # NORMAL / HIGH / LOW

    # Clinical significance
    lbclsig   = Column(String(10))                # Y/N — >50% beyond range boundary

    created_at = Column(DateTime, default=datetime.utcnow)

    patient = relationship("Patient", back_populates="lab_results")