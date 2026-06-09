"""
Session management endpoints.
GET  /sessions       — list all sessions
POST /sessions       — create new session
GET  /sessions/{id}  — get session details
DELETE /sessions/{id} — archive session
"""
from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.database.connection import get_db
from src.memory.long_term import LongTermMemory
from src.api.schemas.session import SessionCreate, SessionResponse

router = APIRouter(prefix="/sessions", tags=["Sessions"])


@router.get("", response_model=List[SessionResponse])
def list_sessions(db: Session = Depends(get_db)):
    """Return all active investigation sessions, newest first."""
    lt = LongTermMemory(db)
    sessions = lt.list_sessions()
    return [
        SessionResponse(
            id=str(s.id),
            name=s.session_name,
            created_at=s.created_at,
            updated_at=s.updated_at,
            active_study_id=s.active_study_id,
            active_patient_id=s.active_patient_id,
            status=s.status,
            turn_count=len(s.conversation_history or []) // 2,
        )
        for s in sessions
    ]


@router.post("", response_model=SessionResponse)
def create_session(
    body: SessionCreate,
    db: Session = Depends(get_db),
):
    """Create a new investigation session."""
    lt = LongTermMemory(db)
    session = lt.create_session(body.name)
    return SessionResponse(
        id=str(session.id),
        name=session.session_name,
        created_at=session.created_at,
        updated_at=session.updated_at,
        active_study_id=session.active_study_id,
        active_patient_id=session.active_patient_id,
        status=session.status,
        turn_count=0,
    )


@router.get("/{session_id}")
def get_session(session_id: str, db: Session = Depends(get_db)):
    """Get full session details including conversation history."""
    lt = LongTermMemory(db)
    session = lt.load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return {
        "id": str(session.id),
        "name": session.session_name,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "active_study_id": session.active_study_id,
        "active_patient_id": session.active_patient_id,
        "investigation_context": session.investigation_context,
        "conversation_history": session.conversation_history or [],
        "status": session.status,
    }


@router.delete("/{session_id}")
def archive_session(session_id: str, db: Session = Depends(get_db)):
    """Archive (soft-delete) a session."""
    lt = LongTermMemory(db)
    lt.archive_session(session_id)
    return {"message": "Session archived"}