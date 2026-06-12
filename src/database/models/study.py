"""
Clinical Study — from ClinicalTrials JSON.
Covers all 17 attribute groups from your data dictionary.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Date, Integer, Float, Boolean, JSON
from sqlalchemy.orm import relationship

from src.database.models.base import Base, GUID


class ClinicalStudy(Base):
    __tablename__ = "clinical_studies"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # ── 1. Identification ─────────────────────────────────────────────────
    nct_id              = Column(String(20),  unique=True, nullable=False, index=True)
    org_study_id        = Column(String(200))
    organization_name   = Column(String(500))
    brief_title         = Column(Text)
    official_title      = Column(Text)
    acronym             = Column(String(100))

    # ── 2. Study Status ───────────────────────────────────────────────────
    overall_status          = Column(String(100), index=True)
    start_date              = Column(String(50))   # kept as string — formats vary
    primary_completion_date = Column(String(50))
    completion_date         = Column(String(50))
    first_submitted_date    = Column(String(50))
    results_posted_date     = Column(String(50))
    last_update_date        = Column(String(50))

    # ── 3. Sponsor / Collaborators ────────────────────────────────────────
    lead_sponsor        = Column(String(500))
    sponsor_class       = Column(String(100))   # NIH / INDUSTRY / OTHER etc.
    responsible_party   = Column(Text)

    # ── 4. Study Description ──────────────────────────────────────────────
    brief_summary       = Column(Text)
    detailed_description= Column(Text)

    # ── 5. Conditions / Keywords ──────────────────────────────────────────
    conditions          = Column(Text)    # comma-separated list
    keywords            = Column(Text)    # comma-separated list

    # ── 6. Study Design ───────────────────────────────────────────────────
    study_type          = Column(String(100))
    observational_model = Column(String(100))
    time_perspective    = Column(String(100))
    enrollment_count    = Column(Integer)
    enrollment_type     = Column(String(50))   # ACTUAL / ANTICIPATED

    # ── 7. Interventions (stored as JSON list) ────────────────────────────
    interventions       = Column(JSON, default=list)
    # Each item: {type, name, description, other_names, arm_groups}

    # ── 8. Outcome Measures (stored as JSON) ─────────────────────────────
    primary_outcomes    = Column(JSON, default=list)
    # Each: {measure, description, time_frame}
    secondary_outcomes  = Column(JSON, default=list)

    # ── 9. Eligibility Criteria ───────────────────────────────────────────
    inclusion_criteria  = Column(Text)
    exclusion_criteria  = Column(Text)
    healthy_volunteers  = Column(String(50))
    sex                 = Column(String(50))
    minimum_age         = Column(String(50))
    maximum_age         = Column(String(50))
    std_age_categories  = Column(Text)    # e.g. "ADULT, OLDER_ADULT"
    study_population    = Column(Text)
    sampling_method     = Column(String(100))

    # ── 10. Locations / Contacts (stored as JSON list) ───────────────────
    locations           = Column(JSON, default=list)
    # Each: {facility, city, state, country, lat, lng}
    contacts            = Column(JSON, default=list)
    # Each: {name, role, email, phone}

    # ── 11. Participant Flow (stored as JSON) ─────────────────────────────
    participant_flow    = Column(JSON, default=dict)
    # {groups, milestones: {started, completed, not_completed}, dropout_reasons}

    # ── 12. Baseline Characteristics ─────────────────────────────────────
    baseline_mean_age   = Column(Float)
    baseline_sex_dist   = Column(JSON, default=dict)   # {male: N, female: N}
    baseline_other      = Column(JSON, default=dict)   # race, weight, etc.

    # ── 13. Outcome Results ───────────────────────────────────────────────
    outcome_results     = Column(JSON, default=list)
    # Measurements: SBP/DBP, week12/52, change from baseline, BP goal, dose, duration

    # ── 14. Adverse Events summary ───────────────────────────────────────
    ae_serious_count    = Column(Integer)
    ae_non_serious_count= Column(Integer)
    ae_population_at_risk= Column(Integer)
    ae_summary          = Column(JSON, default=list)
    # Each: {term, organ_system, n_events, n_participants}

    # ── 15. References / External Links ──────────────────────────────────
    study_website       = Column(Text)
    references          = Column(JSON, default=list)   # list of URLs/titles

    # ── 16. Controlled Medical Vocabulary ────────────────────────────────
    mesh_conditions     = Column(JSON, default=list)   # MeSH disease terms
    mesh_interventions  = Column(JSON, default=list)   # MeSH drug terms
    condition_hierarchy = Column(JSON, default=list)   # ancestor terms
    intervention_hierarchy = Column(JSON, default=list)

    # ── 17. Derived / Misc ────────────────────────────────────────────────
    version_holder      = Column(String(200))
    phase               = Column(String(50))    # PHASE1 / PHASE2 / PHASE3 / NA
    raw_json            = Column(Text)          # full original JSON for reference

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    patients = relationship("Patient", back_populates="study", cascade="all, delete-orphan")