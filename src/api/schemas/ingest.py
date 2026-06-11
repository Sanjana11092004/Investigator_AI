"""Pydantic schemas for ingestion endpoints."""
from typing import Any, Dict
from pydantic import BaseModel, Field

# Keys that map to top-level response fields; everything else an ingestor returns
# is collected into `details`.
_CORE_KEYS = ("success", "file_name", "records", "message")


class IngestResponse(BaseModel):
    success: bool
    file_name: str
    records: int
    message: str
    # Catch-all for ingestor-specific output (e.g. a PDF's `structured_patients`,
    # or whatever a future file type returns). Extra keys flow through here, so a
    # new ingestor never requires a change to this schema.
    details: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_result(cls, result: Dict[str, Any]) -> "IngestResponse":
        """Build a response from any ingestor's result dict, routing unknown keys
        into `details` (skipping null values) so the API surfaces them generically."""
        result = result or {}
        details = {
            k: v for k, v in result.items()
            if k not in _CORE_KEYS and v is not None
        }
        return cls(
            success=result.get("success", False),
            file_name=result.get("file_name", ""),
            records=result.get("records", 0),
            message=result.get("message", ""),
            details=details,
        )
