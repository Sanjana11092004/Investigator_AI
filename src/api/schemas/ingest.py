"""Pydantic schemas for ingestion endpoints."""
from typing import Optional
from pydantic import BaseModel


class IngestResponse(BaseModel):
    success: bool
    file_name: str
    records: int
    message: str