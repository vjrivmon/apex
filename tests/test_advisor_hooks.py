"""Sprint 15 S15.6 — tests para los 3 hooks (advisor-trigger, advice-injector,
trace-prompt). Patrón: subprocess + stdin JSON + stderr/stdout asserts.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_TRIGGER = REPO_ROOT / ".claude" / "hooks" / "advisor-trigger.py"
HOOK_INJECTOR = REPO_ROOT / ".claude" / "hooks" / "advice-injector.py"
HOOK_TRACE = REPO_ROOT / ".claude" / "hooks" / "trace-prompt.py"


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
import advisor  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def project_root(tmp_path):
    """tmp_path con .apex/context.db inicializada."""
    (tmp_path / ".apex").mkdir()
    db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
    run(db.initialize())
    return tmp_path


def _invoke(hook: Path, payload: dict, project_root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(project_root),
        timeout=10,
    )


# ── advisor-trigger.py ───────────────────────────────────────────

class TestAdvisorTrigger:
    def test_below_threshold_no_review(self, project_root):
        """Con count<8 y sin force, no debe crear review ni emitir aviso."""
        # 1 sola llamada → count=1, < 3 (min) y < 8 (interval)
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "x.py"},
            "tool_response": {},
            "cwd": str(project_root),
            "session_id": "s_test",
        }
        cp = _invoke(HOOK_TRIGGER, payload, project_root)
        assert cp.returncode == 0
        # No debería haber creado review (count <= threshold)
        with __import__("sqlite3").connect(
            str(project_root / ".apex" / "context.db")
        ) as c:
            row = c.execute("SELECT COUNT(*) FROM advisor_reviews").fetchone()
        assert row[0] == 0

    def test_force_trigger_creates_review(self, project_root):
        """apex_set_phase debe disparar review aunque count=0."""
        payload = {
            "tool_name": "mcp__apex__apex_set_phase",
            "tool_input": {"phase_number": 5, "status": "in_progress"},
            "tool_response": {"content": [{"text": "Fase 5 → in_progress"}]},
            "cwd": str(project_root),
            "session_id": "s_force",
        }
        cp = _invoke(HOOK_TRIGGER, payload, project_root)
        assert cp.returncode == 0
        assert "advisor_review" in cp.stderr
        with __import__("sqlite3").connect(
            str(project_root / ".apex" / "context.db")
        ) as c:
            row = c.execute(
                "SELECT trigger_kind FROM advisor_reviews WHERE session_id='s_force'"
            ).fetchone()
        assert row is not None
        assert row[0] == "force"


# ── advice-injector.py ───────────────────────────────────────────

class TestAdviceInjector:
    def test_silent_without_cards(self, project_root):
        payload = {"prompt": "hola", "cwd": str(project_root), "session_id": "s_sil"}
        cp = _invoke(HOOK_INJECTOR, payload, project_root)
        assert cp.returncode == 0
        assert cp.stdout == ""

    def test_emits_active_cards(self, project_root):
        # Sembrar advice activa
        db_path = str(project_root / ".apex" / "context.db")
        rid = advisor.record_review(db_path, "s_emit", "manual")
        advisor.record_advice(
            db_path, rid, "phase_drift", "critical",
            "Llevas 12 calls sin grader", "Fase 5 in_progress 30 min sin verdict",
            evidence_refs=["phase=5"],
        )
        payload = {"prompt": "...", "cwd": str(project_root), "session_id": "s_emit"}
        cp = _invoke(HOOK_INJECTOR, payload, project_root)
        assert cp.returncode == 0
        assert cp.stdout, "esperaba JSON con additionalContext en stdout"
        out = json.loads(cp.stdout)
        ctx = out["hookSpecificOutput"]["additionalContext"]
        assert "BLOQUEANTE" in ctx  # critical → bloque escalado
        assert "phase_drift" in ctx
        assert "Llevas 12 calls" in ctx


# ── trace-prompt.py ──────────────────────────────────────────────

class TestTracePrompt:
    def test_fires_on_phase_close(self, project_root):
        payload = {
            "tool_name": "mcp__apex__apex_set_phase",
            "tool_input": {"phase_number": 2, "status": "completed"},
            "tool_response": {},
            "cwd": str(project_root),
        }
        cp = _invoke(HOOK_TRACE, payload, project_root)
        assert cp.returncode == 0
        assert "[apex-trace]" in cp.stderr
        assert "multi_agent_coordination" in cp.stderr  # mapping fase 2

    def test_silent_on_unrelated_tool(self, project_root):
        payload = {
            "tool_name": "Read",
            "tool_input": {"file_path": "x.py"},
            "tool_response": {},
            "cwd": str(project_root),
        }
        cp = _invoke(HOOK_TRACE, payload, project_root)
        assert cp.returncode == 0
        assert "[apex-trace]" not in cp.stderr
