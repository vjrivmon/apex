"""Tests del handoff a 40% (Sprint 9.1)."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from handoff import (
    DEFAULT_CONTEXT_LIMIT,
    HANDOFF_THRESHOLD,
    collect_active_goals,
    estimate_tokens_in_transcript,
    is_over_threshold,
    list_handoffs,
    load_handoff,
    render_handoff,
    serialize_handoff,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Estimación de tokens ─────────────────────────────────────────────────

def test_estimate_tokens_missing_file(tmp_path: Path) -> None:
    assert estimate_tokens_in_transcript(tmp_path / "no_existe.jsonl") == 0


def test_estimate_tokens_chars_div_4(tmp_path: Path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text("a" * 4000)
    tokens = estimate_tokens_in_transcript(f)
    assert tokens == 1000


def test_is_over_threshold_below(tmp_path: Path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text("a" * 4000)  # ~1000 tokens
    assert is_over_threshold(f, context_limit=200_000) is False


def test_is_over_threshold_above(tmp_path: Path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text("a" * 400_000)  # ~100_000 tokens > 80_000 (40% de 200K)
    assert is_over_threshold(f, context_limit=200_000) is True


def test_is_over_threshold_custom_limit(tmp_path: Path) -> None:
    f = tmp_path / "t.jsonl"
    f.write_text("a" * 4000)  # ~1000 tokens
    assert is_over_threshold(f, threshold=0.40, context_limit=2000) is True


# ── Goals activos ────────────────────────────────────────────────────────

def test_collect_active_goals_empty(tmp_path: Path) -> None:
    assert collect_active_goals(tmp_path) == []


def test_collect_active_goals_filters_terminal(tmp_path: Path) -> None:
    goal_dir = tmp_path / ".apex" / "goal"
    goal_dir.mkdir(parents=True)
    (goal_dir / "active.json").write_text(json.dumps({
        "id": "active1", "goal": "Test goal active",
        "turn_budget": 10, "turns_used": 3, "status": "active",
    }))
    (goal_dir / "done.json").write_text(json.dumps({
        "id": "done1", "goal": "Test goal done",
        "turn_budget": 10, "turns_used": 5, "status": "done",
    }))
    actives = collect_active_goals(tmp_path)
    assert len(actives) == 1
    assert actives[0]["id"] == "active1"


def test_collect_active_goals_handles_corrupt_json(tmp_path: Path) -> None:
    goal_dir = tmp_path / ".apex" / "goal"
    goal_dir.mkdir(parents=True)
    (goal_dir / "ok.json").write_text(json.dumps({
        "id": "ok", "goal": "ok", "turn_budget": 5, "turns_used": 1,
        "status": "active",
    }))
    (goal_dir / "bad.json").write_text("{not valid json")
    actives = collect_active_goals(tmp_path)
    assert len(actives) == 1
    assert actives[0]["id"] == "ok"


# ── Render ───────────────────────────────────────────────────────────────

def test_render_handoff_minimal() -> None:
    md = render_handoff(
        state={"current_phase": None, "blocking_verdicts": [],
               "recent_verdicts": []},
        active_goals=[],
        session_id="abc123",
        transcript_tokens=42_000,
    )
    assert "Handoff" in md
    assert "abc123" in md
    assert "42,000" in md
    assert "(ninguna en `in_progress`)" in md


def test_render_handoff_with_blocking_verdict() -> None:
    md = render_handoff(
        state={
            "current_phase": {"number": 5, "name": "scaffold",
                              "status": "in_progress", "notes": ""},
            "blocking_verdicts": [{
                "id": 1, "phase": 5, "quality": 1,
                "issues": ["no_git_init"], "should_block": True,
                "reasoning": "Sin git inicializado.",
                "created_at": "2026-05-03T10:00:00",
            }],
            "recent_verdicts": [],
        },
        active_goals=[],
        session_id="s1",
        transcript_tokens=80_000,
    )
    assert "BLOQUEANDO" in md
    assert "no_git_init" in md
    assert "Fase 5" in md


def test_render_handoff_with_active_goals() -> None:
    md = render_handoff(
        state={"current_phase": None, "blocking_verdicts": [],
               "recent_verdicts": []},
        active_goals=[{
            "id": "g1", "goal": "Fix tests", "turn_budget": 10,
            "turns_used": 4,
        }],
        session_id="s1",
        transcript_tokens=0,
    )
    assert "Goals activos" in md
    assert "g1" in md
    assert "Fix tests" in md
    assert "4/10" in md


# ── Serialización (con BD real) ─────────────────────────────────────────

def test_serialize_and_load_roundtrip(tmp_path: Path) -> None:
    """Crea una BD, escribe handoff, lo lee."""
    from context_db import ApexContextDB

    db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
    _run(db.initialize())

    project_root = tmp_path
    path = _run(serialize_handoff(project_root, "session-xyz", db,
                                   transcript_tokens=1000))
    assert path.exists()
    assert path.name == "session-xyz.md"

    loaded = load_handoff(project_root, "session-xyz")
    assert loaded is not None
    assert "session-xyz" in loaded
    assert "1,000" in loaded


def test_load_handoff_missing(tmp_path: Path) -> None:
    assert load_handoff(tmp_path, "no-existe") is None


def test_list_handoffs_orders_by_mtime(tmp_path: Path) -> None:
    import time
    d = tmp_path / ".apex" / "handoff"
    d.mkdir(parents=True)
    (d / "old.md").write_text("a")
    time.sleep(0.01)
    (d / "new.md").write_text("b")

    out = list_handoffs(tmp_path)
    assert len(out) == 2
    assert out[0]["session_id"] == "new"
    assert out[1]["session_id"] == "old"
