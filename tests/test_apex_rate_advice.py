"""Sprint 16 S16.6 — apex_rate_advice (escape hatch manual).

Tests del contrato: rating ∈ {useful, not_useful}, reason >=10 chars
obligatoria, FK validation (advice_id existente), coexistencia con
outcome temporal vía UNIQUE compuesto, idempotencia con INSERT OR
REPLACE.
"""
import asyncio
import os
import sys

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB
import advisor


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db_path(tmp_path):
    path = str(tmp_path / "test_s16_6.db")
    db = ApexContextDB(path)
    run(db.initialize())
    return path


async def _seed_advice(path: str) -> int:
    async with aiosqlite.connect(path) as c:
        cur = await c.execute(
            "INSERT INTO advisor_reviews (session_id, trigger_kind, status) "
            "VALUES ('s1', 'manual', 'completed')"
        )
        rid = cur.lastrowid
        cur = await c.execute(
            "INSERT INTO advisor_advice (review_id, kind, severity, title, body) "
            "VALUES (?, 'phase_drift', 'warn', 'T', 'B')",
            (rid,),
        )
        await c.commit()
        return cur.lastrowid


def _fetch_outcomes(path: str, advice_id: int) -> list[dict]:
    import sqlite3

    with sqlite3.connect(path) as c:
        c.row_factory = sqlite3.Row
        cur = c.execute(
            "SELECT * FROM advice_outcomes WHERE advice_id=? ORDER BY id",
            (advice_id,),
        )
        return [dict(r) for r in cur.fetchall()]


class TestRateAdviceManual:
    def test_inserts_manual_outcome_with_valid_reason(self, db_path):
        advice_id = run(_seed_advice(db_path))
        result = advisor.rate_advice(
            db_path,
            advice_id=advice_id,
            rating="useful",
            reason="card me ahorró buscar tool olvidada",
        )
        assert "outcome_id" in result
        rows = _fetch_outcomes(db_path, advice_id)
        assert len(rows) == 1
        row = rows[0]
        assert row["assoc_method"] == "manual"
        assert row["inferred_rating"] == "useful"
        assert row["manual_reason"] == "card me ahorró buscar tool olvidada"
        assert row["session_id"] is None  # manual no asocia sesión
        assert row["facet_outcome"] is None

    def test_reason_too_short_raises(self, db_path):
        advice_id = run(_seed_advice(db_path))
        with pytest.raises(ValueError, match=r"reason"):
            advisor.rate_advice(
                db_path, advice_id=advice_id, rating="useful", reason="corta"
            )
        # nada insertado
        assert _fetch_outcomes(db_path, advice_id) == []

    def test_invalid_rating_raises(self, db_path):
        advice_id = run(_seed_advice(db_path))
        # 'unclear' no se permite manual (escape hatch fuerza señal)
        with pytest.raises(ValueError, match=r"rating"):
            advisor.rate_advice(
                db_path,
                advice_id=advice_id,
                rating="unclear",
                reason="reason long enough text",
            )
        with pytest.raises(ValueError, match=r"rating"):
            advisor.rate_advice(
                db_path,
                advice_id=advice_id,
                rating="banana",
                reason="reason long enough text",
            )
        assert _fetch_outcomes(db_path, advice_id) == []

    def test_advice_id_not_exists_raises(self, db_path):
        with pytest.raises(ValueError, match=r"advice_id"):
            advisor.rate_advice(
                db_path,
                advice_id=9999,
                rating="not_useful",
                reason="advice inexistente debe fallar",
            )

    def test_coexists_with_temporal_outcome(self, db_path):
        """UNIQUE(advice_id, assoc_method) permite 1 temporal + 1 manual."""
        advice_id = run(_seed_advice(db_path))
        # primero un temporal directo
        import sqlite3

        with sqlite3.connect(db_path) as c:
            c.execute(
                "INSERT INTO advice_outcomes "
                "(advice_id, assoc_method, inferred_rating, session_id, "
                " facet_outcome) "
                "VALUES (?, 'temporal', 'unclear', 'sess-A', 'unclear_from_transcript')",
                (advice_id,),
            )
            c.commit()
        # ahora añadir manual
        result = advisor.rate_advice(
            db_path,
            advice_id=advice_id,
            rating="not_useful",
            reason="card era ruido pese a sesión global ok",
        )
        rows = _fetch_outcomes(db_path, advice_id)
        assert len(rows) == 2
        methods = {r["assoc_method"] for r in rows}
        assert methods == {"temporal", "manual"}
        manual = next(r for r in rows if r["assoc_method"] == "manual")
        assert manual["inferred_rating"] == "not_useful"
        assert result["outcome_id"] == manual["id"]

    def test_idempotency_replaces_previous_manual(self, db_path):
        """Segundo manual sobre mismo advice → INSERT OR REPLACE."""
        advice_id = run(_seed_advice(db_path))
        first = advisor.rate_advice(
            db_path,
            advice_id=advice_id,
            rating="useful",
            reason="primera valoración correcta",
        )
        second = advisor.rate_advice(
            db_path,
            advice_id=advice_id,
            rating="not_useful",
            reason="me equivoqué, en realidad no sirvió",
        )
        rows = _fetch_outcomes(db_path, advice_id)
        manuals = [r for r in rows if r["assoc_method"] == "manual"]
        # solo 1 manual (UNIQUE compuesto)
        assert len(manuals) == 1
        assert manuals[0]["inferred_rating"] == "not_useful"
        assert "equivoqué" in manuals[0]["manual_reason"]
        # outcome_id puede ser distinto (REPLACE genera nueva fila)
        assert second["outcome_id"] is not None
