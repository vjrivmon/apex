"""Infrastructure adapter: Ollama LLM provider via HTTP API."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

import httpx

from core.ports.llm_provider import ILLMProvider
from shared.config import settings

logger = logging.getLogger(__name__)

# Regex to strip <think>...</think> blocks from deepseek-r1 responses
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# Timeout for a single LLM request (generation can be slow on large models)
_REQUEST_TIMEOUT = 60.0


def _strip_think_blocks(text: str) -> str:
    """Remove ``<think>...</think>`` reasoning blocks from deepseek-r1 output."""
    return _THINK_BLOCK_RE.sub("", text).strip()


class OllamaAdapter(ILLMProvider):
    """Connects to a local (or Tailscale-reachable) Ollama instance.

    Uses the ``/api/chat`` endpoint for both streaming and non-streaming
    generation, and ``/api/tags`` for health checks.
    """

    def __init__(self, base_url: str | None = None) -> None:
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(_REQUEST_TIMEOUT, connect=10.0),
        )

    # -- ILLMProvider ---------------------------------------------------------

    async def generate(
        self,
        prompt: str,
        model: str,
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> str:
        """Send a non-streaming chat completion request and return the full response."""
        payload = self._build_payload(
            prompt, model, system_prompt, temperature, stream=False,
        )
        logger.debug("Ollama generate: model=%s prompt_len=%d", model, len(prompt))

        try:
            response = await self._client.post("/api/chat", json=payload)
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            content: str = data.get("message", {}).get("content", "")
            if "deepseek" in model.lower():
                content = _strip_think_blocks(content)
            return content
        except httpx.TimeoutException:
            logger.error("Ollama request timed out for model %s", model)
            raise
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Ollama HTTP error %s for model %s: %s",
                exc.response.status_code,
                model,
                exc.response.text[:200],
            )
            raise

    async def stream(
        self,
        prompt: str,
        model: str,
        system_prompt: str = "",
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream response tokens one-by-one via Ollama's streaming API."""
        payload = self._build_payload(
            prompt, model, system_prompt, temperature, stream=True,
        )
        logger.debug("Ollama stream: model=%s prompt_len=%d", model, len(prompt))

        try:
            async with self._client.stream(
                "POST", "/api/chat", json=payload,
            ) as response:
                response.raise_for_status()
                in_think_block = False
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        import json as _json

                        chunk: dict[str, Any] = _json.loads(line)
                    except ValueError:
                        continue
                    token = chunk.get("message", {}).get("content", "")
                    if not token:
                        continue

                    # Handle <think> blocks in streaming mode for deepseek-r1
                    if "deepseek" in model.lower():
                        if "<think>" in token:
                            in_think_block = True
                            continue
                        if "</think>" in token:
                            in_think_block = False
                            continue
                        if in_think_block:
                            continue

                    yield token
        except httpx.TimeoutException:
            logger.error("Ollama stream timed out for model %s", model)
            raise
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Ollama stream HTTP error %s for model %s",
                exc.response.status_code,
                model,
            )
            raise

    async def health_check(self) -> bool:
        """Check Ollama availability via ``GET /api/tags``."""
        try:
            response = await self._client.get("/api/tags", timeout=5.0)
            return response.status_code == 200
        except (httpx.HTTPError, httpx.TimeoutException):
            logger.warning("Ollama health check failed at %s", self._base_url)
            return False

    # -- Internals ------------------------------------------------------------

    @staticmethod
    def _build_payload(
        prompt: str,
        model: str,
        system_prompt: str,
        temperature: float,
        *,
        stream: bool,
    ) -> dict[str, Any]:
        """Build the JSON payload for ``/api/chat``."""
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        return {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": temperature},
        }

    # -- Lifecycle ------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()
