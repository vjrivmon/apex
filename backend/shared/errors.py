"""Domain errors for APEX."""

from __future__ import annotations


class ApexError(Exception):
    """Base error for all APEX domain errors."""


class SessionNotFoundError(ApexError):
    """Raised when a session is not found."""

    def __init__(self, session_id: str):
        super().__init__(f"Session not found: {session_id}")
        self.session_id = session_id


class ProjectNotFoundError(ApexError):
    """Raised when a project is not found."""

    def __init__(self, project_id: str):
        super().__init__(f"Project not found: {project_id}")
        self.project_id = project_id


class PhaseError(ApexError):
    """Raised when an invalid phase transition is attempted."""


class LLMProviderError(ApexError):
    """Raised when LLM communication fails."""

    def __init__(self, provider: str, detail: str):
        super().__init__(f"LLM provider error ({provider}): {detail}")
        self.provider = provider


class ArchitectureNotApprovedError(ApexError):
    """Raised when trying to generate code without approved architecture."""
