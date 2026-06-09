"""
Short-term (in-session) conversation memory.
Stores last N turns in memory for context injection.
"""
from typing import List, Dict
from collections import deque

from src.config.settings import settings


class ShortTermMemory:
    """
    Sliding window conversation buffer.
    Keeps the last `window_size` turns in memory.
    """

    def __init__(self, window_size: int = None):
        self.window_size = window_size or settings.memory_window_size
        self._history: deque = deque(maxlen=self.window_size * 2)  # *2 for user+assistant

    def add_user_message(self, content: str) -> None:
        """Add a user message to memory."""
        self._history.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant message to memory."""
        self._history.append({"role": "assistant", "content": content})

    def get_history(self) -> List[Dict[str, str]]:
        """Return the current conversation history as a list."""
        return list(self._history)

    def clear(self) -> None:
        """Clear all history."""
        self._history.clear()

    @property
    def turn_count(self) -> int:
        """Number of complete turns (user + assistant pairs)."""
        return len(self._history) // 2