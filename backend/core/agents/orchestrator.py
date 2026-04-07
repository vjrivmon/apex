"""OrchestratorAgent -- master coordinator for the APEX design flow.

This agent NEVER processes data itself. It decides which specialist agent
to invoke based on the current session phase, manages phase transitions,
and routes messages between agents.
"""

from __future__ import annotations

import logging
from typing import Any

from core.domain import (
    Architecture,
    Phase,
    Session,
)
from core.ports import ILLMProvider, IVectorStore

from .architect import ArchitectAgent
from .codegen import CodeGenAgent
from .conversation import ConversationAgent
from .evaluator import EvalAgent
from .rag_agent import RAGAgent
from .review import ReviewAgent
from .skillgen import SkillGenAgent

logger = logging.getLogger(__name__)

# Defines which phase follows which after a successful step.
_PHASE_TRANSITIONS: dict[Phase, Phase] = {
    Phase.ASSESSMENT: Phase.INTERVIEW,
    Phase.INTERVIEW: Phase.SPEC_GENERATION,
    Phase.SPEC_GENERATION: Phase.ARCHITECTURE,
    Phase.ARCHITECTURE: Phase.REVIEW,
    Phase.REVIEW: Phase.CODE_GEN,
    Phase.CODE_GEN: Phase.EVALUATION,
    Phase.EVALUATION: Phase.EXPORT,
}


