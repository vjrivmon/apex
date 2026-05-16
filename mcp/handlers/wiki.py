"""APEX MCP handler: wiki."""
from __future__ import annotations
from typing import Any


async def handle_apex_wiki_add(db: Any, arguments: dict) -> Any:
    """Handler for apex_wiki_add."""
    await db.add_wiki_page(
        arguments["slug"], arguments["title"], arguments["content"],
        page_type=arguments.get("page_type", "entity"),
        tags=arguments.get("tags"))
    # También escribir el archivo .md en el wiki filesystem
    root = _find_project_root()
    wiki_dir = root / ".apex" / "wiki"
    if wiki_dir.exists():
        page_path = wiki_dir / f"{arguments['slug']}.md"
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(f"# {arguments['title']}\n\n{arguments['content']}", encoding="utf-8")
        append_log(str(wiki_dir), f"Actualizada página: {arguments['slug']}")
        update_index(str(wiki_dir))
    return [TextContent(type="text", text=f"Wiki página '{arguments['slug']}' guardada")]

async def handle_apex_search_cross_project(db: Any, arguments: dict) -> Any:
    """Handler for apex_search_cross_project."""
    query = arguments["query"]
    limit = arguments.get("limit", 8)
    exclude_current = arguments.get("exclude_current", True)
    current_project = None
    if exclude_current:
        root = _find_project_root()
        current_project = root.name.lower().replace(" ", "-")
    hits = _search_cross_project(query, limit=limit, exclude_project=current_project)
    if not hits["hub_available"]:
        return [TextContent(type="text", text=(
            f"hub.db no disponible en {_HUB_DB}. Lanza apex-hub (python -m backend en "
            "~/RoadToDevOps/apex-hub/) para habilitar retrieval cross-project."
        ))]
    elif not (hits["errors"] or hits["decisions"] or hits["components"]):
        return [TextContent(type="text", text=(
            f"Sin hallazgos cross-project para '{query}'. "
            "No hay errores/decisiones previas que aplicar."
        ))]

async def handle_apex_ingest_source(db: Any, arguments: dict) -> Any:
    """Handler for apex_ingest_source."""
    src_path = Path(arguments["path"])
    if not src_path.is_absolute():
        src_path = _find_project_root() / src_path
    if not src_path.exists():
        return [TextContent(type="text", text=f"Path no existe: {src_path}")]

async def handle_apex_lint_second_brain(db: Any, arguments: dict) -> Any:
    """Handler for apex_lint_second_brain."""
    root = _find_project_root()
    apply = bool(arguments.get("apply", False))
    severity = arguments.get("severity")
    report = _run_lint(root, apply_fixes=apply)
    if severity:
        order = ("critical", "high", "medium", "low")
        idx = order.index(severity)
        report.findings = [f for f in report.findings if order.index(f.severity) <= idx]
    report_path = _write_lint_report(report)
    md = _render_lint_report(report)
    return [TextContent(type="text", text=f"{md}\n\n(Report: {report_path})")]

async def handle_apex_synthesize(db: Any, arguments: dict) -> Any:
    """Handler for apex_synthesize."""
    root = _find_project_root()
    trigger = arguments.get("trigger", "auto")
    min_score = float(arguments.get("min_score", 0.6))
    res = _synthesize(root, force=(trigger == "force"), min_score=min_score)
    import json as _json
    return [TextContent(type="text", text=_json.dumps(res, ensure_ascii=False, indent=2, default=str))]

