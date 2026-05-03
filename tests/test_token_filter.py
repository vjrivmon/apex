"""Tests del token_filter (Sprint 9.2)."""
from __future__ import annotations

import pytest

from token_filter import (
    DEFAULT_CHARS_THRESHOLD,
    char_count,
    line_count,
    matches_noisy_patterns,
    should_archive,
    summarize_for_context,
)


# ── Conteo ───────────────────────────────────────────────────────────────

def test_char_count_empty() -> None:
    assert char_count("") == 0
    assert char_count(None) == 0  # type: ignore[arg-type]


def test_char_count_basic() -> None:
    assert char_count("hello") == 5


def test_line_count_empty() -> None:
    assert line_count("") == 0


def test_line_count_basic() -> None:
    assert line_count("a\nb\nc") == 3


# ── Heurísticas ─────────────────────────────────────────────────────────

def test_should_archive_small_output() -> None:
    assert should_archive("hello world") is False


def test_should_archive_by_chars() -> None:
    big = "x" * (DEFAULT_CHARS_THRESHOLD + 1)
    assert should_archive(big) is True


def test_should_archive_by_lines() -> None:
    many = "\n".join(f"line {i}" for i in range(150))
    assert should_archive(many) is True


def test_should_archive_pip_logs() -> None:
    pip = "\n".join([
        "Collecting numpy",
        "Downloading numpy-1.0.0.tar.gz (10MB)",
        "Collecting pandas",
        "Downloading pandas-2.0.tar.gz (15MB)",
        "Collecting scipy",
        "Successfully installed numpy pandas scipy",
    ])
    assert should_archive(pip) is True


def test_matches_noisy_patterns_no_hits() -> None:
    assert matches_noisy_patterns("just regular output") is False


def test_matches_noisy_patterns_dep_tree() -> None:
    tree = "\n".join([
        "node_modules/",
        "├── lib1/",
        "├── lib2/",
        "├── lib3/",
        "├── lib4/",
        "├── lib5/",
        "└── lib6/",
    ])
    assert matches_noisy_patterns(tree) is True


# ── Resumen ──────────────────────────────────────────────────────────────

def test_summarize_short_returns_unchanged() -> None:
    out = "hello\nworld"
    assert summarize_for_context(out) == out


def test_summarize_long_keeps_head_and_tail() -> None:
    lines = [f"line {i}" for i in range(200)]
    out = "\n".join(lines)
    summary = summarize_for_context(out, head_lines=5, tail_lines=3)
    assert "line 0" in summary
    assert "line 4" in summary  # head_lines=5 → 0..4
    assert "line 199" in summary
    assert "líneas omitidas" in summary
    assert "apex_get_archived" in summary
    # No debe contener líneas del medio
    assert "line 100" not in summary


def test_summarize_respects_max_chars() -> None:
    out = "a" * 10_000
    summary = summarize_for_context(out, max_chars=200)
    assert len(summary) <= 250  # algo de margen por el sufijo


def test_summarize_empty() -> None:
    assert summarize_for_context("") == "(output vacío)"
