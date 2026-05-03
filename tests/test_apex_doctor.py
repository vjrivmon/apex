"""Tests del subsistema Apex-doctor (Sprint 13).

Cubre:

- Schema migration: doctor_runs, doctor_proposals, session_starts existen.
- A1 override_clusters: detecta errores con recurrence>=3 o severity high+.
- A2 grader_block_patterns: agrupa issues bloqueantes en >=2 fases.
- A3 stale_handoffs: detecta handoffs con mtime >7d.
- run_doctor end-to-end: persiste run, escribe MD, idempotencia.
- Throttle 1h: segundo run cercano se marca throttled.
- session_starts: record + age.
- Markdown: 0 propuestas vs N propuestas.
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from context_db import ApexContextDB  # noqa: E402
import apex_doctor as d  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Crea .apex/context.db inicializada (con tablas Sprint 13)."""
    (tmp_path / ".apex").mkdir()
    db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
    _run(db.initialize())
    return tmp_path


@pytest.fixture
def db_path(project_root: Path) -> Path:
    return project_root / ".apex" / "context.db"


def _insert_error(db_path: Path, *, description: str, severity: str = "medium",
                  recurrence: int = 1, phase: int | None = None,
                  source: str = "claude") -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "INSERT INTO errors (source, phase, description, severity, "
            "recurrence_count) VALUES (?, ?, ?, ?, ?)",
            (source, phase, description, severity, recurrence),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


def _insert_grader_verdict(db_path: Path, *, phase: int, issues: list[str],
                            should_block: int = 1, reasoning: str = "") -> int:
    import json as _json
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.execute(
            "INSERT INTO grader_verdicts (phase, quality, issues, "
            "should_block, reasoning) VALUES (?, ?, ?, ?, ?)",
            (phase, 2, _json.dumps(issues), should_block, reasoning),
        )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


# ── Schema migration ─────────────────────────────────────────────────────

@pytest.mark.parametrize("table", ["doctor_runs", "doctor_proposals",
                                     "session_starts"])
def test_schema_creates_table(db_path: Path, table: str) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"Tabla {table} no existe en BD limpia"


def test_doctor_proposals_signature_unique(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO doctor_runs (trigger) VALUES ('test')"
        )
        conn.execute(
            "INSERT INTO doctor_proposals (run_id, kind, signature, body) "
            "VALUES (1, 'override_cluster', 'sig-x', 'body1')"
        )
        # Segundo insert con misma signature debe fallar por UNIQUE
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO doctor_proposals (run_id, kind, signature, body) "
                "VALUES (1, 'override_cluster', 'sig-x', 'body2')"
            )
        conn.commit()
    finally:
        conn.close()


# ── A1 override_clusters ─────────────────────────────────────────────────

def test_a1_returns_empty_on_clean_db(db_path: Path) -> None:
    assert d.analyze_override_clusters(db_path) == []


def test_a1_detects_recurrent_error(db_path: Path) -> None:
    _insert_error(db_path, description="hardcoded mock data",
                   severity="medium", recurrence=4, phase=8)
    props = d.analyze_override_clusters(db_path)
    assert len(props) == 1
    assert props[0].kind == "override_cluster"
    assert "hardcoded mock data" in props[0].title
    assert props[0].evidence["recurrence_count"] == 4


def test_a1_detects_critical_severity(db_path: Path) -> None:
    _insert_error(db_path, description="root cause not investigated",
                   severity="critical", recurrence=1)
    props = d.analyze_override_clusters(db_path)
    assert len(props) == 1
    assert "critical" in props[0].title


def test_a1_skips_low_severity_low_recurrence(db_path: Path) -> None:
    _insert_error(db_path, description="cosmetic typo", severity="low",
                   recurrence=1)
    assert d.analyze_override_clusters(db_path) == []


def test_a1_signature_stable_across_runs(db_path: Path) -> None:
    _insert_error(db_path, description="same desc", severity="critical",
                   recurrence=1)
    p1 = d.analyze_override_clusters(db_path)[0]
    p2 = d.analyze_override_clusters(db_path)[0]
    assert p1.signature == p2.signature


# ── A2 grader_block_patterns ─────────────────────────────────────────────

def test_a2_returns_empty_on_clean_db(db_path: Path) -> None:
    assert d.analyze_grader_block_patterns(db_path) == []


def test_a2_detects_issue_in_two_phases(db_path: Path) -> None:
    _insert_grader_verdict(db_path, phase=2, issues=["mock_data"],
                            reasoning="frontend con mock")
    _insert_grader_verdict(db_path, phase=8, issues=["mock_data"],
                            reasoning="integración aún mockeada")
    props = d.analyze_grader_block_patterns(db_path)
    assert len(props) == 1
    assert props[0].kind == "grader_block_pattern"
    assert "mock_data" in props[0].title
    assert props[0].evidence["phases"] == [2, 8]


