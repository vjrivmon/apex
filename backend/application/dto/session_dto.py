"""DTOs for session-related API boundaries."""

from __future__ import annotations

from pydantic import BaseModel, Field


class CreateSessionRequest(BaseModel):
    """Request to create a new design session."""

    problem_description: str = Field(
        ..., min_length=10, description="Description of the problem to solve with a multi-agent system"
    )


class CreateSessionResponse(BaseModel):
    """Response after creating a session."""

    session_id: str
    phase: str
    message: str


class SelectOptionRequest(BaseModel):
    """Request to select an option in an interview round."""

    value: str = Field(..., description="The selected option value or 'custom:...' for free text")


class SessionSummary(BaseModel):
    """Brief session info for listing."""

    id: str
    phase: str
    problem_description: str
    created_at: str
    project_id: str | None = None


class InterviewOptionDTO(BaseModel):
    """A clickable option in the chat UI."""

    label: str
    description: str
    value: str


class InterviewRoundDTO(BaseModel):
    """A structured question with options sent to the frontend."""

    round_number: int
    question: str
    options: list[InterviewOptionDTO]
    rag_context: list[str] = []


class WSMessage(BaseModel):
    """WebSocket message format."""

    type: str  # token, phase, options, architecture, agent_spec, code, export, done, error
    content: str = ""
    metadata: dict = {}
