"""Sprint 17 S17.4 — VirtualFS.find (recursive listing + glob filter)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from vfs import VFSError, VFSNotImplementedError, VirtualFS  # noqa: E402


@pytest.fixture
def project_root(tmp_path):
    root = tmp_path / "RoadToDevOps"
    p = root / "apex"
    (p / "wiki" / "decisions").mkdir(parents=True)
    (p / "wiki" / "entities" / "concepts").mkdir(parents=True)
    (p / "wiki" / "SCHEMA.md").write_text("schema")
    (p / "wiki" / "index.md").write_text("idx")
    (p / "wiki" / "decisions" / "2026-01-foo.md").write_text("a")
    (p / "wiki" / "decisions" / "2026-02-bar.md").write_text("b")
    (p / "wiki" / "entities" / "concepts" / "tdd.md").write_text("c")
    (p / "wiki" / "entities" / "concepts" / "module.md").write_text("d")
    (p / "wiki" / "decisions" / "draft.txt").write_text("not md")
    return root


@pytest.fixture
def vfs(project_root):
    return VirtualFS(allowed_roots=[project_root], vault_root=None)


class TestFind:
    def test_find_recursive_returns_all_files(self, vfs):
        results = vfs.find("/projects/apex/wiki")
        # SCHEMA.md, index.md, 2026-01, 2026-02, draft.txt, tdd.md, module.md = 7
        assert len(results) == 7
        # Todos deben empezar con el prefijo virtual del mount.
        assert all(r.startswith("/projects/apex/wiki/") for r in results)

    def test_find_returns_virtual_paths_not_real(self, vfs):
        results = vfs.find("/projects/apex/wiki")
        for r in results:
            assert "/RoadToDevOps/" not in r
            assert r.startswith("/projects/apex/wiki/")

    def test_find_glob_pattern_md(self, vfs):
        results = vfs.find("/projects/apex/wiki", name="*.md")
        assert len(results) == 6  # excluye draft.txt
        assert all(r.endswith(".md") for r in results)

    def test_find_glob_pattern_specific(self, vfs):
        results = vfs.find("/projects/apex/wiki", name="2026-*")
        assert len(results) == 2
        assert all("2026-" in r for r in results)

    def test_find_within_decisions_subdir(self, vfs):
        """find sobre /projects/apex/decisions/ debe devolver paths bajo decisions/."""
        results = vfs.find("/projects/apex/decisions", name="*.md")
        assert len(results) == 2
        assert all(r.startswith("/projects/apex/decisions/") for r in results)

    def test_find_on_file_returns_match_only_if_pattern_matches(self, vfs):
        results = vfs.find("/projects/apex/wiki/SCHEMA.md", name="*.md")
        assert results == ["/projects/apex/wiki/SCHEMA.md"]

    def test_find_on_file_returns_empty_if_pattern_excludes(self, vfs):
        results = vfs.find("/projects/apex/wiki/SCHEMA.md", name="*.txt")
        assert results == []

    def test_find_on_nonexistent_raises(self, vfs):
        with pytest.raises(VFSError, match="not found"):
            vfs.find("/projects/apex/wiki/no-existe")

    def test_find_virtual_raises_not_implemented(self, vfs):
        with pytest.raises(VFSNotImplementedError):
            vfs.find("/projects/apex/errors/")

    def test_find_results_sorted(self, vfs):
        results = vfs.find("/projects/apex/wiki", name="*.md")
        assert results == sorted(results)
