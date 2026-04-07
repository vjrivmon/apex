"""Port: File Exporter interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class IFileExporter(ABC):
    """Abstract interface for exporting generated code/skills."""

    @abstractmethod
    async def export_zip(
        self,
        files: dict[str, str],
        project_name: str,
    ) -> bytes:
        """Export files as a ZIP archive. Returns bytes."""

    @abstractmethod
    async def export_skill(
        self,
        skill_content: str,
        skill_name: str,
        output_dir: str,
    ) -> str:
        """Export a Claude Code skill to a directory. Returns the path."""
