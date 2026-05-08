"""Sprint 17 S17.1 — schema migration de vfs_render_cache + vfs_query_log.

Verifica que las 2 tablas nuevas existen tras `ApexContextDB.initialize()`,
que la PK y los tipos cumplen, que los índices de telemetría están, que
la re-migración es idempotente y que no rompe el schema previo (S16).
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
    return str(tmp_path / "test_s17.db")


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


class TestSprint17Schema:
    def test_vfs_render_cache_table_exists(self, db, db_path):
        run(db.initialize())
        assert run(_table_exists(db_path, "vfs_render_cache"))

    def test_vfs_query_log_table_exists(self, db, db_path):
        run(db.initialize())
        assert run(_table_exists(db_path, "vfs_query_log"))

    def test_vfs_render_cache_pk_and_columns(self, db, db_path):
        """vfs_render_cache: cache_key PK + rendered + generated_at + source_hash."""
        run(db.initialize())

        async def _columns():
            async with aiosqlite.connect(db_path) as c:
                cur = await c.execute("PRAGMA table_info(vfs_render_cache)")
                rows = await cur.fetchall()
                return {r[1]: (r[2], r[5]) for r in rows}  # name -> (type, pk)

        cols = run(_columns())
        assert "cache_key" in cols
        assert cols["cache_key"][1] == 1, "cache_key must be PRIMARY KEY"
        assert "rendered" in cols
        assert "generated_at" in cols
        assert "source_hash" in cols

    def test_vfs_query_log_indexes(self, db, db_path):
        """Índices de telemetría sobre vfs_query_log."""
        run(db.initialize())
        assert run(_index_exists(db_path, "idx_vfs_query_log_ts"))
        assert run(_index_exists(db_path, "idx_vfs_query_log_project"))

    def test_vfs_render_cache_upsert_idempotent(self, db, db_path):
        """INSERT OR REPLACE sobre cache_key sobrescribe sin duplicar."""
        run(db.initialize())

        async def _ops():
            async with aiosqlite.connect(db_path) as c:
                await c.execute(
                    "INSERT OR REPLACE INTO vfs_render_cache "
                    "(cache_key, rendered, source_hash) VALUES (?, ?, ?)",
                    ("k1", "first", "h1"),
                )
                await c.commit()
                await c.execute(
                    "INSERT OR REPLACE INTO vfs_render_cache "
                    "(cache_key, rendered, source_hash) VALUES (?, ?, ?)",
                    ("k1", "second", "h2"),
                )
                await c.commit()
                cur = await c.execute(
                    "SELECT rendered, source_hash FROM vfs_render_cache "
                    "WHERE cache_key=?",
                    ("k1",),
                )
                row = await cur.fetchone()
                cur = await c.execute("SELECT COUNT(*) FROM vfs_render_cache")
                count = (await cur.fetchone())[0]
                return row, count

        (rendered, h), count = run(_ops())
        assert rendered == "second"
        assert h == "h2"
        assert count == 1

    def test_vfs_query_log_insert_round_trip(self, db, db_path):
        """vfs_query_log acepta inserts típicos y los devuelve íntegros."""
        run(db.initialize())

        async def _ops():
            async with aiosqlite.connect(db_path) as c:
                await c.execute(
                    "INSERT INTO vfs_query_log "
                    "(command, project_slug, hits, latency_ms) "
                    "VALUES (?, ?, ?, ?)",
                    ("ls /projects/apex/wiki", "apex", 12, 8),
                )
                await c.execute(
                    "INSERT INTO vfs_query_log "
                    "(command, project_slug, hits, latency_ms) "
                    "VALUES (?, ?, ?, ?)",
                    ("grep -r foo /projects/", None, 0, 412),
                )
                await c.commit()
                cur = await c.execute(
                    "SELECT command, project_slug, hits, latency_ms "
                    "FROM vfs_query_log ORDER BY id"
                )
                return await cur.fetchall()

        rows = run(_ops())
        assert len(rows) == 2
        assert rows[0][0] == "ls /projects/apex/wiki"
        assert rows[0][1] == "apex"
        assert rows[0][2] == 12
        assert rows[1][1] is None  # project_slug puede ser NULL para queries cross-project

    def test_idempotent_reinitialization(self, db, db_path):
        """Re-correr initialize() en una BD existente no duplica ni borra."""
        run(db.initialize())

        async def _seed():
            async with aiosqlite.connect(db_path) as c:
                await c.execute(
                    "INSERT INTO vfs_render_cache "
                    "(cache_key, rendered, source_hash) VALUES ('k', 'v', 'h')"
                )
                await c.commit()

        run(_seed())
        run(db.initialize())  # debería ser idempotente

        async def _check():
            async with aiosqlite.connect(db_path) as c:
                cur = await c.execute(
                    "SELECT rendered FROM vfs_render_cache WHERE cache_key='k'"
                )
                return await cur.fetchone()

        row = run(_check())
        assert row is not None
        assert row[0] == "v"

    def test_does_not_break_s16_schema(self, db, db_path):
        """Sanity: las tablas de S16 (advice_outcomes, advisor_tuning_history)
        siguen presentes tras añadir el schema VFS."""
        run(db.initialize())
        assert run(_table_exists(db_path, "advice_outcomes"))
        assert run(_table_exists(db_path, "advisor_tuning_history"))
