"""Investigation session model for long-term memory persistence."""
import uuid
from datetime import datetime

from sqlalchemy import Column, String, DateTime, Text, JSON

from src.database.models.base import Base, GUID


class InvestigationSession(Base):
    """
    Persists investigation sessions across application restarts.
    Stores conversation history and extracted context (study, patient, etc.)
    """
    __tablename__ = "investigation_sessions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    session_name = Column(String(500), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Context state — what the session "knows"
    active_study_id = Column(String(100), nullable=True)    # e.g. "NCT01234567"
    active_patient_id = Column(String(100), nullable=True)  # e.g. "SUBJ001"
    investigation_context = Column(JSON, default=dict)       # arbitrary key-value context

    # Full conversation history as JSON list of {role, content} dicts
    conversation_history = Column(JSON, default=list)

    # Summary for quick context injection
    session_summary = Column(Text, nullable=True)

    status = Column(String(50), default="active")  # active | archived