"""Session storage.

`SessionStore` is the interface. `InMemorySessionStore` is today's
implementation. If you outgrow it later, write a `RedisSessionStore`
that implements the same methods and swap it in `get_session_store()`
below — nothing else in the app needs to change.
"""
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import lru_cache
from threading import Lock

from app.core.config import get_settings
from app.core.vector_store import VectorStore

logger = logging.getLogger(__name__)


@dataclass
class SessionData:
    session_id: str
    name: str = "New Chat"
    chat_history: list[dict] = field(default_factory=list)
    vector_store: VectorStore | None = None
    processed_files: set[tuple[str, int]] = field(default_factory=set)
    last_active: float = field(default_factory=time.time)
    # Which browser/device created this session. This is the actual privacy
    # boundary — without it, list_sessions() and get-by-id have no concept
    # of "yours" vs "everyone's" and will happily hand any caller every
    # session on the server. None means "not yet claimed" (a session ID
    # generated client-side that hasn't touched the backend yet).
    owner_device_id: str | None = None

    def touch(self) -> None:
        self.last_active = time.time()

    def maybe_auto_name(self, query: str) -> None:
        """Auto-name the session from its first message, if it's still
        the default placeholder. Called from both /chat and /chat/stream —
        living here (not duplicated in each route) means there's exactly
        one place this logic can go wrong, not two.
        """
        if self.name == "New Chat" and len(self.chat_history) == 0:
            words = query.split()[:4]
            auto_name = " ".join(words).capitalize()
            if len(auto_name) > 30:
                auto_name = auto_name[:27] + "..."
            else:
                auto_name = auto_name + "..."
            self.name = auto_name


class SessionStore(ABC):
    @abstractmethod
    def get_or_create(self, session_id: str, owner_device_id: str | None = None) -> SessionData: ...

    @abstractmethod
    def get(self, session_id: str) -> SessionData | None:
        """Get session data without creating if it doesn't exist."""
        ...

    @abstractmethod
    def save(self, session_data: SessionData) -> None: ...

    @abstractmethod
    def delete(self, session_id: str) -> None: ...

    @abstractmethod
    def cleanup_expired(self, ttl_seconds: int) -> int:
        """Remove sessions inactive longer than ttl_seconds. Returns count removed."""
        ...

    @abstractmethod
    def list_sessions(self, owner_device_id: str) -> list[dict]:
        """Return sessions belonging to this device only — never all sessions."""
        ...

    @abstractmethod
    def rename_session(self, session_id: str, new_name: str) -> None:
        """Rename a session."""
        ...


class InMemorySessionStore(SessionStore):
    """Thread-safe in-memory session store.

    Good for a single-container deployment. Data is lost on restart and
    doesn't work across multiple backend processes — see the module
    docstring if you outgrow this.
    """

    def __init__(self):
        self._sessions: dict[str, SessionData] = {}
        self._lock = Lock()

    def get_or_create(self, session_id: str, owner_device_id: str | None = None) -> SessionData:
        with self._lock:
            if session_id not in self._sessions:
                logger.info("Creating new session: %s (owner: %s)", session_id, owner_device_id)
                self._sessions[session_id] = SessionData(session_id=session_id, owner_device_id=owner_device_id)
            elif self._sessions[session_id].owner_device_id is None and owner_device_id is not None:
                # Claim-on-first-touch: a session created before this fix
                # (or via a path that didn't have a device_id yet) gets
                # claimed by whoever legitimately touches it next with one.
                self._sessions[session_id].owner_device_id = owner_device_id
            self._sessions[session_id].touch()
            return self._sessions[session_id]

    def get(self, session_id: str) -> SessionData | None:
        with self._lock:
            return self._sessions.get(session_id)

    def save(self, session_data: SessionData) -> None:
        with self._lock:
            session_data.touch()
            self._sessions[session_data.session_id] = session_data

    def delete(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def cleanup_expired(self, ttl_seconds: int) -> int:
        cutoff = time.time() - ttl_seconds
        with self._lock:
            expired = [sid for sid, s in self._sessions.items() if s.last_active < cutoff]
            for sid in expired:
                del self._sessions[sid]
        if expired:
            logger.info("Cleaned up %d expired sessions", len(expired))
        return len(expired)

    def list_sessions(self, owner_device_id: str) -> list[dict]:
        """Return only sessions owned by this device — the actual privacy fix.
        Sessions with no owner (pre-fix legacy data) are excluded from
        everyone's list rather than shown to whoever asks first.
        """
        with self._lock:
            return [
                {
                    "session_id": session_id,
                    "name": session.name,
                    "last_active": session.last_active,
                    "message_count": len(session.chat_history),
                }
                for session_id, session in self._sessions.items()
                if session.owner_device_id == owner_device_id
            ]

    def rename_session(self, session_id: str, new_name: str) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id].name = new_name
                logger.info("Renamed session %s to '%s'", session_id, new_name)
            else:
                logger.warning("Attempted to rename non-existent session: %s", session_id)


@lru_cache
def get_session_store() -> SessionStore:
    """Singleton — same store instance shared across all requests in this process."""
    settings = get_settings()
    if settings.session_backend == "redis":
        raise NotImplementedError(
            "Redis backend not implemented yet. Set SESSION_BACKEND=memory, "
            "or implement RedisSessionStore(SessionStore) and wire it in here."
        )
    return InMemorySessionStore()
