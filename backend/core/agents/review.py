"""ReviewAgent -- code and architecture quality reviewer.

Inspired by gstack's multi-pass review approach.  Checks generated code
and architectures for:
- OWASP security basics
- Type safety and error handling
- Architecture compliance (hexagonal boundaries)
- Completeness (all agents implemented, all ports defined)
- Code quality (naming, structure, documentation)
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.domain import Architecture
from core.ports import ILLMProvider, IVectorStore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a senior code reviewer specialising in multi-agent systems and "
    "hexagonal architecture.  You review for security, quality, correctness, "
    "and architecture compliance.  Be thorough but constructive.  "
    "Always respond in valid JSON as instructed."
)

_REVIEW_PROMPT = """\
Review the following multi-agent system design and/or generated code.

Architecture:
- Pattern: {pattern}
- Communication: {communication}
- Agents ({agent_count}):
{agent_summary}

{code_section}

Perform these review passes:

**Pass 1 — Security (OWASP basics)**
- Input validation on all agent boundaries
- No secrets in code or comments
- Proper error messages (no stack traces leaked)
- Rate limiting considerations
- Injection prevention

**Pass 2 — Type Safety & Error Handling**
- All public methods have type hints / types
- Errors are caught and handled gracefully
- Failure modes match agent spec
- No uncaught promise rejections / unhandled exceptions

**Pass 3 — Architecture Compliance**
- Domain layer has ZERO infrastructure imports
- All external dependencies go through ports
- Orchestrator delegates but does not process
- Agents have single responsibility

**Pass 4 — Completeness**
- All agents from the architecture are implemented
- All ports have at least one adapter
- Entry point / main exists and is runnable
- README / documentation present

**Pass 5 — Code Quality**
- Meaningful names (no single-letter variables in business logic)
- Functions under 50 lines
- Proper docstrings / JSDoc on public APIs
- No dead code or TODO placeholders in production paths

Respond with JSON:
{{
  "approved": true/false,
  "overall_score": 0-100,
  "issues": [
    {{
      "pass": "security|type_safety|architecture|completeness|quality",
      "severity": "critical|high|medium|low",
      "file": "path/to/file or 'architecture'",
      "line": null or line_number,
      "description": "What is wrong",
      "suggestion": "How to fix it"
    }}
  ],
  "suggestions": [
    "General improvement suggestion 1",
    "General improvement suggestion 2"
  ],
  "summary": "2-3 sentence overall assessment"
}}

Rules:
- "approved" is true ONLY if there are ZERO critical or high-severity issues.
- Be specific: reference file names and line numbers where possible.
- Every issue MUST have a concrete suggestion for how to fix it.
"""


class ReviewAgent:
    """Reviews SMA designs and generated code for quality and compliance."""

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

    async def review(
        self,
        generated_code: dict[str, str],
        architecture: Architecture,
        llm: ILLMProvider | None = None,
    ) -> dict[str, Any]:
        """Review generated code and architecture for quality and compliance.

        Parameters
        ----------
        generated_code:
            Dict mapping file paths to their content.  May be empty when
            reviewing architecture only.
        architecture:
            The ``Architecture`` entity to review.
        llm:
            Optional LLM override.

        Returns
        -------
        Dict with ``approved`` (bool), ``issues`` (list), ``suggestions``
        (list), ``overall_score`` (int), and ``summary`` (str).
        """
        active_llm = llm or self._llm

        agent_summary = self._format_agents(architecture)
        code_section = self._format_code(generated_code)

        prompt = _REVIEW_PROMPT.format(
            pattern=architecture.pattern,
            communication=architecture.communication,
            agent_count=architecture.agent_count,
            agent_summary=agent_summary,
            code_section=code_section,
        )

        raw = await active_llm.generate(
            prompt=prompt,
            model="default",
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.3,
        )

        try:
            parsed = self._parse_json(raw)
            return self._normalise_result(parsed)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Failed to parse review output: %s", exc)
            return self._fallback_result()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_agents(architecture: Architecture) -> str:
        """Format agent specs for the review prompt."""
        lines: list[str] = []
        for agent in architecture.agents:
            lines.append(
                f"  - {agent.name}: {agent.responsibility}\n"
                f"    failure_mode={agent.failure_mode}, "
                f"needs_rag={agent.needs_rag}, "
                f"deps={agent.dependencies}"
            )
        return "\n".join(lines) if lines else "  (no agents defined)"

    @staticmethod
    def _format_code(code: dict[str, str]) -> str:
        """Format generated code files for the review prompt."""
        if not code:
            return "Generated code: (none yet — reviewing architecture only)"

        parts: list[str] = ["Generated code:"]
        for path, content in code.items():
            # Truncate very long files to keep within LLM context.
            truncated = content[:2000]
            if len(content) > 2000:
                truncated += f"\n... (truncated, {len(content)} chars total)"
            parts.append(f"\n--- {path} ---\n{truncated}")

        return "\n".join(parts)

    @staticmethod
    def _normalise_result(parsed: dict[str, Any]) -> dict[str, Any]:
        """Ensure the review result has all expected keys with correct types."""
        issues = parsed.get("issues", [])

        # Derive approval from issues if not explicitly set.
        has_blocking = any(
            issue.get("severity") in ("critical", "high")
            for issue in issues
            if isinstance(issue, dict)
        )

        return {
            "approved": parsed.get("approved", not has_blocking),
            "overall_score": int(parsed.get("overall_score", 50)),
            "issues": [
                {
                    "pass": issue.get("pass", "unknown"),
                    "severity": issue.get("severity", "medium"),
                    "file": issue.get("file", "unknown"),
                    "line": issue.get("line"),
                    "description": issue.get("description", ""),
                    "suggestion": issue.get("suggestion", ""),
                }
                for issue in issues
                if isinstance(issue, dict)
            ],
            "suggestions": [
                s for s in parsed.get("suggestions", []) if isinstance(s, str)
            ],
            "summary": parsed.get("summary", "Review completed."),
        }

    @staticmethod
    def _fallback_result() -> dict[str, Any]:
        """Return a cautious result when the LLM output is unparseable."""
        return {
            "approved": False,
            "overall_score": 0,
            "issues": [
                {
                    "pass": "unknown",
                    "severity": "high",
                    "file": "review_agent",
                    "line": None,
                    "description": (
                        "The review agent could not produce a parseable assessment. "
                        "This likely indicates the code or architecture is too complex "
                        "for a single-pass review."
                    ),
                    "suggestion": (
                        "Retry the review, or simplify the architecture to reduce "
                        "the amount of code reviewed at once."
                    ),
                }
            ],
            "suggestions": [
                "Consider breaking the review into smaller scopes (per-agent)."
            ],
            "summary": "Review failed to produce a parseable result.",
        }

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
