"""APEX Sprint 15 — Advisor strategy.

El Advisor (subagent Opus on-demand vía Task) lee el shared context de la
sesión y emite advice cards estructuradas. Este módulo NO llama al modelo:
construye el bundle, gestiona pacing/throttle/circuit-breaker, persiste
reviews y advice cards, y los rehidrata para el hook advice-injector.

Ciclo de vida de un review (cerrado el 2026-10-19): se abre en 'pending',
el subagente emite 0-3 cards y el review se cierra con `close_review`
(conteo y duración recalculados desde la BD). `close_ready_reviews`
decide cuándo está listo; `reap_stale_reviews` poda la basura
histórica. El cierre es lo que dispara `register_review_outcome`, es
decir, el circuit breaker.

Ver `.apex/sprints/sprint-15-advisor-blueprint.md` secciones 2 y 6.
"""
from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lib.db_utils import get_sync_db

# ── Constantes de pacing (blueprint sec 2.2) ──
ADVISOR_DEFAULT_INTERVAL = 8
ADVISOR_BACKOFF_INTERVAL = 16
ADVISOR_EMPTY_STREAK_THRESHOLD = 3
ADVISOR_BUNDLE_MAX_TOKENS = 2500
ADVISOR_MIN_CALLS_BEFORE_FIRST = 3

ADVISOR_FORCE_TRIGGERS: frozenset[str] = frozenset({
    "apex_set_phase",
    "apex_grader_evaluate.should_block=1",
    "apex_add_error.severity=critical",
    "apex_add_error.severity=high",
})

ALLOWED_KINDS: frozenset[str] = frozenset({
    "forgotten_tool",
    "cross_project_error",
    "phase_drift",
    "recommend_skill_handoff",
    "grader_overdue",
})

ALLOWED_SEVERITIES: frozenset[str] = frozenset({"info", "warn", "critical"})

# Meta keys (reusan project_meta del schema base)
META_TOOL_COUNT = "advisor_tool_count"
META_EMPTY_STREAK = "advisor_empty_streak"
META_CURRENT_INTERVAL = "advisor_current_interval"
META_LAST_REVIEW_AT = "advisor_last_review_at"

# Ventana de elegibilidad para advice-injector (segundos)
ACTIVE_ADVICE_WINDOW_SEC = 7200  # 2h


# ── Estados de un review ───────────────────────────────────────────
# 'pending'   → abierto; el subagente todavía no ha hablado.
# 'completed' → cerrado y produjo advice (advice_count > 0).
# 'skipped'   → cerrado sin advice (el advisor no vio nada que decir).
# 'abandoned' → podado por antigüedad sin que nadie lo cerrara.
REVIEW_PENDING = "pending"
REVIEW_COMPLETED = "completed"
REVIEW_SKIPPED = "skipped"
REVIEW_ABANDONED = "abandoned"

# Ventana de asentamiento (settle): un review con advice cards no se
# cierra hasta que pasan estos segundos desde la última card. El
# subagente emite sus cards con segundos de diferencia; sin esta
# ventana el hook cerraría el review a mitad del subagente y el
# conteo quedaría a medias.
ADVISOR_SETTLE_SEC = 15

# Un review pending SIN cards se cierra como 'skipped' a partir de
# esta antigüedad: el subagente no llegó a emitir nada.
ADVISOR_GRACE_SEC = 120

# Reparación: un review pending más viejo que esto se poda. Es la red
# de seguridad que limpia la basura histórica (la auditoría del
# 2026-10-19 encontró 7269 reviews 'pending' acumulados porque nada
# cerraba un review nunca).
ADVISOR_STALE_REVIEW_SEC = 3600


# ── Sprint 16.5 — Constantes migrables a project_meta ────────────────
# Las 6 constantes anteriores se persisten como JSON en
# project_meta.advisor_constants para que el auto-tuning del Sprint 16.4
# pueda mutarlas sin tocar código. Si la fila no existe, fallback a
# defaults — no se rompe ninguna BD existente.

