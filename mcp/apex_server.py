"""APEX MCP Server — Expone context.db como herramientas de Claude Code.

Herramientas disponibles:
  - apex_get_context(level)    → Contexto del proyecto (compact/timeline/full)
  - apex_set_phase(num, status)→ Actualizar fase actual
  - apex_add_decision(...)     → Registrar decisión con temporal facts
  - apex_add_error(...)        → Registrar error (bidireccional)
  - apex_add_component(...)    → Registrar componente del proyecto
  - apex_add_next_step(...)    → Añadir siguiente paso
  - apex_complete_step(id)     → Marcar paso como completado
  - apex_search(query)                 → Búsqueda FTS5 en el proyecto actual
  - apex_search_cross_project(query)   → Retrieval FTS5 en TODOS los proyectos (hub.db)
  - apex_init_project(name)            → Inicializar .apex/ en el proyecto actual
  - apex_log_session(summary)          → Registrar resumen de sesión

Configuración en .claude/settings.json:
  {
    "mcpServers": {
      "apex": {
        "command": "python3",
        "args": ["/home/vicente/RoadToDevOps/apex/mcp/apex_server.py"]
      }
    }
  }

El server detecta automáticamente el directorio del proyecto vía CWD.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

# Añadir lib/ al path para importar context_db y wiki_scaffold
_apex_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_apex_root / "lib"))
# La raíz va al FINAL del path, no al principio: `lib/advisor.py` y compañía
# hacen `from lib.db_utils import …` y necesitan `lib` como paquete, pero
# anteponer la raíz haría que el `mcp/` de este repo ensombreciera al SDK `mcp`.
sys.path.append(str(_apex_root))

import grader as _grader  # noqa: E402
import goal_loop as _goal  # noqa: E402
import handoff as _handoff  # noqa: E402
import token_filter as _tf  # noqa: E402
import design_md as _design  # noqa: E402
import research as _research  # noqa: E402
import browser_trace as _browser  # noqa: E402
import skill_forge as _forge  # noqa: E402
import library_ingest as _library  # noqa: E402
import roles as _roles  # noqa: E402
import apex_doctor as _doctor  # noqa: E402
import advisor as _advisor  # noqa: E402
import advisor_outcomes as _advisor_outcomes  # noqa: E402
import advisor_health as _advisor_health  # noqa: E402
import advisor_tuning as _advisor_tuning  # noqa: E402
import reasoning_traces as _traces  # noqa: E402
import skill_handoff as _handoff_skill  # noqa: E402
import prototype as _prototype  # noqa: E402

# El SDK se llama `mcp`, igual que el directorio de este repo. Si el cwd es la
# raíz de APEX, `mcp/` la ensombrece y el import del SDK falla. Se descarta la
# entrada de sys.path que apunta a la raíz ANTES de importar el SDK.
for _p in ("", ".", str(_apex_root)):
    while _p in sys.path:
        sys.path.remove(_p)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from context_db import ApexContextDB
from wiki_scaffold import create_wiki, append_log, update_index
from portfolio_publish import generate as _portfolio_generate, DEFAULT_OUT_DIR as _PORTFOLIO_OUT_DIR
from ingest import ingest as _ingest_source, ingest_dir as _ingest_dir
from lint import run_lint as _run_lint, write_report as _write_lint_report, _render_report as _render_lint_report
from synthesis import synthesize as _synthesize
from scaffold_devops import scaffold as _scaffold_devops, ScaffoldOptions as _ScaffoldOptions
from security_gate import (
    check_gate as _check_security_gate,
    render_report as _render_security_report,
    write_report as _write_security_report,
    scaffold_templates as _scaffold_security_templates,
)
from reverse_engineer import (
    scan_project as _reverse_scan,
    render_report_md as _render_reverse_report,
    ScanReport as _ScanReport,
    RetroactiveFinding as _RetroFinding,
)

# Los handlers viven en `mcp/handlers/` de ESTE repo, pero `mcp` es también el
# nombre del SDK. Importarlos como `mcp.handlers` obligaría a poner la raíz del
# repo por delante en sys.path, lo que ensombrecería al SDK y rompería
# `from mcp.server import Server`. Se cargan por ruta explícita para que ambos
# convivan.
import importlib.util as _ilu

_handlers_pkg_dir = _apex_root / "mcp" / "handlers"
_spec = _ilu.spec_from_file_location(
    "apex_handlers", _handlers_pkg_dir / "__init__.py",
    submodule_search_locations=[str(_handlers_pkg_dir)],
)
_handlers = _ilu.module_from_spec(_spec)
sys.modules["apex_handlers"] = _handlers
_spec.loader.exec_module(_handlers)
HANDLERS = _handlers.HANDLERS
LIBRARY_TOOLS = _handlers.LIBRARY_TOOLS

# --- Debug monitor (envía eventos si está corriendo) ---

# Hub v2 prefiere hub-v2-port; mantenemos fallback al legacy hub-port
_HUB_PORT_FILE_V2 = Path.home() / ".apex" / "hub-v2-port"
_HUB_PORT_FILE = Path.home() / ".apex" / "hub-port"
_HUB_DIR = Path.home() / "RoadToDevOps" / "apex-hub"
_HUB_LOG = Path.home() / ".apex" / "hub.log"
_FALLBACK_MONITOR_URL = "http://localhost:8099/event"


def _read_hub_port() -> str | None:
    """Lee el puerto del Hub. Prefiere v2 sobre legacy."""
    for f in (_HUB_PORT_FILE_V2, _HUB_PORT_FILE):
        try:
            if f.exists():
                p = f.read_text().strip()
                if p.isdigit():
                    return p
        except Exception:
            continue
    return None


def _hub_is_running() -> bool:
    """Comprueba si el hub responde en el puerto registrado (prefiere hub-v2-port)."""
    import socket as _socket
    port_str = _read_hub_port()
    if not port_str:
        return False
    try:
        port = int(port_str)
    except ValueError:
        return False
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, OSError):
            # Puerto en el archivo pero nadie escuchando → archivos stale
            for f in (_HUB_PORT_FILE_V2, _HUB_PORT_FILE):
                try:
                    f.unlink()
                except FileNotFoundError:
                    pass
            return False


def _open_browser(url: str) -> None:
    """Abre la URL en el navegador del usuario."""
    import shutil, subprocess
    for opener in ("xdg-open", "open", "gio", "sensible-browser"):
        if shutil.which(opener):
            try:
                if opener == "gio":
                    subprocess.Popen([opener, "open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                else:
                    subprocess.Popen([opener, url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except Exception:
                continue


def _launch_hub_if_needed() -> None:
    """Si el Hub no está corriendo: lo arranca en background y abre el navegador."""
    already_running = _hub_is_running()

    if not already_running:
        if not _HUB_DIR.exists():
            return

        import subprocess
        venv_python = _HUB_DIR / ".venv" / "bin" / "python"
        python = str(venv_python) if venv_python.exists() else "python3"

        _HUB_LOG.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(_HUB_LOG, "ab") as log:
                subprocess.Popen(
                    [python, "-m", "backend"],
                    cwd=str(_HUB_DIR),
                    stdout=log,
                    stderr=log,
                    start_new_session=True,
                )
        except Exception:
            return

        # Esperar a que el hub escriba el archivo del puerto (máx 6s)
        import time
        for _ in range(30):
            if _hub_is_running():
                break
            time.sleep(0.2)

    # Abrir navegador (esté ya corriendo o recién arrancado)
    try:
        port = _read_hub_port()
        if port and port.isdigit() and not already_running:
            # Solo abrir navegador si acabamos de lanzarlo (no cada vez que se usa /apex)
            _open_browser(f"http://localhost:{port}")
    except Exception:
        pass


def _hub_urls() -> list[str]:
    """Detecta dinámicamente el puerto del APEX Hub. Prefiere hub-v2-port."""
    urls = []
    port = _read_hub_port()
    if port:
        urls.append(f"http://localhost:{port}/api/live/event")
    urls.append(_FALLBACK_MONITOR_URL)
    return urls


async def _debug_log(tool: str, arguments: dict, result: str, duration_ms: int = 0) -> None:
    """Envía evento al APEX Hub (puerto auto-detectado) y/o debug monitor. No falla si ninguno está."""
    project = ""
    try:
        project = _find_project_root().name
    except Exception:
        pass
    payload = {
        "tool": tool,
        "arguments": arguments,
        "result": result[:500],
        "duration_ms": duration_ms,
        "project": project,
    }
    try:
        import httpx
        async with httpx.AsyncClient(timeout=1.0) as client:
            for url in _hub_urls():
                try:
                    await client.post(url, json=payload)
                except Exception:
                    pass
    except Exception:
        pass

# --- Obsidian Vault sync (escribe notas automáticamente) ---

_OBSIDIAN_VAULT = Path.home() / "Documents" / "ApexVault"


def _sync_to_obsidian(event_type: str, data: dict) -> None:
    """Escribe una nota en el vault de Obsidian cada vez que el MCP registra algo.
    No falla si el vault no existe."""
    try:
        if not _OBSIDIAN_VAULT.exists():
            return

        project_name = data.get("project", "unknown")
        project_dir = _OBSIDIAN_VAULT / "projects"
        project_dir.mkdir(parents=True, exist_ok=True)

        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")

        if event_type == "decision":
            # Append to project activity log
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Decisión [{data.get('category', '')}]: {data.get('decision', '')[:100]}\n")

        elif event_type == "error":
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Error [{data.get('source', '')}]: {data.get('description', '')[:100]}\n")

        elif event_type == "phase":
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Fase {data.get('phase', '?')} → {data.get('status', '?')}\n")

        elif event_type == "component":
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Componente: {data.get('name', '')} ({data.get('type', '')})\n")

        elif event_type == "session":
            log_file = project_dir / f"{project_name}-log.md"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(f"- **{now}** — Sesión: {data.get('summary', '')[:100]}\n")

    except Exception:
        pass  # Obsidian sync es best-effort, nunca rompe el flujo


# --- Detectar directorio del proyecto ---

def _find_project_root() -> Path:
    """Busca el directorio del proyecto subiendo desde CWD hasta encontrar .apex/ o .git/."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".apex").exists():
            return parent
        if (parent / ".git").exists():
            return parent
        if parent == parent.parent:
            break
    return cwd


