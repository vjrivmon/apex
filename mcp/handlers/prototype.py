"""APEX MCP handler: prototype."""
from __future__ import annotations

from pathlib import Path

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
from apex_handlers._common import find_project_root as _find_project_root
import prototype as _prototype
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
    else:
        tui_rel = Path(out["tui_path"]).relative_to(root)
        wiki_rel = Path(out["wiki_path"]).relative_to(root)
        return [TextContent(
            type="text",
            text=(
                f"prototype #{out['machine_id']} listo:\n"
                f"  TUI: {tui_rel} (corre con: "
                f"`pip install textual && python {tui_rel}`)\n"
                f"  Wiki: {wiki_rel} (Mermaid stateDiagram + "
                f"reglas)\n"
                f"Mantén ambos sincronizados al editar la "
                f"máquina de estados."
            ),
        )]


