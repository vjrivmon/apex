"""Sprint 16 S16.4 — apex_advisor_apply_tuning auto-tuner.

Tests del comportamiento determinista de la heurística §5 del
blueprint:
- Necesita ≥20 outcomes (useful + not_useful) por categoría.
- Tunea solo si fp_rate >40%.
- Cooldown 7 días por constante.
- force=True salta cooldown registrando source='manual_override'.
- dry_run=True no escribe.
- Cada tune registra fila en advisor_tuning_history.
"""
import asyncio
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB
import advisor
import advisor_tuning


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_tuning.db")
    db = ApexContextDB(path)
    run(db.initialize())
    return path


def _seed_advice_with_outcome(path: str, kind: str, rating: str):
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
        aid = cur.lastrowid
        c.execute(
            "INSERT INTO advice_outcomes "
            "(advice_id, assoc_method, inferred_rating) "
            "VALUES (?, 'temporal', ?)",
            (aid, rating),
        )
        c.commit()


def _seed_outcomes(path: str, kind: str, useful: int, not_useful: int):
    for _ in range(useful):
        _seed_advice_with_outcome(path, kind, "useful")
    for _ in range(not_useful):
        _seed_advice_with_outcome(path, kind, "not_useful")


def _backdate_tuning_history(path: str, constant_name: str, days_ago: int):
    with sqlite3.connect(path) as c:
        c.execute(
            "INSERT INTO advisor_tuning_history "
            "(applied_at, category, constant_name, old_value, new_value, "
            " trigger_n_outcomes, fp_rate_before, source, reason) "
            "VALUES (datetime('now', ?), ?, ?, ?, ?, ?, ?, 'auto', ?)",
            (
                f"-{days_ago} days",
                "phase_drift",
                constant_name,
                8.0,
                12.0,
                25,
                0.45,
                "previous tune",
            ),
        )
        c.commit()


