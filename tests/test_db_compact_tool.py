"""El compactador de la base de contexto es alcanzable desde el MCP.

`lib/db_compact.py` lleva desde el Sprint 12 escrito, con su CLI y su
docstring diciendo "Usage (from MCP tool or hook)", pero sin un solo
importador: era código muerto con intención. Estos tests fijan que la tool
existe, está registrada y hace lo que dice.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def apex_server_mod():
    """Carga mcp/apex_server.py sin que el directorio `mcp/` ensombrezca el SDK."""
    root = _REPO
    for p in ("", ".", str(root)):
        while p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, str(root / "lib"))
    sys.path.append(str(root))
    spec = importlib.util.spec_from_file_location(
        "apex_server", root / "mcp" / "apex_server.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apex_server"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    """Proyecto APEX con su context.db y un cwd dentro de él."""
    apex_dir = tmp_path / ".apex"
    apex_dir.mkdir()
    db = ApexContextDB(str(apex_dir / "context.db"))
    run(db.initialize())
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestToolRegistrada:
    def test_apex_db_compact_esta_registrada(self, apex_server_mod):
        tools = run(apex_server_mod.list_tools())
        assert "apex_db_compact" in {t.name for t in tools}

    def test_el_handler_esta_en_el_dispatch(self, apex_server_mod):
        assert "apex_db_compact" in apex_server_mod.HANDLERS

    def test_el_esquema_declara_retention_days(self, apex_server_mod):
        tools = run(apex_server_mod.list_tools())
        tool = next(t for t in tools if t.name == "apex_db_compact")
        props = tool.inputSchema.get("properties", {})
        assert "retention_days" in props


class TestComportamiento:
    def test_compacta_y_avisa_de_lo_que_hizo(self, apex_server_mod, proyecto):
        db_path = proyecto / ".apex" / "context.db"
        conn = sqlite3.connect(db_path)
        vieja = (
            datetime.now(timezone.utc) - timedelta(days=90)
        ).isoformat()
        conn.execute(
            "INSERT INTO tool_call_log (tool, created_at) VALUES (?,?)",
            ("viejo", vieja),
        )
        conn.commit()
        conn.close()

        res = run(apex_server_mod.call_tool(
            "apex_db_compact", {"retention_days": 30}
        ))
        texto = res[0].text
        assert "filas eliminadas: 1" in texto
        assert "tool_call_log" in texto
        assert "ERRORES" not in texto

        conn = sqlite3.connect(db_path)
        assert conn.execute("SELECT count(*) FROM tool_call_log").fetchone()[0] == 0
        conn.close()

    def test_sin_context_db_no_falla(self, apex_server_mod, tmp_path, monkeypatch):
        vacio = tmp_path / "sin-apex"
        vacio.mkdir()
        monkeypatch.chdir(vacio)
        res = run(apex_server_mod.call_tool("apex_db_compact", {}))
        assert "Nada que compactar" in res[0].text
