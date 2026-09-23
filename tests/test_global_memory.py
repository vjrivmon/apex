"""Bug/feature 2026-07-17 — routing de proyecto + memoria global inmutable.

Dos cosas que se descubrieron a la vez:
1. `_find_project_root()` ascendía hasta `~/.apex/` (config global) y lo
   trataba como proyecto: una carpeta suelta (galia) heredaba el contexto de
   otro proyecto (osyris-ideas). `_get_db()` ahora avisa en vez de servir
   contexto ajeno, y NUNCA resuelve a la BD global.
2. `~/.apex/context.db` es memoria global inmutable de errores GRAVES
   cross-project (append-only). Un proyecto local nunca la sobreescribe.
"""
from __future__ import annotations

import importlib.util
import os
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

import global_memory as gm  # noqa: E402

_APEX_SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp" / "apex_server.py"


@pytest.fixture(scope="module")
def apex_server_mod():
    spec = importlib.util.spec_from_file_location("apex_server_gm", str(_APEX_SERVER_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── routing guard ──

def test_dir_without_apex_raises_not_apex(apex_server_mod, tmp_path, monkeypatch):
    """Una carpeta sin .apex/ propio no debe heredar contexto ajeno."""
    loose = tmp_path / "galia"
    loose.mkdir()
    monkeypatch.chdir(loose)
    # el home simulado no tiene proyecto tampoco
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(apex_server_mod.NotAnApexProjectError):
        apex_server_mod._get_db()


def test_dir_with_own_apex_resolves_locally(apex_server_mod, tmp_path, monkeypatch):
    proj = tmp_path / "miproyecto"
    (proj / ".apex").mkdir(parents=True)
    (proj / ".apex" / "context.db").write_bytes(b"")  # basta con que exista el dir
    monkeypatch.chdir(proj)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    db = apex_server_mod._get_db()
    assert str(proj / ".apex" / "context.db") == str(db.db_path)


def test_never_resolves_to_global(apex_server_mod, tmp_path, monkeypatch):
    """Estar en el home (donde vive ~/.apex) nunca sirve el global como proyecto."""
    (tmp_path / ".apex").mkdir()
    (tmp_path / ".apex" / "context.db").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    with pytest.raises(apex_server_mod.NotAnApexProjectError):
        apex_server_mod._get_db()


# ── memoria global ──

def test_grave_error_is_recorded(tmp_path):
    dbp = tmp_path / "global.db"
    ok = gm.record_grave_error("proyA", "BUG crítico X", "no repetir", severity="critical", db_path=dbp)
    assert ok is True
    con = sqlite3.connect(str(dbp))
    rows = con.execute("SELECT project_id, severity, description FROM grave_errors").fetchall()
    con.close()
    assert rows == [("proyA", "critical", "BUG crítico X")]


def test_non_grave_error_is_ignored(tmp_path):
    dbp = tmp_path / "global.db"
    assert gm.record_grave_error("proyA", "aviso menor", "x", severity="medium", db_path=dbp) is False
    assert gm.record_grave_error("proyA", "otro", "x", severity="low", db_path=dbp) is False
    assert gm.count_grave_errors(dbp) == 0


def test_append_only_dedup(tmp_path):
    """Mismo (project_id, description) no duplica; distinto proyecto sí acumula."""
    dbp = tmp_path / "global.db"
    gm.record_grave_error("proyA", "mismo bug", "l", severity="high", db_path=dbp)
    gm.record_grave_error("proyA", "mismo bug", "l2", severity="high", db_path=dbp)  # dup
    gm.record_grave_error("proyB", "mismo bug", "l", severity="high", db_path=dbp)   # otro proyecto
    assert gm.count_grave_errors(dbp) == 2


def test_global_is_immutable_from_projects(tmp_path):
    """record_grave_error nunca UPDATE ni DELETE: solo INSERT OR IGNORE."""
    dbp = tmp_path / "global.db"
    gm.record_grave_error("proyA", "bug", "leccion original", severity="critical", db_path=dbp)
    # segundo intento con lección distinta: NO debe pisar la original
    gm.record_grave_error("proyA", "bug", "leccion MODIFICADA", severity="critical", db_path=dbp)
    con = sqlite3.connect(str(dbp))
    lesson = con.execute("SELECT lesson FROM grave_errors WHERE project_id='proyA'").fetchone()[0]
    con.close()
    assert lesson == "leccion original"


def test_init_project_en_carpeta_suelta_no_toca_el_global(apex_server_mod, tmp_path, monkeypatch):
    """Caso real 2026-09-22: "Motor Fisico 2D Propio" no tenía .apex/ ni .git/;
    apex_init_project subió hasta el home y escribió fases y decisiones en
    ~/.apex/context.db. Debe crear el .apex/ en la propia carpeta."""
    import asyncio

    (tmp_path / ".apex").mkdir()  # el home tiene su ~/.apex (config + memoria global)
    motor = tmp_path / "RoadToDevOps" / "Motor Fisico 2D Propio"
    motor.mkdir(parents=True)
    monkeypatch.chdir(motor)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))

    asyncio.run(apex_server_mod.call_tool("apex_init_project", {"name": "Motor"}))

    assert (motor / ".apex" / "context.db").exists()
    assert not (tmp_path / ".apex" / "context.db").exists()
