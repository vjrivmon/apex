"""EvalAgent -- designs evaluation strategies for generated SMA systems.

Proposes metrics, benchmarks, and testing strategies tailored to the
specific architecture pattern.  Different patterns demand different
evaluation approaches:
- Pipeline: latency per stage, end-to-end completion rate
- Orchestrator-Worker: task distribution fairness, worker utilisation
- Consensus: agreement rate, decision accuracy
- Expert Network: consultation efficiency, knowledge coverage
- Reactor: event throughput, response latency
- Reflection: improvement rate across iterations
"""

from __future__ import annotations

import logging

from core.domain import Architecture
from core.ports import ILLMProvider, IVectorStore

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are an evaluation strategist for multi-agent systems.  You design "
    "metrics, benchmarks, and testing plans that objectively measure whether "
    "an SMA achieves its goals.  Write in clear, actionable Markdown."
)

_EVALUATION_PROMPT = """\
Design a comprehensive evaluation strategy for the following multi-agent \
system architecture.

Architecture:
- Pattern: {pattern}
- Communication: {communication}
- Agents ({agent_count}):
{agent_summary}

Justification: {justification}

Create an evaluation plan covering:

## 1. Pattern-Specific Metrics
Metrics that directly test whether the {pattern} pattern is working correctly.
{pattern_hints}

## 2. Agent-Level Metrics
For each agent, define:
- **Accuracy**: how correct are its outputs?
- **Latency**: p50 and p99 response time targets
- **Reliability**: expected uptime / success rate
- **Resource usage**: memory, tokens consumed

## 3. System-Level Metrics
- End-to-end latency (user request -> final response)
- Total token cost per request
- Error propagation (does one agent failure cascade?)
- Throughput under load

## 4. Benchmark Strategy
- Define 3-5 test scenarios (easy, medium, hard, edge case, adversarial)
- For each scenario: input description, expected output, pass criteria
- Specify which agents are tested by each scenario

## 5. Regression Testing
- How to detect quality degradation after changes
- Automated test suite structure
- CI/CD integration recommendations

## 6. Human Evaluation Protocol
- When automated metrics are insufficient
- Rubric for human evaluators
- Inter-rater reliability expectations

Write the full plan in Markdown.  Be specific with target numbers \
(e.g., "p99 latency < 3s" not "latency should be low").
"""

# Pattern-specific metric hints to guide the LLM.
_PATTERN_HINTS: dict[str, str] = {
    "pipeline": (
        "- Stage-by-stage latency breakdown\n"
        "- Throughput (items/second through the full pipeline)\n"
        "- Error rate at each stage\n"
        "- Backpressure handling under load"
    ),
    "orchestrator-worker": (
        "- Task routing accuracy (correct worker selected)\n"
        "- Worker utilisation balance\n"
        "- Orchestrator overhead (time spent routing vs. working)\n"
        "- Graceful degradation when a worker fails"
    ),
    "consensus": (
        "- Agreement rate among agents\n"
        "- Decision accuracy vs. ground truth\n"
        "- Deliberation rounds needed\n"
        "- Minority opinion quality (was dissent valuable?)"
    ),
    "expert-network": (
        "- Consultation efficiency (how many experts consulted per query)\n"
        "- Knowledge coverage (are all domains reachable?)\n"
        "- Cross-consultation depth\n"
        "- Expert selection accuracy"
    ),
    "reactor": (
        "- Event throughput (events/second)\n"
        "- Response latency (event -> action)\n"
        "- Event ordering correctness\n"
        "- Missed event rate under load"
    ),
    "reflection": (
        "- Improvement rate per iteration\n"
        "- Convergence speed (iterations to stable output)\n"
        "- Self-critique accuracy (did it catch real issues?)\n"
        "- Diminishing returns detection"
    ),
    "hybrid": (
        "- Metrics from each constituent pattern (see above)\n"
        "- Inter-layer communication overhead\n"
        "- Complexity vs. performance trade-off\n"
        "- Failure isolation between layers"
    ),
}


class EvalAgent:
    """Designs evaluation strategies tailored to specific SMA architectures."""

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

    async def design_evaluation(
        self,
        architecture: Architecture,
        llm: ILLMProvider | None = None,
    ) -> str:
        """Design a complete evaluation plan for the given architecture.

        Parameters
        ----------
        architecture:
            The ``Architecture`` entity to evaluate.
        llm:
            Optional LLM override.

        Returns
        -------
        A Markdown string containing the full evaluation plan.
        """
        active_llm = llm or self._llm

        agent_summary = self._format_agents(architecture)
        pattern_hints = _PATTERN_HINTS.get(
            architecture.pattern.lower(),
            _PATTERN_HINTS.get("hybrid", "- Define metrics relevant to this custom pattern."),
        )

        prompt = _EVALUATION_PROMPT.format(
            pattern=architecture.pattern,
            communication=architecture.communication,
            agent_count=architecture.agent_count,
            agent_summary=agent_summary,
            justification=architecture.justification,
            pattern_hints=pattern_hints,
        )

        try:
            plan = await active_llm.generate(
                prompt=prompt,
                model="default",
                system_prompt=_SYSTEM_PROMPT,
                temperature=0.5,
            )
            return plan.strip()
        except Exception:
            logger.exception("EvalAgent failed to generate evaluation plan")
            return self._fallback_plan(architecture)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_agents(architecture: Architecture) -> str:
        """Format agent specs for the evaluation prompt."""
        lines: list[str] = []
        for agent in architecture.agents:
            lines.append(
                f"  - {agent.name}: {agent.responsibility} "
                f"(model: {agent.recommended_model}, "
                f"failure: {agent.failure_mode})"
            )
        return "\n".join(lines) if lines else "  (no agents defined)"

    @staticmethod
    def _fallback_plan(architecture: Architecture) -> str:
        """Return a minimal evaluation plan when the LLM is unavailable."""
        agent_bullets = "\n".join(
            f"- **{a.name}**: measure accuracy, latency (p50 < 1s, p99 < 5s), "
            f"and error rate (< 5%)"
            for a in architecture.agents
        )

        return (
            f"# Evaluation Plan — {architecture.pattern.title()} SMA\n\n"
            f"## Pattern-Specific Metrics\n"
            f"Metrics for the `{architecture.pattern}` pattern should be defined "
            f"based on the system's primary goals.\n\n"
            f"## Agent-Level Metrics\n"
            f"{agent_bullets}\n\n"
            f"## System-Level Metrics\n"
            f"- End-to-end latency: target p99 < 10s\n"
            f"- Error rate: < 2% of requests\n"
            f"- Token cost: track per-request and set budget alerts\n\n"
            f"## Benchmark Scenarios\n"
            f"1. **Happy path**: standard request with expected input\n"
            f"2. **Edge case**: unusual but valid input\n"
            f"3. **Adversarial**: malformed or malicious input\n\n"
            f"## Regression Testing\n"
            f"- Automated test suite running on every commit\n"
            f"- Golden dataset of input/output pairs\n"
            f"- Alert on >5% degradation in any metric\n"
        )
