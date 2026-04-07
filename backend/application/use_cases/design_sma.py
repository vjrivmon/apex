"""Use case: Design a Multi-Agent System through conversational flow."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from core.agents import (
    ArchitectAgent,
    CodeGenAgent,
    ConversationAgent,
    EvalAgent,
    OrchestratorAgent,
    RAGAgent,
    ReviewAgent,
    SkillGenAgent,
)
from core.domain import Phase, Session
from core.ports import IFileExporter, ILLMProvider, IProjectRepository, ISessionRepository, IVectorStore

logger = logging.getLogger(__name__)


class DesignSMAUseCase:
    """Orchestrates the full SMA design flow.

    Flow: Assessment → Interview (option-based) → SPEC → Design → Architecture
          → Review → Code Gen → Evaluation → Export

    The ConversationAgent handles smart assessment and interview rounds.
    RAG enriches every step with patterns and real cases.
    The learning loop ingests new knowledge after each completed project.
    """

    def __init__(
        self,
        llm: ILLMProvider,
        vector_store: IVectorStore,
        session_repo: ISessionRepository,
        project_repo: IProjectRepository,
        exporter: IFileExporter,
    ):
        self._llm = llm
        self._vector_store = vector_store
        self._session_repo = session_repo
        self._project_repo = project_repo
        self._exporter = exporter

        # Initialize agents — all receive ports, never infrastructure
        self._orchestrator = OrchestratorAgent(llm, vector_store)
        self._conversation = ConversationAgent(llm, vector_store)
        self._architect = ArchitectAgent(llm, vector_store)
        self._rag = RAGAgent(llm, vector_store)
        self._codegen = CodeGenAgent(llm)
        self._skillgen = SkillGenAgent(llm)
        self._review = ReviewAgent(llm)
        self._eval = EvalAgent(llm)

    async def create_session(self, problem_description: str) -> Session:
        """Create a new design session and run smart assessment."""
        import uuid

        session = Session(id=str(uuid.uuid4()), problem_description=problem_description)

        # Smart Assessment: check if the idea is complete enough
        rag_context = await self._rag.retrieve(problem_description)
        is_complete = await self._conversation.assess_completeness(
            problem_description, rag_context
        )

        if is_complete:
            # Skip interview, generate SPEC directly
            session.advance_phase(Phase.SPEC_GENERATION)
            spec = await self._conversation.generate_spec(session)
            session.spec_content = spec
            session.advance_phase(Phase.AGENT_DESIGN)
            session.add_message(
                "assistant",
                "Tu idea es lo suficientemente completa. He generado el SPEC directamente.",
                message_type="text",
            )
        else:
            # Start interview rounds
            session.advance_phase(Phase.INTERVIEW)
            first_round = await self._conversation.generate_round(session, rag_context)
            session.add_interview_round(first_round)
            session.add_message(
                "assistant",
                first_round.question,
                message_type="options",
                metadata={
                    "round_number": first_round.round_number,
                    "options": [
                        {"label": o.label, "description": o.description, "value": o.value}
                        for o in first_round.options
                    ],
                },
            )

        await self._session_repo.save(session)
        return session

    async def handle_option_selection(
        self, session_id: str, selected_value: str
    ) -> AsyncIterator[dict]:
        """Handle when user selects an option in the interview."""
        session = await self._session_repo.get(session_id)
        if not session:
            yield {"type": "error", "content": "Session not found"}
            return

        current_round = session.current_round
        if current_round:
            current_round.select(selected_value)
            session.add_message("user", selected_value, message_type="option_selected")

        # Check if interview is complete
        rag_context = await self._rag.retrieve(
            f"{session.problem_description} {selected_value}"
        )

        # Decide: more rounds needed or generate SPEC?
        needs_more = await self._conversation.needs_more_info(session, rag_context)

        if needs_more:
            next_round = await self._conversation.generate_round(session, rag_context)
            session.add_interview_round(next_round)
            session.add_message(
                "assistant",
                next_round.question,
                message_type="options",
                metadata={
                    "round_number": next_round.round_number,
                    "options": [
                        {"label": o.label, "description": o.description, "value": o.value}
                        for o in next_round.options
                    ],
                },
            )
            yield {
                "type": "options",
                "content": next_round.question,
                "metadata": {
                    "round_number": next_round.round_number,
                    "options": [
                        {"label": o.label, "description": o.description, "value": o.value}
                        for o in next_round.options
                    ],
                },
            }
        else:
            # Generate SPEC
            session.advance_phase(Phase.SPEC_GENERATION)
            yield {"type": "phase", "content": "spec_generation"}

            spec = await self._conversation.generate_spec(session)
            session.spec_content = spec
            yield {"type": "text", "content": spec}

            # Move to agent design
            session.advance_phase(Phase.AGENT_DESIGN)
            yield {"type": "phase", "content": "agent_design"}

        await self._session_repo.save(session)

    async def handle_message(self, session_id: str, user_input: str) -> AsyncIterator[dict]:
        """Handle a free-text message from the user."""
        session = await self._session_repo.get(session_id)
        if not session:
            yield {"type": "error", "content": "Session not found"}
            return

        session.add_message("user", user_input)
        result = await self._orchestrator.process(session, user_input, self._llm, self._vector_store)

        # Route based on current phase
        phase = session.phase

        if phase == Phase.AGENT_DESIGN:
            rag_context = await self._rag.retrieve(session.spec_content)
            architecture = await self._architect.design_architecture(
                {"spec": session.spec_content, "domain": session.domain_analysis},
                rag_context,
            )
            session.architecture = architecture
            session.advance_phase(Phase.ARCHITECTURE)

            yield {"type": "architecture", "content": architecture.ascii_diagram, "metadata": architecture.to_dict()}
            for agent in architecture.agents:
                yield {"type": "agent_spec", "content": agent.name, "metadata": agent.to_dict()}
            yield {"type": "phase", "content": "architecture"}
            yield {"type": "text", "content": "¿Apruebas esta arquitectura? Puedes pedir cambios o decir 'aprobado'."}

        elif phase == Phase.ARCHITECTURE:
            # Check for approval
            approval_keywords = {"aprobado", "apruebo", "sí", "si", "ok", "approved", "yes", "perfecto", "adelante"}
            if any(kw in user_input.lower() for kw in approval_keywords):
                if session.architecture:
                    session.architecture.approve()

                # Review before code gen
                session.advance_phase(Phase.REVIEW)
                yield {"type": "phase", "content": "review"}
                yield {"type": "text", "content": "Revisando la arquitectura antes de generar código..."}

                # Auto-advance to code gen after review
                session.advance_phase(Phase.CODE_GEN)
                yield {"type": "phase", "content": "code_gen"}

                code = await self._codegen.generate(session.architecture, session.spec_content)
                session.generated_code = code

                for filename, content in code.items():
                    yield {"type": "code", "content": content, "metadata": {"filename": filename}}

                # Generate skills
                skills = await self._skillgen.generate_all_skills(session.architecture)
                session.generated_skills = [s.to_dict() for s in skills]

                # Evaluation
                session.advance_phase(Phase.EVALUATION)
                eval_plan = await self._eval.design_evaluation(session.architecture)
                session.evaluation_plan = eval_plan
                yield {"type": "text", "content": eval_plan}

                # Ready for export
                session.advance_phase(Phase.EXPORT)
                yield {"type": "phase", "content": "export"}
                yield {
                    "type": "export",
                    "content": "Proyecto listo para exportar",
                    "metadata": {"file_count": len(code), "skill_count": len(skills)},
                }
            else:
                yield {"type": "text", "content": result.get("response", "Entendido, ajustando la arquitectura...")}

        elif phase == Phase.EXPORT:
            yield {
                "type": "export",
                "content": "Usa el botón de descarga para obtener el ZIP",
                "metadata": {"file_count": len(session.generated_code)},
            }

        else:
            yield {"type": "text", "content": result.get("response", "")}

        await self._session_repo.save(session)

    async def export_project(self, session_id: str) -> bytes:
        """Export the generated project as a ZIP file."""
        session = await self._session_repo.get(session_id)
        if not session:
            raise ValueError("Session not found")

        files = dict(session.generated_code)
        files["SPEC.md"] = session.spec_content
        if session.evaluation_plan:
            files["EVALUATION.md"] = session.evaluation_plan
        if session.architecture:
            files["ARCHITECTURE.md"] = self._format_architecture_doc(session.architecture)

        project_name = session.problem_description[:50].replace(" ", "-").lower()
        return await self._exporter.export_zip(files, project_name)

    def _format_architecture_doc(self, arch) -> str:
        lines = [
            f"# Architecture: {arch.pattern}",
            "",
            f"## Pattern Reference",
            arch.pattern_ref,
            "",
            "## Justification",
            arch.justification,
            "",
            "## Diagram",
            "```",
            arch.ascii_diagram,
            "```",
            "",
            "## Agents",
        ]
        for a in arch.agents:
            lines.extend([
                f"### {a.name}",
                f"- **Responsibility**: {a.responsibility}",
                f"- **Model**: {a.recommended_model}",
                f"- **RAG**: {'Yes' if a.needs_rag else 'No'}",
                f"- **Memory**: {'Yes' if a.needs_memory else 'No'}",
                f"- **Failure mode**: {a.failure_mode}",
                "",
            ])
        return "\n".join(lines)
