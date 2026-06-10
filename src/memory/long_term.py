"""
Long-term (cross-session) memory backed by PostgreSQL.
Persists investigation sessions and allows resuming across restarts.
"""
import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session
from loguru import logger

from src.database.models.session import InvestigationSession
from src.llm.groq_client import GroqClient
from src.llm.prompt_templates import SUMMARY_PROMPT


class LongTermMemory:
    """
    PostgreSQL-backed session persistence.

    Provides:
    - Create / load / update investigation sessions
    - Store full conversation history per session
    - Store extracted investigation context (study, patient, etc.)
    - Auto-summarize sessions for efficient context injection
    """

    def __init__(self, db: Session):
        self.db = db

    def create_session(self, session_name: str = None) -> InvestigationSession:
        """
        Create a new investigation session.

        Args:
            session_name: Human-readable name. Auto-generated if not provided.

        Returns:
            Newly created InvestigationSession.
        """
        if not session_name:
            session_name = f"Investigation {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"

        session = InvestigationSession(
            session_name=session_name,
            conversation_history=[],
            investigation_context={},
        )
        self.db.add(session)
        self.db.commit()
        self.db.refresh(session)
        logger.info(f"Created session: {session.id} — '{session_name}'")
        return session

    def load_session(self, session_id: str) -> Optional[InvestigationSession]:
        """
        Load an existing session by ID.

        Returns None if session not found.
        """
        try:
            return (
                self.db.query(InvestigationSession)
                .filter(InvestigationSession.id == session_id)
                .first()
            )
        except Exception as e:
            # e.g. a malformed (non-UUID) session id — don't 500, treat as missing
            logger.warning(f"load_session failed for id={session_id!r}: {e}")
            self.db.rollback()
            return None

    def list_sessions(self, limit: int = 20) -> List[InvestigationSession]:
        """Return recent active sessions, newest first."""
        return (
            self.db.query(InvestigationSession)
            .filter(InvestigationSession.status == "active")
            .order_by(InvestigationSession.updated_at.desc())
            .limit(limit)
            .all()
        )

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
    ) -> None:
        """
        Append a message to the session's conversation history.

        Args:
            session_id: Session UUID.
            role: "user" or "assistant".
            content: Message content.
        """
        session = self.load_session(session_id)
        if not session:
            return

        history = list(session.conversation_history or [])
        history.append({"role": role, "content": content})
        session.conversation_history = history
        session.updated_at = datetime.utcnow()
        self.db.commit()

    def update_context(
        self,
        session_id: str,
        study_id: str = None,
        patient_id: str = None,
        extra_context: Dict[str, Any] = None,
    ) -> None:
        """
        Update the investigation context for a session.
        Merges new context into existing context (does not overwrite all keys).

        Args:
            session_id: Session UUID.
            study_id: If provided, sets the active study.
            patient_id: If provided, sets the active patient.
            extra_context: Additional key-value context pairs.
        """
        session = self.load_session(session_id)
        if not session:
            return

        if study_id:
            session.active_study_id = study_id
        if patient_id:
            session.active_patient_id = patient_id
        if extra_context:
            current = dict(session.investigation_context or {})
            current.update(extra_context)
            session.investigation_context = current

        session.updated_at = datetime.utcnow()
        self.db.commit()

    def get_context(self, session_id: str) -> Dict[str, Any]:
        """
        Return full context dict for a session.
        Used to inject into RAG pipeline queries.
        """
        session = self.load_session(session_id)
        if not session:
            return {}
        return {
            "active_study_id": session.active_study_id,
            "active_patient_id": session.active_patient_id,
            "investigation_context": session.investigation_context or {},
        }

    def get_history(self, session_id: str, last_n: int = 10) -> List[Dict[str, str]]:
        """
        Return the last N messages from a session's history.
        """
        session = self.load_session(session_id)
        if not session:
            return []
        history = session.conversation_history or []
        return history[-last_n * 2:]  # last N turns = N*2 messages

    def auto_update_context_from_entities(
        self,
        session_id: str,
        entities: Dict[str, List[str]],
    ) -> None:
        """
        Automatically update session context when entities are extracted.
        If new study IDs or patient IDs are found, set them as active context.
        """
        studies = entities.get("studies", [])
        patients = entities.get("patients", [])

        extra = {}
        if entities.get("adverse_events"):
            extra["recent_ae_terms"] = entities["adverse_events"][:3]
        if entities.get("drugs"):
            extra["recent_drugs"] = entities["drugs"][:3]

        # Only pin an active patient when the turn is focused on a SINGLE subject.
        # A list query (e.g. "show all serious AEs" → 24 patients) must not pin one,
        # or the next follow-up gets wrongly filtered to just that patient.
        active_patient = patients[0] if len(patients) == 1 else None

        # Only treat the candidate as a study if it actually looks like a study id
        # (contains a digit) and is not really a subject/patient identifier.
        active_study = None
        if studies:
            candidate = studies[0]
            if any(ch.isdigit() for ch in candidate) and candidate not in patients:
                active_study = candidate

        self.update_context(
            session_id,
            study_id=active_study,
            patient_id=active_patient,
            extra_context=extra if extra else None,
        )

    def archive_session(self, session_id: str) -> None:
        """Mark a session as archived."""
        session = self.load_session(session_id)
        if session:
            session.status = "archived"
            self.db.commit()