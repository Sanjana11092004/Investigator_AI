"""Patient demographics — SDTM DM domain. Matches your DM sheet exactly (26 columns)."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Float, Integer, ForeignKey, Text
from sqlalchemy.orm import relationship

from src.database.models.base import Base, GUID


class Patient(Base):
    __tablename__ = "patients"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    study_id = Column(GUID(), ForeignKey("clinical_studies.id"), nullable=True)

    # Core SDTM identifiers
    usubjid   = Column(String(100), unique=True, nullable=False, index=True)  # e.g. SUBJ-0042
    subjid    = Column(String(50),  index=True)
    studyid   = Column(String(50),  index=True)                               # PHVIGIL2024
    domain    = Column(String(10),  default="DM")

    # Study participation dates
    rfstdtc   = Column(String(50))   # enrolment start date
    rfendtc   = Column(String(50))   # enrolment end date
    dmdtc     = Column(String(50))   # demographics collection date
    dmdy      = Column(Integer)      # study day of demographics (always 1)

    # Site / geography
    siteid    = Column(String(50))
    country   = Column(String(100))  # ISO 3-letter code e.g. IND, USA, GBR

    # Demographics
    age       = Column(Float,        index=True)
    ageu      = Column(String(20))   # always YEARS
    sex       = Column(String(20),   index=True)   # M / F
    race      = Column(String(100))  # WHITE, ASIAN, BLACK OR AFRICAN AMERICAN, etc.
    ethnic    = Column(String(100))  # HISPANIC OR LATINO / NOT HISPANIC OR LATINO / NOT REPORTED

    # Treatment arm
    armcd     = Column(String(50))   # TRTA, TRTB, PLCBO, OBS
    arm       = Column(String(200))  # Treatment A, Placebo, etc.
    actarmcd  = Column(String(50))
    actarm    = Column(String(200))

    # Disease / clinical
    diagnosis = Column(Text,         index=True)   # e.g. Hypertension, Breast Cancer
    diagcd    = Column(String(50),   index=True)   # e.g. HTN, BRCA, SEP
    bmi       = Column(Float)
    bmicat    = Column(String(50))   # UNDERWEIGHT / NORMAL / OVERWEIGHT / OBESE

    # Lifestyle
    smokestat   = Column(String(50)) # NEVER / FORMER / CURRENT / NOT REPORTED
    alcoholuse  = Column(String(50)) # NEVER / SOCIAL / HEAVY / FORMER / NOT REPORTED
    education   = Column(String(100))# PRIMARY / SECONDARY / BACHELOR / POSTGRADUATE / NOT REPORTED

    # Death (populated only for deceased patients)
    dthfl     = Column(String(10))
    dthdtc    = Column(String(50))

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    study            = relationship("ClinicalStudy", back_populates="patients")
    adverse_events   = relationship("AdverseEvent",          back_populates="patient", cascade="all, delete-orphan")
    lab_results      = relationship("LabResult",             back_populates="patient", cascade="all, delete-orphan")
    medications      = relationship("ConcomitantMedication", back_populates="patient", cascade="all, delete-orphan")
    medical_histories= relationship("MedicalHistory",        back_populates="patient", cascade="all, delete-orphan")