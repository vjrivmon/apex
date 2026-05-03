"""Tests del DESIGN.md scaffolder + validator (Sprint 10.1)."""
from __future__ import annotations

from pathlib import Path

import pytest

from design_md import (
    REQUIRED_SECTIONS,
    contrast_ratio,
    default_template,
    design_md_path,
    init_design_md,
    parse_design_md,
    validate,
    format_violations,
)


# ── Plantilla y init ─────────────────────────────────────────────────────

def test_template_contains_all_sections() -> None:
    md = default_template("Test")
    for section in REQUIRED_SECTIONS:
        assert f"## {section}" in md or f"## {section.capitalize()}" in md or \
               f"## {section} " in md or md.lower().count(f"## {section.lower()}") > 0


def test_init_creates_file(tmp_path: Path) -> None:
    path = init_design_md(tmp_path, brand_name="Acme")
    assert path == design_md_path(tmp_path)
    assert path.exists()
    text = path.read_text()
    assert "Acme" in text


def test_init_does_not_overwrite_by_default(tmp_path: Path) -> None:
    init_design_md(tmp_path, brand_name="V1")
    init_design_md(tmp_path, brand_name="V2")  # should NOT overwrite
    assert "V1" in (tmp_path / "DESIGN.md").read_text()
    assert "V2" not in (tmp_path / "DESIGN.md").read_text()


def test_init_overwrites_when_flag(tmp_path: Path) -> None:
    init_design_md(tmp_path, brand_name="V1")
    init_design_md(tmp_path, brand_name="V2", overwrite=True)
    assert "V2" in (tmp_path / "DESIGN.md").read_text()


# ── Parser ──────────────────────────────────────────────────────────────

def test_parse_default_template_finds_all_sections() -> None:
    md = default_template("X")
    parsed = parse_design_md(md)
    for s in REQUIRED_SECTIONS:
        assert s in parsed.sections_present


def test_parse_extracts_color_tokens() -> None:
    md = default_template("X")
    parsed = parse_design_md(md)
    assert "bg" in parsed.color_tokens
    assert parsed.color_tokens["bg"] == "#FAFAF7"
    assert parsed.color_tokens["text"] == "#111111"


def test_parse_detects_avoid_line() -> None:
    md = default_template("X")
    parsed = parse_design_md(md)
    assert parsed.has_avoid_line is True


def test_parse_detects_dark_mode() -> None:
    md = default_template("X")
    parsed = parse_design_md(md)
    assert parsed.has_dark_mode is True


def test_parse_empty() -> None:
    parsed = parse_design_md("")
    assert parsed.color_tokens == {}
    assert parsed.sections_present == set()


# ── Contraste WCAG ──────────────────────────────────────────────────────

def test_contrast_white_black_max() -> None:
    assert contrast_ratio("#FFFFFF", "#000000") == pytest.approx(21.0, rel=0.01)


def test_contrast_same_color_min() -> None:
    assert contrast_ratio("#888888", "#888888") == pytest.approx(1.0, rel=0.01)


def test_contrast_template_text_bg_passes_aa() -> None:
    md = default_template("X")
    parsed = parse_design_md(md)
    ratio = contrast_ratio(parsed.color_tokens["text"], parsed.color_tokens["bg"])
    assert ratio >= 4.5


# ── Validación completa ────────────────────────────────────────────────

def test_validate_template_passes() -> None:
    md = default_template("X")
    violations = validate(md)
    critical = [v for v in violations if v.severity == "critical"]
    assert critical == []


def test_validate_empty_critical() -> None:
    violations = validate("")
    severities = [v.severity for v in violations]
    assert "critical" in severities
    # 5 secciones críticas + warnings
    critical_count = sum(1 for v in violations if v.severity == "critical")
    assert critical_count >= len(REQUIRED_SECTIONS)


def test_validate_low_contrast_fails() -> None:
    md = """## Brand

Avoid: x

## Color

- bg: #FFFFFF
- text: #BBBBBB
- surface: #FFFFFF
- text-muted: #555555
- border: #EEEEEE
- accent: #CCCCCC

## Type

(snip)

## Components

(snip)

## Accessibility / Dark

Dark mode."""
    violations = validate(md)
    contrast_violations = [v for v in violations
                            if v.section == "color" and v.severity == "critical"]
    assert len(contrast_violations) >= 1


def test_format_violations_pass() -> None:
    out = format_violations([])
    assert "PASS" in out


def test_format_violations_fail() -> None:
    md = ""
    violations = validate(md)
    out = format_violations(violations)
    assert "FAIL" in out
    assert "violación" in out
