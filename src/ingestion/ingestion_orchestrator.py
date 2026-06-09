"""
Ingestion Orchestrator.
Routes uploaded files to the correct ingestor based on file type.
Also indexes clinical trial text into the vector store.
"""
import os
from pathlib import Path
from typing import Dict, Any, List

from sqlalchemy.orm import Session
from loguru import logger

from src.ingestion.clinical_trials_ingestor import ClinicalTrialsIngestor
from src.ingestion.sdtm_ingestor import SDTMIngestor
from src.ingestion.pdf_ingestor import PDFIngestor
from src.ingestion.deduplication import compute_file_hash, is_already_ingested


class IngestionOrchestrator:
    """
    Main entry point for all data ingestion.
    
    Usage:
        orchestrator = IngestionOrchestrator(db_session)
        result = orchestrator.ingest_file("/path/to/AE.csv")
    """

    def __init__(self, db: Session):
        self.db = db
        self.ingestors = [
            ClinicalTrialsIngestor(db),
            SDTMIngestor(db),
            PDFIngestor(db),
        ]

    def ingest_file(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """
        Ingest a single file.
        
        Automatically detects file type and routes to the correct ingestor.
        Skips files that have already been ingested (via hash check).
        
        Args:
            file_path: Absolute or relative path to the file.
        
        Returns:
            Dict with: success, records, message, file_name
        """
        if not os.path.exists(file_path):
            return {"success": False, "records": 0, "message": f"File not found: {file_path}"}

        detection_name = kwargs.get(
            "original_filename",
            file_path,
        )

        for ingestor in self.ingestors:
            if ingestor.can_handle(detection_name):
                logger.info(
                    f"Ingesting {detection_name} with {type(ingestor).__name__}"
                )
                result = ingestor.ingest(file_path, **kwargs)
                result["file_name"] = Path(detection_name).name
                return result

        return {
            "success": False,
            "records": 0,
            "message": f"No ingestor found for {Path(file_path).name}",
            "file_name": Path(file_path).name,
        }

    def ingest_directory(self, directory: str) -> List[Dict[str, Any]]:
        """
        Ingest all supported files in a directory.
        
        Processes in order: JSON → CSV → PDF (so patients exist before AEs).
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            logger.error(f"Directory not found: {directory}")
            return []

        # Process in priority order
        all_files = []
        for pattern in ["*.json", "DM.csv", "LB.csv", "AE.csv", "CM.csv", "MH.csv", "*.pdf"]:
            all_files.extend(sorted(dir_path.rglob(pattern)))

        # Deduplicate while preserving order
        seen = set()
        ordered = []
        for f in all_files:
            if str(f) not in seen:
                seen.add(str(f))
                ordered.append(f)

        results = []
        for file_path in ordered:
            result = self.ingest_file(str(file_path))
            results.append(result)

        successful = sum(1 for r in results if r["success"] and r["records"] > 0)
        skipped = sum(1 for r in results if r.get("message", "").startswith("Already"))
        logger.info(f"Batch ingestion complete: {successful} new, {skipped} skipped, {len(results)} total")
        return results