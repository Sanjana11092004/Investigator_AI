"""Audit trail model — tracks every investigation action."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, JSON, Float
from sqlalchemy.dialects.postgresql import UUID

from src.database.models.base import Base


class AuditEntry(Base):
    """
    Immutable audit trail of all queries, retrievals, and responses.
    Every AI interaction is logged here for accountability.
    """
    __tablename__ = "audit_trail"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id = Column(String(100), index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    action_type = Column(String(100), index=True)  # query | ingest | retrieval | response
    user_query = Column(Text)
    retrieval_type = Column(String(50))            # sql | vector | hybrid
    retrieved_sources = Column(JSON, default=list) # list of source doc IDs/names
    llm_response = Column(Text)
    entities_extracted = Column(JSON, default=dict)
    latency_ms = Column(Float)
    tokens_used = Column(JSON, default=dict)       # {prompt: N, completion: N}
    error = Column(Text, nullable=True)