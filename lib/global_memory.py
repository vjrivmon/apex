"""APEX Global Memory — memoria inmutable de errores graves cross-project.

`~/.apex/context.db` NO es el contexto de ningún proyecto: es una memoria
global, append-only, de los errores GRAVES (severity critical|high) que se
van encontrando en CUALQUIER proyecto APEX. Un proyecto local nunca la
sobreescribe; solo se le AÑADEN errores graves con el project_id de origen.

Diseño (bug/feature 2026-07-17):
- Tabla propia `grave_errors`, separada del esquema de proyecto, para no
  mezclarse con datos legacy que pudieran vivir en el mismo fichero.
- Append-only: nunca UPDATE ni DELETE desde un proyecto. La deduplicación
  se hace por (project_id, description) para no acumular el mismo error mil
  veces, pero eso solo evita duplicados exactos — nunca borra.
- Best-effort: si el global no se puede abrir/escribir, no rompe el flujo
  del proyecto (el error ya quedó en la BD local, que es la fuente primaria).
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

GRAVE_SEVERITIES = frozenset({"critical", "high"})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS grave_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'claude',
    phase INTEGER,
    description TEXT NOT NULL,
    cause TEXT DEFAULT '',
    fix TEXT DEFAULT '',
    lesson TEXT DEFAULT '',
    severity TEXT NOT NULL,
    origin_created_at TEXT DEFAULT '',
    recorded_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_id, description)
);
CREATE INDEX IF NOT EXISTS idx_grave_errors_project ON grave_errors(project_id);
CREATE INDEX IF NOT EXISTS idx_grave_errors_severity ON grave_errors(severity);
"""


def global_db_path() -> Path:
    """Ruta canónica de la memoria global. `~/.apex/context.db`.
    APEX_GLOBAL_MEMORY_DB la redirige (la suite la apunta a tmp)."""
    override = os.environ.get("APEX_GLOBAL_MEMORY_DB")
    return Path(override) if override else Path.home() / ".apex" / "context.db"


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA)


def record_grave_error(
    project_id: str,
    description: str,
    lesson: str,
    *,
    severity: str,
    source: str = "claude",
    phase: int | None = None,
    cause: str = "",
    fix: str = "",
    origin_created_at: str = "",
    db_path: Path | None = None,
) -> bool:
    """Añade un error grave a la memoria global (append-only, idempotente).

    Devuelve True si se insertó (o ya existía), False si la severidad no es
    grave o el global no se pudo escribir. Nunca lanza: es best-effort.
    """
    if severity not in GRAVE_SEVERITIES:
        return False
    path = db_path or global_db_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(str(path), timeout=5)
        try:
            _ensure_schema(con)
            con.execute(
                "INSERT OR IGNORE INTO grave_errors "
                "(project_id, source, phase, description, cause, fix, lesson, "
                " severity, origin_created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, source, phase, description, cause, fix, lesson,
                 severity, origin_created_at),
            )
            con.commit()
            return True
        finally:
            con.close()
    except sqlite3.Error:
        return False


def count_grave_errors(db_path: Path | None = None) -> int:
    """Cuántos errores graves hay en la memoria global. 0 si no existe."""
    path = db_path or global_db_path()
    if not path.exists():
        return 0
    try:
        con = sqlite3.connect(str(path), timeout=5)
        try:
            _ensure_schema(con)
            return con.execute("SELECT count(*) FROM grave_errors").fetchone()[0]
        finally:
            con.close()
    except sqlite3.Error:
        return 0
