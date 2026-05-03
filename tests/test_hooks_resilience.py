"""Regresión Sprint 13.10: los hooks de UserPromptSubmit/SessionStart NO
deben caer en silencio cuando el python que los ejecuta no tiene una
dependencia opcional (caso real: aiosqlite ausente en /usr/bin/python3,
presente en .venv/bin/python3).

Bug original: `end-of-day-doctor.py` tenía un único `try/except` que
importaba `apex_doctor`, `wrapup_phrases`, `handoff` y `context_db`
(ApexContextDB). Si `context_db` fallaba (porque aiosqlite no estaba),
el except ponía TODOS los módulos a None y la primera línea de `main()`
hacía `return 0` sin output ni stderr. El doctor del Sprint 13 nunca
disparaba en producción.

Estos tests fuerzan el escenario simulando un ImportError de aiosqlite y
verificando que la rama del doctor sigue activa.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "end-of-day-doctor.py"
SETTINGS = REPO_ROOT / ".claude" / "settings.json"


def _load_hook_module():
    """Carga el hook como módulo para inspeccionar sus globals."""
    spec = importlib.util.spec_from_file_location("eod_hook", HOOK)
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(REPO_ROOT / "lib"))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def test_hook_imports_split_doctor_survives_handoff_failure(monkeypatch):
    """Si el bloque de handoff (context_db/aiosqlite) falla al importar,
    el hook DEBE seguir teniendo `_doc` y `_wp` operativos."""

    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import(name, *args, **kwargs):
        if name == "context_db" or name.startswith("aiosqlite"):
            raise ImportError(f"simulated: {name} not available")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)
    sys.path.insert(0, str(REPO_ROOT / "lib"))
    try:
        for mod_name in ("eod_hook", "context_db", "handoff"):
            sys.modules.pop(mod_name, None)
        spec = importlib.util.spec_from_file_location("eod_hook", HOOK)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(REPO_ROOT / "lib"))

    assert module._doc is not None, (
        "REGRESIÓN Sprint 13: si context_db/aiosqlite falla, _doc queda None y "
        "el hook hace return 0 silencioso. Los imports DEBEN estar separados."
    )
    assert module._wp is not None, "wrapup_phrases tampoco debe arrastrarse al fallo de context_db"
    assert module._ho is None, "handoff sí debe estar None (depende de context_db)"
    assert module.ApexContextDB is None


def test_hook_emits_throttle_message_when_imports_ok(tmp_path, monkeypatch):
    """End-to-end: con todos los imports OK y throttle activo, el hook
    debe imprimir el mensaje de throttle a stdout (no callar)."""
    import asyncio

    sys.path.insert(0, str(REPO_ROOT / "lib"))
    try:
        import apex_doctor as _doc
        from context_db import ApexContextDB
    finally:
        sys.path.remove(str(REPO_ROOT / "lib"))

    apex_dir = tmp_path / ".apex"
    apex_dir.mkdir()
    db_path = apex_dir / "context.db"
    db = ApexContextDB(str(db_path))
    asyncio.new_event_loop().run_until_complete(db.initialize())
    _doc._start_run(db_path, trigger="seed")
    _doc._finish_run(db_path, run_id=1, proposals_count=0, status="done")
    assert _doc.is_throttled(db_path), "fixture inválida: el seed debería dejar el doctor throttled"

    payload = {
        "prompt": "he acabado por hoy",
        "session_id": "regression-throttle-001",
        "transcript_path": "",
        "cwd": str(tmp_path),
    }

    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "lib")},
    )

    assert result.returncode == 0
    assert "[apex-doctor]" in result.stdout, (
        f"hook silencioso (regresión Sprint 13). stdout={result.stdout!r} "
        f"stderr={result.stderr!r}"
    )
    assert "Detectado cierre" in result.stdout
    assert "wrapup_phrase" in result.stdout


def test_settings_json_uses_venv_python_for_lib_hooks():
    """Los hooks que importan módulos de `lib/` deben ejecutarse con el
    python del venv (que tiene aiosqlite). Si alguien vuelve a poner
    `python3` (= /usr/bin/python3), context_db falla y el doctor se
    silencia.
    """
    data = json.loads(SETTINGS.read_text(encoding="utf-8"))
    hooks = data.get("hooks", {})
    seen_commands: list[str] = []
    for event_blocks in hooks.values():
        for block in event_blocks:
            for h in block.get("hooks", []):
                cmd = h.get("command", "")
                if "/.claude/hooks/" in cmd and cmd.endswith(".py"):
                    seen_commands.append(cmd)

    assert seen_commands, "el test no encontró ningún hook .py en settings.json"
    for cmd in seen_commands:
        assert ".venv/bin/python3" in cmd, (
            f"hook usa python sin venv: {cmd!r}. Debe usar "
            "$CLAUDE_PROJECT_DIR/.venv/bin/python3 para que aiosqlite (y "
            "el resto de deps de lib/) estén disponibles."
        )
