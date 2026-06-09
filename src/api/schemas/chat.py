"""Pydantic schemas for chat endpoints."""
from typing import Optional, List, Dict, Any
from pydantic import BaseModel


class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    answer: str
    session_id: str
    sources: List[str]
    entities: Dict[str, List[str]]
    retrieval_type: str
    latency_ms: float
    tokens_used: Dict[str, int]