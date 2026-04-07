"""ConversationAgent -- natural-language interface for the APEX interview.

Responsible for:
- Smart assessment: decides whether the user's initial idea is detailed enough
  to skip the interview entirely.
- Generating interview rounds with clickable options enriched by RAG context.
- Synthesising a SPEC.md from the completed interview transcript.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from core.domain import (
    InterviewOption,
    InterviewRound,
    Session,
)
from core.ports import ILLMProvider, IVectorStore

logger = logging.getLogger(__name__)

# Maximum number of interview rounds before forcing completion.
_MAX_ROUNDS = 8

# Minimum rounds to ensure baseline information is gathered.
_MIN_ROUNDS = 3

_SYSTEM_PROMPT = (
    "You are APEX's interview engine.  Your job is to understand what kind of "
    "multi-agent system (SMA) the user needs.  Ask focused questions about:\n"
    "1. The core problem / domain\n"
    "2. The desired agent roles and responsibilities\n"
    "3. Communication patterns between agents\n"
    "4. Data flow and processing requirements\n"
    "5. Constraints (latency, cost, accuracy, privacy)\n"
    "6. Expected scale and deployment environment\n\n"
    "Always respond in valid JSON as instructed in the prompt."
)


class ConversationAgent:
    """Manages the interview flow that gathers requirements for SMA design."""

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

    async def assess_completeness(
        self,
        idea: str,
        rag_context: dict[str, list[dict]],
        llm: ILLMProvider | None = None,
    ) -> bool:
        """Decide whether *idea* contains enough information to skip the interview.

        Returns ``True`` when the description already covers the six key
        dimensions (problem, agents, communication, data, constraints, scale).
        """
        active_llm = llm or self._llm

        context_summary = self._summarise_rag_context(rag_context)

        prompt = (
            "Evaluate whether the following user idea is detailed enough to design "
            "a multi-agent system WITHOUT further questions.\n\n"
            "The idea must cover ALL of these dimensions to be considered complete:\n"
            "1. Core problem / domain clearly stated\n"
            "2. Agent roles or responsibilities identifiable\n"
            "3. Communication pattern implied or stated\n"
            "4. Data flow described\n"
            "5. Constraints mentioned (latency, cost, accuracy, etc.)\n"
            "6. Scale / deployment context given\n\n"
            f"RAG context (similar patterns):\n{context_summary}\n\n"
            f"User idea:\n{idea}\n\n"
            'Respond with a JSON object: {{"complete": true/false, "missing": ["dimension1", ...]}}'
        )

        raw = await active_llm.generate(
            prompt=prompt,
            model="default",
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.3,
        )

        try:
            parsed = self._parse_json(raw)
            return bool(parsed.get("complete", False))
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse completeness assessment; defaulting to incomplete.")
            return False

    async def generate_round(
        self,
        session: Session,
        rag_context: dict[str, list[dict]],
        llm: ILLMProvider | None = None,
    ) -> InterviewRound:
        """Generate the next interview round with clickable options.

        Each option is enriched by RAG context so the user can see real-world
        pattern examples alongside abstract choices.
        """
        active_llm = llm or self._llm

        round_number = len(session.interview_rounds) + 1

        # Guard: force completion after MAX_ROUNDS.
        if round_number > _MAX_ROUNDS:
            return self._build_final_confirmation_round(round_number)

        transcript = self._build_transcript(session)
        context_summary = self._summarise_rag_context(rag_context)

        prompt = (
            f"You are conducting interview round {round_number} (of up to {_MAX_ROUNDS}).\n\n"
            f"Transcript so far:\n{transcript}\n\n"
            f"RAG context (known patterns and real cases):\n{context_summary}\n\n"
            "Generate ONE focused question that fills the biggest gap in our "
            "understanding of the user's multi-agent system.\n\n"
            "Respond with JSON:\n"
            "{\n"
            '  "question": "...",\n'
            '  "options": [\n'
            '    {"label": "Short name", "description": "1-2 sentences", "value": "snake_case_id", "rag_hint": "keyword for next RAG query"},\n'
            "    ... (3-5 options)\n"
            "  ]\n"
            "}\n\n"
            "Rules:\n"
            "- Options must be mutually exclusive and exhaustive (add 'other' if needed).\n"
            "- Use RAG context to make options concrete (mention real patterns).\n"
            f"- If round >= {_MIN_ROUNDS} and all 6 dimensions are covered, "
            'set "question" to "DONE" and "options" to [].'
        )

        raw = await active_llm.generate(
            prompt=prompt,
            model="default",
            system_prompt=_SYSTEM_PROMPT,
            temperature=0.7,
        )

        try:
            parsed = self._parse_json(raw)
        except (json.JSONDecodeError, ValueError):
            logger.warning("Failed to parse round generation; returning fallback question.")
            return self._build_fallback_round(round_number)

        # Handle "DONE" signal from the LLM.
        question = parsed.get("question", "")
        if question.strip().upper() == "DONE":
            return self._build_final_confirmation_round(round_number)

        options = [
            InterviewOption(
                label=opt.get("label", f"Option {i + 1}"),
                description=opt.get("description", ""),
                value=opt.get("value", f"option_{i + 1}"),
                rag_hint=opt.get("rag_hint", ""),
            )
            for i, opt in enumerate(parsed.get("options", []))
        ]

        rag_texts = [
            doc.get("text", doc.get("content", ""))
            for doc in rag_context.get("patterns", []) + rag_context.get("cases", [])
            if isinstance(doc, dict)
        ]

        return InterviewRound(
            round_number=round_number,
            question=question,
            options=options,
            rag_context=rag_texts[:5],  # Keep top-5 references.
        )

    async def generate_spec(
        self,
        session: Session,
        llm: ILLMProvider | None = None,
    ) -> str:
        """Synthesise a SPEC.md document from the completed interview transcript."""
        active_llm = llm or self._llm

        transcript = self._build_transcript(session)

        prompt = (
            "Using the following interview transcript, generate a comprehensive "
            "SPEC.md for a multi-agent system.\n\n"
            f"Transcript:\n{transcript}\n\n"
            "The SPEC must include these sections:\n"
            "# Project Name\n"
            "## Problem Statement\n"
            "## Objectives\n"
            "## Agent Roles\n"
            "  - Name, responsibility, inputs, outputs for each agent\n"
            "## Communication Pattern\n"
            "## Data Flow\n"
            "## Constraints\n"
            "  - Latency, cost, accuracy, privacy, scale\n"
            "## Success Metrics\n"
            "## Open Questions\n\n"
            "Write in Markdown.  Be specific and actionable.  "
            "Do NOT add information the user did not provide."
        )

        spec = await active_llm.generate(
            prompt=prompt,
            model="default",
            system_prompt=(
                "You are a technical writer creating a specification for a "
                "multi-agent system design."
            ),
            temperature=0.5,
        )

        return spec.strip()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_transcript(session: Session) -> str:
        """Build a plain-text transcript from session messages and rounds."""
        parts: list[str] = []

        if session.problem_description:
            parts.append(f"[Initial idea]: {session.problem_description}")

        for rnd in session.interview_rounds:
            parts.append(f"\n[Round {rnd.round_number}] Q: {rnd.question}")
            if rnd.selected_value:
                parts.append(f"[Round {rnd.round_number}] A: {rnd.selected_value}")

        return "\n".join(parts) if parts else "(no transcript yet)"

    @staticmethod
    def _summarise_rag_context(rag_context: dict[str, list[dict]]) -> str:
        """Condense RAG results into a short text block."""
        lines: list[str] = []
        for pattern in rag_context.get("patterns", []):
            name = pattern.get("name", pattern.get("id", "unknown"))
            desc = pattern.get("description", pattern.get("text", ""))
            lines.append(f"- Pattern '{name}': {desc[:200]}")

        for case in rag_context.get("cases", []):
            name = case.get("name", case.get("id", "unknown"))
            desc = case.get("description", case.get("text", ""))
            lines.append(f"- Case '{name}': {desc[:200]}")

        return "\n".join(lines) if lines else "(no RAG context available)"

    @staticmethod
    def _parse_json(raw: str) -> dict[str, Any]:
        """Extract and parse the first JSON object from *raw*."""
        # Handle cases where the LLM wraps JSON in markdown fences.
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            # Remove opening fence (```json or ```)
            first_newline = cleaned.index("\n")
            cleaned = cleaned[first_newline + 1 :]
            # Remove closing fence
            if "```" in cleaned:
                cleaned = cleaned[: cleaned.rindex("```")]
            cleaned = cleaned.strip()

        return json.loads(cleaned)

    @staticmethod
    def _build_fallback_round(round_number: int) -> InterviewRound:
        """Return a generic round when LLM output is unparseable."""
        return InterviewRound(
            round_number=round_number,
            question=(
                "Could you describe the main problem your multi-agent system "
                "needs to solve and the key agents involved?"
            ),
            options=[
                InterviewOption(
                    label="Data processing pipeline",
                    description="Sequential stages that transform data end-to-end.",
                    value="pipeline",
                    rag_hint="pipeline pattern",
                ),
                InterviewOption(
                    label="Task orchestration",
                    description="A central coordinator delegates subtasks to workers.",
                    value="orchestrator_worker",
                    rag_hint="orchestrator worker pattern",
                ),
                InterviewOption(
                    label="Expert consultation",
                    description="Specialists collaborate and cross-consult.",
                    value="expert_network",
                    rag_hint="expert network pattern",
                ),
                InterviewOption(
                    label="Other / Custom",
                    description="I have a different architecture in mind.",
                    value="other",
                    rag_hint="multi-agent architecture",
                ),
            ],
        )

    @staticmethod
    def _build_final_confirmation_round(round_number: int) -> InterviewRound:
        """Build a terminal round that simply confirms the interview is done."""
        rnd = InterviewRound(
            round_number=round_number,
            question="Interview complete. Shall I generate the specification now?",
            options=[
                InterviewOption(
                    label="Yes, generate SPEC",
                    description="Proceed to specification generation.",
                    value="confirm",
                ),
                InterviewOption(
                    label="Add more details",
                    description="I want to provide additional information.",
                    value="custom:more_details",
                ),
            ],
        )
        # Auto-select to signal completion.
        rnd.select("confirm")
        return rnd
