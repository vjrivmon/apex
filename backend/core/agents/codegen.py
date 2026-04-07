"""CodeGenAgent -- generates complete SMA code from architecture designs.

Produces a full hexagonal-architecture project in either TypeScript or Python,
including domain entities, agent classes, ports, infrastructure stubs,
and an orchestrator that wires everything together.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.domain import Architecture
from core.ports import ILLMProvider, IVectorStore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a senior software engineer specialised in multi-agent systems.  "
    "You generate production-quality code following hexagonal architecture.  "
    "All code must include type hints (Python) or TypeScript types, proper "
    "error handling, and clear docstrings/JSDoc.  "
    "Never import from infrastructure in domain code.  "
    "Always respond in valid JSON as instructed."
)

_GENERATION_PROMPT = """\
Generate a complete multi-agent system project based on the following \
architecture and specification.

Architecture:
- Pattern: {pattern}
- Communication: {communication}
- Agents: {agent_summary}

Diagram:
{diagram}

Specification:
{spec}

Generate ALL files needed for a working project using hexagonal architecture.
The project structure must follow:

```
src/
├── domain/          # Entities and business rules (NO external deps)
│   ├── agents/      # Agent entity definitions
│   └── types.ts/py  # Shared types
├── application/     # Use cases / orchestration
│   └── orchestrator.ts/py
├── ports/           # Interfaces (in/out)
│   ├── llm_provider.ts/py
│   └── message_bus.ts/py
├── infrastructure/  # Adapters (LLM, DB, etc.)
│   └── adapters/
└── main.ts/py       # Entry point
```

Respond with a JSON object where each key is a file path and each value is \
the complete file content:

{{
  "src/domain/types.py": "# content...",
  "src/domain/agents/agent_name.py": "# content...",
  "src/application/orchestrator.py": "# content...",
  "src/ports/llm_provider.py": "# content...",
  "src/infrastructure/adapters/ollama_adapter.py": "# content...",
  "src/main.py": "# content...",
  "requirements.txt": "# or package.json",
  "README.md": "# Project docs"
}}

