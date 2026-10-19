"""Regla absoluta #18: el retrieval cross-project es obligatorio, no opcional.

La regla dice (commands/rules/absolute-rules.md:50):

    18. **Cross-project retrieval obligatorio** antes de decisiones de
    diseno/stack: `apex_search_cross_project(query)` previene repetir
    bugs vistos en otros proyectos del ecosistema.

"Obligatorio" sin maquinaria es una recomendación. Estos tests fijan la
maquinaria: el flag se escribe cuando el agente consulta el hub, y el
grader bloquea el cierre de las fases de decisión si no se consultó.

La lógica venía del commit `bce5bf6` de la rama sin fusionar.
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
from context_db import ApexContextDB  # noqa: E402
import cross_project_flag as flag  # noqa: E402
import grader as g  # noqa: E402


@pytest.fixture(scope="module")
def handlers():
    """Carga el paquete de handlers bajo el alias `apex_handlers`.

    Importarlo como `mcp.handlers` ensombrecería el SDK `mcp` y rompería
    `from mcp.types import TextContent`. Mismo truco que el servidor.
    """
    pkg = _REPO / "mcp" / "handlers"
    spec = importlib.util.spec_from_file_location(
        "apex_handlers", pkg / "__init__.py",
        submodule_search_locations=[str(pkg)],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["apex_handlers"] = mod
    raiz = str(_REPO)
    original = list(sys.path)
    for p in ("", ".", raiz):
        while p in sys.path:
            sys.path.remove(p)
    sys.path.insert(0, str(_REPO / "lib"))
    sys.path.append(raiz)
    try:
        yield mod
    finally:
        sys.path[:] = original


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


@pytest.fixture
def db(tmp_path):
    path = tmp_path / ".apex" / "context.db"
    path.parent.mkdir(parents=True)
    db = ApexContextDB(str(path))
    run(db.initialize())
    return db


class TestFasesObligatorias:
    def test_las_fases_de_decision_estan_definidas(self):
        assert flag.CROSS_PROJECT_PHASES == frozenset({0, 2, 3, 5})

    @pytest.mark.parametrize("fase", sorted(flag.CROSS_PROJECT_PHASES))
    def test_sin_consulta_bloquea(self, fase, tmp_path):
        e = g.gather_evidence(
            tmp_path, phase=fase,
            decisions_metadata={"detected_os": "Linux",
                                "hub_available": True,
                                "cross_project_consulted": False},
        )
        checks = g.run_deterministic_checks(e)
        assert checks["cross_project_consulted"] is False
        issues = g.deterministic_to_issues(checks)
        assert g.ISSUE_NO_CROSS_PROJECT in issues
        assert g.ISSUE_NO_CROSS_PROJECT in g.BLOCKING_ISSUES

    @pytest.mark.parametrize("fase", sorted(flag.CROSS_PROJECT_PHASES))
    def test_con_consulta_no_bloquea_por_eso(self, fase, tmp_path):
        e = g.gather_evidence(
            tmp_path, phase=fase,
            decisions_metadata={"detected_os": "Linux",
                                "hub_available": True,
                                "cross_project_consulted": True},
        )
        checks = g.run_deterministic_checks(e)
        assert checks["cross_project_consulted"] is True
        assert g.ISSUE_NO_CROSS_PROJECT not in g.deterministic_to_issues(checks)

    @pytest.mark.parametrize("fase", [1, 4, 6, 7, 8, 9, 10, 11])
    def test_las_fases_que_no_son_de_decision_no_lo_exigen(self, fase, tmp_path):
        e = g.gather_evidence(
            tmp_path, phase=fase,
            decisions_metadata={"detected_os": "Linux",
                                "hub_available": True,
                                "cross_project_consulted": False},
        )
        checks = g.run_deterministic_checks(e)
        assert "cross_project_consulted" not in checks

    def test_sin_hub_no_se_exige(self, tmp_path):
        """No se puede exigir lo que no se puede hacer."""
        e = g.gather_evidence(
            tmp_path, phase=3,
            decisions_metadata={"detected_os": "Linux",
                                "hub_available": False,
                                "cross_project_consulted": False},
        )
        checks = g.run_deterministic_checks(e)
        assert "cross_project_consulted" not in checks


class TestElFlag:
    def test_la_clave_es_por_fase(self):
        assert flag.meta_key(3) == "cross_project_consulted_phase_3"

    def test_registrar_y_consultar(self, db):
        assert run(flag.was_consulted(db, 5)) is False
        assert run(flag.mark_consulted(db, 5)) is True
        assert run(flag.was_consulted(db, 5)) is True

    def test_el_flag_es_por_fase(self, db):
        run(flag.mark_consulted(db, 5))
        assert run(flag.was_consulted(db, 5)) is True
        assert run(flag.was_consulted(db, 3)) is False

    def test_registrar_sin_fase_usa_la_actual(self, db):
        run(db.set_phase(4, "in_progress"))
        assert run(flag.mark_consulted(db, None)) is True
        assert run(flag.was_consulted(db, 4)) is True

    def test_registrar_sin_fase_y_sin_proyecto_no_rompe(self, db):
        # Sin fase actual, `mark_consulted` devuelve False y no lanza.
        assert run(flag.mark_consulted(db, None)) is False


class TestLosHandlersLoEscriben:
    """La búsqueda cross-project y el entry-check son las dos que cuentan."""

    def test_search_cross_project_marca_el_flag(self, handlers, db, tmp_path,
                                                 monkeypatch):
        import apex_handlers.wiki as wiki

        class _Hub:
            def exists(self):
                return True

        monkeypatch.setattr(wiki, "_search_cross_project", lambda *a, **k: {
            "errors": [{"project_id": "otro", "description": "d",
                        "lesson": "l", "severity": "high",
                        "recurrence_count": 1}],
            "decisions": [], "components": [], "hub_available": True,
        })
        # Se consulta el hub mientras se trabaja en la fase 5.
        run(db.set_phase(5, "in_progress"))
        run(wiki.handle_apex_search_cross_project(db, {"query": "memoria"}))
        assert run(flag.was_consulted(db, 5)) is True

    def test_phase_entry_check_marca_el_flag(self, handlers, db, tmp_path,
                                             monkeypatch):
        import apex_handlers.phase_gate as pg

        class _Hub:
            def exists(self):
                return True

        monkeypatch.setattr(pg, "_HUB_DB", _Hub())
        monkeypatch.setattr(pg, "search_cross_project",
                            lambda *a, **k: {"errors": [], "decisions": [],
                                             "hub_available": True})
        run(pg.handle_apex_phase_entry_check(db, {"phase": 5}))
        assert run(flag.was_consulted(db, 5)) is True
