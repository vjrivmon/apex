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


def _find_context_db(start: Path) -> Path | None:
    """Busca .apex/context.db hacia arriba."""
    for parent in [start, *start.parents]:
        candidate = parent / ".apex" / "context.db"
        if candidate.exists():
            return candidate
    return None


def _get_latest_verdict(db_path: Path, phase: int) -> dict | None:
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=2)
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT id, phase, quality, issues, should_block, reasoning "
            "FROM grader_verdicts WHERE phase=? "
            "ORDER BY created_at DESC LIMIT 1",
            (phase,))
        row = cur.fetchone()
        conn.close()
        if not row:
            return None
        return {
            "id": row["id"], "phase": row["phase"], "quality": row["quality"],
            "issues": json.loads(row["issues"] or "[]"),
            "should_block": bool(row["should_block"]),
            "reasoning": row["reasoning"],
        }
    except sqlite3.OperationalError:
        # tabla no existe (proyecto antes de Sprint 8) o BD locked
        return None
    except Exception:
        return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # input inválido: no bloqueamos

    tool_name = payload.get("tool_name") or payload.get("name") or ""
    if tool_name not in TARGET_TOOLS:
        return 0

    args = payload.get("tool_input") or payload.get("arguments") or {}
    if args.get("force"):
        return 0  # override explícito

    phase_number = args.get("phase_number")
    new_status = args.get("status")
    if phase_number is None or new_status is None:
        return 0

    blocking_phase = None
    if new_status == "completed":
        blocking_phase = int(phase_number)
    elif new_status == "in_progress" and int(phase_number) > 0:
        blocking_phase = int(phase_number) - 1
    if blocking_phase is None or blocking_phase < 0:
        return 0

    cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
    db_path = _find_context_db(cwd)
    if not db_path:
        return 0

    verdict = _get_latest_verdict(db_path, blocking_phase)
    if not verdict or not verdict["should_block"]:
        # Sprint 12: si la transición es a in_progress y la nueva fase
        # tiene rol asociado, sugiere invocarlo (no bloqueante).
        if new_status == "in_progress":
            _suggest_role_for_phase(int(phase_number))
        return 0

    # Bloqueo: stderr → usuario, exit 2 → tool no se ejecuta
    issues = ", ".join(verdict["issues"]) or "(ninguna)"
    print(
        "phase-gate.py BLOQUEA apex_set_phase:\n"
        f"  Fase {blocking_phase} tiene verdict #{verdict['id']} con quality {verdict['quality']}/4\n"
        f"  Issues: {issues}\n"
        f"  Razón: {verdict['reasoning']}\n"
        "\n"
        "Resolución: ataca los issues y vuelve a llamar apex_grader_evaluate.\n"
        "Override: pasa force=True con force_reason='...' al apex_set_phase.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
