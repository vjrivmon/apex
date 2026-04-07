"""ArchitectAgent -- designs multi-agent system architectures.

Uses a decision-tree approach to select the optimal SMA pattern, then
elaborates the full architecture with agent specifications, a diagram,
justification, and academic references.

Decision tree:
    Has main task with specialised subtasks?
      YES -> Sequential or parallel?
        Sequential -> PIPELINE
        Parallel   -> ORCHESTRATOR-WORKER
      NO  -> Consensus needed?
        YES -> CONSENSUS
        NO  -> Specialists that cross-consult?
          YES -> EXPERT NETWORK
          NO  -> SINGLE AGENT / REACTOR / REFLECTION
    HYBRID: multiple levels combined
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.domain import AgentSpec, Architecture
from core.ports import ILLMProvider, IVectorStore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are APEX's architecture designer.  You specialise in multi-agent "
    "system (SMA) architecture patterns.  You know these patterns deeply:\n"
    "1. PIPELINE — sequential processing stages\n"
    "2. ORCHESTRATOR-WORKER — central coordinator + specialist workers\n"
    "3. CONSENSUS — multiple agents vote / deliberate\n"
    "4. EXPERT NETWORK — specialists cross-consult on demand\n"
    "5. REACTOR — event-driven agents reacting to stimuli\n"
    "6. REFLECTION — self-evaluating agent with inner critic\n"
    "7. HYBRID — combination of multiple patterns\n\n"
    "Always respond in valid JSON as instructed in the prompt."
)

_DECISION_TREE_PROMPT = """\
Analyse the following problem specification and RAG context to select the \
optimal multi-agent architecture pattern.

Apply this decision tree:
1. Does the problem have a main task decomposable into specialised subtasks?
   YES -> Are subtasks sequential or parallel?
     Sequential -> PIPELINE
     Parallel   -> ORCHESTRATOR-WORKER
   NO -> 2.
2. Is consensus or deliberation among multiple perspectives needed?
   YES -> CONSENSUS
   NO  -> 3.
3. Are there domain specialists that need to cross-consult?
   YES -> EXPERT_NETWORK
   NO  -> 4.
4. Is it event-driven / reactive?
   YES -> REACTOR
   NO  -> 5.
5. Does the agent need self-evaluation / iterative refinement?
   YES -> REFLECTION
   NO  -> SINGLE_AGENT
6. If multiple patterns apply at different levels -> HYBRID

Problem specification:
{problem_analysis}

RAG patterns & cases:
{rag_patterns}

Respond with JSON:
{{
  "pattern": "one of: pipeline, orchestrator-worker, consensus, expert-network, reactor, reflection, hybrid",
  "pattern_ref": "Academic paper or real-case reference",
  "justification": "2-3 sentences explaining WHY this pattern fits",
  "communication": "synchronous | asynchronous | queue-based",
  "agents": [
    {{
      "name": "AgentName",
      "responsibility": "One sentence",
      "input_description": "What it receives",
      "output_description": "What it produces",
      "recommended_model": "model name or tier (e.g. gpt-4, claude-3, llama-70b, small-local)",
      "needs_rag": true/false,
      "needs_memory": true/false,
      "failure_mode": "return_empty | retry_once | escalate | fallback_default",
      "tools": ["tool1", "tool2"],
      "dependencies": ["OtherAgentName"]
    }}
  ],
  "ascii_diagram": "ASCII art showing agents and their connections (multi-line string)"
}}

