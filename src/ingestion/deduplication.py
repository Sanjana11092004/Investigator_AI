"""
File deduplication using MD5 hashing.
If a file has been ingested before, it is skipped entirely.
"""
import hashlib
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session
from loguru import logger

from src.database.models.document import IngestedDocument


def compute_file_hash(file_path: str) -> str:
    """
    Compute MD5 hash of a file for deduplication.
    
    Args:
        file_path: Path to the file.
    
    Returns:
        Hex digest string of MD5 hash.
    """
    md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            md5.update(chunk)
    return md5.hexdigest()


def compute_bytes_hash(content: bytes) -> str:
    """Compute MD5 hash from bytes (for uploaded files)."""
    return hashlib.md5(content).hexdigest()


def is_already_ingested(db: Session, file_hash: str) -> bool:
    """
    Check if a file with this hash was already ingested successfully.
    
    Args:
        db: SQLAlchemy session.
        file_hash: MD5 hash string.
    
    Returns:
        True if the file was already ingested.
    """
    record = (
        db.query(IngestedDocument)
        .filter(
            IngestedDocument.file_hash == file_hash,
            IngestedDocument.status == "completed",
        )
        .first()
    )
    if record:
        logger.info(f"File with hash {file_hash[:8]}... already ingested as '{record.file_name}'. Skipping.")
        return True
    return False


def register_document(
    db: Session,
    file_name: str,
    file_path: str,
    file_hash: str,
    file_type: str,
    file_size_bytes: int,
    record_count: int = 0,
    status: str = "completed",
    error_message: Optional[str] = None,
) -> IngestedDocument:
    """
    Register a document in the ingested_documents table.
    
    Args:
        db: SQLAlchemy session.
        file_name: Original filename.
        file_path: Full path to file.
        file_hash: MD5 hash.
        file_type: One of 'clinical_trials_json', 'sdtm', 'narrative_pdf'.
        file_size_bytes: File size.
        record_count: Number of records/pages ingested.
        status: 'completed' | 'failed' | 'processing'.
        error_message: Error details if failed.
    
    Returns:
        The created IngestedDocument record.
    """
    doc = IngestedDocument(
        file_name=file_name,
        file_path=str(file_path),
        file_hash=file_hash,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        record_count=record_count,
        status=status,
        error_message=error_message,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    logger.info(f"Registered document: {file_name} (type={file_type}, records={record_count})")
    return doc