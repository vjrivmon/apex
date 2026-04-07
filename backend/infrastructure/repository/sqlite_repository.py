"""Infrastructure adapter: SQLite-backed session and project repositories."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

from core.domain.project import Project
from core.domain.session import Message, Session
from core.domain.phase import InterviewOption, InterviewRound, Phase
from core.domain.architecture import Architecture
from core.domain.agent_spec import AgentSpec
from core.ports.project_repository import IProjectRepository
from core.ports.session_repository import ISessionRepository
from shared.config import settings

logger = logging.getLogger(__name__)

# Extract the file path from the SQLAlchemy-style URL
_DB_PATH_PREFIX = "sqlite:///"


def _resolve_db_path(url: str) -> str:
    """Convert ``sqlite:///./apex.db`` to an absolute path string."""
    raw = url.removeprefix(_DB_PATH_PREFIX)
    return str(Path(raw).resolve())


class _SQLiteBase:
    """Shared helpers for SQLite repositories."""

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _resolve_db_path(settings.database_url)

    async def _get_connection(self) -> aiosqlite.Connection:
        """Open a connection (caller is responsible for closing it)."""
        conn = await aiosqlite.connect(self._db_path)
        conn.row_factory = aiosqlite.Row
        return conn

    async def _ensure_tables(self) -> None:
        """Create tables if they do not exist."""
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    data TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'in_progress',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await conn.commit()
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# Session serialisation helpers
# ---------------------------------------------------------------------------


def _session_to_json(session: Session) -> str:
    """Serialise a ``Session`` to a JSON string for storage."""
    data = {
        "id": session.id,
        "created_at": session.created_at.isoformat(),
        "phase": session.phase.value,
        "messages": [
            {
                "role": m.role,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
                "message_type": m.message_type,
                "metadata": m.metadata,
            }
            for m in session.messages
        ],
        "interview_rounds": [
            {
                "round_number": r.round_number,
                "question": r.question,
                "options": [
                    {
                        "label": o.label,
                        "description": o.description,
                        "value": o.value,
                        "rag_hint": o.rag_hint,
                    }
                    for o in r.options
                ],
                "selected_value": r.selected_value,
                "rag_context": r.rag_context,
            }
            for r in session.interview_rounds
        ],
        "problem_description": session.problem_description,
        "domain_analysis": session.domain_analysis,
        "architecture": session.architecture.to_dict() if session.architecture else None,
        "generated_code": session.generated_code,
        "generated_skills": session.generated_skills,
        "spec_content": session.spec_content,
        "evaluation_plan": session.evaluation_plan,
        "project_id": session.project_id,
    }
    return json.dumps(data, ensure_ascii=False)


def _session_from_json(raw: str) -> Session:
    """Deserialise a ``Session`` from its JSON representation."""
    data = json.loads(raw)

    messages = [
        Message(
            role=m["role"],
            content=m["content"],
            timestamp=datetime.fromisoformat(m["timestamp"]),
            message_type=m.get("message_type", "text"),
            metadata=m.get("metadata", {}),
        )
        for m in data.get("messages", [])
    ]

    interview_rounds = [
        InterviewRound(
            round_number=r["round_number"],
            question=r["question"],
            options=[
                InterviewOption(
                    label=o["label"],
                    description=o["description"],
                    value=o["value"],
                    rag_hint=o.get("rag_hint", ""),
                )
                for o in r.get("options", [])
            ],
            selected_value=r.get("selected_value"),
            rag_context=r.get("rag_context", []),
        )
        for r in data.get("interview_rounds", [])
    ]

    arch_data = data.get("architecture")
    architecture = None
    if arch_data:
        agents = [
            AgentSpec(
                name=a["name"],
                responsibility=a["responsibility"],
                input_description=a["input_description"],
                output_description=a["output_description"],
                recommended_model=a["recommended_model"],
                needs_rag=a.get("needs_rag", False),
                needs_memory=a.get("needs_memory", False),
                failure_mode=a.get("failure_mode", "return_empty"),
                tools=a.get("tools", []),
                dependencies=a.get("dependencies", []),
            )
            for a in arch_data.get("agents", [])
        ]
        architecture = Architecture(
            pattern=arch_data["pattern"],
            pattern_ref=arch_data["pattern_ref"],
            justification=arch_data["justification"],
            ascii_diagram=arch_data["ascii_diagram"],
            agents=agents,
            communication=arch_data.get("communication", "synchronous"),
            approved=arch_data.get("approved", False),
            review_notes=arch_data.get("review_notes", ""),
        )

    return Session(
        id=data["id"],
        created_at=datetime.fromisoformat(data["created_at"]),
        phase=Phase(data["phase"]),
        messages=messages,
        interview_rounds=interview_rounds,
        problem_description=data.get("problem_description", ""),
        domain_analysis=data.get("domain_analysis", {}),
        architecture=architecture,
        generated_code=data.get("generated_code", {}),
        generated_skills=data.get("generated_skills", []),
        spec_content=data.get("spec_content", ""),
        evaluation_plan=data.get("evaluation_plan", ""),
        project_id=data.get("project_id"),
    )


# ---------------------------------------------------------------------------
# Project serialisation helpers
# ---------------------------------------------------------------------------