ADVISOR_CONSTANTS_KEY = "advisor_constants"

ADVISOR_CONSTANT_DEFAULTS: dict[str, int | float] = {
    "default_interval": ADVISOR_DEFAULT_INTERVAL,
    "backoff_interval": ADVISOR_BACKOFF_INTERVAL,
    "empty_streak_threshold": ADVISOR_EMPTY_STREAK_THRESHOLD,
    "bundle_max_tokens": ADVISOR_BUNDLE_MAX_TOKENS,
    "min_calls_before_first": ADVISOR_MIN_CALLS_BEFORE_FIRST,
    "active_advice_window_sec": ACTIVE_ADVICE_WINDOW_SEC,
    # Sprint 16.4 — claves nuevas tuneables
    "phase_drift_window_min": 30,
    "complexity_score_threshold": 0.6,
    "grader_overdue_phases": 2,
}


def get_advisor_constants(db_path: Path | str) -> dict[str, int | float]:
    """Devuelve constantes del Advisor con fallback a defaults.

    Lee `project_meta.advisor_constants` (JSON). Si la fila no existe,
    el JSON está corrupto o no es un dict, devuelve una copia de
    `ADVISOR_CONSTANT_DEFAULTS`. Las keys desconocidas en el JSON se
    ignoran; las keys conocidas que falten en el JSON caen a defaults.
    """
    with _conn(db_path) as c:
        cur = c.execute(
            "SELECT value FROM project_meta WHERE key=?",
            (ADVISOR_CONSTANTS_KEY,),
        )
        row = cur.fetchone()
    if not row:
        return dict(ADVISOR_CONSTANT_DEFAULTS)
    try:
        parsed = json.loads(row[0])
    except (json.JSONDecodeError, TypeError):
        return dict(ADVISOR_CONSTANT_DEFAULTS)
    if not isinstance(parsed, dict):
        return dict(ADVISOR_CONSTANT_DEFAULTS)
    merged = dict(ADVISOR_CONSTANT_DEFAULTS)
    for k, v in parsed.items():
        if k in ADVISOR_CONSTANT_DEFAULTS:
            merged[k] = v
    return merged


def set_advisor_constants(
    db_path: Path | str, constants: dict[str, Any]
) -> None:
    """Persiste constantes del Advisor en `project_meta.advisor_constants`.

    Solo se guardan las keys reconocidas (presentes en
    `ADVISOR_CONSTANT_DEFAULTS`). Cualquier key desconocida se descarta
    silenciosamente para evitar contaminación. Idempotente: escribir el
    mismo dict dos veces produce el mismo estado.
    """
    safe = {
        k: v
        for k, v in constants.items()
        if k in ADVISOR_CONSTANT_DEFAULTS
    }
    with _conn(db_path) as c:
        _set_meta(c, ADVISOR_CONSTANTS_KEY, json.dumps(safe))
        c.commit()


# ── Helpers internos ──────────────────────────────────────────────

def _conn(db_path: Path | str):
    """Context manager de conexión con los PRAGMAs estándar.

    Devuelve el context manager entero, no `.__enter__()`: entrar y descartar
    el generador dejaba el `finally: conn.close()` en manos del recolector, y
    la conexión aparecía cerrada a mitad de uso ("Cannot operate on a closed
    database"). Todos los llamadores hacen `with _conn(...) as c`.
    """
    return get_sync_db(db_path)


def _get_meta_int(c: sqlite3.Connection, key: str, default: int = 0) -> int:
    cur = c.execute("SELECT value FROM project_meta WHERE key=?", (key,))
    row = cur.fetchone()
    if not row:
        return default
    try:
        return int(row[0])
    except (ValueError, TypeError):
        return default


