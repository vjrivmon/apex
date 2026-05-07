"""Tests del /goal turn-budget loop (Sprint 8.2)."""
from __future__ import annotations

from pathlib import Path

import pytest

from goal_loop import (
    DECISION_CONTINUE,
    DECISION_DEGENERATE,
    DECISION_DONE,
    STATUS_ACTIVE,
    STATUS_BUDGET_EXHAUSTED,
    STATUS_CONTEXT_THRESHOLD,
    STATUS_DEGENERATE,
    STATUS_DONE,
    STATUS_PAUSED,
    apply_judge_decision,
    build_judge_prompt,
    list_active_goals,
    load_goal,
    parse_judge_decision,
    pause_goal,
    record_turn,
    start_goal,
)


def test_start_goal_creates_state(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "Make tests green", turn_budget=5)
    assert s.goal == "Make tests green"
    assert s.turn_budget == 5
    assert s.turns_used == 0
    assert s.status == STATUS_ACTIVE
    assert len(s.id) == 12


def test_start_goal_persists_to_disk(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "X")
    path = tmp_path / ".apex" / "goal" / f"{s.id}.json"
    assert path.exists()


def test_load_goal_roundtrip(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "Build feature X", turn_budget=10)
    loaded = load_goal(tmp_path, s.id)
    assert loaded.goal == s.goal
    assert loaded.turn_budget == 10


def test_record_turn_increments_count(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "X", turn_budget=3)
    s = record_turn(tmp_path, s.id, "Did A", ["Read", "Edit"])
    assert s.turns_used == 1
    assert s.history[0]["summary"] == "Did A"
    assert s.history[0]["tools_used"] == ["Read", "Edit"]


def test_budget_exhausted_at_limit(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "X", turn_budget=2)
    record_turn(tmp_path, s.id, "T1")
    s = record_turn(tmp_path, s.id, "T2")
    assert s.turns_used == 2
    assert s.status == STATUS_BUDGET_EXHAUSTED


def test_record_turn_stops_at_terminal(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "X", turn_budget=1)
    s = record_turn(tmp_path, s.id, "T1")
    assert s.status == STATUS_BUDGET_EXHAUSTED
    s = record_turn(tmp_path, s.id, "T2")  # ya terminal, no incrementa
    assert s.turns_used == 1


def test_judge_done_marks_status(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "X")
    record_turn(tmp_path, s.id, "T1")
    s = apply_judge_decision(tmp_path, s.id,
                              {"decision": DECISION_DONE, "reason": "all green"})
    assert s.status == STATUS_DONE


def test_judge_degenerate_marks_status(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "X")
    record_turn(tmp_path, s.id, "T1")
    record_turn(tmp_path, s.id, "T1 again")
    s = apply_judge_decision(tmp_path, s.id,
                              {"decision": DECISION_DEGENERATE,
                               "reason": "no progreso"})
    assert s.status == STATUS_DEGENERATE


def test_judge_continue_keeps_active(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "X")
    record_turn(tmp_path, s.id, "T1")
    s = apply_judge_decision(tmp_path, s.id,
                              {"decision": DECISION_CONTINUE,
                               "reason": "sigue trabajando"})
    assert s.status == STATUS_ACTIVE


def test_pause_goal(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "X")
    s = pause_goal(tmp_path, s.id)
    assert s.status == STATUS_PAUSED


def test_list_active_excludes_terminal(tmp_path: Path) -> None:
    a = start_goal(tmp_path, "A")
    b = start_goal(tmp_path, "B")
    apply_judge_decision(tmp_path, b.id,
                         {"decision": DECISION_DONE, "reason": "done"})
    actives = list_active_goals(tmp_path)
    ids = {g.id for g in actives}
    assert a.id in ids
    assert b.id not in ids


def test_parse_judge_clean_json() -> None:
    text = '{"decision": "done", "reason": "tests pasan"}'
    d = parse_judge_decision(text)
    assert d["decision"] == DECISION_DONE


def test_parse_judge_with_preamble() -> None:
    text = 'Mi veredicto:\n{"decision": "continue", "reason": "still working"}'
    d = parse_judge_decision(text)
    assert d["decision"] == DECISION_CONTINUE


def test_parse_judge_invalid_decision_falls_back() -> None:
    text = '{"decision": "weird", "reason": "x"}'
    d = parse_judge_decision(text)
    assert d["decision"] == DECISION_CONTINUE


