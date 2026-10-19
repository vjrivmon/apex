"""APEX MCP handler: VirtualFS cross-project (Sprint 17).

El VirtualFS expone los proyectos del ecosistema como un filesystem
read-only con primitivas UNIX (`ls`, `cat`, `grep`, `find`). Estas cuatro
tools lo hacen alcanzable desde el agente:

- `apex_vfs_exec`  — una línea tipo bash limitada (whitelist de comandos)
- `apex_vfs_ls`    — listado
- `apex_vfs_cat`   — lectura de un fichero
- `apex_vfs_grep`  — búsqueda con flags POSIX

El exec NO usa `subprocess`: el comando se parsea con una whitelist
explícita (riesgo R3 del blueprint). El VirtualFS es read-only: cualquier
escritura devuelve EROFS.

La whitelist de raíces sale de `hub.db.global_meta.vfs_allowed_roots`
(default `~/RoadToDevOps` + el ApexVault). `hub.db` se abre siempre en
solo-lectura; el caché de renders y la telemetría van a la `context.db`
del proyecto actual.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path
from typing import Any

from mcp.types import TextContent

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lib"))

import vfs as _vfs  # noqa: E402
import vfs_grep as _vfs_grep  # noqa: E402
import vfs_sql_render as _vfs_sql_render  # noqa: E402
from apex_handlers._common import _HUB_DB  # noqa: E402
from apex_handlers._common import find_project_root as _find_project_root  # noqa: E402
from apex_handlers._common import vault_dir  # noqa: E402

#: Extrae el slug de un proyecto de un texto con paths `/projects/<slug>`.
_PROJECT_SLUG_RE = re.compile(r"/projects/([^/\s]+)")

#: Tools del VirtualFS. No requieren un `db` de proyecto: el VFS es
#: cross-project y se puede consultar desde cualquier directorio (el
#: dispatcher puede despacharlas con `db=None`, como hace con
#: `LIBRARY_TOOLS`). El caché y la telemetría se pierden si no hay
#: `.apex/context.db` en el proyecto actual, pero la lectura funciona.
VFS_TOOLS = frozenset({
    "apex_vfs_exec", "apex_vfs_ls", "apex_vfs_cat", "apex_vfs_grep",
})


def _default_roots() -> list[Path]:
    """Raíces por defecto del VirtualFS: el ecosistema de proyectos."""
    return [Path.home() / "RoadToDevOps"]


def _proyecto_db_path(db: Any) -> Path | None:
    """`context.db` del proyecto actual: ahí va el caché y la telemetría.

    Si el dispatcher no pasa `db` (el VFS es cross-project y puede
    llamarse desde fuera de un proyecto), se busca el `.apex/context.db`
    del directorio de trabajo. Si no hay ninguno, no hay caché ni
    telemetría, pero la lectura sigue funcionando.
    """
    if db is not None:
        path = getattr(db, "db_path", None)
        if path is not None:
            return Path(path)
    candidate = _find_project_root() / ".apex" / "context.db"
    return candidate if candidate.exists() else None


def _build_vfs(db: Any) -> _vfs.VirtualFS:
    """Construye el VirtualFS con la whitelist del hub y el materializador SQL.

    El materializador (`vfs_sql_render.SqlMaterializer`) convierte las
    categorías virtuales (`errors`, `skills-history`, `lessons-*`) en
    markdown cacheado en `vfs_render_cache`.
    """
    vfs = _vfs.VirtualFS.from_hub_with_defaults(
        _HUB_DB,
        default_roots=_default_roots(),
        default_vault=vault_dir(),
    )
    vfs.materializer = _vfs_sql_render.SqlMaterializer(
        vfs, cache_db_path=_proyecto_db_path(db), hub_db_path=_HUB_DB
    )
    return vfs


def _slug_from_path(path: str) -> str | None:
    """Slug del proyecto de un path virtual (`/projects/<slug>/...`).

    También funciona con una línea de exec (`ls /projects/apex/wiki`): lo
    que se registra en la telemetría es el proyecto consultado, no el
    comando entero.
    """
    parts = [p for p in (path or "").split("/") if p]
    if len(parts) >= 2 and parts[0] == "projects":
        return parts[1]
    match = _PROJECT_SLUG_RE.search(path or "")
    return match.group(1) if match else None


def _log_query(
    db: Any, command: str, project_slug: str | None, hits: int, latency_ms: int
) -> None:
    """Registra la consulta en `vfs_query_log` (telemetría del Sprint 17)."""
    cache_db = _proyecto_db_path(db)
    if cache_db is None:
        return
    log = _vfs_sql_render.QueryLog(cache_db)
    log.record(command, project_slug, hits, latency_ms)


def _error(exc: Exception) -> list[TextContent]:
    return [TextContent(type="text", text=f"ERROR: {exc}")]


# ── apex_vfs_ls ─────────────────────────────────────────────────────────


async def handle_apex_vfs_ls(db: Any, arguments: dict) -> Any:
    """Handler for apex_vfs_ls."""
    path = arguments.get("path", "/")
    started = time.monotonic()
    try:
        vfs = _build_vfs(db)
        entries = vfs.ls(path)
    except _vfs.VFSError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001 — la tool no debe romper el server
        return _error(exc)

    payload = {
        "path": path,
        "entries": [
            {
                "name": entry.name,
                "kind": entry.kind,
                "size_bytes": entry.size_bytes,
            }
            for entry in entries
        ],
    }
    _log_query(
        db,
        f"ls {path}",
        _slug_from_path(path),
        len(entries),
        int((time.monotonic() - started) * 1000),
    )
    return [TextContent(
        type="text",
        text=json.dumps(payload, ensure_ascii=False, indent=2),
    )]


# ── apex_vfs_cat ────────────────────────────────────────────────────────


async def handle_apex_vfs_cat(db: Any, arguments: dict) -> Any:
    """Handler for apex_vfs_cat."""
    path = arguments.get("path", "")
    if not path:
        return _error("falta 'path'")
    started = time.monotonic()
    try:
        vfs = _build_vfs(db)
        content = vfs.cat(path)
    except _vfs.VFSError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)

    _log_query(
        db,
        f"cat {path}",
        _slug_from_path(path),
        1,
        int((time.monotonic() - started) * 1000),
    )
    return [TextContent(type="text", text=content)]


# ── apex_vfs_grep ───────────────────────────────────────────────────────


async def handle_apex_vfs_grep(db: Any, arguments: dict) -> Any:
    """Handler for apex_vfs_grep."""
    pattern = arguments.get("pattern", "")
    if not pattern:
        return _error("falta 'pattern'")
    path = arguments.get("path", "/projects")
    flags = arguments.get("flags", "") or ""
    started = time.monotonic()
    try:
        vfs = _build_vfs(db)
        outcome = _vfs_grep.grep_detailed(
            vfs, pattern, path, flags, use_fts_prefilter=True
        )
    except ValueError as exc:
        return _error(exc)
    except _vfs.VFSError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)

    lines: list[str] = []
    for warning in outcome.warnings:
        lines.append(f"AVISO: {warning}")
    if outcome.hits:
        for hit in outcome.hits:
            if "l" in flags:
                lines.append(hit.virtual_path)
            elif "n" in flags:
                lines.append(f"{hit.virtual_path}:{hit.line_num}:{hit.line}")
            else:
                lines.append(f"{hit.virtual_path}:{hit.line}")
    else:
        lines.append(f"Sin coincidencias para {pattern!r} en {path}")

    _log_query(
        db,
        f"grep {flags} {pattern} {path}".strip(),
        _slug_from_path(path),
        len(outcome.hits),
        int((time.monotonic() - started) * 1000),
    )
    return [TextContent(type="text", text="\n".join(lines))]


# ── apex_vfs_exec ───────────────────────────────────────────────────────


async def handle_apex_vfs_exec(db: Any, arguments: dict) -> Any:
    """Handler for apex_vfs_exec."""
    command = arguments.get("command", "")
    if not command:
        return _error("falta 'command'")
    started = time.monotonic()
    try:
        vfs = _build_vfs(db)
        result = _vfs.run_exec(vfs, command)
    except _vfs.VFSError as exc:
        return _error(exc)
    except Exception as exc:  # noqa: BLE001
        return _error(exc)

    payload: dict[str, Any] = {
        "stdout": result.stdout,
        "stderr": result.stderr,
        "exit_code": result.exit_code,
    }
    if result.warnings:
        payload["warnings"] = list(result.warnings)

    hits = 0
    if result.stdout:
        hits = len(result.stdout.splitlines())
    _log_query(
        db,
        command,
        _slug_from_path(command),
        hits,
        int((time.monotonic() - started) * 1000),
    )
    return [TextContent(
        type="text",
        text=json.dumps(payload, ensure_ascii=False, indent=2),
    )]
