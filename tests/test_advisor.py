"""Sprint 15 S15.2 — tests para lib/advisor.py.

Cobertura: should_run (throttle + circuit breaker), record/update/dismiss,
get_active_advice (orden por severity), build_bundle (smoke + cap).
"""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
import advisor  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db_path(tmp_path):
    p = tmp_path / "ctx.db"
    db = ApexContextDB(str(p))
    run(db.initialize())
    return str(p)


def _create_review(db_path: str, sid: str = "s1", trigger: str = "manual") -> int:
    return advisor.record_review(db_path, sid, trigger)


# ── should_run / pacing ────────────────────────────────────────────

class TestShouldRun:
    def test_blocked_below_min_calls(self, db_path):
        with sqlite3.connect(db_path) as c:
            advisor._set_meta(c, advisor.META_TOOL_COUNT, 2)
            c.commit()
        run_, reason = advisor.should_run(db_path)
        assert run_ is False
        assert "min_calls" in reason

    def test_blocked_below_interval(self, db_path):
        with sqlite3.connect(db_path) as c:
            advisor._set_meta(c, advisor.META_TOOL_COUNT, 5)
            c.commit()
        run_, reason = advisor.should_run(db_path)
        assert run_ is False
        assert "interval" in reason

    def test_passes_at_default_interval(self, db_path):
        with sqlite3.connect(db_path) as c:
            advisor._set_meta(c, advisor.META_TOOL_COUNT, 8)
            c.commit()
        run_, reason = advisor.should_run(db_path)
        assert run_ is True

    def test_force_bypass(self, db_path):
        run_, reason = advisor.should_run(db_path, force=True)
        assert run_ is True
        assert reason == "force"


# ── increment / outcome / circuit breaker ──────────────────────────

class TestPacing:
    def test_increment_tool_count(self, db_path):
        assert advisor.increment_tool_count(db_path) == 1
        assert advisor.increment_tool_count(db_path) == 2
        assert advisor.increment_tool_count(db_path) == 3

    def test_outcome_zero_advice_grows_streak(self, db_path):
        rid = _create_review(db_path)
        advisor.register_review_outcome(db_path, advice_count=0)
        with sqlite3.connect(db_path) as c:
            assert advisor._get_meta_int(c, advisor.META_EMPTY_STREAK) == 1
            assert advisor._get_meta_int(c, advisor.META_TOOL_COUNT) == 0

    def test_outcome_with_advice_resets_streak_and_interval(self, db_path):
        with sqlite3.connect(db_path) as c:
            advisor._set_meta(c, advisor.META_EMPTY_STREAK, 5)
            advisor._set_meta(c, advisor.META_CURRENT_INTERVAL, advisor.ADVISOR_BACKOFF_INTERVAL)
            c.commit()
        advisor.register_review_outcome(db_path, advice_count=2)
        with sqlite3.connect(db_path) as c:
            assert advisor._get_meta_int(c, advisor.META_EMPTY_STREAK) == 0
            assert (
                advisor._get_meta_int(c, advisor.META_CURRENT_INTERVAL)
                == advisor.ADVISOR_DEFAULT_INTERVAL
            )

    def test_three_empties_triggers_backoff(self, db_path):
        for _ in range(advisor.ADVISOR_EMPTY_STREAK_THRESHOLD):
            advisor.register_review_outcome(db_path, advice_count=0)
        with sqlite3.connect(db_path) as c:
            assert (
                advisor._get_meta_int(c, advisor.META_CURRENT_INTERVAL)
                == advisor.ADVISOR_BACKOFF_INTERVAL
            )


# ── record / update review ─────────────────────────────────────────

