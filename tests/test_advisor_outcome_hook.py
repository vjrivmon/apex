"""Sprint 16 S16.7 — hook .claude/hooks/advisor-outcome-watch.py.

Tests del comportamiento UserPromptSubmit:
- High-water mark se persiste y avanza con cada call.
- Antes del N-ésimo prompt, no ejecuta cycle (silent).
- En el N-ésimo, propone tuning si hay proposals pendientes.
- Errores internos no bloquean (exit 0 siempre).
"""
import asyncio
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK = REPO_ROOT / ".claude" / "hooks" / "advisor-outcome-watch.py"

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def project_root(tmp_path):
    (tmp_path / ".apex").mkdir()
    db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
    run(db.initialize())
    return tmp_path


def _seed_outcomes_for_tuning(db_path: str):
    """Siembra 20 outcomes (8 useful + 12 not_useful) en phase_drift
    para que apply_tuning encuentre 1 proposal."""
    with sqlite3.connect(db_path) as c:
        for rating, n in (("useful", 8), ("not_useful", 12)):
            for _ in range(n):
                cur = c.execute(
                    "INSERT INTO advisor_reviews (session_id, trigger_kind, status) "
                    "VALUES ('s', 'manual', 'completed')"
                )
                rid = cur.lastrowid
                cur = c.execute(
                    "INSERT INTO advisor_advice (review_id, kind, severity, title, body) "
                    "VALUES (?, 'phase_drift', 'warn', ?, 'B')",
                    (rid, f"adv-{rid}"),
                )
                aid = cur.lastrowid
                c.execute(
                    "INSERT INTO advice_outcomes "
                    "(advice_id, assoc_method, inferred_rating) "
                    "VALUES (?, 'temporal', ?)",
                    (aid, rating),
                )
        c.commit()


def _invoke(payload: dict, project_root: Path, env_extra: dict = None):
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    # Aislar facets dir para que freshness sea None
    env.setdefault("APEX_USAGE_DATA_ROOT", str(project_root / "_no_facets"))
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(project_root),
        timeout=10,
        env=env,
    )


def _read_counter(project_root: Path) -> int:
    db_path = project_root / ".apex" / "context.db"
    with sqlite3.connect(str(db_path)) as c:
        row = c.execute(
            "SELECT value FROM project_meta WHERE key='outcome_watch_prompt_count'"
        ).fetchone()
    return int(row[0]) if row else 0


class TestAdvisorOutcomeWatch:
    def test_increments_counter_on_each_call(self, project_root):
        for expected in (1, 2, 3):
            cp = _invoke(
                {"prompt": "hi", "cwd": str(project_root), "session_id": "s"},
                project_root,
                env_extra={"APEX_OUTCOME_WATCH_EVERY_N_PROMPTS": "10"},
            )
            assert cp.returncode == 0
            assert _read_counter(project_root) == expected

    def test_silent_before_threshold(self, project_root):
        """Con EVERY_N=10 y 9 calls: nunca emite stdout."""
        _seed_outcomes_for_tuning(
            str(project_root / ".apex" / "context.db")
        )
        for _ in range(9):
            cp = _invoke(
                {"prompt": "x", "cwd": str(project_root)},
                project_root,
                env_extra={"APEX_OUTCOME_WATCH_EVERY_N_PROMPTS": "10"},
            )
            assert cp.returncode == 0
            assert cp.stdout == ""

    def test_emits_proposal_on_threshold(self, project_root):
        _seed_outcomes_for_tuning(
            str(project_root / ".apex" / "context.db")
        )
        # Bajamos N a 3 para reducir runtime del test
        env_extra = {"APEX_OUTCOME_WATCH_EVERY_N_PROMPTS": "3"}
        # 2 calls silenciosas + 1 que dispara
        for _ in range(2):
            cp = _invoke(
                {"prompt": "x", "cwd": str(project_root)},
                project_root,
                env_extra=env_extra,
            )
            assert cp.stdout == ""
        cp = _invoke(
            {"prompt": "x", "cwd": str(project_root)},
            project_root,
            env_extra=env_extra,
        )
        assert cp.returncode == 0
        assert cp.stdout, "esperaba JSON con additionalContext en stdout"
        out = json.loads(cp.stdout)
        ac = out["hookSpecificOutput"]["additionalContext"]
        assert "phase_drift" in ac
        assert "tuning" in ac.lower()

    def test_does_not_block_on_internal_error(self, project_root, monkeypatch):
        """Aunque el hook reciba un payload corrupto, exit 0."""
        # stdin no JSON: el hook devuelve 0 silenciosamente.
        cp = subprocess.run(
            [sys.executable, str(HOOK)],
            input="not-json-{",
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=10,
        )
        assert cp.returncode == 0
        # Counter NO debe avanzar (no llegó a abrir BD válida con cwd válido)
        # En realidad, falla antes de increment_counter — ok.
