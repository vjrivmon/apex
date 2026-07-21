"""APEX MCP handler: portfolio."""
from __future__ import annotations
from portfolio_publish import generate as _portfolio_generate

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from pathlib import Path
from mcp.types import TextContent
from portfolio_publish import DEFAULT_OUT_DIR as _PORTFOLIO_OUT_DIR
from apex_handlers._common import find_project_root as _find_project_root
from typing import Any


async def handle_apex_set_portfolio_meta(db: Any, arguments: dict) -> Any:
    """Handler for apex_set_portfolio_meta."""
    fields = arguments["fields"] or {}
    if not isinstance(fields, dict):
        return [TextContent(type="text", text="fields debe ser un objeto {key: value}")]
    else:
        import json as _json
        saved = []
        for k, v in fields.items():
            key = k if k.startswith("portfolio_") else f"portfolio_{k}"
            if isinstance(v, (list, dict)):
                value = _json.dumps(v, ensure_ascii=False)
            elif isinstance(v, bool):
                value = "true" if v else "false"
            else:
                value = str(v) if v is not None else ""
            await db.set_meta(key, value)
            saved.append(key)
        return [TextContent(type="text", text=(
            f"Guardados {len(saved)} campos en project_meta: {', '.join(saved)}. "
            "Ejecuta apex_portfolio_draft para generar el MDX."
        ))]


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
    else:
        try:
            path = _portfolio_generate(slug, ctx_db, out_dir, apply=apply)
            content = path.read_text(encoding="utf-8")
            action = "Aplicado" if apply else "Draft generado"
            hint = (
                "\n\nRevisa el contenido y, si está bien, llama de nuevo con apply=true. "
                "Tras aplicar, commitear en vr-web y hacer push para que Vercel redeploy."
                if not apply else
                "\n\nAhora commitear en vr-web:\n"
                f"  cd ~/RoadToDevOps/vr-web && git add content/cases/{slug}.mdx && "
                f"git commit -m 'feat(cases): publica {slug} desde APEX' && git push"
            )
            return [TextContent(type="text", text=f"{action}: {path}\n\n{content}{hint}")]
        except FileNotFoundError as e:
            return [TextContent(type="text", text=f"Error: {e}")]


