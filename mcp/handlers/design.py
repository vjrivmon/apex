"""APEX MCP handler: design."""
from __future__ import annotations
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

