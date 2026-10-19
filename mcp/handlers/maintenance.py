"""APEX MCP handler: mantenimiento de la base de contexto.

`lib/db_compact.py` estaba escrito desde el Sprint 12 pero sin un solo
importador: nadie podía invocarlo. Esta tool lo hace alcanzable, que es lo
que el propio módulo pedía en su docstring ("Usage (from MCP tool or hook)").
"""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
from apex_handlers._common import find_project_root as _find_project_root
import db_compact as _db_compact
from typing import Any


async def handle_apex_db_compact(db: Any, arguments: dict) -> Any:
    """Handler for apex_db_compact."""
    root = _find_project_root()
    db_path = root / ".apex" / "context.db"
    retention_days = int(arguments.get("retention_days", 30))
    if not db_path.exists():
        return [TextContent(
            type="text",
            text=f"No hay context.db en {db_path}. Nada que compactar.",
        )]

    stats = _db_compact.apex_db_compact(db_path, retention_days=retention_days)

    lines = [
        f"Compactación de {db_path}",
        f"  retención: {retention_days} días",
        f"  filas eliminadas: {stats.get('rows_deleted', 0)}",
        f"  tamaño antes: {stats.get('vacuum_before_kb', 0)} KB",
        f"  tamaño después: {stats.get('vacuum_after_kb', 0)} KB",
    ]
    cleaned = stats.get("tables_cleaned") or []
    if cleaned:
        lines.append(f"  tablas limpiadas: {', '.join(cleaned)}")
    skipped = stats.get("tables_skipped") or []
    if skipped:
        lines.append("  tablas omitidas:")
        for item in skipped:
            lines.append(f"    - {item}")
    errors = stats.get("errors") or []
    if errors:
        lines.append("  ERRORES:")
        for item in errors:
            lines.append(f"    - {item}")
    return [TextContent(type="text", text="\n".join(lines))]