def test_parse_judge_no_json_heuristic() -> None:
    assert parse_judge_decision("done.").get("decision") == DECISION_DONE
    assert parse_judge_decision("degenerate loop").get("decision") == DECISION_DEGENERATE
    assert parse_judge_decision("ehh").get("decision") == DECISION_CONTINUE


def test_parse_judge_empty() -> None:
    d = parse_judge_decision("")
    assert d["decision"] == DECISION_CONTINUE


def test_build_prompt_self_contained(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "Fix tests in tests/", turn_budget=10)
    record_turn(tmp_path, s.id, "Read tests/foo.py")
    record_turn(tmp_path, s.id, "Edited tests/foo.py")
    s = load_goal(tmp_path, s.id)
    prompt = build_judge_prompt(s)
    assert "Fix tests in tests/" in prompt
    assert "Turnos usados: 2 / 10" in prompt
    assert "decision" in prompt
    assert "done|continue|degenerate" in prompt


def test_build_prompt_excludes_judge_self_history(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "X")
    record_turn(tmp_path, s.id, "T1")
    apply_judge_decision(tmp_path, s.id,
                         {"decision": DECISION_CONTINUE, "reason": "go on"})
    s = load_goal(tmp_path, s.id)
    prompt = build_judge_prompt(s)
    # El último entry es del juez, no debe aparecer en el bloque de turnos
    assert "[judge]" not in prompt


# ── context_threshold trigger (sprint corto: /goal + auto-handoff) ────────


def _write_fake_transcript(path: Path, size_bytes: int) -> Path:
    path.write_text("x" * size_bytes, encoding="utf-8")
    return path


def test_record_turn_no_transcript_path_keeps_legacy_behavior(
    tmp_path: Path,
) -> None:
    s = start_goal(tmp_path, "legacy", turn_budget=3)
    state = record_turn(tmp_path, s.id, "T1")
    assert state.status == STATUS_ACTIVE
    assert "transcript_tokens" not in state.history[-1]


def test_record_turn_below_threshold_stays_active(tmp_path: Path) -> None:
    s = start_goal(tmp_path, "below", turn_budget=5)
    transcript = _write_fake_transcript(tmp_path / "t.jsonl", 4_000)  # ~1000 tk
    state = record_turn(
        tmp_path, s.id, "small turn",
        transcript_path=transcript,
        threshold_tokens=200_000,
    )
    assert state.status == STATUS_ACTIVE
    last = state.history[-1]
    assert last["transcript_tokens"] == 1_000
    assert "threshold_tokens" not in last


def test_record_turn_over_threshold_marks_context_threshold(
    tmp_path: Path,
) -> None:
    s = start_goal(tmp_path, "over", turn_budget=10)
    # 4 chars/token => 800_000 bytes ≈ 200_000 tokens (== umbral)
    transcript = _write_fake_transcript(tmp_path / "t.jsonl", 900_000)
    state = record_turn(
        tmp_path, s.id, "big turn",
        transcript_path=transcript,
        threshold_tokens=200_000,
    )
    assert state.status == STATUS_CONTEXT_THRESHOLD
    last = state.history[-1]
    assert last["transcript_tokens"] == 225_000
    assert last["threshold_tokens"] == 200_000


def test_context_threshold_overrides_budget_exhausted(tmp_path: Path) -> None:
    """Si el último turno cumple budget Y umbral, gana context_threshold."""
    s = start_goal(tmp_path, "both", turn_budget=1)
    transcript = _write_fake_transcript(tmp_path / "t.jsonl", 900_000)
    state = record_turn(
        tmp_path, s.id, "final turn",
        transcript_path=transcript,
        threshold_tokens=200_000,
    )
    # Budget se agotó (1/1) Y umbral cruzado: prevalece context_threshold
    assert state.turns_used == 1
    assert state.status == STATUS_CONTEXT_THRESHOLD


def test_record_turn_threshold_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APEX_HANDOFF_THRESHOLD_TOKENS", "5000")
    s = start_goal(tmp_path, "env", turn_budget=10)
    transcript = _write_fake_transcript(tmp_path / "t.jsonl", 24_000)  # 6000 tk
    state = record_turn(
        tmp_path, s.id, "env-driven", transcript_path=transcript,
    )
    assert state.status == STATUS_CONTEXT_THRESHOLD
    assert state.history[-1]["threshold_tokens"] == 5_000
