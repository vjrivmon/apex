"""APEX MCP handler: prototype."""
from __future__ import annotations
from typing import Any


async def handle_apex_prototype_init(db: Any, arguments: dict) -> Any:
    """Handler for apex_prototype_init."""
    root = _find_project_root()
    try:
        out = _prototype.apex_prototype_init(
            project_root=root,
            feature_name=arguments["feature_name"],
            states=arguments["states"],
            transitions=arguments["transitions"],
            initial_state=arguments["initial_state"],
            force=bool(arguments.get("force", False)),
        )
    except ValueError as e:
        return [TextContent(
            type="text", text=f"Validación falló: {e}")]

