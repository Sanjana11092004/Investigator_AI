"""
Run this first — zero dependencies, instant feedback.
Tells you exactly which ID formats the regex will and won't catch.
"""
import re

PATIENT_ID_RE = re.compile(
    r'\b(?:SUBJ|PAT|API[-_]?DM|DM)[-_]?\w*\d\w*\b',
    re.IGNORECASE,
)

test_cases = [
    # (query_text, should_match, expected_id)
    ("Show SUBJ-0001 demographics",          True,  "SUBJ-0001"),
    ("Show SUBJ0001 demographics",           True,  "SUBJ0001"),
    ("Show PAT-1 demographics",              True,  "PAT-1"),
    ("Show PAT001 demographics",             True,  "PAT001"),
    ("Show API-DM-001 demographics",         True,  "API-DM-001"),
    ("List all patients above age 60",       False, None),
    ("Show all patients",                    False, None),
    ("How many subjects are in the study",   False, None),
    ("Show subject demographics",            False, None),
]

print(f"{'Query':<45} {'Expected':<10} {'Got':<15} {'Pass?'}")
print("-" * 85)
all_pass = True
for query, should_match, expected in test_cases:
    match = PATIENT_ID_RE.search(query)
    got = match.group(0) if match else None
    passed = (got == expected)
    all_pass = all_pass and passed
    status = "✓" if passed else "✗ FAIL"
    print(f"{query:<45} {str(expected):<10} {str(got):<15} {status}")

print()
print("All tests passed ✓" if all_pass else "Some tests FAILED ✗ — regex needs adjustment")

# Also print what your actual DB IDs would match against
print("\n--- Testing your actual DB ID format ---")
db_ids = ["SUBJ-0001", "SUBJ-0002", "SUBJ-0010"]
for id_ in db_ids:
    query = f"Show {id_} demographics"
    match = PATIENT_ID_RE.search(query)
    print(f"Query: '{query}' → extracted: {match.group(0) if match else 'NONE'}")