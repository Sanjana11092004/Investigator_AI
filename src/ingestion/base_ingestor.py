"""Abstract base class for all ingestors."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any

from sqlalchemy.orm import Session


class BaseIngestor(ABC):
    """
    All ingestors inherit from this.
    Each ingestor handles one data source type.
    """

    def __init__(self, db: Session):
        self.db = db

    @abstractmethod
    def can_handle(self, file_path: str) -> bool:
        """Return True if this ingestor handles the given file."""
        ...

    @abstractmethod
    def ingest(self, file_path: str, **kwargs) -> Dict[str, Any]:
        """
        Ingest the file into the database and/or vector store.
        
        Returns:
            Dict with keys: success (bool), records (int), message (str)
        """
        ...