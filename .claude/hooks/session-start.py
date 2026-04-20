#!/usr/bin/env python3
"""SessionStart hook para APEX — inyecta lecciones cross-project al contexto.

Lee ~/RoadToDevOps/apex-hub/data/hub.db (agregada por apex-hub) y extrae los
top-5 errores recurrentes de OTROS proyectos para evitar repetirlos. Devuelve
JSON con `hookSpecificOutput.additionalContext` que Claude Code inyecta
directamente en el contexto al iniciar la sesión.

Best-effort: si hub.db no existe o hay cualquier error, devuelve stdout vacío
(el hook no bloquea nunca el arranque de la sesión).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

HUB_DB = Path.home() / "RoadToDevOps" / "apex-hub" / "data" / "hub.db"
MAX_ERRORS = 5


def _current_project_id() -> str | None:
    """Devuelve el slug del proyecto actual (nombre del cwd) para excluirlo."""
    # Claude Code invoca hooks desde el cwd del proyecto
    cwd = Path(os.getcwd())
    # Sube hasta encontrar .git o .apex, luego devuelve el nombre de ese dir
    for parent in [cwd, *cwd.parents]:
        if (parent / ".apex").exists() or (parent / ".git").exists():
            return parent.name.lower().replace(" ", "-")
        if parent == parent.parent:
            break
    return cwd.name.lower().replace(" ", "-")


def _read_top_errors() -> list[dict]:
    if not HUB_DB.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{HUB_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.OperationalError:
        return []
    try:
        exclude = _current_project_id()
        sql = (
            "SELECT project_id, description, lesson, severity, recurrence_count, phase "
            "FROM errors"
        )
        params: list = []
        if exclude:
            sql += " WHERE project_id != ?"
            params.append(exclude)
        sql += (
            " ORDER BY recurrence_count DESC, "
            " CASE severity "
            "   WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "   WHEN 'medium' THEN 2 ELSE 3 END "
            " LIMIT ?"
        )
        params.append(MAX_ERRORS)
        return [dict(r) for r in conn.execute(sql, params)]
    except sqlite3.Error:
        return []
    finally:
        conn.close()


def _format_context(errors: list[dict]) -> str:
    if not errors:
        return ""
    lines = [
        "## APEX — Lecciones cross-project a respetar en esta sesión",
        "",
        "_Auto-inyectado por `.claude/hooks/session-start.py` desde `apex-hub/data/hub.db`. "
        "Son errores documentados en OTROS proyectos que NO debes repetir aquí._",
        "",
    ]
    for i, e in enumerate(errors, 1):
        sev = e.get("severity", "medium")
        rec = e.get("recurrence_count", 1)
        lines.append(
            f"{i}. **[{e['project_id']} · {sev} · x{rec}]** {e['description'][:220]}"
        )
        lesson = (e.get("lesson") or "").strip()
        if lesson:
            lines.append(f"   - **Lección:** {lesson[:260]}")
    lines.append("")
    lines.append(
        "Antes de tomar decisiones de diseño/stack/arquitectura, usa "
        "`apex_search_cross_project(query)` para consultar casos similares."
    )
    return "\n".join(lines)


def main() -> None:
    # stdin: JSON con metadatos del evento (session_id, source, cwd, etc).
    # No lo necesitamos, pero lo consumimos para no dejar el pipe colgando.
    try:
        sys.stdin.read()
    except Exception:
        pass

    try:
        errors = _read_top_errors()
        context_md = _format_context(errors)
        if not context_md:
            # Sin lecciones que inyectar → salir silencioso (hook no-op).
            sys.exit(0)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context_md,
            }
        }
        print(json.dumps(output, ensure_ascii=False))
    except Exception:
        # Nunca romper el arranque de la sesión por un error del hook.
        sys.exit(0)


if __name__ == "__main__":
    main()
