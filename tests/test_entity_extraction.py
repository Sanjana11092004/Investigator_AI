"""Tests for clinical entity extraction — no DB needed."""
import pytest
from src.entity_extraction.extractor import EntityExtractor


@pytest.fixture(scope="module")
def extractor():
    return EntityExtractor()


class TestEntityExtractor:

    def test_extracts_patient_ids(self, extractor):
        text = "Patient SUBJ-001 experienced hepatotoxicity. Subject PHVIGIL2024-TEST-042 also had nausea."
        entities = extractor.extract(text)
        assert len(entities["patients"]) > 0

    def test_extracts_nct_study_id(self, extractor):
        text = "Study NCT01234567 enrolled 200 patients with Hypertension."
        entities = extractor.extract(text)
        assert any("NCT" in s for s in entities["studies"])

    def test_extracts_severity_grade(self, extractor):
        text = "The patient had a Grade 3 SEVERE adverse event requiring hospitalisation."
        entities = extractor.extract(text)
        combined = " ".join(entities["adverse_events"]).upper()
        assert "GRADE" in combined or "SEVERE" in combined

    def test_extracts_lab_tests(self, extractor):
        text = "ALT was elevated to 120 U/L. AST and creatinine were within normal limits."
        entities = extractor.extract(text)
        lab_text = " ".join(entities["lab_tests"]).upper()
        assert "ALT" in lab_text or "AST" in lab_text

    def test_extracts_outcomes(self, extractor):
        text = "The patient recovered after treatment. One subject had a fatal outcome."
        entities = extractor.extract(text)
        outcome_text = " ".join(entities["outcomes"]).lower()
        assert "recovered" in outcome_text or "fatal" in outcome_text

    def test_empty_text_returns_empty_lists(self, extractor):
        entities = extractor.extract("")
        for key in entities:
            assert isinstance(entities[key], list)
            assert len(entities[key]) == 0

    def test_deduplication(self, extractor):
        text = "SUBJ-001 had nausea. SUBJ-001 also had vomiting. SUBJ-001 recovered fully."
        entities = extractor.extract(text)
        for val in entities["patients"]:
            assert entities["patients"].count(val) == 1

    def test_returns_all_expected_keys(self, extractor):
        entities = extractor.extract("test")
        expected_keys = {"patients", "drugs", "adverse_events", "studies", "lab_tests", "diagnoses", "outcomes"}
        assert set(entities.keys()) == expected_keys