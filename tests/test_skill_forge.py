"""Tests del Skill Forge (Sprint 11.2).

Cada detector se prueba con una BD seedada in-memory (físicamente en tmp_path
para que `sqlite3.connect(file:...)` URI funcione). El hub.db de D3 se monta
con un schema mínimo de hub_search FTS5.
"""
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

import pytest

from context_db import ApexContextDB
from skill_forge import (
    D1_MIN_PHASES,
    D2_MIN_FREQ,
    D2_WINDOW,
    Pattern,
    Proposal,
    approve,
    context_db_path,
    is_rejected,
    list_proposals,
    log_tool_call,
    propose,
    proposals_dir,
    reject,
    scan_all,
    scan_and_write,
    scan_cross_project_repeats,
    scan_grader_blocks,
    scan_tool_call_patterns,
    write_proposal,
)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── Fixtures ──────────────────────────────────────────────────────────────

@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Crea un proyecto vacío con .apex/context.db inicializada."""
    (tmp_path / ".apex").mkdir()
    db = ApexContextDB(str(context_db_path(tmp_path)))
    _run(db.initialize())
    return tmp_path


@pytest.fixture
def hub_db(tmp_path: Path) -> Path:
    """Crea un hub.db mínimo con FTS5 hub_search."""
    p = tmp_path / "hub.db"
    conn = sqlite3.connect(str(p))
    conn.executescript("""
        CREATE VIRTUAL TABLE hub_search USING fts5(
            project_id, source_type, source_id, content
        );
    """)
    conn.commit()
    conn.close()
    return p


# ── Pattern.slug ──────────────────────────────────────────────────────────

def test_pattern_slug_deterministic() -> None:
    p1 = Pattern(detector="grader_block", signature="grader_block:mock_data")
    p2 = Pattern(detector="grader_block", signature="grader_block:mock_data")
    assert p1.slug() == p2.slug()
    assert p1.slug().startswith("grader-block-grader-block-mock-data-")


def test_pattern_slug_differs_per_signature() -> None:
    a = Pattern(detector="tool_call", signature="tool_call:Read→Edit→Bash")
    b = Pattern(detector="tool_call", signature="tool_call:Bash→Read→Edit")
    assert a.slug() != b.slug()


# ── D1: scan_grader_blocks ────────────────────────────────────────────────

def _seed_verdict(root: Path, phase: int, issues: list[str],
                  should_block: bool = True) -> None:
    db = ApexContextDB(str(context_db_path(root)))
    _run(db.add_verdict(
        phase=phase, quality=1, reasoning="seed",
        issues=issues, should_block=should_block,
    ))


def test_d1_no_verdicts(project_root: Path) -> None:
    assert scan_grader_blocks(context_db_path(project_root)) == []


def test_d1_below_threshold(project_root: Path) -> None:
    _seed_verdict(project_root, 1, ["mock_data"])
    _seed_verdict(project_root, 2, ["mock_data"])
    # Solo 2 fases distintas, threshold = 3
    patterns = scan_grader_blocks(context_db_path(project_root))
    assert patterns == []


def test_d1_threshold_met(project_root: Path) -> None:
    for phase in (1, 2, 3):
        _seed_verdict(project_root, phase, ["mock_data"])
    patterns = scan_grader_blocks(context_db_path(project_root))
    assert len(patterns) == 1
    p = patterns[0]
    assert p.detector == "grader_block"
    assert p.evidence["issue"] == "mock_data"
    assert p.evidence["phases"] == [1, 2, 3]
    assert p.evidence["occurrences"] == 3


def test_d1_ignores_non_blocking(project_root: Path) -> None:
    for phase in (1, 2, 3):
        _seed_verdict(project_root, phase, ["mock_data"], should_block=False)
    assert scan_grader_blocks(context_db_path(project_root)) == []


def test_d1_multiple_issues(project_root: Path) -> None:
    for phase in (1, 2, 3):
        _seed_verdict(project_root, phase, ["mock_data", "no_git_init"])
    patterns = scan_grader_blocks(context_db_path(project_root))
    assert {p.evidence["issue"] for p in patterns} == {"mock_data", "no_git_init"}


# ── D2: scan_tool_call_patterns ───────────────────────────────────────────

def _seed_tool_calls(root: Path, tools: list[str]) -> None:
    db_path = context_db_path(root)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executemany(
            "INSERT INTO tool_call_log (tool, args_summary) VALUES (?, '')",
            [(t,) for t in tools],
        )
        conn.commit()
    finally:
        conn.close()


def test_d2_empty_log(project_root: Path) -> None:
    assert scan_tool_call_patterns(context_db_path(project_root)) == []


def test_d2_below_threshold(project_root: Path) -> None:
    # Triplete repetido 3 veces (threshold = 5)
    seq = ["Bash", "Read", "Edit"]
    _seed_tool_calls(project_root, seq * 3)
    assert scan_tool_call_patterns(context_db_path(project_root)) == []


def test_d2_threshold_met(project_root: Path) -> None:
    seq = ["Bash", "Read", "Edit"]
    # Repetir el triplete contiguo 6 veces produce >=5 tripletes contiguos
    # exactos. Intercalamos un separador para que los demás tripletes formados
    # por superposición no contaminen el conteo.
    tools: list[str] = []
    for _ in range(6):
        tools.extend(seq)
        tools.append("SEP")
    _seed_tool_calls(project_root, tools)
    patterns = scan_tool_call_patterns(context_db_path(project_root))
    matched = [p for p in patterns
               if p.evidence["sequence"] == seq]
    assert len(matched) == 1
    assert matched[0].evidence["occurrences"] >= D2_MIN_FREQ


def test_d2_filters_self_repeating(project_root: Path) -> None:
    # 30 Reads en fila no debería generar un pattern (Read,Read,Read)
    _seed_tool_calls(project_root, ["Read"] * 30)
    patterns = scan_tool_call_patterns(context_db_path(project_root))
    assert all(p.evidence["sequence"] != ["Read", "Read", "Read"]
               for p in patterns)


# ── D3: scan_cross_project_repeats ────────────────────────────────────────

def _seed_decision(root: Path, category: str, decision: str) -> None:
    db = ApexContextDB(str(context_db_path(root)))
    _run(db.add_decision(category=category, decision=decision,
                          reasoning="seed"))


def _seed_hub(hub: Path, projects_with_decision: list[tuple[str, str]]) -> None:
    conn = sqlite3.connect(str(hub))
    try:
        conn.executemany(
            "INSERT INTO hub_search (project_id, source_type, source_id, content) "
            "VALUES (?, 'decision', '0', ?)",
            projects_with_decision,
        )
        conn.commit()
    finally:
        conn.close()


def test_d3_no_decisions(project_root: Path, hub_db: Path) -> None:
    assert scan_cross_project_repeats(context_db_path(project_root), hub_db) == []


def test_d3_no_hub(project_root: Path, tmp_path: Path) -> None:
    _seed_decision(project_root, "stack", "Use FastAPI for backend")
    nonexistent = tmp_path / "no_hub.db"
    assert scan_cross_project_repeats(context_db_path(project_root),
                                       nonexistent) == []


def test_d3_threshold_met(project_root: Path, hub_db: Path) -> None:
    _seed_decision(project_root, "stack", "Use FastAPI for backend")
    _seed_hub(hub_db, [
        ("proj_a", "Use FastAPI backend uvicorn"),
        ("proj_b", "Decision FastAPI backend chosen"),
    ])
    patterns = scan_cross_project_repeats(context_db_path(project_root), hub_db)
    assert len(patterns) == 1
    p = patterns[0]
    assert p.detector == "cross_project"
    assert "proj_a" in p.evidence["shared_with_projects"]
    assert "proj_b" in p.evidence["shared_with_projects"]


def test_d3_excludes_own_project(project_root: Path, hub_db: Path) -> None:
    _seed_decision(project_root, "stack", "Use FastAPI for backend")
    _seed_hub(hub_db, [
        ("proj_self", "Use FastAPI backend uvicorn"),
        ("proj_b", "Decision FastAPI backend chosen"),
    ])
    patterns = scan_cross_project_repeats(
        context_db_path(project_root), hub_db, project_id="proj_self")
    # Sólo proj_b queda → < D3_MIN_PROJECTS (2)
    assert patterns == []


# ── propose / write_proposal / list_proposals ───────────────────────────

def test_propose_grader_block_yields_skill_md() -> None:
    pat = Pattern(
        detector="grader_block",
        signature="grader_block:mock_data",
        evidence={"issue": "mock_data", "phases": [1, 2, 3], "occurrences": 3},
        confidence=0.6,
    )
    prop = propose(pat)
    assert isinstance(prop, Proposal)
    assert "avoid-mock-data" in prop.skill_md
    assert "Mitigar issue recurrente" in prop.title


def test_propose_unknown_detector_raises() -> None:
    with pytest.raises(ValueError):
        propose(Pattern(detector="unknown", signature="x"))


def test_write_proposal_creates_file(project_root: Path) -> None:
    pat = Pattern(
        detector="tool_call",
        signature="tool_call:A→B→C",
        evidence={"sequence": ["A", "B", "C"], "occurrences": 5},
    )
    path = write_proposal(propose(pat), project_root)
    assert path.exists()
    assert path.parent == proposals_dir(project_root)
    content = path.read_text(encoding="utf-8")
    assert "macro-a-b-c" in content
    assert "Aprobar" in content


def test_list_proposals_after_write(project_root: Path) -> None:
    pat = Pattern(detector="grader_block",
                   signature="grader_block:mock_data",
                   evidence={"issue": "mock_data", "phases": [1, 2, 3]})
    write_proposal(propose(pat), project_root)
    items = list_proposals(project_root)
    assert len(items) == 1
    assert items[0]["slug"].startswith("grader-block-")


# ── approve / reject ─────────────────────────────────────────────────────

def test_approve_moves_to_skills_root(project_root: Path, tmp_path: Path) -> None:
    pat = Pattern(detector="grader_block",
                   signature="grader_block:emoji_in_frontend",
                   evidence={"issue": "emoji_in_frontend", "phases": [2, 5, 8]})
    prop = propose(pat)
    write_proposal(prop, project_root)
    skills_root = tmp_path / "skills_target"
    target = approve(prop.slug, project_root, skills_root=skills_root)
    assert target.exists()
    assert target.parent == skills_root / prop.slug
    # Source ya no existe
    assert not (proposals_dir(project_root) / f"{prop.slug}.md").exists()
    # El SKILL.md tiene frontmatter limpio (sólo el bloque draft, no toda la propuesta)
    body = target.read_text(encoding="utf-8")
    assert body.startswith("---\n")
    assert "## Aprobar" not in body


def test_approve_missing_proposal_raises(project_root: Path) -> None:
    with pytest.raises(FileNotFoundError):
        approve("no-existe-slug", project_root)


def test_reject_records_and_blocks_reproposal(project_root: Path) -> None:
    pat = Pattern(detector="grader_block",
                   signature="grader_block:no_git_init",
                   evidence={"issue": "no_git_init", "phases": [5, 8, 11]})
    prop = propose(pat)
    write_proposal(prop, project_root)
    reject(prop.slug, "ya tengo skill manual", project_root)
    assert is_rejected(context_db_path(project_root), prop.slug)
    # Propuesta borrada
    assert not (proposals_dir(project_root) / f"{prop.slug}.md").exists()


# ── scan_and_write integration ───────────────────────────────────────────

def test_scan_and_write_skips_rejected(project_root: Path) -> None:
    for phase in (1, 2, 3):
        _seed_verdict(project_root, phase, ["mock_data"])
    written_first = scan_and_write(project_root)
    assert len(written_first) == 1
    slug = written_first[0].stem
    # Rechazar y volver a escanear → no debe re-proponer
    reject(slug, "no aplica", project_root)
    written_second = scan_and_write(project_root)
    assert written_second == []


def test_scan_and_write_idempotent(project_root: Path) -> None:
    for phase in (1, 2, 3):
        _seed_verdict(project_root, phase, ["mock_data"])
    first = scan_and_write(project_root)
    second = scan_and_write(project_root)
    assert len(first) == 1
    # Segunda pasada no debe crear duplicados
    assert second == []


# ── log_tool_call ────────────────────────────────────────────────────────

def test_log_tool_call_writes_row(project_root: Path) -> None:
    log_tool_call(project_root, "Bash", "git status")
    log_tool_call(project_root, "Read", "")
    db = sqlite3.connect(str(context_db_path(project_root)))
    try:
        rows = db.execute(
            "SELECT tool, args_summary FROM tool_call_log ORDER BY id"
        ).fetchall()
    finally:
        db.close()
    assert rows == [("Bash", "git status"), ("Read", "")]


def test_log_tool_call_no_db_does_not_raise(tmp_path: Path) -> None:
    # No existe .apex/context.db → función debe ser silenciosa
    log_tool_call(tmp_path, "Bash", "x")  # no lanza


# ── scan_all integra los tres detectores ─────────────────────────────────

def test_scan_all_combines(project_root: Path, hub_db: Path) -> None:
    # D1
    for phase in (1, 2, 3):
        _seed_verdict(project_root, phase, ["mock_data"])
    # D2
    seq = ["Bash", "Read", "Edit"]
    tools: list[str] = []
    for _ in range(6):
        tools.extend(seq)
        tools.append("SEP")
    _seed_tool_calls(project_root, tools)
    # D3
    _seed_decision(project_root, "stack", "Use FastAPI for backend")
    _seed_hub(hub_db, [
        ("proj_a", "Use FastAPI backend uvicorn"),
        ("proj_b", "Decision FastAPI backend chosen"),
    ])

    patterns = scan_all(project_root, hub_db_path=hub_db)
    detectors = {p.detector for p in patterns}
    assert detectors == {"grader_block", "tool_call", "cross_project"}
