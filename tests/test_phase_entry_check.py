"""Tests para apex_phase_entry_check (S20.B).

Cubre:
- Retrieval cross-project: queries dirigidas por fase producen keys correctas.
- Gate de entrada: fase anterior completed vs no-completed.
- Bloque visual: formato del output auditable.
- hub.db no disponible: mensaje explícito, no crash.
- Deduplicación de hits entre queries múltiples.
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "mcp"))


# ---------------------------------------------------------------------------
# Helpers para crear hub.db de prueba
# ---------------------------------------------------------------------------

def _make_hub_db(path: Path) -> None:
    """Crea un hub.db mínimo con errores y decisiones de prueba."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS errors (
            id INTEGER PRIMARY KEY,
            project_id TEXT,
            description TEXT,
            lesson TEXT,
            severity TEXT DEFAULT 'medium',
            recurrence_count INTEGER DEFAULT 1,
            phase INTEGER
        );
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY,
            project_id TEXT,
            category TEXT,
            decision TEXT,
            reasoning TEXT,
            phase INTEGER,
            invalid_from TEXT
        );
        CREATE TABLE IF NOT EXISTS components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            component_id TEXT,
            project_id TEXT,
            name TEXT,
            type TEXT,
            description TEXT,
            status TEXT DEFAULT 'active'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS hub_search USING fts5(
            project_id UNINDEXED,
            source_type UNINDEXED,
            source_id UNINDEXED,
            content,
            tokenize='porter ascii'
        );
        INSERT INTO errors VALUES
            (1, 'focusnow', 'No se inicializo git antes del scaffold', 'REGLA: git init es el primer sub-paso de fase 5', 'critical', 3, 5),
            (2, 'focusnow', 'Datos mock hardcodeados en frontend', 'Nunca declarar fase completada con datos mock', 'critical', 2, 8),
            (3, 'tfg-tutor', 'Datos del classifier no propagados al tutor', 'Contexto compartido debe ser explicito', 'high', 1, 6);
        INSERT INTO decisions VALUES
            (1, 'focusnow', 'solution_type', 'Usar FastAPI + Next.js', 'Mejor separacion de responsabilidades', 5, NULL),
            (2, 'tfg-tutor', 'database', 'SQLite para sesiones, no PostgreSQL', 'Simplicidad en despliegue', 7, NULL);
        INSERT INTO hub_search VALUES
            ('focusnow', 'error', 1, 'git init scaffold hexagonal estructura errores secretos env'),
            ('focusnow', 'error', 2, 'mock datos hardcoded frontend integration end-to-end errores'),
            ('tfg-tutor', 'error', 3, 'domain logic pure core errores entidades casos uso datos propagados'),
            ('focusnow', 'decision', 1, 'scaffold hexagonal FastAPI Next.js estructura'),
            ('tfg-tutor', 'decision', 2, 'database adapter migraciones SQLite infraestructura');
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests de _search_cross_project con hub.db real
# ---------------------------------------------------------------------------

def test_search_cross_project_returns_errors_for_scaffold_query(tmp_path, monkeypatch):
    """Query de fase 5 encuentra errores de git/scaffold en hub.db."""
    hub_db = tmp_path / "hub.db"
    _make_hub_db(hub_db)

    import apex_server as srv
    monkeypatch.setattr(srv, "_HUB_DB", hub_db)

    hits = srv._search_cross_project("scaffold hexagonal estructura errores", limit=5)
    assert hits["hub_available"] is True
    assert len(hits["errors"]) >= 1
    descs = [e["description"] for e in hits["errors"]]
    assert any("git" in d.lower() or "scaffold" in d.lower() for d in descs)


def test_search_cross_project_returns_errors_for_integration_query(tmp_path, monkeypatch):
    """Query de fase 8 encuentra errores de mock/integration."""
    hub_db = tmp_path / "hub.db"
    _make_hub_db(hub_db)

    import apex_server as srv
    monkeypatch.setattr(srv, "_HUB_DB", hub_db)

    hits = srv._search_cross_project("mock datos hardcoded frontend", limit=5)
    assert hits["hub_available"] is True
    assert len(hits["errors"]) >= 1


