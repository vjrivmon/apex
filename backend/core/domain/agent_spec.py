"""Agent specification entity — defines a single agent in a designed SMA."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentSpec:
    """Specification for one agent within a multi-agent system."""

    name: str
    responsibility: str  # One sentence. If you need two, it's two agents.
    input_description: str
    output_description: str
    recommended_model: str
    needs_rag: bool = False
    needs_memory: bool = False
    failure_mode: str = "return_empty"  # What to do when the agent fails
    tools: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)  # Names of agents it depends on

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "responsibility": self.responsibility,
            "input_description": self.input_description,
            "output_description": self.output_description,
            "recommended_model": self.recommended_model,
            "needs_rag": self.needs_rag,
            "needs_memory": self.needs_memory,
            "failure_mode": self.failure_mode,
            "tools": self.tools,
            "dependencies": self.dependencies,
        }
