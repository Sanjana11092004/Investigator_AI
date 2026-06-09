# debug_retriever.py
import sys
sys.path.insert(0, ".")

from src.database.connection import get_db_context
from src.rag.sql_retriever import SQLRetriever

test_cases = [
    # (classification_dict, raw_query)
    (
        {"strategy": "sql", "sql_entities": ["patients"], "filters": {"patient_id": "PAT-1"}},
        "Show PAT-1 demographics"
    ),
    (
        {"strategy": "sql", "sql_entities": ["patients"], "filters": {}},
        "List all patients"
    ),
    (
        {"strategy": "sql", "sql_entities": ["adverse_events"], "filters": {"serious_only": True}},
        "Show all serious adverse events"
    ),
    (
        {"strategy": "sql", "sql_entities": ["lab_results"], "filters": {}},
        "Show abnormal lab results"
    ),
]

with get_db_context() as db:
    retriever = SQLRetriever(db)
    for classification, query in test_cases:
        print(f"\n{'='*60}")
        print(f"Query      : {query}")
        print(f"Given classification: {classification}")
        results = retriever.retrieve(classification, query)
        if results:
            for r in results:
                print(f"Source : {r['source']}")
                print(f"Content: {r['content'][:300]}")
        else:
            print("RESULT: EMPTY — nothing returned")