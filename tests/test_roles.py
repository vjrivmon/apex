"""Tests del subsistema de roles (Sprint 12 — Virtual office).

Cubre:

- Estructura del registry (5 roles, todos con campos obligatorios).
- Render del frontmatter YAML (parseable, name/desc/tools/model).
- install_role / install_all (idempotente, force=True reescribe).
- recommended_for_phase / reason_for_phase / PHASE_ROLE_MAP.
- build_invocation (subagent_type, prompt incluye contexto y placeholders).
- record_invocation / get_invocations / update_invocation_status (CRUD).
- Schema migration: tabla role_invocations existe en BD limpia.
"""
from __future__ import annotations

import asyncio
import sqlite3
import sys
from pathlib import Path

import pytest

# Permite importar desde lib/ sin instalar el paquete
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from context_db import ApexContextDB  # noqa: E402
import roles as r  # noqa: E402


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Crea .apex/context.db inicializada (con role_invocations)."""
    (tmp_path / ".apex").mkdir()
    db = ApexContextDB(str(tmp_path / ".apex" / "context.db"))
    _run(db.initialize())
    return tmp_path


@pytest.fixture
def agents_root(tmp_path: Path) -> Path:
    target = tmp_path / "agents"
    target.mkdir()
    return target


# ── Registry ──────────────────────────────────────────────────────────────

def test_registry_has_six_roles() -> None:
    """Sprint 15 añade apex-advisor (asesor on-demand). Total 6 roles."""
    assert set(r.list_roles()) == {
        "apex-architect", "apex-implementer", "apex-reviewer",
        "apex-qa", "apex-devops", "apex-advisor",
    }


@pytest.mark.parametrize("role_name", [
    "apex-architect", "apex-implementer", "apex-reviewer",
    "apex-qa", "apex-devops",
])
def test_role_spec_required_fields(role_name: str) -> None:
    spec = r.ROLES[role_name]
    assert spec.name == role_name
    assert spec.description and len(spec.description) > 30
    assert spec.tools, "tools whitelist no puede ir vacío"
    assert spec.model in {"haiku", "sonnet", "opus", "inherit"}
    assert spec.system_prompt.startswith("Eres el ")
    assert spec.color in {"blue", "green", "orange", "purple", "red"}


def test_phase_role_map_covers_design_through_deploy() -> None:
    # Las fases mainline deben tener rol
    for phase in (2, 3, 4, 5, 6, 7, 8, 9, 10, 11):
        assert r.PHASE_ROLE_MAP[phase] in r.ROLES
    # Las fases sin rol siguen sin entrada
    for phase in (0, 1, 12):
        assert phase not in r.PHASE_ROLE_MAP


def test_role_phases_are_consistent_with_map() -> None:
    """Cada rol declara phases consistentes con PHASE_ROLE_MAP."""
    for role_name, spec in r.ROLES.items():
        for phase in spec.phases:
            # 13/14 son extensiones del DevOps que no están en el map
            # principal (el map cubre flow obligatorio)
            if phase in r.PHASE_ROLE_MAP:
                assert r.PHASE_ROLE_MAP[phase] == role_name


# ── Frontmatter rendering ────────────────────────────────────────────────

def test_render_agent_md_has_yaml_frontmatter() -> None:
    md = r.render_agent_md(r.ROLES["apex-architect"])
    assert md.startswith("---\n")
    # Frontmatter cerrado
    parts = md.split("---\n", 2)
    assert len(parts) == 3
    head = parts[1]
    for key in ("name:", "description:", "tools:", "model:", "color:"):
        assert key in head, f"Frontmatter sin {key}"
    body = parts[2]
    assert "Eres el **Architect**" in body


def test_render_agent_md_description_is_one_line() -> None:
    md = r.render_agent_md(r.ROLES["apex-implementer"])
    desc_line = next(
        line for line in md.splitlines() if line.startswith("description:")
    )
    # No debe contener \n literal en la línea de description
    assert "\n" not in desc_line[len("description: "):]


def test_render_agent_md_tools_csv() -> None:
    md = r.render_agent_md(r.ROLES["apex-qa"])
    tools_line = next(
        line for line in md.splitlines() if line.startswith("tools:")
    )
    assert "Read" in tools_line
    assert "mcp__playwright__*" in tools_line
    assert "mcp__apex__*" in tools_line


# ── install_role / install_all ───────────────────────────────────────────

def test_install_role_writes_file(agents_root: Path) -> None:
    path, status = r.install_role("apex-architect", agents_root=agents_root)
    assert path.exists()
    assert status == "written"
    assert "apex-architect" in path.read_text()


def test_install_role_skips_existing(agents_root: Path) -> None:
    r.install_role("apex-architect", agents_root=agents_root)
    path, status = r.install_role("apex-architect", agents_root=agents_root)
    assert status == "skipped"
    assert path.exists()


def test_install_role_force_overwrites(agents_root: Path) -> None:
    path, _ = r.install_role("apex-architect", agents_root=agents_root)
    path.write_text("STALE")
    path2, status = r.install_role(
        "apex-architect", agents_root=agents_root, force=True)
    assert path2 == path
    # Contenido nuevo, no stale
    content = path.read_text()
    assert "STALE" not in content
    assert "apex-architect" in content


def test_install_all_creates_six_files(agents_root: Path) -> None:
    """Sprint 15: install_all instala 6 (5 de S12 + apex-advisor)."""
    results = r.install_all(agents_root=agents_root)
    assert len(results) == 6
    files = list(agents_root.glob("*.md"))
    assert len(files) == 6
    for role_name in r.ROLES:
        assert (agents_root / f"{role_name}.md").exists()


def test_install_all_idempotent(agents_root: Path) -> None:
    r.install_all(agents_root=agents_root)
    second = r.install_all(agents_root=agents_root)
    statuses = {name: status for name, (_p, status) in second.items()}
    assert all(s == "skipped" for s in statuses.values())


def test_install_role_unknown_raises(agents_root: Path) -> None:
    with pytest.raises(KeyError):
        r.install_role("apex-fantasma", agents_root=agents_root)


def test_is_installed_reflects_state(agents_root: Path) -> None:
    assert not r.is_installed("apex-qa", agents_root=agents_root)
    r.install_role("apex-qa", agents_root=agents_root)
    assert r.is_installed("apex-qa", agents_root=agents_root)


# ── Recommendation ───────────────────────────────────────────────────────

@pytest.mark.parametrize("phase,expected", [
    (2, "apex-architect"),
    (3, "apex-architect"),
    (4, "apex-qa"),
    (5, "apex-implementer"),
    (7, "apex-implementer"),
    (8, "apex-reviewer"),
    (9, "apex-qa"),
    (10, "apex-reviewer"),
    (11, "apex-devops"),
])
def test_recommended_for_phase(phase: int, expected: str) -> None:
    assert r.recommended_for_phase(phase) == expected


@pytest.mark.parametrize("phase", [0, 1, 12, 13, 14, 99])
def test_recommended_for_phase_none(phase: int) -> None:
    assert r.recommended_for_phase(phase) is None


def test_reason_for_phase_with_role() -> None:
    text = r.reason_for_phase(5)
    assert "apex-implementer" in text
    assert "scaffold" in text


def test_reason_for_phase_without_role() -> None:
    text = r.reason_for_phase(0)
    assert "no tiene rol asociado" in text


# ── build_invocation ─────────────────────────────────────────────────────

def test_build_invocation_returns_required_keys() -> None:
    inv = r.build_invocation(
        "apex-architect", phase=2,
        context_summary="repo nuevo, sin .apex aún",
        project_name="demo",
    )
    for key in ("role", "subagent_type", "description", "prompt"):
        assert key in inv
    assert inv["subagent_type"] == "apex-architect"
    assert "fase 2" in inv["description"]


def test_build_invocation_includes_context_in_prompt() -> None:
    inv = r.build_invocation(
        "apex-implementer", phase=5,
        context_summary="DESIGN.md ya creado, falta scaffold backend",
    )
    p = inv["prompt"]
    assert "Fase**: 5" in p
    assert "DESIGN.md ya creado" in p
    assert "apex_get_context" in p


def test_build_invocation_without_phase() -> None:
    inv = r.build_invocation("apex-reviewer", context_summary="audit ad-hoc")
    assert "ad-hoc" in inv["description"]
    assert "Fase**: " not in inv["prompt"]


def test_build_invocation_extra_instructions() -> None:
    inv = r.build_invocation(
        "apex-qa", phase=9,
        extra_instructions="Foco en flaky tests del módulo X",
    )
    assert "flaky tests" in inv["prompt"]


def test_build_invocation_unknown_role_raises() -> None:
    with pytest.raises(KeyError):
        r.build_invocation("apex-fantasma", phase=2)


# ── Telemetría ───────────────────────────────────────────────────────────

def test_record_invocation_inserts_row(project_root: Path) -> None:
    db_path = project_root / ".apex" / "context.db"
    inv_id = r.record_invocation(
        db_path,
        role="apex-architect",
        phase=2,
        session_id="sess-001",
        context_summary="probando",
    )
    assert inv_id > 0


def test_get_invocations_filters(project_root: Path) -> None:
    db_path = project_root / ".apex" / "context.db"
    r.record_invocation(db_path, role="apex-architect", phase=2)
    r.record_invocation(db_path, role="apex-implementer", phase=5)
    r.record_invocation(db_path, role="apex-implementer", phase=6)

    all_rows = r.get_invocations(db_path, limit=10)
    assert len(all_rows) == 3

    impl = r.get_invocations(db_path, role="apex-implementer", limit=10)
    assert len(impl) == 2
    assert all(row["role"] == "apex-implementer" for row in impl)

    phase5 = r.get_invocations(db_path, phase=5, limit=10)
    assert len(phase5) == 1


def test_update_invocation_status(project_root: Path) -> None:
    db_path = project_root / ".apex" / "context.db"
    inv_id = r.record_invocation(db_path, role="apex-qa", phase=4)
    r.update_invocation_status(
        db_path, invocation_id=inv_id, status="completed")
    rows = r.get_invocations(db_path, role="apex-qa", limit=1)
    assert rows[0]["status"] == "completed"


def test_role_invocations_table_in_clean_db(project_root: Path) -> None:
    db_path = project_root / ".apex" / "context.db"
    conn = sqlite3.connect(str(db_path))
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='role_invocations'")
    row = cur.fetchone()
    conn.close()
    assert row is not None, "Migración: role_invocations no existe"


# ── Helpers ──────────────────────────────────────────────────────────────

def test_role_summary_returns_dict() -> None:
    summary = r.role_summary("apex-devops")
    assert summary["name"] == "apex-devops"
    assert "Bash" in summary["tools"]
    assert 11 in summary["phases"]
