"""APEX API — FastAPI application with WebSocket streaming."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from application.dto.session_dto import (
    CreateSessionRequest,
    CreateSessionResponse,
    SelectOptionRequest,
    SessionSummary,
)
from application.use_cases.design_sma import DesignSMAUseCase
from application.use_cases.manage_patterns import ManagePatternsUseCase
from shared.config import settings

logger = logging.getLogger(__name__)

# --- Dependency injection (wired at startup) ---
_design_use_case: DesignSMAUseCase | None = None
_patterns_use_case: ManagePatternsUseCase | None = None


def _get_design_uc() -> DesignSMAUseCase:
    assert _design_use_case is not None, "App not initialized"
    return _design_use_case


def _get_patterns_uc() -> ManagePatternsUseCase:
    assert _patterns_use_case is not None, "App not initialized"
    return _patterns_use_case


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Wire up infrastructure adapters on startup."""
    global _design_use_case, _patterns_use_case

    # Late imports to avoid circular dependencies
    from infrastructure.export.zip_exporter import ZipExporter
    from infrastructure.llm.ollama_adapter import OllamaAdapter
    from infrastructure.rag.chroma_adapter import ChromaAdapter
    from infrastructure.repository.sqlite_repository import SQLiteProjectRepo, SQLiteSessionRepo

    llm = OllamaAdapter(settings.ollama_base_url)
    vector_store = ChromaAdapter(settings.chroma_host, settings.chroma_port)
    session_repo = SQLiteSessionRepo()
    project_repo = SQLiteProjectRepo()
    exporter = ZipExporter()

    _design_use_case = DesignSMAUseCase(
        llm=llm,
        vector_store=vector_store,
        session_repo=session_repo,
        project_repo=project_repo,
        exporter=exporter,
    )
    _patterns_use_case = ManagePatternsUseCase(vector_store)

    logger.info("APEX backend started on port %d", settings.backend_port)
    yield
    logger.info("APEX backend shutting down")


app = FastAPI(
    title="APEX",
    description="Design Multi-Agent Systems, Intelligently",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Health ---


@app.get("/health")
async def health():
    return {
        "status": "healthy",
        "service": "apex",
        "version": "1.0.0",
        "agents": [
            "OrchestratorAgent",
            "ConversationAgent",
            "ArchitectAgent",
            "RAGAgent",
            "CodeGenAgent",
            "SkillGenAgent",
            "ReviewAgent",
            "EvalAgent",
        ],
    }


# --- Sessions ---


@app.post("/api/sessions", response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest):
    uc = _get_design_uc()
    session = await uc.create_session(req.problem_description)
    return CreateSessionResponse(
        session_id=session.id,
        phase=session.phase.value,
        message="Session created. Check the phase to know if interview is needed.",
    )


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    uc = _get_design_uc()
    session = await uc._session_repo.get(session_id)
    if not session:
        return {"error": "Session not found"}, 404
    return session.to_dict()


@app.get("/api/sessions")
async def list_sessions():
    uc = _get_design_uc()
    sessions = await uc._session_repo.list_all()
    return [
        SessionSummary(
            id=s.id,
            phase=s.phase.value,
            problem_description=s.problem_description[:100],
            created_at=s.created_at.isoformat(),
            project_id=s.project_id,
        ).model_dump()
        for s in sessions
    ]


@app.post("/api/sessions/{session_id}/select")
async def select_option(session_id: str, req: SelectOptionRequest):
    uc = _get_design_uc()
    results = []
    async for msg in uc.handle_option_selection(session_id, req.value):
        results.append(msg)
    return {"events": results}


# --- Export ---


@app.get("/api/sessions/{session_id}/export")
async def export_session(session_id: str):
    uc = _get_design_uc()
    zip_bytes = await uc.export_project(session_id)
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=apex-{session_id[:8]}.zip"},
    )


# --- Patterns ---


@app.get("/api/patterns")
async def list_patterns():
    uc = _get_patterns_uc()
    return await uc.list_patterns()


@app.get("/api/patterns/search")
async def search_patterns(q: str):
    uc = _get_patterns_uc()
    return await uc.search_patterns(q)


