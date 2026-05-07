#!/usr/bin/env python3
"""APEX Sprint 15 — UserPromptSubmit hook: inyecta advice cards activas.

Lee `advisor_advice` no descartadas asociadas a reviews recientes (<2h) de
la sesión actual y las inyecta como `additionalContext`.

Severidad escala el formato:
  - critical → prepend bloque <system-reminder>BLOQUEANTE</system-reminder>
  - warn → bloque normal
  - info → bloque normal

NO bloquea. Si no hay cards, salida vacía.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "lib"))

try:
    import advisor as _advisor  # type: ignore
except Exception:
    _advisor = None


def _find_project_root(cwd: Path) -> Path | None:
    for parent in [cwd, *cwd.parents]:
        if (parent / ".apex" / "context.db").exists():
            return parent
    return None


def _format_card(card: dict) -> str:
    sev = (card.get("severity") or "info").upper()
    title = card.get("title", "")
    body = card.get("body", "")
    aid = card.get("id", "?")
    kind = card.get("kind", "?")
    return (
        f"- [{sev}] (advice #{aid} · kind={kind}) {title}\n"
        f"  {body}\n"
        f"  Aplicar O dismiss: apex_dismiss_advice({aid}, "
        f"reason='<motivo claro>')"
    )


def main() -> int:
    if _advisor is None:
        return 0
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    cwd = Path(payload.get("cwd") or os.getcwd())
    root = _find_project_root(cwd)
    if root is None:
        return 0
    db_path = root / ".apex" / "context.db"
    if not db_path.exists():
        return 0
    session_id = (
        payload.get("session_id")
        or os.environ.get("APEX_SESSION_ID")
        or "unknown"
    )

    try:
        cards = _advisor.get_active_advice(str(db_path), session_id)
    except Exception:
        return 0
    if not cards:
        return 0

    has_critical = any((c.get("severity") or "") == "critical" for c in cards)
    blocks: list[str] = []
    if has_critical:
        blocks.append(
            "<system-reminder>BLOQUEANTE: hay advice cards CRÍTICAS del "
            "Advisor APEX. Atiéndelas antes de continuar — aplica la "
            "recomendación O llama apex_dismiss_advice con razón "
            "clara.</system-reminder>"
        )
    blocks.append("APEX advisor — cards activas:")
    blocks.extend(_format_card(c) for c in cards)
    additional = "\n".join(blocks)
    out = {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": additional,
        }
    }
    sys.stdout.write(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
