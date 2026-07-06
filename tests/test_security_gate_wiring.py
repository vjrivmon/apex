"""S21 — el gate 10.5 (AgentArmor) debe BLOQUEAR de verdad la entrada a
fase 11, tanto en el dispatcher MCP (apex_set_phase) como en el hook
phase-gate.py. Hallazgo critico de la auditoria 2026-06-26: estaba
documentado como bloqueante pero ningun codigo lo aplicaba.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

_APEX_SERVER_PATH = Path(__file__).resolve().parent.parent / "mcp" / "apex_server.py"
_HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "phase-gate.py"

_LAYERS = [
    ("L1", "ingestion"), ("L2", "storage"), ("L3", "context"),
    ("L4", "planning"), ("L5", "execution"), ("L6", "output"),
    ("L7", "inter-agent"), ("L8", "identity"),
]


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(scope="module")
def apex_server_mod():
    spec = importlib.util.spec_from_file_location(
        "apex_server_secgate", str(_APEX_SERVER_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def project_root(tmp_path, monkeypatch):
    (tmp_path / ".apex").mkdir()
    monkeypatch.chdir(tmp_path)
    from context_db import ApexContextDB
    db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
    run(db.initialize())
    return tmp_path


def _write_layers(root: Path, status: str) -> None:
    sec = root / ".apex" / "security"
    sec.mkdir(parents=True, exist_ok=True)
    for lid, name in _LAYERS:
        (sec / f"{lid}-{name}.md").write_text(
            f"---\nlayer: {lid}\nstatus: {status}\n---\n# {lid}\n",
            encoding="utf-8")


def _complete_phases_0_to_10(root: Path) -> None:
    """Deja fases 0-10 completadas para que la guarda de progresión secuencial
    (C4) no enmascare el gate de seguridad al entrar a fase 11."""
    from context_db import ApexContextDB
    db = ApexContextDB(str(root / ".apex" / "context.db"))
    for n in range(0, 11):
        run(db.set_phase(n, "completed"))


def _enter_11(mod, root: Path | None = None):
    if root is not None:
        _complete_phases_0_to_10(root)
    return run(mod.call_tool(
        "apex_set_phase",
        {"phase_number": 11, "status": "in_progress"}))[0].text


# ── Dispatcher (apex_set_phase) ──────────────────────────────────

def test_dispatcher_blocks_entry_to_11_when_layers_not_passed(apex_server_mod, project_root):
    _write_layers(project_root, "pending")
    text = _enter_11(apex_server_mod, project_root)
    assert "BLOQUEADO" in text and "seguridad" in text.lower()


def test_dispatcher_allows_entry_to_11_when_all_passed(apex_server_mod, project_root):
    _write_layers(project_root, "passed")
    text = _enter_11(apex_server_mod, project_root)
    assert "BLOQUEADO" not in text
    assert "Fase 11" in text


def test_dispatcher_blocks_when_no_security_dir(apex_server_mod, project_root):
    # C3 (auditoría 2026-07-03): fail-CLOSED. Llegar a deploy sin evidencia
    # AgentArmor bloquea; antes (Sprint 26) no bloqueaba (fail-open).
    assert not (project_root / ".apex" / "security").exists()
    text = _enter_11(apex_server_mod, project_root)
    assert "BLOQUEADO" in text and "seguridad" in text.lower()


def test_dispatcher_force_bypasses_and_records_override(apex_server_mod, project_root):
    _write_layers(project_root, "failed")
    _complete_phases_0_to_10(project_root)
    text = run(apex_server_mod.call_tool(
        "apex_set_phase",
        {"phase_number": 11, "status": "in_progress",
         "force": True, "force_reason": "deploy de emergencia"}))[0].text
    assert "BLOQUEADO" not in text
    # el override quedo registrado como error critico
    from context_db import ApexContextDB
    db = ApexContextDB(str(project_root / ".apex" / "context.db"))
    errors = run(db.get_errors())
    assert any("gate de seguridad" in (e.get("description") or "").lower()
               for e in errors)


# ── Hook (phase-gate.py) ─────────────────────────────────────────

def _invoke_hook(payload: dict, root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload), capture_output=True, text=True,
        cwd=str(root), env=env, timeout=10)


def _payload(force=False):
    p = {"tool_name": "apex_set_phase",
         "tool_input": {"phase_number": 11, "status": "in_progress"}}
    if force:
        p["tool_input"]["force"] = True
    return p


def test_hook_blocks_entry_to_11_when_not_passed(project_root):
    _write_layers(project_root, "pending")
    cp = _invoke_hook(_payload(), project_root)
    assert cp.returncode == 2
    assert "seguridad" in cp.stderr.lower()


def test_hook_allows_when_all_passed(project_root):
    _write_layers(project_root, "passed")
    cp = _invoke_hook(_payload(), project_root)
    assert cp.returncode == 0


def test_hook_blocks_when_no_security_dir(project_root):
    # C3 (auditoría 2026-07-03): fail-CLOSED en el hook también.
    cp = _invoke_hook(_payload(), project_root)
    assert cp.returncode == 2
    assert "seguridad" in cp.stderr.lower()


def test_hook_force_bypasses(project_root):
    _write_layers(project_root, "failed")
    cp = _invoke_hook(_payload(force=True), project_root)
    assert cp.returncode == 0