def _set_meta(c: sqlite3.Connection, key: str, value: Any) -> None:
    c.execute(
        "INSERT INTO project_meta (key, value, updated_at) "
        "VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET "
        "  value=excluded.value, updated_at=excluded.updated_at",
        (key, str(value)),
    )


# ── Pacing / throttle / circuit breaker ───────────────────────────

def increment_tool_count(db_path: Path | str) -> int:
    with _conn(db_path) as c:
        n = _get_meta_int(c, META_TOOL_COUNT, 0) + 1
        _set_meta(c, META_TOOL_COUNT, n)
        c.commit()
    return n


def reset_tool_count(db_path: Path | str) -> None:
    with _conn(db_path) as c:
        _set_meta(c, META_TOOL_COUNT, 0)
        c.commit()


def get_current_interval(db_path: Path | str) -> int:
    with _conn(db_path) as c:
        return _get_meta_int(c, META_CURRENT_INTERVAL, ADVISOR_DEFAULT_INTERVAL)


def should_run(db_path: Path | str, force: bool = False) -> tuple[bool, str]:
    if force:
        return True, "force"
    with _conn(db_path) as c:
        count = _get_meta_int(c, META_TOOL_COUNT, 0)
        interval = _get_meta_int(c, META_CURRENT_INTERVAL, ADVISOR_DEFAULT_INTERVAL)
    if count < ADVISOR_MIN_CALLS_BEFORE_FIRST:
        return False, f"min_calls_not_reached ({count}<{ADVISOR_MIN_CALLS_BEFORE_FIRST})"
    if count < interval:
        return False, f"interval_not_reached ({count}<{interval})"
    return True, f"interval_reached ({count}>={interval})"


def register_review_outcome(db_path: Path | str, advice_count: int) -> None:
    """Tras un review, ajusta empty_streak + current_interval (circuit breaker).

    Punto de entrada del circuit breaker. Lo llama `close_review` (la vía
    normal) y, en tests, directamente.

    - 0 advice → streak += 1; si streak >= threshold, interval = backoff
    - >0 advice → streak = 0, interval vuelve a default
    Siempre resetea tool_count y guarda last_review_at.
    """
    with _conn(db_path) as c:
        if advice_count == 0:
            streak = _get_meta_int(c, META_EMPTY_STREAK, 0) + 1
            _set_meta(c, META_EMPTY_STREAK, streak)
            if streak >= ADVISOR_EMPTY_STREAK_THRESHOLD:
                _set_meta(c, META_CURRENT_INTERVAL, ADVISOR_BACKOFF_INTERVAL)
        else:
            _set_meta(c, META_EMPTY_STREAK, 0)
            _set_meta(c, META_CURRENT_INTERVAL, ADVISOR_DEFAULT_INTERVAL)
        _set_meta(c, META_TOOL_COUNT, 0)
        _set_meta(c, META_LAST_REVIEW_AT, time.time())
        c.commit()


# ── Persistencia: reviews ────────────────────────────────────────

def record_review(
    db_path: Path | str,
    session_id: str,
    trigger_kind: str,
    bundle_size_tokens: int = 0,
) -> int:
    with _conn(db_path) as c:
        cur = c.execute(
            "INSERT INTO advisor_reviews "
            "(session_id, trigger_kind, bundle_size_tokens, status) "
            "VALUES (?, ?, ?, 'pending')",
            (session_id, trigger_kind, bundle_size_tokens),
        )
        rid = cur.lastrowid
        c.commit()
    return rid


