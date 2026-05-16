"""APEX MCP handler: context."""
from __future__ import annotations
from typing import Any


async def handle_apex_init_project(db: Any, arguments: dict) -> Any:
    """Handler for apex_init_project."""
    root = _find_project_root()
    await db.initialize()
    await db.set_meta("nombre", arguments["name"])
    if arguments.get("description"):
        await db.set_meta("descripción", arguments["description"])
    if arguments.get("solution_type"):
        await db.set_meta("tipo_solución", arguments["solution_type"])
    # Crear wiki scaffold
    domain = arguments.get("domain", "")
    wiki_dir = create_wiki(str(root), arguments["name"], domain)
    return [TextContent(type="text", text=f"Proyecto inicializado en {root}/.apex/\n- context.db creada con 15 fases\n- Wiki scaffold en {wiki_dir}")]

async def handle_apex_get_context(db: Any, arguments: dict) -> Any:
    """Handler for apex_get_context."""
    level = arguments.get("level", "timeline")
    if not (await _db_exists(db)):
        return [TextContent(type="text", text="No se encontró .apex/context.db en este proyecto. Usa apex_init_project primero.")]

async def handle_apex_set_phase(db: Any, arguments: dict) -> Any:
    """Handler for apex_set_phase."""
    phase_n = arguments["phase_number"]
    new_status = arguments["status"]
    force = bool(arguments.get("force", False))
    force_reason = arguments.get("force_reason", "")

    # Sprint 8: consultar último verdict del grader
    blocking_phase = phase_n if new_status == "completed" else (phase_n - 1 if new_status == "in_progress" else None)
    verdict = None
    if blocking_phase is not None and blocking_phase >= 0:
        verdict = await db.get_latest_verdict(blocking_phase)

    if verdict and verdict.get("should_block") and not force:
        msg_lines = [
            f"BLOQUEADO por grader (verdict #{verdict['id']} de fase {blocking_phase}):",
            f"  Quality: {verdict['quality']}/4",
            f"  Issues: {', '.join(verdict['issues']) or '(ninguna)'}",
            f"  Razón: {verdict['reasoning']}",
            "",
            "Para bypassear: apex_set_phase(..., force=True, force_reason='...')",
            "Para resolver: ataca los issues y vuelve a llamar apex_grader_evaluate.",
        ]
        return [TextContent(type="text", text="\n".join(msg_lines))]

async def handle_apex_search(db: Any, arguments: dict) -> Any:
    """Handler for apex_search."""
    mode = arguments.get("mode", "hybrid")
    limit = arguments.get("limit", 10)
    if mode == "fts":
        results = await db.search(arguments["query"], limit=limit)
        formatter = lambda r: f"- [{r['source']}] {r['content'][:150]}"
    return [TextContent(type='text', text='OK')]

async def handle_apex_log_session(db: Any, arguments: dict) -> Any:
    """Handler for apex_log_session."""
    await db.log_session(
        arguments["summary"], key_outcomes=arguments.get("key_outcomes", ""),
        phase=arguments.get("phase"))
    _project = await db.get_meta("nombre") or "unknown"
    _sync_to_obsidian("session", {"project": _project, "summary": arguments["summary"]})
    return [TextContent(type="text", text=f"Sesión registrada: {arguments['summary'][:80]}")]

