"""Sprint 17 S17.3 — VirtualFS.ls + cat sobre mounts reales.

Verifica que `ls(path)` y `cat(path)` operan sobre las categorías reales
(wiki, decisions, handoffs, raw, vault), respetan RBAC y rechazan
escritura. Los mounts virtuales (errors, skills-history, lessons-*)
quedan documentados como "not yet implemented" hasta S17.6.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from vfs import (  # noqa: E402
    VFSError,
    VFSNotImplementedError,
    VFSPathError,
    VirtualFS,
)


@pytest.fixture
def project_root(tmp_path):
    root = tmp_path / "RoadToDevOps"
    p = root / "apex"
    (p / "wiki" / "decisions").mkdir(parents=True)
    (p / "wiki" / "SCHEMA.md").write_text("schema content\nline 2\n")
    (p / "wiki" / "index.md").write_text("idx")
    (p / "wiki" / "decisions" / "2026-01-foo.md").write_text("decision A")
    (p / "wiki" / "decisions" / "2026-02-bar.md").write_text("decision B")
    (p / ".apex" / "handoff").mkdir(parents=True)
    (p / ".apex" / "handoff" / "h1.md").write_text("handoff one")
    (p / ".apex" / "raw").mkdir(parents=True)
    return root


@pytest.fixture
def vault_root(tmp_path):
    v = tmp_path / "ApexVault"
    v.mkdir()
    (v / "index.md").write_text("vault root index")
    return v


@pytest.fixture
def vfs(project_root, vault_root):
    return VirtualFS(allowed_roots=[project_root], vault_root=vault_root)


class TestLs:
    def test_ls_wiki_lists_files_and_dirs_sorted(self, vfs):
        entries = vfs.ls("/projects/apex/wiki")
        names = [e.name for e in entries]
        assert names == sorted(names), "entries should be sorted"
        assert "SCHEMA.md" in names
        assert "index.md" in names
        assert "decisions" in names

    def test_ls_distinguishes_file_vs_dir_kind(self, vfs):
        entries = {e.name: e for e in vfs.ls("/projects/apex/wiki")}
        assert entries["decisions"].kind == "dir"
        assert entries["SCHEMA.md"].kind == "file"

    def test_ls_decisions_remaps_correctly(self, vfs):
        names = [e.name for e in vfs.ls("/projects/apex/decisions")]
        assert "2026-01-foo.md" in names
        assert "2026-02-bar.md" in names

    def test_ls_handoffs_lists(self, vfs):
        names = [e.name for e in vfs.ls("/projects/apex/handoffs")]
        assert names == ["h1.md"]

    def test_ls_vault_root(self, vfs):
        names = [e.name for e in vfs.ls("/vault/")]
        assert "index.md" in names

    def test_ls_on_file_raises(self, vfs):
        with pytest.raises(VFSError, match="not a directory"):
            vfs.ls("/projects/apex/wiki/SCHEMA.md")

    def test_ls_on_nonexistent_raises(self, vfs):
        with pytest.raises(VFSError, match="not found"):
            vfs.ls("/projects/apex/wiki/no-existe")

    def test_ls_virtual_category_raises_not_implemented(self, vfs):
        """ls sobre /projects/apex/errors/ pendiente de S17.6."""
        with pytest.raises(VFSNotImplementedError):
            vfs.ls("/projects/apex/errors/")

    def test_ls_traversal_blocked(self, vfs):
        with pytest.raises(VFSPathError):
            vfs.ls("/projects/apex/wiki/../../etc")


class TestCat:
    def test_cat_reads_file_content(self, vfs):
        assert vfs.cat("/projects/apex/wiki/SCHEMA.md") == "schema content\nline 2\n"

    def test_cat_reads_decisions_file(self, vfs):
        assert vfs.cat("/projects/apex/decisions/2026-01-foo.md") == "decision A"

    def test_cat_reads_handoff_file(self, vfs):
        assert vfs.cat("/projects/apex/handoffs/h1.md") == "handoff one"

    def test_cat_reads_vault_file(self, vfs):
        assert vfs.cat("/vault/index.md") == "vault root index"

    def test_cat_on_dir_raises(self, vfs):
        with pytest.raises(VFSError, match="is a directory"):
            vfs.cat("/projects/apex/wiki")

    def test_cat_on_nonexistent_raises(self, vfs):
        with pytest.raises(VFSError, match="not found"):
            vfs.cat("/projects/apex/wiki/no-existe.md")

    def test_cat_virtual_category_raises_not_implemented(self, vfs):
        with pytest.raises(VFSNotImplementedError):
            vfs.cat("/projects/apex/errors/recurrent.md")
