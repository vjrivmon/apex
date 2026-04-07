"""Port: LLM Provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator


class ILLMProvider(ABC):
    """Abstract interface for LLM communication.

    In production: OllamaAdapter / VRAINAdapter (local models, zero API cost).
    In development: Claude Code (MAX subscription) is the brain — this port
    is not called directly.
    """

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        model: str,
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        """Generate a complete response."""

    @abstractmethod
    async def stream(
        self,
        prompt: str,
        model: str,
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream response tokens."""

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the LLM provider is available."""
