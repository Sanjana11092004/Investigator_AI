"""
Query classifier that decides SQL vs Vector vs Hybrid retrieval.
Uses LLM to parse intent and extract filters from natural language queries.
"""
import json
import re
from typing import Dict, Any

from loguru import logger

from src.llm.groq_client import GroqClient
from src.llm.prompt_templates import QUERY_CLASSIFIER_PROMPT


class QueryClassifier:
    """
    Classifies a user query to determine the best retrieval strategy.

    Returns a structured decision including:
    - strategy: sql | vector | hybrid
    - sql_entities: list of tables to query (in priority order)
    - filters: extracted structured filters (study, patient, age, severity)
    - search_terms: key terms for vector search
    """

    # Matches: SUBJ-0001, SUBJ001, PAT-1, PAT001, API-DM-001, DM-001
    # Requires at least one digit so plain words like "patients" are never captured.
    _PATIENT_ID_RE = re.compile(
        r'\b(?:SUBJ|PAT|API[-_]?DM|DM)[-_]?\w*\d\w*\b',
        re.IGNORECASE,
    )

    def __init__(self):
        self.llm = GroqClient()

    # ──────────────────────────────────────────────────────────────────────
    def classify(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Classify a user query.

        Args:
            query: Natural language query from user.
            context: Session context (active study, patient, etc.).

        Returns:
            Classification dict with strategy, sql_entities, and filters.
        """
        context = context or {}

        # ── 1. Pull patient_id from raw query text before calling LLM ──
        patient_id_from_query = self._extract_patient_id(query)

        # ── 2. Enrich query string with session context ──
        enriched_query = query
        active_study   = context.get("active_study_id")
        active_patient = context.get("active_patient_id") or patient_id_from_query
        if active_study and active_study not in query:
            enriched_query = f"[Context: Study {active_study}] {enriched_query}"
        if active_patient and active_patient not in query:
            enriched_query = f"[Context: Patient {active_patient}] {enriched_query}"

        # ── 3. Call LLM classifier ──
        prompt = QUERY_CLASSIFIER_PROMPT.format(query=enriched_query)
        try:
            response, _ = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=400,
            )
            clean = response.strip()
            if "```" in clean:
                clean = clean.split("```")[1].replace("json", "").strip()
            result = json.loads(clean)
            logger.info(f"CLASSIFIER RESULT (raw): {result}")

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Query classifier failed, using rule-based fallback: {e}")
            result = self._rule_based_classify(query)

        # ── 4. Post-process: ensure sql_entities is in the right priority order ──
        result["sql_entities"] = self._reorder_entities(
            result.get("sql_entities", []),
            query,
        )

        # ── 5. Merge filters ──
        filters = result.setdefault("filters", {})

        # Validate a candidate patient_id — must contain at least one digit
        # so plain words like 'patients' or 'subjects' are never used as IDs.
        def _is_valid_patient_id(val):
            return bool(val and any(c.isdigit() for c in str(val)))

        # Inject patient_id from raw query text (highest confidence),
        # then session context — only if it looks like a real ID.
        if not filters.get("patient_id"):
            if _is_valid_patient_id(patient_id_from_query):
                filters["patient_id"] = patient_id_from_query
            elif _is_valid_patient_id(active_patient):
                filters["patient_id"] = active_patient
            # else: leave as null — do not filter by patient

        if not filters.get("study_id") and active_study:
            filters["study_id"] = active_study

        logger.info(
            f"CLASSIFIER FINAL → strategy={result.get('strategy')} | "
            f"entities={result.get('sql_entities')} | filters={filters}"
        )
        return result

    # ──────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────

    def _extract_patient_id(self, text: str) -> str | None:
        """Extract a patient/subject ID directly from raw query text."""
        match = self._PATIENT_ID_RE.search(text)
        return match.group(0) if match else None

    def _reorder_entities(self, entities: list, query: str) -> list:
        """
        Enforce priority order: patients > labs > medications > medical_history
        > adverse_events > studies.

        - Removes 'studies' if other specific entities are present.
        - Ensures studies is always last.
        """
        q = query.lower()
        priority = [
            "patients",
            "lab_results",
            "medications",
            "medical_history",
            "adverse_events",
            "studies",
        ]

        # Deduplicate while keeping order
        seen = set()
        ordered = []
        for p in priority:
            if p in entities and p not in seen:
                ordered.append(p)
                seen.add(p)

        # If we have specific clinical entities, drop 'studies' unless query
        # explicitly asks about a study/trial/NCT
        specific = {"patients", "lab_results", "medications", "medical_history", "adverse_events"}
        if specific.intersection(ordered):
            study_explicit = any(kw in q for kw in [
                "nct", "trial", "phase", "sponsor", "enroll",
                "study design", "protocol", "clinical study",
            ])
            if not study_explicit and "studies" in ordered:
                ordered.remove("studies")

        return ordered if ordered else entities

    def _rule_based_classify(self, query: str) -> Dict[str, Any]:
        """
        Fallback: pure keyword-based classification when LLM call fails.
        Mirrors the priority in SQLRetriever._query_mentions_* helpers.
        """
        q = query.lower()
        entities = []

        # Patient signals
        if (
            self._PATIENT_ID_RE.search(query)
            or any(kw in q for kw in [
                "patient", "subject", "demographic", "age", "sex", "gender",
                "race", "ethnic", "arm", "bmi", "smoke", "alcohol", "blood group",
                "blood type", "allergy",
            ])
        ):
            entities.append("patients")

        # Lab signals
        if any(kw in q for kw in [
            "lab", "result", "alt", "ast", "wbc", "creatinine", "hemoglobin",
            "hba1c", "cd4", "glucose", "liver enzyme", "kidney", "abnormal",
        ]):
            entities.append("lab_results")

        # Medication signals
        if any(kw in q for kw in [
            "medication", "drug", "medicine", "treatment", "concomitant",
            "dose", "route", "metformin", "pembrolizumab",
        ]):
            entities.append("medications")

        # Medical history signals
        if any(kw in q for kw in [
            "history", "comorbid", "prior", "previous condition",
            "diagnosed", "chronic",
        ]):
            entities.append("medical_history")

        # AE signals
        if any(kw in q for kw in [
            "adverse", "event", "toxicity", "side effect", "reaction",
            "serious", "fatal", "hospitaliz", "grade",
        ]):
            entities.append("adverse_events")

        # Study signals — only if nothing more specific matched
        if not entities or any(kw in q for kw in [
            "nct", "trial design", "phase", "sponsor", "enroll", "protocol",
        ]):
            entities.append("studies")

        strategy = "vector" if any(kw in q for kw in [
            "narrative", "report", "pdf", "document", "describe",
        ]) else "sql"

        return {
            "strategy": strategy,
            "sql_entities": entities or ["patients", "adverse_events"],
            "filters": {},
            "search_terms": query.split()[:5],
        }