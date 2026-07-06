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
import platform
import sys
from pathlib import Path

# Añadir lib/ al path para importar context_db y wiki_scaffold
_apex_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_apex_root / "lib"))

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


def _security_gate_blocks() -> bool:
    """True si el gate 10.5 NO pasa al entrar a fase 11 (deploy).

    Fail-CLOSED (auditoría 2026-07-03, C3): llegar a deploy SIN `.apex/security/`
    también bloquea — un proyecto que despliega debe tener evidencia AgentArmor.
    Antes (Sprint 26) el dir ausente no bloqueaba (fail-open). Override con
    force=True. Best-effort: ante error inesperado de lectura, no bloquea para
    no colgar el flujo por un bug de la maquinaria.
    """
    try:
        root = _find_project_root()
        if not (root / ".apex" / "security").is_dir():
            return True
        return not _check_security_gate(root).passed
    except Exception:
        return False
from reverse_engineer import (
    scan_project as _reverse_scan,
    render_report_md as _render_reverse_report,
    ScanReport as _ScanReport,
    RetroactiveFinding as _RetroFinding,
)

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


# Hooks que se instalan en proyectos guiados. Se excluyen a proposito:
#   - session-start.py: ya esta registrado a nivel usuario (~/.claude),
#     registrarlo aqui duplicaria la inyeccion de contexto cross-project.
#   - weekly-design-lint.py: solo tiene sentido en proyectos de diseno;
#     ensuciaria la wiki de proyectos no-UI.
_PROJECT_HOOKS = {
    "PreToolUse": [
        ("mcp__apex__apex_set_phase", ["phase-gate.py"]),
        ("Write|Edit|MultiEdit", ["code-before-phase5-gate.py"]),
    ],
    "PostToolUse": [("", [
        "post-tool-archive.py", "skill-forge-watch.py",
        "advisor-trigger.py", "trace-prompt.py",
    ])],
    "UserPromptSubmit": [("", [
        "context-watch.py", "end-of-day-doctor.py",
        "advice-injector.py", "advisor-outcome-watch.py",
    ])],
}


def _build_project_settings() -> dict:
    """settings.json para un proyecto guiado: apunta al venv y a los hooks
    del repo apex por ruta absoluta, para que el harness corra fuera del
    propio repo apex sin duplicar scripts ni necesitar un venv local."""
    py = str(_apex_root / ".venv" / "bin" / "python3")
    hooks_dir = _apex_root / ".claude" / "hooks"

    def _cmd(script: str) -> dict:
        return {"type": "command",
                "command": f"{py} {hooks_dir / script}"}

    hooks: dict = {}
    for event, groups in _PROJECT_HOOKS.items():
        hooks[event] = [
            {"matcher": matcher, "hooks": [_cmd(s) for s in scripts]}
            for matcher, scripts in groups
        ]
    return {"hooks": hooks}


