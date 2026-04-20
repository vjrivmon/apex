"""Tests del security gate (AgentArmor 8-layer)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from security_gate import check_gate, scaffold_templates, render_report


def test_gate_missing_without_scaffold(tmp_path: Path):
    (tmp_path / ".apex").mkdir()
    report = check_gate(tmp_path)
    # 8 capas, todas missing
    assert len(report.layers) == 8
    assert all(l.status == "missing" for l in report.layers)
    assert not report.passed


def test_scaffold_creates_8_files(tmp_path: Path):
    copied = scaffold_templates(tmp_path)
    # 8 layers + README
    assert len(copied) == 9
    sec_dir = tmp_path / ".apex" / "security"
    for L in ("L1-ingestion", "L2-storage", "L3-context", "L4-planning",
              "L5-execution", "L6-output", "L7-inter-agent", "L8-identity"):
        assert (sec_dir / f"{L}.md").exists()


def test_gate_blocks_with_pending_layers(tmp_path: Path):
    scaffold_templates(tmp_path)
    report = check_gate(tmp_path)
    # Todas las templates están en status: pending
    assert all(l.status == "pending" for l in report.layers)
    assert not report.passed


def test_gate_passes_when_all_layers_passed(tmp_path: Path):
    scaffold_templates(tmp_path)
    sec_dir = tmp_path / ".apex" / "security"
    # Marcar todas las capas como passed
    for md_file in sec_dir.glob("L*-*.md"):
        content = md_file.read_text()
        content = content.replace("status: pending", "status: passed")
        md_file.write_text(content)
    report = check_gate(tmp_path)
    assert report.passed
    assert all(l.status == "passed" for l in report.layers)


def test_render_report_includes_layer_icons(tmp_path: Path):
    scaffold_templates(tmp_path)
    report = check_gate(tmp_path)
    md = render_report(report)
    assert "AgentArmor" in md
    assert "L1" in md
    assert "L8" in md
    assert "pending" in md
