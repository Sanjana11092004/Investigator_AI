"""
SQL RAG Retriever — structured retrieval over the SDTM / ClinicalTrials tables.

Two modes:
  • Aggregation  ("how many ... ", "count ...", "average ...") → runs real
    COUNT / AVG queries with the requested filters applied, so the answer is exact.
  • Listing      → returns sample rows, with the TRUE total in the header
    (e.g. "Adverse Events (154 total, showing 20)") so the model never reports the
    capped row count as if it were the total.
"""
from typing import Dict, Any, List

from sqlalchemy.orm import Session
from sqlalchemy import or_, func, distinct
from loguru import logger

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

    # ──────────────────────────────────────────────────────────────────────
    def retrieve(self, classification: Dict[str, Any], original_query: str) -> List[Dict[str, Any]]:
        filters  = classification.get("filters", {})
        entities = classification.get("sql_entities", [])
        results  = []

        study_id     = filters.get("study_id")
        patient_id   = filters.get("patient_id")
        serious_only = filters.get("serious_only", False)
        severity     = filters.get("severity")
        age_filter   = filters.get("age_filter")

        # ── Aggregation path: compute exact counts/averages and return ──
        if self._is_aggregation(original_query):
            agg = self._aggregate(filters, entities, original_query)
            if agg:
                return agg

        # ── Listing path ──
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
            results.extend(self._query_studies(study_id=study_id, query_text=original_query))

        return results[: settings.sql_max_rows]

    # ══════════════════════════════════════════════════════════════════════
    # Query builders (filters applied, no limit) — shared by list + aggregate
    # ══════════════════════════════════════════════════════════════════════
    def _build_ae_query(self, study_id=None, patient_id=None, serious_only=False,
                        severity=None, query_text=""):
        q = self.db.query(AdverseEvent)
        if study_id:
            q = q.filter(AdverseEvent.studyid.ilike(f"%{study_id}%"))
        if patient_id:
            q = q.filter(AdverseEvent.usubjid.ilike(f"%{patient_id}%"))
        if serious_only:
            q = q.filter(AdverseEvent.aeserfl == "Y")
        if severity and "grade" not in severity.lower():
            q = q.filter(AdverseEvent.aesev.ilike(f"%{severity}%"))
        grade = self._extract_grade(query_text)
        if grade:
            q = q.filter(AdverseEvent.aegrade >= grade)
        if self._mentions_fatal(query_text):
            q = q.filter(or_(AdverseEvent.aesdth == "Y", AdverseEvent.aeout.ilike("%FATAL%")))
        # free-text term match (only when no structured filter narrows it already)
        keywords = self._extract_medical_keywords(query_text)
        if keywords and not (study_id or patient_id or serious_only or grade):
            conds = []
            for kw in keywords:
                conds.append(AdverseEvent.aedecod.ilike(f"%{kw}%"))
                conds.append(AdverseEvent.aeterm.ilike(f"%{kw}%"))
            q = q.filter(or_(*conds))
        return q

    def _build_patient_query(self, study_id=None, patient_id=None, age_filter=None, query_text=""):
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
        return q

    def _build_study_query(self, study_id=None, query_text=""):
        q = self.db.query(ClinicalStudy)
        if study_id:
            q = q.filter(or_(
                ClinicalStudy.nct_id.ilike(f"%{study_id}%"),
                ClinicalStudy.brief_title.ilike(f"%{study_id}%"),
                ClinicalStudy.acronym.ilike(f"%{study_id}%"),
            ))
        ql = (query_text or "").lower()
        # status / phase filters from free text
        for status in ["completed", "recruiting", "terminated", "withdrawn",
                       "active", "suspended", "enrolling"]:
            if status in ql:
                q = q.filter(ClinicalStudy.overall_status.ilike(f"%{status}%"))
                break
        import re as _re
        ph = _re.search(r'phase\s*([1-4])', ql)
        if ph:
            q = q.filter(ClinicalStudy.phase.ilike(f"%{ph.group(1)}%"))
        return q

    # ══════════════════════════════════════════════════════════════════════
    # Aggregation
    # ══════════════════════════════════════════════════════════════════════
    def _is_aggregation(self, query: str) -> bool:
        ql = (query or "").lower()
        triggers = ["how many", "how much", "number of", "count of", "count the",
                    "total number", "total count", "average", "avg ", "mean ",
                    "percentage", "what percent", "proportion of"]
        return any(t in ql for t in triggers) or ql.strip().startswith("count ")

    def _aggregate(self, filters: Dict[str, Any], entities, query: str) -> List[Dict[str, Any]]:
        ql = query.lower()
        lines: List[str] = []

        study_id     = filters.get("study_id")
        patient_id   = filters.get("patient_id")
        serious_only = filters.get("serious_only", False)
        severity     = filters.get("severity")
        age_filter   = filters.get("age_filter")
        grade        = self._extract_grade(query)

        wants_patients = ("patient" in ql or "subject" in ql or "patients" in entities)
        wants_ae = (any(k in ql for k in ["adverse", "event", " ae ", "toxicity", "reaction"])
                    or serious_only or severity or grade or self._mentions_fatal(query)
                    or "adverse_events" in entities)
        wants_studies = (any(k in ql for k in ["stud", "trial", "nct", "sponsor", "enroll", "phase"])
                         or "studies" in entities)
        wants_labs = (any(k in ql for k in ["lab", "alt", "ast", "creatinine", "hemoglobin",
                          "hba1c", "glucose"]) or "lab_results" in entities)
        wants_meds = (any(k in ql for k in ["medication", "drug", "medicine", "concomitant"])
                      or "medications" in entities)

        # Adverse-event aggregation (and distinct patients with that AE condition)
        if wants_ae:
            aeq = self._build_ae_query(study_id, patient_id, serious_only, severity, query)
            n_ae = aeq.count()
            desc = self._ae_filter_desc(filters, query)
            if wants_patients:
                n_pts = aeq.with_entities(AdverseEvent.usubjid).distinct().count()
                lines.append(f"Distinct patients with {desc}adverse events: **{n_pts}**")
            lines.append(f"{desc.capitalize() or 'Total '}adverse-event records: **{n_ae}**")
        elif wants_patients:
            pq = self._build_patient_query(study_id, patient_id, age_filter, query)
            lines.append(f"Patients matching the query: **{pq.count()}**")

        if wants_studies:
            sq = self._build_study_query(study_id, query)
            lines.append(f"Studies matching the query: **{sq.count()}**")

        if wants_labs:
            lq = self.db.query(LabResult)
            if patient_id:
                lq = lq.filter(LabResult.usubjid.ilike(f"%{patient_id}%"))
            if "abnormal" in ql or "high" in ql or "low" in ql:
                lq = lq.filter(LabResult.lbnrind.in_(["HIGH", "LOW"]))
            lines.append(f"Lab result records matching the query: **{lq.count()}**")

        if wants_meds:
            mq = self.db.query(ConcomitantMedication)
            if patient_id:
                mq = mq.filter(ConcomitantMedication.usubjid.ilike(f"%{patient_id}%"))
            lines.append(f"Medication records matching the query: **{mq.count()}**")

        # Averages
        if "average" in ql or "avg" in ql or "mean" in ql:
            if "age" in ql:
                avg = self.db.query(func.avg(Patient.age)).scalar()
                if avg is not None:
                    lines.append(f"Average patient age: **{round(float(avg), 1)} years**")
            if "enroll" in ql:
                avg = self.db.query(func.avg(ClinicalStudy.enrollment_count)).scalar()
                if avg is not None:
                    lines.append(f"Average study enrollment: **{round(float(avg))}** participants")
            if "bmi" in ql:
                avg = self.db.query(func.avg(Patient.bmi)).scalar()
                if avg is not None:
                    lines.append(f"Average patient BMI: **{round(float(avg), 1)}**")

        if not lines:
            return []
        content = "**Aggregate result(s) computed directly from the database:**\n" + \
                  "\n".join(f"- {l}" for l in lines)
        return [{"content": content, "source": "aggregate query", "type": "sql"}]

    def _ae_filter_desc(self, filters: Dict[str, Any], query: str) -> str:
        parts = []
        if filters.get("serious_only"):
            parts.append("serious ")
        grade = self._extract_grade(query)
        if grade:
            parts.append(f"grade ≥{grade} ")
        sev = filters.get("severity")
        if sev and "grade" not in str(sev).lower():
            parts.append(f"{sev} ")
        if self._mentions_fatal(query):
            parts.append("fatal ")
        for kw in self._extract_medical_keywords(query):
            if kw in ("liver", "hepatotoxicity", "hepatic", "renal", "cardiac"):
                parts.append(f"{kw}-related ")
                break
        return "".join(parts)

    # ══════════════════════════════════════════════════════════════════════
    # Listing methods (now report the TRUE total)
    # ══════════════════════════════════════════════════════════════════════
    def _header(self, label: str, total: int, shown: int) -> str:
        if total > shown:
            return f"**{label}** ({total} total, showing {shown}):"
        return f"**{label}** ({total} found):"

    def _query_adverse_events(self, study_id=None, patient_id=None, serious_only=False,
                              severity=None, query_text="") -> List[Dict[str, Any]]:
        q = self._build_ae_query(study_id, patient_id, serious_only, severity, query_text)
        total = q.count()
        aes = q.limit(settings.sql_max_rows).all()
        if not aes:
            return []
        rows = [
            f"Patient {ae.usubjid}: {ae.aeterm} ({ae.aedecod}) | "
            f"SOC: {ae.aebodsys or 'N/A'} | "
            f"Severity: {ae.aesev or 'N/A'} | Grade: {ae.aegrade or 'N/A'} | "
            f"Serious: {ae.aeserfl or 'N/A'} | Death: {ae.aesdth or 'N/A'} | "
            f"Outcome: {ae.aeout or 'N/A'} | Related: {ae.aerel or 'N/A'} | Start: {ae.aestdtc or 'N/A'}"
            for ae in aes
        ]
        content = self._header("Adverse Events", total, len(rows)) + "\n" + "\n".join(rows)
        return [{"content": content, "source": "adverse_events table", "type": "sql", "count": total}]

    def _query_patients(self, study_id=None, patient_id=None, age_filter=None,
                        query_text="") -> List[Dict[str, Any]]:
        q = self._build_patient_query(study_id, patient_id, age_filter, query_text)
        total = q.count()
        patients = q.limit(settings.sql_max_rows).all()
        if not patients:
            return []
        rows = [
            f"Patient {p.usubjid}: Age {p.age} {p.ageu or ''} | "
            f"Sex: {p.sex} | Race: {p.race or 'N/A'} | "
            f"Diagnosis: {p.diagnosis or 'N/A'} ({p.diagcd or 'N/A'}) | "
            f"Arm: {p.arm or 'N/A'} | BMI: {p.bmi or 'N/A'} ({p.bmicat or 'N/A'}) | "
            f"Country: {p.country or 'N/A'} | Site: {p.siteid or 'N/A'}"
            for p in patients
        ]
        content = self._header("Patients", total, len(rows)) + "\n" + "\n".join(rows)
        return [{"content": content, "source": "patients table", "type": "sql", "count": total}]

    def _query_lab_results(self, patient_id=None, study_id=None, query_text="") -> List[Dict[str, Any]]:
        q = self.db.query(LabResult)
        if patient_id:
            q = q.filter(LabResult.usubjid.ilike(f"%{patient_id}%"))
        if study_id:
            q = q.filter(LabResult.studyid.ilike(f"%{study_id}%"))
        keywords = self._extract_medical_keywords(query_text)
        LAB_SHORT_CODES = {"alt", "ast", "wbc", "ldh", "cd4", "egfr", "hb"}
        if keywords and not patient_id:
            short = [k for k in keywords if k in LAB_SHORT_CODES]
            long_ = [k for k in keywords if k not in LAB_SHORT_CODES and len(k) > 3]
            conditions = [LabResult.lbtestcd.ilike(f"%{k}%") for k in short]
            conditions += [LabResult.lbtest.ilike(f"%{k}%") for k in long_]
            if conditions:
                q = q.filter(or_(*conditions))
        if not patient_id:
            q = q.filter(LabResult.lbnrind.in_(["HIGH", "LOW"]))
        total = q.count()
        labs = q.limit(settings.sql_max_rows).all()
        if not labs:
            return []
        rows = [
            f"Patient {lb.usubjid}: {lb.lbtest} ({lb.lbtestcd}) = {lb.lbstresn} {lb.lbstresu or ''} "
            f"[{lb.lbnrind}] | Ref: {lb.lbnrlo}–{lb.lbnrhi} | "
            f"Significant: {lb.lbclsig or 'N/A'} | Visit: {lb.visit or 'N/A'}"
            for lb in labs
        ]
        content = self._header("Lab Results", total, len(rows)) + "\n" + "\n".join(rows)
        return [{"content": content, "source": "lab_results table", "type": "sql", "count": total}]

    def _query_medications(self, patient_id=None, query_text="") -> List[Dict[str, Any]]:
        q = self.db.query(ConcomitantMedication)
        if patient_id:
            q = q.filter(ConcomitantMedication.usubjid.ilike(f"%{patient_id}%"))
        keywords = self._extract_medical_keywords(query_text)
        if keywords and not patient_id:
            q = q.filter(or_(*[ConcomitantMedication.cmdecod.ilike(f"%{kw}%") for kw in keywords]))
        total = q.count()
        meds = q.limit(settings.sql_max_rows).all()
        if not meds:
            return []
        rows = [
            f"Patient {m.usubjid}: {m.cmtrt} ({m.cmdecod}) | Class: {m.cmcat or 'N/A'} | "
            f"Dose: {m.cmdose or 'N/A'} | Route: {m.cmroute or 'N/A'} | "
            f"Ongoing: {m.cmongo or 'N/A'} | Indication: {m.cmreas or 'N/A'}"
            for m in meds
        ]
        content = self._header("Medications", total, len(rows)) + "\n" + "\n".join(rows)
        return [{"content": content, "source": "concomitant_medications table", "type": "sql", "count": total}]

    def _query_medical_history(self, patient_id=None, query_text="") -> List[Dict[str, Any]]:
        q = self.db.query(MedicalHistory)
        if patient_id:
            q = q.filter(MedicalHistory.usubjid.ilike(f"%{patient_id}%"))
        keywords = self._extract_medical_keywords(query_text)
        if keywords and not patient_id:
            q = q.filter(or_(*[MedicalHistory.mhterm.ilike(f"%{kw}%") for kw in keywords]))
        total = q.count()
        mhs = q.limit(settings.sql_max_rows).all()
        if not mhs:
            return []
        rows = [
            f"Patient {mh.usubjid}: {mh.mhterm} ({mh.mhdecod}) | SOC: {mh.mhbodsys or 'N/A'} | "
            f"Severity: {mh.mhsev or 'N/A'} | Ongoing: {mh.mhongo or 'N/A'} | Onset: {mh.mhstdtc or 'N/A'}"
            for mh in mhs
        ]
        content = self._header("Medical History", total, len(rows)) + "\n" + "\n".join(rows)
        return [{"content": content, "source": "medical_histories table", "type": "sql", "count": total}]

    def _query_studies(self, study_id=None, query_text="") -> List[Dict[str, Any]]:
        q = self._build_study_query(study_id, query_text)
        total = q.count()
        studies = q.limit(settings.sql_max_rows).all()
        if not studies:
            return []
        rows = [
            f"Study {s.nct_id}: {s.brief_title} | Status: {s.overall_status} | Phase: {s.phase} | "
            f"Condition: {s.conditions} | Sponsor: {s.lead_sponsor} | Enrolled: {s.enrollment_count}"
            for s in studies
        ]
        content = self._header("Clinical Studies", total, len(rows)) + "\n" + "\n".join(rows)
        return [{"content": content, "source": "clinical_studies table", "type": "sql", "count": total}]

    # ══════════════════════════════════════════════════════════════════════
    # Helpers
    # ══════════════════════════════════════════════════════════════════════
    def _apply_age_filter(self, query, age_filter: str):
        import re as _re
        age_filter = age_filter.lower().strip()
        nums = _re.findall(r'\d+', age_filter)
        if "between" in age_filter and len(nums) >= 2:
            return query.filter(Patient.age.between(float(nums[0]), float(nums[1])))
        if (">=" in age_filter or "≥" in age_filter) and nums:
            return query.filter(Patient.age >= float(nums[0]))
        if ">" in age_filter and nums:
            return query.filter(Patient.age > float(nums[0]))
        if ("<=" in age_filter or "≤" in age_filter) and nums:
            return query.filter(Patient.age <= float(nums[0]))
        if "<" in age_filter and nums:
            return query.filter(Patient.age < float(nums[0]))
        return query

    def _extract_medical_keywords(self, text: str) -> List[str]:
        stopwords = {
            "show", "list", "find", "get", "what", "which", "how", "many", "all",
            "the", "a", "an", "in", "of", "for", "and", "or", "with", "patients",
            "study", "patient", "data", "results", "give", "me", "tell", "above",
            "below", "only", "have", "had", "were", "who", "does", "count", "number",
            "total", "average", "them", "their", "they", "are", "is",
        }
        words = [w.strip(".,?!;:'\"") for w in text.lower().split()]
        LAB_SHORT_CODES = {"alt", "ast", "wbc", "ldh", "cd4", "egfr", "hb"}
        return [w for w in words if (len(w) > 3 or w in LAB_SHORT_CODES) and w not in stopwords]

    def _extract_diagnosis_keywords(self, text: str) -> List[str]:
        disease_terms = [
            "hypertension", "diabetes", "cancer", "hiv", "hepatitis", "sepsis",
            "stroke", "cardiac", "renal", "liver", "lung", "breast", "leukemia",
            "multiple sclerosis", "arthritis", "asthma", "copd", "depression",
            "alzheimer", "heart failure", "obesity", "thyroid", "epilepsy",
        ]
        text_lower = text.lower()
        return [d for d in disease_terms if d in text_lower]

    def _extract_grade(self, text: str):
        import re
        match = re.search(r'grade\s*([1-4])', text.lower())
        return int(match.group(1)) if match else None

    def _mentions_fatal(self, text: str) -> bool:
        t = (text or "").lower()
        return "fatal" in t or "death" in t or "died" in t or "deaths" in t

    def _query_mentions_ae(self, q: str) -> bool:
        return any(kw in q.lower() for kw in [
            "adverse", "event", " ae ", "toxicity", "side effect", "reaction",
            "serious", "fatal", "hospitaliz", "grade",
        ])

    def _query_mentions_patients(self, q: str) -> bool:
        import re
        q_lower = q.lower()
        keywords = ["patient", "patients", "subject", "demographic", "age", "sex",
                    "gender", "arm", "bmi", "smoke", "alcohol", "education", "country",
                    "site", "blood", "allergy"]
        if any(k in q_lower for k in keywords):
            return True
        return bool(re.search(r'\b(pat|subj)[-_]?\w+\b', q_lower))

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
            "study", "studies", "trial", "trials", "nct", "protocol", "phase",
            "sponsor", "enroll", "enrollment",
        ])
