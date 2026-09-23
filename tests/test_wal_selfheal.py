"""Bug 2026-07-17 — self-heal de sidecars WAL corruptos.

Un rsync/backup externo dejó `context.db-wal` y `context.db-shm` como symlinks
auto-referenciales en feedback-juanmi. SQLite los seguía al abrir en modo WAL,
caía en ELOOP y abortaba con `unable to open database file`, dejando el MCP
muerto para ese proyecto. `_heal_wal_sidecars` los aparta antes del primer
connect.

Cubre:
- El symlink auto-referencial se sana y `initialize()` abre la BD sin error.
- Idempotencia: un segundo pase no falla ni re-renombra nada.
- Un `-wal` REGULAR con datos queda intacto byte-a-byte (protección anti-pérdida).
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

_APEX_SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp" / "apex_server.py"


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(scope="module")
def apex_server_mod():
    spec = importlib.util.spec_from_file_location(
        "apex_server_selfheal", str(_APEX_SERVER_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def real_db(tmp_path):
    """Crea una BD APEX real e inicializada, luego cierra sus sidecars."""
    from context_db import ApexContextDB

    (tmp_path / ".apex").mkdir()
    db_path = tmp_path / ".apex" / "context.db"
    db = ApexContextDB(str(db_path))
    run(db.initialize())
    # checkpoint TRUNCATE deja el .db autosuficiente, sin -wal/-shm colgando
    import sqlite3

    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    for suffix in ("-wal", "-shm"):
        side = Path(str(db_path) + suffix)
        if side.exists():
            side.unlink()
    return db_path


def _make_selfref_symlink(side: str) -> None:
    """Crea un symlink que apunta a su propia ruta absoluta (ELOOP)."""
    if os.path.lexists(side):
        os.unlink(side)
    os.symlink(side, side)


def test_selfref_symlink_is_healed(apex_server_mod, real_db):
    wal = str(real_db) + "-wal"
    _make_selfref_symlink(wal)
    assert os.path.islink(wal)
    # symlink auto-referencial: realpath resuelve a sí mismo, no existe destino
    assert os.path.realpath(wal) == wal
    assert not os.path.exists(wal)

    apex_server_mod._heal_wal_sidecars(real_db)

    # el symlink roto ya no está en su ruta; fue renombrado a .corrupt-*
    assert not os.path.islink(wal)
    corrupt = list(Path(real_db).parent.glob("context.db-wal.corrupt-*"))
    assert corrupt, "el symlink roto debería estar renombrado a .corrupt-*"


def test_initialize_succeeds_after_heal(apex_server_mod, real_db):
    """Reproduce el bug real: sin heal, initialize() aborta con ELOOP."""
    from context_db import ApexContextDB

    _make_selfref_symlink(str(real_db) + "-wal")
    _make_selfref_symlink(str(real_db) + "-shm")

    db = ApexContextDB(str(real_db))
    apex_server_mod._INITIALIZED_DB_PATHS.discard(str(real_db))
    # _ensure_db_schema llama _heal_wal_sidecars antes de initialize()
    run(apex_server_mod._ensure_db_schema(db))

    # BD abre y los datos siguen: initialize() crea las 15 fases APEX
    import sqlite3

    con = sqlite3.connect(str(real_db))
    assert con.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert con.execute("SELECT count(*) FROM phases").fetchone()[0] >= 15
    con.close()


def test_heal_is_idempotent(apex_server_mod, real_db):
    _make_selfref_symlink(str(real_db) + "-wal")
    apex_server_mod._heal_wal_sidecars(real_db)
    first = sorted(Path(real_db).parent.glob("context.db-wal.corrupt-*"))
    # segundo pase: no hay symlink que sanar, no falla, no crea otro .corrupt
    apex_server_mod._heal_wal_sidecars(real_db)
    second = sorted(Path(real_db).parent.glob("context.db-wal.corrupt-*"))
    assert first == second, "un segundo heal no debe renombrar de nuevo"


def test_real_wal_file_is_untouched(apex_server_mod, real_db):
    """Protección anti-pérdida: un -wal REGULAR con datos no se toca."""
    wal = Path(str(real_db) + "-wal")
    payload = b"WAL-DATA-PENDIENTE\x00\x01\x02" * 64
    wal.write_bytes(payload)
    assert not os.path.islink(wal)  # es fichero regular

    apex_server_mod._heal_wal_sidecars(real_db)

    # byte-a-byte intacto: nunca se renombra ni borra un -wal real
    assert wal.exists()
    assert wal.read_bytes() == payload
    assert not list(Path(real_db).parent.glob("context.db-wal.corrupt-*"))
