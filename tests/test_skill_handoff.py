"""Sprint 15 S15.4 — tests para lib/skill_handoff.py."""
from __future__ import annotations

import asyncio
import os
import sqlite3
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
import skill_handoff as sh  # noqa: E402


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


class TestCreate:
    def test_create_returns_id(self, db_path):
        hid = sh.create_handoff(
            db_path, "s1", "grill-with-docs", "prototype",
            "Quiero validar la state machine antes de seguir.",
            snapshot={"pending_questions": ["q1"]},
        )
        assert isinstance(hid, int) and hid > 0

    def test_same_skill_raises(self, db_path):
        with pytest.raises(ValueError):
            sh.create_handoff(db_path, "s1", "X", "X", "abc")

    def test_short_reason_raises(self, db_path):
        with pytest.raises(ValueError):
            sh.create_handoff(db_path, "s1", "A", "B", "")
        with pytest.raises(ValueError):
            sh.create_handoff(db_path, "s1", "A", "B", "ok")  # <3 chars


class TestResume:
    def test_resume_marks_returned_at(self, db_path):
        hid = sh.create_handoff(
            db_path, "s1", "A", "B", "razon valida",
            snapshot={"key": "v"},
        )
        d = sh.resume_handoff(db_path, hid, "result OK")
        assert d is not None
        with sqlite3.connect(db_path) as c:
            row = c.execute(
                "SELECT returned_at, result_summary FROM skill_handoffs WHERE id=?",
                (hid,),
            ).fetchone()
        assert row[0] is not None
        assert row[1] == "result OK"

    def test_resume_unknown_returns_none(self, db_path):
        assert sh.resume_handoff(db_path, 999, "") is None


class TestOrphans:
    def test_orphans_excludes_returned(self, db_path):
        hid_a = sh.create_handoff(db_path, "s1", "A", "B", "razon")
        hid_b = sh.create_handoff(db_path, "s1", "C", "D", "razon")
        # Forzar created_at antiguo en hid_a
        with sqlite3.connect(db_path) as c:
            c.execute(
                "UPDATE skill_handoffs SET created_at=datetime('now', '-1 hour') "
                "WHERE id=?",
                (hid_a,),
            )
            c.commit()
        sh.resume_handoff(db_path, hid_a, "ok")  # marcado como returned
        orphans = sh.get_orphan_handoffs(db_path, max_age_seconds=60)
        # hid_a returned, hid_b muy reciente (no >60s) → ninguno
        assert all(o["id"] != hid_a for o in orphans)

    def test_orphans_returns_aged_unreturned(self, db_path):
        hid = sh.create_handoff(db_path, "s1", "A", "B", "razon")
        with sqlite3.connect(db_path) as c:
            c.execute(
                "UPDATE skill_handoffs SET created_at=datetime('now', '-2 hours') "
                "WHERE id=?",
                (hid,),
            )
            c.commit()
        orphans = sh.get_orphan_handoffs(db_path, max_age_seconds=1800)
        ids = [o["id"] for o in orphans]
        assert hid in ids
