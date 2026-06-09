"""Pydantic schemas for session endpoints."""
from typing import Optional, Dict, Any, List
from datetime import datetime
from pydantic import BaseModel


class SessionCreate(BaseModel):
    name: Optional[str] = None


class SessionResponse(BaseModel):
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    active_study_id: Optional[str]
    active_patient_id: Optional[str]
    status: str
    turn_count: int