# debug_pipeline.py
import sys
sys.path.insert(0, ".")

import logging
logging.basicConfig(level=logging.DEBUG)

from src.database.connection import get_db_context
from src.rag.rag_pipeline import RAGPipeline

with get_db_context() as db:
    pipeline = RAGPipeline(db)
    # debug_pipeline.py — change the question to a real ID
    result = pipeline.query(
        question="List all patients above age 60",
        conversation_history=[],
        session_context={},
    )
    print("\n=== ANSWER ===")
    print(result["answer"])
    print("\n=== SOURCES ===")
    print(result["sources"])