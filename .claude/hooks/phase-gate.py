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
    """Busca .apex/context.db hacia arriba. No trata ~/.apex como proyecto:
    esa es la memoria global de errores graves, no el contexto de nadie
    (bug 2026-07-17)."""
    home = Path.home()
    for parent in [start, *start.parents]:
        if parent == home:
            break
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


def _security_gate_blocks(project_dir: Path) -> tuple[bool, str]:
    """True si .apex/security/ existe pero alguna capa no esta `passed`.

    Stdlib puro (sin yaml): lee el frontmatter y busca la linea `status:`.
    Si el dir no existe, no bloquea (proyecto sin AgentArmor). Fail-open
    ante errores de lectura.
    """
    sec_dir = project_dir / ".apex" / "security"
    if not sec_dir.is_dir():
        # Fail-CLOSED (auditoría 2026-07-03, C3): llegar a fase 11 (deploy)
        # sin evidencia AgentArmor bloquea. Un proyecto que despliega DEBE
        # tener las capas L1-L8. Override con force=True.
        return True, "sin .apex/security/ (scaffold AgentArmor primero)"
    layer_files = sorted(sec_dir.glob("L*-*.md"))
    if not layer_files:
        return True, "sin capas L*-*.md en .apex/security/"
    not_passed = []
    for f in layer_files:
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            not_passed.append(f"{f.stem}(ilegible)")
            continue
        status = "pending"
        if text.startswith("---"):
            try:
                end = text.index("---", 3)
                for line in text[3:end].splitlines():
                    if line.strip().lower().startswith("status:"):
                        status = line.split(":", 1)[1].strip().strip('"\'').lower()
                        break
            except ValueError:
                status = "failed"
        if status != "passed":
            not_passed.append(f"{f.stem.split('-')[0]}({status})")
    if not_passed:
        return True, ", ".join(not_passed)
    return False, ""


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

    # Gate 10.5 (AgentArmor): no entrar a fase 11 (deploy) si alguna capa
    # de seguridad no esta passed. Independiente del gate del grader.
    try:
        _entering_11 = (int(float(phase_number)) == 11
                        and new_status == "in_progress")
    except (TypeError, ValueError):
        _entering_11 = False
    if _entering_11:
        _cwd = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
        _blocks, _detail = _security_gate_blocks(_cwd)
        if _blocks:
            print(
                "phase-gate.py BLOQUEA apex_set_phase (gate de seguridad 10.5):\n"
                f"  Capas no passed: {_detail}\n"
                "\n"
                "Resolucion: completa .apex/security/L*-*.md (status: passed) "
                "y corre apex_security_gate.\n"
                "Override: pasa force=True con force_reason='...'.",
                file=sys.stderr,
            )
            return 2

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

    # Fail-CLOSED (auditoría 2026-07-03, C2): CERRAR una fase (completed) exige
    # un verdict NO bloqueante del grader. Sin verdict → el grader nunca corrió
    # → bloqueamos y lo exigimos. Es la diferencia entre un gate opt-in (el
    # agente decide llamar al grader) y uno vinculante. Las transiciones a
    # in_progress siguen fail-open (solo sugieren rol): el gate muerde al
    # CERRAR, no al abrir.
    if new_status == "completed" and verdict is None:
        print(
            "phase-gate.py BLOQUEA apex_set_phase (grader no ejecutado):\n"
            f"  No hay verdict del grader para la fase {blocking_phase}.\n"
            "  No se puede cerrar una fase sin evaluarla.\n"
            "\n"
            "Resolución: corre apex_grader_evaluate(phase="
            f"{blocking_phase}, ...) y vuelve a intentar.\n"
            "Override: force=True con force_reason='...' (queda registrado).",
            file=sys.stderr,
        )
        return 2

    if verdict is None or not verdict["should_block"]:
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
