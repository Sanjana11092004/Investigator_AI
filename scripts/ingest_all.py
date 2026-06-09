"""
Bulk ingest all files in the data/ directory.
Run after placing your data files in data/clinical_trials/, data/sdtm/, data/narratives/
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from loguru import logger
from src.database.connection import get_db_context
from src.ingestion.ingestion_orchestrator import IngestionOrchestrator
from src.config.settings import settings


def main():
    logger.info(f"Starting bulk ingestion from {settings.data_dir}")
    
    with get_db_context() as db:
        orchestrator = IngestionOrchestrator(db)
        results = orchestrator.ingest_directory(settings.data_dir)

    total_records = sum(r.get("records", 0) for r in results)
    successful = sum(1 for r in results if r["success"])
    failed = [r for r in results if not r["success"] and not r.get("message", "").startswith("Already")]

    logger.info(f"Ingestion complete: {successful}/{len(results)} files, {total_records} total records")
    
    if failed:
        logger.warning(f"Failed files:")
        for f in failed:
            logger.warning(f"  {f.get('file_name')}: {f.get('message')}")


if __name__ == "__main__":
    main()