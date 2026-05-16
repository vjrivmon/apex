"""APEX MCP handler: decisions."""
from __future__ import annotations
from typing import Any


async def handle_apex_add_decision(db: Any, arguments: dict) -> Any:
    """Handler for apex_add_decision."""
    did = await db.add_decision(
        arguments["category"], arguments["decision"], arguments["reasoning"],
        phase=arguments.get("phase"), alternatives=arguments.get("alternatives", ""))
    _project = await db.get_meta("nombre") or "unknown"
    _sync_to_obsidian("decision", {"project": _project, "category": arguments["category"], "decision": arguments["decision"]})
    return [TextContent(type="text", text=f"Decisión #{did} registrada: {arguments['decision'][:80]}")]

async def handle_apex_invalidate_decision(db: Any, arguments: dict) -> Any:
    """Handler for apex_invalidate_decision."""
    await db.invalidate_decision(arguments["decision_id"], arguments.get("reason", ""))
    return [TextContent(type="text", text=f"Decisión #{arguments['decision_id']} invalidada")]

async def handle_apex_add_error(db: Any, arguments: dict) -> Any:
    """Handler for apex_add_error."""
    eid = await db.add_error(
        arguments["source"], arguments["description"], arguments["lesson"],
        phase=arguments.get("phase"), severity=arguments.get("severity", "medium"))
    _project = await db.get_meta("nombre") or "unknown"
    _sync_to_obsidian("error", {"project": _project, "source": arguments["source"], "description": arguments["description"]})
    return [TextContent(type="text", text=f"Error #{eid} registrado [{arguments['source']}]: {arguments['description'][:80]}")]

