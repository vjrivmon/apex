"""Tests del research helper (Sprint 10.2). Sin red real — usamos HTML fixtures."""
from __future__ import annotations

import pytest

from research import (
    Signals,
    extract_signals,
    signals_to_markdown,
)


SAMPLE_HTML = """<!DOCTYPE html>
<html>
<head>
<title>Acme — The Modern Way</title>
<style>
body { font-family: Inter, sans-serif; color: #111111; }
.brand { color: #C45A3D; }
</style>
</head>
<body>
<nav>
  <a href="/">Home</a>
  <a href="/pricing">Pricing</a>
  <a href="/docs">Docs</a>
</nav>
<h1>Build great products faster</h1>
<h2>Ship in days, not weeks</h2>
<h2>Loved by 10k teams</h2>
<a class="btn-primary" href="/signup">Start free</a>
<button class="cta">Book a demo</button>
</body>
</html>
"""


def test_extract_title() -> None:
    s = extract_signals("https://x.com", SAMPLE_HTML)
    assert s.title == "Acme — The Modern Way"


def test_extract_h1() -> None:
    s = extract_signals("https://x.com", SAMPLE_HTML)
    assert s.h1 == ["Build great products faster"]


def test_extract_h2() -> None:
    s = extract_signals("https://x.com", SAMPLE_HTML)
    assert s.h2 == ["Ship in days, not weeks", "Loved by 10k teams"]


def test_extract_nav_links() -> None:
    s = extract_signals("https://x.com", SAMPLE_HTML)
    assert "Home" in s.nav_links
    assert "Pricing" in s.nav_links
    assert "Docs" in s.nav_links


def test_extract_ctas() -> None:
    s = extract_signals("https://x.com", SAMPLE_HTML)
    assert "Start free" in s.ctas
    assert "Book a demo" in s.ctas


def test_extract_colors() -> None:
    s = extract_signals("https://x.com", SAMPLE_HTML)
    assert "#111111" in s.colors
    assert "#C45A3D" in s.colors


def test_extract_fonts() -> None:
    s = extract_signals("https://x.com", SAMPLE_HTML)
    assert "Inter" in s.fonts


def test_extract_empty_html() -> None:
    s = extract_signals("https://x.com", "")
    assert s.title == ""
    assert s.h1 == []
    assert s.colors == []


def test_signals_to_markdown_includes_url() -> None:
    s = extract_signals("https://acme.dev", SAMPLE_HTML, fetcher="static")
    md = signals_to_markdown(s)
    assert "https://acme.dev" in md
    assert "Acme — The Modern Way" in md
    assert "Build great products faster" in md
    assert "static" in md


def test_dedupe_keeps_order() -> None:
    html = "<h2>A</h2><h2>B</h2><h2>A</h2><h2>C</h2>"
    s = extract_signals("https://x.com", html)
    assert s.h2 == ["A", "B", "C"]


def test_signals_dataclass_to_dict() -> None:
    s = Signals(url="x", title="y")
    d = s.to_dict()
    assert d["url"] == "x"
    assert d["title"] == "y"
    assert d["h1"] == []