_INITIALIZED_DB_PATHS: set[str] = set()


def _get_db() -> ApexContextDB:
    """Obtiene la instancia de context.db para el proyecto actual."""
    root = _find_project_root()
    db_path = root / ".apex" / "context.db"
    return ApexContextDB(str(db_path))


async def _ensure_db_schema(db: ApexContextDB) -> None:
    """Garantiza que el schema está al día. Ejecuta initialize() (idempotente)
    una vez por path en cada vida del proceso. Necesario para que BDs creadas
    antes del Sprint 8 reciban automáticamente la tabla grader_verdicts y
    cualquier futura adición al schema."""
    key = str(db.db_path)
    if key in _INITIALIZED_DB_PATHS:
        return
    if db.db_path.exists():
        # BD existente: ejecuta executescript para añadir tablas nuevas
        # (CREATE TABLE IF NOT EXISTS) sin tocar datos.
        await db.initialize()
    _INITIALIZED_DB_PATHS.add(key)


# --- Cross-project retrieval (lectura de apex-hub/data/hub.db) ---

_HUB_DB = _HUB_DIR / "data" / "hub.db"


def _search_cross_project(query: str, limit: int = 8, exclude_project: str | None = None) -> dict:
    """Consulta hub.db (agregada por apex-hub) para encontrar errores, decisiones y
    componentes de OTROS proyectos similares al query. Best-effort: si hub.db no
    existe, devuelve dict vacío sin fallar.

    Returns:
      {
        "errors": [{project_id, description, lesson, severity, recurrence_count}],
        "decisions": [{project_id, category, decision, reasoning}],
        "components": [{project_id, name, type, description}],
        "hub_available": bool,
      }
    """
    import sqlite3

    empty = {"errors": [], "decisions": [], "components": [], "hub_available": False}

    if not _HUB_DB.exists():
        return empty

    try:
        conn = sqlite3.connect(f"file:{_HUB_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.OperationalError:
        return empty

    try:
        fts_q = query.strip()
        if not fts_q:
            return {**empty, "hub_available": True}

        # FTS5 sobre hub_search: source_type ∈ {error, decision, component, wiki, session}
        # Nota: no usamos alias (`hs.`) porque FTS5 rechaza referencias a columnas
        # UNINDEXED a través de alias de tabla.
        sql = (
            "SELECT project_id, source_type, source_id, "
            "snippet(hub_search, 3, '[', ']', '...', 24) AS snip, rank "
            "FROM hub_search WHERE hub_search MATCH ?"
        )
        params: list = [fts_q]
        if exclude_project:
            sql += " AND project_id != ?"
            params.append(exclude_project)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit * 3)

        try:
            rows = [dict(r) for r in conn.execute(sql, params)]
        except sqlite3.OperationalError:
            # Sintaxis FTS5 inválida → reintento como frase
            try:
                rows = [dict(r) for r in conn.execute(sql, [f'"{fts_q}"', *params[1:]])]
            except sqlite3.OperationalError:
                return {**empty, "hub_available": True}

        errors, decisions, components = [], [], []

        for row in rows:
            src_type = row["source_type"]
            src_id = row["source_id"]
            pid = row["project_id"]
            # source_id apunta al PK de hub.db (id para decisions/errors/wiki,
            # rowid para components) — no al original_id del context.db local.
            if src_type == "error" and len(errors) < limit:
                r = conn.execute(
                    "SELECT description, lesson, severity, recurrence_count, phase "
                    "FROM errors WHERE id = ?",
                    (src_id,),
                ).fetchone()
                if r:
                    errors.append({"project_id": pid, **dict(r)})
            elif src_type == "decision" and len(decisions) < limit:
                r = conn.execute(
                    "SELECT category, decision, reasoning, phase, invalid_from "
                    "FROM decisions WHERE id = ?",
                    (src_id,),
                ).fetchone()
                if r:
                    decisions.append({"project_id": pid, **dict(r)})
            elif src_type == "component" and len(components) < limit:
                r = conn.execute(
                    "SELECT component_id, name, type, description, status "
                    "FROM components WHERE rowid = ?",
                    (src_id,),
                ).fetchone()
                if r:
                    components.append({"project_id": pid, **dict(r)})
        return {
            "errors": errors,
            "decisions": decisions,
            "components": components,
            "hub_available": True,
        }
    finally:
        conn.close()


