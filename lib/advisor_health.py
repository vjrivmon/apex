"""APEX Sprint 16.3 — Advisor health dashboard.

Construye un snapshot JSON-friendly del estado del Advisor para
dogfooding y para que `apex_advisor_apply_tuning` (S16.4) o el hook
`advisor-outcome-watch.py` (S16.7) puedan tomar decisiones.

Métricas:
- `total_advice_emitted[kind]`: cuenta de cards por categoría.
- `outcomes_computed[kind][assoc_method][rating]`: matriz de outcomes.
- `fp_rate[kind]`: ratio not_useful/(useful+not_useful) o None si
  count(not_useful) < `FP_RATE_MIN_NEGATIVES` (5).
- `constants_actuales[name]`: {value, source: 'default' | 'tuned'}.
- `tuning_history`: últimos 5 entries de `advisor_tuning_history`.
- `circuit_breaker_trips_24h`: nº de reviews
  `trigger_kind='circuit_breaker_reset'` últimas 24h.
- `facets_freshness_days`: días desde el archivo más reciente en
  `~/.claude/usage-data/facets/`. None si no existe el dir.

No expone texto libre — solo enums y números (privacidad).
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from lib.db_utils import get_sync_db

import advisor

try:
    import usage_data_reader as _udr  # noqa
except ImportError:  # pragma: no cover
    _udr = None


FP_RATE_MIN_NEGATIVES = 5
TUNING_HISTORY_LIMIT = 5
FRESHNESS_WARN_DAYS = 7  # caller decide qué hacer; aquí solo informa


def _outcomes_window_clause(window_days: int) -> str:
    return f"computed_at >= datetime('now', '-{int(window_days)} days')"


def advisor_health(
    db_path: str | Path,
    window_days: int = 30,
) -> dict[str, Any]:
    db_path = str(db_path)
    out: dict[str, Any] = {
        "total_advice_emitted": {},
        "outcomes_computed": {},
        "fp_rate": {},
        "constants_actuales": {},
        "tuning_history": [],
        "circuit_breaker_trips_24h": 0,
        "facets_freshness_days": None,
        "window_days": window_days,
    }
    with get_sync_db(db_path) as c:
        c.row_factory = sqlite3.Row

        # 1. Totales por kind
        cur = c.execute(
            "SELECT kind, COUNT(*) AS n FROM advisor_advice GROUP BY kind"
        )
        out["total_advice_emitted"] = {r["kind"]: r["n"] for r in cur.fetchall()}

        # 2. Outcomes por kind × assoc_method × rating en ventana
        cur = c.execute(
            f"""
            SELECT a.kind, o.assoc_method, o.inferred_rating, COUNT(*) AS n
            FROM advice_outcomes o
            JOIN advisor_advice a ON a.id = o.advice_id
            WHERE {_outcomes_window_clause(window_days)}
            GROUP BY a.kind, o.assoc_method, o.inferred_rating
            """
        )
        oc: dict[str, dict[str, dict[str, int]]] = {}
        for r in cur.fetchall():
            kind = r["kind"]
            method = r["assoc_method"]
            rating = r["inferred_rating"]
            kind_block = oc.setdefault(
                kind,
                {
                    "temporal": {"useful": 0, "not_useful": 0, "unclear": 0},
                    "manual": {"useful": 0, "not_useful": 0, "unclear": 0},
                },
            )
            kind_block[method][rating] = r["n"]
        out["outcomes_computed"] = oc

        # 3. fp_rate por kind (None si <5 not_useful)
        for kind, block in oc.items():
            useful = block["temporal"]["useful"] + block["manual"]["useful"]
            not_useful = (
                block["temporal"]["not_useful"] + block["manual"]["not_useful"]
            )
            if not_useful < FP_RATE_MIN_NEGATIVES:
                out["fp_rate"][kind] = None
                continue
            denom = useful + not_useful
            out["fp_rate"][kind] = round(not_useful / denom, 4) if denom else None

        # 4. Constantes actuales (defaults vs tuned)
        constants_now = advisor.get_advisor_constants(db_path)
        defaults = advisor.ADVISOR_CONSTANT_DEFAULTS
        last_tune_by_constant: dict[str, str] = {}
        cur = c.execute(
            "SELECT constant_name, MAX(applied_at) AS last "
            "FROM advisor_tuning_history GROUP BY constant_name"
        )
        for r in cur.fetchall():
            last_tune_by_constant[r["constant_name"]] = r["last"]
        for name, value in constants_now.items():
            default_value = defaults.get(name, value)
            source = "tuned" if value != default_value else "default"
            out["constants_actuales"][name] = {
                "value": value,
                "source": source,
                "last_tuned_at": last_tune_by_constant.get(name),
            }

        # 5. Tuning history últimos 5
        cur = c.execute(
            "SELECT applied_at, category, constant_name, old_value, new_value, "
            "       trigger_n_outcomes, fp_rate_before, source, reason "
            "FROM advisor_tuning_history "
            "ORDER BY applied_at DESC LIMIT ?",
            (TUNING_HISTORY_LIMIT,),
        )
        out["tuning_history"] = [dict(r) for r in cur.fetchall()]

        # 6. Circuit breaker trips últimas 24h
        cur = c.execute(
            "SELECT COUNT(*) AS n FROM advisor_reviews "
            "WHERE trigger_kind='circuit_breaker_reset' "
            "  AND triggered_at >= datetime('now', '-1 day')"
        )
        row = cur.fetchone()
        out["circuit_breaker_trips_24h"] = int(row["n"]) if row else 0

    # 7. Facets freshness (filesystem, no BD)
    out["facets_freshness_days"] = _facets_freshness_days()
    out["facets_warn_threshold_days"] = FRESHNESS_WARN_DAYS
    return out


def _facets_freshness_days() -> int | None:
    """Días desde el archivo .json más reciente en facets/. None si no
    existe el dir o está vacío."""
    if _udr is None:  # pragma: no cover
        return None
    facets_dir = _udr.usage_data_root() / "facets"
    if not facets_dir.is_dir():
        return None
    newest_mtime = 0.0
    for entry in facets_dir.iterdir():
        if entry.is_file() and entry.suffix == ".json":
            try:
                mt = entry.stat().st_mtime
            except OSError:  # pragma: no cover
                continue
            if mt > newest_mtime:
                newest_mtime = mt
    if newest_mtime == 0.0:
        return None
    age_seconds = time.time() - newest_mtime
    return max(0, int(age_seconds // 86400))
