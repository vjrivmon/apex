"""Auditoría 2026-07-03 (C13) — el gate que hace vinculante la regla #3:
no escribir código de producción antes de fase 5, en el punto de acción
(Write/Edit), no como prosa.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))

_HOOK = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "code-before-phase5-gate.py"


@pytest.fixture
def apex_project(tmp_path):
    (tmp_path / ".apex").mkdir()
    from context_db import ApexContextDB
    import asyncio
    db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
    asyncio.new_event_loop().run_until_complete(db.initialize())
    return tmp_path


def _set_phase(root: Path, num: int, status: str = "in_progress"):
    import asyncio
    from context_db import ApexContextDB
    db = ApexContextDB(str(root / ".apex" / "context.db"))
    asyncio.new_event_loop().run_until_complete(db.set_phase(num, status))


def _invoke(root: Path, file_path: str, tool="Write", env_extra=None):
    payload = {"tool_name": tool, "tool_input": {"file_path": file_path, "content": "x=1"}}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=str(root))
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload), capture_output=True, text=True,
        cwd=str(root), env=env, timeout=10)


def test_blocks_production_code_before_phase5(apex_project):
    cp = _invoke(apex_project, str(apex_project / "src" / "app.py"))
    assert cp.returncode == 2
    assert "regla absoluta #3" in cp.stderr


def test_allows_production_code_in_phase5(apex_project):
    _set_phase(apex_project, 5, "in_progress")
    cp = _invoke(apex_project, str(apex_project / "src" / "app.py"))
    assert cp.returncode == 0


def test_allows_tests_before_phase5(apex_project):
    cp = _invoke(apex_project, str(apex_project / "tests" / "test_app.py"))
    assert cp.returncode == 0


def test_allows_apex_and_wiki_writes(apex_project):
    assert _invoke(apex_project, str(apex_project / ".apex" / "note.py")).returncode == 0
    assert _invoke(apex_project, str(apex_project / "wiki" / "concepts" / "x.md")).returncode == 0


def test_allows_config_files(apex_project):
    assert _invoke(apex_project, str(apex_project / "pyproject.toml")).returncode == 0
    assert _invoke(apex_project, str(apex_project / "package.json")).returncode == 0


def test_allows_markdown_and_docs(apex_project):
    assert _invoke(apex_project, str(apex_project / "README.md")).returncode == 0
    assert _invoke(apex_project, str(apex_project / "docs" / "design.py")).returncode == 0


def test_escape_hatch_env(apex_project):
    cp = _invoke(apex_project, str(apex_project / "src" / "app.py"),
                 env_extra={"APEX_ALLOW_EARLY_CODE": "1"})
    assert cp.returncode == 0


def test_no_op_outside_apex_project(tmp_path):
    # sin .apex/: el hook no aplica
    cp = _invoke(tmp_path, str(tmp_path / "app.py"))
    assert cp.returncode == 0


def test_edit_tool_also_gated(apex_project):
    cp = _invoke(apex_project, str(apex_project / "src" / "app.py"), tool="Edit")
    assert cp.returncode == 2
