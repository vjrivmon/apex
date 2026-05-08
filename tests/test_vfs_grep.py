"""Sprint 17 S17.5 — vfs_grep + flags + FTS5 pre-filter.

Cubre:
- `parse_grep_flags` traduce strings tipo `-i`, `-rn`, `-E`, `-l`.
- `grep(vfs, pattern, virtual_path, flags)` escanea archivos bajo el VFS
  y devuelve `list[GrepHit]` con paths virtuales.
- Flags soportados: `-i` (ignore case), `-r` (recursive — implícito en
  dirs), `-n` (line number), `-l` (files-with-matches), `-E` (extended
  regex).
- Pre-filtro FTS5 opcional contra `context.db.context_fts` (best-effort,
  fallback a scan completo si la query no es traducible).
- Categorías virtuales (errors, skills-history, lessons-*) lanzan
  `VFSNotImplementedError`.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
from vfs import VFSNotImplementedError, VirtualFS  # noqa: E402
from vfs_grep import GrepFlags, GrepHit, grep, parse_grep_flags  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def project_root(tmp_path):
    root = tmp_path / "RoadToDevOps"
    p = root / "apex"
    (p / "wiki" / "decisions").mkdir(parents=True)
    (p / ".apex").mkdir(parents=True)
    (p / "wiki" / "SCHEMA.md").write_text(
        "Línea uno: APEX flow guardian\n"
        "Línea dos: TODO refactor\n"
        "Línea tres: tdd loop is canon\n"
    )
    (p / "wiki" / "decisions" / "2026-arquitectura.md").write_text(
        "# Decisión\nUsar tdd estricto\nFlow guardian dispara grader\n"
    )
    (p / "wiki" / "decisions" / "2026-stack.md").write_text(
        "Stack: python + sqlite\nNada de TDD horizontal\n"
    )
    return root


@pytest.fixture
def vfs(project_root):
    return VirtualFS(allowed_roots=[project_root], vault_root=None)


# =============================================================================
# parse_grep_flags
# =============================================================================


class TestParseGrepFlags:
    def test_no_flags(self):
        f = parse_grep_flags("")
        assert isinstance(f, GrepFlags)
        assert f.ignore_case is False
        assert f.recursive is False
        assert f.line_number is False
        assert f.files_with_matches is False
        assert f.extended_regex is False

    def test_ignore_case(self):
        assert parse_grep_flags("-i").ignore_case is True

    def test_recursive(self):
        assert parse_grep_flags("-r").recursive is True

    def test_line_number(self):
        assert parse_grep_flags("-n").line_number is True

    def test_files_with_matches(self):
        assert parse_grep_flags("-l").files_with_matches is True

    def test_extended_regex(self):
        assert parse_grep_flags("-E").extended_regex is True

    def test_combined_short_form(self):
        f = parse_grep_flags("-rn")
        assert f.recursive is True
        assert f.line_number is True

    def test_combined_separate(self):
        f = parse_grep_flags("-r -n -i")
        assert f.recursive and f.line_number and f.ignore_case

    def test_unknown_flag_raises(self):
        with pytest.raises(ValueError, match="unknown grep flag"):
            parse_grep_flags("-Z")


# =============================================================================
# grep operativo
# =============================================================================


class TestGrep:
    def test_basic_match_in_single_file(self, vfs):
        hits = grep(vfs, "tdd", "/projects/apex/wiki/SCHEMA.md")
        assert len(hits) == 1
        assert hits[0].virtual_path == "/projects/apex/wiki/SCHEMA.md"
        assert "tdd loop" in hits[0].line.lower()

    def test_recursive_on_directory_default(self, vfs):
        """Pasar un directorio implica recursión sin necesidad de -r."""
        hits = grep(vfs, "tdd", "/projects/apex/wiki")
        # SCHEMA.md (1) + 2026-arquitectura.md (1) + 2026-stack.md (1 con TDD case-sensitive? "Nada de TDD" sí matchea "TDD" pero no "tdd")
        # En case-sensitive solo coincide "tdd" exacto.
        # SCHEMA.md "tdd loop" + 2026-arquitectura "tdd estricto" = 2 hits.
        assert len(hits) == 2
        paths = {h.virtual_path for h in hits}
        assert "/projects/apex/wiki/SCHEMA.md" in paths
        assert "/projects/apex/wiki/decisions/2026-arquitectura.md" in paths

    def test_ignore_case_flag(self, vfs):
        """-i hace case-insensitive: tdd matchea TDD también."""
        hits = grep(vfs, "tdd", "/projects/apex/wiki", flags="-i")
        # SCHEMA.md, 2026-arquitectura.md, 2026-stack.md ("Nada de TDD")
        assert len(hits) == 3

    def test_line_number_flag(self, vfs):
        """-n incluye line_num 1-based."""
        hits = grep(vfs, "tdd", "/projects/apex/wiki/SCHEMA.md", flags="-n")
        assert len(hits) == 1
        assert hits[0].line_num == 3

    def test_line_number_default_zero(self, vfs):
        """Sin -n el line_num es 0 (no reportado)."""
        hits = grep(vfs, "tdd", "/projects/apex/wiki/SCHEMA.md")
        assert hits[0].line_num == 0

    def test_files_with_matches_flag(self, vfs):
        """-l devuelve solo paths, una entry por archivo, sin contenido."""
        hits = grep(vfs, "guardian", "/projects/apex/wiki", flags="-l")
        assert len(hits) == 2
        assert all(h.line == "" and h.line_num == 0 for h in hits)
        paths = {h.virtual_path for h in hits}
        assert paths == {
            "/projects/apex/wiki/SCHEMA.md",
            "/projects/apex/wiki/decisions/2026-arquitectura.md",
        }

    def test_extended_regex_flag(self, vfs):
        """-E permite alternancia con `|`."""
        hits = grep(
            vfs, r"refactor|grader", "/projects/apex/wiki", flags="-E"
        )
        # "TODO refactor" en SCHEMA.md + "dispara grader" en 2026-arquitectura.md
        assert len(hits) == 2

    def test_no_match_returns_empty(self, vfs):
        hits = grep(vfs, "xyzzyplatypus", "/projects/apex/wiki")
        assert hits == []

    def test_returns_virtual_paths(self, vfs):
        hits = grep(vfs, "tdd", "/projects/apex/wiki")
        for h in hits:
            assert h.virtual_path.startswith("/projects/apex/wiki/")
            assert "/RoadToDevOps/" not in h.virtual_path

    def test_grep_virtual_category_raises(self, vfs):
        with pytest.raises(VFSNotImplementedError):
            grep(vfs, "x", "/projects/apex/errors/")

    def test_grep_results_sorted_by_path_then_line(self, vfs):
        hits = grep(vfs, "tdd", "/projects/apex/wiki", flags="-in")
        sorted_hits = sorted(
            hits, key=lambda h: (h.virtual_path, h.line_num)
        )
        assert hits == sorted_hits


# =============================================================================
# FTS5 pre-filter (best-effort)
# =============================================================================


class TestFTSPrefilter:
    def test_fts_prefilter_smoke(self, vfs, project_root):
        """Con context.db con FTS5 indexado, el grep produce los mismos
        resultados que sin pre-filter (consistencia).

        Este test confirma que el pre-filter NO rompe resultados; no
        verifica el speedup en sí."""
        db_path = project_root / "apex" / ".apex" / "context.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db = ApexContextDB(str(db_path))
        run(db.initialize())

        async def _seed():
            await db.add_wiki_page(
                slug="entities/concepts/tdd",
                title="TDD",
                content="tdd loop is canon",
            )
        run(_seed())

        hits_with = grep(
            vfs,
            "tdd",
            "/projects/apex/wiki",
            flags="-i",
            use_fts_prefilter=True,
        )
        hits_without = grep(
            vfs,
            "tdd",
            "/projects/apex/wiki",
            flags="-i",
            use_fts_prefilter=False,
        )
        # Mismo conjunto de archivos hit (independientemente del pre-filter).
        assert {h.virtual_path for h in hits_with} == {
            h.virtual_path for h in hits_without
        }

    def test_fts_prefilter_falls_back_when_pattern_untranslatable(self, vfs):
        """Patterns con regex specials (`()`, `|`, `\\`) no se traducen a
        FTS5 MATCH; el grep debe seguir funcionando vía scan completo."""
        hits = grep(
            vfs,
            r"(refactor|grader)",
            "/projects/apex/wiki",
            flags="-E",
            use_fts_prefilter=True,
        )
        # No crashea + devuelve los mismos hits que sin pre-filter
        assert len(hits) >= 2
