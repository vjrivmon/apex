"""APEX MCP handler: wiki."""
from __future__ import annotations
from ingest import ingest as _ingest_source, ingest_dir as _ingest_dir

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from pathlib import Path
from mcp.types import TextContent
from apex_handlers._common import _HUB_DB
from apex_handlers._common import find_project_root as _find_project_root
from lint import _render_report as _render_lint_report
from lint import run_lint as _run_lint
from apex_handlers._common import search_cross_project as _search_cross_project
import cross_project_flag as _cp_flag
from synthesis import synthesize as _synthesize
from lint import write_report as _write_lint_report
from wiki_scaffold import append_log
from wiki_scaffold import update_index
from wiki_scaffold import sanitize_slug
from wiki_scaffold import wiki_page_path
from wiki_scaffold import WikiPathError
from typing import Any


def _dentro_de(root: Path, destino: Path) -> bool:
    """¿`destino` (resuelto, symlinks incluidos) está dentro de `root`?"""
    try:
        return destino.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _resolver_ruta_ingesta(ruta: str, project_root: Path) -> Path:
    """Resuelve la ruta de la ingesta y la acota al proyecto.

    Reglas:
    - una ruta relativa se resuelve contra la raíz del proyecto;
    - una ruta absoluta sólo se acepta si está dentro de la raíz del proyecto
      (que incluye `.apex/raw/`);
    - la comprobación se hace sobre la ruta RESUELTA, así que un symlink que
      apunte fuera del proyecto también se rechaza.

    Lanza `ValueError` con el motivo y las rutas permitidas.
    """
    if not isinstance(ruta, str) or not ruta.strip():
        raise ValueError(
            "La ruta de la ingesta está vacía: se esperaba la ruta de un archivo "
            f"dentro del proyecto {project_root} (por ejemplo '.apex/raw/research/nota.md')."
        )
    candidata = Path(ruta).expanduser()
    if not candidata.is_absolute():
        candidata = project_root / candidata
    try:
        resuelta = candidata.resolve()
    except OSError as exc:
        raise ValueError(
            f"No se pudo resolver la ruta {ruta!r}: {exc}. Se esperaba una ruta dentro "
            f"del proyecto {project_root}."
        )
    permitidas = [project_root, project_root / ".apex" / "raw"]
    if not any(_dentro_de(raiz, resuelta) for raiz in permitidas):
        raise ValueError(
            f"La ruta {resuelta} está fuera del proyecto. Rutas permitidas: "
            f"{project_root} y sus subdirectorios (incluido {project_root / '.apex' / 'raw'})."
        )
    return resuelta