Rules:
- Each agent has exactly ONE responsibility.
- If an agent does two things, split it into two agents.
- Always include error handling / failure modes.
- The diagram must show data flow direction with arrows (->).
- Include 3-8 agents (prefer fewer, well-defined agents).
"""


class ArchitectAgent:
    """Designs SMA architectures from problem specifications and RAG context."""

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

    async def design_architecture(
        self,
        problem_analysis: str,
        rag_patterns: dict[str, list[dict]],
        llm: ILLMProvider | None = None,
    ) -> Architecture:
        """Design a complete SMA architecture for the given problem.

        Parameters
        ----------
        problem_analysis:
            The SPEC content or problem description.
        rag_patterns:
            Dict with ``patterns`` and ``cases`` lists from RAGAgent.
        llm:
            Optional LLM override.

        Returns
        -------
        A fully populated ``Architecture`` domain entity.
        """
        active_llm = llm or self._llm

        rag_summary = self._format_rag(rag_patterns)
        prompt = _DECISION_TREE_PROMPT.format(
            problem_analysis=problem_analysis,
            rag_patterns=rag_summary,
        )

        raw = await active_llm.generate(
            prompt=prompt,
            model="default",
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.6,
        )

        try:
            parsed = self._parse_json(raw)
            return self._build_architecture(parsed)
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.warning("Failed to parse architect LLM output: %s", exc)
            return self._fallback_architecture(problem_analysis)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_architecture(data: dict[str, Any]) -> Architecture:
        """Construct an ``Architecture`` entity from parsed LLM JSON."""
        agents = [
            AgentSpec(
                name=a["name"],
                responsibility=a["responsibility"],
                input_description=a.get("input_description", ""),
                output_description=a.get("output_description", ""),
                recommended_model=a.get("recommended_model", "default"),
                needs_rag=a.get("needs_rag", False),
                needs_memory=a.get("needs_memory", False),
                failure_mode=a.get("failure_mode", "return_empty"),
                tools=a.get("tools", []),
                dependencies=a.get("dependencies", []),
            )
            for a in data.get("agents", [])
        ]

        return Architecture(
            pattern=data["pattern"],
            pattern_ref=data.get("pattern_ref", ""),
            justification=data.get("justification", ""),
            ascii_diagram=data.get("ascii_diagram", "(no diagram)"),
            agents=agents,
            communication=data.get("communication", "synchronous"),
        )

    @staticmethod
    def _fallback_architecture(problem: str) -> Architecture:
        """Return a safe default when LLM output is unusable."""
        return Architecture(
            pattern="orchestrator-worker",
            pattern_ref="Chase (2023) — Orchestration Patterns for LLM Applications",
            justification=(
                "Defaulting to orchestrator-worker as the safest general-purpose "
                "pattern.  A central coordinator delegates subtasks to specialist "
                "workers, providing clear control flow and error isolation."
            ),
            ascii_diagram=(
                "         +---------------+\n"
                "         | Orchestrator  |\n"
                "         +------+--------+\n"
                "                |\n"
                "     +----------+----------+\n"
                "     |          |          |\n"
                " +---v---+ +---v---+ +---v---+\n"
                " |Worker1| |Worker2| |Worker3|\n"
                " +-------+ +-------+ +-------+"
            ),
            agents=[
                AgentSpec(
                    name="Orchestrator",
                    responsibility="Coordinate task distribution and collect results.",
                    input_description="User request",
                    output_description="Aggregated result",
                    recommended_model="default",
                ),
                AgentSpec(
                    name="Worker",
                    responsibility="Process a single subtask as delegated.",
                    input_description="Subtask specification",
                    output_description="Subtask result",
                    recommended_model="default",
                ),
            ],
            communication="synchronous",
        )

    @staticmethod
    def _format_rag(rag_data: dict[str, list[dict]]) -> str:
        """Format RAG results into a concise text block for the prompt."""
        lines: list[str] = []
        for p in rag_data.get("patterns", []):
            name = p.get("name", p.get("id", "?"))
            desc = p.get("description", p.get("text", ""))[:300]
            lines.append(f"Pattern: {name} — {desc}")

        for c in rag_data.get("cases", []):
            name = c.get("name", c.get("id", "?"))
            desc = c.get("description", c.get("text", ""))[:300]
            lines.append(f"Case: {name} — {desc}")

        return "\n".join(lines) if lines else "(no RAG context)"

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
