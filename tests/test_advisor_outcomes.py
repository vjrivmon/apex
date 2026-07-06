"""Sprint 16.2 — motor implícito de outcomes (rating vía facets).

`lib/advisor_outcomes.compute_outcomes` cruza `advisor_advice` con
`~/.claude/usage-data/facets/` vía heurística temporal del Sprint 13.9.
Para cada advice sin outcome temporal previo, asocia con la sesión que
contenía su `created_at` (slack 5 min), lee el facet asociado e infiere
`useful` / `not_useful` / `unclear` según blueprint S16 §3.

Tests previstos (blueprint S16 §11): asociación temporal, inferencia
rating en cada caso (useful/not_useful/unclear), facet ausente devuelve
`no_facet_yet`, idempotencia (no duplica), `force` recomputa,
`lookback_days` filtra.
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
import advisor_outcomes as ao  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "ctx.db"
    db = ApexContextDB(str(p))
    _run(db.initialize())
    return p


@pytest.fixture
def usage_root(tmp_path: Path) -> Path:
    root = tmp_path / "usage-data"
    (root / "session-meta").mkdir(parents=True)
    (root / "facets").mkdir(parents=True)
    return root


@pytest.fixture
def project_path() -> str:
    return "/proj/test"


# ── Helpers ───────────────────────────────────────────────────────────


def _seed_advice(
    db_path: Path,
    *,
    created_at: datetime | None = None,
    review_id: int | None = None,
    kind: str = "phase_drift",
    title: str = "T",
) -> int:
    """Inserta un advisor_advice (creando review si falta). Devuelve advice_id."""
    with sqlite3.connect(str(db_path)) as c:
        if review_id is None:
            cur = c.execute(
                "INSERT INTO advisor_reviews (session_id, trigger_kind, status) "
                "VALUES ('s1', 'manual', 'completed')"
            )
            review_id = cur.lastrowid
        if created_at is not None:
            ts = created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            cur = c.execute(
                "INSERT INTO advisor_advice "
                "(review_id, kind, severity, title, body, created_at) "
                "VALUES (?, ?, 'warn', ?, 'B', ?)",
                (review_id, kind, title, ts),
            )
        else:
            cur = c.execute(
                "INSERT INTO advisor_advice "
                "(review_id, kind, severity, title, body) "
                "VALUES (?, ?, 'warn', ?, 'B')",
                (review_id, kind, title),
            )
        c.commit()
        return int(cur.lastrowid)


def _write_meta(
    usage_root: Path,
    *,
    sid: str,
    project_path: str,
    start: datetime,
    duration_min: int = 30,
) -> None:
    payload = {
        "session_id": sid,
        "project_path": project_path,
        "start_time": start.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
        "duration_minutes": duration_min,
        "tool_counts": {},
        "tool_errors": 0,
        "tool_error_categories": {},
        "git_commits": 0,
        "lines_added": 0,
        "lines_removed": 0,
        "files_modified": 0,
    }
    (usage_root / "session-meta" / f"{sid}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_facet(
    usage_root: Path,
    *,
    sid: str,
    outcome: str = "fully_achieved",
    helpfulness: str = "very_helpful",
    user_satisfaction: dict | None = None,
    friction_counts: dict | None = None,
) -> None:
    payload = {
        "session_id": sid,
        "outcome": outcome,
        "claude_helpfulness": helpfulness,
        "user_satisfaction_counts": user_satisfaction or {"satisfied": 1},
        "friction_counts": friction_counts or {},
        "primary_success": "ok",
        "session_type": "single",
        "friction_detail": "",
        "brief_summary": "test",
    }
    (usage_root / "facets" / f"{sid}.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _read_outcome(
    db_path: Path,
    advice_id: int,
    assoc: str = "temporal",
) -> dict | None:
    with sqlite3.connect(str(db_path)) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            "SELECT * FROM advice_outcomes "
            "WHERE advice_id=? AND assoc_method=?",
            (advice_id, assoc),
        )
        r = cur.fetchone()
    return dict(r) if r else None


# ── 1. Heurística pura (4 tests) ──────────────────────────────────────


class TestRatingHeuristic:
    """`infer_rating` aplica las reglas §3 sin tocar BD ni facets."""

    def test_fully_achieved_helpful_satisfied_is_useful(self):
        assert (
            ao.infer_rating("fully_achieved", "very_helpful", "satisfied")
            == "useful"
        )

    def test_not_achieved_is_not_useful(self):
        assert (
            ao.infer_rating("not_achieved", "very_helpful", "satisfied")
            == "not_useful"
        )

    def test_frustrated_overrides_good_signals(self):
        assert (
            ao.infer_rating("fully_achieved", "very_helpful", "frustrated")
            == "not_useful"
        )

    def test_unclear_outcome_with_clean_signals_is_unclear(self):
        assert (
            ao.infer_rating(
                "unclear_from_transcript",
                "moderately_helpful",
                "satisfied",
            )
            == "unclear"
        )


# ── 2. compute_outcomes — asociación e inserción (10 tests) ──────────


class TestComputeOutcomes:
    def test_no_meta_returns_no_facet_yet(
        self, db_path, usage_root, project_path
    ):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        _seed_advice(db_path, created_at=ts)
        result = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root
        )
        assert result.no_facet_yet == 1
        assert result.computed == 0
        assert _read_outcome(db_path, 1) is None

    def test_useful_full_path_inserts_outcome(
        self, db_path, usage_root, project_path
    ):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        _seed_advice(db_path, created_at=ts)
        _write_meta(
            usage_root, sid="sess-A", project_path=project_path,
            start=ts - timedelta(minutes=5), duration_min=30,
        )
        _write_facet(
            usage_root, sid="sess-A",
            outcome="fully_achieved", helpfulness="very_helpful",
        )
        result = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root
        )
        assert result.computed == 1
        row = _read_outcome(db_path, 1)
        assert row is not None
        assert row["inferred_rating"] == "useful"
        assert row["session_id"] == "sess-A"
        assert row["assoc_method"] == "temporal"
        assert row["facet_outcome"] == "fully_achieved"
        assert row["facet_helpfulness"] == "very_helpful"

    def test_not_useful_via_outcome(
        self, db_path, usage_root, project_path
    ):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        _seed_advice(db_path, created_at=ts)
        _write_meta(
            usage_root, sid="s1", project_path=project_path,
            start=ts - timedelta(minutes=5),
        )
        _write_facet(
            usage_root, sid="s1",
            outcome="not_achieved", helpfulness="very_helpful",
        )
        result = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root
        )
        assert result.computed == 1
        assert _read_outcome(db_path, 1)["inferred_rating"] == "not_useful"

    def test_not_useful_via_satisfaction_frustrated(
        self, db_path, usage_root, project_path
    ):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        _seed_advice(db_path, created_at=ts)
        _write_meta(
            usage_root, sid="s1", project_path=project_path,
            start=ts - timedelta(minutes=5),
        )
        _write_facet(
            usage_root, sid="s1",
            outcome="fully_achieved", helpfulness="essential",
            user_satisfaction={"frustrated": 2, "satisfied": 0},
        )
        result = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root
        )
        assert result.computed == 1
        row = _read_outcome(db_path, 1)
        assert row["inferred_rating"] == "not_useful"
        assert row["facet_satisfaction"] == "frustrated"

    def test_unclear_when_outcome_unclear(
        self, db_path, usage_root, project_path
    ):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        _seed_advice(db_path, created_at=ts)
        _write_meta(
            usage_root, sid="s1", project_path=project_path,
            start=ts - timedelta(minutes=5),
        )
        _write_facet(
            usage_root, sid="s1",
            outcome="unclear_from_transcript",
            helpfulness="moderately_helpful",
            user_satisfaction={"satisfied": 1},
        )
        result = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root
        )
        assert result.computed == 1
        assert _read_outcome(db_path, 1)["inferred_rating"] == "unclear"

    def test_idempotent_second_run_skips(
        self, db_path, usage_root, project_path
    ):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        _seed_advice(db_path, created_at=ts)
        _write_meta(
            usage_root, sid="s1", project_path=project_path,
            start=ts - timedelta(minutes=5),
        )
        _write_facet(usage_root, sid="s1")
        first = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root
        )
        second = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root
        )
        assert first.computed == 1
        assert second.computed == 0
        assert second.skipped == 1
        with sqlite3.connect(str(db_path)) as c:
            n = c.execute(
                "SELECT COUNT(*) FROM advice_outcomes WHERE advice_id=1"
            ).fetchone()[0]
        assert n == 1

    def test_force_recomputes_after_facet_change(
        self, db_path, usage_root, project_path
    ):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        _seed_advice(db_path, created_at=ts)
        _write_meta(
            usage_root, sid="s1", project_path=project_path,
            start=ts - timedelta(minutes=5),
        )
        _write_facet(
            usage_root, sid="s1",
            outcome="fully_achieved", helpfulness="very_helpful",
        )
        ao.compute_outcomes(db_path, project_path, usage_root=usage_root)
        assert _read_outcome(db_path, 1)["inferred_rating"] == "useful"
        # Cambia el facet y recomputa con force=True
        _write_facet(
            usage_root, sid="s1",
            outcome="not_achieved", helpfulness="very_helpful",
        )
        result = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root, force=True,
        )
        assert result.force_updated == 1
        assert _read_outcome(db_path, 1)["inferred_rating"] == "not_useful"

    def test_lookback_days_filters_old_advice(
        self, db_path, usage_root, project_path
    ):
        old_ts = datetime.now(timezone.utc) - timedelta(days=30)
        _seed_advice(db_path, created_at=old_ts)
        _write_meta(
            usage_root, sid="s1", project_path=project_path,
            start=old_ts - timedelta(minutes=5),
        )
        _write_facet(usage_root, sid="s1")
        result = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root,
            lookback_days=14,
        )
        assert result.computed == 0
        assert result.no_facet_yet == 0
        assert _read_outcome(db_path, 1) is None

    def test_friction_keys_serialized_only_with_count_gt_0(
        self, db_path, usage_root, project_path
    ):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        _seed_advice(db_path, created_at=ts)
        _write_meta(
            usage_root, sid="s1", project_path=project_path,
            start=ts - timedelta(minutes=5),
        )
        _write_facet(
            usage_root, sid="s1",
            friction_counts={
                "buggy_code": 0,
                "wrong_approach": 3,
                "misunderstood_request": 1,
            },
        )
        ao.compute_outcomes(db_path, project_path, usage_root=usage_root)
        row = _read_outcome(db_path, 1)
        keys = json.loads(row["friction_keys"])
        assert "buggy_code" not in keys
        assert keys[0] == "wrong_approach"        # count=3
        assert keys[1] == "misunderstood_request"  # count=1

    def test_returns_compute_result_with_all_counts(
        self, db_path, usage_root, project_path
    ):
        ts = datetime.now(timezone.utc) - timedelta(days=1)
        # advice A: tiene meta + facet → computed
        _seed_advice(db_path, created_at=ts, title="A")
        _write_meta(
            usage_root, sid="sA", project_path=project_path,
            start=ts - timedelta(minutes=5),
        )
        _write_facet(usage_root, sid="sA")
        # advice B: sin meta → no_facet_yet
        ts2 = ts + timedelta(hours=2)
        _seed_advice(db_path, created_at=ts2, title="B")
        result = ao.compute_outcomes(
            db_path, project_path, usage_root=usage_root
        )
        assert result.computed == 1
        assert result.no_facet_yet == 1
        assert result.skipped == 0
        assert result.force_updated == 0
