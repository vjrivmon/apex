"""S21 — apex_init_project debe instalar el harness (hooks) en el proyecto
guiado, no solo en el repo apex. Hallazgo critico de la auditoria
2026-06-26: 10 de 11 hooks solo corrian dentro de ~/RoadToDevOps/apex.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

_APEX_SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp" / "apex_server.py"
_APEX_ROOT = Path(__file__).resolve().parent.parent


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location(
        "apex_server_installer", str(_APEX_SERVER_PATH))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture
def guided_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _init(mod, **kw):
    args = {"name": "proyecto-guiado"}
    args.update(kw)
    return run(mod.call_tool("apex_init_project", args))[0].text


def test_init_writes_project_settings(mod, guided_project):
    text = _init(mod)
    settings = guided_project / ".claude" / "settings.json"
    assert settings.exists(), text
    data = json.loads(settings.read_text())
    assert set(data["hooks"]) == {"PreToolUse", "PostToolUse", "UserPromptSubmit"}


def test_init_writes_binding_claude_md(mod, guided_project):
    # C5 (auditoría 2026-07-03): init deja las reglas en el layer always-on.
    text = _init(mod)
    cmd = guided_project / "CLAUDE.md"
    assert cmd.exists(), text
    body = cmd.read_text()
    assert "<!-- APEX:BEGIN -->" in body
    assert "proyecto-guiado" in body
    assert "NUNCA" in body


def test_init_registers_code_gate_hook(mod, guided_project):
    # C13: el write-gate se instala en el proyecto guiado.
    _init(mod)
    data = json.loads((guided_project / ".claude" / "settings.json").read_text())
    pre = data["hooks"]["PreToolUse"]
    assert any(g["matcher"] == "Write|Edit|MultiEdit"
               and any("code-before-phase5-gate.py" in h["command"] for h in g["hooks"])
               for g in pre)


def test_hooks_point_at_apex_venv_and_repo(mod, guided_project):
    _init(mod)
    data = json.loads((guided_project / ".claude" / "settings.json").read_text())
    cmds = [h["command"]
            for groups in data["hooks"].values()
            for g in groups for h in g["hooks"]]
    venv = str(_APEX_ROOT / ".venv" / "bin" / "python3")
    hooks_dir = str(_APEX_ROOT / ".claude" / "hooks")
    assert cmds, "no commands registered"
    for c in cmds:
        assert c.startswith(venv), f"interpreter not apex venv: {c}"
        assert hooks_dir in c, f"hook not in apex repo: {c}"


def test_excludes_session_start_and_weekly_design_lint(mod, guided_project):
    # session-start.py ya esta a nivel usuario; weekly-design-lint solo aplica
    # a proyectos de diseno. No deben registrarse en proyectos guiados.
    _init(mod)
    raw = (guided_project / ".claude" / "settings.json").read_text()
    assert "session-start.py" not in raw
    assert "weekly-design-lint.py" not in raw


def test_phase_gate_registered_on_set_phase(mod, guided_project):
    _init(mod)
    data = json.loads((guided_project / ".claude" / "settings.json").read_text())
    pre = data["hooks"]["PreToolUse"]
    assert any(g["matcher"] == "mcp__apex__apex_set_phase"
               and any("phase-gate.py" in h["command"] for h in g["hooks"])
               for g in pre)


def test_idempotent_does_not_overwrite_without_force(mod, guided_project):
    _init(mod)
    settings = guided_project / ".claude" / "settings.json"
    settings.write_text('{"hooks": {"sentinel": true}}')
    text = _init(mod)  # segunda vez, sin force
    assert "ya existe" in text
    assert json.loads(settings.read_text()) == {"hooks": {"sentinel": True}}


def test_force_overwrites(mod, guided_project):
    _init(mod)
    settings = guided_project / ".claude" / "settings.json"
    settings.write_text('{"hooks": {"sentinel": true}}')
    _init(mod, force_hooks=True)
    data = json.loads(settings.read_text())
    assert "sentinel" not in data["hooks"]
    assert "PreToolUse" in data["hooks"]


def test_install_hooks_false_skips(mod, guided_project):
    text = _init(mod, install_hooks=False)
    assert not (guided_project / ".claude" / "settings.json").exists()


def test_skips_when_root_is_apex_repo(mod, monkeypatch):
    # Si el cwd ES el repo apex, no se sobrescribe su settings.json canonico.
    msg = mod._install_project_hooks(_APEX_ROOT)
    assert "omitido" in msg
