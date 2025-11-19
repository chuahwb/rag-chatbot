from __future__ import annotations

import threading
from typing import Dict, Optional

from app.agents.state import ChatState


class SessionMemoryStore:
    """
    In-memory conversation store keyed by sessionId.

    Provides thread-safe access for the FastAPI app without introducing
    additional infrastructure. Can be swapped for Redis or a database later.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: Dict[str, ChatState] = {}

    def get(self, session_id: str) -> Optional[ChatState]:
        with self._lock:
            return self._sessions.get(session_id)

    def save(self, state: ChatState) -> None:
        with self._lock:
            self._sessions[state.sessionId] = state

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)


memory_store = SessionMemoryStore()



