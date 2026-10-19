"""APEX MCP handler: context."""
from __future__ import annotations

# Imports que el refactor a handlers dejó fuera al cortar del monolito.
import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / 'lib'))
from mcp.types import TextContent
from apex_handlers._common import db_exists as _db_exists
from apex_handlers._common import find_project_root as _find_project_root
from apex_handlers._common import sync_to_obsidian as _sync_to_obsidian
from apex_handlers._common import vault_project_id as _vault_project_id
from security_gate import GITLEAKS_MARKERS as _GITLEAKS_MARKERS
from security_gate import SECURITY_GATE_PHASE as _SECURITY_GATE_PHASE
from security_gate import _check_gitleaks_configured as _check_gitleaks_configured
from wiki_scaffold import create_wiki
from typing import Any
import platform


# Fases cuyo veredicto hay que consultar, además del de la fase previa.
#
# El gate 10.5 (AgentArmor) no lo produce `apex_grader_evaluate` sino
# `apex_security_gate`, que hasta el 2026-10-19 solo redactaba un informe.
# Sin veredicto, entrar en la fase 11 se colaba sin revisión de seguridad.
GATE_PHASE = _SECURITY_GATE_PHASE
DEPLOY_PHASE = 11

# Fases cuyo veredicto es OBLIGATORIO: sin veredicto, la transición se
# frena. El gate 10.5 es fail-closed —si no se ha ejecutado, no hay evidencia
# de que la seguridad esté revisada—. La fase 10 mantiene la semántica del
# grader: sin veredicto, deja pasar (comportamiento previo, intacto).
_FASES_FAIL_CLOSED = {GATE_PHASE}

# Fase que exige gitleaks configurado (Gap F, blueprint S19.1c).
_FASE_GITLEAKS = 10


def _fases_del_veredicto(phase_n, new_status: str) -> list:
    """Fases cuyo veredicto hay que leer para permitir esta transición.

    Antes era un único `blocking_phase`. Con el gate 10.5 son varias: entrar
    en la fase 11 exige el veredicto de la fase 10 Y el del gate 10.5.
    """
    if new_status == "completed":
        fases = [phase_n]
    elif new_status == "in_progress":
        fases = [phase_n - 1]
    else:
        fases = []
    if phase_n == DEPLOY_PHASE and GATE_PHASE not in fases:
        fases.append(GATE_PHASE)
    return fases


async def handle_apex_init_project(db: Any, arguments: dict) -> Any:
    """Handler for apex_init_project."""
    root = _find_project_root()
    await db.initialize()
    await db.set_meta("nombre", arguments["name"])
    if arguments.get("description"):
        await db.set_meta("descripción", arguments["description"])
    if arguments.get("solution_type"):
        await db.set_meta("tipo_solución", arguments["solution_type"])
    # El grader exige `detected_os` desde la fase 1. Lo sabe el propio
    # servidor, que corre en la máquina del usuario: no depende del agente.
    await db.set_meta("detected_os", platform.system())
    # Crear wiki scaffold
    domain = arguments.get("domain", "")
    wiki_dir = create_wiki(str(root), arguments["name"], domain)
    return [TextContent(type="text", text=f"Proyecto inicializado en {root}/.apex/\n- context.db creada con 15 fases\n- Wiki scaffold en {wiki_dir}")]

async def handle_apex_get_context(db: Any, arguments: dict) -> Any:
    """Handler for apex_get_context."""
    level = arguments.get("level", "timeline")
    if not (await _db_exists(db)):
        return [TextContent(type="text", text="No se encontró .apex/context.db en este proyecto. Usa apex_init_project primero.")]
    else:
        ctx = await db.get_context(level)
        return [TextContent(type="text", text=ctx)]