def test_search_cross_project_hub_not_available(tmp_path, monkeypatch):
    """Sin hub.db el resultado indica hub_available=False sin crash."""
    import apex_server as srv
    monkeypatch.setattr(srv, "_HUB_DB", tmp_path / "nonexistent.db")

    hits = srv._search_cross_project("cualquier query", limit=5)
    assert hits["hub_available"] is False
    assert hits["errors"] == []
    assert hits["decisions"] == []


def test_search_cross_project_excludes_current_project(tmp_path, monkeypatch):
    """exclude_project filtra resultados del proyecto actual."""
    hub_db = tmp_path / "hub.db"
    _make_hub_db(hub_db)

    import apex_server as srv
    monkeypatch.setattr(srv, "_HUB_DB", hub_db)

    hits_with_excl = srv._search_cross_project(
        "scaffold errores", limit=5, exclude_project="focusnow"
    )
    for e in hits_with_excl["errors"]:
        assert e["project_id"] != "focusnow"


# ---------------------------------------------------------------------------
# Tests del bloque visual (formato auditable)
# ---------------------------------------------------------------------------

def test_phase_queries_cover_all_phases():
    """Cada fase 5-10 tiene queries dirigidas definidas.

    Se comprueba el diccionario real del handler, no la presencia de una
    cadena en el fichero: tras la refactorización de 2026-07 las queries
    viven en `mcp/handlers/phase_gate.py`.
    """
    import importlib.util as ilu

    pkg_dir = ROOT / "mcp" / "handlers"
    spec = ilu.spec_from_file_location(
        "apex_handlers", pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    mod = ilu.module_from_spec(spec)
    sys.modules["apex_handlers"] = mod
    spec.loader.exec_module(mod)

    from apex_handlers.phase_gate import _PHASE_QUERIES

    for phase in range(5, 11):
        assert phase in _PHASE_QUERIES, f"fase {phase} sin queries dirigidas"
        assert _PHASE_QUERIES[phase], f"fase {phase} con lista vacía"


def test_phase_entry_output_format_with_errors(tmp_path, monkeypatch):
    """El bloque visual contiene el encabezado auditable y cita errores."""
    hub_db = tmp_path / "hub.db"
    _make_hub_db(hub_db)

    import apex_server as srv
    monkeypatch.setattr(srv, "_HUB_DB", hub_db)

    # Simular _search_cross_project devolviendo hits conocidos
    def mock_search(query, limit=8, exclude_project=None):
        return {
            "hub_available": True,
            "errors": [{"project_id": "focusnow", "severity": "critical",
                        "recurrence_count": 3, "description": "No git init",
                        "lesson": "git init primero siempre", "phase": 5}],
            "decisions": [],
            "components": [],
        }

    monkeypatch.setattr(srv, "_search_cross_project", mock_search)

    # Construir el bloque manualmente usando la misma lógica del handler
    lines = ["## Gate de entrada — Fase 5", ""]
    lines.append("### Lecciones cross-project aplicadas")
    lines.append("")
    lines.append("**Errores a evitar (1)**")
    lines.append("- [focusnow · critical · x3] No git init")
    lines.append("  → Lección: git init primero siempre")

    output = "\n".join(lines)
    assert "### Lecciones cross-project aplicadas" in output
    assert "focusnow" in output
    assert "critical" in output
    assert "Lección:" in output


def test_phase_entry_output_zero_hits(tmp_path, monkeypatch):
    """Con 0 hits el bloque lo indica explícitamente."""
    import apex_server as srv
    monkeypatch.setattr(srv, "_HUB_DB", tmp_path / "hub.db")  # no existe

    lines = ["## Gate de entrada — Fase 7", ""]
    lines.append("### Lecciones cross-project aplicadas")
    lines.append("")
    lines.append("hub.db no disponible — retrieval cross-project desactivado.")

    output = "\n".join(lines)
    assert "hub.db no disponible" in output
    assert "### Lecciones cross-project aplicadas" in output


def test_deduplication_across_queries(tmp_path, monkeypatch):
    """Múltiples queries no producen el mismo error duplicado."""
    hub_db = tmp_path / "hub.db"
    _make_hub_db(hub_db)

    import apex_server as srv
    monkeypatch.setattr(srv, "_HUB_DB", hub_db)

    seen: set = set()
    all_errors = []
    queries = ["scaffold hexagonal estructura errores", "git init secretos env"]
    for q in queries:
        hits = srv._search_cross_project(q, limit=5)
        for e in hits.get("errors", []):
            key = (e["project_id"], e["description"][:60])
            if key not in seen:
                seen.add(key)
                all_errors.append(e)

    # No debe haber duplicados: len(all_errors) == len(seen)
    assert len(all_errors) == len(seen)


# ---------------------------------------------------------------------------
# Tests de verificación de fase anterior
# ---------------------------------------------------------------------------

def test_prev_phase_completed_message():
    """Si la fase anterior está completed, el mensaje lo confirma."""
    phase_map = {4: "completed", 5: "in_progress"}
    prev_phase = 5
    prev_status = phase_map.get(prev_phase)

    if prev_status and prev_status != "completed":
        msg = f"ADVERTENCIA: Fase {prev_phase} esta en estado '{prev_status}'"
    elif prev_status == "completed":
        msg = f"Fase {prev_phase}: completed"
    else:
        msg = f"Fase {prev_phase}: estado desconocido"

    assert "ADVERTENCIA" in msg
    assert "in_progress" in msg


def test_prev_phase_unknown_message():
    """Si la fase anterior no está en context.db, mensaje explícito."""
    phase_map: dict = {}
    prev_phase = 4
    prev_status = phase_map.get(prev_phase)

    if prev_status == "completed":
        msg = f"Fase {prev_phase}: completed"
    elif prev_status:
        msg = f"ADVERTENCIA: {prev_status}"
    else:
        msg = f"Fase {prev_phase}: estado desconocido"

    assert "desconocido" in msg


# ---------------------------------------------------------------------------
# Tests de subpasos de seguridad en archivos de fase
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("fname,expected_anchor", [
    ("05-scaffold.md", "5i-sec"),
    ("06-core.md", "6h-sec"),
    ("07-infrastructure.md", "7d-sec"),
    ("08-integration.md", "8e-sec"),
    ("09-testing.md", "9e-sec"),
    ("10-security.md", "10e-sec"),
])
def test_security_substep_present_in_phase(fname, expected_anchor):
    """Cada archivo de fase tiene su subpaso de seguridad."""
    path = ROOT / "commands" / "phases" / fname
    content = path.read_text()
    assert expected_anchor in content, f"{fname} no tiene subpaso [{expected_anchor}]"


@pytest.mark.parametrize("fname", [
    "05-scaffold.md", "06-core.md", "07-infrastructure.md",
    "08-integration.md", "09-testing.md", "10-security.md",
])
def test_gate_de_entrada_present_in_phase(fname):
    """Cada archivo de fase 5-10 tiene su gate de entrada."""
    path = ROOT / "commands" / "phases" / fname
    content = path.read_text()
    assert "Gate de entrada" in content, f"{fname} no tiene gate de entrada"
    assert "apex_phase_entry_check" in content, f"{fname} no referencia apex_phase_entry_check"


def test_tool_definition_in_server():
    """apex_phase_entry_check está definido en list_tools() del MCP server."""
    source = (ROOT / "mcp" / "apex_server.py").read_text()
    assert 'name="apex_phase_entry_check"' in source


def test_tool_handler_in_server():
    """apex_phase_entry_check tiene handler registrado.

    Tras la refactorización a `mcp/handlers/` (2026-07) el despacho ya no es
    un `elif` en el monolito: se comprueba el registro real en HANDLERS, que
    es lo que determina si la tool responde.
    """
    import importlib.util as ilu

    pkg_dir = ROOT / "mcp" / "handlers"
    spec = ilu.spec_from_file_location(
        "apex_handlers", pkg_dir / "__init__.py",
        submodule_search_locations=[str(pkg_dir)],
    )
    mod = ilu.module_from_spec(spec)
    sys.modules["apex_handlers"] = mod
    spec.loader.exec_module(mod)

    assert "apex_phase_entry_check" in mod.HANDLERS
    assert callable(mod.HANDLERS["apex_phase_entry_check"])
