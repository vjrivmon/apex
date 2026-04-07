"""Project entity — tracks a designed SMA project and its history."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Project:
    """A completed or in-progress SMA design project."""

    id: str
    name: str
    description: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: str | None = None
    spec_content: str = ""  # Generated SPEC.md
    architecture_pattern: str = ""
    agent_count: int = 0
    status: str = "in_progress"  # in_progress, completed, exported
    export_path: str | None = None
    tags: list[str] = field(default_factory=list)
    learnings: list[str] = field(default_factory=list)  # Extracted for knowledge loop

    def complete(self, export_path: str) -> None:
        self.status = "completed"
        self.export_path = export_path
        self.updated_at = datetime.now(timezone.utc)

    def add_learning(self, learning: str) -> None:
        self.learnings.append(learning)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "session_id": self.session_id,
            "spec_content": self.spec_content,
            "architecture_pattern": self.architecture_pattern,
            "agent_count": self.agent_count,
            "status": self.status,
            "export_path": self.export_path,
            "tags": self.tags,
            "learnings": self.learnings,
        }
