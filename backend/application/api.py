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
    session_repo = SQLiteSessionRepo(settings.database_url)
    project_repo = SQLiteProjectRepo(settings.database_url)
    exporter = ZipExporter()

    await session_repo.initialize()
    await project_repo.initialize()

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