def test_a2_skips_single_phase_issue(db_path: Path) -> None:
    _insert_grader_verdict(db_path, phase=4, issues=["edge_cases_missing"])
    assert d.analyze_grader_block_patterns(db_path) == []


def test_a2_ignores_non_blocking_verdicts(db_path: Path) -> None:
    _insert_grader_verdict(db_path, phase=2, issues=["minor"], should_block=0)
    _insert_grader_verdict(db_path, phase=8, issues=["minor"], should_block=0)
    assert d.analyze_grader_block_patterns(db_path) == []


def test_a2_handles_malformed_issues_json(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO grader_verdicts (phase, quality, issues, "
            "should_block, reasoning) VALUES (2, 2, 'NOT JSON', 1, '')"
        )
        conn.commit()
    finally:
        conn.close()
    # No crash
    assert d.analyze_grader_block_patterns(db_path) == []


# ── A3 stale_handoffs ────────────────────────────────────────────────────

def test_a3_returns_empty_when_no_handoffs(project_root: Path) -> None:
    assert d.analyze_stale_handoffs(project_root) == []


def test_a3_detects_old_handoff(project_root: Path) -> None:
    h_dir = project_root / ".apex" / "handoff"
    h_dir.mkdir(parents=True)
    old_file = h_dir / "old-sess.md"
    old_file.write_text("handoff content")
    # Backdate 10 días
    old_ts = time.time() - 10 * 86400
    os.utime(old_file, (old_ts, old_ts))

    props = d.analyze_stale_handoffs(project_root)
    assert len(props) == 1
    assert "1 handoff(s)" in props[0].title


def test_a3_ignores_recent_handoff(project_root: Path) -> None:
    h_dir = project_root / ".apex" / "handoff"
    h_dir.mkdir(parents=True)
    (h_dir / "recent.md").write_text("recent")
    assert d.analyze_stale_handoffs(project_root) == []


def test_a3_groups_multiple_stale(project_root: Path) -> None:
    h_dir = project_root / ".apex" / "handoff"
    h_dir.mkdir(parents=True)
    for slug in ("s1", "s2", "s3"):
        f = h_dir / f"{slug}.md"
        f.write_text("body")
        old = time.time() - 8 * 86400
        os.utime(f, (old, old))
    props = d.analyze_stale_handoffs(project_root)
    assert len(props) == 1
    assert props[0].evidence["count"] == 3


# ── run_doctor end-to-end ────────────────────────────────────────────────

def test_run_doctor_clean_db(project_root: Path) -> None:
    run = d.run_doctor(project_root, trigger="test")
    assert run.status == "done"
    assert run.run_id > 0
    assert run.proposals_count == 0
    md = project_root / ".apex" / "doctor" / f"{run.run_id:04d}.md"
    assert md.exists()
    assert "Sin hallazgos" in md.read_text()


def test_run_doctor_with_findings(project_root: Path, db_path: Path) -> None:
    _insert_error(db_path, description="recurring boom", severity="critical",
                   recurrence=5)
    _insert_grader_verdict(db_path, phase=2, issues=["x"], reasoning="r1")
    _insert_grader_verdict(db_path, phase=8, issues=["x"], reasoning="r2")

    run = d.run_doctor(project_root, trigger="test")
    assert run.status == "done"
    assert run.proposals_count == 2
    md = project_root / ".apex" / "doctor" / f"{run.run_id:04d}.md"
    text = md.read_text()
    assert "override_cluster" in text or "Errores recurrentes" in text
    assert "grader_block_pattern" in text or "Patrones del grader" in text


def test_run_doctor_idempotent_signatures(project_root: Path,
                                            db_path: Path) -> None:
    _insert_error(db_path, description="boom", severity="critical",
                   recurrence=1)

    run1 = d.run_doctor(project_root, trigger="test1", force=True)
    assert run1.proposals_count == 1
    # Segundo run con la misma evidencia: la propuesta YA existe (UNIQUE),
    # por lo que el segundo run no añade duplicados
    run2 = d.run_doctor(project_root, trigger="test2", force=True)
    assert run2.proposals_count == 0


# ── Throttle ─────────────────────────────────────────────────────────────

def test_throttle_blocks_second_run(project_root: Path) -> None:
    run1 = d.run_doctor(project_root, trigger="t1")
    assert run1.status == "done"
    run2 = d.run_doctor(project_root, trigger="t2")
    assert run2.status == "throttled"
    assert "cooldown" in run2.skipped_reason


def test_force_skips_throttle(project_root: Path) -> None:
    d.run_doctor(project_root, trigger="t1")
    run2 = d.run_doctor(project_root, trigger="t2", force=True)
    assert run2.status == "done"


def test_is_throttled_false_on_clean_db(db_path: Path) -> None:
    assert d.is_throttled(db_path) is False


# ── session_starts ──────────────────────────────────────────────────────

def test_record_session_start_returns_true_first_time(db_path: Path) -> None:
    assert d.record_session_start(db_path, "sess-001") is True


def test_record_session_start_idempotent(db_path: Path) -> None:
    d.record_session_start(db_path, "sess-001")
    assert d.record_session_start(db_path, "sess-001") is False


def test_record_session_start_empty_id(db_path: Path) -> None:
    assert d.record_session_start(db_path, "") is False


def test_session_age_seconds_unknown(db_path: Path) -> None:
    assert d.session_age_seconds(db_path, "ghost") is None


def test_session_age_seconds_for_known(db_path: Path) -> None:
    d.record_session_start(db_path, "sess-known")
    age = d.session_age_seconds(db_path, "sess-known")
    assert age is not None
    assert 0 <= age < 5  # acabamos de insertarlo


def test_session_started_at_backdate(db_path: Path) -> None:
    """Si manualmente backdatemos un session_start, session_age refleja la
    diferencia."""
    past = (datetime.now(timezone.utc) - timedelta(hours=4)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO session_starts (session_id, started_at) VALUES (?, ?)",
            ("sess-old", past),
        )
        conn.commit()
    finally:
        conn.close()
    age = d.session_age_seconds(db_path, "sess-old")
    assert age is not None
    assert age >= 3.5 * 3600


# ── Persistencia helpers ────────────────────────────────────────────────

def test_record_proposal_returns_id(db_path: Path) -> None:
    run_id = d._start_run(db_path, trigger="t")
    p = d.DoctorProposal(kind="override_cluster", signature="abc",
                          title="t", body="b")
    pid = d.record_proposal(db_path, run_id, p)
    assert pid is not None and pid > 0


def test_record_proposal_dedup(db_path: Path) -> None:
    run_id = d._start_run(db_path, trigger="t")
    p = d.DoctorProposal(kind="override_cluster", signature="abc",
                          title="t", body="b")
    d.record_proposal(db_path, run_id, p)
    second = d.record_proposal(db_path, run_id, p)
    assert second is None


def test_list_recent_proposals_filters_by_status(db_path: Path,
                                                   project_root: Path) -> None:
    run_id = d._start_run(db_path, trigger="t")
    p = d.DoctorProposal(kind="override_cluster", signature="abc",
                          title="t", body="b")
    d.record_proposal(db_path, run_id, p)
    open_props = d.list_recent_proposals(db_path, status="open")
    assert len(open_props) == 1
    done_props = d.list_recent_proposals(db_path, status="done")
    assert done_props == []


# ── Markdown rendering ─────────────────────────────────────────────────

def test_render_run_md_empty(project_root: Path) -> None:
    run = d.DoctorRun(
        run_id=1, started_at="x", finished_at="y",
        proposals=[], trigger="t", status="done",
    )
    md = d.render_run_md(run, project_root)
    assert "Apex-doctor run #1" in md
    assert "Sin hallazgos" in md


def test_render_run_md_with_proposals(project_root: Path) -> None:
    p = d.DoctorProposal(
        kind="override_cluster", signature="sig",
        title="Algo recurrente", body="## detalle\n\nfoo",
    )
    run = d.DoctorRun(
        run_id=2, started_at="x", finished_at="y",
        proposals=[p], trigger="t", status="done",
    )
    md = d.render_run_md(run, project_root)
    assert "Algo recurrente" in md
    assert "## detalle" in md
    assert "Errores recurrentes" in md


# ── short_summary ──────────────────────────────────────────────────────

def test_short_summary_throttled() -> None:
    run = d.DoctorRun(run_id=0, started_at="x", finished_at="",
                       proposals=[], trigger="t", status="throttled",
                       skipped_reason="cooldown")
    assert "saltado" in d.short_summary(run)


def test_short_summary_no_findings() -> None:
    run = d.DoctorRun(run_id=5, started_at="x", finished_at="y",
                       proposals=[], trigger="t", status="done")
    s = d.short_summary(run)
    assert "sin hallazgos" in s
    assert "#5" in s


def test_short_summary_with_findings() -> None:
    p = d.DoctorProposal(kind="stale_handoff", signature="s",
                          title="t", body="b")
    run = d.DoctorRun(run_id=7, started_at="x", finished_at="y",
                       proposals=[p], trigger="t", status="done")
    s = d.short_summary(run)
    assert "1 propuesta" in s
    assert "stale_handoff" in s
    assert "0007.md" in s
