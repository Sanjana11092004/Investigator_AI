"""
Query classifier that decides SQL vs Vector vs Hybrid retrieval.
Uses LLM to parse intent and extract filters from natural language queries.
"""
import json
from typing import Dict, Any

from loguru import logger

from src.llm.groq_client import GroqClient
from src.llm.prompt_templates import QUERY_CLASSIFIER_PROMPT


class QueryClassifier:
    """
    Classifies a user query to determine the best retrieval strategy.
    
    Returns a structured decision including:
    - strategy: sql | vector | hybrid
    - filters: extracted structured filters (study, patient, age, severity)
    - search_terms: key terms for vector search
    """

    def __init__(self):
        self.llm = GroqClient()

    def classify(self, query: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Classify a user query.
        
        Args:
            query: Natural language query from user.
            context: Session context (active study, patient, etc.).
        
        Returns:
            Classification dict with strategy and filters.
        """
        # Enrich query with context
        enriched_query = query
        if context:
            study = context.get("active_study_id")
            patient = context.get("active_patient_id")
            if study and study not in query:
                enriched_query = f"[Context: Study {study}] {query}"
            if patient and patient not in query:
                enriched_query = f"[Context: Patient {patient}] {enriched_query}"

        prompt = QUERY_CLASSIFIER_PROMPT.format(query=enriched_query)

        try:
            response, _ = self.llm.chat(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,  # Deterministic classification
                max_tokens=300,
            )

            # Parse JSON response
            clean = response.strip()
            if "```" in clean:
                clean = clean.split("```")[1].replace("json", "").strip()
            result = json.loads(clean)
            logger.info(f"CLASSIFIER RESULT: {result}")

        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Query classifier failed, defaulting to hybrid: {e}")
            result = {
                "strategy": "hybrid",
                "sql_entities": ["patients", "adverse_events"],
                "filters": {},
                "search_terms": query.split()[:5],
            }

        # Merge context filters into result
        if context:
            filters = result.setdefault("filters", {})
            if not filters.get("study_id") and context.get("active_study_id"):
                filters["study_id"] = context["active_study_id"]
            if not filters.get("patient_id") and context.get("active_patient_id"):
                filters["patient_id"] = context["active_patient_id"]

        logger.debug(f"Query classified as: {result.get('strategy')} | filters: {result.get('filters')}")
        return result