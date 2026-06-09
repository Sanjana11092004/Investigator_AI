"""
ClinicalTrials JSON Ingestor.
Parses ClinicalTrials.gov API format and stores in clinical_studies table.
Also adds study text to the vector store for semantic search.
"""
import json
import os
from datetime import date
from pathlib import Path
from typing import Dict, Any, Optional

from sqlalchemy.orm import Session
from loguru import logger

from src.database.models.study import ClinicalStudy
from src.database.models.document import IngestedDocument
from src.ingestion.base_ingestor import BaseIngestor
from src.ingestion.deduplication import (
    compute_file_hash,
    is_already_ingested,
    register_document,
)


def _parse_date(date_str: Optional[str]) -> Optional[date]:
    """Parse date strings from ClinicalTrials JSON."""
    if not date_str:
        return None
    for fmt in ["%Y-%m-%d", "%B %d, %Y", "%B %Y", "%Y"]:
        try:
            from datetime import datetime
            return datetime.strptime(date_str.strip(), fmt).date()
        except (ValueError, AttributeError):
            continue
    return None


def _safe_get(data: dict, *keys, default=None):
    """Safely traverse nested dicts."""
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, default)
        else:
            return default
    return current if current is not None else default


class ClinicalTrialsIngestor(BaseIngestor):
    """
    Ingests ClinicalTrials JSON files.
    
    Supports both:
    - Single study JSON (one study object)
    - Array of studies
    - ClinicalTrials.gov API response format
    """

    def can_handle(self, file_path: str) -> bool:
        return file_path.endswith(".json")

    def ingest(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """
        Parse JSON and insert clinical study records into PostgreSQL.
        
        Also returns text content for vector store indexing.
        """
        display_name = Path(kwargs.get("original_filename") or file_path).name
        file_hash = compute_file_hash(file_path)

        if is_already_ingested(self.db, file_hash):
            return {"success": True, "records": 0, "message": "Already ingested. Skipped."}

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {file_path}: {e}")
            register_document(
                self.db, display_name, file_path, file_hash,
                "clinical_trials_json", os.path.getsize(file_path),
                status="failed", error_message=str(e)
            )
            return {"success": False, "records": 0, "message": f"JSON parse error: {e}"}

        # Normalize to list
        if isinstance(raw, dict):
            # Could be a single study or wrapped in 'studies'
            studies_raw = raw.get("studies", [raw])
        elif isinstance(raw, list):
            studies_raw = raw
        else:
            return {"success": False, "records": 0, "message": "Unrecognized JSON format"}

        count = 0
        for study_data in studies_raw:
            try:
                study = self._parse_study(study_data)
                if study:
                    # Check for existing NCT ID (upsert)
                    existing = (
                        self.db.query(ClinicalStudy)
                        .filter(ClinicalStudy.nct_id == study.nct_id)
                        .first()
                    )
                    if existing:
                        logger.info(f"Study {study.nct_id} already exists. Updating.")
                        for col in ["brief_title", "brief_summary", "raw_json"]:
                            setattr(existing, col, getattr(study, col))
                    else:
                        self.db.add(study)
                    count += 1
            except Exception as e:
                logger.warning(f"Failed to parse one study entry: {e}")
                continue

        self.db.commit()

        register_document(
            self.db,
            display_name,
            file_path,
            file_hash,
            "clinical_trials_json",
            os.path.getsize(file_path),
            record_count=count,
        )

        logger.info(f"ClinicalTrials ingestor: {count} studies from {Path(file_path).name}")
        return {"success": True, "records": count, "message": f"Ingested {count} studies"}

    def _parse_study(self, data: dict) -> Optional[ClinicalStudy]:
        """
        Parse a single study from various ClinicalTrials JSON formats.
        Handles both old and new API formats.
        """
        # New API format (v2)
        protocol = data.get("protocolSection", {})
        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        desc_module = protocol.get("descriptionModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        design_module = protocol.get("designModule", {})
        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
        eligibility_module = protocol.get("eligibilityModule", {})
        arms_module = protocol.get("armsInterventionsModule", {})

        nct_id = (
            id_module.get("nctId")
            or data.get("nct_id")
            or data.get("NCTId")
            or data.get("id")
        )

        if not nct_id:
            logger.warning("Study has no NCT ID, skipping.")
            return None

        title = (
            id_module.get("briefTitle")
            or data.get("BriefTitle")
            or data.get("title")
            or "Unknown Title"
        )

        # # Conditions
        conditions = conditions_module.get("conditions", [])
        condition_str = ", ".join(conditions) if conditions else data.get("condition", "")

        # Interventions
        interventions = arms_module.get("interventions", [])
        if interventions:
            intervention_str = ", ".join(
                f"{i.get('name', '')} ({i.get('type', '')})" for i in interventions[:5]
            )
        else:
            intervention_str = data.get("intervention", "")

        # Dates
        start_date_str = (
            _safe_get(status_module, "startDateStruct", "date")
            or data.get("StartDate")
        )
        completion_date_str = (
            _safe_get(status_module, "completionDateStruct", "date")
            or data.get("CompletionDate")
        )

        return ClinicalStudy(
            nct_id=nct_id,
            brief_title=title,
            official_title=id_module.get("officialTitle") or data.get("OfficialTitle"),
            brief_summary=(
                desc_module.get("briefSummary")
                or data.get("BriefSummary")
                or data.get("summary", "")
            ),
            detailed_description=(
                desc_module.get("detailedDescription")
                or data.get("DetailedDescription", "")
            ),
            # study_status=(
            #     status_module.get("overallStatus")
            #     or data.get("OverallStatus")
            #     or data.get("status", "")
            # ),
            phase=(
                ", ".join(design_module.get("phases", []))
                or data.get("Phase", "")
            ),
            study_type=design_module.get("studyType") or data.get("StudyType", ""),
            # condition=condition_str,
            interventions=[{"name": intervention_str}] if intervention_str else [],
            lead_sponsor=(
                 _safe_get(sponsor_module, "leadSponsor", "name")
                 or data.get("LeadSponsorName", "")
            ),
            overall_status=(
                status_module.get("overallStatus")
                or data.get("OverallStatus")
                or data.get("status", "")
            ),
            conditions=condition_str,
            # start_date / completion_date columns are String(50) — store raw
            # string (formats vary: "YYYY", "YYYY-MM", "YYYY-MM-DD").
            start_date=start_date_str,
            completion_date=completion_date_str,
            enrollment_count=int(
                _safe_get(design_module, "enrollmentInfo", "count")
                or data.get("EnrollmentCount")
                or 0
            ),
            minimum_age=(
                eligibility_module.get("minimumAge")
                or data.get("MinimumAge", "")
            ),
            maximum_age=(
                eligibility_module.get("maximumAge")
                or data.get("MaximumAge", "")
            ),
            sex=eligibility_module.get("sex") or data.get("Gender", ""),
            healthy_volunteers=(
                eligibility_module.get("healthyVolunteers")
                or data.get("HealthyVolunteers", "")
            ),
            raw_json=json.dumps(data),
        )