class TestReviewCRUD:
    def test_record_review_returns_int_id(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        assert isinstance(rid, int) and rid > 0

    def test_record_review_status_defaults_pending(self, db_path):
        rid = advisor.record_review(db_path, "s1", "manual")
        with sqlite3.connect(db_path) as c:
            row = c.execute("SELECT status FROM advisor_reviews WHERE id=?", (rid,)).fetchone()
        assert row[0] == "pending"


# ── advice CRUD ────────────────────────────────────────────────────

class TestAdviceCRUD:
    def test_record_advice_invalid_kind_raises(self, db_path):
        rid = _create_review(db_path)
        with pytest.raises(ValueError):
            advisor.record_advice(db_path, rid, "bogus_kind", "warn", "T", "B")

    def test_record_advice_idempotent_on_duplicate(self, db_path):
        rid = _create_review(db_path)
        a1 = advisor.record_advice(
            db_path, rid, "phase_drift", "warn", "T", "B1",
        )
        a2 = advisor.record_advice(
            db_path, rid, "phase_drift", "warn", "T", "B2",
        )
        assert isinstance(a1, int)
        assert a2 is None  # duplicate UNIQUE(review_id, kind, title)

    def test_dismiss_advice_requires_reason(self, db_path):
        rid = _create_review(db_path)
        aid = advisor.record_advice(db_path, rid, "phase_drift", "warn", "T", "B")
        with pytest.raises(ValueError):
            advisor.dismiss_advice(db_path, aid, "")
        with pytest.raises(ValueError):
            advisor.dismiss_advice(db_path, aid, "ok")  # <3 chars

    def test_dismiss_advice_marks_dismissed(self, db_path):
        rid = _create_review(db_path)
        aid = advisor.record_advice(db_path, rid, "phase_drift", "warn", "T", "B")
        ok = advisor.dismiss_advice(db_path, aid, "irrelevante para esta fase")
        assert ok is True
        with sqlite3.connect(db_path) as c:
            row = c.execute(
                "SELECT dismissed, dismissed_reason FROM advisor_advice WHERE id=?",
                (aid,),
            ).fetchone()
        assert row[0] == 1
        assert "irrelevante" in row[1]


# ── get_active_advice ──────────────────────────────────────────────

class TestActiveAdvice:
    def test_filters_dismissed(self, db_path):
        rid = advisor.record_review(db_path, "s_active", "manual")
        a1 = advisor.record_advice(db_path, rid, "phase_drift", "warn", "T1", "B")
        advisor.record_advice(db_path, rid, "grader_overdue", "info", "T2", "B")
        advisor.dismiss_advice(db_path, a1, "no aplica")
        active = advisor.get_active_advice(db_path, "s_active")
        assert len(active) == 1
        assert active[0]["title"] == "T2"

    def test_orders_by_severity(self, db_path):
        rid = advisor.record_review(db_path, "s_ord", "manual")
        advisor.record_advice(db_path, rid, "grader_overdue", "info", "low", "B")
        advisor.record_advice(db_path, rid, "phase_drift", "critical", "top", "B")
        advisor.record_advice(db_path, rid, "forgotten_tool", "warn", "mid", "B")
        active = advisor.get_active_advice(db_path, "s_ord")
        assert [a["severity"] for a in active] == ["critical", "warn", "info"]


# ── build_bundle ───────────────────────────────────────────────────

class TestBundle:
    def test_smoke_returns_session_id_and_keys(self, db_path):
        bundle = advisor.build_bundle(db_path, "s1")
        assert bundle["session_id"] == "s1"
        for k in ("phase", "recent_decisions", "blocking_verdicts",
                  "recent_traces", "recent_tool_calls"):
            assert k in bundle

    def test_truncates_when_oversized(self, db_path):
        # Insert 200 tool_call rows con args muy largos
        with sqlite3.connect(db_path) as c:
            big = "X" * 200
            for i in range(200):
                c.execute(
                    "INSERT INTO tool_call_log (tool, args_summary) VALUES (?, ?)",
                    (f"tool_{i}", big),
                )
            c.commit()
        bundle = advisor.build_bundle(db_path, "s1")
        # build_bundle solo carga 20, así que esto no dispara el cap.
        # Forzamos artificialmente: bypass para verificar el helper directo.
        oversized = "Y" * (advisor.ADVISOR_BUNDLE_MAX_TOKENS * 4 + 1000)
        truncated = advisor._truncate_to_tokens(
            oversized, advisor.ADVISOR_BUNDLE_MAX_TOKENS,
        )
        assert "[... truncado ...]" in truncated
        assert len(truncated) < len(oversized)
