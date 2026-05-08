"""Sprint 17 S17.2 — VirtualFS path resolver + RBAC whitelist.

Verifica que `VirtualFS._resolve(virtual_path)` mapea rutas virtuales
canónicas (`/projects/<slug>/<category>/...`, `/vault/...`,
`/lessons/...`) a rutas reales del filesystem o a categorías virtuales,
respetando la whitelist de `vfs_allowed_roots` y bloqueando path
traversal.
"""
import json
import os
import sqlite3
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from vfs import ResolvedPath, VFSPathError, VirtualFS  # noqa: E402


@pytest.fixture
def project_root(tmp_path):
    """Crea un árbol de proyectos sintético equivalente a `~/RoadToDevOps/`."""
    root = tmp_path / "RoadToDevOps"
    for slug in ("apex", "tfg-tutor"):
        (root / slug / "wiki" / "decisions").mkdir(parents=True)
        (root / slug / "wiki" / "SCHEMA.md").write_text(f"schema-{slug}")
        (root / slug / "wiki" / "decisions" / "2026-x.md").write_text("decision")
        (root / slug / ".apex" / "handoff").mkdir(parents=True)
        (root / slug / ".apex" / "handoff" / "h1.md").write_text("handoff")
        (root / slug / ".apex" / "raw").mkdir(parents=True)
        (root / slug / ".apex" / "raw" / "note.md").write_text("raw")
    return root


@pytest.fixture
def vault_root(tmp_path):
    v = tmp_path / "ApexVault"
    v.mkdir()
    (v / "index.md").write_text("vault index")
    (v / "projects").mkdir()
    (v / "projects" / "apex-log.md").write_text("apex log")
    return v


@pytest.fixture
def vfs(project_root, vault_root):
    return VirtualFS(allowed_roots=[project_root], vault_root=vault_root)


class TestResolverRealMounts:
    def test_resolve_project_wiki(self, vfs, project_root):
        r = vfs._resolve("/projects/apex/wiki/SCHEMA.md")
        assert isinstance(r, ResolvedPath)
        assert r.kind == "real"
        assert r.category == "wiki"
        assert r.slug == "apex"
        assert r.real_path == project_root / "apex" / "wiki" / "SCHEMA.md"

    def test_resolve_project_decisions_remaps_to_wiki_decisions(self, vfs, project_root):
        r = vfs._resolve("/projects/apex/decisions/2026-x.md")
        assert r.kind == "real"
        assert r.category == "decisions"
        assert r.real_path == project_root / "apex" / "wiki" / "decisions" / "2026-x.md"

    def test_resolve_project_handoffs(self, vfs, project_root):
        r = vfs._resolve("/projects/apex/handoffs/h1.md")
        assert r.kind == "real"
        assert r.category == "handoffs"
        assert r.real_path == project_root / "apex" / ".apex" / "handoff" / "h1.md"

    def test_resolve_project_raw(self, vfs, project_root):
        r = vfs._resolve("/projects/apex/raw/note.md")
        assert r.kind == "real"
        assert r.category == "raw"
        assert r.real_path == project_root / "apex" / ".apex" / "raw" / "note.md"

    def test_resolve_category_root_returns_directory(self, vfs, project_root):
        """`/projects/<slug>/wiki` (sin trailing) resuelve al directorio raíz."""
        r = vfs._resolve("/projects/apex/wiki")
        assert r.kind == "real"
        assert r.real_path == project_root / "apex" / "wiki"
        assert r.is_root is True

    def test_resolve_vault_root(self, vfs, vault_root):
        r = vfs._resolve("/vault/index.md")
        assert r.kind == "real"
        assert r.category == "vault"
        assert r.slug is None
        assert r.real_path == vault_root / "index.md"


class TestResolverVirtualCategories:
    def test_resolve_project_errors_is_virtual(self, vfs):
        r = vfs._resolve("/projects/apex/errors/")
        assert r.kind == "virtual"
        assert r.category == "errors"
        assert r.slug == "apex"
        assert r.real_path is None

    def test_resolve_project_skills_history_is_virtual(self, vfs):
        r = vfs._resolve("/projects/apex/skills-history/")
        assert r.kind == "virtual"
        assert r.category == "skills-history"
        assert r.slug == "apex"

    def test_resolve_lessons_critical_is_virtual(self, vfs):
        r = vfs._resolve("/lessons/critical/")
        assert r.kind == "virtual"
        assert r.category == "lessons-critical"
        assert r.slug is None

    def test_resolve_lessons_by_project_is_virtual(self, vfs):
        r = vfs._resolve("/lessons/by-project/apex.md")
        assert r.kind == "virtual"
        assert r.category == "lessons-by-project"
        assert r.slug == "apex"


class TestResolverRejections:
    def test_traversal_attack_rejected(self, vfs):
        with pytest.raises(VFSPathError, match="traversal"):
            vfs._resolve("/projects/apex/wiki/../../etc/passwd")

    def test_traversal_via_vault_rejected(self, vfs):
        with pytest.raises(VFSPathError, match="traversal"):
            vfs._resolve("/vault/../../../../etc/passwd")

    def test_unknown_top_level_rejected(self, vfs):
        with pytest.raises(VFSPathError, match="unknown mount"):
            vfs._resolve("/etc/passwd")

    def test_unknown_project_slug_rejected(self, vfs):
        """Slug que no corresponde a un dir real bajo ningún allowed_root."""
        with pytest.raises(VFSPathError, match="unknown project"):
            vfs._resolve("/projects/notreal/wiki/x.md")

    def test_unknown_category_within_project_rejected(self, vfs):
        with pytest.raises(VFSPathError, match="unknown category"):
            vfs._resolve("/projects/apex/secrets/foo.md")

    def test_relative_path_rejected(self, vfs):
        with pytest.raises(VFSPathError, match="absolute"):
            vfs._resolve("projects/apex/wiki")

    def test_no_vault_root_rejects_vault_paths(self, project_root):
        vfs_no_vault = VirtualFS(allowed_roots=[project_root], vault_root=None)
        with pytest.raises(VFSPathError, match="vault not configured"):
            vfs_no_vault._resolve("/vault/index.md")


class TestFromHub:
    def test_from_hub_reads_allowed_roots(self, tmp_path, project_root, vault_root):
        """from_hub() lee `vfs_allowed_roots` y `vfs_vault_root` de hub.db."""
        hub_db = tmp_path / "hub.db"
        conn = sqlite3.connect(str(hub_db))
        conn.execute(
            "CREATE TABLE global_meta (key TEXT PRIMARY KEY, value TEXT, "
            "updated_at TEXT DEFAULT (datetime('now')))"
        )
        conn.execute(
            "INSERT INTO global_meta (key, value) VALUES (?, ?)",
            ("vfs_allowed_roots", json.dumps([str(project_root)])),
        )
        conn.execute(
            "INSERT INTO global_meta (key, value) VALUES (?, ?)",
            ("vfs_vault_root", str(vault_root)),
        )
        conn.commit()
        conn.close()

        vfs = VirtualFS.from_hub(hub_db)
        r = vfs._resolve("/projects/apex/wiki/SCHEMA.md")
        assert r.kind == "real"
        r = vfs._resolve("/vault/index.md")
        assert r.kind == "real"

    def test_from_hub_missing_db_uses_defaults(self, tmp_path):
        """Si hub.db no existe, from_hub() usa allowed_roots vacío (sin proyectos)."""
        vfs = VirtualFS.from_hub(tmp_path / "missing.db")
        with pytest.raises(VFSPathError):
            vfs._resolve("/projects/apex/wiki/x.md")
