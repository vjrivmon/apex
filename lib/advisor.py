"""APEX Sprint 15 — Advisor strategy.

El Advisor (subagent Opus on-demand vía Task) lee el shared context de la
sesión y emite advice cards estructuradas. Este módulo NO llama al modelo:
construye el bundle, gestiona pacing/throttle/circuit-breaker, persiste
reviews y advice cards, y los rehidrata para el hook advice-injector.

Ver `.apex/sprints/sprint-15-advisor-blueprint.md` secciones 2 y 6.
"""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

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


# ── Helpers internos ──────────────────────────────────────────────

def _conn(db_path: Path | str) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path), timeout=5.0)


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
) -> None:
    fields = ["status=?"]
    params: list[Any] = [status]
    if advice_count is not None:
        fields.append("advice_count=?")
        params.append(advice_count)
    if duration_ms is not None:
        fields.append("duration_ms=?")
        params.append(duration_ms)
    params.append(review_id)
    with _conn(db_path) as c:
        c.execute(f"UPDATE advisor_reviews SET {', '.join(fields)} WHERE id=?", params)
        c.commit()


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
            return cur.lastrowid
        except sqlite3.IntegrityError:
            return None


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
        cur = c.execute(
            "SELECT id, phase, quality, issues, reasoning, created_at "
            "FROM grader_verdicts WHERE should_block=1 "
            "ORDER BY id DESC LIMIT 3"
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
