"""Auditoría 2026-07-03 (C5) — apex_init_project debe escribir un CLAUDE.md
binding en el proyecto guiado, para que las 20 reglas absolutas entren en el
contexto always-on de Claude Code (no solo tras un context pointer).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

_APEX_SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp" / "apex_server.py"

BEGIN = "<!-- APEX:BEGIN -->"
END = "<!-- APEX:END -->"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("apex_server_cmd", str(_APEX_SERVER_PATH))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_creates_claude_md_when_absent(mod, tmp_path):
    msg = mod._install_project_claude_md(tmp_path, "miproyecto")
    cmd = tmp_path / "CLAUDE.md"
    assert cmd.exists()
    text = cmd.read_text()
    assert BEGIN in text and END in text
    assert "miproyecto" in text
    assert "NUNCA" in text and "fase 5" in text
    assert "creado" in msg


def test_prepends_block_preserving_existing(mod, tmp_path):
    cmd = tmp_path / "CLAUDE.md"
    cmd.write_text("# Mi proyecto\n\nNotas propias del usuario.\n")
    mod._install_project_claude_md(tmp_path, "x")
    text = cmd.read_text()
    assert BEGIN in text
    assert "Notas propias del usuario." in text  # preserved
    assert text.index(BEGIN) < text.index("Notas propias")  # block first


def test_idempotent_skips_when_block_present(mod, tmp_path):
    mod._install_project_claude_md(tmp_path, "x")
    first = (tmp_path / "CLAUDE.md").read_text()
    msg = mod._install_project_claude_md(tmp_path, "x")
    second = (tmp_path / "CLAUDE.md").read_text()
    assert first == second  # no duplication
    assert "ya tiene bloque" in msg
    assert second.count(BEGIN) == 1


def test_force_regenerates_block_only(mod, tmp_path):
    cmd = tmp_path / "CLAUDE.md"
    cmd.write_text("# User\n")
    mod._install_project_claude_md(tmp_path, "x")
    # user edita fuera del bloque
    text = cmd.read_text() + "\nContenido añadido después.\n"
    cmd.write_text(text)
    mod._install_project_claude_md(tmp_path, "x", force=True)
    out = cmd.read_text()
    assert out.count(BEGIN) == 1
    assert "Contenido añadido después." in out  # user content survives


def test_skips_apex_repo_itself(mod):
    apex_root = mod._apex_root
    msg = mod._install_project_claude_md(apex_root, "apex")
    assert "omitido" in msg
