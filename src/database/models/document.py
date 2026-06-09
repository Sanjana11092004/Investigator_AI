"""
Document registry — tracks every ingested file with its hash.
This is the deduplication table.
"""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, Integer
from sqlalchemy.dialects.postgresql import UUID

from src.database.models.base import Base


class IngestedDocument(Base):
    """
    Central registry of all ingested documents.
    A document is uniquely identified by its MD5 hash,
    so the same file is never processed twice.
    """
    __tablename__ = "ingested_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_name = Column(String(512), nullable=False)
    file_path = Column(Text, nullable=False)
    file_hash = Column(String(64), unique=True, nullable=False, index=True)
    file_type = Column(String(50), nullable=False)  # 'clinical_trials_json' | 'sdtm' | 'narrative_pdf'
    file_size_bytes = Column(Integer)
    ingested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String(50), default="completed")  # completed | failed | processing
    record_count = Column(Integer, default=0)  # rows/pages ingested
    error_message = Column(Text, nullable=True)