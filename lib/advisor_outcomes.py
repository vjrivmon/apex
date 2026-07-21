"""APEX Sprint 16.2 — motor implícito de outcomes para el Advisor.

Cruza `advisor_advice` con `~/.claude/usage-data/facets/` (Sprint 13.9)
vía heurística temporal y deja una fila en `advice_outcomes` con
`assoc_method='temporal'` por advice. La fila contiene los enums del
facet (outcome, helpfulness, satisfaction, friction_keys con count>0)
más un `inferred_rating ∈ {useful, not_useful, unclear}` derivado por
`infer_rating()` siguiendo la heurística §3 del blueprint S16.

Diseño:

- **Sin texto libre**: solo enums del facet llegan a `context.db` para
  preservar privacidad de briefs/código (§10 R5).
- **Idempotente**: `UNIQUE (advice_id, assoc_method)` en el schema y
  filtrado previo evitan duplicados; `force=True` actualiza la fila ya
  existente.
- **Causalidad débil aceptada**: el facet evalúa la sesión completa,
  no la card específica. El auto-tuning (S16.4) solo decide a nivel
  agregado N>=20 — el ruido individual se cancela.
- **Best-effort**: si `~/.claude/usage-data/` no existe (Claude Code
  nunca corrió `/insights`), `iter_*` devuelve vacío y todos los
  advices terminan en `no_facet_yet` sin error.

Invocadores: tool MCP `apex_advisor_compute_outcomes` (manual o vía
hook `advisor-outcome-watch.py` cada 10 prompts en S16.7).
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from lib.db_utils import get_sync_db

import usage_data_reader as udr


# ── Conjuntos de enums (heurística §3 del blueprint) ─────────────────

NOT_USEFUL_OUTCOMES: frozenset[str] = frozenset({
    "not_achieved", "partially_achieved",
})
NOT_USEFUL_HELPFULNESS: frozenset[str] = frozenset({
    "unhelpful", "slightly_helpful",
})
NOT_USEFUL_SATISFACTION: frozenset[str] = frozenset({
    "dissatisfied", "frustrated",
})

USEFUL_OUTCOMES: frozenset[str] = frozenset({
    "fully_achieved", "mostly_achieved",
})
USEFUL_HELPFULNESS: frozenset[str] = frozenset({
    "very_helpful", "essential", "moderately_helpful",
})

# Slack para asociación temporal advice ↔ sesión (consistente con A5).
ASSOC_SLACK_MINUTES = 5


# ── Resultado de un pase de cómputo ──────────────────────────────────


@dataclass
class ComputeResult:
    """Conteo de advices procesados por categoría."""
    computed: int = 0          # nuevas filas insertadas
    skipped: int = 0           # ya tenían outcome temporal y force=False
    no_facet_yet: int = 0      # sin meta/facet match — reintenta luego
    force_updated: int = 0     # outcome existente actualizado por force=True


# ── Heurística de inferencia ─────────────────────────────────────────


def infer_rating(
    outcome: str,
    helpfulness: str,
    satisfaction: str,
) -> str:
    """Devuelve `useful` | `not_useful` | `unclear` (blueprint §3).

    Reglas en orden:
    1. `not_useful` si CUALQUIERA de las señales es negativa (outcome
       en {not_achieved, partially_achieved}, helpfulness en
       {unhelpful, slightly_helpful}, satisfaction en
       {dissatisfied, frustrated}).
    2. `useful` si outcome y helpfulness son positivos y satisfaction
       no es negativa (ya descartado en 1).
    3. `unclear` en cualquier otro caso (incluido outcome
       `unclear_from_transcript` o vacío).
    """
    if outcome in NOT_USEFUL_OUTCOMES:
        return "not_useful"
    if helpfulness in NOT_USEFUL_HELPFULNESS:
        return "not_useful"
    if satisfaction in NOT_USEFUL_SATISFACTION:
        return "not_useful"
    if outcome in USEFUL_OUTCOMES and helpfulness in USEFUL_HELPFULNESS:
        return "useful"
    return "unclear"


# ── Helpers de derivación de facets ──────────────────────────────────


def _derive_satisfaction(counts: dict) -> str:
    """Reduce `user_satisfaction_counts` a un único label representativo.

    Prioridad: frustrated > dissatisfied > satisfied > likely_satisfied
    > mixed > "" (vacío). La prioridad negativa va primero porque la
    heurística §3 dispara `not_useful` ante ANY signal negativa.
    """
    if not isinstance(counts, dict):
        return ""
    for key in (
        "frustrated", "dissatisfied",
        "satisfied", "likely_satisfied", "mixed",
    ):
        if int(counts.get(key, 0) or 0) > 0:
            return key
    return ""


def _friction_keys_active(counts: dict) -> list[str]:
    """Lista de friction keys con count>0, ordenadas por count desc + key asc."""
    if not isinstance(counts, dict):
        return []
    items = [(k, int(v or 0)) for k, v in counts.items() if int(v or 0) > 0]
    items.sort(key=lambda x: (-x[1], x[0]))
    return [k for k, _ in items]


def _parse_db_timestamp(s: str) -> datetime | None:
    """Convierte el `created_at` de SQLite a datetime UTC.

    Acepta los dos formatos que aparecen en `context.db`:
    - `'YYYY-MM-DD HH:MM:SS'` (default `datetime('now')`)
    - ISO8601 con o sin sufijo `Z`.
    """
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── Núcleo: compute_outcomes ─────────────────────────────────────────


def compute_outcomes(
    db_path: str | Path,
    project_path: str,
    *,
    lookback_days: int = 14,
    force: bool = False,
    usage_root: Path | None = None,
) -> ComputeResult:
    """Itera `advisor_advice` reciente y rellena `advice_outcomes`.

    Args:
        db_path: ruta a `context.db`.
        project_path: ruta absoluta del proyecto (para filtrar
            session-meta y evitar mezclar con otros proyectos).
        lookback_days: ventana hacia atrás desde ahora; advices más
            viejos se ignoran (no entran en el conteo).
        force: si True, recomputa outcomes ya existentes con
            `assoc_method='temporal'` (UPDATE en vez de skip).
        usage_root: override para tests; en producción cae a
            `udr.usage_data_root()`.

    Returns:
        `ComputeResult` con conteos de cada caso.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    with get_sync_db(db_path) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            "SELECT a.id AS advice_id, a.created_at, "
            "       (SELECT ao.id FROM advice_outcomes ao "
            "        WHERE ao.advice_id=a.id "
            "          AND ao.assoc_method='temporal') AS outcome_id "
            "FROM advisor_advice a "
            "WHERE a.created_at >= ? "
            "ORDER BY a.id ASC",
            (cutoff_str,),
        )
        candidates = [dict(r) for r in cur.fetchall()]

    # Pre-cachea facets de las sesiones del proyecto (lectura única).
    session_ids = {
        m.session_id
        for m in udr.iter_meta(project_path=project_path, root=usage_root)
    }
    facets_by_sid: dict[str, udr.UsageFacets] = {
        f.session_id: f
        for f in udr.iter_facets(session_ids=session_ids, root=usage_root)
    }

    result = ComputeResult()
    for cand in candidates:
        advice_id = cand["advice_id"]
        outcome_id = cand["outcome_id"]

        if outcome_id is not None and not force:
            result.skipped += 1
            continue

        ts = _parse_db_timestamp(cand["created_at"])
        if ts is None:
            result.skipped += 1
            continue

        sid = udr.find_session_for_timestamp(
            ts, project_path,
            root=usage_root, slack_minutes=ASSOC_SLACK_MINUTES,
        )
        if sid is None:
            result.no_facet_yet += 1
            continue

        facet = facets_by_sid.get(sid)
        if facet is None:
            # Hay session-meta pero el facet aún no se escribió.
            result.no_facet_yet += 1
            continue

        outcome_enum = facet.outcome
        helpfulness = facet.claude_helpfulness
        satisfaction = _derive_satisfaction(facet.user_satisfaction_counts)
        friction = _friction_keys_active(facet.friction_counts)
        rating = infer_rating(outcome_enum, helpfulness, satisfaction)
        friction_json = json.dumps(friction, ensure_ascii=False)

        with get_sync_db(db_path) as conn:
            if outcome_id is None:
                conn.execute(
                    "INSERT INTO advice_outcomes "
                    "(advice_id, session_id, assoc_method, "
                    " facet_outcome, facet_helpfulness, facet_satisfaction, "
                    " friction_keys, inferred_rating) "
                    "VALUES (?, ?, 'temporal', ?, ?, ?, ?, ?)",
                    (
                        advice_id, sid,
                        outcome_enum, helpfulness, satisfaction,
                        friction_json, rating,
                    ),
                )
                result.computed += 1
            else:
                conn.execute(
                    "UPDATE advice_outcomes "
                    "SET session_id=?, facet_outcome=?, facet_helpfulness=?, "
                    "    facet_satisfaction=?, friction_keys=?, "
                    "    inferred_rating=?, computed_at=datetime('now') "
                    "WHERE id=?",
                    (
                        sid, outcome_enum, helpfulness, satisfaction,
                        friction_json, rating, outcome_id,
                    ),
                )
                result.force_updated += 1
            conn.commit()

    return result
