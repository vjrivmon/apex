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

# --- Debug monitor (envía eventos si está corriendo) ---

_HUB_PORT_FILE = Path.home() / ".apex" / "hub-port"
_HUB_DIR = Path.home() / "RoadToDevOps" / "apex-hub"
_HUB_LOG = Path.home() / ".apex" / "hub.log"
_FALLBACK_MONITOR_URL = "http://localhost:8099/event"


def _hub_is_running() -> bool:
    """Comprueba si el hub responde en el puerto indicado por hub-port."""
    import socket as _socket
    if not _HUB_PORT_FILE.exists():
        return False
    try:
        port = int(_HUB_PORT_FILE.read_text().strip())
    except (ValueError, OSError):
        return False
    with _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except (ConnectionRefusedError, OSError):
            # Puerto en el archivo pero nadie escuchando → archivo stale
            try:
                _HUB_PORT_FILE.unlink()
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
            if _HUB_PORT_FILE.exists() and _hub_is_running():
                break
            time.sleep(0.2)

    # Abrir navegador (esté ya corriendo o recién arrancado)
    try:
        if _HUB_PORT_FILE.exists():
            port = _HUB_PORT_FILE.read_text().strip()
            if port.isdigit() and not already_running:
                # Solo abrir navegador si acabamos de lanzarlo (no cada vez que se usa /apex)
                _open_browser(f"http://localhost:{port}")
    except Exception:
        pass


def _hub_urls() -> list[str]:
    """Detecta dinámicamente el puerto del APEX Hub leyendo ~/.apex/hub-port."""
    urls = []
    try:
        if _HUB_PORT_FILE.exists():
            port = _HUB_PORT_FILE.read_text().strip()
            if port.isdigit():
                urls.append(f"http://localhost:{port}/api/live/event")
    except Exception:
        pass
    urls.append(_FALLBACK_MONITOR_URL)
    return urls