def _install_project_hooks(root: Path, force: bool = False) -> str:
    """Escribe <root>/.claude/settings.json con el registro de hooks APEX.

    Idempotente: si ya existe y no es force, no lo toca. Si el dir es el
    propio repo apex, no hace nada (ya tiene su settings.json canonico).
    """
    if root.resolve() == _apex_root.resolve():
        return "settings.json: omitido (es el repo apex)"
    settings_path = root / ".claude" / "settings.json"
    if settings_path.exists() and not force:
        return f"settings.json: ya existe en {settings_path} (usa force para sobrescribir)"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(_build_project_settings(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8")
    n = sum(len(s) for groups in _PROJECT_HOOKS.values() for _, s in groups)
    return f"settings.json: {n} hooks registrados en {settings_path}"


_CLAUDE_MD_BEGIN = "<!-- APEX:BEGIN -->"
_CLAUDE_MD_END = "<!-- APEX:END -->"


def _apex_claude_md_block(project_name: str) -> str:
    """Bloque APEX para el CLAUDE.md del proyecto guiado.

    Auditoría 2026-07-03 (C5): CLAUDE.md es el ÚNICO fichero que Claude Code
    carga incondicionalmente cada turno. Si init no lo escribe, las reglas
    absolutas viven solo tras un context pointer que el agente puede no seguir.
    Este bloque las inlinea en el layer always-on, con `gate` como leading word.
    """
    return f"""{_CLAUDE_MD_BEGIN}
## APEX — Proyecto guiado (no editar este bloque a mano)

Este proyecto (**{project_name}**) se desarrolla con APEX. En CADA sesión:

1. Ejecuta `ToolSearch("apex")` y luego `/apex` — retoma la fase actual.
2. Las fases 0-14 son SECUENCIALES. Un **gate** bloquea cerrar una fase sin
   pasar el grader (`apex_grader_evaluate`) y escribir código antes de fase 5.
   Estos gates son vinculantes (hooks), no consejos.

### Reglas absolutas (violarlas hace fallar la fase)

- **SIEMPRE** registra decisiones/errores/componentes con las tools `apex_*`.
  El contexto vive en `.apex/context.db`, no en tu memoria de sesión.
- **NUNCA** generes código antes de fase 5 (0-4 son análisis y diseño). Un
  **gate** lo bloquea.
- **NUNCA** cierres una fase sin TODOS sus sub-pasos verificados por el grader.
- **NUNCA** uses emojis como iconos. Lucide/Phosphor/Heroicons/SVG. (error x3 proyectos)
- **NUNCA** describas un diseño visual con texto: mockup en herramienta de diseño.
- **SIEMPRE** `uname -s` antes de proponer stack dependiente de plataforma.
- **SIEMPRE** verifica frontend con Playwright ANTES de presentarlo.
- **SIEMPRE** `apex_search_cross_project(query)` (o `apex_phase_entry_check`)
  antes de decisiones de stack/diseño. En fases 0/2/3/5 es un **gate**: el
  grader BLOQUEA cerrar la fase si no consultaste hub.db. No es opcional.
- **NUNCA** preguntes qué sub-paso hacer primero: son secuenciales, sigue el orden.
- **NUNCA** inventes decisiones de diseño: si hay duda, `AskUserQuestion`.
- **Español con tildes y eñes** en toda UI y copy.
- Arquitectura hexagonal + SMA por defecto; parte lo que crezca >400 líneas o haga 3 cosas.

### Postura bajo presión (por qué el proceso es el mismo cada sesión)

- **No cedas tu criterio verificado ante presión.** Si comprobaste algo
  (`uname`, `ss`, un ToS, un test que falla, una regla APEX) y el usuario
  empuja sin refutarlo ("hazlo sin rechistar", "no me pongas excusas"),
  mantén la posición y reexpón la evidencia UNA vez. No digas "tienes razón"
  a algo que nadie ha rebatido. Ceder ante presión (no ante razón) es
  exactamente lo que produce "cada sesión algo distinto".
- **Cambiar el objetivo se acata; saltarse un gate/sub-paso NO.** Un requisito
  nuevo es legítimo; brincar una verificación no lo es.
- Excepción: acción irreversible sobre algo tuyo (cuenta, servidor) → tú
  decides asumir el riesgo, pero el agente deja el escenario de fallo explícito.

El detalle completo de cada fase vive en el repo APEX; `/apex` lo carga bajo demanda.
{_CLAUDE_MD_END}
"""


def _install_project_claude_md(root: Path, project_name: str,
                               force: bool = False) -> str:
    """Escribe/inyecta el bloque APEX en <root>/CLAUDE.md (idempotente).

    - Sin CLAUDE.md → lo crea con el bloque.
    - CLAUDE.md sin bloque APEX → antepone el bloque (preserva el resto).
    - CLAUDE.md con bloque APEX → lo reemplaza si force, si no lo deja.
    - En el propio repo apex: omitido (ya tiene su CLAUDE.md canónico).
    """
    if root.resolve() == _apex_root.resolve():
        return "CLAUDE.md: omitido (es el repo apex)"
    path = root / "CLAUDE.md"
    block = _apex_claude_md_block(project_name)
    if not path.exists():
        path.write_text(block, encoding="utf-8")
        return f"CLAUDE.md: creado con bloque APEX en {path}"
    existing = path.read_text(encoding="utf-8")
    if _CLAUDE_MD_BEGIN in existing:
        if not force:
            return "CLAUDE.md: ya tiene bloque APEX (usa force para regenerar)"
        start = existing.index(_CLAUDE_MD_BEGIN)
        end = existing.index(_CLAUDE_MD_END) + len(_CLAUDE_MD_END)
        new = existing[:start] + block.rstrip("\n") + existing[end:]
        path.write_text(new, encoding="utf-8")
        return f"CLAUDE.md: bloque APEX regenerado en {path}"
    # Existe pero sin bloque: anteponer, preservando el contenido del usuario.
    path.write_text(block + "\n" + existing, encoding="utf-8")
    return f"CLAUDE.md: bloque APEX antepuesto en {path}"


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

# Palabras vacías que no discriminan y que, al ser AND implícito en FTS5,
# vaciaban el resultado (p.ej. "errores" iba en cada query de fase y forzaba
# que cada hit la contuviese literalmente).
_FTS_STOPWORDS = {
    "errores", "error", "de", "la", "el", "los", "las", "y", "o", "en",
    "con", "para", "the", "a", "an", "of", "and", "or",
}


def _build_fts_or_query(query: str) -> str:
    """Convierte una consulta multi-palabra en una disyunción FTS5 (OR).

    FTS5 `MATCH "a b c"` es AND implícito: exige las tres palabras en la misma
    fila, lo que devolvía 0 hits para queries como
    "scaffold hexagonal estructura errores". Tokenizamos, quitamos stopwords y
    caracteres especiales de FTS5, y unimos con OR para que cualquier término
    relevante haga match (rank ordena por relevancia). Best-effort: si tras
    filtrar no queda nada, cae al término más largo del original.
    """
    import re

    raw_tokens = re.findall(r"[0-9A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", query.lower())
    tokens = [t for t in raw_tokens if len(t) >= 3 and t not in _FTS_STOPWORDS]
    if not tokens:
        # Nada útil tras filtrar: usa el token más largo del original (o vacío).
        tokens = sorted(raw_tokens, key=len, reverse=True)[:1]
    if not tokens:
        return ""
    # Dedup preservando orden.
    seen: set = set()
    uniq = [t for t in tokens if not (t in seen or seen.add(t))]
    return " OR ".join(uniq)


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
        # AND implícito de FTS5 vaciaba el resultado; usamos disyunción OR.
        or_q = _build_fts_or_query(fts_q)
        if not or_q:
            return {**empty, "hub_available": True}

        sql = (
            "SELECT project_id, source_type, source_id, "
            "snippet(hub_search, 3, '[', ']', '...', 24) AS snip, rank "
            "FROM hub_search WHERE hub_search MATCH ?"
        )
        params: list = [or_q]
        if exclude_project:
            sql += " AND project_id != ?"
            params.append(exclude_project)
        sql += " ORDER BY rank LIMIT ?"
        params.append(limit * 3)

        try:
            rows = [dict(r) for r in conn.execute(sql, params)]
        except sqlite3.OperationalError:
            # Sintaxis FTS5 inválida → reintento como frase exacta del original
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


async def _mark_cross_project_consulted(db, phase: int | None) -> None:
    """Registra en project_meta que se consultó hub.db para la fase actual.

    El grader (fase 0,2,3,5) exige este flag para cerrar la fase — regla
    absoluta #18. Best-effort: si falla el registro, no rompe el retrieval.
    """
    if phase is None:
        try:
            cur = await db.get_current_phase()
            phase = cur["number"] if cur else None
        except Exception:
            phase = None
    if phase is None:
        return
    try:
        await db.set_meta(f"cross_project_consulted_phase_{int(phase)}", "true")
    except Exception:
        pass


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
                    "install_hooks": {"type": "boolean", "default": True, "description": "Registra los hooks APEX en .claude/settings.json del proyecto (default true)"},
                    "force_hooks": {"type": "boolean", "default": False, "description": "Sobrescribe un .claude/settings.json existente"},
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
                        "enum": ["architecture", "stack", "design", "data", "security", "deploy", "ux", "testing", "solution_type", "detected", "launch", "maintenance", "performance"],
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
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    db = _get_db()
    await _ensure_db_schema(db)
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
            await db.set_meta("detected_os", platform.system() or "unknown")
            if arguments.get("description"):
                await db.set_meta("descripción", arguments["description"])
            if arguments.get("solution_type"):
                await db.set_meta("tipo_solución", arguments["solution_type"])
            # Crear wiki scaffold
            domain = arguments.get("domain", "")
            wiki_dir = create_wiki(str(root), arguments["name"], domain)
            # Instala el harness (hooks) en el proyecto guiado salvo opt-out.
            hooks_msg = ""
            if arguments.get("install_hooks", True):
                _force = bool(arguments.get("force_hooks", False))
                hooks_msg = "\n- " + _install_project_hooks(root, force=_force)
                # C5: binding always-on. CLAUDE.md mete las 20 reglas en el
                # contexto que Claude Code carga cada turno del proyecto guiado.
                hooks_msg += "\n- " + _install_project_claude_md(
                    root, arguments["name"], force=_force)
            result = [TextContent(type="text", text=f"Proyecto inicializado en {root}/.apex/\n- context.db creada con 15 fases\n- Wiki scaffold en {wiki_dir}{hooks_msg}")]

        elif name == "apex_set_phase":
            phase_n = arguments["phase_number"]
            new_status = arguments["status"]
            force = bool(arguments.get("force", False))
            force_reason = arguments.get("force_reason", "")

            # Sprint 8: consultar último verdict del grader
            blocking_phase = phase_n if new_status == "completed" else (phase_n - 1 if new_status == "in_progress" else None)
            verdict = None
            if blocking_phase is not None and blocking_phase >= 0:
                verdict = await db.get_latest_verdict(blocking_phase)

            # Guarda de progresión secuencial (auditoría 2026-07-03, C4): no se
            # puede ABRIR una fase saltándose fases previas incompletas. Evita
            # que el agente pase de fase 2 a 8 sin pasar por 3-7.
            _seq_gap = None
            if new_status == "in_progress" and not force and isinstance(phase_n, int) and phase_n > 0:
                _all = await db.get_all_phases()
                _by_num = {p["number"]: p for p in _all}
                _skipped = [n for n in range(0, phase_n)
                            if _by_num.get(n) and _by_num[n]["status"] not in ("completed", "in_progress")]
                if _skipped:
                    _seq_gap = _skipped

            # Fail-CLOSED (auditoría 2026-07-03, C2): CERRAR una fase exige un
            # verdict del grader. Sin verdict → el grader nunca corrió → se
            # bloquea. Espeja al hook phase-gate.py; el dispatcher es la red de
            # respaldo si el hook no está instalado.
            _no_verdict_close = (new_status == "completed"
                                 and blocking_phase is not None and blocking_phase >= 0
                                 and verdict is None and not force)

            if _seq_gap is not None:
                msg_lines = [
                    f"BLOQUEADO por progresión secuencial (C4):",
                    f"  Para abrir la fase {phase_n} faltan fases previas sin empezar: {_seq_gap}",
                    "",
                    "Las fases son secuenciales. Cierra las previas antes de saltar.",
                    "Para bypassear: apex_set_phase(..., force=True, force_reason='...').",
                ]
                result = [TextContent(type="text", text="\n".join(msg_lines))]
            elif _no_verdict_close:
                msg_lines = [
                    f"BLOQUEADO: fase {blocking_phase} no tiene verdict del grader.",
                    "  No se puede cerrar una fase sin evaluarla.",
                    "",
                    f"Para resolver: corre apex_grader_evaluate(phase={blocking_phase}, ...).",
                    "Para bypassear: apex_set_phase(..., force=True, force_reason='...').",
                ]
                result = [TextContent(type="text", text="\n".join(msg_lines))]
            elif verdict and verdict.get("should_block") and not force:
                msg_lines = [
                    f"BLOQUEADO por grader (verdict #{verdict['id']} de fase {blocking_phase}):",
                    f"  Quality: {verdict['quality']}/4",
                    f"  Issues: {', '.join(verdict['issues']) or '(ninguna)'}",
                    f"  Razón: {verdict['reasoning']}",
                    "",
                    "Para bypassear: apex_set_phase(..., force=True, force_reason='...')",
                    "Para resolver: ataca los issues y vuelve a llamar apex_grader_evaluate.",
                ]
                result = [TextContent(type="text", text="\n".join(msg_lines))]
            elif (phase_n == 11 and new_status == "in_progress"
                  and not force and _security_gate_blocks()):
                # Gate 10.5 (AgentArmor): no se entra a fase 11 (deploy) si
                # alguna capa L1-L8 no esta en `status: passed`.
                _root = _find_project_root()
                _report = _check_security_gate(_root)
                _failed = ", ".join(
                    f"{l.layer}({l.status})" for l in _report.failed_layers
                ) or "(desconocidas)"
                msg_lines = [
                    "BLOQUEADO por gate de seguridad 10.5 (AgentArmor):",
                    f"  Capas no passed: {_failed}",
                    "",
                    "Para resolver: completa las capas en .apex/security/L*-*.md "
                    "(status: passed) y corre apex_security_gate para verificar.",
                    "Para bypassear: apex_set_phase(..., force=True, "
                    "force_reason='...').",
                ]
                result = [TextContent(type="text", text="\n".join(msg_lines))]
            else:
                if (phase_n == 11 and new_status == "in_progress"
                        and force and _security_gate_blocks()):
                    # override documentado del gate de seguridad
                    await db.add_error(
                        source="claude",
                        description="Override del gate de seguridad 10.5 al entrar a fase 11",
                        lesson=force_reason or "(sin razon documentada)",
                        phase=10,
                        severity="critical",
                    )
                if verdict and verdict.get("should_block") and force:
                    # registra el override como error con la razón
                    await db.add_error(
                        source="claude",
                        description=f"Override de bloqueo del grader en fase {blocking_phase}",
                        lesson=force_reason or "(sin razón documentada)",
                        phase=blocking_phase,
                        severity="high",
                    )
                await db.set_phase(phase_n, new_status, arguments.get("notes", ""))
                _project = await db.get_meta("nombre") or "unknown"
                _sync_to_obsidian("phase", {
                    "project": _project, "phase": phase_n,
                    "status": new_status, "notes": arguments.get("notes", ""),
                })
                msg = f"Fase {phase_n} → {new_status}"
                if verdict:
                    msg += f" (grader: quality {verdict['quality']}/4)"
                result = [TextContent(type="text", text=msg)]

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

        elif name == "apex_security_gate":
            root = _find_project_root()
            if arguments.get("scaffold"):
                copied = _scaffold_security_templates(root)
                scaffold_msg = f"Scaffolded {len(copied)} archivos de templates AgentArmor.\n\n"
            else:
                scaffold_msg = ""
            report = _check_security_gate(root)
            md = _render_security_report(report)
            report_path = _write_security_report(report)
            status = "PASSED ✓" if report.passed else "BLOCKED ✗"
            result = [TextContent(type="text", text=(
                f"{scaffold_msg}Security Gate: **{status}**\n\n{md}\n\n(Report: {report_path})"
            ))]

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
            if hits["hub_available"]:
                # Registra la consulta para satisfacer el gate del grader (#18).
                await _mark_cross_project_consulted(db, None)
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

        elif name == "apex_phase_entry_check":
            phase = arguments["phase"]
            context_hint = arguments.get("context_hint", "")

            # Queries dirigidas por fase. Multi-palabra: el retrieval las
            # tokeniza y las une con OR (ver _build_fts_or_query), así que NO
            # hace falta stuffing de "errores" — antes forzaba AND y vaciaba.
            _PHASE_QUERIES = {
                0: ["mercado competidores dominio", "value proposition problema real"],
                2: ["diseño paleta tipografia stack", "arquitectura frontend backend"],
                3: ["modelo datos spec entidades", "api contrato esquema"],
                5: ["scaffold hexagonal estructura", "git secretos entorno"],
                6: ["dominio logica core entidades", "casos uso tests"],
                7: ["database adapter migraciones", "LLM adapter infraestructura"],
                8: ["integration end-to-end", "mock datos hardcoded frontend"],
                9: ["tests coverage playwright", "edge cases regresion"],
                10: ["seguridad OWASP secretos", "rate limit headers auth"],
            }

            lines = [f"## Gate de entrada — Fase {phase}"]
            lines.append("")

            # 1. Verificar fase anterior completada
            prev_phase = phase - 1
            try:
                all_phases = await db.get_all_phases()
                phase_map = {p["phase_number"]: p["status"] for p in all_phases}
                prev_status = phase_map.get(prev_phase)
            except Exception:
                prev_status = None

            if prev_status and prev_status != "completed":
                lines.append(f"ADVERTENCIA: Fase {prev_phase} esta en estado '{prev_status}', no 'completed'.")
                lines.append(f"  Verifica con apex_get_context(level='timeline') antes de continuar.")
            elif prev_status == "completed":
                lines.append(f"Fase {prev_phase}: completed")
            else:
                lines.append(f"Fase {prev_phase}: estado desconocido (context.db no inicializado o fase no registrada)")

            lines.append("")

            # 2. Retrieval cross-project dirigido por fase
            root = _find_project_root()
            current_project = root.name.lower().replace(" ", "-")
            all_errors: list[dict] = []
            all_decisions: list[dict] = []

            base_queries = _PHASE_QUERIES.get(phase, [])
            if context_hint:
                base_queries = [context_hint] + base_queries

            seen_error_ids: set = set()
            seen_decision_ids: set = set()

            for q in base_queries[:3]:  # máx 3 queries para no saturar
                hits = _search_cross_project(q, limit=5, exclude_project=current_project)
                for e in hits.get("errors", []):
                    key = (e["project_id"], e["description"][:60])
                    if key not in seen_error_ids:
                        seen_error_ids.add(key)
                        all_errors.append(e)
                for d in hits.get("decisions", []):
                    key = (d["project_id"], d["decision"][:60])
                    if key not in seen_decision_ids:
                        seen_decision_ids.add(key)
                        all_decisions.append(d)

            hub_ok = _HUB_DB.exists()
            if hub_ok:
                # El entry-check hace el retrieval por el agente: cuenta como
                # consulta cross-project para el gate del grader (#18).
                await _mark_cross_project_consulted(db, phase)

            # 3. Bloque visual auditable
            lines.append("### Lecciones cross-project aplicadas")
            lines.append("")

            if not hub_ok:
                lines.append("hub.db no disponible — retrieval cross-project desactivado.")
                lines.append("Para activarlo: lanza apex-hub (`python -m backend` en ~/RoadToDevOps/apex-hub/).")
            elif not all_errors and not all_decisions:
                lines.append(f"Sin lecciones cross-project para fase {phase}. No hay errores ni decisiones previas relevantes.")
                lines.append("(hub.db disponible, 0 hits)")
            else:
                if all_errors:
                    lines.append(f"**Errores a evitar ({len(all_errors)})**")
                    for e in all_errors[:6]:
                        sev = e.get("severity", "medium")
                        rec = e.get("recurrence_count", 1)
                        proj = e.get("project_id", "?")
                        desc = e.get("description", "")[:120]
                        lesson = e.get("lesson", "")[:180]
                        lines.append(f"- [{proj} · {sev} · x{rec}] {desc}")
                        if lesson:
                            lines.append(f"  → Lección: {lesson}")
                if all_decisions:
                    lines.append("")
                    lines.append(f"**Decisiones previas relevantes ({len(all_decisions)})**")
                    for d in all_decisions[:4]:
                        proj = d.get("project_id", "?")
                        cat = d.get("category", "")
                        dec = d.get("decision", "")[:120]
                        tag = "INVALIDADA" if d.get("invalid_from") else "vigente"
                        lines.append(f"- [{proj} · {cat} · {tag}] {dec}")

            lines.append("")
            lines.append("---")
            lines.append(f"Retrieval completado. Procede con sub-paso [{'abcdefghij'[phase-5]}a] de la fase {phase}.")

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

        elif name == "apex_reverse_scan":
            target = Path(arguments["path"]).expanduser().resolve()
            if not target.exists() or not target.is_dir():
                result = [TextContent(type="text", text=f"Path no existe o no es directorio: {target}")]
            else:
                report = _reverse_scan(target)
                fmt = arguments.get("format", "markdown")
                chunks = []
                if fmt in ("markdown", "both"):
                    chunks.append(_render_reverse_report(report))
                if fmt in ("json", "both"):
                    chunks.append(f"```json\n{report.to_json()}\n```")
                if arguments.get("write_report"):
                    apex_dir = target / ".apex"
                    apex_dir.mkdir(exist_ok=True)
                    from datetime import datetime, timezone
                    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                    out_path = apex_dir / f"reverse-report-{stamp}.md"
                    out_path.write_text(_render_reverse_report(report), encoding="utf-8")
                    chunks.append(f"\n(Report: {out_path})")
                result = [TextContent(type="text", text="\n\n".join(chunks))]

        elif name == "apex_reverse_plan":
            scan_report = arguments["scan_report"]
            answers = arguments.get("answers", {})
            # Construir ActionPlan: priorizar findings según severity y answers
            # a=skip, b=now, c=backlog, d=partial
            tasks = []
            for f in scan_report.get("findings", []):
                choice = answers.get(f["id"], "b")  # default: now
                if choice == "a":
                    action = "skip"
                elif choice == "c":
                    action = "backlog"
                elif choice == "d":
                    action = "verify"
                else:
                    action = "now"
                tasks.append({
                    "finding_id": f["id"],
                    "phase": f["phase"],
                    "severity": f["severity"],
                    "title": f["title"],
                    "action": action,
                })
            # Ordenar: now first, luego severity, luego phase
            action_order = {"now": 0, "verify": 1, "backlog": 2, "skip": 3}
            sev_order = {"high": 0, "medium": 1, "low": 2}
            tasks.sort(key=lambda t: (action_order[t["action"]], sev_order[t["severity"]], t["phase"]))
            # Fases a retomar: las que tengan status != completed según el scan
            phases_to_retake = [
                p for p in scan_report.get("phases", [])
                if p["status"] in ("partial", "missing", "unknown")
            ]
            plan = {
                "project": scan_report.get("project_name"),
                "tasks": tasks,
                "phases_to_retake": phases_to_retake,
                "summary": f"{len([t for t in tasks if t['action']=='now'])} tareas ahora · "
                           f"{len([t for t in tasks if t['action']=='backlog'])} backlog · "
                           f"{len([t for t in tasks if t['action']=='skip'])} skipped",
            }
            md = [f"# Plan de acción: {plan['project']}", "", f"**{plan['summary']}**", "", "## Tareas ordenadas"]
            for t in tasks[:30]:
                md.append(f"- [{t['action'].upper()}] {t['finding_id']} (fase {t['phase']}, {t['severity']}): {t['title']}")
            md.append("")
            md.append(f"## Fases a retomar: {len(phases_to_retake)}")
            for p in phases_to_retake:
                md.append(f"- Fase {p['phase']} ({p['name']}) — status={p['status']} score={p['score']:.2f}")
            result = [TextContent(type="text", text="\n".join(md) + f"\n\n```json\n{json.dumps(plan, indent=2, ensure_ascii=False)}\n```")]

        elif name == "apex_onboard_apply":
            target = Path(arguments["path"]).expanduser().resolve()
            scan_report = arguments["scan_report"]
            plan = arguments.get("plan", {})

            apex_dir = target / ".apex"
            wiki_dir = apex_dir / "wiki"
            created = []
            if not wiki_dir.exists():
                create_wiki(str(wiki_dir), project_name=target.name)
                created.append(str(wiki_dir))

            # Crear/inicializar context.db del proyecto target
            target_db_path = apex_dir / "context.db"
            from context_db import ApexContextDB
            target_db = ApexContextDB(str(target_db_path))
            await target_db.initialize()

            # Registrar meta
            await target_db.set_project_meta("project_name", target.name)
            await target_db.set_project_meta("onboarded_by", "apex_onboard_apply")
            from datetime import datetime, timezone
            await target_db.set_project_meta("onboarded_at", datetime.now(timezone.utc).isoformat())

            # Marcar fases según scan
            phase_count = 0
            for p in scan_report.get("phases", []):
                if isinstance(p["phase"], float) and p["phase"] == 10.5:
                    continue  # 10.5 es gate, no fase en la tabla
                phase_num = int(p["phase"])
                status_map = {"completed": "completed", "partial": "in_progress", "missing": "pending", "unknown": "pending"}
                await target_db.set_phase(phase_num, status_map[p["status"]],
                                          notes=f"[retroactive] score={p['score']:.2f}. {'; '.join(p['evidence'][:2])}")
                phase_count += 1

            # Registrar findings como errores retroactivos (category=retroactive)
            findings_logged = 0
            for f in scan_report.get("findings", [])[:50]:
                await target_db.add_decision(
                    category="retroactive",
                    decision=f"[{f['id']}] {f['title']}",
                    reasoning=f["detail"],
                    phase=int(f["phase"]) if f["phase"] >= 0 and isinstance(f["phase"], (int, float)) and f["phase"] == int(f["phase"]) else 0,
                )
                findings_logged += 1

            # next_steps del plan
            tasks_logged = 0
            for t in plan.get("tasks", [])[:30]:
                if t["action"] in ("now", "verify"):
                    priority = "high" if t["severity"] == "high" else "medium"
                    await target_db.add_next_step(
                        description=f"[{t['finding_id']}] {t['title']}",
                        priority=priority,
                    )
                    tasks_logged += 1

            # Wiki: gap-analysis
            gap_md = "# Gap analysis\n\n"
            gap_md += f"Scan del {datetime.now(timezone.utc).strftime('%Y-%m-%d')}\n\n"
            gap_md += f"## Fases\n\n"
            for p in scan_report.get("phases", []):
                gap_md += f"- **{p['phase']} {p['name']}**: {p['status']} (score {p['score']:.2f})\n"
            gap_md += "\n## Findings críticos\n\n"
            for f in scan_report.get("findings", []):
                if f["severity"] == "high":
                    gap_md += f"- {f['id']} (fase {f['phase']}): {f['detail']}\n"
            await target_db.add_wiki_page(
                slug="concepts/gap-analysis",
                title="Gap analysis",
                content=gap_md,
                page_type="concept",
                tags=["retroactive", "onboarding"],
            )
            (wiki_dir / "concepts").mkdir(parents=True, exist_ok=True)
            (wiki_dir / "concepts" / "gap-analysis.md").write_text(gap_md, encoding="utf-8")

            await target_db.log_session(
                summary=f"Onboarded via reverse-engineer: {phase_count} fases, {findings_logged} findings, {tasks_logged} next_steps",
                key_outcomes=json.dumps({"phases": phase_count, "findings": findings_logged, "tasks": tasks_logged}),
                phase=0,
            )

            result = [TextContent(type="text", text=(
                f"Onboard aplicado en {target}:\n"
                f"- {phase_count} fases marcadas\n"
                f"- {findings_logged} findings retroactivos registrados como decisiones\n"
                f"- {tasks_logged} tareas añadidas como next_steps\n"
                f"- Wiki: concepts/gap-analysis.md creado\n"
                f"- .apex/ listo para arrancar fase 12 (iteración)"
            ))]

        elif name == "apex_grader_evaluate":
            phase_n = int(arguments["phase"])
            mode = arguments.get("mode", "deterministic")
            component_types = list(arguments.get("component_types", []))
            persist = bool(arguments.get("persist", True))

            # Recolectar metadata de decisiones para enriquecer evidence
            try:
                decisions_meta = {}
                _os = await db.get_meta("detected_os")
                if not _os:
                    # Auto-heal: proyectos inicializados antes de que
                    # apex_init_project escribiera detected_os no tienen el
                    # valor. Sin esto, no_so_detection (bloqueante) los
                    # dejaba atascados en cada fase. Lo escribimos ahora.
                    _os = platform.system() or "unknown"
                    try:
                        await db.set_meta("detected_os", _os)
                    except Exception:
                        pass
                if _os:
                    decisions_meta["detected_os"] = _os
                # Flag cross-project (#18): ¿se consultó hub.db para esta fase?
                decisions_meta["hub_available"] = _HUB_DB.exists()
                _cp = await db.get_meta(f"cross_project_consulted_phase_{phase_n}")
                decisions_meta["cross_project_consulted"] = (_cp == "true")
            except Exception:
                decisions_meta = {}

            project_root = _find_project_root()
            evidence = _grader.gather_evidence(
                project_root=project_root,
                phase=phase_n,
                component_types=component_types,
                decisions_metadata=decisions_meta,
            )
            if mode == "full":
                verdict_obj = _grader.evaluate_full(evidence, use_anthropic=True)
            else:
                verdict_obj = _grader.evaluate_deterministic(evidence)

            verdict_id = None
            if persist:
                verdict_id = await db.add_verdict(**verdict_obj.to_db_kwargs())

            block_marker = "BLOCK" if verdict_obj.should_block else "PASS"
            lines = [
                f"[{block_marker}] Grader fase {phase_n} — quality {verdict_obj.quality}/4",
                f"Issues: {', '.join(verdict_obj.issues) or '(ninguna)'}",
                f"Checks: {json.dumps(verdict_obj.deterministic_checks, ensure_ascii=False)}",
                f"LLM judged: {verdict_obj.llm_judged}",
                f"Razón: {verdict_obj.reasoning}",
            ]
            if verdict_id:
                lines.append(f"Persistido como verdict #{verdict_id}")
            result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_design_md_init":
            project_root = _find_project_root()
            brand = arguments.get("brand_name", "Acme")
            overwrite = bool(arguments.get("overwrite", False))
            path = _design.init_design_md(project_root, brand_name=brand,
                                            overwrite=overwrite)
            existed = path.exists() and not overwrite
            msg = (f"DESIGN.md {'sobrescrito' if overwrite else 'inicializado'} "
                   f"en {path}\nBrand: {brand}\n"
                   f"Próximo: editar valores reales y commitear como prerequisito de fase 2.")
            result = [TextContent(type="text", text=msg)]

        elif name == "apex_design_md_validate":
            project_root = _find_project_root()
            path_arg = arguments.get("path")
            path = Path(path_arg) if path_arg else _design.design_md_path(project_root)
            if not path.exists():
                result = [TextContent(type="text", text=(
                    f"DESIGN.md no existe en {path}. "
                    f"Ejecuta apex_design_md_init primero."))]
            else:
                violations = _design.validate(path.read_text(encoding="utf-8"))
                result = [TextContent(type="text", text=_design.format_violations(violations))]

        elif name == "apex_research_competitor":
            url = arguments["url"]
            prefer_spa = bool(arguments.get("prefer_spa", False))
            signals = _research.summarize_competitor(url, prefer_spa=prefer_spa)
            md = _research.signals_to_markdown(signals)
            result = [TextContent(type="text", text=md)]

        elif name == "apex_browser_trace":
            url = arguments["url"]
            nav_timeout = float(arguments.get("nav_timeout_s", 25))
            settle_ms = int(arguments.get("settle_ms", 1500))
            capture_dom = bool(arguments.get("capture_dom", True))
            save_jsonl = bool(arguments.get("save_jsonl", False))
            use_fallback = bool(arguments.get("use_fallback", True))
            include_dom = bool(arguments.get("include_dom_in_output", False))

            trace = await asyncio.to_thread(
                _browser.trace_url,
                url,
                nav_timeout_s=nav_timeout,
                settle_ms=settle_ms,
                capture_dom=capture_dom,
                use_fallback=use_fallback,
            )

            md = _browser.trace_to_markdown(trace)
            saved_path: Path | None = None
            if save_jsonl:
                project_root = _find_project_root()
                slug = (
                    "".join(c if c.isalnum() else "-" for c in url)
                    .strip("-")[:60]
                    or "trace"
                )
                stamp = trace.started_at or 0
                saved_path = _browser.trace_to_jsonl(
                    trace,
                    project_root / ".apex" / "browser-traces" / f"{slug}-{int(stamp)}.json",
                    include_dom=True,
                )

            sections = [md]
            third = _browser.third_party_domains(trace)
            if third:
                sections.append(
                    "## Dominios externos\n" + "\n".join(f"- {d}" for d in third[:25])
                )
            if saved_path:
                sections.append(f"\n_Trace guardado en {saved_path}_")
            if include_dom and trace.dom_html:
                sections.append("## DOM (outerHTML)\n```html\n" + trace.dom_html[:200_000] + "\n```")
            result = [TextContent(type="text", text="\n\n".join(sections))]

        elif name == "apex_archive_output":
            tool_name = arguments["tool"]
            tool_args = arguments.get("arguments", {})
            output = arguments["output"]
            summary = _tf.summarize_for_context(output)
            aid = await db.archive_output(tool_name, tool_args, output, summary)
            result = [TextContent(type="text", text=(
                f"Archivado #{aid} — {len(output):,} chars completos, "
                f"{len(summary):,} chars en resumen.\n"
                f"Recuperar con apex_get_archived(id={aid}).\n\n"
                f"Resumen:\n{summary}"
            ))]

        elif name == "apex_get_archived":
            aid = arguments.get("id")
            if aid is None:
                tool_filter = arguments.get("tool")
                items = await db.list_archived(limit=20, tool=tool_filter)
                if not items:
                    result = [TextContent(type="text", text="No hay archivos en tool_output_archive.")]
                else:
                    lines = [f"{len(items)} archivo(s):"]
                    for it in items:
                        lines.append(
                            f"  #{it['id']} · {it['tool']} · "
                            f"{it['chars_full']:,} chars (resumen {it['chars_summary']:,}) · "
                            f"{it['created_at']}"
                        )
                    result = [TextContent(type="text", text="\n".join(lines))]
            else:
                rec = await db.get_archived(int(aid))
                if rec is None:
                    result = [TextContent(type="text", text=f"No existe archivo #{aid}.")]
                else:
                    result = [TextContent(type="text", text=(
                        f"Archivo #{rec['id']} ({rec['tool']}, "
                        f"{rec['chars_full']:,} chars, {rec['created_at']}):\n\n"
                        f"{rec['output_full']}"
                    ))]

        elif name == "apex_handoff_write":
            session_id = arguments["session_id"]
            transcript_tokens = int(arguments.get("transcript_tokens", 0))
            project_root = _find_project_root()
            path = await _handoff.serialize_handoff(
                project_root, session_id, db, transcript_tokens=transcript_tokens)
            result = [TextContent(type="text", text=(
                f"Handoff escrito en {path}\n"
                f"Tokens estimados: {transcript_tokens:,}\n"
                f"Para retomar: apex_resume_session(session_id=\"{session_id}\")"
            ))]

        elif name == "apex_resume_session":
            project_root = _find_project_root()
            session_id = arguments.get("session_id")
            if not session_id:
                handoffs = _handoff.list_handoffs(project_root)
                if not handoffs:
                    result = [TextContent(type="text", text=(
                        "No hay handoffs en .apex/handoff/. "
                        "Ejecuta apex_handoff_write(session_id=...) primero."))]
                else:
                    lines = [f"{len(handoffs)} handoff(s) disponible(s):"]
                    for h in handoffs[:10]:
                        lines.append(f"  - {h['session_id']} · "
                                     f"{h['size_bytes']:,} bytes · {h['modified']}")
                    result = [TextContent(type="text", text="\n".join(lines))]
            else:
                content = _handoff.load_handoff(project_root, session_id)
                if content is None:
                    result = [TextContent(type="text", text=(
                        f"No hay handoff para session_id={session_id}. "
                        f"Lista disponibles con apex_resume_session() sin args."))]
                else:
                    result = [TextContent(type="text", text=content)]

        elif name == "apex_goal_loop":
            action = arguments["action"]
            project_root = _find_project_root()
            if action == "start":
                state = _goal.start_goal(
                    project_root,
                    arguments["goal"],
                    turn_budget=int(arguments.get("turn_budget", _goal.DEFAULT_TURN_BUDGET)),
                )
                result = [TextContent(type="text", text=(
                    f"○ Goal set ({state.turn_budget}-turn budget): {state.goal}\n"
                    f"  id: {state.id}"
                ))]
            elif action == "record_turn":
                transcript_path = arguments.get("transcript_path") or None
                threshold_tokens = arguments.get("threshold_tokens")
                state = _goal.record_turn(
                    project_root,
                    arguments["goal_id"],
                    arguments.get("turn_summary", ""),
                    list(arguments.get("tools_used", [])),
                    transcript_path=transcript_path,
                    threshold_tokens=int(threshold_tokens) if threshold_tokens else None,
                )
                msg = (
                    f"Turn {state.turns_used}/{state.turn_budget} recorded — "
                    f"status={state.status}"
                )
                if state.status == _goal.STATUS_CONTEXT_THRESHOLD:
                    sid = arguments.get("session_id") or f"goal_{state.id}"
                    last_entry = state.history[-1] if state.history else {}
                    transcript_tokens = int(last_entry.get("transcript_tokens", 0))
                    threshold_used = int(last_entry.get("threshold_tokens", 0))
                    handoff_path = await _handoff.serialize_handoff(
                        project_root, sid, db,
                        transcript_tokens=transcript_tokens,
                    )
                    msg += (
                        f"\n\n⚠ Umbral de contexto cruzado "
                        f"({transcript_tokens:,} tk ≥ {threshold_used:,} tk).\n"
                        f"Handoff escrito en: {handoff_path}\n"
                        f"Acción del usuario:\n"
                        f"  1. Teclea `/clear` para liberar contexto.\n"
                        f"  2. En la sesión nueva, ejecuta:\n"
                        f"     apex_resume_session(session_id=\"{sid}\")"
                    )
                result = [TextContent(type="text", text=msg)]
            elif action == "judge_prompt":
                state = _goal.load_goal(project_root, arguments["goal_id"])
                prompt = _goal.build_judge_prompt(state)
                result = [TextContent(type="text", text=prompt)]
            elif action == "apply_decision":
                decision = arguments.get("decision") or {"decision": "continue", "reason": "(sin)"}
                state = _goal.apply_judge_decision(project_root, arguments["goal_id"], decision)
                glyph = {"done": "✓", "degenerate": "✗", "active": "↻",
                         "paused": "‖", "budget_exhausted": "⊘"}.get(state.status, "·")
                result = [TextContent(type="text", text=(
                    f"{glyph} status={state.status} ({state.turns_used}/{state.turn_budget}) — "
                    f"{decision.get('reason', '')}"
                ))]
            elif action == "pause":
                state = _goal.pause_goal(project_root, arguments["goal_id"])
                result = [TextContent(type="text", text=(
                    f"‖ Goal paused — {state.turns_used}/{state.turn_budget} turns used"
                ))]
            elif action == "list":
                actives = _goal.list_active_goals(project_root)
                if not actives:
                    result = [TextContent(type="text", text="No hay goals activos.")]
                else:
                    lines = [f"{len(actives)} goal(s) activo(s):"]
                    for s in actives:
                        lines.append(f"  - [{s.id}] {s.turns_used}/{s.turn_budget} — {s.goal[:120]}")
                    result = [TextContent(type="text", text="\n".join(lines))]
            elif action == "load":
                state = _goal.load_goal(project_root, arguments["goal_id"])
                result = [TextContent(type="text", text=state.to_json())]
            else:
                result = [TextContent(type="text", text=f"action desconocida: {action}")]

        elif name == "apex_skill_forge_scan":
            project_root = _find_project_root()
            include_cp = bool(arguments.get("include_cross_project", True))
            hub_path = _HUB_DB if include_cp else None
            project_id = project_root.name
            patterns = _forge.scan_all(project_root, hub_db_path=hub_path,
                                        project_id=project_id)
            written: list[str] = []
            existing: list[str] = []
            rejected: list[str] = []
            db_path = _forge.context_db_path(project_root)
            for pat in patterns:
                slug = pat.slug()
                if _forge.is_rejected(db_path, slug):
                    rejected.append(slug)
                    continue
                prop_path = _forge.proposals_dir(project_root) / f"{slug}.md"
                if prop_path.exists():
                    existing.append(slug)
                    continue
                _forge.write_proposal(_forge.propose(pat), project_root)
                written.append(slug)
            lines = [f"Skill Forge scan — {len(patterns)} patrón(es) detectado(s)"]
            if written:
                lines.append(f"  ○ propuestas nuevas ({len(written)}):")
                lines += [f"    - {s}" for s in written]
            if existing:
                lines.append(f"  · ya propuestos ({len(existing)}):")
                lines += [f"    - {s}" for s in existing]
            if rejected:
                lines.append(f"  ✗ rechazados previamente ({len(rejected)}):")
                lines += [f"    - {s}" for s in rejected]
            if not (written or existing or rejected):
                lines.append("  (sin patrones recurrentes detectados)")
            result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_skill_forge_approve":
            project_root = _find_project_root()
            slug = arguments["slug"]
            skills_root = arguments.get("skills_root", "~/.claude/skills")
            target = _forge.approve(slug, project_root, skills_root=skills_root)
            result = [TextContent(type="text", text=(
                f"○ Skill aprobado: {slug}\n  → {target}"
            ))]

        elif name == "apex_skill_forge_reject":
            project_root = _find_project_root()
            slug = arguments["slug"]
            reason = arguments["reason"]
            _forge.reject(slug, reason, project_root)
            result = [TextContent(type="text", text=(
                f"✗ Skill rechazado: {slug}\n  motivo: {reason}"
            ))]

        elif name == "apex_install_roles":
            agents_root_arg = arguments.get("agents_root") or "~/.claude/agents"
            agents_root = Path(os.path.expanduser(agents_root_arg))
            results = _roles.install_all(
                agents_root=agents_root,
                force=bool(arguments.get("force", False)),
            )
            lines = [f"Roles instalados en {agents_root}:"]
            for role_name, (path, status) in results.items():
                marker = {"written": "○", "skipped": "·", "overwritten": "↻"}.get(
                    status, "?")
                lines.append(f"  {marker} {role_name} [{status}] → {path}")
            lines.append("")
            lines.append(
                "Para invocar: apex_invoke_role(role='apex-architect', "
                "phase=2, context_summary=...). El orquestador dispara el "
                "`Task` tool con el `subagent_type` devuelto."
            )
            result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_recommend_role":
            phase = int(arguments["phase"])
            role = _roles.recommended_for_phase(phase)
            reason = _roles.reason_for_phase(phase)
            installed = (
                _roles.is_installed(role) if role else False
            )
            payload = {
                "phase": phase,
                "phase_name": _roles.PHASE_NAMES.get(phase, "?"),
                "role": role,
                "installed": installed,
                "reason": reason,
            }
            text = (
                f"{reason}\n"
                f"Instalado: {'sí' if installed else 'no'}"
            )
            if role and not installed:
                text += "\n\nEjecuta apex_install_roles() antes de invocarlo."
            text += f"\n\n{json.dumps(payload, ensure_ascii=False)}"
            result = [TextContent(type="text", text=text)]

        elif name == "apex_invoke_role":
            role_name = arguments["role"]
            if role_name not in _roles.ROLES:
                result = [TextContent(type="text", text=(
                    f"Rol desconocido: {role_name}. "
                    f"Disponibles: {', '.join(_roles.list_roles())}"
                ))]
            else:
                phase_arg = arguments.get("phase")
                phase_int = int(phase_arg) if phase_arg is not None else None
                project_root = _find_project_root()
                inv = _roles.build_invocation(
                    role_name,
                    phase=phase_int,
                    context_summary=arguments.get("context_summary", ""),
                    project_name=project_root.name,
                    extra_instructions=arguments.get("extra_instructions", ""),
                )
                # Telemetría
                db_path = project_root / ".apex" / "context.db"
                inv_id = 0
                if db_path.exists():
                    try:
                        inv_id = _roles.record_invocation(
                            db_path,
                            role=role_name,
                            phase=phase_int,
                            session_id=arguments.get("session_id", ""),
                            context_summary=arguments.get("context_summary", "")[:500],
                            status="invoked",
                        )
                    except Exception:
                        inv_id = 0
                installed = _roles.is_installed(role_name)
                lines = [
                    f"Invocación preparada para {role_name} "
                    f"(invocation_id={inv_id})",
                    f"Instalado en ~/.claude/agents/: {'sí' if installed else 'no'}",
                    "",
                    "→ El orquestador (Claude Code main) debe ahora llamar:",
                    "",
                    f"Task(subagent_type=\"{inv['subagent_type']}\",",
                    f"     description=\"{inv['description']}\",",
                    "     prompt=<<<",
                    inv["prompt"],
                    ">>>)",
                ]
                if not installed:
                    lines.append("")
                    lines.append(
                        "AVISO: el agente no está instalado. Ejecuta primero "
                        "apex_install_roles()."
                    )
                result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_doctor_run":
            project_root = _find_project_root()
            run = _doctor.run_doctor(
                project_root,
                trigger=arguments.get("trigger", "manual"),
                force=bool(arguments.get("force", False)),
                hub_db=_HUB_DB if _HUB_DB.exists() else None,
            )
            lines = [_doctor.short_summary(run)]
            if run.status == "throttled":
                lines.append(f"  motivo: {run.skipped_reason}")
                lines.append("  fuerza con: apex_doctor_run(force=True)")
            elif run.status == "done":
                lines.append(
                    f"  inicio: {run.started_at} | fin: {run.finished_at}"
                )
                if run.proposals_count > 0:
                    rel = (
                        Path(".apex") / "doctor" / f"{run.run_id:04d}.md"
                    )
                    lines.append(f"  report: {rel}")
                    by_kind: dict[str, int] = {}
                    for p in run.proposals:
                        by_kind[p.kind] = by_kind.get(p.kind, 0) + 1
                    for kind, count in by_kind.items():
                        lines.append(f"    - {kind}: {count}")
            result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_ingest_library_skills":
            project_root = _find_project_root()
            res = _library.ingest(
                project_root,
                source=arguments.get("source", "both"),
                query=arguments.get("query"),
                min_stars=int(arguments.get("min_stars", _library.GH_MIN_STARS)),
                limit_repos=int(arguments.get("limit_repos",
                                              _library.GH_DEFAULT_LIMIT_REPOS)),
                max_skills_per_repo=int(arguments.get(
                    "max_skills_per_repo",
                    _library.GH_MAX_SKILLS_PER_REPO,
                )),
            )
            if res.written and _HUB_DB.exists():
                try:
                    _library.reset_visit_counter(_HUB_DB)
                except Exception:
                    pass
            lines = [
                f"Library Ingest — fuentes: {', '.join(res.sources_used) or '(ninguna)'}",
                f"  repos GitHub revisados: {res.repos_searched}",
            ]
            if res.written:
                lines.append(f"  ○ propuestas nuevas ({len(res.written)}):")
                lines += [f"    - {s}" for s in res.written]
            if res.already_proposed:
                lines.append(f"  · ya propuestas ({len(res.already_proposed)}):")
                lines += [f"    - {s}" for s in res.already_proposed[:10]]
            if res.already_imported:
                lines.append(f"  · ya importadas, mismo SHA "
                             f"({len(res.already_imported)})")
            if res.rejected:
                lines.append(f"  ✗ rechazadas previamente ({len(res.rejected)})")
            if res.invalid:
                lines.append(f"  ⚠ inválidas ({len(res.invalid)}):")
                for slug, reason in res.invalid[:5]:
                    lines.append(f"    - {slug}: {reason[:140]}")
            if not (res.written or res.already_proposed or res.already_imported
                    or res.rejected or res.invalid):
                lines.append("  (sin candidatas)")
            lines.append("")
            lines.append("Aprobar: apex_skill_forge_approve(slug)")
            lines.append("Rechazar: apex_skill_forge_reject(slug, reason)")
            result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_advisor_review":
            session_id = arguments["session_id"]
            force = bool(arguments.get("force", False))
            trigger = arguments.get("trigger", "manual")
            db_path = str(db.db_path)
            run_, reason = _advisor.should_run(db_path, force=force)
            if not run_:
                result = [TextContent(
                    type="text",
                    text=f"Advisor review SKIPPED: {reason}",
                )]
            else:
                bundle = _advisor.build_bundle(db_path, session_id)
                tokens = _advisor.estimate_bundle_tokens(bundle)
                rid = _advisor.record_review(
                    db_path, session_id, trigger, bundle_size_tokens=tokens,
                )
                lines = [
                    f"advisor_review #{rid} creado · trigger={trigger}",
                    f"  bundle_size_tokens≈{tokens}",
                    f"  reason: {reason}",
                    "",
                    "Próximo paso: invocar el subagent",
                    f"  Task(subagent_type='apex-advisor', prompt='review_id={rid}; "
                    f"session_id={session_id}; ver bundle vía apex_get_context')",
                ]
                if bundle.get("phase"):
                    lines.append(f"  phase actual: {bundle['phase']}")
                if bundle.get("blocking_verdicts"):
                    lines.append(
                        f"  verdicts bloqueantes: {len(bundle['blocking_verdicts'])}"
                    )
                result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_record_advice":
            db_path = str(db.db_path)
            try:
                aid = _advisor.record_advice(
                    db_path,
                    review_id=int(arguments["review_id"]),
                    kind=arguments["kind"],
                    severity=arguments["severity"],
                    title=arguments["title"],
                    body=arguments["body"],
                    evidence_refs=arguments.get("evidence_refs", []),
                )
            except ValueError as e:
                result = [TextContent(type="text", text=f"Validación falló: {e}")]
            else:
                if aid is None:
                    result = [TextContent(
                        type="text",
                        text=(
                            "Card duplicada (mismo review/kind/title) — "
                            "ignorada silenciosamente."
                        ),
                    )]
                else:
                    result = [TextContent(
                        type="text",
                        text=(
                            f"advice #{aid} registrada · kind={arguments['kind']} "
                            f"severity={arguments['severity']}"
                        ),
                    )]

        elif name == "apex_dismiss_advice":
            db_path = str(db.db_path)
            try:
                ok = _advisor.dismiss_advice(
                    db_path,
                    advice_id=int(arguments["advice_id"]),
                    reason=arguments["reason"],
                )
            except ValueError as e:
                result = [TextContent(type="text", text=f"Validación falló: {e}")]
            else:
                if ok:
                    result = [TextContent(
                        type="text",
                        text=f"advice #{arguments['advice_id']} descartada.",
                    )]
                else:
                    result = [TextContent(
                        type="text",
                        text=f"advice #{arguments['advice_id']} no existe.",
                    )]

        elif name == "apex_rate_advice":
            db_path = str(db.db_path)
            try:
                payload = _advisor.rate_advice(
                    db_path,
                    advice_id=int(arguments["advice_id"]),
                    rating=arguments["rating"],
                    reason=arguments["reason"],
                )
            except ValueError as e:
                result = [TextContent(type="text", text=f"Validación falló: {e}")]
            else:
                result = [TextContent(
                    type="text",
                    text=(
                        f"outcome manual #{payload['outcome_id']} registrado "
                        f"para advice #{arguments['advice_id']} "
                        f"({arguments['rating']})."
                    ),
                )]

        elif name == "apex_log_trace":
            db_path = str(db.db_path)
            try:
                tid = _traces.log_trace(
                    db_path,
                    session_id=arguments["session_id"],
                    phase=arguments.get("phase"),
                    category=arguments["category"],
                    gate_kind=arguments["gate_kind"],
                    deliberation=arguments["deliberation"],
                    calibration_confidence=float(arguments["calibration_confidence"]),
                    calibration_text=arguments.get("calibration_text", ""),
                    alternatives_considered=arguments.get("alternatives_considered", []),
                )
            except ValueError as e:
                result = [TextContent(type="text", text=f"Validación falló: {e}")]
            else:
                result = [TextContent(
                    type="text",
                    text=(
                        f"reasoning_trace #{tid} registrada · "
                        f"category={arguments['category']} "
                        f"gate={arguments['gate_kind']}"
                    ),
                )]

        elif name == "apex_handoff_skill":
            db_path = str(db.db_path)
            try:
                hid = _handoff_skill.create_handoff(
                    db_path,
                    session_id=arguments["session_id"],
                    from_skill=arguments["from_skill"],
                    to_skill=arguments["to_skill"],
                    reason=arguments["reason"],
                    snapshot=arguments.get("snapshot", {}),
                )
            except ValueError as e:
                result = [TextContent(type="text", text=f"Validación falló: {e}")]
            else:
                result = [TextContent(
                    type="text",
                    text=(
                        f"skill_handoff #{hid} creado: "
                        f"{arguments['from_skill']} → {arguments['to_skill']}.\n"
                        f"Para volver: apex_resume_skill_handoff(handoff_id={hid}, "
                        f"result_summary='...')"
                    ),
                )]

        elif name == "apex_resume_skill_handoff":
            db_path = str(db.db_path)
            d = _handoff_skill.resume_handoff(
                db_path,
                handoff_id=int(arguments["handoff_id"]),
                result_summary=arguments.get("result_summary", ""),
            )
            if d is None:
                result = [TextContent(
                    type="text",
                    text=f"handoff #{arguments['handoff_id']} no existe.",
                )]
            else:
                lines = [
                    f"skill_handoff #{d['id']} retomado · "
                    f"vuelves a {d['from_skill']}",
                    f"  origen del handoff: {d['from_skill']} → {d['to_skill']}",
                    f"  razón original: {d['reason']}",
                ]
                snap = d.get("snapshot")
                if isinstance(snap, dict) and snap:
                    lines.append(f"  snapshot keys: {list(snap.keys())}")
                result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_prototype_init":
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
                result = [TextContent(
                    type="text", text=f"Validación falló: {e}")]
            else:
                tui_rel = Path(out["tui_path"]).relative_to(root)
                wiki_rel = Path(out["wiki_path"]).relative_to(root)
                result = [TextContent(
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

        elif name == "apex_advisor_compute_outcomes":
            project_path = str(_find_project_root().resolve())
            res = _advisor_outcomes.compute_outcomes(
                str(db.db_path),
                project_path,
                lookback_days=int(arguments.get("lookback_days", 14)),
                force=bool(arguments.get("force", False)),
            )
            lines = [
                "advisor_compute_outcomes:",
                f"  computed:      {res.computed}",
                f"  skipped:       {res.skipped}",
                f"  no_facet_yet:  {res.no_facet_yet}",
                f"  force_updated: {res.force_updated}",
            ]
            if res.no_facet_yet > 0 and res.computed == 0:
                lines.append(
                    "  aviso: ningún facet match. Si nunca corres "
                    "`/insights`, no habrá outcomes implícitos. "
                    "Considera `apex_rate_advice` (S16.6) como escape "
                    "hatch o ejecuta `/insights` periódicamente."
                )
            result = [TextContent(type="text", text="\n".join(lines))]

        elif name == "apex_advisor_health":
            import json as _json
            payload = _advisor_health.advisor_health(
                str(db.db_path),
                window_days=int(arguments.get("window_days", 30)),
            )
            result = [TextContent(
                type="text",
                text=_json.dumps(payload, ensure_ascii=False, indent=2),
            )]

        elif name == "apex_advisor_apply_tuning":
            import json as _json
            payload = _advisor_tuning.apply_tuning(
                str(db.db_path),
                dry_run=bool(arguments.get("dry_run", True)),
                force=bool(arguments.get("force", False)),
            )
            result = [TextContent(
                type="text",
                text=_json.dumps(payload, ensure_ascii=False, indent=2),
            )]

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
