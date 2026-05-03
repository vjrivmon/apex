"""Tests del Library Ingest (Sprint 11.3).

Cubre tres ejes:

- **Pure**: validación, frontmatter, slug determinismo, formato del proposal,
  el patch de `_extract_skill_block` con 4 backticks externos.
- **Pipeline**: `ingest()` con `refs_override` (sin red) — dedup, rechazos,
  ya importados, ya propuestos, inválidos.
- **HTTP local**: `http.server` mock que sirve respuestas estilo GitHub
  Search / Trees / raw para `fetch_github_catalog` end-to-end.
- **CLI subprocess**: `_parse_library_skills_dry_run` con stdout sintético.
"""
from __future__ import annotations

import asyncio
import http.server
import json
import socket
import socketserver
import sqlite3
import threading
from pathlib import Path

import pytest

from context_db import ApexContextDB
from library_ingest import (
    GH_API_BASE,
    GH_RAW_BASE,
    IngestResult,
    LibraryProposal,
    SkillRef,
    _parse_library_skills_dry_run,
    context_db_path,
    fetch_blob_content,
    fetch_github_catalog,
    has_library_skills_cli,
    fetch_library_skills_local,
    ingest,
    is_already_imported,
    is_rejected,
    list_skill_files_in_repo,
    mark_imported,
    parse_frontmatter,
    proposals_dir,
    reset_visit_counter,
    search_github_skill_repos,
    validate_skill,
    write_proposal,
)
from skill_forge import _extract_skill_block, approve


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    (tmp_path / ".apex").mkdir()
    db = ApexContextDB(str(context_db_path(tmp_path)))
    _run(db.initialize())
    return tmp_path


