"""Tests Sprint 13.9 — usage_data_reader + A5 grader_false_positives + A6
friction_recurrence (cruce con `~/.claude/usage-data/`).

Cubre:

- Reader: iter_meta filtra por project_path, salta JSON corrupto, devuelve
  vacío si dir no existe; iter_facets filtra por session_ids;
  find_session_for_timestamp respeta rango y slack.
- A5: vacío en BD limpia, no fire bajo threshold, fire al threshold,
  signature por fase, no fire si facet outcome=unclear ni helpfulness/sat ok.
- A6: vacío sin facets, filtra por project_path, fire al threshold,
  no fire bajo threshold de sesiones únicas.
- Integración con run_doctor: A5/A6 se invocan, render_run_md incluye nuevos
  títulos.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from context_db import ApexContextDB  # noqa: E402
import apex_doctor as d  # noqa: E402
import usage_data_reader as udr  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    (tmp_path / ".apex").mkdir()
    db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
    _run(db.initialize())
    return tmp_path


@pytest.fixture
def db_path(project_root: Path) -> Path:
    return project_root / ".apex" / "context.db"


@pytest.fixture
def usage_root(tmp_path: Path) -> Path:
    """Crea un root de usage-data simulado (vacío) y los subdirs."""
    root = tmp_path / "usage-data"
    (root / "session-meta").mkdir(parents=True)
    (root / "facets").mkdir(parents=True)
    return root


def _write_meta(usage_root: Path, *, sid: str, project_path: str,
                start: datetime, duration_min: int = 30,
                tool_errors: int = 0,
                tool_error_categories: dict | None = None) -> None:
    payload = {
        "session_id": sid,
        "project_path": project_path,
        "start_time": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "duration_minutes": duration_min,
        "tool_counts": {"Bash": 5, "Edit": 3},
        "tool_errors": tool_errors,
        "tool_error_categories": tool_error_categories or {},
        "git_commits": 0,
        "git_pushes": 0,
        "input_tokens": 100,
        "output_tokens": 200,
        "lines_added": 10,
        "lines_removed": 0,
        "files_modified": 1,
        "user_message_count": 4,
        "assistant_message_count": 5,
        "languages": {},
        "first_prompt": "",
        "user_interruptions": 0,
        "user_response_times": [],
        "uses_task_agent": False,
        "uses_mcp": False,
        "uses_web_search": False,
        "uses_web_fetch": False,
        "message_hours": [],
        "user_message_timestamps": [],
    }
    (usage_root / "session-meta" / f"{sid}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_facet(usage_root: Path, *, sid: str, outcome: str = "fully_achieved",
                  helpfulness: str = "very_helpful",
                  user_satisfaction: dict | None = None,
                  friction_counts: dict | None = None,
                  friction_detail: str = "",
                  brief: str = "test session") -> None:
    payload = {
        "session_id": sid,
        "underlying_goal": "test",
        "goal_categories": {"feature_implementation": 1},
        "outcome": outcome,
        "user_satisfaction_counts": user_satisfaction or {"likely_satisfied": 1},
        "claude_helpfulness": helpfulness,
        "session_type": "single_task",
        "friction_counts": friction_counts or {},
        "friction_detail": friction_detail,
        "primary_success": "multi_file_changes",
        "brief_summary": brief,
    }
    (usage_root / "facets" / f"{sid}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _insert_verdict(db_path: Path, *, phase: int, should_block: int = 0,
                     reasoning: str = "ok",
                     created_at: datetime | None = None) -> int:
    conn = sqlite3.connect(str(db_path))
    try:
        if created_at is not None:
            cur = conn.execute(
                "INSERT INTO grader_verdicts (phase, quality, issues, "
                "should_block, reasoning, created_at) "
                "VALUES (?, ?, '[]', ?, ?, ?)",
                (phase, 3, should_block, reasoning,
                 created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")),
            )
        else:
            cur = conn.execute(
                "INSERT INTO grader_verdicts (phase, quality, issues, "
                "should_block, reasoning) VALUES (?, ?, '[]', ?, ?)",
                (phase, 3, should_block, reasoning),
            )
        conn.commit()
        return int(cur.lastrowid or 0)
    finally:
        conn.close()


# ── Reader: iter_meta ─────────────────────────────────────────────────────

def test_iter_meta_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    missing = tmp_path / "noexiste"
    assert list(udr.iter_meta(root=missing)) == []


def test_iter_meta_filters_by_project_path(usage_root: Path) -> None:
    base = datetime(2026, 5, 3, 10, tzinfo=timezone.utc)
    _write_meta(usage_root, sid="sid-A1", project_path="/proj/A", start=base)
    _write_meta(usage_root, sid="sid-A2", project_path="/proj/A",
                start=base + timedelta(hours=1))
    _write_meta(usage_root, sid="sid-B1", project_path="/proj/B",
                start=base + timedelta(hours=2))
    only_a = list(udr.iter_meta(project_path="/proj/A", root=usage_root))
    assert len(only_a) == 2
    assert all(m.project_path == "/proj/A" for m in only_a)


def test_iter_meta_skips_invalid_json(usage_root: Path) -> None:
    _write_meta(usage_root, sid="ok-1", project_path="/p",
                start=datetime(2026, 5, 3, tzinfo=timezone.utc))
    (usage_root / "session-meta" / "broken.json").write_text("{not-json", encoding="utf-8")
    metas = list(udr.iter_meta(root=usage_root))
    assert len(metas) == 1
    assert metas[0].session_id == "ok-1"


# ── Reader: iter_facets ───────────────────────────────────────────────────

def test_iter_facets_filters_by_session_ids(usage_root: Path) -> None:
    for sid in ("a", "b", "c"):
        _write_facet(usage_root, sid=sid)
    sel = list(udr.iter_facets(session_ids={"a", "c"}, root=usage_root))
    assert {f.session_id for f in sel} == {"a", "c"}


def test_iter_facets_returns_empty_when_dir_missing(tmp_path: Path) -> None:
    assert list(udr.iter_facets(root=tmp_path / "missing")) == []


# ── Reader: find_session_for_timestamp ────────────────────────────────────

def test_find_session_for_timestamp_matches_within_range(usage_root: Path) -> None:
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    _write_meta(usage_root, sid="s-mid", project_path="/p",
                start=base, duration_min=30)
    found = udr.find_session_for_timestamp(
        base + timedelta(minutes=15), "/p", root=usage_root
    )
    assert found == "s-mid"


def test_find_session_for_timestamp_no_match_outside_range(usage_root: Path) -> None:
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    _write_meta(usage_root, sid="s-only", project_path="/p",
                start=base, duration_min=30)
    found = udr.find_session_for_timestamp(
        base + timedelta(hours=2), "/p", root=usage_root
    )
    assert found is None


def test_find_session_respects_project_filter(usage_root: Path) -> None:
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    _write_meta(usage_root, sid="s-other", project_path="/other",
                start=base, duration_min=30)
    found = udr.find_session_for_timestamp(
        base + timedelta(minutes=15), "/p", root=usage_root
    )
    assert found is None


# ── A5 grader_false_positives ─────────────────────────────────────────────

def test_a5_empty_on_clean_db(db_path: Path, project_root: Path,
                                usage_root: Path) -> None:
    assert d.analyze_grader_false_positives(
        db_path, project_root, usage_root=usage_root
    ) == []


def test_a5_under_threshold_does_not_fire(db_path: Path, project_root: Path,
                                            usage_root: Path) -> None:
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    _write_meta(usage_root, sid="sid-1", project_path=str(project_root.resolve()),
                start=base)
    _write_facet(usage_root, sid="sid-1", outcome="not_achieved")
    _insert_verdict(db_path, phase=5, should_block=0,
                    created_at=base + timedelta(minutes=5))
    assert d.analyze_grader_false_positives(
        db_path, project_root, usage_root=usage_root
    ) == []


def test_a5_fires_when_two_false_positives_same_phase(
    db_path: Path, project_root: Path, usage_root: Path
) -> None:
    project_path = str(project_root.resolve())
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    for i, sid in enumerate(("sid-A", "sid-B")):
        start = base + timedelta(hours=i)
        _write_meta(usage_root, sid=sid, project_path=project_path, start=start)
        _write_facet(usage_root, sid=sid, outcome="not_achieved",
                      helpfulness="unhelpful", brief=f"sesion mala {sid}")
        _insert_verdict(db_path, phase=5, should_block=0,
                        created_at=start + timedelta(minutes=10))
    proposals = d.analyze_grader_false_positives(
        db_path, project_root, usage_root=usage_root
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.kind == "grader_false_positive"
    assert p.signature == "grader_false_positive:phase=5"
    assert p.evidence["phase"] == 5
    assert p.evidence["false_positive_count"] == 2


def test_a5_does_not_fire_when_outcome_is_unclear(
    db_path: Path, project_root: Path, usage_root: Path
) -> None:
    """outcome=unclear_from_transcript no debe contar como mal."""
    project_path = str(project_root.resolve())
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    for i, sid in enumerate(("c-1", "c-2")):
        start = base + timedelta(hours=i)
        _write_meta(usage_root, sid=sid, project_path=project_path, start=start)
        _write_facet(usage_root, sid=sid, outcome="unclear_from_transcript",
                      helpfulness="moderately_helpful")
        _insert_verdict(db_path, phase=5, should_block=0,
                        created_at=start + timedelta(minutes=10))
    assert d.analyze_grader_false_positives(
        db_path, project_root, usage_root=usage_root
    ) == []


def test_a5_signature_per_phase(db_path: Path, project_root: Path,
                                  usage_root: Path) -> None:
    project_path = str(project_root.resolve())
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    sids_phases = [
        ("p5-a", 5), ("p5-b", 5), ("p7-a", 7), ("p7-b", 7),
    ]
    for i, (sid, phase) in enumerate(sids_phases):
        start = base + timedelta(hours=i)
        _write_meta(usage_root, sid=sid, project_path=project_path, start=start)
        _write_facet(usage_root, sid=sid, outcome="not_achieved")
        _insert_verdict(db_path, phase=phase, should_block=0,
                        created_at=start + timedelta(minutes=10))
    proposals = d.analyze_grader_false_positives(
        db_path, project_root, usage_root=usage_root
    )
    sigs = {p.signature for p in proposals}
    assert sigs == {
        "grader_false_positive:phase=5",
        "grader_false_positive:phase=7",
    }


def test_a5_ignores_blocked_verdicts(db_path: Path, project_root: Path,
                                       usage_root: Path) -> None:
    """should_block=1 son verdicts donde el grader bloqueó — no son falsos
    positivos por definición, los cubre A2."""
    project_path = str(project_root.resolve())
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    for i, sid in enumerate(("b-1", "b-2")):
        start = base + timedelta(hours=i)
        _write_meta(usage_root, sid=sid, project_path=project_path, start=start)
        _write_facet(usage_root, sid=sid, outcome="not_achieved")
        _insert_verdict(db_path, phase=5, should_block=1,
                        created_at=start + timedelta(minutes=10))
    assert d.analyze_grader_false_positives(
        db_path, project_root, usage_root=usage_root
    ) == []


# ── A6 friction_recurrence ────────────────────────────────────────────────

def test_a6_empty_when_no_meta(project_root: Path, usage_root: Path) -> None:
    assert d.analyze_friction_recurrence(
        project_root, usage_root=usage_root
    ) == []


def test_a6_filters_by_project_path(project_root: Path, usage_root: Path) -> None:
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    # Sesion DEL proyecto sin friction
    _write_meta(usage_root, sid="own", project_path=str(project_root.resolve()),
                start=base)
    _write_facet(usage_root, sid="own")
    # Sesion de OTRO proyecto con friction (no debe contar)
    _write_meta(usage_root, sid="other-1", project_path="/other/proj", start=base)
    _write_facet(usage_root, sid="other-1",
                  friction_counts={"wrong_approach": 5})
    _write_meta(usage_root, sid="other-2", project_path="/other/proj",
                start=base + timedelta(hours=1))
    _write_facet(usage_root, sid="other-2",
                  friction_counts={"wrong_approach": 5})
    assert d.analyze_friction_recurrence(
        project_root, usage_root=usage_root
    ) == []


def test_a6_fires_at_threshold(project_root: Path, usage_root: Path) -> None:
    project_path = str(project_root.resolve())
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    # Dos sesiones distintas, friction wrong_approach total = 4 (>=3) en
    # 2 sesiones (>=2)
    _write_meta(usage_root, sid="s1", project_path=project_path, start=base)
    _write_facet(usage_root, sid="s1",
                  friction_counts={"wrong_approach": 2},
                  friction_detail="Claude eligió enfoque equivocado en spec")
    _write_meta(usage_root, sid="s2", project_path=project_path,
                start=base + timedelta(hours=2))
    _write_facet(usage_root, sid="s2",
                  friction_counts={"wrong_approach": 2},
                  friction_detail="otro caso de wrong_approach")
    proposals = d.analyze_friction_recurrence(
        project_root, usage_root=usage_root
    )
    assert len(proposals) == 1
    p = proposals[0]
    assert p.kind == "friction_recurrence"
    assert p.signature == "friction_recurrence:wrong_approach"
    assert p.evidence["friction_key"] == "wrong_approach"
    assert p.evidence["total_occurrences"] == 4
    assert p.evidence["affected_sessions"] == 2


def test_a6_no_fire_under_session_threshold(
    project_root: Path, usage_root: Path
) -> None:
    """5 ocurrencias en 1 sesión → no fire (umbral sesiones distintas=2)."""
    project_path = str(project_root.resolve())
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    _write_meta(usage_root, sid="solo", project_path=project_path, start=base)
    _write_facet(usage_root, sid="solo",
                  friction_counts={"buggy_code": 5})
    assert d.analyze_friction_recurrence(
        project_root, usage_root=usage_root
    ) == []


# ── Integración con run_doctor + render ──────────────────────────────────

def test_run_doctor_invokes_a5_a6_when_usage_data_present(
    db_path: Path, project_root: Path, usage_root: Path,
    monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APEX_USAGE_DATA_ROOT", str(usage_root))
    project_path = str(project_root.resolve())
    base = datetime(2026, 5, 3, 10, 0, tzinfo=timezone.utc)
    # Setup A5: 2 falsos positivos en fase 5
    for i, sid in enumerate(("a5-1", "a5-2")):
        start = base + timedelta(hours=i)
        _write_meta(usage_root, sid=sid, project_path=project_path, start=start)
        _write_facet(usage_root, sid=sid, outcome="not_achieved",
                      friction_counts={"wrong_approach": 2})
        _insert_verdict(db_path, phase=5, should_block=0,
                        created_at=start + timedelta(minutes=10))
    run = d.run_doctor(project_root, trigger="manual", force=True)
    assert run.status == "done"
    kinds = {p.kind for p in run.proposals}
    assert "grader_false_positive" in kinds
    assert "friction_recurrence" in kinds


def test_render_run_md_includes_new_kind_titles(project_root: Path) -> None:
    run = d.DoctorRun(
        run_id=42,
        started_at="2026-05-03T19:00:00",
        finished_at="2026-05-03T19:00:01",
        proposals=[
            d.DoctorProposal(
                kind="grader_false_positive",
                signature="grader_false_positive:phase=5",
                title="Grader laxo en fase 5",
                body="cuerpo A5",
            ),
            d.DoctorProposal(
                kind="friction_recurrence",
                signature="friction_recurrence:wrong_approach",
                title="Friction wrong_approach recurrente",
                body="cuerpo A6",
            ),
        ],
        trigger="manual",
        status="done",
    )
    md = d.render_run_md(run, project_root)
    assert "Grader laxo (cruce con observer Claude Code)" in md
    assert "Friction recurrente del observer" in md
    assert "cuerpo A5" in md
    assert "cuerpo A6" in md
