"""APEX MCP handler: design."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from pathlib import Path
from mcp.types import TextContent
import design_md as _design
from apex_handlers._common import find_project_root as _find_project_root
from typing import Any


async def handle_apex_design_md_init(db: Any, arguments: dict) -> Any:
    """Handler for apex_design_md_init."""
    project_root = _find_project_root()
    brand = arguments.get("brand_name", "Acme")
    overwrite = bool(arguments.get("overwrite", False))
    path = _design.init_design_md(project_root, brand_name=brand,
                                    overwrite=overwrite)
    existed = path.exists() and not overwrite
    msg = (f"DESIGN.md {'sobrescrito' if overwrite else 'inicializado'} "
           f"en {path}\nBrand: {brand}\n"
           f"Próximo: editar valores reales y commitear como prerequisito de fase 2.")
    return [TextContent(type="text", text=msg)]

async def handle_apex_design_md_validate(db: Any, arguments: dict) -> Any:
    """Handler for apex_design_md_validate."""
    project_root = _find_project_root()
    path_arg = arguments.get("path")
    path = Path(path_arg) if path_arg else _design.design_md_path(project_root)
    if not path.exists():
        return [TextContent(type="text", text=(
            f"DESIGN.md no existe en {path}. "
            f"Ejecuta apex_design_md_init primero."))]
    else:
        violations = _design.validate(path.read_text(encoding="utf-8"))
        return [TextContent(type="text", text=_design.format_violations(violations))]