def _project_to_json(project: Project) -> str:
    """Serialise a ``Project`` to a JSON string for storage."""
    data = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "created_at": project.created_at.isoformat(),
        "updated_at": project.updated_at.isoformat(),
        "session_id": project.session_id,
        "spec_content": project.spec_content,
        "architecture_pattern": project.architecture_pattern,
        "agent_count": project.agent_count,
        "status": project.status,
        "export_path": project.export_path,
        "tags": project.tags,
        "learnings": project.learnings,
    }
    return json.dumps(data, ensure_ascii=False)


def _project_from_json(raw: str) -> Project:
    """Deserialise a ``Project`` from its JSON representation."""
    data = json.loads(raw)
    return Project(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        session_id=data.get("session_id"),
        spec_content=data.get("spec_content", ""),
        architecture_pattern=data.get("architecture_pattern", ""),
        agent_count=data.get("agent_count", 0),
        status=data.get("status", "in_progress"),
        export_path=data.get("export_path"),
        tags=data.get("tags", []),
        learnings=data.get("learnings", []),
    )


# ---------------------------------------------------------------------------
# SQLiteSessionRepo
# ---------------------------------------------------------------------------


class SQLiteSessionRepo(_SQLiteBase, ISessionRepository):
    """Async SQLite-backed session repository."""

    def __init__(self, db_path: str | None = None) -> None:
        super().__init__(db_path)
        self._initialized = False

    async def _init_once(self) -> None:
        if not self._initialized:
            await self._ensure_tables()
            self._initialized = True

    async def save(self, session: Session) -> None:
        """Save or update a session (upsert)."""
        await self._init_once()
        now = datetime.now(timezone.utc).isoformat()
        data_json = _session_to_json(session)
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO sessions (id, data, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    data = excluded.data,
                    updated_at = excluded.updated_at
                """,
                (session.id, data_json, session.created_at.isoformat(), now),
            )
            await conn.commit()
            logger.debug("Saved session %s", session.id)
        finally:
            await conn.close()

    async def get(self, session_id: str) -> Session | None:
        """Retrieve a session by ID, or ``None`` if not found."""
        await self._init_once()
        conn = await self._get_connection()
        try:
            cursor = await conn.execute(
                "SELECT data FROM sessions WHERE id = ?", (session_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return _session_from_json(row[0])
        finally:
            await conn.close()

    async def list_all(self) -> list[Session]:
        """Return all sessions ordered by creation date (newest first)."""
        await self._init_once()
        conn = await self._get_connection()
        try:
            cursor = await conn.execute(
                "SELECT data FROM sessions ORDER BY created_at DESC",
            )
            rows = await cursor.fetchall()
            return [_session_from_json(row[0]) for row in rows]
        finally:
            await conn.close()

    async def delete(self, session_id: str) -> None:
        """Delete a session by ID."""
        await self._init_once()
        conn = await self._get_connection()
        try:
            await conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,),
            )
            await conn.commit()
            logger.debug("Deleted session %s", session_id)
        finally:
            await conn.close()


# ---------------------------------------------------------------------------
# SQLiteProjectRepo
# ---------------------------------------------------------------------------


class SQLiteProjectRepo(_SQLiteBase, IProjectRepository):
    """Async SQLite-backed project repository."""

    def __init__(self, db_path: str | None = None) -> None:
        super().__init__(db_path)
        self._initialized = False

    async def _init_once(self) -> None:
        if not self._initialized:
            await self._ensure_tables()
            self._initialized = True

    async def save(self, project: Project) -> None:
        """Save or update a project (upsert)."""
        await self._init_once()
        now = datetime.now(timezone.utc).isoformat()
        data_json = _project_to_json(project)
        conn = await self._get_connection()
        try:
            await conn.execute(
                """
                INSERT INTO projects (id, name, description, data, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    data = excluded.data,
                    status = excluded.status,
                    updated_at = excluded.updated_at
                """,
                (
                    project.id,
                    project.name,
                    project.description,
                    data_json,
                    project.status,
                    project.created_at.isoformat(),
                    now,
                ),
            )
            await conn.commit()
            logger.debug("Saved project %s (%s)", project.id, project.name)
        finally:
            await conn.close()

    async def get(self, project_id: str) -> Project | None:
        """Retrieve a project by ID, or ``None`` if not found."""
        await self._init_once()
        conn = await self._get_connection()
        try:
            cursor = await conn.execute(
                "SELECT data FROM projects WHERE id = ?", (project_id,),
            )
            row = await cursor.fetchone()
            if row is None:
                return None
            return _project_from_json(row[0])
        finally:
            await conn.close()

    async def list_all(self, status: str | None = None) -> list[Project]:
        """Return projects, optionally filtered by status (newest first)."""
        await self._init_once()
        conn = await self._get_connection()
        try:
            if status:
                cursor = await conn.execute(
                    "SELECT data FROM projects WHERE status = ? ORDER BY created_at DESC",
                    (status,),
                )
            else:
                cursor = await conn.execute(
                    "SELECT data FROM projects ORDER BY created_at DESC",
                )
            rows = await cursor.fetchall()
            return [_project_from_json(row[0]) for row in rows]
        finally:
            await conn.close()

    async def delete(self, project_id: str) -> None:
        """Delete a project by ID."""
        await self._init_once()
        conn = await self._get_connection()
        try:
            await conn.execute(
                "DELETE FROM projects WHERE id = ?", (project_id,),
            )
            await conn.commit()
            logger.debug("Deleted project %s", project_id)
        finally:
            await conn.close()