@app.get("/api/patterns/stats")
async def pattern_stats():
    uc = _get_patterns_uc()
    return {
        "pattern_count": await uc.get_pattern_count(),
        "case_count": await uc.get_case_count(),
    }


# --- Stats (combined endpoint for dashboard) ---


@app.get("/api/stats")
async def dashboard_stats():
    uc = _get_design_uc()
    puc = _get_patterns_uc()
    sessions = await uc._session_repo.list_all()
    try:
        pattern_count = await puc.get_pattern_count()
        case_count = await puc.get_case_count()
    except Exception:
        pattern_count = 0
        case_count = 0

    completed = sum(1 for s in sessions if s.phase.value == "export")
    total_skills = sum(len(s.generated_skills) for s in sessions)

    return {
        "total_projects": len(sessions),
        "completed_projects": completed,
        "pattern_count": pattern_count,
        "case_count": case_count,
        "skills_generated": total_skills,
        "active_agents": 8,
    }


# --- Skills ---


@app.get("/api/skills")
async def list_skills():
    uc = _get_design_uc()
    sessions = await uc._session_repo.list_all()
    all_skills = []
    for s in sessions:
        for skill in s.generated_skills:
            skill["session_id"] = s.id
            all_skills.append(skill)
    return all_skills


# --- Agent Status ---


@app.get("/api/agents/status")
async def agent_status():
    """Returns the status of all 8 APEX agents."""
    agents = [
        {
            "name": "OrchestratorAgent",
            "display_name": "Orquestador",
            "description": "Coordina todos los agentes. Nunca procesa datos directamente.",
            "model": "coordinador",
            "status": "activo",
        },
        {
            "name": "ConversationAgent",
            "display_name": "Conversación",
            "description": "Interfaz de lenguaje natural. Gestiona la entrevista y genera el SPEC.",
            "model": settings.ollama_conversation_model,
            "status": "activo",
        },
        {
            "name": "ArchitectAgent",
            "display_name": "Arquitecto",
            "description": "Diseña la arquitectura SMA usando el árbol de decisión.",
            "model": settings.ollama_architect_model,
            "status": "activo",
        },
        {
            "name": "RAGAgent",
            "display_name": "RAG",
            "description": "Recupera patrones y casos reales de la base de conocimiento.",
            "model": settings.ollama_rag_model,
            "status": "activo",
        },
        {
            "name": "CodeGenAgent",
            "display_name": "Generador de Código",
            "description": "Genera código hexagonal completo para el SMA diseñado.",
            "model": settings.ollama_codegen_model,
            "status": "activo",
        },
        {
            "name": "SkillGenAgent",
            "display_name": "Generador de Skills",
            "description": "Genera skills de Claude Code a partir de la arquitectura.",
            "model": settings.ollama_codegen_model,
            "status": "activo",
        },
        {
            "name": "ReviewAgent",
            "display_name": "Revisor",
            "description": "Revisa el código generado: seguridad, calidad, arquitectura.",
            "model": settings.ollama_architect_model,
            "status": "activo",
        },
        {
            "name": "EvalAgent",
            "display_name": "Evaluador",
            "description": "Diseña la estrategia de evaluación y benchmarks del SMA.",
            "model": settings.ollama_conversation_model,
            "status": "activo",
        },
    ]
    return agents


# --- WebSocket ---


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """Bidirectional streaming for the chat interface."""
    await websocket.accept()
    uc = _get_design_uc()

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            msg_type = payload.get("type", "message")
            content = payload.get("content", "")

            if msg_type == "select_option":
                async for event in uc.handle_option_selection(session_id, content):
                    await websocket.send_text(json.dumps(event))
            elif msg_type == "message":
                async for event in uc.handle_message(session_id, content):
                    await websocket.send_text(json.dumps(event))
            else:
                await websocket.send_text(
                    json.dumps({"type": "error", "content": f"Unknown message type: {msg_type}"})
                )

            await websocket.send_text(json.dumps({"type": "done", "content": ""}))

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: session %s", session_id)
    except Exception as e:
        logger.exception("WebSocket error: session %s", session_id)
        try:
            await websocket.send_text(json.dumps({"type": "error", "content": str(e)}))
        except Exception:
            pass
