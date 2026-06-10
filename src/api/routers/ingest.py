"""
Ingestion endpoint — accepts file uploads and triggers ingestion pipeline.
POST /ingest/upload — upload a file
GET  /ingest/documents — list all ingested documents
"""
import os
import tempfile
from typing import List, Optional

from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Form
from sqlalchemy.orm import Session
from loguru import logger

from src.database.connection import get_db
from src.database.models.document import IngestedDocument
from src.ingestion.ingestion_orchestrator import IngestionOrchestrator
from src.ingestion.deduplication import compute_bytes_hash, is_already_ingested
from src.api.schemas.ingest import IngestResponse

router = APIRouter(prefix="/ingest", tags=["Ingestion"])


@router.post("/upload", response_model=IngestResponse)
async def upload_and_ingest(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
) -> IngestResponse:
    """
    Upload a file and ingest it into the system.

    Supported formats:
    - .json  → ClinicalTrials JSON
    - .csv   → SDTM domain (DM, LB, AE, CM, MH)
    - .pdf   → Medical narrative

    If the file was already ingested (same content), it is skipped.
    """
    content = await file.read()
    file_hash = compute_bytes_hash(content)

    if is_already_ingested(db, file_hash):
        return IngestResponse(
            success=True,
            file_name=file.filename,
            records=0,
            message="Already ingested. No changes made.",
        )

    # Write to temp file for ingestion
    suffix = os.path.splitext(file.filename)[1]
    with tempfile.NamedTemporaryFile(
    delete=False, suffix=suffix
    ) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        orchestrator = IngestionOrchestrator(db)
        result = orchestrator.ingest_file(
            tmp_path,
            original_filename=file.filename,
            session_id=session_id,
        )
        result["file_name"] = file.filename
        logger.info(f"Upload ingested: {file.filename} → {result}")
        return IngestResponse(**result)
    except Exception as e:
        logger.error(f"Upload ingestion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        os.unlink(tmp_path)


@router.get("/documents")
def list_documents(
    db: Session = Depends(get_db),
    limit: int = 50,
):
    """List all ingested documents with their status."""
    docs = (
        db.query(IngestedDocument)
        .order_by(IngestedDocument.ingested_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(d.id),
            "file_name": d.file_name,
            "file_type": d.file_type,
            "status": d.status,
            "record_count": d.record_count,
            "ingested_at": d.ingested_at.isoformat(),
            "file_size_bytes": d.file_size_bytes,
        }
        for d in docs
    ]