def update_review_status(
    db_path: Path | str,
    review_id: int,
    status: str,
    advice_count: int | None = None,
    duration_ms: int | None = None,
    expected_status: str | None = None,
) -> bool:
    """Actualiza el estado de un review. Devuelve True si cambió algo.

    `expected_status` (opcional) hace el UPDATE condicional: sólo
    aplica si el estado actual coincide. Es lo que permite cerrar un
    review sin doble-cierre — el circuit breaker sólo debe dispararse
    una vez por review.
    """
    fields = ["status=?"]
    params: list[Any] = [status]
    if advice_count is not None:
        fields.append("advice_count=?")
        params.append(advice_count)
    if duration_ms is not None:
        fields.append("duration_ms=?")
        params.append(duration_ms)
    params.append(review_id)
    where = "id=?"
    if expected_status is not None:
        where = "id=? AND status=?"
        params.append(expected_status)
    with _conn(db_path) as c:
        cur = c.execute(
            f"UPDATE advisor_reviews SET {', '.join(fields)} WHERE {where}",
            params,
        )
        c.commit()
        return cur.rowcount > 0


# ── Ciclo de vida del review: cierre, circuit breaker, reparación ──
#
# Diseño (por qué así):
#
# Un review se abre en 'pending' cuando el hook dispara al subagente.
# El subagente devuelve 0-3 advice cards, pero **no hay señal explícita
# de "ya he terminado"**: el tool `apex_record_advice` no publica un
# parámetro de cierre (su schema vive en mcp/apex_server.py) y el
# prompt del subagente no lo pide. Por eso el cierre se deriva del
# estado observable en la BD, con tres reglas y un único principio:
#
#   **La realidad de la tabla `advisor_advice` manda.** El conteo y la
#   duración se recalculan siempre desde la BD, nunca de lo que declara
#   el subagente. Un review cerrado tiene `advice_count` exacto y
#   `duration_ms` real, da igual cuándo se cerrara.
#
# Las tres reglas de cierre:
#
# 1. `close_ready_reviews` — cierra los pending que están "listos":
#    tienen cards y la última es de hace >= ADVISOR_SETTLE_SEC (el
#    subagente ya terminó), o no tienen cards y llevan >=
#    ADVISOR_GRACE_SEC abiertos (el subagente no dijo nada → 'skipped').
# 2. `close_review` — el cierre en sí: recalcula contadores, fija el
#    estado terminal y llama a `register_review_outcome`, que resetea
#    `tool_count` y actualiza `empty_streak`/`current_interval`. Ése es
#    el punto donde el circuit breaker deja de ser decorativo.
# 3. `reap_stale_reviews` — reparación idempotente: poda los pending
#    más viejos que ADVISOR_STALE_REVIEW_SEC. No toca el circuit
#    breaker a propósito (miles de reviews de basura alimentarían
#    `empty_streak` y dejarían el advisor en backoff perpetuo).


def _parse_db_ts(value: str | None) -> datetime | None:
    """Convierte un timestamp de SQLite ('YYYY-MM-DD HH:MM:SS' UTC) a datetime UTC."""
    if not value:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _review_counters(c: sqlite3.Connection, review_id: int) -> tuple[int, int]:
    """(advice_count, duration_ms) autoritativos de un review.

    `advice_count` sale de `advisor_advice` (la realidad), no de lo que
    declare el subagente. `duration_ms` es el tiempo real transcurrido
    desde `triggered_at`.
    """
    cur = c.execute(
        "SELECT (SELECT COUNT(*) FROM advisor_advice a "
        "         WHERE a.review_id = advisor_reviews.id), "
        "       CAST((julianday('now') - julianday(triggered_at)) * 86400000 "
        "            AS INTEGER) "
        "FROM advisor_reviews WHERE id=?",
        (review_id,),
    )
    row = cur.fetchone()
    if row is None:
        return (0, 0)
    return (int(row[0] or 0), max(0, int(row[1] or 0)))


def sync_review_counters(db_path: Path | str, review_id: int) -> dict | None:
    """Refresca `advice_count` y `duration_ms` del review desde la BD.

    Se llama tras cada advice card: el conteo refleja siempre lo que
    hay realmente en `advisor_advice`, aunque el subagente siga
    emitiendo cards después. Devuelve None si el review no existe.
    """
    with _conn(db_path) as c:
        n, ms = _review_counters(c, review_id)
        cur = c.execute(
            "UPDATE advisor_reviews SET advice_count=?, duration_ms=? WHERE id=?",
            (n, ms, review_id),
        )
        c.commit()
        changed = cur.rowcount > 0
    if not changed:
        return None
    return {"review_id": review_id, "advice_count": n, "duration_ms": ms}


