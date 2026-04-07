"""Pattern entity — SMA architecture pattern from RAG knowledge base."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Pattern:
    """A multi-agent system architecture pattern."""

    id: str
    name: str  # e.g., "Pipeline", "Orchestrator-Worker"
    description: str
    when_to_use: str
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)
    paper_ref: str = ""  # Academic reference
    example_cases: list[str] = field(default_factory=list)
    ascii_template: str = ""  # Template diagram for this pattern

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "pros": self.pros,
            "cons": self.cons,
            "paper_ref": self.paper_ref,
            "example_cases": self.example_cases,
            "ascii_template": self.ascii_template,
        }
