"""Port: Project Repository interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from core.domain.project import Project


class IProjectRepository(ABC):
    """Abstract interface for project persistence."""

    @abstractmethod
    async def save(self, project: Project) -> None:
        """Save or update a project."""

    @abstractmethod
    async def get(self, project_id: str) -> Project | None:
        """Get a project by ID."""

    @abstractmethod
    async def list_all(self, status: str | None = None) -> list[Project]:
        """List projects, optionally filtered by status."""

    @abstractmethod
    async def delete(self, project_id: str) -> None:
        """Delete a project."""
