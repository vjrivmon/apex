"""Shared database connection factory for APEX.

Unifies SQLite access across all modules (context_db, advisor, advisor_outcomes,
advisor_health, advisor_tuning) with consistent PRAGMAs and connection management.

Usage:
    from lib.db_utils import get_sync_db
    with get_sync_db(db_path) as conn:
        conn.execute("SELECT ...")

    # async variant (for context_db.py)
    from lib.db_utils import get_async_db
    async with get_async_db(db_path) as db:
        await db.execute("SELECT ...")
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path

try:
    import aiosqlite
except ImportError:
    aiosqlite = None  # type: ignore[assignment]


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply standard PRAGMAs to a sync connection."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")


@contextmanager
def get_sync_db(db_path: str | Path):
    """Context manager yielding a sqlite3.Connection with standard PRAGMAs.

    Usage:
        with get_sync_db(db_path) as conn:
            row = conn.execute("SELECT ...").fetchone()
    """
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    _apply_pragmas(conn)
    try:
        yield conn
    finally:
        conn.close()


def get_sync_conn(db_path: str | Path) -> sqlite3.Connection:
    """Non-context-manager variant. Caller must close manually.

    Use get_sync_db() when possible. This exists for code paths that
    need a connection object without a with-block.
    """
    conn = sqlite3.connect(str(db_path), timeout=5.0)
    _apply_pragmas(conn)
    return conn


@asynccontextmanager
async def get_async_db(db_path: str | Path):
    """Async context manager yielding an aiosqlite.Connection with standard PRAGMAs.

    Usage:
        async with get_async_db(db_path) as db:
            await db.execute("SELECT ...")
    """
    if aiosqlite is None:
        raise ImportError("aiosqlite is required for async DB access")
    db = await aiosqlite.connect(str(db_path))
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    try:
        yield db
    finally:
        await db.close()
