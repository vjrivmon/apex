"""APEX Sprint 16.4 — Auto-tuner de constantes del Advisor.

Heurística determinista (§5 del blueprint S16):

| Categoría                | Constante                    | Old → New |
|--------------------------|------------------------------|-----------|
| `forgotten_tool`         | `default_interval`           | 8 → 12    |
| `phase_drift`            | `phase_drift_window_min`     | 30 → 45   |
| `recommend_skill_handoff`| `complexity_score_threshold` | 0.6 → 0.75|
| `grader_overdue`         | `grader_overdue_phases`      | 2 → 3     |

Reglas:
- Mínimo 20 outcomes (useful + not_useful, sin contar `unclear`) por
  categoría antes de proponer.
- `not_useful_rate = not_useful / (useful + not_useful)`. Si >40%,
  propone tune.
- Cooldown 7 días por constante (anti-oscilación). Bloquea proposals
  hasta que el cooldown expira.
- `force=True` salta el cooldown y registra `source='manual_override'`
  en `advisor_tuning_history`.
- `dry_run=True` (default) devuelve propuestas sin escribir.
- `dry_run=False` UPDATE `project_meta.advisor_constants` y registra
  fila en `advisor_tuning_history`.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from lib.db_utils import get_sync_db

import advisor


MIN_OUTCOMES_TO_TUNE = 20
NOT_USEFUL_RATE_THRESHOLD = 0.40
COOLDOWN_DAYS = 7

# (categoría, constante a tunear, nuevo valor)
TUNING_RULES: dict[str, tuple[str, int | float]] = {
    "forgotten_tool":          ("default_interval",           12),
    "phase_drift":             ("phase_drift_window_min",     45),
    "recommend_skill_handoff": ("complexity_score_threshold", 0.75),
    "grader_overdue":          ("grader_overdue_phases",      3),
}


def _outcome_counts_by_kind(c: sqlite3.Connection) -> dict[str, dict[str, int]]:
    """Suma counts de useful + not_useful por kind (temporal + manual)."""
    cur = c.execute(
        """
        SELECT a.kind, o.inferred_rating, COUNT(*) AS n
        FROM advice_outcomes o
        JOIN advisor_advice a ON a.id = o.advice_id
        WHERE o.inferred_rating IN ('useful', 'not_useful')
        GROUP BY a.kind, o.inferred_rating
        """
    )
    out: dict[str, dict[str, int]] = {}
    for row in cur.fetchall():
        kind, rating, n = row[0], row[1], int(row[2])
        out.setdefault(kind, {"useful": 0, "not_useful": 0})[rating] = n
    return out


def _is_constant_in_cooldown(c: sqlite3.Connection, constant_name: str) -> bool:
    cur = c.execute(
        "SELECT 1 FROM advisor_tuning_history "
        "WHERE constant_name=? "
        "  AND applied_at >= datetime('now', ?) "
        "LIMIT 1",
        (constant_name, f"-{COOLDOWN_DAYS} days"),
    )
    return cur.fetchone() is not None


def apply_tuning(
    db_path: str | Path,
    dry_run: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    """Genera y opcionalmente aplica las propuestas de auto-tuning.

    Returns:
        {
            'proposals': [{category, constant, old, new, fp_rate,
                          n_outcomes, reason}],
            'cooldown_blocked': [constant_name, ...],
            'applied': N (solo si dry_run=False),
        }
    """
    db_path = str(db_path)
    proposals: list[dict[str, Any]] = []
    cooldown_blocked: list[str] = []

    with get_sync_db(db_path) as c:
        counts = _outcome_counts_by_kind(c)
        constants_now = advisor.get_advisor_constants(db_path)

        for category, (constant_name, new_value) in TUNING_RULES.items():
            kind_counts = counts.get(category, {"useful": 0, "not_useful": 0})
            useful = kind_counts["useful"]
            not_useful = kind_counts["not_useful"]
            total = useful + not_useful
            if total < MIN_OUTCOMES_TO_TUNE:
                continue
            fp_rate = not_useful / total
            if fp_rate <= NOT_USEFUL_RATE_THRESHOLD:
                continue
            old_value = constants_now.get(constant_name)
            if old_value is None:
                continue
            if old_value == new_value:
                # Ya está al nivel propuesto — nada que tunear.
                continue
            if not force and _is_constant_in_cooldown(c, constant_name):
                cooldown_blocked.append(constant_name)
                continue
            proposals.append({
                "category": category,
                "constant": constant_name,
                "old": old_value,
                "new": new_value,
                "fp_rate": round(fp_rate, 4),
                "n_outcomes": total,
                "reason": (
                    f"fp_rate {round(fp_rate * 100, 1)}% "
                    f">{int(NOT_USEFUL_RATE_THRESHOLD * 100)}% sobre "
                    f"{total} outcomes (≥{MIN_OUTCOMES_TO_TUNE})"
                ),
            })

    out: dict[str, Any] = {
        "proposals": proposals,
        "cooldown_blocked": cooldown_blocked,
    }
    if dry_run:
        return out

    if not proposals:
        out["applied"] = 0
        return out

    # Aplicar: actualiza constants y registra history
    new_constants = dict(constants_now)
    for p in proposals:
        new_constants[p["constant"]] = p["new"]
    advisor.set_advisor_constants(db_path, new_constants)
    source = "manual_override" if force else "auto"
    with get_sync_db(db_path) as c:
        for p in proposals:
            c.execute(
                "INSERT INTO advisor_tuning_history "
                "(category, constant_name, old_value, new_value, "
                " trigger_n_outcomes, fp_rate_before, source, reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    p["category"],
                    p["constant"],
                    float(p["old"]),
                    float(p["new"]),
                    int(p["n_outcomes"]),
                    float(p["fp_rate"]),
                    source,
                    p["reason"],
                ),
            )
        c.commit()
    out["applied"] = len(proposals)
    return out
