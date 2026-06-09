"""
SQL RAG Retriever — column names matched to actual SDTM data.
Key changes from original:
  - AdverseEvent.aeser  → AdverseEvent.aeserfl
  - ConcomitantMedication.cmindc   → ConcomitantMedication.cmreas
  - ConcomitantMedication.cmongoing → ConcomitantMedication.cmongo
  - Added: aegrade filter, bmicat, diagcd filters
"""
from typing import Dict, Any, List

from sqlalchemy.orm import Session
from sqlalchemy import or_
from loguru import logger
# from sympy import re

from src.database.models.patient import Patient
from src.database.models.adverse_event import AdverseEvent
from src.database.models.lab_result import LabResult
from src.database.models.medication import ConcomitantMedication
from src.database.models.medical_history import MedicalHistory
from src.database.models.study import ClinicalStudy
from src.config.settings import settings


class SQLRetriever:

    def __init__(self, db: Session):
        self.db = db

    def retrieve(self, classification: Dict[str, Any], original_query: str) -> List[Dict[str, Any]]:
        filters  = classification.get("filters", {})
        entities = classification.get("sql_entities", [])
        results  = []

        study_id     = filters.get("study_id")
        patient_id   = filters.get("patient_id")
        serious_only = filters.get("serious_only", False)
        severity     = filters.get("severity")
        age_filter   = filters.get("age_filter")

        # import re

        # if not patient_id:
        #     match = re.search(
        #         r'\b(?:PAT|SUBJ|API-DM)[-_A-Z0-9]+\b',
        #         original_query,
        #         re.IGNORECASE
        #     )
        #     if match:
        #         patient_id = match.group(0)

        query_lower = original_query.lower()

        if (
            "how many studies" in query_lower
            or "count studies" in query_lower
            or "number of studies" in query_lower
        ):
            return self._count_studies()
        
        if (
            "how many patients" in query_lower
            or "count patients" in query_lower
            or "number of patients" in query_lower
        ):
            return self._count_patients()

        if (
            "how many adverse events" in query_lower
            or "count adverse events" in query_lower
            or "number of adverse events" in query_lower
        ):
            return self._count_adverse_events()


        if "adverse_events" in entities or self._query_mentions_ae(original_query):
            results.extend(self._query_adverse_events(
                study_id=study_id, patient_id=patient_id,
                serious_only=serious_only, severity=severity,
                query_text=original_query,
            ))

        if "patients" in entities or self._query_mentions_patients(original_query):
            results.extend(self._query_patients(
                study_id=study_id, patient_id=patient_id,
                age_filter=age_filter, query_text=original_query,
            ))

        if "lab_results" in entities or self._query_mentions_labs(original_query):
            results.extend(self._query_lab_results(
                patient_id=patient_id, study_id=study_id, query_text=original_query,
            ))

        if "medications" in entities or self._query_mentions_meds(original_query):
            results.extend(self._query_medications(
                patient_id=patient_id, query_text=original_query,
            ))

        if "medical_history" in entities or self._query_mentions_mh(original_query):
            results.extend(self._query_medical_history(
                patient_id=patient_id, query_text=original_query,
            ))

        if "studies" in entities or self._query_mentions_study(original_query):
            results.extend(self._query_studies(study_id=study_id))

        return results[:settings.sql_max_rows]

    # ──────────────────────────────────────────────────────────────────────
    def _query_adverse_events(
        self,
        study_id=None, patient_id=None,
        serious_only=False, severity=None, query_text="",
    ) -> List[Dict[str, Any]]:
        q = self.db.query(AdverseEvent)

        if study_id:
            q = q.filter(AdverseEvent.studyid.ilike(f"%{study_id}%"))
        if patient_id:
            q = q.filter(AdverseEvent.usubjid.ilike(f"%{patient_id}%"))
        if serious_only:
            q = q.filter(AdverseEvent.aeserfl == "Y")   # ← AESERFL not AESER
        if severity:
            q = q.filter(AdverseEvent.aesev.ilike(f"%{severity}%"))

        # Grade filter — e.g. "grade 3", "grade >= 2"
        grade = self._extract_grade(query_text)
        if grade:
            q = q.filter(AdverseEvent.aegrade >= grade)

        # Keyword search
        keywords = self._extract_medical_keywords(query_text)
        if keywords and not (study_id or patient_id or serious_only):
            q = q.filter(or_(*[AdverseEvent.aedecod.ilike(f"%{kw}%") for kw in keywords]))

        aes = q.limit(settings.sql_max_rows).all()
        if not aes:
            return []

        rows = [
            f"Patient {ae.usubjid}: {ae.aeterm} ({ae.aedecod}) | "
            f"SOC: {ae.aebodsys or 'N/A'} | "
            f"Severity: {ae.aesev or 'N/A'} | Grade: {ae.aegrade or 'N/A'} | "
            f"Serious: {ae.aeserfl or 'N/A'} | Death: {ae.aesdth or 'N/A'} | "
            f"Hospitalised: {ae.aeshosp or 'N/A'} | Life-threatening: {ae.aeslife or 'N/A'} | "
            f"Related: {ae.aerel or 'N/A'} | Outcome: {ae.aeout or 'N/A'} | "
            f"Duration: {ae.aedur or 'N/A'} days | Start: {ae.aestdtc or 'N/A'}"
            for ae in aes
        ]
        content = f"**Adverse Events** ({len(rows)} found):\n" + "\n".join(rows)
        return [{"content": content, "source": "adverse_events table", "type": "sql", "count": len(rows)}]

    # ──────────────────────────────────────────────────────────────────────
    def _query_patients(
        self, study_id=None, patient_id=None, age_filter=None, query_text=""
    ) -> List[Dict[str, Any]]:
        import re as _re
        q = self.db.query(Patient)

        if study_id:
            q = q.filter(Patient.studyid.ilike(f"%{study_id}%"))
        if patient_id:
            q = q.filter(or_(
                Patient.usubjid.ilike(f"%{patient_id}%"),
                Patient.subjid.ilike(f"%{patient_id}%"),
            ))
        if age_filter:
            q = self._apply_age_filter(q, age_filter)

        diag_keywords = self._extract_diagnosis_keywords(query_text)
        if diag_keywords:
            q = q.filter(or_(
                *[Patient.diagnosis.ilike(f"%{kw}%") for kw in diag_keywords] +
                [Patient.diagcd.ilike(f"%{kw}%") for kw in diag_keywords]
            ))

        patients = q.limit(settings.sql_max_rows).all()
        if not patients:
            return []

        rows = [
            f"Patient {p.usubjid}: Age {p.age} {p.ageu or ''} | "
            f"Sex: {p.sex} | Race: {p.race or 'N/A'} | Ethnic: {p.ethnic or 'N/A'} | "
            f"Diagnosis: {p.diagnosis or 'N/A'} ({p.diagcd or 'N/A'}) | "
            f"Arm: {p.arm or 'N/A'} | BMI: {p.bmi or 'N/A'} ({p.bmicat or 'N/A'}) | "
            f"Smoking: {p.smokestat or 'N/A'} | Alcohol: {p.alcoholuse or 'N/A'} | "
            f"Country: {p.country or 'N/A'} | Site: {p.siteid or 'N/A'}"
            for p in patients
        ]
        content = f"**Patients** ({len(rows)} found):\n" + "\n".join(rows)
        return [{"content": content, "source": "patients table", "type": "sql", "count": len(rows)}]
    
    # ──────────────────────────────────────────────────────────────────────
    def _apply_age_filter(self, query, age_filter: str):
        import re as _re
        age_filter = age_filter.lower().strip()
        if "between" in age_filter:
            nums = _re.findall(r'\d+', age_filter)
            if len(nums) >= 2:
                return query.filter(Patient.age.between(float(nums[0]), float(nums[1])))
        elif ">=" in age_filter or "≥" in age_filter:
            nums = _re.findall(r'\d+', age_filter)
            if nums:
                return query.filter(Patient.age >= float(nums[0]))
        elif ">" in age_filter:
            nums = _re.findall(r'\d+', age_filter)
            if nums:
                return query.filter(Patient.age > float(nums[0]))
        elif "<=" in age_filter or "≤" in age_filter:
            nums = _re.findall(r'\d+', age_filter)
            if nums:
                return query.filter(Patient.age <= float(nums[0]))
        elif "<" in age_filter:
            nums = _re.findall(r'\d+', age_filter)
            if nums:
                return query.filter(Patient.age < float(nums[0]))
        return query
    # ──────────────────────────────────────────────────────────────────────
    def _query_lab_results(self, patient_id=None, study_id=None, query_text="") -> List[Dict[str, Any]]:
        q = self.db.query(LabResult)
        if patient_id:
            q = q.filter(LabResult.usubjid.ilike(f"%{patient_id}%"))
        if study_id:
            q = q.filter(LabResult.studyid.ilike(f"%{study_id}%"))

        # Match short lab codes (ALT, AST) against lbtestcd,
        # and longer terms against lbtest — combined with OR
        keywords = self._extract_medical_keywords(query_text)
        LAB_SHORT_CODES = {"alt", "ast", "wbc", "ldh", "cd4", "egfr", "hb"}
        if keywords and not patient_id:
            short = [k for k in keywords if k in LAB_SHORT_CODES]
            long_  = [k for k in keywords if k not in LAB_SHORT_CODES and len(k) > 3]
            conditions = []
            for k in short:
                conditions.append(LabResult.lbtestcd.ilike(f"%{k}%"))
            for k in long_:
                conditions.append(LabResult.lbtest.ilike(f"%{k}%"))
            if conditions:
                q = q.filter(or_(*conditions))

        # Always restrict to abnormal unless patient-specific
        if not patient_id:
            q = q.filter(LabResult.lbnrind.in_(["HIGH", "LOW"]))

        labs = q.limit(50).all()
        if not labs:
            return []

        rows = [
            f"Patient {lb.usubjid}: {lb.lbtest} ({lb.lbtestcd}) = {lb.lbstresn} {lb.lbstresu or ''} "
            f"[{lb.lbnrind}] | Ref: {lb.lbnrlo}–{lb.lbnrhi} | "
            f"Clinically significant: {lb.lbclsig or 'N/A'} | "
            f"Visit: {lb.visit or 'N/A'} | Study day: {lb.lbdy or 'N/A'}"
            for lb in labs
        ]
        content = f"**Lab Results** ({len(rows)} found):\n" + "\n".join(rows)
        return [{"content": content, "source": "lab_results table", "type": "sql", "count": len(rows)}]
    # ──────────────────────────────────────────────────────────────────────
    def _query_medications(
        self, patient_id=None, query_text=""
    ) -> List[Dict[str, Any]]:
        q = self.db.query(ConcomitantMedication)
        if patient_id:
            q = q.filter(ConcomitantMedication.usubjid.ilike(f"%{patient_id}%"))

        keywords = self._extract_medical_keywords(query_text)
        if keywords and not patient_id:
            q = q.filter(or_(*[
                ConcomitantMedication.cmdecod.ilike(f"%{kw}%") for kw in keywords
            ]))

        meds = q.limit(50).all()
        if not meds:
            return []

        rows = [
            f"Patient {m.usubjid}: {m.cmtrt} ({m.cmdecod}) | "
            f"Class: {m.cmcat or 'N/A'} | "
            f"Dose: {m.cmdose or 'N/A'} | Route: {m.cmroute or 'N/A'} | "
            f"Frequency: {m.cmdosfrq or 'N/A'} | Ongoing: {m.cmongo or 'N/A'} | "
            f"Indication: {m.cmreas or 'N/A'} | "
            f"Start day: {m.cmdy or 'N/A'}"
            for m in meds
        ]
        content = f"**Medications** ({len(rows)} found):\n" + "\n".join(rows)
        return [{"content": content, "source": "concomitant_medications table", "type": "sql", "count": len(rows)}]

    # ──────────────────────────────────────────────────────────────────────
    def _query_medical_history(
        self, patient_id=None, query_text=""
    ) -> List[Dict[str, Any]]:
        q = self.db.query(MedicalHistory)
        if patient_id:
            q = q.filter(MedicalHistory.usubjid.ilike(f"%{patient_id}%"))

        keywords = self._extract_medical_keywords(query_text)
        if keywords and not patient_id:
            q = q.filter(or_(*[MedicalHistory.mhterm.ilike(f"%{kw}%") for kw in keywords]))

        mhs = q.limit(50).all()
        if not mhs:
            return []

        rows = [
            f"Patient {mh.usubjid}: {mh.mhterm} ({mh.mhdecod}) | "
            f"SOC: {mh.mhbodsys or 'N/A'} | Severity: {mh.mhsev or 'N/A'} | "
            f"Ongoing: {mh.mhongo or 'N/A'} | "
            f"Diagnosed: {mh.mhstdtc or 'N/A'} | Study day onset: {mh.mhdy or 'N/A'}"
            for mh in mhs
        ]
        content = f"**Medical History** ({len(rows)} found):\n" + "\n".join(rows)
        return [{"content": content, "source": "medical_histories table", "type": "sql", "count": len(rows)}]

    # ──────────────────────────────────────────────────────────────────────
    def _query_studies(self, study_id=None) -> List[Dict[str, Any]]:
        q = self.db.query(ClinicalStudy)
        if study_id:
            q = q.filter(or_(
                ClinicalStudy.nct_id.ilike(f"%{study_id}%"),
                ClinicalStudy.brief_title.ilike(f"%{study_id}%"),
                ClinicalStudy.acronym.ilike(f"%{study_id}%"),
            ))
        studies = q.limit(10).all()
        if not studies:
            return []

        rows = [
            f"Study {s.nct_id}: {s.brief_title} | "
            f"Status: {s.overall_status} | Phase: {s.phase} | "
            f"Condition: {s.conditions} | Sponsor: {s.lead_sponsor} | "
            f"Enrolled: {s.enrollment_count} | Start: {s.start_date}"
            for s in studies
        ]
        content = f"**Clinical Studies** ({len(rows)} found):\n" + "\n".join(rows)
        return [{"content": content, "source": "clinical_studies table", "type": "sql"}]
    

    def _count_studies(self):
        count = self.db.query(ClinicalStudy).count()

        return [{
            "type": "sql",
            "source": "clinical_studies",
            "content": f"Total studies in database: {count}"
        }]
    
    def _count_patients(self):
        count = self.db.query(Patient).count()

        return [{
            "type": "sql",
            "source": "patients",
            "content": f"Total patients in database: {count}"
        }]
    
    def _count_adverse_events(self):
        count = self.db.query(AdverseEvent).count()

        return [{
            "type": "sql",
            "source": "adverse_events",
            "content": f"Total adverse events in database: {count}"
        }]
    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────
    def _extract_medical_keywords(self, text: str) -> List[str]:
        stopwords = {
            "show", "list", "find", "get", "what", "which", "how", "many", "all",
            "the", "a", "an", "in", "of", "for", "and", "or", "with", "patients",
            "study", "patient", "data", "results", "give", "me", "tell", "above",
            "below", "only", "have", "had", "were", "who", "does",
        }
        words = [w.strip(".,?!;:'\"") for w in text.lower().split()]
        LAB_SHORT_CODES = {"alt", "ast", "wbc", "ldh", "cd4", "egfr", "hb", "ggт"}
        return [
              w for w in words
             if (len(w) > 3 or w in LAB_SHORT_CODES) and w not in stopwords
        ]

    def _extract_diagnosis_keywords(self, text: str) -> List[str]:
        """Extract disease/diagnosis terms from query text."""
        disease_terms = [
            "hypertension", "diabetes", "cancer", "hiv", "hepatitis", "sepsis",
            "stroke", "cardiac", "renal", "liver", "lung", "breast", "leukemia",
            "multiple sclerosis", "arthritis", "asthma", "copd", "depression",
            "alzheimer", "heart failure", "obesity", "thyroid",
        ]
        text_lower = text.lower()
        return [d for d in disease_terms if d in text_lower]

    def _extract_grade(self, text: str) -> int | None:
        """Extract numeric grade from query e.g. 'grade 3' → 3"""
        import re
        match = re.search(r'grade\s*([1-4])', text.lower())
        return int(match.group(1)) if match else None

    def _query_mentions_ae(self, q: str) -> bool:
        return any(kw in q.lower() for kw in [
            "adverse", "event", " ae ", "toxicity", "side effect", "reaction",
            "serious", "fatal", "hospitaliz", "grade",
        ])

    def _query_mentions_patients(self, q: str) -> bool:
        import re

        q_lower = q.lower()

        keywords = [
            "patient", "patients", "subject", "demographic",
            "age", "sex", "gender",
            "arm", "bmi", "smoke", "alcohol",
            "education", "country", "site",
            "blood", "allergy"
        ]

        if any(k in q_lower for k in keywords):
            return True

        # PAT-1 / PAT001 / SUBJ001
        if re.search(r'\b(pat|subj)[-_]?\w+\b', q_lower):
            return True

        return False

    def _query_mentions_labs(self, q: str) -> bool:
        return any(kw in q.lower() for kw in [
            "lab", "result", "test", "alt", "ast", "alat", "asat",
            "creatinine", "hemoglobin", "hba1c", "cd4", "glucose",
            "liver", "kidney", "abnormal", "high", "low", "normal range",
        ])

    def _query_mentions_meds(self, q: str) -> bool:
        return any(kw in q.lower() for kw in [
            "medication", "drug", "medicine", "treatment", "concomitant",
            "dose", "route", "ongoing", "metformin", "pembrolizumab",
        ])

    def _query_mentions_mh(self, q: str) -> bool:
        return any(kw in q.lower() for kw in [
            "history", "comorbid", "prior", "previous", "condition",
            "diagnosed", "chronic", "hypertension", "diabetes",
        ])

    def _query_mentions_study(self, q: str) -> bool:
        return any(kw in q.lower() for kw in [
            "study", "studies", "trial", "trials",
            "nct", "protocol", "phase",
            "sponsor", "enroll", "enrollment",
        ])