@pytest.fixture
def hub_db(tmp_path: Path) -> Path:
    p = tmp_path / "hub.db"
    conn = sqlite3.connect(str(p))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS global_meta (
            key TEXT PRIMARY KEY, value TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
    return p


def _valid_skill_md(name: str = "demo-skill",
                    desc: str = "Test skill that does nothing useful") -> str:
    return (
        f"---\n"
        f"name: {name}\n"
        f"description: {desc}\n"
        f"---\n\n"
        f"# {name}\n\n"
        f"Useful skill for demo purposes. Trigger when X happens.\n\n"
        f"## Steps\n\n"
        f"1. Do A\n2. Do B\n3. Profit.\n\n"
        f"```python\nprint('hello')\n```\n"
    )


def _ref(name: str = "demo-skill",
         source: str = "github",
         sha: str = "abc123",
         raw_md: str | None = None) -> SkillRef:
    return SkillRef(
        name=name,
        description=f"Description of {name}",
        source=source,
        source_url=f"https://example.invalid/{name}",
        sha=sha,
        raw_md=raw_md if raw_md is not None else _valid_skill_md(name),
        kind="library",
    )


# ── parse_frontmatter ─────────────────────────────────────────────────────

def test_parse_frontmatter_basic() -> None:
    fm = parse_frontmatter("---\nname: foo\ndescription: bar\n---\nbody")
    assert fm == {"name": "foo", "description": "bar"}


def test_parse_frontmatter_missing_returns_none() -> None:
    assert parse_frontmatter("# no frontmatter\n\nbody") is None


def test_parse_frontmatter_multiline_continuation() -> None:
    md = (
        "---\n"
        "name: foo\n"
        "description: long description\n"
        "  that wraps\n"
        "---\n\nbody"
    )
    fm = parse_frontmatter(md)
    assert fm is not None
    assert fm["description"].startswith("long description")
    assert "that wraps" in fm["description"]


# ── SkillRef.slug determinismo ────────────────────────────────────────────

def test_slug_deterministic() -> None:
    a = _ref()
    b = _ref()
    assert a.slug() == b.slug()
    assert a.slug().startswith("import-github-demo-skill-")


def test_slug_changes_with_sha() -> None:
    a = _ref(sha="aaaaaa")
    b = _ref(sha="bbbbbb")
    assert a.slug() != b.slug()


# ── validate_skill ────────────────────────────────────────────────────────

def test_validate_skill_happy_path() -> None:
    ok, issues = validate_skill(_ref())
    assert ok is True
    assert issues == []


def test_validate_skill_missing_frontmatter() -> None:
    ref = _ref(raw_md="# no frontmatter\n\nbody " * 30)
    ok, issues = validate_skill(ref)
    assert ok is False
    assert any("frontmatter" in i.lower() for i in issues)


def test_validate_skill_missing_name() -> None:
    md = "---\ndescription: only desc\n---\n\nbody " * 10
    ref = _ref(raw_md=md)
    ok, issues = validate_skill(ref)
    assert ok is False
    assert any("name" in i for i in issues)


def test_validate_skill_description_too_long() -> None:
    long = "x" * 250
    md = (
        f"---\n"
        f"name: foo\n"
        f"description: {long}\n"
        f"---\n\n# foo\n\n" + ("body content " * 30)
    )
    ok, issues = validate_skill(_ref(raw_md=md))
    assert ok is False
    assert any("description" in i for i in issues)


def test_validate_skill_secret_blocks() -> None:
    md = (
        "---\nname: foo\ndescription: bar\n---\n\n# foo\n\n"
        + "Some content " * 20
        + "\n\nMy token: ghp_" + ("A" * 36) + "\n"
    )
    ok, issues = validate_skill(_ref(raw_md=md))
    assert ok is False
    assert any("secreto" in i for i in issues)


def test_validate_skill_body_too_short() -> None:
    md = "---\nname: foo\ndescription: bar\n---\n"
    ok, issues = validate_skill(_ref(raw_md=md))
    assert ok is False
    assert any("corta" in i.lower() or "vac" in i.lower() for i in issues)


def test_validate_skill_kebab_case_warning_non_blocking() -> None:
    md = (
        "---\nname: NotKebabCase\ndescription: bar\n---\n\n"
        "# foo\n\n" + ("body " * 30)
    )
    ok, issues = validate_skill(_ref(raw_md=md))
    assert ok is True
    assert any("kebab" in i.lower() for i in issues)


# ── LibraryProposal.to_markdown + extract_skill_block ────────────────────

def test_proposal_markdown_uses_4_backticks() -> None:
    prop = LibraryProposal(ref=_ref())
    md = prop.to_markdown()
    assert "````markdown" in md
    assert md.count("````markdown") == 1


def test_extract_skill_block_handles_4_backticks_with_inner_code() -> None:
    """Regresión Sprint 11.3: el _extract_skill_block del Sprint 11.2 usa
    3 backticks y se rompe si la SKILL.md descargada contiene un bloque
    ```python ... ``` propio."""
    prop = LibraryProposal(ref=_ref())
    md = prop.to_markdown()
    extracted = _extract_skill_block(md)
    assert extracted is not None
    assert "name: demo-skill" in extracted
    assert "```python" in extracted  # bloque interno preservado


def test_extract_skill_block_3_backticks_compat_legacy() -> None:
    """Proposals del Sprint 11.2 (skill_forge) siguen funcionando."""
    legacy_proposal = (
        "# Skill Forge Proposal — foo\n\n"
        "## Draft de SKILL.md\n\n"
        "```markdown\n---\nname: foo\ndescription: bar\n---\n\nbody\n```\n"
    )
    extracted = _extract_skill_block(legacy_proposal)
    assert extracted is not None
    assert "name: foo" in extracted


# ── write_proposal + persistencia ────────────────────────────────────────

def test_write_proposal_creates_file(project_root: Path) -> None:
    ref = _ref()
    prop = LibraryProposal(ref=ref)
    path = write_proposal(prop, project_root)
    assert path.exists()
    assert path.parent == proposals_dir(project_root)
    assert path.stem == ref.slug()
    assert path.read_text(encoding="utf-8").startswith(
        "# Library Ingest Proposal"
    )


def test_mark_and_check_imported(project_root: Path) -> None:
    ref = _ref(sha="commit-aaa")
    db = context_db_path(project_root)
    assert is_already_imported(db, ref.slug(), ref.sha) is False
    mark_imported(db, ref)
    assert is_already_imported(db, ref.slug(), ref.sha) is True
    assert is_already_imported(db, ref.slug(), "different-sha") is False


def test_is_rejected_uses_skill_forge_table(project_root: Path) -> None:
    db = context_db_path(project_root)
    assert is_rejected(db, "import-github-foo-deadbeef") is False
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO skill_forge_rejections (slug, reason) VALUES (?, ?)",
        ("import-github-foo-deadbeef", "no me gusta"),
    )
    conn.commit()
    conn.close()
    assert is_rejected(db, "import-github-foo-deadbeef") is True


# ── ingest pipeline (refs_override → sin red) ────────────────────────────

def test_ingest_writes_valid_refs(project_root: Path) -> None:
    refs = [_ref("alpha-skill", sha="a1"), _ref("beta-skill", sha="b1")]
    res = ingest(project_root, refs_override=refs)
    assert len(res.written) == 2
    assert res.invalid == []
    files = sorted(proposals_dir(project_root).glob("import-github-*.md"))
    assert len(files) == 2


