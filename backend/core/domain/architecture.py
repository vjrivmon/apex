"""Architecture entity — the designed SMA architecture."""

from __future__ import annotations

from dataclasses import dataclass, field

from .agent_spec import AgentSpec


@dataclass
class Architecture:
    """Complete multi-agent system architecture design."""

    pattern: str  # pipeline, orchestrator-worker, consensus, expert-network, reactor, reflection, hybrid
    pattern_ref: str  # Paper citation or real case reference
    justification: str  # Why this pattern was chosen (2-3 sentences)
    ascii_diagram: str  # Visual representation of the architecture
    agents: list[AgentSpec] = field(default_factory=list)
    communication: str = "synchronous"  # synchronous, asynchronous, queue-based
    approved: bool = False
    review_notes: str = ""  # Notes from ReviewAgent

    @property
    def agent_count(self) -> int:
        return len(self.agents)

    def approve(self) -> None:
        self.approved = True

    def add_review(self, notes: str) -> None:
        self.review_notes = notes

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "pattern_ref": self.pattern_ref,
            "justification": self.justification,
            "ascii_diagram": self.ascii_diagram,
            "agents": [a.to_dict() for a in self.agents],
            "communication": self.communication,
            "approved": self.approved,
            "review_notes": self.review_notes,
        }
