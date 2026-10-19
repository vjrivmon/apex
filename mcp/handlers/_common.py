"""Shared utilities for APEX MCP handler modules."""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

# La raiz del repo, para importar `lib.project_root` (implementacion unica).
_LIB = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
if str(_LIB.parent) not in sys.path:
    sys.path.append(str(_LIB.parent))
from lib.project_root import resolve_project_root as _resolve_project_root  # noqa: E402
from lib.fts_query import build_fts_or_query as _build_fts_or_query  # noqa: E402


# --- Hub constants ---
_HUB_DIR = Path.home() / "RoadToDevOps" / "apex-hub"
_HUB_DB = _HUB_DIR / "data" / "hub.db"


def find_project_root() -> Path:
    """Raíz del proyecto APEX: delega en `lib/project_root.py`.

    La implementación es ÚNICA y vive en `lib/project_root.py`
    (`resolve_project_root()`): sube desde el CWD hasta encontrar `.apex/` o
    `.git/`, NUNCA sube hasta el home (`~/.apex/` es config global y memoria
    de errores graves, no un proyecto) y, si no hay proyecto, devuelve el CWD.

    Antes de 2026-10-19 esta función tenía su propia copia de la lógica, y
    no coincidía con la de los hooks: acababa escribiendo en la BD global.
    """
    return _resolve_project_root()


async def db_exists(db) -> bool:
    """Verifica si context.db existe."""
    return db.db_path.exists()


def vault_dir() -> Path:
    """Vault de Obsidian. APEX_VAULT_DIR lo redirige (los tests lo apuntan a tmp)."""
    return Path(os.environ.get("APEX_VAULT_DIR", Path.home() / "Documents" / "ApexVault")).expanduser()


def vault_project_id(db_path) -> str:
    """Id del proyecto con la misma fórmula que apex-hub (scanner._project_id_from_path):
    así `<id>-log.md` y la ficha exportada por el hub se llaman igual. No usa la meta
    `nombre`, que es libre y sin ella todo caía en unknown-log.md."""
    return Path(db_path).parent.parent.name.lower().replace(" ", "-")


_LEAKED_CALL = re.compile(r'(?m)^[ \t]*(?:</?invoke\b|<parameter name="|</parameter>)')


def leaked_call_markup(arguments: dict) -> str | None:
    """Nombre del argumento que trae sintaxis de otra llamada a tool, o None.

    Una llamada mal formada mete los parámetros siguientes (`alternatives`,
    `phase`, `lesson`...) dentro del texto del anterior. Se guardaba tal cual:
    el 2026-09-23 había 51 registros así en 9 proyectos, y el texto rompía el
    render en Obsidian. Solo cuenta al inicio de línea, que es donde aparece la
    fuga; mencionarlo dentro de una frase o entre backticks no la dispara.
    """
    for key, value in arguments.items():
        if isinstance(value, str) and _LEAKED_CALL.search(value):
            return key
    return None


def sync_to_obsidian(event_type: str, data: dict) -> None:
    """Escribe una nota en el vault de Obsidian cada vez que el MCP registra algo.
    No falla si el vault no existe."""
    _OBSIDIAN_VAULT = vault_dir()
    try:
        if not _OBSIDIAN_VAULT.exists():
            return

        project_name = data.get("project", "unknown")
        # Misma carpeta que exporta apex-hub: projects/<id>/{<id>,decisiones,...,log}.md
        project_dir = _OBSIDIAN_VAULT / "projects" / project_name
        project_dir.mkdir(parents=True, exist_ok=True)
        log_file = project_dir / "log.md"

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        if event_type == "decision":
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Decisión [{data.get('category', '')}]: {data.get('decision', '')[:100]}\n")
        elif event_type == "error":
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Error [{data.get('source', '')}]: {data.get('description', '')[:100]}\n")
        elif event_type == "phase":
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Fase {data.get('phase', '?')} → {data.get('status', '?')}\n")
        elif event_type == "component":
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Componente: {data.get('name', '')} ({data.get('type', '')})\n")
        elif event_type == "session":
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

        # FTS5 hace AND implícito: MATCH "a b c" exige las tres palabras en
        # la MISMA fila. Pasando la consulta cruda, una pregunta natural
        # ("memoria global errores graves") devolvía 0 hits aunque la base
        # tuviera las palabras repartidas en 365 filas distintas. Medido
        # contra el hub.db real el AND daba 0 y el OR 365.
        # La consulta se ensancha; el ORDER BY rank (BM25) sigue ordenando
        # por relevancia. Ver lib/fts_query.py.
        or_q = _build_fts_or_query(fts_q)
        if not or_q:
            return {**empty, "hub_available": True}

        sql = (
            "SELECT project_id, source_type, source_id, "
            "snippet(hub_search, 3, '[', ']', '...', 24) AS snip, rank "
            "FROM hub_search WHERE hub_search MATCH ?"
        )
        params: list = [or_q]
        if exclude_project:
            sql += " AND project_id != ?"
            params.append(exclude_project)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit * 3)

        try:
            rows = [dict(r) for r in conn.execute(sql, params)]
        except sqlite3.OperationalError:
            # Sintaxis FTS5 inválida → reintento como frase exacta del original
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
