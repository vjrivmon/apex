"""APEX MCP handler: library."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
from apex_handlers._common import _HUB_DB
from apex_handlers._common import find_project_root as _find_project_root
import library_ingest as _library
from typing import Any


async def handle_apex_ingest_library_skills(db: Any, arguments: dict) -> Any:
    """Handler for apex_ingest_library_skills."""
    project_root = _find_project_root()
    res = _library.ingest(
        project_root,
        source=arguments.get("source", "both"),
        query=arguments.get("query"),
        min_stars=int(arguments.get("min_stars", _library.GH_MIN_STARS)),
        limit_repos=int(arguments.get("limit_repos",
                                      _library.GH_DEFAULT_LIMIT_REPOS)),
        max_skills_per_repo=int(arguments.get(
            "max_skills_per_repo",
            _library.GH_MAX_SKILLS_PER_REPO,
        )),
    )
    if res.written and _HUB_DB.exists():
        try:
            _library.reset_visit_counter(_HUB_DB)
        except Exception:
            pass
    lines = [
        f"Library Ingest — fuentes: {', '.join(res.sources_used) or '(ninguna)'}",
        f"  repos GitHub revisados: {res.repos_searched}",
    ]
    if res.written:
        lines.append(f"  ○ propuestas nuevas ({len(res.written)}):")
        lines += [f"    - {s}" for s in res.written]
    if res.already_proposed:
        lines.append(f"  · ya propuestas ({len(res.already_proposed)}):")
        lines += [f"    - {s}" for s in res.already_proposed[:10]]
    if res.already_imported:
        lines.append(f"  · ya importadas, mismo SHA "
                     f"({len(res.already_imported)})")
    if res.rejected:
        lines.append(f"  ✗ rechazadas previamente ({len(res.rejected)})")
    if res.invalid:
        lines.append(f"  ⚠ inválidas ({len(res.invalid)}):")
        for slug, reason in res.invalid[:5]:
            lines.append(f"    - {slug}: {reason[:140]}")
    if not (res.written or res.already_proposed or res.already_imported
            or res.rejected or res.invalid):
        lines.append("  (sin candidatas)")
    lines.append("")
    lines.append("Aprobar: apex_skill_forge_approve(slug)")
    lines.append("Rechazar: apex_skill_forge_reject(slug, reason)")
    return [TextContent(type="text", text="\n".join(lines))]