def _recurrent_errors_cross_project(limit: int = 5, exclude_project: str | None = None) -> list[dict]:
    """Devuelve los errores cross-project con mayor recurrence_count (lecciones
    universales). Usado por el hook SessionStart."""
    import sqlite3

    if not _HUB_DB.exists():
        return []
    try:
        conn = sqlite3.connect(f"file:{_HUB_DB}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
    except sqlite3.OperationalError:
        return []
    try:
        sql = (
            "SELECT project_id, description, lesson, severity, recurrence_count, phase "
            "FROM errors"
        )
        params: list = []
        if exclude_project:
            sql += " WHERE project_id != ?"
            params.append(exclude_project)
        sql += " ORDER BY recurrence_count DESC, "
        sql += "CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END "
        sql += "LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


# --- MCP Server ---

server = Server("apex")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="apex_get_context",
            description="Obtiene el contexto del proyecto APEX. Niveles: 'compact' (~200 tokens), 'timeline' (~800 tokens), 'full' (~2000 tokens).",
            inputSchema={
                "type": "object",
                "properties": {
                    "level": {
                        "type": "string",
                        "enum": ["compact", "timeline", "full"],
                        "description": "Nivel de detalle del contexto",
                        "default": "timeline",
                    }
                },
            },
        ),
        Tool(
            name="apex_init_project",
            description="Inicializa .apex/ en el proyecto actual. Crea context.db, wiki scaffold, y registra metadatos.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre del proyecto"},
                    "description": {"type": "string", "description": "Descripción breve"},
                    "solution_type": {"type": "string", "description": "Tipo de solución (cli/bot/mcp/app/agent/streamlit)"},
                    "domain": {"type": "string", "description": "Dominio del proyecto (ej: supermercados, educación)"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="apex_set_phase",
            description=(
                "Actualiza el estado de una fase (0-14). Estados: pending, "
                "in_progress, completed, skipped. Sprint 8: si el último verdict "
                "del grader para la fase tiene should_block=true, esta tool falla "
                "salvo que se pase force=true (registra apex_add_error con motivo)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "phase_number": {"type": "integer", "minimum": 0, "maximum": 14},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "skipped"]},
                    "notes": {"type": "string", "description": "Observaciones sobre la fase", "default": ""},
                    "force": {
                        "type": "boolean",
                        "description": "Bypass al bloqueo del grader (registra error con razón)",
                        "default": False,
                    },
                    "force_reason": {
                        "type": "string",
                        "description": "Razón del override (obligatoria si force=true)",
                        "default": "",
                    },
                },
                "required": ["phase_number", "status"],
            },
        ),
        Tool(
            name="apex_add_decision",
            description="Registra una decisión tomada en el proyecto. Las decisiones tienen temporal facts (se pueden invalidar).",
            inputSchema={
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "enum": ["architecture", "stack", "design", "data", "security", "deploy", "ux", "testing"],
                        "description": "Categoría de la decisión",
                    },
                    "decision": {"type": "string", "description": "Qué se decidió (markdown)"},
                    "reasoning": {"type": "string", "description": "Por qué se tomó esta decisión (markdown)"},
                    "phase": {"type": "integer", "description": "Fase en la que se tomó"},
                    "alternatives": {"type": "string", "description": "Alternativas descartadas y por qué"},
                },
                "required": ["category", "decision", "reasoning"],
            },
        ),
        Tool(
            name="apex_invalidate_decision",
            description="Marca una decisión como ya no vigente (temporal fact). La decisión no se borra, pasa al historial.",
            inputSchema={
                "type": "object",
                "properties": {
                    "decision_id": {"type": "integer", "description": "ID de la decisión a invalidar"},
                    "reason": {"type": "string", "description": "Por qué se invalida"},
                },
                "required": ["decision_id", "reason"],
            },
        ),
        Tool(
            name="apex_add_error",
            description="Registra un error cometido (por Claude o por el usuario). Si el error ya existe, incrementa recurrence_count.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {"type": "string", "enum": ["claude", "user"], "description": "Quién cometió el error"},
                    "description": {"type": "string", "description": "Qué salió mal"},
                    "lesson": {"type": "string", "description": "Lección aprendida para el futuro"},
                    "phase": {"type": "integer", "description": "Fase en la que ocurrió"},
                    "severity": {"type": "string", "enum": ["low", "medium", "high", "critical"], "default": "medium"},
                },
                "required": ["source", "description", "lesson"],
            },
        ),
        Tool(
            name="apex_add_component",
            description="Registra un componente del proyecto (domain entity, agent, port, adapter, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string", "description": "ID único (ej: scraper-mercadona)"},
                    "name": {"type": "string", "description": "Nombre legible"},
                    "type": {"type": "string", "enum": ["domain", "agent", "port", "adapter", "api", "test", "config", "skill"]},
                    "status": {"type": "string", "enum": ["planned", "in_progress", "implemented", "tested", "verified"], "default": "planned"},
                    "phase": {"type": "integer"},
                    "description": {"type": "string"},
                    "files": {"type": "array", "items": {"type": "string"}, "description": "Archivos que implementan este componente"},
                },
                "required": ["id", "name", "type"],
            },
        ),
        Tool(
            name="apex_update_component",
            description="Actualiza el estado de un componente existente.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "status": {"type": "string", "enum": ["planned", "in_progress", "implemented", "tested", "verified"]},
                },
                "required": ["id", "status"],
            },
        ),
        Tool(
            name="apex_add_next_step",
            description="Añade un siguiente paso al proyecto con prioridad.",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "Qué hay que hacer"},
                    "priority": {"type": "integer", "minimum": 1, "maximum": 10, "description": "1=urgente, 10=nice-to-have", "default": 5},
                    "phase": {"type": "integer"},
                },
                "required": ["description"],
            },
        ),
        Tool(
            name="apex_complete_step",
            description="Marca un siguiente paso como completado.",
            inputSchema={
                "type": "object",
                "properties": {
                    "step_id": {"type": "integer"},
                },
                "required": ["step_id"],
            },
        ),
        Tool(
            name="apex_search",
            description=(
                "Búsqueda en todo el contexto del proyecto. mode='hybrid' (default) "
                "combina FTS5 BM25 70% + keyword overlap 30% — mejor recall con "
                "inflexiones, typos y términos compuestos. mode='fts' usa solo FTS5."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Texto a buscar"},
                    "limit": {"type": "integer", "default": 10},
                    "mode": {"type": "string", "enum": ["hybrid", "fts"], "default": "hybrid"},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="apex_set_portfolio_meta",
            description=(
                "Guarda campos portfolio_* en project_meta para alimentar el "
                "publisher de vr-web. Usar durante la fase 14 o cuando el "
                "usuario pida publicar el caso. Llaves esperadas sin prefijo "
                "(ej. 'title', 'headline', 'problem', 'results', 'learnings', "
                "'tags', 'repo_url', 'related_pack'...). El prefijo 'portfolio_' "
                "se añade automáticamente. Listas/dicts se serializan como JSON."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "object",
                        "description": "Diccionario {nombre_campo: valor}. Strings se guardan directo; listas/dicts como JSON.",
                    },
                },
                "required": ["fields"],
            },
        ),
        Tool(
            name="apex_portfolio_draft",
            description=(
                "Genera (o actualiza) un archivo MDX de caso para vr-web/content/cases/ "
                "a partir de project_meta. Por defecto escribe <slug>.mdx.draft para "
                "que el usuario revise. Cuando el usuario apruebe, llamar con apply=True "
                "para escribir el <slug>.mdx final (conservando campos manuales si ya existe)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Identificador del caso (ej. 'apex', 'dni')"},
                    "apply": {"type": "boolean", "default": False, "description": "Si true, escribe el .mdx final. Si false, .mdx.draft para revisión."},
                    "out_dir": {"type": "string", "description": "Directorio destino (default: ~/RoadToDevOps/vr-web/content/cases)"},
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="apex_security_gate",
            description=(
                "Verifica las 8 capas AgentArmor (L1-L8) leyendo "
                ".apex/security/L*-*.md. Devuelve un reporte markdown y escribe "
                ".apex/security/audit-report-YYYY-MM-DD.md. Si scaffold=true, "
                "copia las 8 plantillas al proyecto primero. Fase 11 (Deploy) "
                "NO debe permitirse si cualquier capa no está passed."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "scaffold": {"type": "boolean", "default": False,
                                "description": "Si true, copia templates L1-L8 a .apex/security/ antes de verificar"},
                },
            },
        ),
        Tool(
            name="apex_scaffold_devops",
            description=(
                "Copia templates CI/CD + Docker + Monitor al proyecto actual (o al "
                "target indicado). Renombra placeholders (PROJECT_NAME, STACK, "
                "PORT, HEALTH_PATH, DEPLOY_TARGET). No pisa archivos existentes "
                "salvo overwrite=true. Incluye GitHub Actions (ci, deploy-staging, "
                "deploy-prod, release-please), Dockerfile multi-stage, "
                "docker-compose.prod.yml, y stack de monitoring (Prometheus, "
                "Grafana dashboard, alerts, Loki, health.py)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "Directorio destino (default: proyecto actual)"},
                    "name": {"type": "string", "description": "Nombre del proyecto"},
                    "stack": {"type": "string", "enum": ["python", "node"], "default": "python"},
                    "deploy_target": {"type": "string", "enum": ["vercel", "fly", "vps"], "default": "vercel"},
                    "port": {"type": "integer", "default": 8000},
                    "health_path": {"type": "string", "default": "/health"},
                    "with_monitoring": {"type": "boolean", "default": True},
                    "overwrite": {"type": "boolean", "default": False},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="apex_ingest_source",
            description=(
                "Procesa UN archivo de .apex/raw/ (md/txt/json) con el pipeline "
                "QUERY→INGEST: resuelve URLs, extrae signals (headings/listas/citas/code), "
                "clasifica (entity/concept/comparison/query/raw), genera página wiki con "
                "frontmatter YAML + wikilinks cross-wiki + bias flags. Si path es un "
                "directorio, procesa todos los archivos recursivamente."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Archivo o dir dentro de .apex/raw/ (absoluto o relativo)"},
                    "auto_wiki": {"type": "boolean", "default": True, "description": "Escribir páginas wiki (default true)"},
                    "recursive": {"type": "boolean", "default": True, "description": "Si path es dir, recorrer subdirectorios"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="apex_lint_second_brain",
            description=(
                "Ejecuta la batería de lint: contradicciones entre decisiones activas, "
                "errores recurrentes sin decisión, componentes huérfanos, wiki stale, "
                "pages sin wikilinks, next_steps bloqueados por pasos completados. "
                "Output: .apex/wiki/lint-report-YYYY-MM-DD.md. Con apply=True aplica "
                "auto-fixes triviales (NS-001 unblock)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "apply": {"type": "boolean", "default": False},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                },
            },
        ),
        Tool(
            name="apex_synthesize",
            description=(
                "Dispara dream_deep cuando la densidad reciente supera umbrales (nuevas "
                "decisiones/errores/wiki 7d, o >14d sin síntesis). trigger='force' la "
                "fuerza. Promueve señales scored >=min_score a wiki/synthesis/YYYY-MM-DD.md."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "trigger": {"type": "string", "enum": ["auto", "force"], "default": "auto"},
                    "min_score": {"type": "number", "default": 0.6, "minimum": 0, "maximum": 1},
                },
            },
        ),
        Tool(
            name="apex_search_cross_project",
            description=(
                "OBLIGATORIO antes de decisiones de diseño/arquitectura/stack. "
                "Consulta hub.db (agregada por apex-hub) para encontrar errores, "
                "decisiones y componentes de OTROS proyectos similares. Úsalo SIEMPRE "
                "antes de: elegir ancho de layout, proponer stack, elegir librería de "
                "iconos, diseñar componente, o cualquier decisión que ya se haya "
                "enfrentado en otro proyecto. Evita repetir errores cross-project."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Términos de búsqueda (ej: 'margen ancho layout', 'emoji icono', 'stack scraping')",
                    },
                    "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 20},
                    "exclude_current": {
                        "type": "boolean",
                        "default": True,
                        "description": "Excluir el proyecto actual de los resultados",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="apex_log_session",
            description="Registra un resumen de la sesión actual para persistir entre conversaciones.",
            inputSchema={
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Resumen de lo que se hizo en esta sesión"},
                    "key_outcomes": {"type": "string", "description": "Resultados clave", "default": ""},
                    "phase": {"type": "integer"},
                },
                "required": ["summary"],
            },
        ),
        Tool(
            name="apex_wiki_add",
            description="Añade o actualiza una página en la knowledge base (LLM-Wiki) del proyecto.",
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Ruta de la página (ej: entities/product, concepts/normalization)"},
                    "title": {"type": "string"},
                    "content": {"type": "string", "description": "Contenido markdown"},
                    "page_type": {"type": "string", "enum": ["entity", "concept", "comparison", "query", "raw"], "default": "entity"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["slug", "title", "content"],
            },
        ),
        Tool(
            name="apex_reverse_scan",
            description=(
                "Ingeniería inversa de un proyecto existente. Escanea el "
                "CÓDIGO (no los docs) con git+glob+grep y devuelve un "
                "ScanReport JSON + markdown. Cubre las 14 fases + gate 10.5, "
                "detecta anti-patterns cross-project (emojis, console.log, "
                "CORS wildcards, secretos hardcoded, etc.), y reporta docs vs "
                "code mismatches. NO modifica el proyecto. Read-only."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path absoluto al proyecto a escanear"},
                    "format": {"type": "string", "enum": ["markdown", "json", "both"], "default": "markdown"},
                    "write_report": {"type": "boolean", "default": False,
                                    "description": "Si true, escribe .apex/reverse-report-YYYY-MM-DD.md"},
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="apex_reverse_plan",
            description=(
                "Toma un ScanReport (JSON del scan) + answers del usuario a "
                "los findings y produce un ActionPlan priorizado mapeado a "
                "fases a retomar. Los answers son dicts {finding_id: "
                "choice(a|b|c|d)}. No modifica nada. Solo calcula el plan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "scan_report": {"type": "object", "description": "ScanReport devuelto por apex_reverse_scan (format=json)"},
                    "answers": {"type": "object", "description": "Map finding_id → a|b|c|d"},
                },
                "required": ["scan_report"],
            },
        ),
        Tool(
            name="apex_onboard_apply",
            description=(
                "Crea .apex/ en el proyecto escaneado con decisiones "
                "retroactivas (category='retroactive'), componentes "
                "detectados, errores de fases saltadas, y fases marcadas "
                "completed/partial/pending según el scan. Solo ejecutar tras "
                "que el usuario apruebe el plan devuelto por apex_reverse_plan."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path del proyecto"},
                    "plan": {"type": "object", "description": "ActionPlan aprobado por el usuario"},
                    "scan_report": {"type": "object", "description": "Scan original"},
                },
                "required": ["path", "scan_report"],
            },
        ),
        Tool(
            name="apex_grader_evaluate",
            description=(
                "Sprint 8.1 — Grader outcome-based. Evalúa el cierre de una fase "
                "ejecutando checks deterministas (git, tests, OS, emojis, schema, "
                "Playwright) y opcionalmente juicio LLM. Persiste el verdict en "
                "context.db. Si should_block=true, apex_set_phase debe rechazar la "
                "transición a esa fase."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "phase": {"type": "integer", "description": "Fase a evaluar (0-14)"},
                    "mode": {
                        "type": "string",
                        "enum": ["deterministic", "full"],
                        "description": "deterministic = solo checks programáticos; full = + juicio LLM si hay ANTHROPIC_API_KEY",
                        "default": "deterministic",
                    },
                    "component_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tipos de componente detectados (web, cli, mcp, bot, ...). Phase-aware checks los usan.",
                        "default": [],
                    },
                    "persist": {
                        "type": "boolean",
                        "description": "Guardar verdict en grader_verdicts table",
                        "default": True,
                    },
                },
                "required": ["phase"],
            },
        ),
        Tool(
            name="apex_design_md_init",
            description=(
                "Sprint 10.1 — Crea DESIGN.md en raíz del proyecto siguiendo el "
                "estándar Google Labs (5 secciones: Brand, Color, Type, Components, "
                "Accessibility/Dark). No sobreescribe salvo overwrite=true."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "brand_name": {"type": "string", "default": "Acme"},
                    "overwrite": {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="apex_design_md_validate",
            description=(
                "Sprint 10.1 — Valida DESIGN.md actual: estructura (5 secciones "
                "obligatorias), contraste WCAG AA en pares text/bg/text-muted/accent, "
                "tamaño máximo. Devuelve lista de violations."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path del DESIGN.md (default: ./DESIGN.md)",
                    },
                },
            },
        ),
        Tool(
            name="apex_research_competitor",
            description=(
                "Sprint 10.2 — Fetch + extract de competidor. Estático (httpx) o "
                "SPA (chromium --dump-dom con virtual-time-budget). Devuelve "
                "signals: title, H1, H2, nav, CTAs, paleta, fuentes. Útil en "
                "fase 0 (mercado) y fase 2 (diseño visual)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "prefer_spa": {
                        "type": "boolean",
                        "default": False,
                        "description": "Forzar chromium dump-dom (SPAs modernas)",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="apex_browser_trace",
            description=(
                "Sprint 11.1 — Captura una sesión real de navegación con Chrome "
                "via DevTools Protocol nativo (websockets). Devuelve title, "
                "final URL, lifecycle, network log (status/duration por request), "
                "consola (errores JS), tamaño de DOM y dominios externos. "
                "Útil para fase 02 (research profundo: qué APIs llama un "
                "competidor, qué tracking carga), fase 11 (smoke-test post-deploy) "
                "y fase 13 (replicar bugs). Si CDP falla y use_fallback=True, "
                "intenta con Playwright."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "nav_timeout_s": {
                        "type": "number",
                        "default": 25,
                        "description": "Timeout total de navegación + load + idle",
                    },
                    "settle_ms": {
                        "type": "integer",
                        "default": 1500,
                        "description": "Espera extra tras load para CSS-in-JS / network tail",
                    },
                    "capture_dom": {
                        "type": "boolean",
                        "default": True,
                        "description": "Si True, incluye outerHTML del documento final",
                    },
                    "save_jsonl": {
                        "type": "boolean",
                        "default": False,
                        "description": "Si True, guarda en .apex/browser-traces/<slug>.json",
                    },
                    "use_fallback": {
                        "type": "boolean",
                        "default": True,
                        "description": "Si CDP falla, intentar con Playwright",
                    },
                    "include_dom_in_output": {
                        "type": "boolean",
                        "default": False,
                        "description": "Si True, devuelve también el outerHTML completo",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name="apex_archive_output",
            description=(
                "Sprint 9.2 — Archiva un output largo de herramienta en "
                "tool_output_archive. Devuelve el id de archivo + un resumen "
                "apto para contexto. Úsalo cuando post-tool-archive.py avise "
                "que un output supera el umbral."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "tool": {"type": "string"},
                    "arguments": {"type": "object", "default": {}},
                    "output": {"type": "string"},
                },
                "required": ["tool", "output"],
            },
        ),
        Tool(
            name="apex_get_archived",
            description=(
                "Sprint 9.2 — Recupera un output archivado por id. Sin id, "
                "lista los últimos 20 archivos."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "description": "ID del archivo"},
                    "tool": {"type": "string", "description": "Filtrar por tool al listar"},
                },
            },
        ),
        Tool(
            name="apex_handoff_write",
            description=(
                "Sprint 9.1 — Serializa el estado activo de la sesión a "
                ".apex/handoff/{session_id}.md (fase actual, verdicts del grader "
                "bloqueando, goals activos, próximos pasos). Útil cuando el "
                "context-watch.py avisa de >40% de contexto."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID de la sesión (truncado a 12 chars suele ser suficiente)",
                    },
                    "transcript_tokens": {
                        "type": "integer",
                        "description": "Tokens estimados en la sesión actual (opcional, solo informativo)",
                        "default": 0,
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="apex_resume_session",
            description=(
                "Sprint 9.1 — Rehidrata el contexto de una sesión previa leyendo "
                ".apex/handoff/{session_id}.md. Si no se pasa session_id, lista "
                "los handoffs disponibles."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID de la sesión a rehidratar. Si se omite, devuelve la lista.",
                    },
                },
            },
        ),
        Tool(
            name="apex_goal_loop",
            description=(
                "Sprint 8.2 — /goal turn-budget loop. Acciones: start, record_turn, "
                "judge_prompt, apply_decision, pause, list. El estado se persiste "
                "en .apex/goal/{id}.json. El juez decide done|continue|degenerate."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["start", "record_turn", "judge_prompt",
                                 "apply_decision", "pause", "list", "load"],
                    },
                    "goal": {"type": "string", "description": "Texto del goal (action=start)"},
                    "turn_budget": {"type": "integer", "default": 20},
                    "goal_id": {"type": "string", "description": "ID del goal (action != start/list)"},
                    "turn_summary": {"type": "string", "description": "Resumen del turno (action=record_turn)"},
                    "tools_used": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Herramientas usadas en el turno",
                        "default": [],
                    },
                    "decision": {
                        "type": "object",
                        "description": "Decisión del juez (action=apply_decision): {decision, reason}",
                    },
                    "transcript_path": {
                        "type": "string",
                        "description": (
                            "(action=record_turn) Ruta al JSONL de la sesión. "
                            "Si se pasa y supera APEX_HANDOFF_THRESHOLD_TOKENS, "
                            "el goal termina con status=context_threshold y "
                            "se escribe handoff automáticamente."
                        ),
                    },
                    "session_id": {
                        "type": "string",
                        "description": (
                            "(action=record_turn) ID de la sesión de Claude Code. "
                            "Necesario si pasas transcript_path para que el "
                            "auto-handoff sepa dónde escribirlo."
                        ),
                    },
                    "threshold_tokens": {
                        "type": "integer",
                        "description": (
                            "(action=record_turn) Override del umbral de tokens. "
                            "Si no se pasa, lee APEX_HANDOFF_THRESHOLD_TOKENS o "
                            "200000."
                        ),
                    },
                },
                "required": ["action"],
            },
        ),
        Tool(
            name="apex_skill_forge_scan",
            description=(
                "Sprint 11.2 — Skill Forge: corre los 3 detectores (grader_block, "
                "tool_call, cross_project) sobre context.db + hub.db y escribe "
                "propuestas nuevas en .apex/skill-proposals/<slug>.md. Devuelve "
                "lista de slugs nuevos, ya propuestos y rechazados. Idempotente: "
                "no duplica propuestas ni propone slugs rechazados."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "include_cross_project": {
                        "type": "boolean", "default": True,
                        "description": "Si False, omite el detector D3 (cross-project).",
                    },
                },
            },
        ),
        Tool(
            name="apex_skill_forge_approve",
            description=(
                "Sprint 11.2 — Aprueba una propuesta de Skill Forge: extrae el "
                "draft de SKILL.md y lo mueve a ~/.claude/skills/<slug>/SKILL.md. "
                "Borra la propuesta original."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string", "description": "Slug de la propuesta"},
                    "skills_root": {
                        "type": "string", "default": "~/.claude/skills",
                        "description": "Directorio raíz donde instalar la skill",
                    },
                },
                "required": ["slug"],
            },
        ),
        Tool(
            name="apex_skill_forge_reject",
            description=(
                "Sprint 11.2 — Rechaza una propuesta de Skill Forge: registra el "
                "slug en skill_forge_rejections para que no vuelva a proponerse "
                "y borra la propuesta original."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "reason": {"type": "string", "description": "Motivo del rechazo"},
                },
                "required": ["slug", "reason"],
            },
        ),
        Tool(
            name="apex_install_roles",
            description=(
                "Sprint 12 — Virtual office: instala los 5 agentes especializados "
                "(apex-architect, apex-implementer, apex-reviewer, apex-qa, "
                "apex-devops) en ~/.claude/agents/. Idempotente: skip si el "
                "archivo ya existe (force=true para reescribir). El orquestador "
                "los invoca después con el `Task` tool y subagent_type='apex-...'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "force": {
                        "type": "boolean",
                        "default": False,
                        "description": "Reescribe los agentes existentes.",
                    },
                    "agents_root": {
                        "type": "string",
                        "default": "~/.claude/agents",
                        "description": "Directorio destino (sólo para tests).",
                    },
                },
            },
        ),
        Tool(
            name="apex_recommend_role",
            description=(
                "Sprint 12 — Devuelve el rol especializado recomendado para una "
                "fase del flujo /apex (None para fases 0-1, 10.5, 12). Útil para "
                "que el orquestador decida si invocar `Task` con un subagent."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "phase": {"type": "integer", "description": "Fase 0-14"},
                },
                "required": ["phase"],
            },
        ),
        Tool(
            name="apex_invoke_role",
            description=(
                "Sprint 12 — Construye el prompt + subagent_type para que el "
                "orquestador dispare el `Task` tool. Esta tool NO ejecuta el "
                "subagent (sólo Claude Code main puede llamar `Task`). Devuelve "
                "una invocación lista para copiar/pegar y registra la llamada en "
                "role_invocations para telemetría."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "description": "Rol: apex-architect|apex-implementer|apex-reviewer|apex-qa|apex-devops",
                    },
                    "phase": {
                        "type": "integer",
                        "description": "Fase asociada (opcional)",
                    },
                    "context_summary": {
                        "type": "string",
                        "default": "",
                        "description": "Resumen del estado actual que el orquestador conoce.",
                    },
                    "extra_instructions": {
                        "type": "string",
                        "default": "",
                        "description": "Instrucciones específicas adicionales para el subagent.",
                    },
                    "session_id": {
                        "type": "string",
                        "default": "",
                        "description": "Session id para correlacionar en role_invocations.",
                    },
                },
                "required": ["role"],
            },
        ),
        Tool(
            name="apex_doctor_run",
            description=(
                "Sprint 13 — Apex-doctor: corre los 4 analizadores "
                "(override_clusters, grader_block_patterns, stale_handoffs, "
                "cross_project_patterns) sobre context.db + .apex/handoff/ + "
                "hub.db y escribe propuestas nuevas en .apex/doctor/<run_id>.md. "
                "Idempotente vía signature UNIQUE. Throttle de 1h entre runs "
                "(saltar con force=true). Trigger normal: hook "
                "end-of-day-doctor.py al detectar frase de cierre o "
                "sesión >3.5h. A4 sincroniza grader_verdicts locales a "
                "hub.grader_verdicts y postea cross_project_patterns como "
                "tickets en hub.doctor_tickets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "force": {
                        "type": "boolean",
                        "default": False,
                        "description": "Salta el throttle de 1h.",
                    },
                    "trigger": {
                        "type": "string",
                        "default": "manual",
                        "description": "Etiqueta del trigger (manual|wrapup_phrase|session_age|cron).",
                    },
                },
            },
        ),
        Tool(
            name="apex_ingest_library_skills",
            description=(
                "Sprint 11.3 — Descubre e ingiere skills externas desde dos "
                "fuentes: (a) GitHub Search (repos populares con 'claude-skills' "
                "en nombre o topic; awesome-lists curadas) y (b) library-skills "
                "CLI (uvx library-skills --dry-run --claude) si el proyecto "
                "tiene pyproject.toml/package.json. Cada SKILL.md descargada "
                "pasa un filtro determinista (frontmatter, longitud, regex de "
                "secretos) antes de proponerse en .apex/skill-proposals/ con "
                "prefijo 'import-'. La aprobación reusa apex_skill_forge_approve."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "source": {
                        "type": "string",
                        "enum": ["github", "pkg", "both"],
                        "default": "both",
                        "description": "Fuente a consultar.",
                    },
                    "query": {
                        "type": "string",
                        "description": (
                            "Query GitHub custom (opcional). Por defecto usa "
                            "'awesome-claude-skills in:name', "
                            "'claude-skills in:name', 'topic:claude-skills'."
                        ),
                    },
                    "min_stars": {
                        "type": "integer", "default": 50,
                        "description": "Filtro mínimo de estrellas en GitHub.",
                    },
                    "limit_repos": {
                        "type": "integer", "default": 8,
                        "description": "Repos top a inspeccionar.",
                    },
                    "max_skills_per_repo": {
                        "type": "integer", "default": 30,
                        "description": "Skills máximas a descargar por repo.",
                    },
                },
            },
        ),
        Tool(
            name="apex_advisor_review",
            description=(
                "Sprint 15 — Dispara una revisión del Advisor. Construye el "
                "shared context (fase, decisiones, verdicts, trazas, tool calls) "
                "y crea un advisor_review en estado 'pending'. El subagent "
                "apex-advisor lee el bundle y emite 0-3 advice cards via "
                "apex_record_advice. Aplica throttle (cada 8 calls) salvo "
                "force=true. Retorna review_id + bundle resumido."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "ID de sesión activa para asociar el review.",
                    },
                    "force": {
                        "type": "boolean", "default": False,
                        "description": "Bypass del throttle/circuit breaker.",
                    },
                    "trigger": {
                        "type": "string", "default": "manual",
                        "description": (
                            "Etiqueta del trigger: manual | tool_count | "
                            "phase_change | grader_blocking | circuit_breaker_reset."
                        ),
                    },
                },
                "required": ["session_id"],
            },
        ),
        Tool(
            name="apex_record_advice",
            description=(
                "Sprint 15 — Registra una advice card del subagent advisor. "
                "Idempotente vía UNIQUE(review_id, kind, title). Sólo 5 kinds "
                "permitidos: forgotten_tool, cross_project_error, phase_drift, "
                "recommend_skill_handoff, grader_overdue. Cada card debe llevar "
                "evidence_refs concretos (decision_id, error_id, trace_id, "
                "cross_project_path)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "review_id": {"type": "integer"},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "forgotten_tool", "cross_project_error", "phase_drift",
                            "recommend_skill_handoff", "grader_overdue",
                        ],
                    },
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warn", "critical"],
                    },
                    "title": {"type": "string"},
                    "body": {"type": "string"},
                    "evidence_refs": {
                        "type": "array", "default": [],
                        "items": {"type": "string"},
                    },
                },
                "required": ["review_id", "kind", "severity", "title", "body"],
            },
        ),
        Tool(
            name="apex_dismiss_advice",
            description=(
                "Sprint 15 — Marca una advice card como descartada con razón "
                "obligatoria (>=3 chars). Queda en BD para auditar el olvido "
                "voluntario; el doctor (S16+) detectará dismiss recurrente "
                "como señal de reglas mal calibradas."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "advice_id": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["advice_id", "reason"],
            },
        ),
        Tool(
            name="apex_rate_advice",
            description=(
                "Sprint 16.6 — Escape hatch manual: rating explícito de una "
                "advice card cuando el rating implícito (vía facets) no llega. "
                "rating ∈ {'useful', 'not_useful'}, reason ≥10 chars. "
                "Coexiste con outcome temporal (UNIQUE compuesto en "
                "advice_outcomes); idempotente (segundo rating sobre el "
                "mismo advice sobreescribe vía INSERT OR REPLACE)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "advice_id": {"type": "integer"},
                    "rating": {
                        "type": "string",
                        "enum": ["useful", "not_useful"],
                    },
                    "reason": {"type": "string", "minLength": 10},
                },
                "required": ["advice_id", "rating", "reason"],
            },
        ),
        Tool(
            name="apex_log_trace",
            description=(
                "Sprint 15 — Registra una traza de razonamiento en un gate denso "
                "(phase_close, grader_blocking, doctor_proposal, override). 4 "
                "categorías iniciales: cascading_failure_recovery, "
                "socratic_self_correction, multi_agent_coordination, "
                "long_horizon_consequences. Insumo del Advisor + corpus para "
                "SFT futuro. Deliberation: 200-2000 chars; confidence: 0.0-1.0."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "phase": {"type": "integer"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "cascading_failure_recovery",
                            "socratic_self_correction",
                            "multi_agent_coordination",
                            "long_horizon_consequences",
                        ],
                    },
                    "gate_kind": {
                        "type": "string",
                        "enum": [
                            "phase_close", "grader_blocking",
                            "doctor_proposal", "override",
                        ],
                    },
                    "deliberation": {"type": "string"},
                    "calibration_confidence": {"type": "number"},
                    "calibration_text": {"type": "string", "default": ""},
                    "alternatives_considered": {
                        "type": "array", "default": [],
                        "items": {"type": "object"},
                    },
                },
                "required": [
                    "session_id", "category", "gate_kind",
                    "deliberation", "calibration_confidence",
                ],
            },
        ),
        Tool(
            name="apex_handoff_skill",
            description=(
                "Sprint 15 — Cambio de modo dentro de la sesión (flujo Pocock: "
                "grill-with-docs → prototype → grill-with-docs). Persiste el "
                "snapshot del estado actual (archivos abiertos, decisiones "
                "tentativas, preguntas pendientes) para que el modo destino "
                "pueda retomar y, al volver, registrar el resultado."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string"},
                    "from_skill": {"type": "string"},
                    "to_skill": {"type": "string"},
                    "reason": {"type": "string"},
                    "snapshot": {"type": "object", "default": {}},
                },
                "required": ["session_id", "from_skill", "to_skill", "reason"],
            },
        ),
        Tool(
            name="apex_resume_skill_handoff",
            description=(
                "Sprint 15 — Marca el handoff como retornado y guarda el "
                "result_summary del modo destino. Devuelve el snapshot original "
                "para que el skill origen retome con contexto fresco."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "handoff_id": {"type": "integer"},
                    "result_summary": {"type": "string", "default": ""},
                },
                "required": ["handoff_id"],
            },
        ),
        Tool(
            name="apex_prototype_init",
            description=(
                "Sprint 15 (skill /prototype) — Genera un prototipo "
                "ejecutable de máquina de estados (Textual TUI Python) "
                "para validar lógica de negocio compleja antes de "
                "escribirla en el código real. Crea "
                "`.apex/prototypes/<feature>.py` + "
                "`wiki/concepts/<feature>-state-machine.md` (con "
                "diagrama Mermaid) y registra la máquina en la tabla "
                "`state_machines` para que el grader pueda verificar "
                "después que el código real honra las transiciones. "
                "Usa `force=True` para sobrescribir un feature_name "
                "existente."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "feature_name": {
                        "type": "string",
                        "description": (
                            "Slug snake-case (a-z0-9_-), 1-50 chars."),
                    },
                    "states": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Lista de estados (>=2, únicos)."),
                    },
                    "transitions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "from": {"type": "string"},
                                "event": {"type": "string"},
                                "to": {"type": "string"},
                                "guard": {"type": "string"},
                            },
                            "required": ["from", "event", "to"],
                        },
                        "description": (
                            "Transiciones [{from, event, to, guard?}]."),
                    },
                    "initial_state": {
                        "type": "string",
                        "description": (
                            "Estado de arranque, debe estar en `states`."),
                    },
                    "force": {
                        "type": "boolean",
                        "default": False,
                        "description": (
                            "Si feature_name ya existe, sobrescribe."),
                    },
                },
                "required": [
                    "feature_name", "states", "transitions",
                    "initial_state",
                ],
            },
        ),
        Tool(
            name="apex_advisor_compute_outcomes",
            description=(
                "Sprint 16.2 — Motor implícito de outcomes del Advisor. "
                "Cruza `advisor_advice` reciente con los facets de "
                "`~/.claude/usage-data/facets/` (Sprint 13.9): para cada "
                "advice sin outcome temporal, asocia con la sesión que "
                "contenía su `created_at` (slack 5 min) e infiere "
                "`useful` / `not_useful` / `unclear` siguiendo la "
                "heurística §3 del blueprint S16. Inserta una fila en "
                "`advice_outcomes` con `assoc_method='temporal'`. "
                "Idempotente: re-ejecutar omite los advices ya "
                "procesados salvo `force=True`. Si Claude Code nunca "
                "corrió `/insights`, los advices terminan en "
                "`no_facet_yet` sin error."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "lookback_days": {
                        "type": "integer", "default": 14,
                        "description": (
                            "Ventana hacia atrás desde ahora; advices "
                            "más viejos se ignoran."
                        ),
                    },
                    "force": {
                        "type": "boolean", "default": False,
                        "description": (
                            "Recomputa outcomes ya existentes con "
                            "`assoc_method='temporal'` (UPDATE)."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="apex_advisor_health",
            description=(
                "Sprint 16.3 — Dashboard JSON-friendly del Advisor: "
                "totales por categoría, outcomes (temporal/manual × "
                "useful/not_useful/unclear), fp_rate por categoría "
                "(None si <5 not_useful), constants actuales (default "
                "vs tuned con timestamp del último tune), tuning_history "
                "últimos 5, circuit_breaker_trips últimas 24h, "
                "facets_freshness_days. Sólo enums y números — sin "
                "texto libre, publicable sin riesgo."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "window_days": {
                        "type": "integer", "default": 30,
                        "description": (
                            "Ventana hacia atrás para outcomes. "
                            "total_advice_emitted ignora la ventana."
                        ),
                    },
                },
            },
        ),
        Tool(
            name="apex_advisor_apply_tuning",
            description=(
                "Sprint 16.4 — Auto-tuner determinista de constantes "
                "del Advisor. Para cada categoría con ≥20 outcomes y "
                "not_useful_rate >40%, propone tunear la constante "
                "asociada (forgotten_tool→default_interval, "
                "phase_drift→phase_drift_window_min, "
                "recommend_skill_handoff→complexity_score_threshold, "
                "grader_overdue→grader_overdue_phases). Cooldown 7 días "
                "por constante. dry_run=True (default) sólo devuelve "
                "propuestas; dry_run=False persiste y registra fila en "
                "advisor_tuning_history. force=True salta cooldown y "
                "registra source='manual_override'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "default": True},
                    "force": {"type": "boolean", "default": False},
                },
            },
        ),
        Tool(
            name="apex_book_search",
            description=(
                "Consulta la biblioteca de libros técnicos del usuario (sus notas "
                "de lectura indexadas). Devuelve pasajes LITERALES con su cita "
                "(libro, capítulo, sección). Funciona desde cualquier directorio, "
                "con o sin proyecto APEX. "
                "Úsala SIEMPRE que: (a) el usuario pregunte qué dice, recomienda o "
                "explica alguno de sus libros ('qué dice el libro sobre evaluación "
                "de agentes', 'qué pone el Cap. 6 sobre memoria'); (b) vayas a "
                "decidir arquitectura, orquestación, uso de tools, memoria/RAG o "
                "estrategia de evaluación de un sistema de agentes. "
                "IMPORTANTE: envía 'query' en INGLÉS aunque el usuario pregunte en "
                "español — el corpus está en inglés y traducir la consulta duplica "
                "la precisión (medido: 6/6 aciertos frente a 2/6). Traduce la "
                "intención, no palabra por palabra. "
                "Responde SOLO con los pasajes devueltos. Si no hay pasajes, di que "
                "el libro no cubre el tema; NO rellenes con conocimiento propio sin "
                "avisar explícitamente de que no viene del libro."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Consulta en INGLÉS con términos técnicos del dominio "
                            "(ej: 'context window budget management', "
                            "'when fine-tuning a foundation model is worth it')"
                        ),
                    },
                    "book": {
                        "type": "string",
                        "description": (
                            "Slug o título para acotar a un libro. "
                            "Omitir para buscar en todos."
                        ),
                    },
                    "limit": {"type": "integer", "default": 5, "minimum": 1, "maximum": 15},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="apex_book_index",
            description=(
                "Indexa una carpeta de libro en la biblioteca (una carpeta por "
                "libro, en cualquier ruta del disco). Trocea los .md en fragmentos "
                "citables y los vectoriza con nomic-embed-text local. "
                "Es incremental: solo reindexa los capítulos cuyo contenido cambió, "
                "así que añadir un capítulo nuevo es barato. Idempotente."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Carpeta del libro (admite ~).",
                    },
                    "title": {
                        "type": "string",
                        "description": "Título del libro. Por defecto, el nombre de la carpeta.",
                    },
                    "author": {
                        "type": "string",
                        "description": "Autor, para la cita. No suele estar en los ficheros.",
                    },
                    "force": {
                        "type": "boolean",
                        "default": False,
                        "description": "Reindexar todo aunque no haya cambios.",
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="apex_book_list",
            description=(
                "Lista los libros indexados en la biblioteca, con su recuento de "
                "capítulos y fragmentos. Útil para saber qué puede consultarse "
                "antes de preguntar, o para verificar que un libro se indexó."
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="apex_phase_entry_check",
            description=(
                "OBLIGATORIO al inicio de cada fase (5-10). Ejecuta tres comprobaciones: "
                "(1) verifica que la fase anterior está completed en context.db, "
                "(2) recupera errores y decisiones cross-project relevantes para esta fase, "
                "(3) devuelve un bloque visual '### Lecciones cross-project aplicadas' con "
                "los hits reales (proyecto, severidad, lección). El bloque es auditable — "
                "si está vacío, lo indica explícitamente. Usar ANTES del primer sub-paso "
                "de la fase. Nunca mockear ni saltarse."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "phase": {
                        "type": "integer",
                        "description": "Número de fase que va a comenzar (5-10)",
                        "minimum": 5,
                        "maximum": 10,
                    },
                    "context_hint": {
                        "type": "string",
                        "description": "Descripción breve del proyecto/feature actual para dirigir el retrieval (ej: 'auth con JWT', 'scraper de productos', 'bot Telegram')",
                    },
                },
                "required": ["phase"],
            },
        ),    ]