Rules:
- Generate REAL, RUNNABLE code — not placeholders or TODOs.
- Each agent must have: __init__, process method, error handling.
- The orchestrator must route to agents based on the {pattern} pattern.
- Include a requirements.txt or package.json.
- Include a README.md with setup instructions.
- Use async/await for all agent communication.
- Keep each file under 200 lines.  Split if larger.
"""


class CodeGenAgent:
    """Generates complete SMA project code from architecture designs."""

    def __init__(
        self,
        llm: ILLMProvider,
        vector_store: IVectorStore | None = None,
    ) -> None:
        self._llm = llm
        self._vector_store = vector_store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def generate(
        self,
        architecture: Architecture,
        spec: str,
        llm: ILLMProvider | None = None,
    ) -> dict[str, str]:
        """Generate all source files for the designed SMA.

        Parameters
        ----------
        architecture:
            The approved ``Architecture`` entity.
        spec:
            The SPEC.md content describing the project requirements.
        llm:
            Optional LLM override.

        Returns
        -------
        Dict mapping file paths to their full content.
        """
        active_llm = llm or self._llm

        agent_summary = self._summarise_agents(architecture)

        prompt = _GENERATION_PROMPT.format(
            pattern=architecture.pattern,
            communication=architecture.communication,
            agent_summary=agent_summary,
            diagram=architecture.ascii_diagram,
            spec=spec[:3000],  # Truncate to stay within context limits.
        )

        raw = await active_llm.generate(
            prompt=prompt,
            model="default",
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.4,
        )

        try:
            files = self._parse_json(raw)
            if not isinstance(files, dict):
                raise ValueError("Expected a JSON object with file paths as keys")

            validated = self._validate_files(files)
            logger.info("CodeGen produced %d files", len(validated))
            return validated

        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse CodeGen output: %s", exc)
            # Attempt to split and recover partial output.
            recovered = self._attempt_recovery(raw, architecture)
            if recovered:
                return recovered
            return self._fallback_files(architecture)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _summarise_agents(architecture: Architecture) -> str:
        """Build a concise summary of agents for the generation prompt."""
        lines: list[str] = []
        for agent in architecture.agents:
            deps = ", ".join(agent.dependencies) if agent.dependencies else "none"
            lines.append(
                f"- {agent.name}: {agent.responsibility} "
                f"(in: {agent.input_description}, out: {agent.output_description}, "
                f"deps: {deps})"
            )
        return "\n".join(lines) if lines else "(no agents defined)"

    @staticmethod
    def _validate_files(files: dict[str, Any]) -> dict[str, str]:
        """Ensure all values are non-empty strings and paths look reasonable."""
        validated: dict[str, str] = {}
        for path, content in files.items():
            if not isinstance(path, str) or not path.strip():
                continue
            if not isinstance(content, str):
                content = str(content)
            if not content.strip():
                continue
            # Normalise path separators.
            clean_path = path.strip().replace("\\", "/")
            validated[clean_path] = content
        return validated

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Extract JSON from potentially markdown-fenced LLM output."""
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
            if "```" in cleaned:
                cleaned = cleaned[: cleaned.rindex("```")]
            cleaned = cleaned.strip()
        return json.loads(cleaned)

    def _attempt_recovery(
        self,
        raw: str,
        architecture: Architecture,
    ) -> dict[str, str] | None:
        """Try to extract file blocks from non-JSON LLM output.

        Some models produce files separated by markdown headings or fences
        instead of strict JSON.  We try to recover individual files.
        """
        files: dict[str, str] = {}
        current_path: str | None = None
        current_lines: list[str] = []

        for line in raw.split("\n"):
            stripped = line.strip()

            # Detect file path markers like "### src/main.py" or "**src/main.py**"
            if stripped.startswith("### ") or stripped.startswith("**"):
                if current_path and current_lines:
                    files[current_path] = "\n".join(current_lines)
                potential = stripped.lstrip("#* ").rstrip("*: ")
                if "/" in potential or potential.endswith((".py", ".ts", ".json", ".md", ".txt")):
                    current_path = potential
                    current_lines = []
                    continue

            if current_path is not None:
                # Skip markdown code fences.
                if stripped.startswith("```"):
                    continue
                current_lines.append(line)

        # Flush the last file.
        if current_path and current_lines:
            files[current_path] = "\n".join(current_lines)

        return files if files else None

    @staticmethod
    def _fallback_files(architecture: Architecture) -> dict[str, str]:
        """Generate minimal scaffold files when all parsing fails."""
        agents_code: list[str] = []
        for agent in architecture.agents:
            safe_name = agent.name.lower().replace(" ", "_").replace("-", "_")
            agents_code.append(
                f'class {agent.name.replace(" ", "")}Agent:\n'
                f'    """Agent: {agent.responsibility}"""\n\n'
                f"    async def process(self, input_data: str) -> str:\n"
                f'        raise NotImplementedError("TODO: implement {safe_name}")\n'
            )

        agents_content = "\n\n".join(agents_code) if agents_code else "# No agents defined\n"

        orchestrator_imports = ", ".join(
            f'{a.name.replace(" ", "")}Agent' for a in architecture.agents
        )

        return {
            "src/domain/agents/__init__.py": (
                f'"""Agent definitions for {architecture.pattern} architecture."""\n\n'
                f"{agents_content}"
            ),
            "src/application/orchestrator.py": (
                f'"""Orchestrator for {architecture.pattern} pattern."""\n\n'
                f"from src.domain.agents import {orchestrator_imports}\n\n\n"
                f"class Orchestrator:\n"
                f'    """Routes requests through the {architecture.pattern} pipeline."""\n\n'
                f"    async def run(self, input_data: str) -> str:\n"
                f'        raise NotImplementedError("TODO: implement orchestration")\n'
            ),
            "src/main.py": (
                f'"""Entry point for the {architecture.pattern} SMA."""\n\n'
                f"from src.application.orchestrator import Orchestrator\n\n\n"
                f"async def main() -> None:\n"
                f"    orchestrator = Orchestrator()\n"
                f'    result = await orchestrator.run("Hello")\n'
                f"    print(result)\n"
            ),
            "requirements.txt": "# Add project dependencies here\n",
            "README.md": (
                f"# {architecture.pattern.title()} SMA\n\n"
                f"{architecture.justification}\n\n"
                f"## Architecture\n\n"
                f"```\n{architecture.ascii_diagram}\n```\n"
            ),
        }
