"""Re-index a narrative PDF with the current settings.

Deletes the document's existing vector chunks + ingestion record, then re-runs
the full PDF ingestor — which re-chunks/re-embeds at the current CHUNK_SIZE and
(if PDF_STRUCTURED_EXTRACTION=true) builds the structured per-document JSON.

Usage:
    python -m scripts.reindex_pdf data/narratives/patient_narrative_001.pdf
"""
import sys
from pathlib import Path

# Ensure the project root is importable when run as a file (python scripts/...).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger

from src.database.connection import SessionLocal
from src.database.models.document import IngestedDocument
from src.ingestion.deduplication import compute_file_hash
from src.ingestion.pdf_ingestor import PDFIngestor
from src.catalog.catalog_store import get_catalog_store


def main(path: str) -> None:
    file_name = Path(path).name
    file_hash = compute_file_hash(path)
    db = SessionLocal()
    try:
        # 1. Drop existing catalog chunks for this source.
        get_catalog_store().delete_by_source(file_name)

        # 2. Drop the ingestion record so the ingestor doesn't skip it.
        deleted = (
            db.query(IngestedDocument)
            .filter(IngestedDocument.file_hash == file_hash)
            .delete(synchronize_session=False)
        )
        db.commit()
        logger.info(f"removed {deleted} ingestion record(s) for {file_name}")

        # 3. Re-ingest (re-chunk + re-embed + structured extraction).
        result = PDFIngestor(db).ingest(path, original_filename=file_name)
        logger.info(f"DONE: {result}")
        print("RESULT:", result)
    finally:
        db.close()


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "data/narratives/patient_narrative_001.pdf"
    main(target)
