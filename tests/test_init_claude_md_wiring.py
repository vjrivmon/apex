"""S19.2 / S19.3: el cableado desde el MCP.

`lib/init_claude_md.py` y las slash commands se escribieron como módulos
sueltos (S19.2, S19.3 del blueprint). Estos tests fijan que están CONECTADOS:
`apex_init_project` genera el CLAUDE.md APEX-aware e instala los comandos, y
`apex_set_phase` refresca la fase en el bloque.

Sin esto, los módulos son código muerto con tests: exactamente el problema
que arrastra `lib/db_compact.py` desde el Sprint 12.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
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
    """Proyecto APEX recién inicializado, con el cwd dentro de él."""
    apex_dir = tmp_path / ".apex"
    apex_dir.mkdir()
    db = ApexContextDB(str(apex_dir / "context.db"))
    run(db.initialize())
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestInitProject:
    def test_genera_el_claude_md_apex_aware(self, apex_server_mod, proyecto):
        res = run(apex_server_mod.call_tool(
            "apex_init_project", {"name": "demo"}
        ))
        texto = res[0].text
        claude_md = proyecto / "CLAUDE.md"
        assert claude_md.exists(), texto
        assert "APEX-AWARE" in claude_md.read_text(encoding="utf-8")
        assert "CLAUDE.md APEX-aware" in texto

    def test_instala_las_slash_commands(self, apex_server_mod, proyecto):
        res = run(apex_server_mod.call_tool(
            "apex_init_project", {"name": "demo"}
        ))
        comandos = proyecto / ".claude" / "commands"
        assert comandos.is_dir(), res[0].text
        assert (comandos / "apex-decision.md").exists()
        assert (comandos / "apex-error.md").exists()
        assert (comandos / "apex-component.md").exists()
        assert (comandos / "apex-search.md").exists()

    def test_no_pisa_un_claude_md_preexistente(
        self, apex_server_mod, proyecto,
    ):
        claude_md = proyecto / "CLAUDE.md"
        claude_md.write_text(
            "# Mi proyecto\n\nContenido del usuario que no se toca.\n",
            encoding="utf-8",
        )
        run(apex_server_mod.call_tool("apex_init_project", {"name": "demo"}))
        texto = claude_md.read_text(encoding="utf-8")
        assert "Contenido del usuario que no se toca." in texto
        assert "APEX-AWARE" in texto

    def test_es_idempotente(self, apex_server_mod, proyecto):
        run(apex_server_mod.call_tool("apex_init_project", {"name": "demo"}))
        primera = (proyecto / "CLAUDE.md").read_text(encoding="utf-8")
        run(apex_server_mod.call_tool("apex_init_project", {"name": "demo"}))
        segunda = (proyecto / "CLAUDE.md").read_text(encoding="utf-8")
        assert primera == segunda
        # Y el bloque marcable aparece UNA sola vez.
        assert segunda.count("<!-- APEX-AWARE START -->") == 1


class TestSetPhaseRefrescaElBloque:
    def test_la_fase_actual_aparece_en_el_claude_md(
        self, apex_server_mod, proyecto,
    ):
        run(apex_server_mod.call_tool("apex_init_project", {"name": "demo"}))
        claude_md = proyecto / "CLAUDE.md"
        antes = claude_md.read_text(encoding="utf-8")

        run(apex_server_mod.call_tool(
            "apex_set_phase", {"phase_number": 3, "status": "in_progress"}
        ))

        despues = claude_md.read_text(encoding="utf-8")
        assert despues != antes, "el bloque APEX-AWARE debe reflejar la fase"
        assert "APEX-AWARE" in despues
        # Un solo bloque, aunque se haya llamado varias veces.
        assert despues.count("<!-- APEX-AWARE START -->") == 1
