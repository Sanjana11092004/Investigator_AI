# debug_classifier.py
import sys
sys.path.insert(0, ".")

from src.rag.query_classifier import QueryClassifier

clf = QueryClassifier()

test_queries = [
    "Show PAT-1 demographics",
    "Show API-DM-001 demographics",
    "Show SUBJ001 demographics",
    "List all patients above age 60",
    "Show all serious adverse events",
    "What is the phase of the study?",
]

for q in test_queries:
    result = clf.classify(q)
    print(f"\nQuery   : {q}")
    print(f"Strategy: {result['strategy']}")
    print(f"Entities: {result['sql_entities']}")
    print(f"Filters : {result['filters']}")