async def _debug_log(tool: str, arguments: dict, result: str, duration_ms: int = 0) -> None:
    """Envía evento al APEX Hub (puerto auto-detectado) y/o debug monitor. No falla si ninguno está."""
    payload = {
        "tool": tool,
        "arguments": arguments,
        "result": result[:500],
        "duration_ms": duration_ms,
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


def _get_db() -> ApexContextDB:
    """Obtiene la instancia de context.db para el proyecto actual."""
    root = _find_project_root()
    db_path = root / ".apex" / "context.db"
    return ApexContextDB(str(db_path))


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
            description="Actualiza el estado de una fase del proyecto (0-14). Estados: pending, in_progress, completed, skipped.",
            inputSchema={
                "type": "object",
                "properties": {
                    "phase_number": {"type": "integer", "minimum": 0, "maximum": 14},
                    "status": {"type": "string", "enum": ["pending", "in_progress", "completed", "skipped"]},
                    "notes": {"type": "string", "description": "Observaciones sobre la fase", "default": ""},
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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    db = _get_db()
    import time
    _t0 = time.monotonic()

    try:
        if name == "apex_get_context":
            level = arguments.get("level", "timeline")
            if not (await _db_exists(db)):
                result = [TextContent(type="text", text="No se encontró .apex/context.db en este proyecto. Usa apex_init_project primero.")]
            else:
                ctx = await db.get_context(level)
                result = [TextContent(type="text", text=ctx)]

        elif name == "apex_init_project":
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
            result = [TextContent(type="text", text=f"Proyecto inicializado en {root}/.apex/\n- context.db creada con 15 fases\n- Wiki scaffold en {wiki_dir}")]

        elif name == "apex_set_phase":
            await db.set_phase(arguments["phase_number"], arguments["status"], arguments.get("notes", ""))
            _project = await db.get_meta("nombre") or "unknown"
            _sync_to_obsidian("phase", {"project": _project, "phase": arguments["phase_number"], "status": arguments["status"], "notes": arguments.get("notes", "")})
            result = [TextContent(type="text", text=f"Fase {arguments['phase_number']} → {arguments['status']}")]

        elif name == "apex_add_decision":
            did = await db.add_decision(
                arguments["category"], arguments["decision"], arguments["reasoning"],
                phase=arguments.get("phase"), alternatives=arguments.get("alternatives", ""))
            _project = await db.get_meta("nombre") or "unknown"
            _sync_to_obsidian("decision", {"project": _project, "category": arguments["category"], "decision": arguments["decision"]})
            result = [TextContent(type="text", text=f"Decisión #{did} registrada: {arguments['decision'][:80]}")]

        elif name == "apex_invalidate_decision":
            await db.invalidate_decision(arguments["decision_id"], arguments.get("reason", ""))
            result = [TextContent(type="text", text=f"Decisión #{arguments['decision_id']} invalidada")]

        elif name == "apex_add_error":
            eid = await db.add_error(
                arguments["source"], arguments["description"], arguments["lesson"],
                phase=arguments.get("phase"), severity=arguments.get("severity", "medium"))
            _project = await db.get_meta("nombre") or "unknown"
            _sync_to_obsidian("error", {"project": _project, "source": arguments["source"], "description": arguments["description"]})
            result = [TextContent(type="text", text=f"Error #{eid} registrado [{arguments['source']}]: {arguments['description'][:80]}")]

        elif name == "apex_add_component":
            await db.add_component(
                arguments["id"], arguments["name"], arguments["type"],
                phase=arguments.get("phase"), description=arguments.get("description", ""),
                files=arguments.get("files"))
            if arguments.get("status") and arguments["status"] != "planned":
                await db.update_component_status(arguments["id"], arguments["status"])
            _project = await db.get_meta("nombre") or "unknown"
            _sync_to_obsidian("component", {"project": _project, "name": arguments["name"], "type": arguments["type"]})
            result = [TextContent(type="text", text=f"Componente '{arguments['name']}' registrado como {arguments.get('status', 'planned')}")]

        elif name == "apex_update_component":
            await db.update_component_status(arguments["id"], arguments["status"])
            result = [TextContent(type="text", text=f"Componente '{arguments['id']}' → {arguments['status']}")]

        elif name == "apex_add_next_step":
            sid = await db.add_next_step(
                arguments["description"], priority=arguments.get("priority", 5),
                phase=arguments.get("phase"))
            result = [TextContent(type="text", text=f"Paso #{sid} añadido [P{arguments.get('priority', 5)}]: {arguments['description'][:80]}")]

        elif name == "apex_complete_step":
            await db.complete_step(arguments["step_id"])
            result = [TextContent(type="text", text=f"Paso #{arguments['step_id']} completado")]

        elif name == "apex_search":
            mode = arguments.get("mode", "hybrid")
            limit = arguments.get("limit", 10)
            if mode == "fts":
                results = await db.search(arguments["query"], limit=limit)
                formatter = lambda r: f"- [{r['source']}] {r['content'][:150]}"
            else:
                results = await db.search_hybrid(arguments["query"], limit=limit)
                formatter = lambda r: (
                    f"- [{r['source']} · score={r['hybrid_score']:.2f}] {r['content'][:150]}"
                )
            if not results:
                result = [TextContent(type="text", text=f"Sin resultados para '{arguments['query']}' (mode={mode})")]
            else:
                lines = [f"Resultados para '{arguments['query']}' (mode={mode}):"]
                for r in results:
                    lines.append(formatter(r))
                result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_scaffold_devops":
            target = Path(arguments["target"]) if arguments.get("target") else _find_project_root()
            opts = _ScaffoldOptions(
                target=target,
                project_name=arguments["name"],
                stack=arguments.get("stack", "python"),
                deploy_target=arguments.get("deploy_target", "vercel"),
                port=int(arguments.get("port", 8000)),
                health_path=arguments.get("health_path", "/health"),
                with_monitoring=bool(arguments.get("with_monitoring", True)),
                overwrite=bool(arguments.get("overwrite", False)),
            )
            report = _scaffold_devops(opts)
            lines = [f"Scaffold DevOps en {target}:"]
            lines.append(f"- Copiados: {len(report.copied)}")
            for p in report.copied:
                lines.append(f"  + {p.relative_to(target)}")
            if report.skipped:
                lines.append(f"- Saltados ({len(report.skipped)}, ya existían):")
                for p in report.skipped:
                    lines.append(f"  · {p.relative_to(target)}")
            result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_ingest_source":
            src_path = Path(arguments["path"])
            if not src_path.is_absolute():
                src_path = _find_project_root() / src_path
            if not src_path.exists():
                result = [TextContent(type="text", text=f"Path no existe: {src_path}")]
            else:
                auto_wiki = arguments.get("auto_wiki", True)
                recursive = arguments.get("recursive", True)
                project_root = _find_project_root()
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
                result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_lint_second_brain":
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
            result = [TextContent(type="text", text=f"{md}\n\n(Report: {report_path})")]

        elif name == "apex_synthesize":
            root = _find_project_root()
            trigger = arguments.get("trigger", "auto")
            min_score = float(arguments.get("min_score", 0.6))
            res = _synthesize(root, force=(trigger == "force"), min_score=min_score)
            import json as _json
            result = [TextContent(type="text", text=_json.dumps(res, ensure_ascii=False, indent=2, default=str))]

        elif name == "apex_set_portfolio_meta":
            fields = arguments["fields"] or {}
            if not isinstance(fields, dict):
                result = [TextContent(type="text", text="fields debe ser un objeto {key: value}")]
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
                result = [TextContent(type="text", text=(
                    f"Guardados {len(saved)} campos en project_meta: {', '.join(saved)}. "
                    "Ejecuta apex_portfolio_draft para generar el MDX."
                ))]

        elif name == "apex_portfolio_draft":
            slug = arguments["slug"]
            apply = bool(arguments.get("apply", False))
            out_dir = Path(arguments["out_dir"]) if arguments.get("out_dir") else _PORTFOLIO_OUT_DIR
            root = _find_project_root()
            ctx_db = root / ".apex" / "context.db"
            if not ctx_db.exists():
                result = [TextContent(type="text", text=(
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
                    result = [TextContent(type="text", text=f"{action}: {path}\n\n{content}{hint}")]
                except FileNotFoundError as e:
                    result = [TextContent(type="text", text=f"Error: {e}")]

        elif name == "apex_search_cross_project":
            query = arguments["query"]
            limit = arguments.get("limit", 8)
            exclude_current = arguments.get("exclude_current", True)
            current_project = None
            if exclude_current:
                root = _find_project_root()
                current_project = root.name.lower().replace(" ", "-")
            hits = _search_cross_project(query, limit=limit, exclude_project=current_project)
            if not hits["hub_available"]:
                result = [TextContent(type="text", text=(
                    f"hub.db no disponible en {_HUB_DB}. Lanza apex-hub (python -m backend en "
                    "~/RoadToDevOps/apex-hub/) para habilitar retrieval cross-project."
                ))]
            elif not (hits["errors"] or hits["decisions"] or hits["components"]):
                result = [TextContent(type="text", text=(
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
                result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_log_session":
            await db.log_session(
                arguments["summary"], key_outcomes=arguments.get("key_outcomes", ""),
                phase=arguments.get("phase"))
            _project = await db.get_meta("nombre") or "unknown"
            _sync_to_obsidian("session", {"project": _project, "summary": arguments["summary"]})
            result = [TextContent(type="text", text=f"Sesión registrada: {arguments['summary'][:80]}")]

        elif name == "apex_wiki_add":
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
            result = [TextContent(type="text", text=f"Wiki página '{arguments['slug']}' guardada")]

        else:
            result = [TextContent(type="text", text=f"Herramienta desconocida: {name}")]

    except Exception as e:
        _duration = int((time.monotonic() - _t0) * 1000)
        await _debug_log(name, arguments, f"ERROR: {str(e)}", _duration)
        return [TextContent(type="text", text=f"Error en {name}: {str(e)}")]

    # Log al debug monitor después de cada llamada exitosa
    _duration = int((time.monotonic() - _t0) * 1000)
    await _debug_log(name, arguments, result[0].text if result else "", _duration)
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
