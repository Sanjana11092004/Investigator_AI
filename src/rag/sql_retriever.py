"""
SQL RAG Retriever — structured retrieval over the SDTM / ClinicalTrials tables.

Two modes:
  • Aggregation  ("how many ... ", "count ...", "average ...") → runs real
    COUNT / AVG queries with the requested filters applied, so the answer is exact.
  • Listing      → returns sample rows, with the TRUE total in the header
    (e.g. "Adverse Events (154 total, showing 20)") so the model never reports the
    capped row count as if it were the total.
"""
import json
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
        # The classifier's entity list is authoritative; the keyword heuristics
        # only act as a fallback when the classifier returned no entities (so a
        # "studies" question isn't polluted with AE/medical-history rows just
        # because a disease word appears).
        fb = not entities

        if "adverse_events" in entities or (fb and self._query_mentions_ae(original_query)):
            results.extend(self._query_adverse_events(
                study_id=study_id, patient_id=patient_id,
                serious_only=serious_only, severity=severity,
                query_text=original_query,
            ))

        if "patients" in entities or (fb and self._query_mentions_patients(original_query)):
            results.extend(self._query_patients(
                study_id=study_id, patient_id=patient_id,
                age_filter=age_filter, query_text=original_query,
            ))

        if "lab_results" in entities or (fb and self._query_mentions_labs(original_query)):
            results.extend(self._query_lab_results(
                patient_id=patient_id, study_id=study_id, query_text=original_query,
            ))

        if "medications" in entities or (fb and self._query_mentions_meds(original_query)):
            results.extend(self._query_medications(
                patient_id=patient_id, query_text=original_query,
            ))

        if "medical_history" in entities or (fb and self._query_mentions_mh(original_query)):
            results.extend(self._query_medical_history(
                patient_id=patient_id, query_text=original_query,
            ))

        if "studies" in entities or (fb and self._query_mentions_study(original_query)):
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
        q = self._apply_patient_categorical(q, (query_text or "").lower())
        return q

    def _apply_patient_categorical(self, q, ql: str):
        """Apply demographic/categorical filters parsed from the query text:
        sex, treatment arm, race, BMI category, smoking status."""
        import re as _re
        # sex — check 'female'/'women' before 'male' ('female' contains 'male')
        if "female" in ql or "women" in ql or "woman" in ql:
            q = q.filter(Patient.sex.ilike("F"))
        elif "male" in ql or _re.search(r'\bmen\b', ql) or "males" in ql:
            q = q.filter(Patient.sex.ilike("M"))
        # treatment arm
        if "placebo" in ql:
            q = q.filter(or_(Patient.arm.ilike("%placebo%"), Patient.actarm.ilike("%placebo%")))
        elif "treatment arm" in ql or "active arm" in ql or "active treatment" in ql or "treatment group" in ql:
            q = q.filter(or_(Patient.arm.ilike("%treat%"), Patient.actarm.ilike("%treat%")))
        # race
        for race in ["white", "asian", "black", "hispanic"]:
            if _re.search(rf'\b{race}\b', ql):
                q = q.filter(Patient.race.ilike(f"%{race}%"))
                break
        # BMI category
        if "obese" in ql or "obesity" in ql:
            q = q.filter(Patient.bmicat.ilike("%obese%"))
        elif "overweight" in ql:
            q = q.filter(Patient.bmicat.ilike("%overweight%"))
        elif "underweight" in ql:
            q = q.filter(Patient.bmicat.ilike("%underweight%"))
        elif "normal weight" in ql or "normal bmi" in ql:
            q = q.filter(Patient.bmicat.ilike("%normal%"))
        # smoking status (specific phrases only, to avoid false matches)
        if "former smoker" in ql or "ex-smoker" in ql or "ex smoker" in ql:
            q = q.filter(Patient.smokestat.ilike("%former%"))
        elif "never smoked" in ql or "non-smoker" in ql or "nonsmoker" in ql or "never smoker" in ql:
            q = q.filter(Patient.smokestat.ilike("%never%"))
        elif "current smoker" in ql:
            q = q.filter(Patient.smokestat.ilike("%current%"))
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
                    "total number", "total count", "average", "avg ", "mean ", "mean ",
                    "percentage", "what percent", "proportion of",
                    "most common", "most frequent", "most prevalent", "top ", "most ",
                    "distribution", "breakdown", "group by", "by diagnosis",
                    "by severity", "by phase", "by sex", "by arm", "by status",
                    # statistical
                    "highest", "lowest", "maximum", "minimum", "max ", "min ",
                    "oldest", "youngest", "largest", "smallest", "greatest", "median"]
        return any(t in ql for t in triggers) or ql.strip().startswith("count ")

    def _aggregate(self, filters: Dict[str, Any], entities, query: str) -> List[Dict[str, Any]]:
        ql = query.lower()
        lines: List[str] = []

        # Cross-entity decomposition ("metric X among patients with condition Y")
        cross = self._cross_entity_analytic(query)
        if cross:
            return cross

        # Statistical (mean/max/min/argmax) takes precedence
        stat = self._stat_aggregate(query)
        if stat:
            return stat

        # "most common / top / distribution" → GROUP BY breakdown
        gb = self._group_by_aggregate(ql)
        if gb:
            return gb

        study_id     = filters.get("study_id")
        patient_id   = filters.get("patient_id")
        serious_only = filters.get("serious_only", False)
        severity     = filters.get("severity")
        age_filter   = filters.get("age_filter")
        grade        = self._extract_grade(query)

        # Classifier entities are authoritative; keyword heuristics only fall back
        # when the classifier returned nothing (fb). This keeps a CSV question from
        # silently pulling in JSON 'studies' data.
        fb = not entities
        wants_patients = ("patients" in entities) or (fb and ("patient" in ql or "subject" in ql))
        wants_ae = ("adverse_events" in entities) or serious_only or severity or grade \
            or self._mentions_fatal(query) \
            or (fb and any(k in ql for k in ["adverse", "event", " ae ", "toxicity", "reaction"]))
        wants_labs = ("lab_results" in entities) \
            or (fb and any(k in ql for k in ["lab", "alt", "ast", "creatinine", "hemoglobin", "hba1c", "glucose"]))
        wants_meds = ("medications" in entities) \
            or (fb and any(k in ql for k in ["medication", "drug", "medicine", "concomitant"]))

        # 'studies' (JSON) only when explicitly requested — never from the bare word
        # "study"/"studies" if a CSV entity is already being answered.
        csv_wanted = wants_patients or wants_ae or wants_labs or wants_meds
        explicit_study = any(k in ql for k in ["nct", "trial", "sponsor", "enroll", "phase ",
                                               "clinical study", "trial design", "protocol"])
        if csv_wanted:
            wants_studies = ("studies" in entities) or explicit_study
        else:
            wants_studies = ("studies" in entities) or explicit_study or ("stud" in ql)

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
            n = pq.count()
            total = self.db.query(Patient).count()
            desc = self._patient_filter_desc(filters, query).strip()
            label = (desc[0].upper() + desc[1:] + " patients") if desc else "Patients"
            if n != total and total:
                pct = round(100.0 * n / total, 1)
                lines.append(f"{label}: **{n}** ({pct}% of the {total}-patient cohort)")
            else:
                lines.append(f"Total patients in the database: **{n}**")

        if wants_studies:
            sq = self._build_study_query(study_id, query)
            desc = self._study_filter_desc(query)
            label = (desc + "studies").strip() if desc else "Studies"
            lines.append(f"{label[0].upper() + label[1:]}: **{sq.count()}**")

        if wants_labs:
            lq = self.db.query(LabResult)
            if patient_id:
                lq = lq.filter(LabResult.usubjid.ilike(f"%{patient_id}%"))
            abnormal = ("abnormal" in ql or "high" in ql or "low" in ql or "elevated" in ql)
            if abnormal:
                lq = lq.filter(LabResult.lbnrind.in_(["HIGH", "LOW"]))
            test_label = ""
            for code in ["alt", "ast", "creatinine", "hemoglobin", "hba1c", "glucose",
                         "bilirubin", "wbc", "platelet", "albumin"]:
                if code in ql:
                    lq = lq.filter(or_(LabResult.lbtestcd.ilike(f"%{code}%"),
                                       LabResult.lbtest.ilike(f"%{code}%")))
                    test_label = code.upper() + " "
                    break
            label = (("abnormal " if abnormal else "") + test_label + "lab results").strip()
            lines.append(f"{label[0].upper() + label[1:]}: **{lq.count()}**")

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

    # ══════════════════════════════════════════════════════════════════════
    # Cross-entity query decomposition
    # ══════════════════════════════════════════════════════════════════════
    def _extract_age_filter_text(self, text: str):
        import re as _re
        t = text.lower()
        m = _re.search(r'(?:over|above|older than|greater than|>)\s*(\d+)', t)
        if m:
            return f"> {m.group(1)}"
        m = _re.search(r'(?:under|below|younger than|less than|<)\s*(\d+)', t)
        if m:
            return f"< {m.group(1)}"
        m = _re.search(r'between\s*(\d+)\s*(?:and|-|to)\s*(\d+)', t)
        if m:
            return f"between {m.group(1)} and {m.group(2)}"
        return None

    def _cohort_usubjids(self, cohort_text: str):
        """Return the set of USUBJIDs matching the cohort clause, or None if no
        recognizable condition (so the caller can fall back to a normal query)."""
        import re as _re
        ql = cohort_text.lower()
        sets = []

        # AE-based cohort conditions
        aeq = self.db.query(AdverseEvent.usubjid).distinct()
        ae_applied = False
        if "serious" in ql:
            aeq = aeq.filter(AdverseEvent.aeserfl == "Y"); ae_applied = True
        g = self._extract_grade(cohort_text)
        if g:
            aeq = aeq.filter(AdverseEvent.aegrade >= g); ae_applied = True
        if self._mentions_fatal(cohort_text):
            aeq = aeq.filter(or_(AdverseEvent.aesdth == "Y", AdverseEvent.aeout.ilike("%fatal%"))); ae_applied = True
        if any(k in ql for k in ["adverse", "event", "toxicity", "reaction", " ae "]):
            # exclude structural/flag words so we only term-match real AE names
            GENERIC = {"serious", "grade", "among", "amongst", "fatal", "death",
                       "deaths", "patients", "patient", "experienced", "having", "report"}
            terms = [t for t in self._extract_medical_keywords(cohort_text)
                     if t not in self.LAB_TERMS and t not in GENERIC]
            if terms:
                aeq = aeq.filter(or_(
                    *[AdverseEvent.aeterm.ilike(f"%{t}%") for t in terms] +
                     [AdverseEvent.aedecod.ilike(f"%{t}%") for t in terms]))
                ae_applied = True
        if ae_applied:
            sets.append({u for (u,) in aeq.all()})

        # Patient-based cohort conditions (age / sex / arm / race / diagnosis)
        pq = self.db.query(Patient.usubjid)
        p_applied = False
        age = self._extract_age_filter_text(cohort_text)
        if age:
            pq = self._apply_age_filter(pq, age); p_applied = True
        if any(w in ql for w in ["female", "male", "women", "men", "placebo", "treatment arm",
                                 "white", "asian", "black", "hispanic", "obese", "overweight"]):
            pq = self._apply_patient_categorical(pq, ql); p_applied = True
        diag = self._extract_diagnosis_keywords(cohort_text)
        if diag:
            pq = pq.filter(or_(
                *[Patient.diagnosis.ilike(f"%{d}%") for d in diag] +
                 [Patient.diagcd.ilike(f"%{d}%") for d in diag])); p_applied = True
        if p_applied:
            sets.append({u for (u,) in pq.all()})

        if not sets:
            return None
        return set.intersection(*sets) if len(sets) > 1 else sets[0]

    def _cross_entity_analytic(self, query: str):
        """Decompose 'metric X among patients with condition Y' into:
        (1) compute the cohort, (2) run the metric restricted to the cohort."""
        import re as _re
        ql = query.lower()
        m = _re.search(
            r'\b(?:among|amongst|having)\b|\bfor patients\b|\bin patients\b'
            r'|\bwho (?:have|has|had)\b|\bthat (?:have|has|had)\b|\bwith\b', ql)
        if not m:
            return None

        metric_part = query[:m.start()]
        cohort_part = query[m.start():]
        cohort = self._cohort_usubjids(cohort_part)
        if cohort is None:
            return None  # unrecognized cohort → let the normal path handle it

        words = cohort_part.strip().rstrip("?.!").split()
        fillers = {"among", "amongst", "for", "in", "who", "that", "with",
                   "having", "the", "patients", "patient"}
        while words and words[0].lower() in fillers:
            words.pop(0)
        cohort_desc = " ".join(words) or "the cohort"

        if not cohort:
            return [{"content": f"No patients match the cohort '{cohort_desc}', so the metric cannot be computed.",
                     "source": "aggregate query (decomposed)", "type": "sql"}]

        cohort = list(cohort)
        mql = metric_part.lower()
        is_max = any(k in mql for k in ["highest", "maximum", "max ", "largest", "greatest"])
        is_min = any(k in mql for k in ["lowest", "minimum", "min ", "smallest"])
        lines = [f"Cohort — patients with {cohort_desc}: **{len(cohort)} patients**"]

        code, label = self._detect_lab(mql)
        if code:
            base = self.db.query(LabResult).filter(
                LabResult.lbtestcd.ilike(code), LabResult.lbstresn.isnot(None),
                LabResult.usubjid.in_(cohort))
            n = base.count()
            if n == 0:
                lines.append(f"No {label} measurements found in this cohort.")
            else:
                ur = base.with_entities(LabResult.lbstresu).first()
                unit = ur[0] if ur and ur[0] else ""
                if is_max:
                    r = base.order_by(LabResult.lbstresn.desc()).first()
                    lines.append(f"Highest {label} in this cohort: **{r.lbstresn} {unit}** (patient {r.usubjid})")
                elif is_min:
                    r = base.order_by(LabResult.lbstresn.asc()).first()
                    lines.append(f"Lowest {label} in this cohort: **{r.lbstresn} {unit}** (patient {r.usubjid})")
                else:
                    avg = base.with_entities(func.avg(LabResult.lbstresn)).scalar()
                    lines.append(f"Mean {label} in this cohort: **{round(float(avg), 2)} {unit}** (across {n} measurements)")
        elif any(k in mql for k in ["adverse", "event", " ae "]):
            aeq = self.db.query(AdverseEvent).filter(AdverseEvent.usubjid.in_(cohort))
            srs = "serious" in mql
            if srs:
                aeq = aeq.filter(AdverseEvent.aeserfl == "Y")
            g = self._extract_grade(metric_part)
            if g:
                aeq = aeq.filter(AdverseEvent.aegrade >= g)
            lines.append(f"{'Serious ' if srs else ''}adverse-event records in this cohort: **{aeq.count()}**")
        elif "age" in mql:
            avg = self.db.query(func.avg(Patient.age)).filter(Patient.usubjid.in_(cohort)).scalar()
            if avg is not None:
                lines.append(f"Average age in this cohort: **{round(float(avg), 1)} years**")
        # else: the cohort count line is the answer

        content = "**Cross-entity result (query decomposition):**\n" + "\n".join(f"- {l}" for l in lines)
        return [{"content": content, "source": "aggregate query (decomposed)", "type": "sql"}]

    # Lab name / synonym → SDTM test code
    LAB_TERMS = {
        "sgpt": "ALT", "alt": "ALT", "sgot": "AST", "ast": "AST",
        "creatinine": "CREAT", "creat": "CREAT", "bilirubin": "BILI", "bili": "BILI",
        "albumin": "ALB", "alkaline phosphatase": "ALP", "alk phos": "ALP", "alp": "ALP",
        "ggt": "GGT", "hemoglobin": "HGB", "haemoglobin": "HGB", "hgb": "HGB",
        "wbc": "WBC", "platelet": "PLAT", "hba1c": "HBA1C", "egfr": "EGFR",
        "bun": "BUN", "cd4": "CD4", "cholesterol": "CHOL", "crp": "CRP",
        "esr": "ESR", "amylase": "AMYLASE", "bnp": "BNP", "fev1": "FEV1", "glucose": "GLUC",
    }

    def _detect_lab(self, ql: str):
        import re as _re
        for term in sorted(self.LAB_TERMS, key=len, reverse=True):
            if len(term) <= 4:                       # short codes need word boundary
                if _re.search(rf'\b{_re.escape(term)}\b', ql):
                    return self.LAB_TERMS[term], term.upper()
            elif term in ql:
                return self.LAB_TERMS[term], term.upper()
        return None, None

    def _stat_aggregate(self, query: str):
        """mean / max / min (with the argmax patient) over numeric columns:
        lab values, age, BMI, study enrollment, and study-with-most-AEs."""
        ql = query.lower()
        is_mean = any(k in ql for k in ["mean", "average", "avg"])
        is_max = any(k in ql for k in ["highest", "maximum", "max ", "largest",
                                       "greatest", "peak", "oldest", "most "])
        is_min = any(k in ql for k in ["lowest", "minimum", "min ", "smallest", "youngest"])
        if not (is_mean or is_max or is_min):
            return None

        lines = []

        # ── Lab value statistics ──
        code, label = self._detect_lab(ql)
        if code:
            base = self.db.query(LabResult).filter(
                LabResult.lbtestcd.ilike(code), LabResult.lbstresn.isnot(None))
            n = base.count()
            if n:
                ur = base.with_entities(LabResult.lbstresu).first()
                unit = (ur[0] if ur and ur[0] else "")
                if is_mean:
                    avg = base.with_entities(func.avg(LabResult.lbstresn)).scalar()
                    lines.append(f"Mean {label}: **{round(float(avg), 2)} {unit}** (across {n} measurements)")
                if is_max:
                    r = base.order_by(LabResult.lbstresn.desc()).first()
                    lines.append(f"Highest {label}: **{r.lbstresn} {unit}** — patient {r.usubjid} (visit {r.visit or 'N/A'})")
                if is_min:
                    r = base.order_by(LabResult.lbstresn.asc()).first()
                    lines.append(f"Lowest {label}: **{r.lbstresn} {unit}** — patient {r.usubjid} (visit {r.visit or 'N/A'})")

        # ── Age ──
        if "age" in ql or "oldest" in ql or "youngest" in ql:
            if is_mean and "age" in ql:
                a = self.db.query(func.avg(Patient.age)).scalar()
                if a is not None:
                    lines.append(f"Average patient age: **{round(float(a), 1)} years**")
            if is_max or "oldest" in ql:
                p = self.db.query(Patient).filter(Patient.age.isnot(None)).order_by(Patient.age.desc()).first()
                if p:
                    lines.append(f"Oldest patient: **{p.usubjid}** ({p.age} years)")
            if is_min or "youngest" in ql:
                p = self.db.query(Patient).filter(Patient.age.isnot(None)).order_by(Patient.age.asc()).first()
                if p:
                    lines.append(f"Youngest patient: **{p.usubjid}** ({p.age} years)")

        # ── BMI ──
        if "bmi" in ql:
            if is_mean:
                a = self.db.query(func.avg(Patient.bmi)).scalar()
                if a is not None:
                    lines.append(f"Average BMI: **{round(float(a), 1)}**")
            if is_max:
                p = self.db.query(Patient).filter(Patient.bmi.isnot(None)).order_by(Patient.bmi.desc()).first()
                if p:
                    lines.append(f"Highest BMI: **{p.bmi}** — patient {p.usubjid}")

        # ── Study enrollment ──
        if "enroll" in ql:
            if is_mean:
                a = self.db.query(func.avg(ClinicalStudy.enrollment_count)).scalar()
                if a is not None:
                    lines.append(f"Average study enrollment: **{round(float(a))}** participants")
            if is_max:
                s = (self.db.query(ClinicalStudy).filter(ClinicalStudy.enrollment_count.isnot(None))
                     .order_by(ClinicalStudy.enrollment_count.desc()).first())
                if s:
                    lines.append(f"Largest enrollment: **{s.enrollment_count}** — {s.nct_id} ({s.brief_title})")

        # ── Study with the most (serious) adverse events ──
        if ("study" in ql or "studies" in ql) and any(k in ql for k in ["adverse", "serious", " ae "]):
            q = self.db.query(AdverseEvent.studyid, func.count(AdverseEvent.id))
            serious = "serious" in ql
            if serious:
                q = q.filter(AdverseEvent.aeserfl == "Y")
            rows = q.group_by(AdverseEvent.studyid).order_by(func.count(AdverseEvent.id).desc()).limit(5).all()
            if rows:
                top = rows[0]
                lines.append(f"Study with the most {'serious ' if serious else ''}adverse events: "
                             f"**{top[0]}** ({top[1]} events)")

        if not lines:
            return None
        content = "**Statistical result(s) computed directly from the database:**\n" + \
                  "\n".join(f"- {l}" for l in lines)
        return [{"content": content, "source": "aggregate query", "type": "sql"}]

    def _group_by_aggregate(self, ql: str):
        """Handle 'most common / top / distribution / breakdown by X' via GROUP BY."""
        if not any(k in ql for k in ["most common", "most frequent", "most prevalent",
                                     "top ", "distribution", "breakdown", "group by",
                                     "by diagnosis", "by severity", "by phase",
                                     "by sex", "by arm", "by status"]):
            return None

        def run(col, model, limit=8):
            rows = (self.db.query(col, func.count(model.id))
                    .group_by(col).order_by(func.count(model.id).desc()).limit(limit).all())
            return [(v if v not in (None, "") else "N/A", c) for v, c in rows]

        def fmt(label, rows):
            return f"{label}: " + ", ".join(f"{v} ({c})" for v, c in rows)

        lines = []
        if any(k in ql for k in ["diagnos", "condition", "disease"]):
            lines.append(fmt("Patients by diagnosis (most common first)",
                             run(Patient.diagnosis, Patient)))
        if "sex" in ql or "gender" in ql:
            lines.append(fmt("Patients by sex", run(Patient.sex, Patient)))
        if "arm" in ql or "treatment group" in ql:
            lines.append(fmt("Patients by study arm", run(Patient.arm, Patient)))
        if "severity" in ql:
            lines.append(fmt("Adverse events by severity", run(AdverseEvent.aesev, AdverseEvent)))
        if any(k in ql for k in ["adverse", "event", " ae "]) and "severity" not in ql:
            lines.append(fmt("Adverse events by type (most common first)",
                             run(AdverseEvent.aedecod, AdverseEvent)))
        if "phase" in ql:
            lines.append(fmt("Studies by phase", run(ClinicalStudy.phase, ClinicalStudy)))
        if "status" in ql:
            lines.append(fmt("Studies by status", run(ClinicalStudy.overall_status, ClinicalStudy)))
        if any(k in ql for k in ["medication", "drug", "medicine"]):
            lines.append(fmt("Medications by type (most common first)",
                             run(ConcomitantMedication.cmdecod, ConcomitantMedication)))

        if not lines:
            return None
        content = "**Breakdown computed directly from the database:**\n" + \
                  "\n".join(f"- {l}" for l in lines)
        return [{"content": content, "source": "aggregate query", "type": "sql"}]

    def _study_filter_desc(self, query: str) -> str:
        import re as _re
        ql = query.lower()
        parts = []
        for st in ["completed", "recruiting", "terminated", "withdrawn",
                   "active", "suspended", "enrolling"]:
            if st in ql:
                parts.append(st + " ")
                break
        ph = _re.search(r'phase\s*([1-4])', ql)
        if ph:
            parts.append(f"phase-{ph.group(1)} ")
        return "".join(parts)

    def _patient_filter_desc(self, filters: Dict[str, Any], query: str) -> str:
        """Human-readable label of the patient filters in the query, so the
        aggregate count is unambiguous (e.g. 'female placebo-arm')."""
        import re as _re
        ql = query.lower()
        parts = []
        if "female" in ql or "women" in ql or "woman" in ql:
            parts.append("female ")
        elif "male" in ql or _re.search(r'\bmen\b', ql):
            parts.append("male ")
        if "placebo" in ql:
            parts.append("placebo-arm ")
        elif any(k in ql for k in ["treatment arm", "active arm", "active treatment", "treatment group"]):
            parts.append("treatment-arm ")
        for race in ["white", "asian", "black", "hispanic"]:
            if _re.search(rf'\b{race}\b', ql):
                parts.append(f"{race} ")
                break
        if "obese" in ql or "obesity" in ql:
            parts.append("obese ")
        elif "overweight" in ql:
            parts.append("overweight ")
        af = filters.get("age_filter")
        if af:
            parts.append(f"age {af} ")
        for d in self._extract_diagnosis_keywords(query):
            parts.append(f"{d} ")
            break
        return "".join(parts)

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
        # Keyword match on conditions / title / summary so cross-study reasoning
        # ("summarize studies about hepatotoxicity") retrieves the right studies.
        kws = self._study_keywords(query_text)
        if kws:
            kq = q.filter(or_(
                *[ClinicalStudy.conditions.ilike(f"%{k}%") for k in kws] +
                 [ClinicalStudy.brief_title.ilike(f"%{k}%") for k in kws] +
                 [ClinicalStudy.brief_summary.ilike(f"%{k}%") for k in kws]))
            if kq.count() > 0:        # only narrow if it actually matches something
                q = kq
        total = q.count()
        # A specific study (filtered by id/keyword down to a few) gets DEEP detail
        # pulled from raw_json; broad cross-study queries stay summary-only (token budget).
        specific = bool(study_id) or total <= 2
        limit = 3 if specific else min(settings.sql_max_rows, 8)
        studies = q.limit(limit).all()
        if not studies:
            return []
        rows = []
        for s in studies:
            summ = (s.brief_summary or "").strip().replace("\n", " ")
            if len(summ) > (600 if specific else 260):
                summ = summ[: (600 if specific else 260)] + "…"
            block = (f"Study {s.nct_id}: {s.brief_title} | Status: {s.overall_status} | "
                     f"Phase: {s.phase} | Conditions: {s.conditions} | Sponsor: {s.lead_sponsor} | "
                     f"Enrolled: {s.enrollment_count}\n  Summary: {summ or 'N/A'}")
            if specific:
                detail = self._study_detail(s.raw_json)
                if detail:
                    block += "\n  " + detail
            rows.append(block)
        content = self._header("Clinical Studies", total, len(rows)) + "\n" + "\n\n".join(rows)
        return [{"content": content, "source": "clinical_studies table", "type": "sql", "count": total}]

    def _study_detail(self, raw_json) -> str:
        """Extract deep narrative fields from a study's stored raw JSON so the LLM
        can answer detailed questions (eligibility, outcomes, interventions, arms)."""
        if not raw_json:
            return ""
        try:
            data = json.loads(raw_json)
        except Exception:
            return ""
        proto = data.get("protocolSection", {})
        parts = []
        dd = (proto.get("descriptionModule", {}) or {}).get("detailedDescription")
        if dd:
            parts.append("Detailed description: " + dd[:600])
        elig = (proto.get("eligibilityModule", {}) or {}).get("eligibilityCriteria")
        if elig:
            parts.append("Eligibility: " + elig.replace("\n", " ")[:500])
        om = proto.get("outcomesModule", {}) or {}
        prim = om.get("primaryOutcomes", []) or []
        if prim:
            parts.append("Primary outcomes: " + "; ".join(o.get("measure", "") for o in prim[:4]))
        sec = om.get("secondaryOutcomes", []) or []
        if sec:
            parts.append("Secondary outcomes: " + "; ".join(o.get("measure", "") for o in sec[:3]))
        arms = proto.get("armsInterventionsModule", {}) or {}
        ints = arms.get("interventions", []) or []
        if ints:
            parts.append("Interventions: " + "; ".join(
                f"{i.get('type', '')}: {i.get('name', '')}" for i in ints[:5]))
        armg = arms.get("armGroups", []) or []
        if armg:
            parts.append("Arms: " + "; ".join(a.get("label", "") for a in armg[:5]))
        return "\n  ".join(parts)

    def _study_keywords(self, text: str) -> List[str]:
        """Content keywords for matching studies — excludes reasoning verbs so a
        question like 'summarize efficacy across studies' doesn't filter on
        'summarize' / 'efficacy' and return nothing."""
        REASONING = {
            "summarize", "summary", "summarise", "compare", "comparison", "trend",
            "trends", "efficacy", "risk", "across", "overview", "analyze", "analyse",
            "analysis", "describe", "reported", "incidence", "pattern", "patterns",
            "generate", "between", "highest", "lowest", "common", "studies", "study",
            "trial", "trials", "overall", "various", "different", "treatment",
        }
        return [w for w in self._extract_medical_keywords(text) if w not in REASONING]

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
            "total", "average", "them", "their", "they", "are", "is", "there",
            # generic category words — these name a TABLE, not a specific term to match
            "adverse", "event", "events", "reaction", "reactions", "effect", "effects",
            "medication", "medications", "medicine", "medicines", "drug", "drugs",
            "concomitant", "lab", "labs", "laboratory", "test", "tests", "result",
            "record", "records", "trial", "trials", "studies", "value", "values",
            "enrolled", "assigned", "primary", "report", "reported", "cohort",
            "database", "across", "much", "were", "was",
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