def get_review(db_path: Path | str, review_id: int) -> dict | None:
    """Fila completa de `advisor_reviews` como dict, o None si no existe."""
    with _conn(db_path) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute("SELECT * FROM advisor_reviews WHERE id=?", (review_id,))
        row = cur.fetchone()
    return dict(row) if row is not None else None


def pending_reviews(
    db_path: Path | str, session_id: str | None = None
) -> list[dict]:
    """Reviews en estado 'pending' (opcionalmente de una sola sesión)."""
    sql = (
        "SELECT id, session_id, triggered_at FROM advisor_reviews "
        "WHERE status=?"
    )
    params: list[Any] = [REVIEW_PENDING]
    if session_id is not None:
        sql += " AND session_id=?"
        params.append(session_id)
    sql += " ORDER BY id ASC"
    with _conn(db_path) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def close_review(
    db_path: Path | str,
    review_id: int,
    status: str | None = None,
    advice_count: int | None = None,
    duration_ms: int | None = None,
    notify_circuit: bool = True,
) -> dict | None:
    """Cierra un review en estado terminal. Devuelve el cierre o None.

    - `advice_count` y `duration_ms` se recalculan desde la BD salvo que
      se pasen explícitamente: la realidad manda sobre lo que declara el
      subagente.
    - Estado por defecto: 'completed' si produjo advice, 'skipped' si no.
    - Idempotente: si el review ya no está 'pending' devuelve None y NO
      vuelve a disparar el circuit breaker.
    - `notify_circuit=True` (defecto) llama a `register_review_outcome`:
      resetea `tool_count` y actualiza `empty_streak`/`current_interval`.
      Es la conexión que le faltaba al bucle del advisor.
    """
    with _conn(db_path) as c:
        row = c.execute(
            "SELECT status FROM advisor_reviews WHERE id=?", (review_id,)
        ).fetchone()
        if row is None or row[0] != REVIEW_PENDING:
            return None
        n, ms = _review_counters(c, review_id)
    final_count = n if advice_count is None else advice_count
    final_ms = ms if duration_ms is None else duration_ms
    final_status = status or (
        REVIEW_COMPLETED if final_count > 0 else REVIEW_SKIPPED
    )
    changed = update_review_status(
        db_path,
        review_id,
        final_status,
        advice_count=final_count,
        duration_ms=final_ms,
        expected_status=REVIEW_PENDING,
    )
    if not changed:
        return None
    if notify_circuit:
        register_review_outcome(db_path, final_count)
    return {
        "review_id": review_id,
        "status": final_status,
        "advice_count": final_count,
        "duration_ms": final_ms,
    }


def close_ready_reviews(
    db_path: Path | str,
    session_id: str | None = None,
    settle_sec: int = ADVISOR_SETTLE_SEC,
    grace_sec: int = ADVISOR_GRACE_SEC,
) -> list[dict]:
    """Cierra los reviews 'pending' que ya están listos.

    Un review está listo cuando:
    - tiene advice cards y la última es de hace >= `settle_sec`: el
      subagente ya terminó (emite sus cards con segundos de diferencia;
      cerrarlas en caliente truncaría el conteo) → 'completed'.
    - no tiene cards y lleva >= `grace_sec` abierto: el subagente no
      llegó a decir nada → 'skipped' (alimenta el circuit breaker).

    `session_id=None` (defecto) revisa todas las sesiones del
    proyecto: un review de una sesión anterior no puede quedarse
    abierto para siempre porque nadie vuelva a esa sesión.

    Idempotente: un review ya cerrado no se toca.
    """
    now = datetime.now(timezone.utc)
    closed: list[dict] = []
    for row in pending_reviews(db_path, session_id):
        with _conn(db_path) as c:
            cur = c.execute(
                "SELECT (SELECT COUNT(*) FROM advisor_advice a "
                "         WHERE a.review_id=?), "
                "       (SELECT MAX(a.created_at) FROM advisor_advice a "
                "         WHERE a.review_id=?)",
                (row["id"], row["id"]),
            )
            n_raw, last_card = cur.fetchone()
        n = int(n_raw or 0)
        if n > 0:
            last = _parse_db_ts(last_card)
            if last is None:
                continue
            if (now - last).total_seconds() < settle_sec:
                continue  # el subagente puede seguir emitiendo
            status = REVIEW_COMPLETED
        else:
            started = _parse_db_ts(row["triggered_at"])
            if started is None:
                continue
            if (now - started).total_seconds() < grace_sec:
                continue
            status = REVIEW_SKIPPED
        res = close_review(db_path, row["id"], status=status)
        if res is not None:
            closed.append(res)
    return closed


