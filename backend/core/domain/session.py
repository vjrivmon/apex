"""Session entity — a design conversation with the user."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from .architecture import Architecture
from .phase import InterviewRound, Phase


@dataclass
class Message:
    """A single message in the conversation."""

    role: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    message_type: str = "text"  # text, options, architecture, agent_spec, code, export
    metadata: dict = field(default_factory=dict)  # Extra data (options, code blocks, etc.)


@dataclass
class Session:
    """A design session: user describes a problem, APEX designs the SMA."""

    id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    phase: Phase = Phase.ASSESSMENT
    messages: list[Message] = field(default_factory=list)
    interview_rounds: list[InterviewRound] = field(default_factory=list)
    problem_description: str = ""
    domain_analysis: dict = field(default_factory=dict)
    architecture: Architecture | None = None
    generated_code: dict[str, str] = field(default_factory=dict)  # filename -> content
    generated_skills: list[dict] = field(default_factory=list)
    spec_content: str = ""
    evaluation_plan: str = ""
    project_id: str | None = None

    def add_message(self, role: str, content: str, **kwargs) -> Message:
        msg = Message(role=role, content=content, **kwargs)
        self.messages.append(msg)
        return msg

    def advance_phase(self, target: Phase) -> None:
        self.phase = target

    def add_interview_round(self, round_: InterviewRound) -> None:
        self.interview_rounds.append(round_)

    @property
    def current_round(self) -> InterviewRound | None:
        unanswered = [r for r in self.interview_rounds if not r.is_answered]
        return unanswered[0] if unanswered else None

    @property
    def interview_complete(self) -> bool:
        return all(r.is_answered for r in self.interview_rounds) and len(self.interview_rounds) > 0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat(),
            "phase": self.phase.value,
            "messages": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp.isoformat(),
                    "message_type": m.message_type,
                    "metadata": m.metadata,
                }
                for m in self.messages
            ],
            "problem_description": self.problem_description,
            "spec_content": self.spec_content,
            "architecture": self.architecture.to_dict() if self.architecture else None,
            "project_id": self.project_id,
        }