def test_ingest_filters_invalid(project_root: Path) -> None:
    bad = SkillRef(
        name="bad", description="x", source="github",
        source_url="https://x", sha="zz",
        raw_md="no frontmatter at all\n",
    )
    good = _ref("good-skill", sha="g1")
    res = ingest(project_root, refs_override=[bad, good])
    assert len(res.written) == 1
    assert len(res.invalid) == 1
    assert res.invalid[0][0] == bad.slug()


def test_ingest_idempotent_on_already_proposed(project_root: Path) -> None:
    """El proposal queda en disco + tabla library_imports. La 2ª ingesta no
    re-escribe ni duplica — se reporta como already_imported (mismo SHA)."""
    ref = _ref("dup-skill", sha="d1")
    ingest(project_root, refs_override=[ref])
    res = ingest(project_root, refs_override=[ref])
    assert res.written == []
    assert ref.slug() in (res.already_imported + res.already_proposed)


def test_ingest_already_proposed_when_db_missing_record(
    project_root: Path,
) -> None:
    """Caso edge: archivo existe pero la tabla library_imports no tiene la
    fila (BD borrada manualmente, etc). Se detecta vía proposal_path.exists()."""
    ref = _ref("orphan-skill", sha="o1")
    prop = LibraryProposal(ref=ref)
    write_proposal(prop, project_root)
    res = ingest(project_root, refs_override=[ref])
    assert ref.slug() in res.already_proposed
    assert res.written == []


def test_ingest_skips_rejected(project_root: Path) -> None:
    ref = _ref("rejected-skill", sha="r1")
    db = context_db_path(project_root)
    conn = sqlite3.connect(str(db))
    conn.execute(
        "INSERT INTO skill_forge_rejections (slug, reason) VALUES (?, ?)",
        (ref.slug(), "previous reject"),
    )
    conn.commit()
    conn.close()
    res = ingest(project_root, refs_override=[ref])
    assert ref.slug() in res.rejected
    assert res.written == []


def test_ingest_skips_already_imported_same_sha(project_root: Path) -> None:
    ref = _ref("imported-skill", sha="same-sha")
    db = context_db_path(project_root)
    mark_imported(db, ref)
    # Borramos el archivo del proposal para no caer en "already_proposed"
    # (no se escribió porque mark_imported es manual aquí).
    res = ingest(project_root, refs_override=[ref])
    assert ref.slug() in res.already_imported


def test_ingest_dedup_within_same_call(project_root: Path) -> None:
    ref = _ref("dedup-skill", sha="x1")
    res = ingest(project_root, refs_override=[ref, ref, ref])
    assert len(res.written) == 1


# ── approve via skill_forge — extremo a extremo ──────────────────────────

def test_approve_lib_proposal_preserves_inner_code(
    project_root: Path, tmp_path: Path,
) -> None:
    ref = _ref("approve-test", sha="a1")
    ingest(project_root, refs_override=[ref])
    skills_root = tmp_path / "skills_home"
    target = approve(ref.slug(), project_root, skills_root=skills_root)
    text = target.read_text(encoding="utf-8")
    assert text.startswith("---")
    assert "name: approve-test" in text
    assert "```python" in text  # bloque interno conservado


# ── _parse_library_skills_dry_run ────────────────────────────────────────

def test_parse_library_skills_dry_run_extracts_lines(tmp_path: Path) -> None:
    stdout = (
        "Found 2 libraries with skills:\n"
        "fastapi (router-best-practices) — Best practices for FastAPI routers\n"
        "streamlit (caching) — Streamlit caching patterns and decorators\n"
        "noisy line that should not match\n"
    )
    refs = _parse_library_skills_dry_run(stdout, tmp_path)
    assert len(refs) == 2
    assert refs[0].source == "pkg"
    assert refs[0].name.startswith("pkg-fastapi-")
    assert "library-skills.io" in refs[0].source_url


def test_fetch_library_skills_local_no_marker(tmp_path: Path) -> None:
    """Sin pyproject.toml ni package.json → []."""
    assert fetch_library_skills_local(tmp_path) == []


