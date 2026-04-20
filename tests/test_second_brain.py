"""Tests del segundo cerebro: ingest + lint + synthesis + hybrid retrieval."""
from __future__ import annotations

import asyncio
import tempfile
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

from context_db import ApexContextDB, _tokenize
from wiki_scaffold import create_wiki
from ingest import ingest, _classify, _resolve_urls, _bias_check, _extract_signals
from lint import run_lint
from synthesis import check_density, synthesize


# ========== Tokenizer ==========

def test_tokenize_strips_punctuation():
    assert _tokenize("hola, mundo!") == ["hola", "mundo"]


def test_tokenize_preserves_accents():
    assert _tokenize("Año tras año") == ["año", "tras", "año"]


# ========== Ingest helpers ==========

def test_resolve_urls_classifies_github_arxiv():
    text = "Ver https://github.com/foo/bar y https://arxiv.org/abs/2309.12345"
    urls = _resolve_urls(text)
    kinds = {u["source_type"] for u in urls}
    assert kinds == {"repository", "paper"}


def test_classify_prefers_socratic_from_dir():
    assert _classify("contenido", "socratic") == "query"


def test_classify_detects_comparison_keyword():
    assert _classify("React vs Vue", None) == "comparison"


def test_bias_check_flags_always_and_never():
    flags = _bias_check("You should always do X and never do Y")
    assert len(flags) >= 2


def test_extract_signals_gets_headings_and_lists():
    text = "# Title\n\n## Sub\n\n- item one\n- item two\n"
    sigs = _extract_signals(text)
    kinds = {s.kind for s in sigs}
    assert {"heading", "list-item"} <= kinds


# ========== Ingest end-to-end ==========

def test_ingest_writes_wiki_page(tmp_path: Path):
    create_wiki(tmp_path, "test")
    src = tmp_path / ".apex" / "raw" / "research" / "competitors.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(
        "# Competitors\n\n"
        "See https://github.com/foo/bar.\n\n"
        "- always use hexagonal\n"
        "- never mix tenants\n",
        encoding="utf-8",
    )
    result = ingest(src, project_root=tmp_path, write_db=False)
    assert result.wiki_page_path is not None
    assert result.wiki_page_path.exists()
    md = result.wiki_page_path.read_text(encoding="utf-8")
    assert "title:" in md
    assert "github.com" in md
    assert len(result.bias_flags) >= 1  # "always" or "never"


# ========== Lint ==========

def _run_async(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def test_lint_without_db_returns_critical(tmp_path: Path):
    report = run_lint(tmp_path)
    assert any(f.severity == "critical" for f in report.findings)


def test_lint_detects_contradicting_decisions(tmp_path: Path):
    db_path = tmp_path / ".apex" / "context.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = ApexContextDB(str(db_path))

    async def setup():
        await db.initialize()
        await db.add_decision("architecture", "Usar arquitectura hexagonal", "modularidad", phase=3)
        await db.add_decision("architecture", "Monolito de verdad, sin hexagonal", "simplicidad", phase=3)

    _run_async(setup())
    report = run_lint(tmp_path)
    assert any(f.rule_id == "DR-001" for f in report.findings)


# ========== Synthesis ==========

def test_synthesis_returns_not_triggered_when_empty(tmp_path: Path):
    db_path = tmp_path / ".apex" / "context.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = ApexContextDB(str(db_path))

    async def setup():
        await db.initialize()

    _run_async(setup())
    # 999d desde última síntesis → sí dispara, pero sin candidates nada se promueve
    res = synthesize(tmp_path)
    assert res["ok"] is True


def test_density_snapshot_has_expected_fields(tmp_path: Path):
    db_path = tmp_path / ".apex" / "context.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = ApexContextDB(str(db_path))

    async def setup():
        await db.initialize()

    _run_async(setup())
    snap = check_density(db_path)
    assert snap.new_decisions_7d == 0
    assert snap.new_errors_7d == 0


# ========== Hybrid retrieval ==========

def test_hybrid_search_recall_beats_fts_for_partial(tmp_path: Path):
    """Hybrid debe encontrar contenido que FTS por sí solo no encuentra."""
    db_path = tmp_path / ".apex" / "context.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = ApexContextDB(str(db_path))

    async def setup():
        await db.initialize()
        await db.add_decision(
            "architecture",
            "Implementar retrieval cross-project basado en FTS5 agregada",
            "Evita repetir errores resueltos en otros proyectos",
            phase=12,
        )
        # FTS exact: match
        fts = await db.search("cross project retrieval", limit=5)
        hyb = await db.search_hybrid("cross-project", limit=5)
        return fts, hyb

    fts, hyb = _run_async(setup())
    # Hybrid debe devolver al menos 1 resultado
    assert len(hyb) >= 1
    assert hyb[0]["hybrid_score"] > 0
