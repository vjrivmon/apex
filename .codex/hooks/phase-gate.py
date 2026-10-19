#!/usr/bin/env python3
"""PreToolUse hook: bloquea apex_set_phase si el último verdict del grader
para la fase a cerrar tiene should_block=True (Sprint 8.1).

El handler MCP también valida — este hook es la red de seguridad ANTES de
que el MCP reciba la llamada. Reduce dependencia del servidor MCP y deja
el bloqueo explícito en el log de la sesión.

Override: argumento force=True bypasea el bloqueo (también registrado por
el handler MCP como apex_add_error de severidad alta).

Convención hooks (Claude Code):
- Lee JSON desde stdin con tool_name + tool_input
- exit 0 → permite
- exit 2 → bloquea (stderr se muestra al usuario)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

# La raíz del repo debe estar en sys.path ANTES de `from lib.…`:
# el hook puede ejecutarse desde cualquier cwd.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lib.project_root import project_db_path as _project_db_path
from lib.hook_metrics import start_hook, end_hook

TARGET_TOOLS = {
    "mcp__apex__apex_set_phase",
    "apex_set_phase",
}


_PHASE_ROLE_MAP = {
    2: "apex-architect", 3: "apex-architect",
    4: "apex-qa",
    5: "apex-implementer", 6: "apex-implementer", 7: "apex-implementer",
    8: "apex-reviewer",
    9: "apex-qa",
    10: "apex-reviewer",
    11: "apex-devops",
}


def _suggest_role_for_phase(phase: int) -> None:
    """Imprime sugerencia a stderr si la fase tiene rol asociado.

    No bloquea (exit 0 lo controla el caller). Falla silenciosa si stderr
    no está disponible.
    """
    role = _PHASE_ROLE_MAP.get(phase)
    if not role:
        return
    try:
        print(
            f"[phase-gate] Fase {phase} recomienda invocar el rol {role}.\n"
            f"  → apex_invoke_role(role='{role}', phase={phase}, "
            "context_summary='...')\n"
            "  → Después: dispara `Task` con el subagent_type devuelto.\n"
            "  Si los agentes no están instalados: apex_install_roles().",
            file=sys.stderr,
        )
    except Exception:
        pass


# La base del proyecto la resuelve lib/project_root.py, la implementacion
# UNICA. Antes cada hook traia su propia copia; la de Codex ni siquiera
# cortaba en el home, asi que desde el home resolvia ~/.apex/context.db
# (la memoria global de errores graves) como si fuera el contexto del
# proyecto.
def _find_context_db(start: Path) -> Path | None:
    """Busca .apex/context.db hacia arriba. Nunca devuelve la global."""
    return _project_db_path(start)


class VerdictIlegible(Exception):
    """No se pudo determinar si hay bloqueo: la BD no se dejó consultar.

    Es distinto de "no hay verdict". Colapsar ambos casos en None hacía que
    una BD bloqueada o una fila corrupta dejaran pasar la transición en
    silencio — un fail-open en el único punto que debía frenar.
    """


def _issues_validas(bruto) -> list[str]:
    """`issues` debe ser una lista de cadenas.

    json.loads solo valida sintaxis: `'[1]'` parsea bien y luego revienta en
    el `", ".join(...)` del mensaje de bloqueo, fuera de todo manejo. Una
    fila con forma inesperada es una BD que no se entiende, no un permiso.
    """
    try:
        valor = json.loads(bruto or "[]")
    except json.JSONDecodeError as e:
        raise VerdictIlegible(f"columna issues corrupta: {e}") from e
    if not isinstance(valor, list) or not all(isinstance(i, str) for i in valor):
        raise VerdictIlegible(f"columna issues con forma inesperada: {valor!r}")
    return valor


def _bloqueo_valido(bruto) -> bool:
    """`should_block` debe ser 0 o 1.

    El esquema no lo restringe, y `bool(...)` convertiría NULL en False
    (silenciando un bloqueo) y la cadena "0" en True (inventando uno).
    """
    if bruto in (0, 1):
        return bool(bruto)
    raise VerdictIlegible(f"should_block con valor inesperado: {bruto!r}")


def _get_latest_verdict(db_path: Path, phase: int) -> dict | None:
    """Último verdict de la fase, o None si no hay ninguno.

    Lanza `VerdictIlegible` si la BD existe pero no se pudo leer. La tabla
    ausente NO es error: los proyectos anteriores al Sprint 8 no la tienen.
    """
    conn = None
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, phase, quality, issues, should_block, reasoning "
            "FROM grader_verdicts WHERE phase=? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (phase,)).fetchone()
        if not row:
            return None
        return {
            "id": row["id"], "phase": row["phase"], "quality": row["quality"],
            "issues": _issues_validas(row["issues"]),
            "should_block": _bloqueo_valido(row["should_block"]),
            "reasoning": row["reasoning"],
        }
    except sqlite3.OperationalError as e:
        # Solo la tabla ausente es "no hay nada que evaluar" (proyecto
        # pre-Sprint 8). Se exige el nombre para no silenciar un esquema roto
        # por otra tabla o vista que falte.
        if "no such table: grader_verdicts" in str(e).lower():
            return None
        raise VerdictIlegible(f"BD ilegible: {e}") from e
    except VerdictIlegible:
        raise
    except Exception as e:  # noqa: BLE001 — se reporta, no se traga
        raise VerdictIlegible(f"{type(e).__name__}: {e}") from e
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — cerrar es best-effort
                pass


def _fases_a_comprobar(phase_number, new_status: str) -> list[int]:
    """Fases cuyo veredicto hay que leer para esta transición.

    Refleja la MISMA regla que el handler MCP
    (`mcp/handlers/context.py::_fases_del_veredicto`): entrar en la fase 11
    exige el veredicto de la fase 10 Y el del gate de seguridad 10.5.

    El hook sólo frena si algún veredicto dice "bloquea". La AUSENCIA de
    veredicto la resuelve el handler MCP (que es fail-closed para el 10.5):
    el hook no bloquea de más, pero tampoco deja pasar un bloqueo.
    """
    try:
        phase_n = int(phase_number)
    except (TypeError, ValueError):
        return []
    fases: list[int] = []
    if new_status == "completed":
        fases = [phase_n]
    elif new_status == "in_progress" and phase_n > 0:
        fases = [phase_n - 1]
    else:
        return []
    if phase_n == 11 and 10.5 not in fases:
        fases.append(10.5)
    return [f for f in fases if f is not None and f >= 0]


def main() -> int:
    _hook_start = start_hook("phase-gate")
    try:
        payload = json.load(sys.stdin)
    except Exception:
        end_hook("phase-gate", _hook_start, exit_code=0)
        return 0  # input inválido: no bloqueamos

    tool_name = payload.get("tool_name") or payload.get("name") or ""
    if tool_name not in TARGET_TOOLS:
        end_hook("phase-gate", _hook_start, exit_code=0)
        return 0

    args = payload.get("tool_input") or payload.get("arguments") or {}
    if args.get("force"):
        end_hook("phase-gate", _hook_start, exit_code=0)
        return 0  # override explícito

    phase_number = args.get("phase_number")
    new_status = args.get("status")
    if phase_number is None or new_status is None:
        end_hook("phase-gate", _hook_start, exit_code=0)
        return 0

    blocking_phases = _fases_a_comprobar(phase_number, new_status)
    if not blocking_phases:
        end_hook("phase-gate", _hook_start, exit_code=0)
        return 0

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    db_path = _find_context_db(cwd)
    if not db_path:
        end_hook("phase-gate", _hook_start, exit_code=0)
        return 0

    for blocking_phase in blocking_phases:
        try:
            verdict = _get_latest_verdict(db_path, blocking_phase)
        except VerdictIlegible as e:
            # No se sabe si hay bloqueo. Se avisa en voz alta y se deja pasar:
            # bloquear por una BD momentáneamente locked dejaría la sesión
            # atascada sin causa real. Lo que no se hace es callar.
            print(
                f"[phase-gate] AVISO: no se pudo comprobar el grader de la fase "
                f"{blocking_phase}.\n"
                f"  Motivo: {e}\n"
                f"  BD: {db_path}\n"
                "  El hook deja pasar porque el fallo es de lectura, no un "
                "veredicto negativo.\n"
                "  Aviso: el handler MCP consulta la MISMA BD antes de escribir, "
                "y lo hace\n"
                "  antes de mirar force, así que es probable que apex_set_phase "
                "falle igual.\n"
                "  Arregla la BD (revisa locks y permisos de "
                ".apex/context.db) y reevalúa.",
                file=sys.stderr,
            )
            end_hook("phase-gate", _hook_start, exit_code=0)
            return 0

        if not verdict or not verdict["should_block"]:
            continue

        # Bloqueo: stderr → usuario, exit 2 → tool no se ejecuta
        issues = ", ".join(verdict["issues"]) or "(ninguna)"
        etiqueta = ("gate de seguridad 10.5" if blocking_phase == 10.5
                    else f"fase {blocking_phase}")
        print(
            "phase-gate.py BLOQUEA apex_set_phase:\n"
            f"  {etiqueta} tiene verdict #{verdict['id']} con quality "
            f"{verdict['quality']}/4\n"
            f"  Issues: {issues}\n"
            f"  Razón: {verdict['reasoning']}\n"
            "\n"
            "Resolución: ataca los issues y vuelve a llamar apex_grader_evaluate.\n"
            "Override: pasa force=True con force_reason='...' al apex_set_phase.",
            file=sys.stderr,
        )
        end_hook("phase-gate", _hook_start, exit_code=2)
        return 2

    # Ninguna de las fases bloquea.
    if new_status == "in_progress":
        # Sprint 12: si la transición es a in_progress y la nueva fase
        # tiene rol asociado, sugiere invocarlo (no bloqueante).
        _suggest_role_for_phase(int(phase_number))
    end_hook("phase-gate", _hook_start, exit_code=0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
