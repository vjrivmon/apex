"""APEX MCP handler: portfolio."""
from __future__ import annotations
from typing import Any


async def handle_apex_set_portfolio_meta(db: Any, arguments: dict) -> Any:
    """Handler for apex_set_portfolio_meta."""
    fields = arguments["fields"] or {}
    if not isinstance(fields, dict):
        return [TextContent(type="text", text="fields debe ser un objeto {key: value}")]

async def handle_apex_portfolio_draft(db: Any, arguments: dict) -> Any:
    """Handler for apex_portfolio_draft."""
    slug = arguments["slug"]
    apply = bool(arguments.get("apply", False))
    out_dir = Path(arguments["out_dir"]) if arguments.get("out_dir") else _PORTFOLIO_OUT_DIR
    root = _find_project_root()
    ctx_db = root / ".apex" / "context.db"
    if not ctx_db.exists():
        return [TextContent(type="text", text=(
            f"No se encontró {ctx_db}. Inicia el proyecto con apex_init_project primero."
        ))]