def reap_stale_reviews(
    db_path: Path | str, max_age_sec: int = ADVISOR_STALE_REVIEW_SEC
) -> int:
    """Reparación idempotente: poda los reviews 'pending' demasiado viejos.

    El bucle del advisor nunca cerraba un review, así que
    `advisor_reviews` acumuló miles de filas 'pending' (7269 en la
    auditoría del 2026-10-19). Esta función las pasa a estado terminal:
    'abandoned' si no produjeron advice, 'completed' si la hubo (el
    trabajo se hizo; sólo se perdió el cierre).

    NO toca el circuit breaker a propósito: 7269 reviews de basura
    alimentarían `empty_streak` y dejarían el advisor en backoff
    perpetuo. El circuit breaker sólo cuenta reviews reales, los que
    cierra `close_review`.

    Idempotente: sólo toca filas 'pending', así que la segunda pasada no
    encuentra nada que podar. Devuelve el nº de filas podadas.
    """
    with _conn(db_path) as c:
        cur = c.execute(
            "UPDATE advisor_reviews "
            "SET advice_count = (SELECT COUNT(*) FROM advisor_advice a "
            "                     WHERE a.review_id = advisor_reviews.id), "
            "    duration_ms = MAX(0, CAST((julianday('now') "
            "                           - julianday(triggered_at)) "
            "                           * 86400000 AS INTEGER)), "
            "    status = CASE WHEN (SELECT COUNT(*) FROM advisor_advice a "
            "                      WHERE a.review_id = advisor_reviews.id) > 0 "
            "                 THEN ? ELSE ? END "
            "WHERE status=? AND triggered_at < datetime('now', ?)",
            (
                REVIEW_COMPLETED,
                REVIEW_ABANDONED,
                REVIEW_PENDING,
                f"-{int(max_age_sec)} seconds",
            ),
        )
        c.commit()
        return max(0, cur.rowcount)



# ── Persistencia: advice cards ───────────────────────────────────

def record_advice(
    db_path: Path | str,
    review_id: int,
    kind: str,
    severity: str,
    title: str,
    body: str,
    evidence_refs: list | None = None,
) -> int | None:
    """Inserta una advice card. Idempotente vía UNIQUE(review_id, kind, title).

    Tras cada card refresca los contadores del review (`advice_count` y
    `duration_ms`): el estado del review refleja siempre la realidad de
    la tabla, aunque el subagente siga emitiendo cards después.

    Returns:
        id de la card insertada, o None si era duplicada (silenciosa).
    Raises:
        ValueError si kind/severity no están en sus whitelists.
    """
    if kind not in ALLOWED_KINDS:
        raise ValueError(f"invalid kind: {kind!r} not in {sorted(ALLOWED_KINDS)}")
    if severity not in ALLOWED_SEVERITIES:
        raise ValueError(
            f"invalid severity: {severity!r} not in {sorted(ALLOWED_SEVERITIES)}"
        )
    refs_json = json.dumps(evidence_refs or [], ensure_ascii=False)
    with _conn(db_path) as c:
        try:
            cur = c.execute(
                "INSERT INTO advisor_advice "
                "(review_id, kind, severity, title, body, evidence_refs) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (review_id, kind, severity, title, body, refs_json),
            )
            c.commit()
            advice_id = cur.lastrowid
        except sqlite3.IntegrityError:
            return None
    sync_review_counters(db_path, review_id)
    return advice_id


