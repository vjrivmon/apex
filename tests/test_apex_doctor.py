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


# ── Sprint 13.8 — Hub bridge: project_id, hub conn, schema ─────────────────

import json as _json  # noqa: E402


@pytest.fixture
def hub_db(tmp_path: Path) -> Path:
    """Crea hub.db vacío en una ruta temp y aplica el schema."""
    p = tmp_path / "hub.db"
    conn = sqlite3.connect(str(p))
    conn.executescript(d._HUB_SCHEMA)
    conn.commit()
    conn.close()
    return p


def _insert_hub_verdict(hub_db: Path, *, project_id: str, original_id: int,
                        phase: int, issues: list[str], status: str = "blocked",
                        created_at: str = "2026-05-03T10:00:00") -> None:
    conn = sqlite3.connect(str(hub_db))
    try:
        conn.execute(
            "INSERT INTO grader_verdicts (project_id, original_id, phase, "
            "question_index, status, issues_json, suggestion, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (project_id, original_id, phase, phase, status,
             _json.dumps(issues), "test suggestion", created_at),
        )
        conn.commit()
    finally:
        conn.close()


def test_project_id_from_root_lowercases(tmp_path: Path) -> None:
    p = tmp_path / "MyProject"
    p.mkdir()
    assert d._project_id_from_root(p) == "myproject"


def test_project_id_from_root_handles_kebab() -> None:
    p = Path("/home/x/RoadToDevOps/TFG-Tutor-Virtual")
    # No resuelve fs, sólo nombre
    assert d._project_id_from_root(p) == "tfg-tutor-virtual"


