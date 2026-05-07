"""APEX Sprint 15 — skill_handoff.

Cambio de modo dentro de sesión (flujo Pocock). Un skill cede el control a
otro preservando snapshot; al volver, queda registrado el resultado.

Ver `.apex/sprints/sprint-15-advisor-blueprint.md` sección 5.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _conn(db_path: Path | str) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path), timeout=5.0)


def create_handoff(
    db_path: Path | str,
    session_id: str,
    from_skill: str,
    to_skill: str,
    reason: str,
    snapshot: dict[str, Any] | None = None,
) -> int:
    if not from_skill or not to_skill:
        raise ValueError("from_skill and to_skill required")
    if from_skill == to_skill:
        raise ValueError("from_skill and to_skill must differ")
    if not reason or len(reason.strip()) < 3:
        raise ValueError("reason required (>=3 chars)")
    snap_json = json.dumps(snapshot or {}, ensure_ascii=False)
    with _conn(db_path) as c:
        cur = c.execute(
            "INSERT INTO skill_handoffs "
            "(session_id, from_skill, to_skill, reason, snapshot) "
            "VALUES (?, ?, ?, ?, ?)",
            (session_id, from_skill, to_skill, reason.strip(), snap_json),
        )
        c.commit()
        return int(cur.lastrowid)


def resume_handoff(
    db_path: Path | str,
    handoff_id: int,
    result_summary: str = "",
) -> dict | None:
    """Marca returned_at = now y guarda result_summary. Devuelve snapshot."""
    with _conn(db_path) as c:
        c.row_factory = sqlite3.Row
        row = c.execute(
            "SELECT id, session_id, from_skill, to_skill, reason, snapshot, "
            "       returned_at FROM skill_handoffs WHERE id=?",
            (handoff_id,),
        ).fetchone()
        if not row:
            return None
        if row["returned_at"]:
            return dict(row)  # ya retornado, no re-marcar
        c.execute(
            "UPDATE skill_handoffs "
            "SET returned_at = datetime('now'), result_summary = ? "
            "WHERE id = ?",
            (result_summary or "", handoff_id),
        )
        c.commit()
        d = dict(row)
        try:
            d["snapshot"] = json.loads(d.get("snapshot") or "{}")
        except json.JSONDecodeError:
            pass
        return d


def get_orphan_handoffs(
    db_path: Path | str,
    max_age_seconds: int = 1800,
) -> list[dict]:
    """Para el Advisor: handoffs sin returned_at más viejos que N segundos.

    Default: 30 min. Triggers card phase_drift "handoff huérfano".
    """
    with _conn(db_path) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            "SELECT id, session_id, from_skill, to_skill, reason, "
            "       created_at FROM skill_handoffs "
            "WHERE returned_at IS NULL "
            "  AND created_at <= datetime('now', ?) "
            "ORDER BY created_at ASC",
            (f"-{int(max_age_seconds)} seconds",),
        )
        return [dict(r) for r in cur.fetchall()]
