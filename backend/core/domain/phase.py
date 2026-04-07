"""Design flow phases and interview engine models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Phase(str, Enum):
    """Phases of the APEX design flow."""

    ASSESSMENT = "assessment"
    INTERVIEW = "interview"
    SPEC_GENERATION = "spec_generation"
    AGENT_DESIGN = "agent_design"
    ARCHITECTURE = "architecture"
    REVIEW = "review"
    CODE_GEN = "code_gen"
    EVALUATION = "evaluation"
    EXPORT = "export"


@dataclass(frozen=True)
class InterviewOption:
    """A clickable option in an interview round."""

    label: str
    description: str
    value: str
    rag_hint: str = ""  # Used to enrich next round's RAG query


@dataclass
class InterviewRound:
    """A structured question with selectable options."""

    round_number: int
    question: str
    options: list[InterviewOption] = field(default_factory=list)
    selected_value: str | None = None
    rag_context: list[str] = field(default_factory=list)  # Patterns/cases retrieved

    @property
    def is_answered(self) -> bool:
        return self.selected_value is not None

    def select(self, value: str) -> None:
        valid_values = {o.value for o in self.options}
        valid_values.add("other")  # Always allow custom input
        if value not in valid_values and not value.startswith("custom:"):
            raise ValueError(f"Invalid option: {value}")
        self.selected_value = value
