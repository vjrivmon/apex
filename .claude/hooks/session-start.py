#!/usr/bin/env python3
"""SessionStart hook para APEX — inyecta lecciones cross-project al contexto.

Lee ~/RoadToDevOps/apex-hub/data/hub.db (agregada por apex-hub) y extrae los
errores cross-project más recurrentes de OTROS proyectos para evitar repetirlos.
La recurrencia se calcula al leer (proyectos distintos con la misma firma),
no leyendo `hub.db.errors.recurrence_count`, que es la recurrencia local y
siempre vale 1. Devuelve JSON con `hookSpecificOutput.additionalContext` que
Claude Code inyecta directamente en el contexto al iniciar la sesión.

Best-effort: si hub.db no existe o hay cualquier error, devuelve stdout vacío
(el hook no bloquea nunca el arranque de la sesión).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

# La raíz del repo debe estar en sys.path ANTES de `from lib.…`:
# el hook puede ejecutarse desde cualquier cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.hook_metrics import start_hook, end_hook

HUB_DB = Path.home() / "RoadToDevOps" / "apex-hub" / "data" / "hub.db"
INGEST_REMINDER_THRESHOLD = int(
    os.environ.get("APEX_LIBRARY_INGEST_THRESHOLD", "5")
)


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
    """Errores cross-project con recurrencia real, agrupados y ordenados.

    Antes esta función hacía `ORDER BY recurrence_count DESC` sobre
    `hub.db.errors`, pero ese valor es la recurrencia LOCAL (sólo sube si el
    mismo error se repite en la misma `context.db`) y el escáner del hub lo
    copia tal cual: las 367 filas tienen `recurrence_count = 1`. El orden era
    degenerado y el `LIMIT 5` devolvía siempre los mismos errores.

    Ahora la recurrencia se calcula al leer, agrupando por firma y contando
    PROYECTOS DISTINTOS: un error que aparece en 4 proyectos es una lección
    del ecosistema. Ver `lib/cross_project_errors.py`.
    """
    from lib.cross_project_errors import top_errors

    return top_errors(HUB_DB, exclude_project=_current_project_id())


def _bump_visit_counter(project_id: str) -> int:
    """Añade el `project_id` actual al set de proyectos visitados desde la
    última ingesta de skills externas. Devuelve len(set) tras añadir.

    Persiste en `hub.db` tabla `global_meta` (creada on-demand). Best-effort:
    si hub.db no existe o falla, devuelve 0 (no dispara recordatorio).
    """
    if not HUB_DB.exists() or not project_id:
        return 0
    try:
        conn = sqlite3.connect(str(HUB_DB))
    except sqlite3.OperationalError:
        return 0
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS global_meta ("
            "key TEXT PRIMARY KEY, value TEXT, "
            "updated_at TEXT DEFAULT (datetime('now')))"
        )
        row = conn.execute(
            "SELECT value FROM global_meta WHERE key=?",
            ("library_ingest_visit_set",),
        ).fetchone()
        try:
            visited = set(json.loads(row[0])) if row and row[0] else set()
        except (TypeError, ValueError, json.JSONDecodeError):
            visited = set()
        visited.add(project_id)
        conn.execute(
            "INSERT OR REPLACE INTO global_meta (key, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            ("library_ingest_visit_set", json.dumps(sorted(visited))),
        )
        conn.commit()
        return len(visited)
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _ingest_reminder(visit_count: int) -> str:
    if visit_count < INGEST_REMINDER_THRESHOLD:
        return ""
    return (
        "\n\n## APEX — Recordatorio: ingesta de skills externas\n\n"
        f"Llevas **{visit_count} proyectos** sin ingerir skills nuevas desde "
        f"GitHub o `library-skills.io` (umbral={INGEST_REMINDER_THRESHOLD}). "
        "Si quieres descubrir skills curadas por la comunidad para tener "
        "más herramientas a mano, corre:\n\n"
        "```\napex_ingest_library_skills(source=\"both\")\n```\n\n"
        "Esto descarga candidatas, valida frontmatter y secretos, y deja "
        "propuestas en `.apex/skill-proposals/import-*.md` para que las "
        "apruebes una a una con `apex_skill_forge_approve(slug)`.\n\n"
        "Si prefieres saltar este recordatorio en este proyecto, ignóralo: "
        "el contador no avanza dos veces para el mismo proyecto."
    )


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
        n_proj = e.get("project_count", 1)
        proyectos = ", ".join(e.get("projects", []))
        lines.append(
            f"{i}. **[{sev} · {n_proj} proyecto{'s' if n_proj != 1 else ''}]** "
            f"{e['description'][:220]}"
        )
        if proyectos:
            lines.append(f"   - **Visto en:** {proyectos}")
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
    _hook_start = start_hook("session-start")
    # stdin: JSON con metadatos del evento (session_id, source, cwd, etc).
    # No lo necesitamos, pero lo consumimos para no dejar el pipe colgando.
    try:
        sys.stdin.read()
    except Exception:
        pass

    try:
        errors = _read_top_errors()
        context_md = _format_context(errors)

        # Sprint 11.3: contador cross-project para recordar la ingesta de
        # skills externas cada N proyectos distintos.
        try:
            project_id = _current_project_id() or ""
            visits = _bump_visit_counter(project_id)
            reminder = _ingest_reminder(visits)
        except Exception:
            reminder = ""
        context_md = (context_md or "") + reminder

        if not context_md.strip():
            end_hook("session-start", _hook_start, exit_code=0)
            sys.exit(0)
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context_md,
            }
        }
        print(json.dumps(output, ensure_ascii=False))
        end_hook("session-start", _hook_start, exit_code=0)
    except Exception as e:  # noqa: BLE001
        # Nunca romper el arranque de la sesión por un error del hook, pero
        # tampoco callarlo: sin este aviso, un fallo aquí se manifiesta como
        # "el contexto cross-project dejó de aparecer" sin pista de por qué.
        print(
            f"[session-start] El hook falló y no inyectó contexto: "
            f"{type(e).__name__}: {e}",
            file=sys.stderr,
        )
        end_hook("session-start", _hook_start, exit_code=0)
        sys.exit(0)


if __name__ == "__main__":
    main()