def dismiss_advice(
    db_path: Path | str,
    advice_id: int,
    reason: str,
) -> bool:
    if not reason or len(reason.strip()) < 3:
        raise ValueError("dismiss reason required (>=3 chars)")
    with _conn(db_path) as c:
        cur = c.execute(
            "UPDATE advisor_advice "
            "SET dismissed=1, dismissed_reason=? "
            "WHERE id=?",
            (reason.strip(), advice_id),
        )
        c.commit()
        return cur.rowcount > 0


# ── Sprint 16.6 — Escape hatch manual ────────────────────────────────

ALLOWED_MANUAL_RATINGS: frozenset[str] = frozenset({"useful", "not_useful"})
MIN_MANUAL_REASON_CHARS = 10


def rate_advice(
    db_path: Path | str,
    advice_id: int,
    rating: str,
    reason: str,
) -> dict:
    """Escape hatch manual: inserta una fila en `advice_outcomes` con
    `assoc_method='manual'`. No reemplaza el outcome temporal: el
    UNIQUE compuesto permite ambos coexistiendo.

    - rating ∈ {'useful', 'not_useful'}; 'unclear' no aplica al manual
      (el escape hatch fuerza señal explícita).
    - reason ≥10 chars (>=10 caracteres no espacios).
    - advice_id debe existir en advisor_advice (FK validation).
    - Idempotente: segundo manual sobre el mismo advice usa
      `INSERT OR REPLACE` respetando el UNIQUE.

    Returns:
        {'outcome_id': int}
    """
    if rating not in ALLOWED_MANUAL_RATINGS:
        raise ValueError(
            f"invalid rating: {rating!r} not in {sorted(ALLOWED_MANUAL_RATINGS)}"
        )
    if reason is None:
        raise ValueError("reason required (>=10 chars)")
    cleaned = reason.strip()
    if len(cleaned) < MIN_MANUAL_REASON_CHARS:
        raise ValueError(
            f"reason too short: requires >={MIN_MANUAL_REASON_CHARS} chars"
        )
    with _conn(db_path) as c:
        # FK validation explícita para mensaje claro (sqlite no la
        # impone a menos que PRAGMA foreign_keys=ON, y queremos un
        # ValueError, no IntegrityError opaco).
        cur = c.execute(
            "SELECT 1 FROM advisor_advice WHERE id=?", (advice_id,)
        )
        if cur.fetchone() is None:
            raise ValueError(f"advice_id {advice_id} no existe")
        cur = c.execute(
            "INSERT OR REPLACE INTO advice_outcomes "
            "(advice_id, assoc_method, inferred_rating, manual_reason) "
            "VALUES (?, 'manual', ?, ?)",
            (advice_id, rating, cleaned),
        )
        c.commit()
        return {"outcome_id": cur.lastrowid}


def get_active_advice(db_path: Path | str, session_id: str) -> list[dict]:
    """Para advice-injector. NOT dismissed AND review reciente (<2h).

    Orden: severity (critical > warn > info), luego id DESC.
    """
    with _conn(db_path) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            "SELECT a.id, a.review_id, a.kind, a.severity, a.title, a.body, "
            "       a.evidence_refs, a.created_at "
            "FROM advisor_advice a "
            "JOIN advisor_reviews r ON r.id = a.review_id "
            "WHERE r.session_id = ? "
            "  AND a.dismissed = 0 "
            "  AND r.triggered_at >= datetime('now', ?) "
            "ORDER BY CASE a.severity "
            "         WHEN 'critical' THEN 0 "
            "         WHEN 'warn' THEN 1 "
            "         ELSE 2 END, a.id DESC",
            (session_id, f"-{ACTIVE_ADVICE_WINDOW_SEC} seconds"),
        )
        return [dict(row) for row in cur.fetchall()]


