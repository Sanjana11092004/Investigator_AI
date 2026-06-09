"""
Audit trail endpoint.
GET /audit — retrieve investigation audit logs.
"""
from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.database.connection import get_db
from src.database.models.audit import AuditEntry

router = APIRouter(prefix="/audit", tags=["Audit"])


@router.get("")
def get_audit_trail(
    session_id: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    """
    Retrieve audit log entries.
    Filter by session_id to get a specific investigation's history.
    """
    q = db.query(AuditEntry).order_by(AuditEntry.timestamp.desc())
    if session_id:
        q = q.filter(AuditEntry.session_id == session_id)
    entries = q.limit(limit).all()
    return [
        {
            "id": str(e.id),
            "session_id": e.session_id,
            "timestamp": e.timestamp.isoformat(),
            "action_type": e.action_type,
            "user_query": e.user_query,
            "retrieval_type": e.retrieval_type,
            "sources": e.retrieved_sources,
            "latency_ms": e.latency_ms,
            "tokens_used": e.tokens_used,
            "error": e.error,
        }
        for e in entries
    ]