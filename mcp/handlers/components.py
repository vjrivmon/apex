"""APEX MCP handler: components."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
from apex_handlers._common import sync_to_obsidian as _sync_to_obsidian
from apex_handlers._common import vault_project_id as _vault_project_id
from typing import Any


async def handle_apex_add_component(db: Any, arguments: dict) -> Any:
    """Handler for apex_add_component."""
    await db.add_component(
        arguments["id"], arguments["name"], arguments["type"],
        phase=arguments.get("phase"), description=arguments.get("description", ""),
        files=arguments.get("files"))
    if arguments.get("status") and arguments["status"] != "planned":
        await db.update_component_status(arguments["id"], arguments["status"])
    _project = _vault_project_id(db.db_path)
    _sync_to_obsidian("component", {"project": _project, "name": arguments["name"], "type": arguments["type"]})
    return [TextContent(type="text", text=f"Componente '{arguments['name']}' registrado como {arguments.get('status', 'planned')}")]

async def handle_apex_update_component(db: Any, arguments: dict) -> Any:
    """Handler for apex_update_component."""
    await db.update_component_status(arguments["id"], arguments["status"])
    return [TextContent(type="text", text=f"Componente '{arguments['id']}' → {arguments['status']}")]

async def handle_apex_add_next_step(db: Any, arguments: dict) -> Any:
    """Handler for apex_add_next_step."""
    sid = await db.add_next_step(
        arguments["description"], priority=arguments.get("priority", 5),
        phase=arguments.get("phase"))
    return [TextContent(type="text", text=f"Paso #{sid} añadido [P{arguments.get('priority', 5)}]: {arguments['description'][:80]}")]

async def handle_apex_complete_step(db: Any, arguments: dict) -> Any:
    """Handler for apex_complete_step."""
    await db.complete_step(arguments["step_id"])
    return [TextContent(type="text", text=f"Paso #{arguments['step_id']} completado")]