# ── Bundle building ──────────────────────────────────────────────

def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Heurística chars/4. Conserva cabeza + cola si excede."""
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    half = max_chars // 2
    head = text[:half]
    tail = text[-half:]
    return f"{head}\n\n[... truncado ...]\n\n{tail}"


def estimate_bundle_tokens(bundle: dict) -> int:
    return len(json.dumps(bundle, ensure_ascii=False, default=str)) // 4


def build_bundle(db_path: Path | str, session_id: str) -> dict:
    """Compone shared context compacto para el subagent advisor.

    Hard cap ADVISOR_BUNDLE_MAX_TOKENS (chars/4 heurística). Si excede,
    el bundle se reempaqueta con _truncated=True y _payload_truncated.
    """
    out: dict[str, Any] = {
        "session_id": session_id,
        "phase": None,
        "recent_decisions": [],
        "blocking_verdicts": [],
        "recent_traces": [],
        "recent_tool_calls": [],
    }
    with _conn(db_path) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            "SELECT phase_number, name, status, started_at "
            "FROM phases WHERE status='in_progress' "
            "ORDER BY phase_number ASC LIMIT 1"
        )
        row = cur.fetchone()
        if row:
            out["phase"] = dict(row)
        cur = c.execute(
            "SELECT id, phase, category, decision, reasoning, created_at "
            "FROM decisions WHERE invalid_from IS NULL "
            "ORDER BY id DESC LIMIT 3"
        )
        out["recent_decisions"] = [dict(r) for r in cur.fetchall()]
        # Solo bloqueos VIGENTES: el verdict debe ser el ÚLTIMO de su fase.
        # Filtrar por should_block=1 a secas resucitaba bloqueos ya resueltos
        # por un PASS posterior, y podía devolver tres verdicts viejos de la
        # misma fase. El histórico se conserva: esto solo elige qué mostrar.
        cur = c.execute(
            "SELECT v.id, v.phase, v.quality, v.issues, v.reasoning, "
            "       v.created_at "
            "FROM grader_verdicts AS v "
            "WHERE v.should_block=1 AND v.id = ("
            "  SELECT u.id FROM grader_verdicts AS u "
            "  WHERE u.phase = v.phase "
            "  ORDER BY u.created_at DESC, u.id DESC LIMIT 1) "
            "ORDER BY v.id DESC LIMIT 3"
        )
        out["blocking_verdicts"] = [dict(r) for r in cur.fetchall()]
        cur = c.execute(
            "SELECT id, phase, category, gate_kind, deliberation, "
            "       calibration_confidence, created_at "
            "FROM reasoning_traces WHERE session_id=? "
            "ORDER BY id DESC LIMIT 5",
            (session_id,),
        )
        out["recent_traces"] = [dict(r) for r in cur.fetchall()]
        cur = c.execute(
            "SELECT tool, args_summary, created_at FROM tool_call_log "
            "ORDER BY id DESC LIMIT 20"
        )
        out["recent_tool_calls"] = [dict(r) for r in cur.fetchall()]

    raw = json.dumps(out, ensure_ascii=False, default=str)
    if len(raw) <= ADVISOR_BUNDLE_MAX_TOKENS * 4:
        out["_size_chars"] = len(raw)
        out["_truncated"] = False
        return out
    capped = _truncate_to_tokens(raw, ADVISOR_BUNDLE_MAX_TOKENS)
    return {
        "session_id": session_id,
        "_truncated": True,
        "_payload_truncated": capped,
        "_size_chars": len(capped),
    }
