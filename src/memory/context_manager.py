"""
Context Manager — combines short and long-term memory into a unified context
that is injected into every RAG pipeline call.
"""
from typing import List, Dict, Any, Optional

from sqlalchemy.orm import Session

from src.memory.short_term import ShortTermMemory
from src.memory.long_term import LongTermMemory


class ContextManager:
    """
    Unified interface for conversation memory.

    Combines:
    - Short-term: in-memory sliding window (fast, current session)
    - Long-term: PostgreSQL-backed persistence (cross-restart)
    """

    def __init__(self, db: Session, session_id: str = None):
        self.db = db
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory(db)
        self.session_id = session_id

        # Load existing history if resuming a session
        if session_id:
            history = self.long_term.get_history(session_id, last_n=10)
            for msg in history:
                if msg["role"] == "user":
                    self.short_term.add_user_message(msg["content"])
                else:
                    self.short_term.add_assistant_message(msg["content"])

    def start_session(self, name: str = None) -> str:
        """Create a new session and return its ID."""
        session = self.long_term.create_session(name)
        self.session_id = str(session.id)
        return self.session_id

    def add_turn(self, user_message: str, assistant_message: str) -> None:
        """
        Record a complete conversation turn.
        Updates both short-term (in memory) and long-term (DB).
        """
        self.short_term.add_user_message(user_message)
        self.short_term.add_assistant_message(assistant_message)

        if self.session_id:
            self.long_term.append_message(self.session_id, "user", user_message)
            self.long_term.append_message(self.session_id, "assistant", assistant_message)

    def get_history(self) -> List[Dict[str, str]]:
        """Return current short-term conversation history."""
        return self.short_term.get_history()

    def get_context(self) -> Dict[str, Any]:
        """Return current session context dict."""
        if self.session_id:
            return self.long_term.get_context(self.session_id)
        return {}

    def update_context_from_entities(self, entities: Dict[str, List[str]]) -> None:
        """Update context based on newly extracted entities."""
        if self.session_id:
            self.long_term.auto_update_context_from_entities(self.session_id, entities)

    def update_context(self, **kwargs) -> None:
        """Manually update context values."""
        if self.session_id:
            self.long_term.update_context(self.session_id, **kwargs)