@server.call_tool()

async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    handler = HANDLERS.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    # La biblioteca de libros vive en ~/.apex/library.db y es cross-project:
    # se consulta desde cualquier sitio, incluso sin proyecto APEX. Por eso se
    # despacha ANTES de _get_db(), que lanzaría NotAnApexProjectError.
    db = None if name in LIBRARY_TOOLS else _get_db()
    if db is not None:
        await _ensure_db_schema(db)

    import time
    _t0 = time.monotonic()
    try:
        result = await handler(db, arguments)
        if not isinstance(result, list):
            result = [TextContent(type="text", text=str(result))]
    except Exception as exc:
        import traceback
        result = [TextContent(type="text", text=f"Error in {name}: {exc}\n{traceback.format_exc()}")]
    elapsed_ms = (time.monotonic() - _t0) * 1000
    # _debug_log es una corrutina con firma (tool, arguments, result, duration_ms).
    # El refactor a handlers la llamaba con un solo argumento y sin await, lo que
    # reventaba TODA tool en tiempo de ejecución.
    await _debug_log(
        name, arguments,
        result[0].text if result else "",
        int(elapsed_ms),
    )
    return result

async def _db_exists(db: ApexContextDB) -> bool:
    """Verifica si context.db existe."""
    return db.db_path.exists()


# --- Entry point ---

async def main():
    # Auto-lanzar APEX Hub si no está corriendo
    _launch_hub_if_needed()

    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
