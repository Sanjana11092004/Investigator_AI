"""
Build the unified JSON store from the current database + vector store.

    python -m scripts.build_json_store

Writes json_store/{demographics,adverse_events,labs,medications,
medical_history,studies,narratives}.json plus index.json (a metadata-only
catalog of every document). The SQL/vector engine stays the query engine; this
is the standardized, metadata-rich representation of all sources.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from loguru import logger
from src.database.connection import get_db_context
from src.json_store.exporter import JSONStoreExporter


def main():
    logger.info("Building unified JSON store…")
    with get_db_context() as db:
        result = JSONStoreExporter(db).export()
    logger.info(f"Done → {result['out_dir']}")
    logger.info(f"Total documents: {result['total_documents']}")
    for section, n in result["by_section"].items():
        logger.info(f"  {section}: {n}")


if __name__ == "__main__":
    main()
