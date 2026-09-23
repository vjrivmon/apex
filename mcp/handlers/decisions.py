"""APEX MCP handler: decisions."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
from apex_handlers._common import sync_to_obsidian as _sync_to_obsidian
from apex_handlers._common import vault_project_id as _vault_project_id
from typing import Any

import global_memory as _global_mem


async def handle_apex_add_decision(db: Any, arguments: dict) -> Any:
    """Handler for apex_add_decision."""
    did = await db.add_decision(
        arguments["category"], arguments["decision"], arguments["reasoning"],
        phase=arguments.get("phase"), alternatives=arguments.get("alternatives", ""))
    _project = _vault_project_id(db.db_path)
    _sync_to_obsidian("decision", {"project": _project, "category": arguments["category"], "decision": arguments["decision"]})
    return [TextContent(type="text", text=f"Decisión #{did} registrada: {arguments['decision'][:80]}")]

async def handle_apex_invalidate_decision(db: Any, arguments: dict) -> Any:
    """Handler for apex_invalidate_decision."""
    await db.invalidate_decision(arguments["decision_id"], arguments.get("reason", ""))
    return [TextContent(type="text", text=f"Decisión #{arguments['decision_id']} invalidada")]

async def handle_apex_add_error(db: Any, arguments: dict) -> Any:
    """Handler for apex_add_error."""
    severity = arguments.get("severity", "medium")
    eid = await db.add_error(
        arguments["source"], arguments["description"], arguments["lesson"],
        phase=arguments.get("phase"), severity=severity)
    _project = _vault_project_id(db.db_path)
    _sync_to_obsidian("error", {"project": _project, "source": arguments["source"], "description": arguments["description"]})
    # Los graves (critical|high) se añaden a la memoria global append-only
    # (~/.apex/context.db) con el id de origen. Best-effort.
    to_global = _global_mem.record_grave_error(
        _project, arguments["description"], arguments["lesson"],
        severity=severity, source=arguments["source"], phase=arguments.get("phase"))
    gmsg = " · añadido a memoria global de errores graves" if to_global else ""
    return [TextContent(type="text", text=f"Error #{eid} registrado [{arguments['source']}]: {arguments['description'][:80]}{gmsg}")]

