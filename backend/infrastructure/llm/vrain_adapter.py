"""Infrastructure adapter: VRAIN UPV LLM provider with Ollama fallback."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from core.ports.llm_provider import ILLMProvider
from shared.config import settings

from .ollama_adapter import OllamaAdapter

logger = logging.getLogger(__name__)


class VRAINAdapter(ILLMProvider):
    """Connects to the VRAIN UPV Ollama instance for large models.

    VRAIN hosts powerful GPUs that can run models like ``qwen3:32b`` which do
    not fit on a Slimbook.  If the VRAIN endpoint is unreachable the adapter
    automatically falls back to the local Ollama instance using a smaller model.

    Fallback strategy:
        1. Try VRAIN with the requested model.
        2. If VRAIN fails, try local Ollama with the configured codegen model.
    """

    def __init__(
        self,
        vrain_url: str | None = None,
        ollama_url: str | None = None,
        fallback_model: str | None = None,
    ) -> None:
        self._vrain = OllamaAdapter(base_url=vrain_url or settings.vrain_base_url)
        self._ollama = OllamaAdapter(base_url=ollama_url or settings.ollama_base_url)
        self._fallback_model = fallback_model or settings.ollama_codegen_model

    # -- ILLMProvider ---------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        model: str,
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        """Generate via VRAIN, falling back to local Ollama on failure."""
        try:
            logger.debug("VRAINAdapter: trying VRAIN model=%s", model)
            return await self._vrain.generate(
                prompt, model, system_prompt, temperature,
            )
        except Exception:
            logger.warning(
                "VRAIN unavailable for model %s — falling back to local Ollama "
                "with model %s",
                model,
                self._fallback_model,
            )
            return await self._ollama.generate(
                prompt, self._fallback_model, system_prompt, temperature,
            )

    async def stream(
        self,
        prompt: str,
        model: str,
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream via VRAIN with fallback to local Ollama.

        Because async generators cannot be "retried" mid-iteration, we probe
        VRAIN health first and choose the backend upfront.
        """
        vrain_ok = await self._vrain.health_check()

        if vrain_ok:
            logger.debug("VRAINAdapter stream: using VRAIN model=%s", model)
            try:
                async for token in self._vrain.stream(
                    prompt, model, system_prompt, temperature,
                ):
                    yield token
                return
            except Exception:
                logger.warning(
                    "VRAIN stream failed mid-generation for model %s — "
                    "cannot retry streaming; yielding nothing for this request",
                    model,
                )
                return

        logger.info(
            "VRAIN not reachable — streaming from local Ollama with model %s",
            self._fallback_model,
        )
        async for token in self._ollama.stream(
            prompt, self._fallback_model, system_prompt, temperature,
        ):
            yield token

    async def health_check(self) -> bool:
        """Return True if *either* VRAIN or local Ollama is reachable."""
        vrain_ok = await self._vrain.health_check()
        if vrain_ok:
            return True
        logger.info("VRAIN unreachable — checking local Ollama as fallback")
        return await self._ollama.health_check()

    # -- Lifecycle ------------------------------------------------------------

    async def close(self) -> None:
        """Close both underlying HTTP clients."""
        await self._vrain.close()
        await self._ollama.close()
