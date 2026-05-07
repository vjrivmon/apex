"""Sprint 16 S16.1 — schema migration de advice_outcomes + advisor_tuning_history.

Verifica que las 2 tablas nuevas existen tras `ApexContextDB.initialize()`,
que sus CHECK + UNIQUE + FK cascade cumplen, que los índices están y que
la re-migración es idempotente. No rompe el schema previo (S15).
"""
import asyncio
import os
import sys

import aiosqlite
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test_s16.db")


@pytest.fixture
def db(db_path):
    return ApexContextDB(db_path)


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _table_exists(path: str, table: str) -> bool:
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return await cur.fetchone() is not None


async def _index_exists(path: str, index: str) -> bool:
    async with aiosqlite.connect(path) as conn:
        cur = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name=?",
            (index,),
        )
        return await cur.fetchone() is not None


async def _seed_advice(path: str) -> int:
    """Inserta un advisor_review + advisor_advice y devuelve advice_id."""
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


class TestSprint16Schema:
    def test_advice_outcomes_table_exists(self, db, db_path):
        run(db.initialize())
        assert run(_table_exists(db_path, "advice_outcomes"))

    def test_advisor_tuning_history_table_exists(self, db, db_path):
        run(db.initialize())
        assert run(_table_exists(db_path, "advisor_tuning_history"))

    def test_advice_outcomes_indexes_present(self, db, db_path):
        run(db.initialize())
        assert run(_index_exists(db_path, "idx_advice_outcomes_advice"))
        assert run(_index_exists(db_path, "idx_advice_outcomes_session"))
        assert run(_index_exists(db_path, "idx_advice_outcomes_rating"))

    def test_advice_outcomes_check_constraints(self, db, db_path):
        """CHECK rechaza valores fuera de los enums permitidos."""
        run(db.initialize())

        async def _check():
            advice_id = await _seed_advice(db_path)
            results = {}
            async with aiosqlite.connect(db_path) as c:
                # rating inválido
                try:
                    await c.execute(
                        "INSERT INTO advice_outcomes "
                        "(advice_id, assoc_method, inferred_rating) "
                        "VALUES (?, 'temporal', 'banana')",
                        (advice_id,),
                    )
                    await c.commit()
                    results["bad_rating"] = False
                except aiosqlite.IntegrityError:
                    results["bad_rating"] = True
                # assoc_method inválido
                try:
                    await c.execute(
                        "INSERT INTO advice_outcomes "
                        "(advice_id, assoc_method, inferred_rating) "
                        "VALUES (?, 'invented', 'useful')",
                        (advice_id,),
                    )
                    await c.commit()
                    results["bad_assoc"] = False
                except aiosqlite.IntegrityError:
                    results["bad_assoc"] = True
                # combinación válida pasa
                await c.execute(
                    "INSERT INTO advice_outcomes "
                    "(advice_id, assoc_method, inferred_rating) "
                    "VALUES (?, 'temporal', 'useful')",
                    (advice_id,),
                )
                await c.commit()
                results["good"] = True
            return results

        out = run(_check())
        assert out == {"bad_rating": True, "bad_assoc": True, "good": True}

    def test_advice_outcomes_unique_advice_assoc(self, db, db_path):
        """UNIQUE(advice_id, assoc_method): permite 1 temporal + 1 manual."""
        run(db.initialize())

        async def _check():
            advice_id = await _seed_advice(db_path)
            async with aiosqlite.connect(db_path) as c:
                # primer temporal
                await c.execute(
                    "INSERT INTO advice_outcomes "
                    "(advice_id, assoc_method, inferred_rating) "
                    "VALUES (?, 'temporal', 'useful')",
                    (advice_id,),
                )
                # un manual debe coexistir
                await c.execute(
                    "INSERT INTO advice_outcomes "
                    "(advice_id, assoc_method, inferred_rating, manual_reason) "
                    "VALUES (?, 'manual', 'not_useful', 'ruidosa')",
                    (advice_id,),
                )
                await c.commit()
                # segundo temporal con mismo advice falla
                raised = False
                try:
                    await c.execute(
                        "INSERT INTO advice_outcomes "
                        "(advice_id, assoc_method, inferred_rating) "
                        "VALUES (?, 'temporal', 'unclear')",
                        (advice_id,),
                    )
                    await c.commit()
                except aiosqlite.IntegrityError:
                    raised = True
                return raised

        assert run(_check()) is True

    def test_advice_outcomes_fk_cascade_on_advice_delete(self, db, db_path):
        """Borrar el advisor_advice padre limpia el advice_outcome (CASCADE)."""
        run(db.initialize())

        async def _check():
            advice_id = await _seed_advice(db_path)
            async with aiosqlite.connect(db_path) as c:
                await c.execute("PRAGMA foreign_keys = ON")
                await c.execute(
                    "INSERT INTO advice_outcomes "
                    "(advice_id, assoc_method, inferred_rating) "
                    "VALUES (?, 'temporal', 'useful')",
                    (advice_id,),
                )
                await c.commit()
                cur = await c.execute(
                    "SELECT COUNT(*) FROM advice_outcomes WHERE advice_id=?",
                    (advice_id,),
                )
                before = (await cur.fetchone())[0]
                await c.execute(
                    "DELETE FROM advisor_advice WHERE id=?", (advice_id,)
                )
                await c.commit()
                cur = await c.execute(
                    "SELECT COUNT(*) FROM advice_outcomes WHERE advice_id=?",
                    (advice_id,),
                )
                after = (await cur.fetchone())[0]
                return before, after

        before, after = run(_check())
        assert (before, after) == (1, 0)

    def test_migration_idempotent(self, db, db_path):
        """Re-correr initialize() no rompe ni duplica."""
        run(db.initialize())
        run(db.initialize())  # segunda vez debe ser no-op
        assert run(_table_exists(db_path, "advice_outcomes"))
        assert run(_table_exists(db_path, "advisor_tuning_history"))

    def test_existing_s15_tables_still_present(self, db, db_path):
        """Backwards-compat: tablas S15 (Advisor) siguen vivas."""
        run(db.initialize())
        for tbl in (
            "advisor_reviews", "advisor_advice", "reasoning_traces",
            "skill_handoffs", "state_machines",
        ):
            assert run(_table_exists(db_path, tbl)), f"missing: {tbl}"
