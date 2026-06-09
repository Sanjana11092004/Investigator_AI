"""
Targeted debug for the two UI failures:
1. "no of patients above 60" — age filter not working
2. "Show SUBJ-0001 lab results" — returns empty through pipeline
"""
import sys
sys.path.insert(0, ".")

from src.rag.query_classifier import QueryClassifier
from src.database.connection import get_db_context
from src.rag.sql_retriever import SQLRetriever

clf = QueryClassifier()

print("=" * 60)
print("TEST 1: Age filter queries")
print("=" * 60)

age_queries = [
    "no of patients above 60",
    "number of patients above age 60",
    "patients above 60",
    "List all patients above age 60",
]

for q in age_queries:
    result = clf.classify(q)
    print(f"\nQuery   : {q}")
    print(f"Strategy: {result['strategy']}")
    print(f"Entities: {result['sql_entities']}")
    print(f"Filters : {result['filters']}")

print("\n" + "=" * 60)
print("TEST 2: SUBJ-0001 lab results — classifier output")
print("=" * 60)

lab_queries = [
    "Show SUBJ-0001 lab results",
    "lab results for SUBJ-0001",
    "Show SUBJ-0001 ALT values",
]

for q in lab_queries:
    result = clf.classify(q)
    print(f"\nQuery   : {q}")
    print(f"Strategy: {result['strategy']}")
    print(f"Entities: {result['sql_entities']}")
    print(f"Filters : {result['filters']}")

print("\n" + "=" * 60)
print("TEST 3: SUBJ-0001 lab results — retriever with patient_id")
print("=" * 60)

with get_db_context() as db:
    retriever = SQLRetriever(db)

    # Simulate what the classifier should produce
    classification = {
        "strategy": "sql",
        "sql_entities": ["lab_results"],
        "filters": {"patient_id": "SUBJ-0001"}
    }
    results = retriever.retrieve(classification, "Show SUBJ-0001 lab results")
    if results:
        print(f"Source : {results[0]['source']}")
        print(f"Content: {results[0]['content'][:400]}")
    else:
        print("EMPTY — checking why...")

        # Check if lbnrind filter is blocking it
        from src.database.models.lab_result import LabResult
        total = db.query(LabResult).filter(
            LabResult.usubjid.ilike("%SUBJ-0001%")
        ).count()
        abnormal = db.query(LabResult).filter(
            LabResult.usubjid.ilike("%SUBJ-0001%"),
            LabResult.lbnrind.in_(["HIGH", "LOW"])
        ).count()
        print(f"  Total lab rows for SUBJ-0001       : {total}")
        print(f"  HIGH/LOW rows for SUBJ-0001        : {abnormal}")
        print(f"  → lbnrind filter blocking? {abnormal == 0 and total > 0}")

print("\n" + "=" * 60)
print("TEST 4: Age filter — retriever direct test")
print("=" * 60)

with get_db_context() as db:
    retriever = SQLRetriever(db)

    classification = {
        "strategy": "sql",
        "sql_entities": ["patients"],
        "filters": {"age_filter": "> 60"}
    }
    results = retriever.retrieve(classification, "patients above 60")
    if results:
        print(f"Source : {results[0]['source']}")
        print(f"Content preview: {results[0]['content'][:300]}")
        # Count how many patients
        lines = results[0]['content'].split('\n')
        patient_lines = [l for l in lines if l.startswith('Patient')]
        print(f"Patients returned: {len(patient_lines)}")
    else:
        print("EMPTY")