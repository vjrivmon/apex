"""APEX MCP handler: curator."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
import curator as _curator
from typing import Any


def _fallo(cfg: dict) -> str:
    return (
        f"Fallo al llamar a {cfg['model']} en {cfg['host']} "
        f"(timeout {cfg['timeout']}s). El curador ha caído a la heurística: "
        "APEX sigue funcionando exactamente igual que sin curador."
    )


async def handle_apex_curator_status(db: Any, arguments: dict) -> Any:
    """Handler for apex_curator_status."""
    import json as _json
    payload = _curator.status(getattr(db, "db_path", None))
    return [TextContent(
        type="text",
        text=_json.dumps(payload, ensure_ascii=False, indent=2),
    )]


async def handle_apex_curator_test(db: Any, arguments: dict) -> Any:
    """Handler for apex_curator_test."""
    texto = str(arguments.get("text") or "")
    kind = str(arguments.get("kind") or "summarize")
    docs = [str(d) for d in (arguments.get("docs") or [])]

    if kind not in ("summarize", "embed", "rerank"):
        return [TextContent(type="text", text=(
            f"kind desconocido: {kind!r}. Use summarize, embed o rerank."
        ))]

    cfg = _curator.curator_config()
    if not cfg["model"]:
        return [TextContent(type="text", text=(
            "Curador OFF: APEX_CURATOR_MODEL no está definida.\n"
            "Siguen usándose las heurísticas actuales (corte por caracteres, "
            "plantilla fija de handoff, ranking BM25)."
        ))]

    curador = _curator.get_curator(db_path=getattr(db, "db_path", None))

    if kind == "embed":
        vector = curador.embed(texto)
        if vector is None:
            return [TextContent(type="text", text=_fallo(cfg))]
        return [TextContent(type="text", text=(
            f"Curador OK · model={cfg['model']} · host={cfg['host']}\n"
            f"dimensión del vector: {len(vector)}"
        ))]

    if kind == "rerank":
        orden = curador.rerank(texto, docs or [texto])
        if orden is None:
            return [TextContent(type="text", text=_fallo(cfg))]
        return [TextContent(type="text", text=(
            f"Curador OK · model={cfg['model']} · host={cfg['host']}\n"
            f"orden de relevancia (índices de los docs): {orden}"
        ))]

    resumen = curador.summarize(
        texto or "prueba de conectividad del curador de APEX", max_tokens=200)
    if resumen is None:
        return [TextContent(type="text", text=_fallo(cfg))]
    return [TextContent(type="text", text=(
        f"Curador OK · model={cfg['model']} · host={cfg['host']}\n\n{resumen}"
    ))]
