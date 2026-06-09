"""
Clinical entity extractor using spaCy + scispaCy.
Extracts: patients, drugs, adverse events, studies, diagnoses, lab tests.
"""
import json
from typing import Dict, Any, List
from functools import lru_cache

import spacy
from loguru import logger


@lru_cache(maxsize=1)
def _load_nlp():
    """Load spaCy model once and cache it."""
    try:
        nlp = spacy.load("en_core_sci_sm")  # scispaCy biomedical model
        logger.info("Loaded scispaCy model: en_core_sci_sm")
    except OSError:
        try:
            nlp = spacy.load("en_core_web_sm")  # fallback
            logger.warning("scispaCy not found, using en_core_web_sm fallback")
        except OSError:
            logger.error("No spaCy model found. Run: python -m spacy download en_core_web_sm")
            return None
    return nlp


class EntityExtractor:
    """
    Extracts clinical entities from text using spaCy NER + rule-based patterns.

    Identified entity categories:
    - patients: subject IDs (e.g. SUBJ001, USUBJID patterns)
    - drugs: medication names
    - adverse_events: AE terms
    - studies: study identifiers
    - lab_tests: lab test names
    - diagnoses: disease/condition mentions
    """

    # Common clinical stopwords to filter noise
    STOPWORDS = {
        "the", "a", "an", "in", "of", "for", "and", "or", "with",
        "to", "from", "at", "by", "is", "are", "was", "were",
        "study", "patient", "result", "data", "show", "find",
    }

    def extract(self, text: str) -> Dict[str, List[str]]:
        """
        Extract entities from text.

        Args:
            text: Input text (query + response combined for richer extraction).

        Returns:
            Dict of entity categories → list of unique values.
        """
        entities: Dict[str, List[str]] = {
            "patients": [],
            "drugs": [],
            "adverse_events": [],
            "studies": [],
            "lab_tests": [],
            "diagnoses": [],
            "outcomes": [],
        }

        if not text:
            return entities

        # Rule-based extraction (fast, reliable for structured patterns)
        entities = self._rule_based_extract(text, entities)

        # NLP-based extraction
        nlp = _load_nlp()
        if nlp:
            entities = self._nlp_extract(text, entities, nlp)

        # Deduplicate all lists
        for key in entities:
            entities[key] = list(dict.fromkeys(
                [e.strip() for e in entities[key] if e.strip() and e.lower() not in self.STOPWORDS]
            ))

        return entities

    def _rule_based_extract(self, text: str, entities: Dict) -> Dict:
        """
        Use regex patterns to extract structured clinical identifiers.
        """
        import re

        # Patient IDs: SUBJ001, USUBJID patterns, subject identifiers
        patient_patterns = [
            r'\b[A-Z]{1,6}-?\d{3,6}\b',         # e.g. SUBJ001, PT-0012
            r'\bUSUBJID[:\s]+([A-Z0-9\-]+)\b',   # USUBJID: XXX
            r'\bpatient\s+([A-Z0-9\-]+)\b',       # "patient SUBJ001"
            r'\bsubject\s+([A-Z0-9\-]+)\b',       # "subject 001"
        ]
        for pat in patient_patterns:
            matches = re.findall(pat, text, re.IGNORECASE)
            entities["patients"].extend(matches)

        # Study IDs: NCT numbers, study codes
        study_patterns = [
            r'\bNCT\d{8}\b',                      # ClinicalTrials NCT ID
            r'\b[A-Z]{2,6}-\d{3,5}\b',            # e.g. ABC-101
            r'\bStudy\s+([A-Z0-9\-]+)\b',         # "Study ABC-101"
        ]
        for pat in study_patterns:
            matches = re.findall(pat, text, re.IGNORECASE)
            entities["studies"].extend(matches)

        # Severity/grade patterns
        ae_patterns = [
            r'Grade\s+[1-4]\b',
            r'\b(MILD|MODERATE|SEVERE|LIFE.THREATENING)\b',
            r'\bSAE\b',
            r'\bserious adverse event\b',
        ]
        for pat in ae_patterns:
            matches = re.findall(pat, text, re.IGNORECASE)
            entities["adverse_events"].extend(matches)

        # Common lab tests
        lab_keywords = [
            "ALT", "AST", "ASAT", "ALAT", "creatinine", "hemoglobin", "WBC",
            "platelet", "bilirubin", "albumin", "glucose", "sodium", "potassium",
            "ALK PHOS", "GGT", "LDH", "HbA1c", "eGFR",
        ]
        for kw in lab_keywords:
            if kw.lower() in text.lower():
                entities["lab_tests"].append(kw)

        # Outcomes
        outcome_keywords = [
            "recovered", "resolved", "fatal", "death", "ongoing", "improved",
            "worsened", "hospitalization", "disability",
        ]
        for kw in outcome_keywords:
            if kw.lower() in text.lower():
                entities["outcomes"].append(kw)

        return entities

    def _nlp_extract(self, text: str, entities: Dict, nlp) -> Dict:
        """
        Use spaCy NER to extract additional entities.
        Maps spaCy entity types to our clinical categories.
        """
        # Truncate to avoid memory issues
        doc = nlp(text[:5000])

        for ent in doc.ents:
            label = ent.label_.upper()
            value = ent.text.strip()

            if len(value) < 2:
                continue

            # scispaCy labels
            if label in ["CHEMICAL", "SIMPLE_CHEMICAL"]:
                entities["drugs"].append(value)
            elif label in ["DISEASE", "DISORDER", "SIGN_OR_SYMPTOM"]:
                entities["diagnoses"].append(value)
            elif label in ["CLINICAL_VARIABLE", "LAB_VALUE"]:
                entities["lab_tests"].append(value)
            # General spaCy fallback labels
            elif label in ["ORG"] and any(
                kw in value.lower() for kw in ["trial", "study", "nct"]
            ):
                entities["studies"].append(value)

        return entities


class RelationshipMapper:
    """
    Maps relationships between extracted entities.
    E.g., Patient → Drug → Adverse Event chains.
    """

    def map_relationships(
        self,
        entities: Dict[str, List[str]],
        context: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        """
        Build entity relationship triples from extracted entities + context.

        Returns:
            List of {subject, relation, object} triples.
        """
        relationships = []

        study = context.get("active_study_id")
        patient = context.get("active_patient_id")

        for p in entities.get("patients", []):
            if study:
                relationships.append({
                    "subject": p,
                    "relation": "enrolled_in",
                    "object": study,
                })
            for ae in entities.get("adverse_events", []):
                relationships.append({
                    "subject": p,
                    "relation": "experienced",
                    "object": ae,
                })
            for drug in entities.get("drugs", []):
                relationships.append({
                    "subject": p,
                    "relation": "received",
                    "object": drug,
                })

        for drug in entities.get("drugs", []):
            for ae in entities.get("adverse_events", []):
                relationships.append({
                    "subject": drug,
                    "relation": "associated_with",
                    "object": ae,
                })

        return relationships