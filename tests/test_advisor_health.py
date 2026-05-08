"""Sprint 16 S16.3 — apex_advisor_health dashboard.

Tests del shape del JSON: BD vacía, datos sintéticos, ventana de
lookback filtra, FP rate None si <5 not_useful por categoría,
freshness detecta archivos >7 días, defaults vs tuned se distinguen
en `constants_actuales`.
"""
import asyncio
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB
import advisor
import advisor_health


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_health.db")
    db = ApexContextDB(path)
    run(db.initialize())
    return path


def _seed_advice(path: str, kind: str = "phase_drift") -> int:
    with sqlite3.connect(path) as c:
        cur = c.execute(
            "INSERT INTO advisor_reviews (session_id, trigger_kind, status) "
            "VALUES ('s', 'manual', 'completed')"
        )
        rid = cur.lastrowid
        cur = c.execute(
            "INSERT INTO advisor_advice (review_id, kind, severity, title, body) "
            "VALUES (?, ?, 'warn', ?, 'B')",
            (rid, kind, f"adv-{rid}-{kind}"),
        )
        c.commit()
        return cur.lastrowid


def _seed_outcome(
    path: str,
    advice_id: int,
    rating: str,
    assoc_method: str = "temporal",
    days_ago: int = 0,
):
    """Inserta outcome con `computed_at` ajustado a N días atrás."""
    with sqlite3.connect(path) as c:
        c.execute(
            "INSERT INTO advice_outcomes "
            "(advice_id, assoc_method, inferred_rating, computed_at) "
            "VALUES (?, ?, ?, datetime('now', ?))",
            (advice_id, assoc_method, rating, f"-{days_ago} days"),
        )
        c.commit()


class TestAdvisorHealthShape:
    def test_empty_db_returns_zeros(self, db_path):
        out = advisor_health.advisor_health(db_path, window_days=30)
        assert "total_advice_emitted" in out
        assert "outcomes_computed" in out
        assert "fp_rate" in out
        assert "constants_actuales" in out
        assert "tuning_history" in out
        assert "circuit_breaker_trips_24h" in out
        assert "facets_freshness_days" in out
        assert out["total_advice_emitted"] == {}
        assert out["outcomes_computed"] == {}
        assert out["fp_rate"] == {}
        assert out["tuning_history"] == []

    def test_total_advice_emitted_groups_by_kind(self, db_path):
        _seed_advice(db_path, "phase_drift")
        _seed_advice(db_path, "phase_drift")
        _seed_advice(db_path, "forgotten_tool")
        out = advisor_health.advisor_health(db_path, window_days=30)
        assert out["total_advice_emitted"] == {
            "phase_drift": 2,
            "forgotten_tool": 1,
        }

    def test_outcomes_computed_separates_temporal_and_manual(self, db_path):
        a1 = _seed_advice(db_path, "phase_drift")
        a2 = _seed_advice(db_path, "phase_drift")
        _seed_outcome(db_path, a1, "useful", "temporal")
        _seed_outcome(db_path, a2, "not_useful", "manual")
        out = advisor_health.advisor_health(db_path, window_days=30)
        oc = out["outcomes_computed"]["phase_drift"]
        assert oc["temporal"]["useful"] == 1
        assert oc["temporal"]["not_useful"] == 0
        assert oc["manual"]["useful"] == 0
        assert oc["manual"]["not_useful"] == 1

    def test_fp_rate_none_when_below_threshold(self, db_path):
        a = _seed_advice(db_path, "phase_drift")
        # 4 not_useful, 1 useful → not_useful insuficiente (<5) → None
        for _ in range(4):
            advice_id = _seed_advice(db_path, "phase_drift")
            _seed_outcome(db_path, advice_id, "not_useful")
        _seed_outcome(db_path, a, "useful")
        out = advisor_health.advisor_health(db_path, window_days=30)
        assert out["fp_rate"]["phase_drift"] is None

    def test_fp_rate_computed_when_threshold_met(self, db_path):
        # 5 not_useful, 5 useful → fp_rate = 0.5
        for _ in range(5):
            aid = _seed_advice(db_path, "forgotten_tool")
            _seed_outcome(db_path, aid, "not_useful")
        for _ in range(5):
            aid = _seed_advice(db_path, "forgotten_tool")
            _seed_outcome(db_path, aid, "useful")
        out = advisor_health.advisor_health(db_path, window_days=30)
        assert out["fp_rate"]["forgotten_tool"] == pytest.approx(0.5)

    def test_window_days_filters_old_outcomes(self, db_path):
        a_old = _seed_advice(db_path, "phase_drift")
        a_new = _seed_advice(db_path, "phase_drift")
        _seed_outcome(db_path, a_old, "not_useful", days_ago=60)
        _seed_outcome(db_path, a_new, "useful", days_ago=1)
        out = advisor_health.advisor_health(db_path, window_days=30)
        # solo cuenta el nuevo
        oc = out["outcomes_computed"]["phase_drift"]
        assert oc["temporal"]["useful"] == 1
        assert oc["temporal"]["not_useful"] == 0

    def test_constants_distinguishes_defaults_vs_tuned(self, db_path):
        # sin tuning → todas defaults
        out = advisor_health.advisor_health(db_path)
        constants = out["constants_actuales"]
        assert constants["default_interval"]["value"] == advisor.ADVISOR_DEFAULT_INTERVAL
        assert constants["default_interval"]["source"] == "default"
        # tunea una constante via set_advisor_constants y verifica
        advisor.set_advisor_constants(db_path, {"default_interval": 99})
        out2 = advisor_health.advisor_health(db_path)
        c2 = out2["constants_actuales"]["default_interval"]
        assert c2["value"] == 99
        assert c2["source"] == "tuned"

    def test_facets_freshness_handles_missing_dir(self, db_path, monkeypatch, tmp_path):
        # Apunta a un dir inexistente
        ghost = tmp_path / "nope" / "facets"
        monkeypatch.setenv("APEX_USAGE_DATA_ROOT", str(tmp_path / "nope"))
        out = advisor_health.advisor_health(db_path)
        assert out["facets_freshness_days"] is None