def test_resolve_hub_db_explicit_arg_wins(tmp_path: Path,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    real = tmp_path / "real.db"
    real.touch()
    monkeypatch.setenv("APEX_HUB_DB_PATH", "/no/existe.db")
    assert d._resolve_hub_db(real) == real


def test_resolve_hub_db_env_overrides_default(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    custom = tmp_path / "custom.db"
    custom.touch()
    monkeypatch.setenv("APEX_HUB_DB_PATH", str(custom))
    assert d._resolve_hub_db(None) == custom


def test_resolve_hub_db_returns_none_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APEX_HUB_DB_PATH", "/path/that/never/exists.db")
    assert d._resolve_hub_db(None) is None


def test_hub_conn_returns_none_for_missing() -> None:
    assert d._hub_conn(None) is None
    assert d._hub_conn(Path("/no/existe.db")) is None


def test_ensure_hub_schema_creates_tables(tmp_path: Path) -> None:
    p = tmp_path / "fresh.db"
    conn = sqlite3.connect(str(p))
    assert d._ensure_hub_schema(conn) is True
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    conn.close()
    assert {"doctor_tickets", "grader_verdicts"} <= tables


# ── Sprint 13.8.B — sync_local_verdicts_to_hub ─────────────────────────────

def test_sync_no_op_when_hub_missing(db_path: Path) -> None:
    _insert_grader_verdict(db_path, phase=5, issues=["mock_data"])
    assert d.sync_local_verdicts_to_hub(db_path, None, "apex") == 0
    assert d.sync_local_verdicts_to_hub(db_path, Path("/no/x.db"), "apex") == 0


def test_sync_copies_local_verdicts_to_hub(db_path: Path, hub_db: Path) -> None:
    _insert_grader_verdict(db_path, phase=5, issues=["mock_data"],
                           reasoning="usa datos hardcodeados")
    n = d.sync_local_verdicts_to_hub(db_path, hub_db, "apex")
    assert n == 1

    conn = sqlite3.connect(str(hub_db))
    rows = conn.execute(
        "SELECT project_id, original_id, phase, status, issues_json, suggestion "
        "FROM grader_verdicts"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    project_id, original_id, phase, status, issues_json, suggestion = rows[0]
    assert project_id == "apex"
    assert original_id == 1
    assert phase == 5
    assert status == "blocked"
    assert _json.loads(issues_json) == ["mock_data"]
    assert "usa datos hardcodeados" in suggestion


def test_sync_maps_should_block_zero_to_ok(db_path: Path, hub_db: Path) -> None:
    _insert_grader_verdict(db_path, phase=3, issues=[],
                           should_block=0, reasoning="ok")
    d.sync_local_verdicts_to_hub(db_path, hub_db, "apex")
    conn = sqlite3.connect(str(hub_db))
    status = conn.execute("SELECT status FROM grader_verdicts").fetchone()[0]
    conn.close()
    assert status == "ok"


def test_sync_idempotent_on_repeated_runs(db_path: Path, hub_db: Path) -> None:
    _insert_grader_verdict(db_path, phase=5, issues=["x"])
    n1 = d.sync_local_verdicts_to_hub(db_path, hub_db, "apex")
    n2 = d.sync_local_verdicts_to_hub(db_path, hub_db, "apex")
    assert n1 == 1
    assert n2 == 0
    conn = sqlite3.connect(str(hub_db))
    total = conn.execute("SELECT COUNT(*) FROM grader_verdicts").fetchone()[0]
    conn.close()
    assert total == 1


def test_sync_separates_by_project_id(db_path: Path, hub_db: Path) -> None:
    _insert_grader_verdict(db_path, phase=5, issues=["x"])
    # Mismo original_id pero distinto project_id → debe coexistir
    d.sync_local_verdicts_to_hub(db_path, hub_db, "apex")
    d.sync_local_verdicts_to_hub(db_path, hub_db, "focusnow")
    conn = sqlite3.connect(str(hub_db))
    n = conn.execute("SELECT COUNT(*) FROM grader_verdicts").fetchone()[0]
    conn.close()
    assert n == 2


def test_sync_creates_hub_schema_if_missing(db_path: Path, tmp_path: Path) -> None:
    """Sync sobre hub.db existente pero sin tablas debe crearlas."""
    bare = tmp_path / "bare.db"
    sqlite3.connect(str(bare)).close()  # crea fichero sin schema
    _insert_grader_verdict(db_path, phase=5, issues=["x"])
    n = d.sync_local_verdicts_to_hub(db_path, bare, "apex")
    assert n == 1


# ── Sprint 13.8.C — A4 cross_project_patterns ─────────────────────────────

def test_a4_no_op_when_hub_missing() -> None:
    assert d.analyze_cross_project_patterns(None, "apex") == []
    assert d.analyze_cross_project_patterns(Path("/no/x.db"), "apex") == []


def test_a4_returns_empty_for_single_project(hub_db: Path) -> None:
    _insert_hub_verdict(hub_db, project_id="apex", original_id=1, phase=5,
                        issues=["mock_data"])
    _insert_hub_verdict(hub_db, project_id="apex", original_id=2, phase=6,
                        issues=["mock_data"])
    assert d.analyze_cross_project_patterns(hub_db, "apex") == []


def test_a4_detects_issue_in_two_projects(hub_db: Path) -> None:
    _insert_hub_verdict(hub_db, project_id="focusnow", original_id=1,
                        phase=5, issues=["mock_data"])
    _insert_hub_verdict(hub_db, project_id="tfg-tutor-virtual",
                        original_id=2, phase=4, issues=["mock_data"])
    props = d.analyze_cross_project_patterns(hub_db, "apex")
    assert len(props) == 1
    p = props[0]
    assert p.kind == "cross_project_pattern"
    assert p.signature == "cross_project_pattern:mock_data"
    assert p.evidence["projects"] == ["focusnow", "tfg-tutor-virtual"]
    assert p.evidence["current_project"] == "apex"
    assert "mock_data" in p.title


def test_a4_ignores_non_blocked_status(hub_db: Path) -> None:
    _insert_hub_verdict(hub_db, project_id="focusnow", original_id=1,
                        phase=5, issues=["x"], status="ok")
    _insert_hub_verdict(hub_db, project_id="apex", original_id=2,
                        phase=5, issues=["x"], status="ok")
    assert d.analyze_cross_project_patterns(hub_db, "apex") == []


def test_a4_handles_malformed_issues_json(hub_db: Path) -> None:
    conn = sqlite3.connect(str(hub_db))
    conn.execute(
        "INSERT INTO grader_verdicts (project_id, original_id, phase, "
        "status, issues_json, created_at) VALUES (?,?,?,?,?,?)",
        ("focusnow", 1, 5, "blocked", "not-json{{", "2026-05-03"),
    )
    conn.commit()
    conn.close()
    # No debe crashear; sólo ignora la fila malformada
    assert d.analyze_cross_project_patterns(hub_db, "apex") == []


def test_a4_signature_stable_across_runs(hub_db: Path) -> None:
    _insert_hub_verdict(hub_db, project_id="focusnow", original_id=1,
                        phase=5, issues=["mock_data"])
    _insert_hub_verdict(hub_db, project_id="apex", original_id=2,
                        phase=5, issues=["mock_data"])
    p1 = d.analyze_cross_project_patterns(hub_db, "apex")[0]
    p2 = d.analyze_cross_project_patterns(hub_db, "apex")[0]
    assert p1.signature_hash() == p2.signature_hash()


# ── Sprint 13.8.D — post_ticket_to_hub ─────────────────────────────────────

def _make_cp_proposal() -> "d.DoctorProposal":
    return d.DoctorProposal(
        kind="cross_project_pattern",
        signature="cross_project_pattern:mock_data",
        title="Issue mock_data en 2 proyectos",
        body="## Patrón\n\nbody",
        evidence={"issue": "mock_data",
                  "projects": ["focusnow", "tfg-tutor-virtual"],
                  "current_project": "apex"},
    )


def test_post_ticket_no_op_when_hub_missing() -> None:
    p = _make_cp_proposal()
    assert d.post_ticket_to_hub(p, None) is False
    assert d.post_ticket_to_hub(p, Path("/no/x.db")) is False


def test_post_ticket_inserts_first_time(hub_db: Path) -> None:
    p = _make_cp_proposal()
    assert d.post_ticket_to_hub(p, hub_db) is True
    conn = sqlite3.connect(str(hub_db))
    rows = conn.execute(
        "SELECT kind, signature, source_projects_json, status FROM doctor_tickets"
    ).fetchall()
    conn.close()
    assert len(rows) == 1
    kind, sig, src_json, status = rows[0]
    assert kind == "cross_project_pattern"
    assert sig == "cross_project_pattern:mock_data"
    assert _json.loads(src_json) == ["focusnow", "tfg-tutor-virtual"]
    assert status == "open"


def test_post_ticket_dedup_on_signature(hub_db: Path) -> None:
    p = _make_cp_proposal()
    assert d.post_ticket_to_hub(p, hub_db) is True
    assert d.post_ticket_to_hub(p, hub_db) is False
    conn = sqlite3.connect(str(hub_db))
    n = conn.execute("SELECT COUNT(*) FROM doctor_tickets").fetchone()[0]
    conn.close()
    assert n == 1


# ── Sprint 13.8.E — run_doctor con hub_db ──────────────────────────────────

def test_run_doctor_backward_compat_no_hub(project_root: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin hub_db arg y env apuntando a path inexistente: A1-A3 corren,
    A4 devuelve [], no crashea."""
    monkeypatch.setenv("APEX_HUB_DB_PATH", "/tmp/no-existe-hub-doctor.db")
    run = d.run_doctor(project_root, trigger="manual", force=True)
    assert run.status == "done"
    # Cero propuestas en BD limpia
    assert run.proposals_count == 0


def test_run_doctor_with_hub_runs_a4_and_sync(project_root: Path,
                                              db_path: Path,
                                              hub_db: Path) -> None:
    """Verdict local se sincroniza, A4 detecta cross-project, ticket posteado."""
    # Local verdict en este proyecto
    _insert_grader_verdict(db_path, phase=5, issues=["mock_data"])
    # Verdicts del hub en otro proyecto (mismo issue)
    _insert_hub_verdict(hub_db, project_id="focusnow", original_id=99,
                        phase=5, issues=["mock_data"])

    run = d.run_doctor(project_root, trigger="manual", force=True,
                        hub_db=hub_db)
    assert run.status == "done"

    # Sync: el verdict local debería estar ahora en hub.grader_verdicts
    project_id = d._project_id_from_root(project_root)
    conn = sqlite3.connect(str(hub_db))
    n_synced = conn.execute(
        "SELECT COUNT(*) FROM grader_verdicts WHERE project_id=?",
        (project_id,),
    ).fetchone()[0]
    # A4: debió detectar 'mock_data' en focusnow + project_id (este)
    cp_props = [p for p in run.proposals if p.kind == "cross_project_pattern"]
    # Ticket: posteado al hub
    n_tickets = conn.execute(
        "SELECT COUNT(*) FROM doctor_tickets WHERE kind='cross_project_pattern'"
    ).fetchone()[0]
    conn.close()

    assert n_synced == 1
    assert len(cp_props) == 1
    assert n_tickets == 1


def test_run_doctor_cp_proposal_only_posts_once(project_root: Path,
                                                db_path: Path,
                                                hub_db: Path) -> None:
    """Re-ejecutar run_doctor con misma evidencia no duplica tickets."""
    _insert_grader_verdict(db_path, phase=5, issues=["x"])
    _insert_hub_verdict(hub_db, project_id="focusnow", original_id=1,
                        phase=5, issues=["x"])
    d.run_doctor(project_root, trigger="manual", force=True, hub_db=hub_db)
    d.run_doctor(project_root, trigger="manual", force=True, hub_db=hub_db)
    conn = sqlite3.connect(str(hub_db))
    n = conn.execute(
        "SELECT COUNT(*) FROM doctor_tickets"
    ).fetchone()[0]
    conn.close()
    assert n == 1


# ── render_run_md con cross_project_pattern ────────────────────────────────

def test_render_run_md_cross_project_kind_title(project_root: Path) -> None:
    p = d.DoctorProposal(
        kind="cross_project_pattern",
        signature="cross_project_pattern:x",
        title="Issue x cross",
        body="body",
        evidence={"projects": ["a", "b"]},
    )
    run = d.DoctorRun(run_id=1, started_at="x", finished_at="y",
                      proposals=[p], trigger="manual", status="done")
    md = d.render_run_md(run, project_root)
    assert "## Patrones cross-project (1)" in md
    assert "Issue x cross" in md
