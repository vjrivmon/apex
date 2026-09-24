"""El grader exige `detected_os` desde la fase 1 y ninguna herramienta lo escribía.

Visto en TeamLens el 24/09/2026: el check `os_detected` fallaba en todas las
fases, y la única salida era un INSERT a mano en `project_meta`. El SO lo sabe
el propio servidor MCP, que corre en la máquina de Vicente: detectarlo es
código determinista, no algo que deba acordarse de apuntar el agente.
"""
from __future__ import annotations

import asyncio
import platform

import pytest

from test_handlers_not_stubbed import handlers, run  # noqa: F401  (fixture)


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    from context_db import ApexContextDB

    raiz = tmp_path / "proyecto"
    (raiz / ".apex").mkdir(parents=True)
    monkeypatch.chdir(raiz)
    db = ApexContextDB(str(raiz / ".apex" / "context.db"))
    asyncio.run(db.initialize())
    return db


def test_iniciar_el_proyecto_apunta_el_so(handlers, proyecto):
    from apex_handlers.context import handle_apex_init_project

    run(handle_apex_init_project(proyecto, {"name": "Prueba"}))

    assert asyncio.run(proyecto.get_meta("detected_os")) == platform.system()


def test_el_grader_apunta_el_so_si_falta_y_el_check_pasa(handlers, proyecto):
    """Los proyectos iniciados antes del arreglo no tienen la meta."""
    from apex_handlers.grader import handle_apex_grader_evaluate

    salida = run(handle_apex_grader_evaluate(proyecto, {"phase": 1, "persist": False}))

    assert asyncio.run(proyecto.get_meta("detected_os")) == platform.system()
    assert '"os_detected": true' in salida[0].text
