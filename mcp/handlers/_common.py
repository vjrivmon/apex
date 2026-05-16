"""Shared utilities for APEX MCP handler modules."""
from __future__ import annotations

import json
from pathlib import Path


# --- Hub constants ---
_HUB_DIR = Path.home() / "RoadToDevOps" / "apex-hub"
_HUB_DB = _HUB_DIR / "data" / "hub.db"


def find_project_root() -> Path:
    """Busca el directorio del proyecto subiendo desde CWD hasta encontrar .apex/ o .git/."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".apex").exists():
            return parent
        if (parent / ".git").exists():
            return parent
        if parent == parent.parent:
            break
    return cwd


async def db_exists(db) -> bool:
    """Verifica si context.db existe."""
    return db.db_path.exists()


def sync_to_obsidian(event_type: str, data: dict) -> None:
    """Escribe una nota en el vault de Obsidian cada vez que el MCP registra algo.
    No falla si el vault no existe."""
    _OBSIDIAN_VAULT = Path.home() / "Documents" / "ApexVault"
    try:
        if not _OBSIDIAN_VAULT.exists():
            return

        project_name = data.get("project", "unknown")
        project_dir = _OBSIDIAN_VAULT / "projects"
        project_dir.mkdir(parents=True, exist_ok=True)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        if event_type == "decision":
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Decisión [{data.get('category', '')}]: {data.get('decision', '')[:100]}\n")
        elif event_type == "error":
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Error [{data.get('source', '')}]: {data.get('description', '')[:100]}\n")
        elif event_type == "phase":
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Fase {data.get('phase', '?')} → {data.get('status', '?')}\n")
        elif event_type == "component":
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Componente: {data.get('name', '')} ({data.get('type', '')})\n")
        elif event_type == "session":
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Sesión: {data.get('summary', '')[:100]}\n")
    except Exception:
        pass  # Obsidian sync es best-effort, nunca rompe el flujo


def search_cross_project(query: str, limit: int = 8, exclude_project: str | None = None) -> dict:
    """Consulta hub.db (agregada por apex-hub) para encontrar errores, decisiones y
    componentes de OTROS proyectos similares al query."""
    import sqlite3

    empty = {"errors": [], "decisions": [], "components": [], "hub_available": False}

    if not _HUB_DB.exists():
        return empty

    try:
        conn = sqlite3.connect(f"file:{_HUB_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.OperationalError:
        return empty

    try:
        fts_q = query.strip()
        if not fts_q:
            return {**empty, "hub_available": True}

        sql = (
            "SELECT project_id, source_type, source_id, "
            "snippet(hub_search, 3, '[', ']', '...', 24) AS snip, rank "
            "FROM hub_search WHERE hub_search MATCH ?"
        )
        params: list = [fts_q]
        if exclude_project:
            sql += " AND project_id != ?"
            params.append(exclude_project)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit * 3)

        try:
            rows = [dict(r) for r in conn.execute(sql, params)]
        except sqlite3.OperationalError:
            try:
                rows = [dict(r) for r in conn.execute(sql, [f'"{fts_q}"', *params[1:]])]
            except sqlite3.OperationalError:
                return {**empty, "hub_available": True}

        errors, decisions, components = [], [], []

        for row in rows:
            src_type = row["source_type"]
            src_id = row["source_id"]
            pid = row["project_id"]
            if src_type == "error" and len(errors) < limit:
                r = conn.execute(
                    "SELECT description, lesson, severity, recurrence_count, phase "
                    "FROM errors WHERE id = ?",
                    (src_id,),
                ).fetchone()
                if r:
                    errors.append({"project_id": pid, **dict(r)})
            elif src_type == "decision" and len(decisions) < limit:
                r = conn.execute(
                    "SELECT category, decision, reasoning, phase, invalid_from "
                    "FROM decisions WHERE id = ?",
                    (src_id,),
                ).fetchone()
                if r:
                    decisions.append({"project_id": pid, **dict(r)})
            elif src_type == "component" and len(components) < limit:
                r = conn.execute(
                    "SELECT component_id, name, type, description, status "
                    "FROM components WHERE rowid = ?",
                    (src_id,),
                ).fetchone()
                if r:
                    components.append({"project_id": pid, **dict(r)})
        return {
            "errors": errors,
            "decisions": decisions,
            "components": components,
            "hub_available": True,
        }
    finally:
        conn.close()
