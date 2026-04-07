"""Port: Session Repository interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.domain.session import Session


class ISessionRepository(ABC):
    """Abstract interface for session persistence."""

    @abstractmethod
    async def save(self, session: Session) -> None:
        """Save or update a session."""

    @abstractmethod
    async def get(self, session_id: str) -> Session | None:
        """Get a session by ID."""

    @abstractmethod
    async def list_all(self) -> list[Session]:
        """List all sessions."""

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Delete a session."""
