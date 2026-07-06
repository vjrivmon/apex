"""Auditoría 2026-07-03 — enforcement vinculante de apex_set_phase.

Cubre las tres guardas nuevas que convierten el gate de opt-in a binding:
- C2 fail-closed del grader: cerrar (completed) una fase sin verdict BLOQUEA.
- C4 progresión secuencial: abrir (in_progress) una fase saltándose previas
  no empezadas BLOQUEA.
- force=True sigue siendo el escape para las tres.

Ejercita tanto el dispatcher MCP (apex_set_phase) como el hook phase-gate.py.
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


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture(scope="module")
def apex_server_mod():
    spec = importlib.util.spec_from_file_location(
        "apex_server_enf", str(_APEX_SERVER_PATH))
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


def _db(root: Path):
    from context_db import ApexContextDB
    return ApexContextDB(str(root / ".apex" / "context.db"))


def _set_phase(mod, **kw):
    return run(mod.call_tool("apex_set_phase", kw))[0].text


def _seed_verdict(root: Path, phase: int, should_block: bool = False):
    """Inserta un verdict del grader para una fase."""
    db = _db(root)
    run(db.add_verdict(
        phase=phase, quality=3, reasoning="test",
        issues=[] if not should_block else ["algo mal"],
        should_block=should_block, evidence_hash="x"))


# ── C2: fail-closed del grader al CERRAR ────────────────────────────

def test_dispatcher_blocks_close_without_verdict(apex_server_mod, project_root):
    # Fase 5 in_progress, sin verdict → cerrar bloquea.
    run(_db(project_root).set_phase(5, "in_progress"))
    text = _set_phase(apex_server_mod, phase_number=5, status="completed")
    assert "BLOQUEADO" in text
    assert "grader" in text.lower()


def test_dispatcher_allows_close_with_passing_verdict(apex_server_mod, project_root):
    run(_db(project_root).set_phase(5, "in_progress"))
    _seed_verdict(project_root, 5, should_block=False)
    text = _set_phase(apex_server_mod, phase_number=5, status="completed")
    assert "BLOQUEADO" not in text
    assert "Fase 5" in text


def test_dispatcher_force_closes_without_verdict(apex_server_mod, project_root):
    run(_db(project_root).set_phase(5, "in_progress"))
    text = _set_phase(apex_server_mod, phase_number=5, status="completed",
                      force=True, force_reason="cierre manual")
    assert "BLOQUEADO" not in text


# ── C4: guarda de progresión secuencial al ABRIR ────────────────────

def test_dispatcher_blocks_phase_skip(apex_server_mod, project_root):
    # Proyecto recién iniciado (todas pending) → abrir fase 8 salta 0-7.
    text = _set_phase(apex_server_mod, phase_number=8, status="in_progress")
    assert "BLOQUEADO" in text
    assert "secuencial" in text.lower()


def test_dispatcher_allows_next_phase_when_prior_complete(apex_server_mod, project_root):
    db = _db(project_root)
    for n in range(0, 5):
        run(db.set_phase(n, "completed"))
    text = _set_phase(apex_server_mod, phase_number=5, status="in_progress")
    assert "BLOQUEADO" not in text


def test_dispatcher_force_bypasses_skip(apex_server_mod, project_root):
    text = _set_phase(apex_server_mod, phase_number=8, status="in_progress",
                      force=True, force_reason="salto deliberado")
    assert "BLOQUEADO" not in text


# ── Hook phase-gate.py: fail-closed del grader ──────────────────────

def _invoke_hook(payload: dict, root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload), capture_output=True, text=True,
        cwd=str(root), env=env, timeout=10)


def test_hook_blocks_close_without_verdict(project_root):
    run(_db(project_root).set_phase(5, "in_progress"))
    payload = {"tool_name": "apex_set_phase",
               "tool_input": {"phase_number": 5, "status": "completed"}}
    cp = _invoke_hook(payload, project_root)
    assert cp.returncode == 2
    assert "grader" in cp.stderr.lower()


def test_hook_allows_close_with_passing_verdict(project_root):
    run(_db(project_root).set_phase(5, "in_progress"))
    _seed_verdict(project_root, 5, should_block=False)
    payload = {"tool_name": "apex_set_phase",
               "tool_input": {"phase_number": 5, "status": "completed"}}
    cp = _invoke_hook(payload, project_root)
    assert cp.returncode == 0


def test_hook_force_bypasses_missing_verdict(project_root):
    run(_db(project_root).set_phase(5, "in_progress"))
    payload = {"tool_name": "apex_set_phase",
               "tool_input": {"phase_number": 5, "status": "completed",
                              "force": True}}
    cp = _invoke_hook(payload, project_root)
    assert cp.returncode == 0