async def handle_apex_wiki_add(db: Any, arguments: dict) -> Any:
    """Handler for apex_wiki_add."""
    root = Path(_find_project_root())
    wiki_dir = root / ".apex" / "wiki"
    # El slug se valida ANTES de tocar la BD o el disco: un slug inválido es
    # un error visible, no una página guardada en un sitio raro.
    try:
        slug = sanitize_slug(arguments["slug"], wiki_dir=wiki_dir)
    except WikiPathError as exc:
        return [TextContent(type="text", text=f"ERROR: slug de wiki inválido. {exc}")]
    # La ruta de la página se resuelve antes de escribir nada, y tiene que
    # seguir dentro del proyecto (symlinks incluidos).
    page_path: Path | None = None
    if wiki_dir.exists():
        try:
            page_path = wiki_page_path(wiki_dir, slug)
        except WikiPathError as exc:
            return [TextContent(type="text", text=f"ERROR: {exc}")]
        if not _dentro_de(root, page_path):
            return [TextContent(type="text", text=(
                f"ERROR: la página {slug!r} se resolvería a {page_path.resolve()}, fuera "
                f"del proyecto {root}. Se esperaba una ruta dentro del wiki del proyecto."
            ))]
    await db.add_wiki_page(
        slug, arguments["title"], arguments["content"],
        page_type=arguments.get("page_type", "entity"),
        tags=arguments.get("tags"))
    # También escribir el archivo .md en el wiki filesystem
    if page_path is not None:
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(f"# {arguments['title']}\n\n{arguments['content']}", encoding="utf-8")
        append_log(str(wiki_dir), f"Actualizada página: {slug}")
        update_index(str(wiki_dir))
    return [TextContent(type="text", text=f"Wiki página '{slug}' guardada")]

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
    # Regla absoluta #18: consultar el hub cuenta como la consulta
    # cross-project que el grader exige en las fases de decisión.
    await _cp_flag.mark_consulted(db, arguments.get("phase"))
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
    else:
        lines = [f"Cross-project retrieval para '{query}':"]
        if hits["errors"]:
            lines.append(f"\n### Errores previos ({len(hits['errors'])})")
            for e in hits["errors"]:
                rec = e.get("recurrence_count", 1)
                sev = e.get("severity", "medium")
                lines.append(
                    f"- [{e['project_id']} · {sev} · x{rec}] {e['description'][:140]}"
                )
                if e.get("lesson"):
                    lines.append(f"  → Lección: {e['lesson'][:200]}")
        if hits["decisions"]:
            lines.append(f"\n### Decisiones previas ({len(hits['decisions'])})")
            for d in hits["decisions"]:
                tag = "INVALIDADA" if d.get("invalid_from") else "vigente"
                lines.append(
                    f"- [{d['project_id']} · {d.get('category','')} · {tag}] {d['decision'][:140]}"
                )
        if hits["components"]:
            lines.append(f"\n### Componentes previos ({len(hits['components'])})")
            for c in hits["components"]:
                lines.append(
                    f"- [{c['project_id']} · {c.get('type','')}] {c.get('name','')}: {(c.get('description') or '')[:120]}"
                )
        return [TextContent(type="text", text="\n".join(lines))]


async def handle_apex_ingest_source(db: Any, arguments: dict) -> Any:
    """Handler for apex_ingest_source."""
    project_root = Path(_find_project_root()).resolve()
    # La ingesta se acota al proyecto: rutas relativas contra la raíz del
    # proyecto y rutas absolutas sólo si caen dentro (symlinks incluidos).
    try:
        src_path = _resolver_ruta_ingesta(arguments["path"], project_root)
    except ValueError as exc:
        return [TextContent(type="text", text=f"ERROR: {exc}")]
    if not src_path.exists():
        return [TextContent(type="text", text=f"Path no existe: {src_path}")]
    else:
        auto_wiki = arguments.get("auto_wiki", True)
        recursive = arguments.get("recursive", True)
        if src_path.is_dir():
            results_list = _ingest_dir(
                src_path, project_root=project_root,
                recursive=recursive, write_wiki=auto_wiki, write_db=True,
            )
            lines = [f"Ingestados {len(results_list)} archivos desde {src_path}:"]
            for r in results_list:
                lines.append(
                    f"- {r.source.name} → {r.page_type}/{r.slug} "
                    f"(signals={r.signals_count}, urls={len(r.urls)}, "
                    f"links={len(r.wikilinks)}, bias={len(r.bias_flags)})"
                )
        else:
            r = _ingest_source(
                src_path, project_root=project_root,
                write_wiki=auto_wiki, write_db=True,
            )
            lines = [
                f"Ingestado {r.source.name} → {r.page_type}/{r.slug}",
                f"- signals: {r.signals_count}",
                f"- urls: {len(r.urls)} ({', '.join(u['source_type'] for u in r.urls[:5])})",
                f"- wikilinks: {len(r.wikilinks)}",
                f"- bias flags: {len(r.bias_flags)}",
            ]
            if r.wiki_page_path:
                lines.append(f"- wiki page: {r.wiki_page_path}")
        return [TextContent(type="text", text="\n".join(lines))]


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

