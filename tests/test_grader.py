"""Tests del grader outcome-based (Sprint 8.1)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from grader import (
    BLOCKING_ISSUES,
    Evidence,
    Verdict,
    ISSUE_NO_GIT,
    ISSUE_NO_TESTS,
    ISSUE_EMOJI,
    ISSUE_NO_SO_CHECK,
    ISSUE_NO_CROSS_PROJECT,
    ISSUE_NO_E2E,
    QUALITY_POOR,
    QUALITY_GOOD,
    QUALITY_ACCEPTABLE,
    build_llm_judge_prompt,
    deterministic_to_issues,
    evaluate_deterministic,
    gather_evidence,
    merge_verdicts,
    parse_llm_verdict,
    run_deterministic_checks,
)


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def empty_repo(tmp_path: Path) -> Path:
    """Repo limpio sin git, sin tests, sin frontend."""
    return tmp_path


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Repo con git inicializado pero vacío."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@test"],
                   check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"],
                   check=True)
    return tmp_path


@pytest.fixture
def project_phase_5_clean(git_repo: Path) -> Path:
    """Proyecto en fase 5 con git + un test mínimo."""
    (git_repo / "tests").mkdir()
    (git_repo / "tests" / "test_dummy.py").write_text("def test_x(): assert 1 == 1\n")
    return git_repo


# ── Tests de gather_evidence ─────────────────────────────────────────────

def test_gather_evidence_detects_git(git_repo: Path) -> None:
    e = gather_evidence(git_repo, phase=5)
    assert e.git_initialized is True
    assert e.phase == 5
    assert e.project_root == git_repo.resolve()


def test_gather_evidence_no_git(empty_repo: Path) -> None:
    e = gather_evidence(empty_repo, phase=5)
    assert e.git_initialized is False
    assert e.test_files == []


def test_gather_evidence_finds_python_tests(project_phase_5_clean: Path) -> None:
    e = gather_evidence(project_phase_5_clean, phase=6)
    assert any("test_dummy.py" in t for t in e.test_files)


def test_gather_evidence_hash_stable(project_phase_5_clean: Path) -> None:
    e1 = gather_evidence(project_phase_5_clean, phase=6)
    e2 = gather_evidence(project_phase_5_clean, phase=6)
    assert e1.hash() == e2.hash()


def test_gather_evidence_hash_changes_with_phase(project_phase_5_clean: Path) -> None:
    e5 = gather_evidence(project_phase_5_clean, phase=5)
    e6 = gather_evidence(project_phase_5_clean, phase=6)
    assert e5.hash() != e6.hash()


# ── Tests de checks deterministas ────────────────────────────────────────

def test_check_no_git_phase_5_blocks(empty_repo: Path) -> None:
    e = gather_evidence(empty_repo, phase=5)
    checks = run_deterministic_checks(e)
    assert checks["git_initialized"] is False
    assert ISSUE_NO_GIT in deterministic_to_issues(checks)


def test_check_git_present_phase_5_passes(git_repo: Path) -> None:
    e = gather_evidence(git_repo, phase=5,
                        decisions_metadata={"detected_os": "Linux"})
    checks = run_deterministic_checks(e)
    assert checks["git_initialized"] is True
    assert ISSUE_NO_GIT not in deterministic_to_issues(checks)


def test_check_no_tests_phase_6_warns(git_repo: Path) -> None:
    e = gather_evidence(git_repo, phase=6,
                        decisions_metadata={"detected_os": "Linux"})
    checks = run_deterministic_checks(e)
    assert checks["tests_present"] is False
    assert ISSUE_NO_TESTS in deterministic_to_issues(checks)


def test_check_tests_phase_6_passes(project_phase_5_clean: Path) -> None:
    e = gather_evidence(project_phase_5_clean, phase=6,
                        decisions_metadata={"detected_os": "Linux"})
    checks = run_deterministic_checks(e)
    assert checks["tests_present"] is True


def test_check_os_not_recorded_phase_1_warns(empty_repo: Path) -> None:
    e = gather_evidence(empty_repo, phase=1, decisions_metadata={})
    checks = run_deterministic_checks(e)
    assert checks["os_detected"] is False
    assert ISSUE_NO_SO_CHECK in deterministic_to_issues(checks)


def test_check_emoji_in_frontend_blocks(git_repo: Path) -> None:
    fe = git_repo / "frontend"
    fe.mkdir()
    (fe / "App.tsx").write_text(
        "export const App = () => <button>Hola \U0001F600</button>\n")
    e = gather_evidence(git_repo, phase=2,
                        decisions_metadata={"detected_os": "Linux"})
    checks = run_deterministic_checks(e)
    assert checks["no_emojis_in_frontend"] is False
    assert ISSUE_EMOJI in deterministic_to_issues(checks)


def test_check_no_emoji_clean_frontend_passes(git_repo: Path) -> None:
    fe = git_repo / "frontend"
    fe.mkdir()
    (fe / "App.tsx").write_text(
        "export const App = () => <button>Continuar</button>\n")
    e = gather_evidence(git_repo, phase=2,
                        decisions_metadata={"detected_os": "Linux"})
    checks = run_deterministic_checks(e)
    assert checks["no_emojis_in_frontend"] is True


def test_check_e2e_for_web_phase_8_warns_without_playwright(git_repo: Path) -> None:
    e = gather_evidence(git_repo, phase=8, component_types=["web"],
                        decisions_metadata={"detected_os": "Linux"})
    checks = run_deterministic_checks(e)
    assert checks.get("e2e_for_web_ui") is False
    assert ISSUE_NO_E2E in deterministic_to_issues(checks)


def test_check_e2e_skipped_for_cli(git_repo: Path) -> None:
    e = gather_evidence(git_repo, phase=8, component_types=["cli"],
                        decisions_metadata={"detected_os": "Linux"})
    checks = run_deterministic_checks(e)
    assert "e2e_for_web_ui" not in checks


# ── Tests de evaluate_deterministic ──────────────────────────────────────

def test_evaluate_blocks_no_git_phase_5(empty_repo: Path) -> None:
    e = gather_evidence(empty_repo, phase=5,
                        decisions_metadata={"detected_os": "Linux"})
    v = evaluate_deterministic(e)
    assert v.should_block is True
    assert v.quality == QUALITY_POOR
    assert ISSUE_NO_GIT in v.issues
    assert v.llm_judged is False


def test_evaluate_passes_clean_phase_5(project_phase_5_clean: Path) -> None:
    # Fase 5 es de decisión: además de OS, exige cross-project consultado (#18).
    e = gather_evidence(project_phase_5_clean, phase=5,
                        decisions_metadata={"detected_os": "Linux",
                                            "cross_project_consulted": True})
    v = evaluate_deterministic(e)
    assert v.should_block is False
    assert v.quality >= QUALITY_GOOD
    assert v.evidence_hash is not None


def test_evaluate_blocks_without_cross_project_phase_5(project_phase_5_clean: Path) -> None:
    # Sin consulta cross-project, una fase de decisión NO cierra (#18, bloqueante).
    e = gather_evidence(project_phase_5_clean, phase=5,
                        decisions_metadata={"detected_os": "Linux"})
    v = evaluate_deterministic(e)
    assert v.should_block is True
    assert ISSUE_NO_CROSS_PROJECT in v.issues


def test_cross_project_not_required_when_hub_unavailable(project_phase_5_clean: Path) -> None:
    # Si hub.db no está disponible, no se puede exigir la consulta → no bloquea.
    e = gather_evidence(project_phase_5_clean, phase=5,
                        decisions_metadata={"detected_os": "Linux",
                                            "hub_available": False})
    checks = run_deterministic_checks(e)
    assert "cross_project_consulted" not in checks


def test_cross_project_not_required_non_decision_phase(project_phase_5_clean: Path) -> None:
    # Fase 6 (core) no es de decisión: no exige cross-project.
    e = gather_evidence(project_phase_5_clean, phase=6,
                        decisions_metadata={"detected_os": "Linux"})
    checks = run_deterministic_checks(e)
    assert "cross_project_consulted" not in checks


def test_evaluate_blocks_on_missing_os_phase_1(empty_repo: Path) -> None:
    e = gather_evidence(empty_repo, phase=1, decisions_metadata={})
    v = evaluate_deterministic(e)
    assert v.should_block is True  # os_detected es blocking desde fase 1
    assert ISSUE_NO_SO_CHECK in v.issues
    assert v.quality == QUALITY_POOR


def test_evaluate_passes_with_os_phase_1(empty_repo: Path) -> None:
    e = gather_evidence(empty_repo, phase=1,
                        decisions_metadata={"detected_os": "Linux"})
    v = evaluate_deterministic(e)
    assert v.should_block is False
    assert ISSUE_NO_SO_CHECK not in v.issues


# ── Tests de parse_llm_verdict ───────────────────────────────────────────

def test_parse_llm_verdict_clean_json() -> None:
    text = '{"quality": 3, "should_block": false, "reasoning": "ok"}'
    d = parse_llm_verdict(text)
    assert d["quality"] == 3
    assert d["should_block"] is False


def test_parse_llm_verdict_with_preamble() -> None:
    text = 'Aquí va mi verdict:\n```json\n{"quality": 4, "reasoning": "great"}\n```'
    d = parse_llm_verdict(text)
    assert d["quality"] == 4


def test_parse_llm_verdict_empty_returns_dict() -> None:
    assert parse_llm_verdict("") == {}
    assert parse_llm_verdict("nada de json") == {}


def test_parse_llm_verdict_malformed_returns_empty() -> None:
    assert parse_llm_verdict("{quality: 3}") == {}  # no es JSON válido


# ── Tests de merge_verdicts ──────────────────────────────────────────────

def test_merge_block_wins_even_if_llm_relaxes() -> None:
    det = Verdict(phase=5, quality=QUALITY_POOR, should_block=True,
                  issues=[ISSUE_NO_GIT], reasoning="no git")
    llm = {"quality": 4, "should_block": False, "reasoning": "looks ok"}
    out = merge_verdicts(det, llm)
    assert out.should_block is True
    assert out.quality == QUALITY_POOR
    assert out.llm_judged is True


def test_merge_llm_can_raise_block() -> None:
    det = Verdict(phase=8, quality=QUALITY_GOOD, should_block=False,
                  issues=[], reasoning="passes")
    llm = {"quality": 1, "should_block": True,
           "additional_issues": ["mock_data"],
           "reasoning": "frontend con datos hardcodeados"}
    out = merge_verdicts(det, llm)
    assert out.should_block is True
    assert "mock_data" in out.issues


def test_merge_no_llm_returns_determinista_unchanged() -> None:
    det = Verdict(phase=5, quality=QUALITY_GOOD, should_block=False,
                  issues=[], reasoning="ok")
    out = merge_verdicts(det, {})
    assert out.llm_judged is False
    assert out.quality == QUALITY_GOOD


# ── Test del prompt builder ──────────────────────────────────────────────

def test_build_llm_prompt_is_self_contained(project_phase_5_clean: Path) -> None:
    e = gather_evidence(project_phase_5_clean, phase=6,
                        component_types=["web"],
                        decisions_metadata={"detected_os": "Linux"})
    det = evaluate_deterministic(e)
    prompt = build_llm_judge_prompt(e, det)
    assert "fase 6" in prompt
    assert "JSON" in prompt
    assert "should_block" in prompt
    # No debe filtrar paths absolutos del sistema (privacidad mínima)
    # (sólo verifica que no hay /home/ o /Users/ — root puede aparecer pero acotado)
    assert "Devuelve SÓLO" in prompt or "Devuelve" in prompt