async def handle_apex_set_phase(db: Any, arguments: dict) -> Any:
    """Handler for apex_set_phase."""
    phase_n = arguments["phase_number"]
    new_status = arguments["status"]
    force = bool(arguments.get("force", False))
    force_reason = arguments.get("force_reason", "")

    # Sprint 8 + auditoría 2026-10-19: consultar los verdicts que aplican a
    # esta transición. Puede ser más de uno: la entrada en la fase 11 exige
    # el de la fase 10 y el del gate 10.5.
    fases = [f for f in _fases_del_veredicto(phase_n, new_status)
             if f is not None and f >= 0]
    veredictos: list[tuple] = []
    bloqueos: list[tuple] = []
    for f in fases:
        verdict = await db.get_latest_verdict(f)
        if verdict is None:
            if f in _FASES_FAIL_CLOSED:
                bloqueos.append((f, None))
            continue
        veredictos.append((f, verdict))
        if verdict.get("should_block"):
            bloqueos.append((f, verdict))

    # Gap F (S19.1c): la fase 10 (seguridad) exige gitleaks configurado.
    falta_gitleaks = (
        phase_n == _FASE_GITLEAKS
        and new_status in ("in_progress", "completed")
        and not _check_gitleaks_configured(_find_project_root())
    )

    if bloqueos or falta_gitleaks:
        if not force:
            msg_lines = []
            for f, verdict in bloqueos:
                if verdict is None:
                    msg_lines += [
                        f"BLOQUEADO por el gate de seguridad (fase {f}): no hay veredicto.",
                        "  El gate 10.5 es fail-closed: sin veredicto no se pasa.",
                        "  Ejecuta apex_security_gate para evaluar las 8 capas AgentArmor.",
                    ]
                else:
                    msg_lines += [
                        f"BLOQUEADO por grader (verdict #{verdict['id']} de fase {f}):",
                        f"  Quality: {verdict['quality']}/4",
                        f"  Issues: {', '.join(verdict['issues']) or '(ninguna)'}",
                        f"  Razón: {verdict['reasoning']}",
                    ]
            if falta_gitleaks:
                marcadores = ", ".join(str(m) for m in _GITLEAKS_MARKERS)
                msg_lines += [
                    "BLOQUEADO: gitleaks no está configurado en el proyecto.",
                    f"  Se esperaba uno de: {marcadores}",
                    f"  (raíz del proyecto: {_find_project_root()})",
                    "  La fase 10 (seguridad) exige detección automática de secretos.",
                    "  Solución: ejecuta apex_scaffold_devops para instalar el hook,",
                    "  o configura .gitleaks.toml a mano.",
                ]
            msg_lines += [
                "",
                "Para bypassear: apex_set_phase(..., force=True, force_reason='...')",
                "Para resolver: ataca los issues y vuelve a llamar apex_grader_evaluate.",
            ]
            return [TextContent(type="text", text="\n".join(msg_lines))]

        # Override explícito: queda registrado como error, igual que antes.
        for f, verdict in bloqueos:
            if verdict is None:
                descripcion = f"Override del gate de seguridad sin veredicto en fase {f}"
            else:
                descripcion = f"Override de bloqueo del grader en fase {f}"
            await db.add_error(
                source="claude",
                description=descripcion,
                lesson=force_reason or "(sin razón documentada)",
                phase=f,
                severity="high",
            )
        if falta_gitleaks:
            await db.add_error(
                source="claude",
                description=f"Override del gate de gitleaks en la fase {_FASE_GITLEAKS}",
                lesson=force_reason or "(sin razón documentada)",
                phase=_FASE_GITLEAKS,
                severity="high",
            )

    await db.set_phase(phase_n, new_status, arguments.get("notes", ""))
    _project = _vault_project_id(db.db_path)
    _sync_to_obsidian("phase", {
        "project": _project, "phase": phase_n,
        "status": new_status, "notes": arguments.get("notes", ""),
    })
    msg = f"Fase {phase_n} → {new_status}"
    for f, verdict in veredictos:
        etiqueta = "gate 10.5" if f == GATE_PHASE else "grader"
        msg += f" ({etiqueta}: quality {verdict['quality']}/4)"
    return [TextContent(type="text", text=msg)]


async def handle_apex_search(db: Any, arguments: dict) -> Any:
    """Handler for apex_search."""
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
        return [TextContent(type="text", text=f"Sin resultados para '{arguments['query']}' (mode={mode})")]
    lines = [f"Resultados para '{arguments['query']}' (mode={mode}):"]
    for r in results:
        lines.append(formatter(r))
    return [TextContent(type="text", text="\n".join(lines))]

async def handle_apex_log_session(db: Any, arguments: dict) -> Any:
    """Handler for apex_log_session."""
    await db.log_session(
        arguments["summary"], key_outcomes=arguments.get("key_outcomes", ""),
        phase=arguments.get("phase"))
    _project = _vault_project_id(db.db_path)
    _sync_to_obsidian("session", {"project": _project, "summary": arguments["summary"]})
    return [TextContent(type="text", text=f"Sesión registrada: {arguments['summary'][:80]}")]