class TestAutoTuner:
    def test_below_min_outcomes_no_proposal(self, db_path):
        _seed_outcomes(db_path, "phase_drift", useful=5, not_useful=10)
        result = advisor_tuning.apply_tuning(db_path, dry_run=True)
        assert result["proposals"] == []

    def test_above_min_but_low_fp_no_proposal(self, db_path):
        # 22 outcomes, 7 not_useful → fp_rate 0.318 < 0.40
        _seed_outcomes(db_path, "phase_drift", useful=15, not_useful=7)
        result = advisor_tuning.apply_tuning(db_path, dry_run=True)
        assert result["proposals"] == []

    def test_proposes_tune_when_threshold_met(self, db_path):
        # 20 outcomes, 12 not_useful → fp_rate 0.6 > 0.40
        _seed_outcomes(db_path, "phase_drift", useful=8, not_useful=12)
        result = advisor_tuning.apply_tuning(db_path, dry_run=True)
        proposals = result["proposals"]
        assert len(proposals) == 1
        p = proposals[0]
        assert p["category"] == "phase_drift"
        assert p["constant"] == "phase_drift_window_min"
        assert p["old"] == 30
        assert p["new"] == 45
        assert p["fp_rate"] == pytest.approx(0.6)

    def test_dry_run_does_not_persist(self, db_path):
        _seed_outcomes(db_path, "forgotten_tool", useful=8, not_useful=12)
        advisor_tuning.apply_tuning(db_path, dry_run=True)
        # Constants no cambiadas
        constants = advisor.get_advisor_constants(db_path)
        assert constants["default_interval"] == advisor.ADVISOR_DEFAULT_INTERVAL
        # History vacía
        with sqlite3.connect(db_path) as c:
            cur = c.execute("SELECT COUNT(*) FROM advisor_tuning_history")
            assert cur.fetchone()[0] == 0

    def test_apply_persists_constants_and_history(self, db_path):
        _seed_outcomes(db_path, "forgotten_tool", useful=8, not_useful=12)
        result = advisor_tuning.apply_tuning(db_path, dry_run=False)
        assert result["applied"] == 1
        # Constants actualizadas
        constants = advisor.get_advisor_constants(db_path)
        # forgotten_tool tunea min_calls_between_reviews / default_interval (alias)
        assert constants["default_interval"] == 12
        # History registrada
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            cur = c.execute(
                "SELECT category, constant_name, old_value, new_value, "
                "       source, fp_rate_before, trigger_n_outcomes "
                "FROM advisor_tuning_history"
            )
            rows = [dict(r) for r in cur.fetchall()]
        assert len(rows) == 1
        r = rows[0]
        assert r["category"] == "forgotten_tool"
        assert r["constant_name"] == "default_interval"
        assert r["old_value"] == 8.0
        assert r["new_value"] == 12.0
        assert r["source"] == "auto"
        assert r["fp_rate_before"] == pytest.approx(0.6)
        assert r["trigger_n_outcomes"] == 20

    def test_cooldown_blocks_recent_tune(self, db_path):
        _seed_outcomes(db_path, "phase_drift", useful=8, not_useful=12)
        # Tunea ya hace 3 días: cooldown de 7 días bloquea
        _backdate_tuning_history(db_path, "phase_drift_window_min", days_ago=3)
        result = advisor_tuning.apply_tuning(db_path, dry_run=True)
        assert result["proposals"] == []
        assert result.get("cooldown_blocked", []) != []

    def test_cooldown_lifted_after_7_days(self, db_path):
        _seed_outcomes(db_path, "phase_drift", useful=8, not_useful=12)
        _backdate_tuning_history(db_path, "phase_drift_window_min", days_ago=8)
        result = advisor_tuning.apply_tuning(db_path, dry_run=True)
        assert len(result["proposals"]) == 1

    def test_force_skips_cooldown_and_logs_manual_override(self, db_path):
        _seed_outcomes(db_path, "phase_drift", useful=8, not_useful=12)
        _backdate_tuning_history(db_path, "phase_drift_window_min", days_ago=2)
        result = advisor_tuning.apply_tuning(db_path, dry_run=False, force=True)
        assert result["applied"] == 1
        with sqlite3.connect(db_path) as c:
            c.row_factory = sqlite3.Row
            cur = c.execute(
                "SELECT source FROM advisor_tuning_history "
                "ORDER BY id DESC LIMIT 1"
            )
            assert cur.fetchone()["source"] == "manual_override"

    def test_unclear_excluded_from_denominator(self, db_path):
        # 8 useful, 12 not_useful, 50 unclear → fp_rate sigue 0.6 y tunea
        _seed_outcomes(db_path, "phase_drift", useful=8, not_useful=12)
        for _ in range(50):
            _seed_advice_with_outcome(db_path, "phase_drift", "unclear")
        result = advisor_tuning.apply_tuning(db_path, dry_run=True)
        assert len(result["proposals"]) == 1
        assert result["proposals"][0]["fp_rate"] == pytest.approx(0.6)

    def test_includes_manual_outcomes_in_count(self, db_path):
        # 10 useful temporal + 10 not_useful manual
        _seed_outcomes(db_path, "phase_drift", useful=10, not_useful=0)
        # añadir 10 manuales not_useful
        with sqlite3.connect(db_path) as c:
            for _ in range(10):
                cur = c.execute(
                    "INSERT INTO advisor_reviews (session_id, trigger_kind, status) "
                    "VALUES ('s', 'manual', 'completed')"
                )
                rid = cur.lastrowid
                cur = c.execute(
                    "INSERT INTO advisor_advice (review_id, kind, severity, title, body) "
                    "VALUES (?, 'phase_drift', 'warn', ?, 'B')",
                    (rid, f"m-{rid}"),
                )
                aid = cur.lastrowid
                c.execute(
                    "INSERT INTO advice_outcomes "
                    "(advice_id, assoc_method, inferred_rating, manual_reason) "
                    "VALUES (?, 'manual', 'not_useful', 'razon larga aceptable')",
                    (aid,),
                )
            c.commit()
        result = advisor_tuning.apply_tuning(db_path, dry_run=True)
        assert len(result["proposals"]) == 1
        assert result["proposals"][0]["fp_rate"] == pytest.approx(0.5)

    def test_proposals_contain_all_four_categories(self, db_path):
        # Cada categoría triggers diferentes constantes
        for kind in ("forgotten_tool", "phase_drift", "recommend_skill_handoff", "grader_overdue"):
            _seed_outcomes(db_path, kind, useful=8, not_useful=12)
        result = advisor_tuning.apply_tuning(db_path, dry_run=True)
        cats = {p["category"] for p in result["proposals"]}
        assert cats == {
            "forgotten_tool",
            "phase_drift",
            "recommend_skill_handoff",
            "grader_overdue",
        }

    def test_unknown_category_ignored(self, db_path):
        # Una categoría sin mapping no aparece en proposals
        _seed_outcomes(db_path, "cross_project_error", useful=8, not_useful=12)
        result = advisor_tuning.apply_tuning(db_path, dry_run=True)
        cats = [p["category"] for p in result["proposals"]]
        assert "cross_project_error" not in cats
