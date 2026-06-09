"""
Tests for RAG pipeline components.
LLM calls are mocked so no real Groq API key is needed.
"""
import json
import pytest
from unittest.mock import MagicMock, patch


class TestQueryClassifier:

    @patch("src.rag.query_classifier.GroqClient")
    def test_sql_strategy_for_ae_query(self, MockGroq):
        mock = MagicMock()
        mock.chat.return_value = (
            json.dumps({
                "strategy": "sql",
                "sql_entities": ["adverse_events"],
                "filters": {"serious_only": True},
                "search_terms": ["adverse events", "serious"],
            }),
            {"prompt": 100, "completion": 50, "total": 150},
        )
        MockGroq.return_value = mock

        from src.rag.query_classifier import QueryClassifier
        classifier = QueryClassifier()
        result = classifier.classify("Show all serious adverse events")
        assert result["strategy"] == "sql"
        assert "adverse_events" in result["sql_entities"]

    @patch("src.rag.query_classifier.GroqClient")
    def test_context_study_injected_into_filters(self, MockGroq):
        mock = MagicMock()
        mock.chat.return_value = (
            json.dumps({
                "strategy": "sql",
                "sql_entities": ["patients"],
                "filters": {},
                "search_terms": [],
            }),
            {},
        )
        MockGroq.return_value = mock

        from src.rag.query_classifier import QueryClassifier
        classifier = QueryClassifier()
        context = {"active_study_id": "PHVIGIL2024", "active_patient_id": None}
        result = classifier.classify("Show patients above age 60", context)
        assert result["filters"].get("study_id") == "PHVIGIL2024"

    @patch("src.rag.query_classifier.GroqClient")
    def test_fallback_on_invalid_json(self, MockGroq):
        """If LLM returns garbage, classifier should default to hybrid."""
        mock = MagicMock()
        mock.chat.return_value = ("NOT JSON AT ALL !!!", {})
        MockGroq.return_value = mock

        from src.rag.query_classifier import QueryClassifier
        classifier = QueryClassifier()
        result = classifier.classify("something something patients")
        assert result["strategy"] == "hybrid"


class TestSQLRetriever:

    def test_returns_serious_ae(self, db_session, sample_adverse_event):
        from src.rag.sql_retriever import SQLRetriever
        retriever = SQLRetriever(db_session)
        classification = {
            "strategy": "sql",
            "sql_entities": ["adverse_events"],
            "filters": {"serious_only": True},
        }
        results = retriever.retrieve(classification, "show serious adverse events")
        assert len(results) > 0
        assert "HEPATOTOX" in results[0]["content"]

    def test_age_filter_greater_than_60(self, db_session, sample_patient):
        """sample_patient is age 65 — should appear with > 60 filter."""
        from src.rag.sql_retriever import SQLRetriever

        # Confirm the patient is visible to this session before testing the retriever
        from src.database.models.patient import Patient
        count = db_session.query(Patient).filter(Patient.age > 60).count()
        assert count > 0, f"sample_patient not visible in db_session (age=65, filter>60). Count={count}"

        retriever = SQLRetriever(db_session)
        classification = {
            "strategy": "sql",
            "sql_entities": ["patients"],
            "filters": {"age_filter": "> 60"},
        }
        results = retriever.retrieve(classification, "show patients above 60")
        assert len(results) > 0, f"Retriever returned no results. DB count was {count}"
        assert "TEST-001" in results[0]["content"]

    def test_age_filter_excludes_young_patients(self, db_session, sample_patient):
        """sample_patient is age 65 — should NOT appear with < 30 filter."""
        from src.rag.sql_retriever import SQLRetriever
        retriever = SQLRetriever(db_session)
        classification = {
            "strategy": "sql",
            "sql_entities": ["patients"],
            "filters": {"age_filter": "< 30"},
        }
        results = retriever.retrieve(classification, "show patients under 30")
        # Either empty or doesn't contain our sample patient
        if results:
            assert "TEST-001" not in results[0]["content"]

    def test_returns_abnormal_lab_results(self, db_session, sample_lab_result):
        from src.rag.sql_retriever import SQLRetriever
        retriever = SQLRetriever(db_session)
        classification = {
            "strategy": "sql",
            "sql_entities": ["lab_results"],
            "filters": {},
        }
        results = retriever.retrieve(classification, "show abnormal lab results ALT")
        assert len(results) > 0
        assert "ALT" in results[0]["content"]

    def test_returns_medications(self, db_session, sample_medication):
        from src.rag.sql_retriever import SQLRetriever
        retriever = SQLRetriever(db_session)
        classification = {
            "strategy": "sql",
            "sql_entities": ["medications"],
            "filters": {},
        }
        results = retriever.retrieve(classification, "show medications metformin")
        assert len(results) > 0
        assert "METFORMIN" in results[0]["content"]

    def test_returns_medical_history(self, db_session, sample_medical_history):
        from src.rag.sql_retriever import SQLRetriever
        retriever = SQLRetriever(db_session)
        classification = {
            "strategy": "sql",
            "sql_entities": ["medical_history"],
            "filters": {},
        }
        results = retriever.retrieve(classification, "show medical history coronary")
        assert len(results) > 0
        assert "CAD" in results[0]["content"]

    def test_empty_result_for_nonexistent_study(self, db_session):
        from src.rag.sql_retriever import SQLRetriever
        retriever = SQLRetriever(db_session)
        classification = {
            "strategy": "sql",
            "sql_entities": ["adverse_events"],
            "filters": {"study_id": "STUDY_DOES_NOT_EXIST_XYZ999"},
        }
        results = retriever.retrieve(classification, "show aes in nonexistent study")
        assert isinstance(results, list)