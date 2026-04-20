"""Tests del scanner reverse-engineer."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from reverse_engineer import scan_project, render_report_md, PHASE_CHECKERS


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)


def _git_commit_all(path: Path, msg: str = "c") -> None:
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=path, check=True)


def test_empty_repo_all_phases_partial_or_missing(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "placeholder.txt").write_text("x")
    _git_commit_all(tmp_path)
    report = scan_project(tmp_path)
    # 16 phases (0-14 + 10.5)
    assert len(report.phases) == 16
    # La mayoría debería estar en missing o partial
    statuses = [p.status for p in report.phases]
    assert statuses.count("completed") <= 2


def test_hexagonal_python_project_gives_high_scaffold_score(tmp_path: Path):
    _git_init(tmp_path)
    for d in ["domain", "ports", "adapters", "application", "infrastructure"]:
        (tmp_path / d).mkdir()
        (tmp_path / d / "__init__.py").write_text("")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\ndependencies=['fastapi']\n")
    (tmp_path / ".env.example").write_text("KEY=value\n")
    _git_commit_all(tmp_path)
    report = scan_project(tmp_path)
    p5 = next(p for p in report.phases if p.phase == 5)
    assert p5.score >= 0.5
    assert any("hexagonal" in e.lower() for e in p5.evidence)


def test_detects_emojis_as_antipattern(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "component.tsx").write_text(
        "export const Btn = () => <button>Hola mundo 🚀</button>"
    )
    _git_commit_all(tmp_path)
    report = scan_project(tmp_path)
    assert any(ap.id == "AP-01" for ap in report.anti_patterns)


def test_detects_env_tracked_in_git_as_high_finding(tmp_path: Path):
    _git_init(tmp_path)
    # Simular .env trackeado (¡error!)
    (tmp_path / ".env").write_text("SECRET=plain\n")
    (tmp_path / "main.py").write_text("print('hi')\n")
    _git_commit_all(tmp_path)
    report = scan_project(tmp_path)
    p10 = next(p for p in report.phases if p.phase == 10)
    assert any(".env" in m for m in p10.missing)
    # Debe haber al menos un finding high
    high = [f for f in report.findings if f.severity == "high"]
    assert high


def test_tests_directory_raises_phase_9(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_sample.py").write_text("def test_x():\n    assert True\n")
    (tmp_path / "tests" / "test_edge.py").write_text("def test_invalid_input():\n    assert True\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n[tool.coverage.run]\nsource=['.']\n")
    _git_commit_all(tmp_path)
    report = scan_project(tmp_path)
    p9 = next(p for p in report.phases if p.phase == 9)
    assert p9.score > 0
    assert p9.status in ("partial", "completed")


def test_dockerfile_plus_workflows_raises_phase_11(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "Dockerfile").write_text("FROM python:3.12\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: ci\non: push\n")
    _git_commit_all(tmp_path)
    report = scan_project(tmp_path)
    p11 = next(p for p in report.phases if p.phase == 11)
    assert p11.score >= 0.4


def test_docs_vs_code_detects_claim_without_evidence(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "README.md").write_text(
        "# Proyecto\n\nEn **producción** con hexagonal architecture y coverage completo.\n"
    )
    (tmp_path / "main.py").write_text("print('hello')\n")
    _git_commit_all(tmp_path)
    report = scan_project(tmp_path)
    mismatches = report.docs_vs_code.get("mismatches", [])
    # Al menos debe detectar una discrepancia (producción sin Docker ni CI)
    assert any("producción" in m or "production" in m.lower() or "hexagonal" in m.lower() for m in mismatches)


def test_render_report_includes_core_sections(tmp_path: Path):
    _git_init(tmp_path)
    (tmp_path / "app.py").write_text("x = 1\n")
    _git_commit_all(tmp_path)
    report = scan_project(tmp_path)
    md = render_report_md(report)
    assert "Completeness por fase" in md
    assert "Findings retroactivos" in md
    assert "Siguiente paso" in md


def test_sixteen_checkers_present():
    # 0..14 + 10.5 = 16 checkers
    assert len(PHASE_CHECKERS) == 16