def test_fetch_library_skills_local_no_cli(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    monkeypatch.setattr(
        "library_ingest.has_library_skills_cli", lambda: False
    )
    assert fetch_library_skills_local(tmp_path) == []


# ── reset_visit_counter ──────────────────────────────────────────────────

def test_reset_visit_counter_writes_global_meta(hub_db: Path) -> None:
    # Llenamos primero
    conn = sqlite3.connect(str(hub_db))
    conn.execute(
        "INSERT INTO global_meta (key, value) VALUES (?, ?)",
        ("library_ingest_visit_set", json.dumps(["a", "b", "c", "d", "e"])),
    )
    conn.commit()
    conn.close()
    reset_visit_counter(hub_db)
    conn = sqlite3.connect(str(hub_db))
    row = conn.execute(
        "SELECT value FROM global_meta WHERE key=?",
        ("library_ingest_visit_set",),
    ).fetchone()
    conn.close()
    assert row is not None
    assert json.loads(row[0]) == []


# ── HTTP local server simulando GitHub API ───────────────────────────────

class _FakeGitHubHandler(http.server.BaseHTTPRequestHandler):
    """Handler de servidor local que simula:

    - GET /search/repositories?q=... → JSON con `items` mínimos.
    - GET /repos/{owner}/{repo}/git/trees/{ref}?recursive=1 → tree con un
      blob `skills/demo/SKILL.md`.
    - GET /raw/{owner}/{repo}/{ref}/{path} → contenido SKILL.md válido.

    Se monta como replacement de `GH_API_BASE` y `GH_RAW_BASE` por monkeypatch.
    """

    def log_message(self, format, *args):  # silenciar acceso log
        return

    def do_GET(self):
        path = self.path
        if path.startswith("/search/repositories"):
            body = {
                "items": [
                    {
                        "full_name": "fakeowner/fakerepo",
                        "stargazers_count": 999,
                        "description": "fake repo for tests",
                        "default_branch": "main",
                        "html_url": "http://example.invalid/fakeowner/fakerepo",
                    },
                ],
            }
            self._send_json(body)
            return
        if "/git/trees/" in path:
            body = {
                "sha": "deadbeefcafe",
                "tree": [
                    {
                        "path": "skills/demo/SKILL.md",
                        "type": "blob",
                        "sha": "blob1234abcd",
                    },
                    {
                        "path": "README.md",
                        "type": "blob",
                        "sha": "noskill",
                    },
                ],
                "truncated": False,
            }
            self._send_json(body)
            return
        if path.startswith("/raw/"):
            content = _valid_skill_md("local-demo",
                                      "Skill from local server tests")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(content.encode())))
            self.end_headers()
            self.wfile.write(content.encode())
            return
        self.send_response(404)
        self.end_headers()

    def _send_json(self, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


@pytest.fixture
def fake_github(monkeypatch: pytest.MonkeyPatch) -> str:
    port = _free_port()
    httpd = socketserver.TCPServer(("127.0.0.1", port), _FakeGitHubHandler)
    httpd.allow_reuse_address = True
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    base_api = f"http://127.0.0.1:{port}"
    base_raw = f"http://127.0.0.1:{port}/raw"
    monkeypatch.setattr("library_ingest.GH_API_BASE", base_api)
    monkeypatch.setattr("library_ingest.GH_RAW_BASE", base_raw)
    yield base_api
    httpd.shutdown()
    httpd.server_close()


def test_search_github_skill_repos_local(fake_github: str) -> None:
    repos = search_github_skill_repos(min_stars=10, limit=5)
    assert len(repos) == 1
    assert repos[0]["full_name"] == "fakeowner/fakerepo"


def test_list_skill_files_local(fake_github: str) -> None:
    files = list_skill_files_in_repo("fakeowner/fakerepo", "main")
    assert len(files) == 1
    assert files[0]["path"] == "skills/demo/SKILL.md"
    assert files[0]["blob_sha"] == "blob1234abcd"


def test_fetch_blob_content_local(fake_github: str) -> None:
    content = fetch_blob_content("fakeowner/fakerepo", "main",
                                  "skills/demo/SKILL.md")
    assert content is not None
    assert "name: local-demo" in content


def test_fetch_github_catalog_end_to_end(fake_github: str,
                                          project_root: Path) -> None:
    refs = list(fetch_github_catalog(min_stars=10, limit_repos=5))
    assert len(refs) == 1
    ref = refs[0]
    assert ref.source == "github"
    assert ref.name == "local-demo"
    assert ref.extra["repo"] == "fakeowner/fakerepo"


def test_ingest_full_pipeline_with_local_server(fake_github: str,
                                                 project_root: Path) -> None:
    res = ingest(project_root, source="github",
                 min_stars=10, limit_repos=5)
    assert len(res.written) == 1
    assert res.repos_searched == 1
    files = sorted(proposals_dir(project_root).glob("*.md"))
    assert len(files) == 1
    text = files[0].read_text(encoding="utf-8")
    assert "Library Ingest Proposal" in text
    assert "````markdown" in text