class OrchestratorAgent:
    """Coordinates specialist agents through the APEX design flow.

    The orchestrator owns no domain logic.  It merely dispatches to the
    right agent, collects the result, advances the phase when appropriate,
    and returns a normalised response envelope.
    """

    def __init__(
        self,
        llm: ILLMProvider,
        vector_store: IVectorStore | None = None,
    ) -> None:
        self._llm = llm
        self._vector_store = vector_store

        # Lazily-created specialist agents (created once, reused).
        self._conversation = ConversationAgent(llm, vector_store)
        self._rag = RAGAgent(llm, vector_store)
        self._architect = ArchitectAgent(llm, vector_store)
        self._codegen = CodeGenAgent(llm, vector_store)
        self._skillgen = SkillGenAgent(llm, vector_store)
        self._review = ReviewAgent(llm, vector_store)
        self._evaluator = EvalAgent(llm, vector_store)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def process(
        self,
        session: Session,
        user_input: str,
        llm: ILLMProvider | None = None,
        vector_store: IVectorStore | None = None,
    ) -> dict[str, Any]:
        """Route *user_input* through the appropriate specialist agent.

        Parameters
        ----------
        session:
            The current design session (mutated in-place).
        user_input:
            Raw text from the user.
        llm:
            Optional override for the LLM provider (falls back to the
            instance default).
        vector_store:
            Optional override for the vector store.

        Returns
        -------
        dict with keys ``phase``, ``response``, ``metadata``.
        """
        # Allow per-call overrides so the FastAPI layer can inject
        # different providers if needed.
        active_llm = llm or self._llm
        active_vs = vector_store or self._vector_store

        phase = session.phase
        logger.info("Orchestrator routing — session=%s  phase=%s", session.id, phase.value)

        try:
            handler = self._get_handler(phase)
            result = await handler(session, user_input, active_llm, active_vs)
        except Exception:
            logger.exception("Agent failed during phase %s", phase.value)
            return {
                "phase": phase.value,
                "response": (
                    "An internal error occurred while processing your request. "
                    "Please try again or rephrase your input."
                ),
                "metadata": {"error": True},
            }

        # Persist the assistant response in the session history.
        response_text: str = result.get("response", "")
        metadata: dict = result.get("metadata", {})
        session.add_message(
            role="assistant",
            content=response_text,
            message_type=metadata.get("message_type", "text"),
            metadata=metadata,
        )

        # Determine whether the phase should advance.
        should_advance = result.get("advance_phase", False)
        if should_advance and phase in _PHASE_TRANSITIONS:
            next_phase = _PHASE_TRANSITIONS[phase]
            session.advance_phase(next_phase)
            logger.info(
                "Phase transition — %s -> %s (session=%s)",
                phase.value,
                next_phase.value,
                session.id,
            )

        return {
            "phase": session.phase.value,
            "response": response_text,
            "metadata": metadata,
        }

    # ------------------------------------------------------------------
    # Internal routing
    # ------------------------------------------------------------------

    def _get_handler(self, phase: Phase):
        """Return the async handler function for *phase*."""
        dispatch: dict[Phase, Any] = {
            Phase.ASSESSMENT: self._handle_assessment,
            Phase.INTERVIEW: self._handle_interview,
            Phase.SPEC_GENERATION: self._handle_spec_generation,
            Phase.ARCHITECTURE: self._handle_architecture,
            Phase.REVIEW: self._handle_review,
            Phase.CODE_GEN: self._handle_code_gen,
            Phase.EVALUATION: self._handle_evaluation,
            Phase.EXPORT: self._handle_export,
        }
        handler = dispatch.get(phase)
        if handler is None:
            raise ValueError(f"No handler registered for phase {phase.value}")
        return handler

    # ------------------------------------------------------------------
    # Phase handlers — thin wrappers that delegate to specialists
    # ------------------------------------------------------------------

    async def _handle_assessment(
        self,
        session: Session,
        user_input: str,
        llm: ILLMProvider,
        vs: IVectorStore | None,
    ) -> dict[str, Any]:
        """Assess whether the user's idea is detailed enough to skip interview."""
        session.problem_description = user_input
        session.add_message(role="user", content=user_input)

        rag_context = await self._fetch_rag_context(user_input, vs)
        is_complete = await self._conversation.assess_completeness(
            idea=user_input,
            rag_context=rag_context,
            llm=llm,
        )

        if is_complete:
            # Enough detail — jump straight to spec generation.
            return {
                "response": (
                    "Your description is thorough enough to skip the interview. "
                    "Generating the specification now..."
                ),
                "metadata": {"skipped_interview": True, "message_type": "text"},
                "advance_phase": True,  # ASSESSMENT -> INTERVIEW (then we advance again below)
            }

        # Need more information — start the interview.
        first_round = await self._conversation.generate_round(
            session=session,
            rag_context=rag_context,
            llm=llm,
        )
        session.add_interview_round(first_round)

        return {
            "response": first_round.question,
            "metadata": {
                "message_type": "options",
                "options": [
                    {"label": o.label, "description": o.description, "value": o.value}
                    for o in first_round.options
                ],
                "round_number": first_round.round_number,
            },
            "advance_phase": True,  # ASSESSMENT -> INTERVIEW
        }

    async def _handle_interview(
        self,
        session: Session,
        user_input: str,
        llm: ILLMProvider,
        vs: IVectorStore | None,
    ) -> dict[str, Any]:
        """Process an interview answer and generate the next round or finish."""
        session.add_message(role="user", content=user_input)

        # Record the answer on the current round.
        current = session.current_round
        if current is not None:
            current.select(user_input)

        # Check if interview is done (conversation agent decides).
        if session.interview_complete:
            return {
                "response": "Interview complete. Generating your specification...",
                "metadata": {"message_type": "text"},
                "advance_phase": True,  # INTERVIEW -> SPEC_GENERATION
            }

        # Generate next round.
        rag_context = await self._fetch_rag_context(user_input, vs)
        next_round = await self._conversation.generate_round(
            session=session,
            rag_context=rag_context,
            llm=llm,
        )
        session.add_interview_round(next_round)

        return {
            "response": next_round.question,
            "metadata": {
                "message_type": "options",
                "options": [
                    {"label": o.label, "description": o.description, "value": o.value}
                    for o in next_round.options
                ],
                "round_number": next_round.round_number,
            },
            "advance_phase": False,
        }

    async def _handle_spec_generation(
        self,
        session: Session,
        user_input: str,
        llm: ILLMProvider,
        vs: IVectorStore | None,
    ) -> dict[str, Any]:
        """Generate SPEC.md from the completed interview."""
        spec = await self._conversation.generate_spec(session=session, llm=llm)
        session.spec_content = spec

        return {
            "response": spec,
            "metadata": {"message_type": "text", "spec_generated": True},
            "advance_phase": True,  # SPEC_GENERATION -> ARCHITECTURE
        }

    async def _handle_architecture(
        self,
        session: Session,
        user_input: str,
        llm: ILLMProvider,
        vs: IVectorStore | None,
    ) -> dict[str, Any]:
        """Design the SMA architecture."""
        rag_data = await self._fetch_rag_context(session.spec_content, vs)
        architecture: Architecture = await self._architect.design_architecture(
            problem_analysis=session.spec_content,
            rag_patterns=rag_data,
            llm=llm,
        )
        session.architecture = architecture

        return {
            "response": (
                f"**Architecture: {architecture.pattern}**\n\n"
                f"{architecture.justification}\n\n"
                f"```\n{architecture.ascii_diagram}\n```\n\n"
                f"Agents: {architecture.agent_count} | "
                f"Communication: {architecture.communication}\n\n"
                f"Reference: {architecture.pattern_ref}"
            ),
            "metadata": {
                "message_type": "architecture",
                "architecture": architecture.to_dict(),
            },
            "advance_phase": True,  # ARCHITECTURE -> REVIEW
        }

    async def _handle_review(
        self,
        session: Session,
        user_input: str,
        llm: ILLMProvider,
        vs: IVectorStore | None,
    ) -> dict[str, Any]:
        """Review the designed architecture before code generation."""
        if session.architecture is None:
            return {
                "response": "No architecture to review. Please go back to the design step.",
                "metadata": {"error": True},
                "advance_phase": False,
            }

        review_result = await self._review.review(
            generated_code={},  # No code yet; reviewing architecture.
            architecture=session.architecture,
            llm=llm,
        )

        if review_result["approved"]:
            session.architecture.approve()
            return {
                "response": (
                    "Architecture approved. Proceeding to code generation.\n\n"
                    + "\n".join(f"- {s}" for s in review_result.get("suggestions", []))
                ),
                "metadata": {"message_type": "text", "review": review_result},
                "advance_phase": True,  # REVIEW -> CODE_GEN
            }

        # Architecture needs revision — stay in review phase.
        issues = review_result.get("issues", [])
        session.architecture.add_review("\n".join(issues))
        return {
            "response": (
                "Architecture review found issues:\n"
                + "\n".join(f"- {i}" for i in issues)
                + "\n\nPlease address these before proceeding."
            ),
            "metadata": {"message_type": "text", "review": review_result},
            "advance_phase": False,
        }

    async def _handle_code_gen(
        self,
        session: Session,
        user_input: str,
        llm: ILLMProvider,
        vs: IVectorStore | None,
    ) -> dict[str, Any]:
        """Generate code and Claude Code skills for the designed SMA."""
        if session.architecture is None:
            return {
                "response": "No architecture available for code generation.",
                "metadata": {"error": True},
                "advance_phase": False,
            }

        # Generate code.
        code_files = await self._codegen.generate(
            architecture=session.architecture,
            spec=session.spec_content,
            llm=llm,
        )
        session.generated_code = code_files

        # Generate skills for each agent in the architecture.
        skills: list[dict] = []
        for agent_spec in session.architecture.agents:
            skill = await self._skillgen.generate_skill(
                architecture=session.architecture,
                agent_spec=agent_spec,
                llm=llm,
            )
            skills.append(skill.to_dict())
        session.generated_skills = skills

        file_list = "\n".join(f"- `{f}`" for f in code_files)
        return {
            "response": (
                f"Generated {len(code_files)} files and "
                f"{len(skills)} Claude Code skills.\n\n"
                f"**Files:**\n{file_list}"
            ),
            "metadata": {
                "message_type": "code",
                "files": list(code_files.keys()),
                "skill_count": len(skills),
            },
            "advance_phase": True,  # CODE_GEN -> EVALUATION
        }

    async def _handle_evaluation(
        self,
        session: Session,
        user_input: str,
        llm: ILLMProvider,
        vs: IVectorStore | None,
    ) -> dict[str, Any]:
        """Design an evaluation strategy for the generated SMA."""
        if session.architecture is None:
            return {
                "response": "No architecture available for evaluation design.",
                "metadata": {"error": True},
                "advance_phase": False,
            }

        plan = await self._evaluator.design_evaluation(
            architecture=session.architecture,
            llm=llm,
        )
        session.evaluation_plan = plan

        return {
            "response": plan,
            "metadata": {"message_type": "text", "evaluation_plan": True},
            "advance_phase": True,  # EVALUATION -> EXPORT
        }

    async def _handle_export(
        self,
        session: Session,
        user_input: str,
        llm: ILLMProvider,
        vs: IVectorStore | None,
    ) -> dict[str, Any]:
        """Final phase -- package everything for export."""
        return {
            "response": (
                "Your SMA design is ready for export. "
                "Use the export endpoint to download the complete package."
            ),
            "metadata": {
                "message_type": "export",
                "exportable": True,
                "file_count": len(session.generated_code),
                "skill_count": len(session.generated_skills),
            },
            "advance_phase": False,  # Terminal phase.
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetch_rag_context(
        self,
        query: str,
        vs: IVectorStore | None,
    ) -> dict[str, list[dict]]:
        """Retrieve RAG context if a vector store is available."""
        if vs is None:
            return {"patterns": [], "cases": []}
        return await self._rag.retrieve(query=query, vector_store=vs)
