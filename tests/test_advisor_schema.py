"""Sprint 15 S15.1 — schema migration de advisor + traces + handoffs + state_machines.

Verifica que las 5 tablas nuevas existen tras `ApexContextDB.initialize()`,
que sus UNIQUEs cumplen, y que las tablas previas (S14 baseline) siguen vivas.
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
    return str(tmp_path / "test_s15.db")


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
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        return await cursor.fetchone() is not None


class TestSprint15Schema:
    def test_advisor_reviews_table_exists(self, db, db_path):
        run(db.initialize())
        assert run(_table_exists(db_path, "advisor_reviews"))

    def test_advisor_advice_table_exists(self, db, db_path):
        run(db.initialize())
        assert run(_table_exists(db_path, "advisor_advice"))

    def test_reasoning_traces_table_exists(self, db, db_path):
        run(db.initialize())
        assert run(_table_exists(db_path, "reasoning_traces"))

    def test_skill_handoffs_table_exists(self, db, db_path):
        run(db.initialize())
        assert run(_table_exists(db_path, "skill_handoffs"))

    def test_state_machines_table_exists(self, db, db_path):
        run(db.initialize())
        assert run(_table_exists(db_path, "state_machines"))

    def test_advisor_advice_unique_review_kind_title(self, db, db_path):
        run(db.initialize())

        async def _check():
            async with aiosqlite.connect(db_path) as c:
                cur = await c.execute(
                    "INSERT INTO advisor_reviews (session_id, trigger_kind, status) "
                    "VALUES ('s1', 'manual', 'pending')"
                )
                rid = cur.lastrowid
                await c.execute(
                    "INSERT INTO advisor_advice (review_id, kind, severity, title, body) "
                    "VALUES (?, 'phase_drift', 'warn', 'X', 'b1')",
                    (rid,),
                )
                raised = False
                try:
                    await c.execute(
                        "INSERT INTO advisor_advice (review_id, kind, severity, title, body) "
                        "VALUES (?, 'phase_drift', 'warn', 'X', 'b2')",
                        (rid,),
                    )
                except aiosqlite.IntegrityError:
                    raised = True
                await c.commit()
                return raised

        assert run(_check()) is True

    def test_state_machines_unique_feature_name(self, db, db_path):
        run(db.initialize())

        async def _check():
            async with aiosqlite.connect(db_path) as c:
                await c.execute(
                    "INSERT INTO state_machines "
                    "(feature_name, states, transitions, initial_state, tui_path, wiki_path) "
                    "VALUES ('cart', '[]', '[]', 'idle', 'a.py', 'a.md')"
                )
                raised = False
                try:
                    await c.execute(
                        "INSERT INTO state_machines "
                        "(feature_name, states, transitions, initial_state, tui_path, wiki_path) "
                        "VALUES ('cart', '[]', '[]', 'idle', 'b.py', 'b.md')"
                    )
                except aiosqlite.IntegrityError:
                    raised = True
                await c.commit()
                return raised

        assert run(_check()) is True

    def test_existing_tables_still_present(self, db, db_path):
        """Backwards-compat: las tablas previas (S14 baseline) no se rompen."""
        run(db.initialize())
        for tbl in (
            "phases", "decisions", "errors", "components", "next_steps",
            "context_log", "wiki_pages", "grader_verdicts", "tool_output_archive",
            "tool_call_log", "skill_forge_rejections", "library_imports",
            "role_invocations", "doctor_runs", "doctor_proposals", "session_starts",
        ):
            assert run(_table_exists(db_path, tbl)), f"missing: {tbl}"
