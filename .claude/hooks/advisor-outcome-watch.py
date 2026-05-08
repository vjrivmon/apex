#!/usr/bin/env python3
"""UserPromptSubmit hook: cada N prompts ejecuta compute_outcomes +
apply_tuning(dry_run=True) y emite aviso si hay propuestas pendientes.

NO bloquea. Sólo emite stdout (additionalContext) cuando hay propuestas
o cuando el dataset de facets está obsoleto.

Comportamiento:

- Lee/escribe el contador `outcome_watch_prompt_count` en
  `project_meta`. Incrementa en cada UserPromptSubmit.
- Cada `APEX_OUTCOME_WATCH_EVERY_N_PROMPTS` (default 10), ejecuta
  `advisor_outcomes.compute_outcomes(lookback_days=14)` y luego
  `advisor_tuning.apply_tuning(dry_run=True)` con timeout wall-clock
  `APEX_OUTCOME_WATCH_TIMEOUT_S` (default 3.0).
- Si hay proposals, escribe a stdout (formato hooks Claude Code):
  `{"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
    "additionalContext": "..."}}`.
- Si `facets_freshness_days` > 7, sugiere correr `/insights`.

Convención hooks Claude Code (UserPromptSubmit):
- stdin: JSON con prompt + cwd + session_id (a veces).
- stdout JSON: aviso al agente.
- stderr: log informativo, no se inyecta al agente.
- exit 0 siempre (no bloquea).
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "lib"))

try:
    import advisor_outcomes as _outcomes
    import advisor_tuning as _tuning
    import advisor_health as _health
except Exception:
    _outcomes = _tuning = _health = None  # type: ignore


COUNTER_KEY = "outcome_watch_prompt_count"
EVERY_N = int(os.environ.get("APEX_OUTCOME_WATCH_EVERY_N_PROMPTS", "10"))
TIMEOUT_S = float(os.environ.get("APEX_OUTCOME_WATCH_TIMEOUT_S", "3.0"))
LOOKBACK_DAYS = int(os.environ.get("APEX_OUTCOME_WATCH_LOOKBACK_DAYS", "14"))
FRESHNESS_WARN_DAYS = 7


def find_project_root(cwd: Path) -> Path | None:
    for parent in [cwd, *cwd.parents]:
        if (parent / ".apex" / "context.db").exists():
            return parent
    return None


def increment_counter(db_path: Path) -> int:
    """Incrementa el contador y devuelve el nuevo valor."""
    try:
        conn = sqlite3.connect(str(db_path))
    except sqlite3.OperationalError:
        return 0
    try:
        row = conn.execute(
            "SELECT value FROM project_meta WHERE key=?", (COUNTER_KEY,)
        ).fetchone()
        current = int(row[0]) if row and str(row[0]).isdigit() else 0
        new_value = current + 1
        conn.execute(
            "INSERT OR REPLACE INTO project_meta (key, value, updated_at) "
            "VALUES (?, ?, datetime('now'))",
            (COUNTER_KEY, str(new_value)),
        )
        conn.commit()
        return new_value
    finally:
        conn.close()


def should_run(prompt_count: int) -> bool:
    """True si toca correr el ciclo. EVERY_N=0 desactiva el hook."""
    if EVERY_N <= 0:
        return False
    return prompt_count > 0 and prompt_count % EVERY_N == 0


def run_cycle(db_path: Path, project_path: str) -> dict:
    """Ejecuta compute_outcomes + apply_tuning(dry_run=True) y devuelve
    un dict con `proposals` y `facets_freshness_days`."""
    out: dict = {"proposals": [], "facets_freshness_days": None}
    if _outcomes is None or _tuning is None or _health is None:
        return out
    try:
        _outcomes.compute_outcomes(
            str(db_path), project_path, lookback_days=LOOKBACK_DAYS
        )
    except Exception:
        # No bloquea ante errores en compute (BD vieja, facets corruptos).
        pass
    try:
        tuning = _tuning.apply_tuning(str(db_path), dry_run=True)
        out["proposals"] = tuning.get("proposals", [])
    except Exception:
        pass
    try:
        out["facets_freshness_days"] = _health._facets_freshness_days()
    except Exception:
        pass
    return out


def render_advice(cycle: dict) -> str:
    """Texto humano para `additionalContext`. '' si no hay aviso."""
    parts: list[str] = []
    proposals = cycle.get("proposals") or []
    if proposals:
        cats = ", ".join(sorted({p["category"] for p in proposals}))
        parts.append(
            f"[advisor-outcome-watch] {len(proposals)} propuesta(s) de "
            f"tuning pendientes ({cats}). Revisa con `apex_advisor_health()` "
            f"y aplica con `apex_advisor_apply_tuning(dry_run=False)`."
        )
    fresh = cycle.get("facets_freshness_days")
    if fresh is not None and fresh > FRESHNESS_WARN_DAYS:
        parts.append(
            f"[advisor-outcome-watch] facets >{FRESHNESS_WARN_DAYS} días "
            f"({fresh}d). Considera correr `/insights` para alimentar el "
            f"motor de outcomes."
        )
    return "\n".join(parts)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    cwd_raw = payload.get("cwd") or os.getcwd()
    project_root = find_project_root(Path(cwd_raw))
    if project_root is None:
        return 0
    db_path = project_root / ".apex" / "context.db"

    prompt_count = increment_counter(db_path)
    if not should_run(prompt_count):
        return 0

    started = time.monotonic()
    cycle = run_cycle(db_path, str(project_root))
    if (time.monotonic() - started) > TIMEOUT_S:
        # Soft timeout: ya corrió, pero avisamos por stderr para audit.
        sys.stderr.write(
            f"[advisor-outcome-watch] cycle excedió {TIMEOUT_S}s\n"
        )

    advice = render_advice(cycle)
    if advice:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": advice,
            }
        }
        sys.stdout.write(json.dumps(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # Última defensa: nunca bloquear.
        sys.stderr.write(f"[advisor-outcome-watch] error: {e}\n")
        sys.exit(0)
